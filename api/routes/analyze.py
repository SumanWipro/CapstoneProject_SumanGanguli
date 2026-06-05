"""
api/routes/analyze.py
=====================
POST /api/v1/analyze — Loan application analysis endpoint.

Responsibilities:
- Accept and validate a LoanApplicationRequest via Pydantic
- Convert it to an initial AgentState via request.to_agent_state()
- Invoke the pre-compiled LangGraph graph from app.state.graph
- Extract the final AgentState and build a LoanDecisionResponse
- Handle pipeline errors gracefully with structured ErrorResponse

Design decision — graph stored on app.state:
    The LangGraph graph is compiled once in api/main.py lifespan() and
    stored on app.state.graph. Routes access it via the FastAPI Request
    object. This avoids recompiling the graph on every request (expensive)
    and keeps the route function thin — pure HTTP ↔ domain translation.

Thread safety:
    LangGraph with MemorySaver is safe for concurrent requests as long as
    each request uses a unique thread_id in the config. We use applicant_id
    as the thread_id so checkpointed state is scoped to one application.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from api.models.request import LoanApplicationRequest
from api.models.response import LoanDecisionResponse, ErrorResponse
from orchestrator.state import state_to_response_dict, is_state_complete
from utils.logger import get_logger

log = get_logger(__name__, component="analyze_route")

router = APIRouter(tags=["Loan Analysis"])


@router.post(
    "/analyze",
    response_model=LoanDecisionResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Internal processing error"},
    },
    summary="Analyse a loan application",
    description=(
        "Submit a loan application for multi-agent AI analysis. "
        "Returns APPROVED, REJECTED, or REVIEW_REQUIRED with a confidence "
        "score, plain-English explanation, and audit Case ID."
    ),
)
async def analyze_loan_application(
    request: Request,
    payload: LoanApplicationRequest,
) -> LoanDecisionResponse:
    """
    Invoke the LangGraph pipeline and return a loan decision.

    Steps:
        1. Convert validated payload to initial AgentState
        2. Retrieve the pre-compiled graph from app.state
        3. Invoke the graph with a unique thread_id config
        4. Extract final state and build LoanDecisionResponse

    Args:
        request: FastAPI Request (carries app.state.graph).
        payload: Validated LoanApplicationRequest (Pydantic-checked).

    Returns:
        LoanDecisionResponse with verdict, confidence_score, explanation,
        case_id, notification_summary, and risk metadata.

    Raises:
        HTTPException 503: If the graph has not been initialised.
        HTTPException 500: If the pipeline raises an unexpected error.
    """
    applicant_id = payload.applicant_id

    log.info(
        "analyze_request_received",
        applicant_id=applicant_id,
        loan_amount=payload.loan_amount,
        employment_type=payload.employment_type,
    )

    # ------------------------------------------------------------------
    # Step 1: Get the pre-compiled graph from app.state
    # ------------------------------------------------------------------
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        log.error("graph_not_initialised")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LangGraph pipeline not initialised. Retry in a moment.",
        )

    # ------------------------------------------------------------------
    # Step 2: Convert request to initial AgentState
    # ------------------------------------------------------------------
    initial_state = payload.to_agent_state()

    # ------------------------------------------------------------------
    # Step 3: Invoke the LangGraph pipeline
    # Each request uses applicant_id as thread_id for isolated checkpoints
    # ------------------------------------------------------------------
    thread_id = f"{applicant_id}-{uuid.uuid4().hex[:8]}"
    config    = {"configurable": {"thread_id": thread_id}}

    try:
        final_state = graph.invoke(initial_state, config=config)

        log.info(
            "pipeline_completed",
            applicant_id=applicant_id,
            verdict=final_state.get("verdict"),
            case_id=final_state.get("case_id"),
            thread_id=thread_id,
        )

    except Exception as exc:
        log.error(
            "pipeline_error",
            applicant_id=applicant_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {type(exc).__name__}",
        )

    # ------------------------------------------------------------------
    # Step 4: Build and return LoanDecisionResponse
    # ------------------------------------------------------------------
    if not is_state_complete(final_state):
        log.warning(
            "pipeline_incomplete_state",
            applicant_id=applicant_id,
            verdict=final_state.get("verdict"),
            case_id=final_state.get("case_id"),
        )

    response_data = state_to_response_dict(final_state)

    return LoanDecisionResponse(**response_data)
