"""
api/main.py
===========
FastAPI application factory for the Loan Approval System.

Responsibilities:
- Create the FastAPI app with metadata, middleware, and routers
- Pre-warm the LangGraph graph at startup and store it on app.state
- Provide a /health endpoint that checks both API and RAG layer readiness
- Expose the `app` object for Uvicorn

Design decisions:
- App factory pattern (create_app()): allows test suite to create isolated
  app instances without side effects from middleware or graph initialisation.
- Graph stored on app.state: compiled once, shared across all requests.
  Avoids recompiling the StateGraph (which re-registers all nodes and edges)
  on every HTTP request.
- /health checks both service liveness and ChromaDB readiness so the
  Streamlit dashboard can display RAG layer status without a separate call.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import analyze
from api.middleware.logging_middleware import LoggingMiddleware
from api.middleware.error_middleware import register_error_handlers
from api.models.response import HealthResponse
from config.settings import get_settings
from utils.logger import get_logger

log      = get_logger(__name__, component="api_main")
settings = get_settings()


def _mcp_server_ready() -> bool:
    """
    Return True if the MCP server is reachable.

    Uses a lightweight HTTP GET against the MCP base URL. Any network
    or HTTP failure is treated as not ready.
    """
    try:
        timeout = max(1.0, min(settings.mcp_client_timeout_seconds, 5.0))
        resp = httpx.get(settings.mcp_client_base_url, timeout=timeout)
        return resp.status_code < 500
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Lifespan: startup and shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager — runs startup code, then yields,
    then runs shutdown code.

    Startup:
        1. Build and compile the LangGraph StateGraph
        2. Store the compiled graph on app.state.graph
        3. Log service start with configuration summary

    Shutdown:
        1. Log graceful shutdown

    Why pre-warm at startup:
        Compiling the LangGraph graph (node registration, edge wiring,
        checkpointer attachment) is a one-time cost of ~100ms. Pre-warming
        at startup means the first request is not penalised by this overhead.
    """
    # ── Startup ──────────────────────────────────────────────────────────
    log.info(
        "loan_approval_api_starting",
        host=settings.api_host,
        port=settings.api_port,
        version=settings.api_version,
        model=settings.bedrock_model_id,
        mcp_base_url=settings.mcp_client_base_url,
    )

    try:
        # Import here (not at module level) to avoid circular imports
        # and to defer langgraph import until the server actually starts
        from orchestrator.graph import build_graph
        graph = build_graph()
        app.state.graph = graph
        log.info("langgraph_graph_ready")
    except Exception as exc:
        log.error("langgraph_graph_failed", error=str(exc))
        # Store None — the /analyze route handles the missing graph gracefully
        app.state.graph = None

    mcp_ready = _mcp_server_ready()
    app.state.mcp_ready = mcp_ready
    if mcp_ready:
        log.info("mcp_server_ready", mcp_base_url=settings.mcp_client_base_url)
    else:
        log.warning("mcp_server_unreachable", mcp_base_url=settings.mcp_client_base_url)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    log.info("loan_approval_api_shutdown")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """
    Create, configure, and return the FastAPI application instance.

    Registers:
        - CORS middleware (allows Streamlit UI origin)
        - Request/response logging middleware
        - Global exception handlers
        - /api/v1/ router (analyze endpoint)
        - /health liveness + readiness probe

    Returns:
        Configured FastAPI instance ready for Uvicorn.
    """
    app = FastAPI(
        title="Loan Approval System API",
        description=(
            "Agentic AI Loan Approval System — multi-agent pipeline "
            "powered by LangGraph, FastMCP, and Claude Sonnet on AWS Bedrock."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS: allow Streamlit UI and local development ───────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://localhost:{settings.streamlit_port}",
            "http://localhost:8501",
            "http://127.0.0.1:8501",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request/response structured logging ──────────────────────────────
    app.add_middleware(LoggingMiddleware)

    # ── Global error handlers (ValidationError → 422, Exception → 500) ──
    register_error_handlers(app)

    # ── API router (versioned) ────────────────────────────────────────────
    app.include_router(
        analyze.router,
        prefix=f"/api/{settings.api_version}",
    )

    # ── Health endpoint ───────────────────────────────────────────────────

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["Health"],
        summary="Liveness and readiness probe",
        description=(
            "Returns service status and ChromaDB collection readiness. "
            "Status 'ok' means both API and RAG layer are ready. "
            "Status 'degraded' means the API is up but ChromaDB is not populated."
        ),
    )
    async def health_check() -> HealthResponse:
        """
        Liveness + readiness probe.

        Checks:
            1. API is reachable (always true if this endpoint responds)
            2. LangGraph graph is compiled (app.state.graph is not None)
            3. ChromaDB collection is populated (via collection_health_check)
            4. MCP server is reachable

        Returns:
            HealthResponse with status "ok" or "degraded".
        """
        graph_ready = getattr(app.state, "graph", None) is not None
        mcp_ready = _mcp_server_ready()
        app.state.mcp_ready = mcp_ready

        try:
            from rag.retriever import collection_health_check
            rag_health = collection_health_check()
            rag_status = rag_health.get("status", "missing")
        except Exception:
            rag_status = "missing"

        if graph_ready and rag_status == "ready" and mcp_ready:
            status_val = "ok"
        else:
            status_val = "degraded"

        log.debug(
            "health_check",
            graph_ready=graph_ready,
            rag_status=rag_status,
            mcp_ready=mcp_ready,
            status=status_val,
        )

        return HealthResponse(
            status=status_val,
            service="loan-approval-api",
            version="1.0.0",
        )

    return app


# ---------------------------------------------------------------------------
# Module-level app instance (used by Uvicorn)
# ---------------------------------------------------------------------------

app = create_app()
