"""
start_mcp_server.py
===================
FastAPI-based MCP tool server for the Loan Approval System.

Replaces the FastMCP SSE server because fastmcp 0.4.1 only supports stdio/SSE
transports, while the orchestrator's MCPClient expects:
  - POST /mcp          — JSON-RPC 2.0 (tools/call method)
  - POST /tools/{name} — REST-style fallback

This script exposes both endpoint patterns on port settings.mcp_port.
Tools are loaded directly by file path to avoid the project mcp/ package
shadowing the installed mcp library.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# sys.path: project root first (no mcp package namespace conflict here
# because we load tools by file path, not via import mcp.tools.*)
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _load(alias: str, rel_path: str):
    """Load a module by file path under a private alias to avoid name clashes."""
    path = os.path.join(_HERE, rel_path)
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Load project tool modules directly (bypasses mcp.* package namespace)
# ---------------------------------------------------------------------------
_pt  = _load("_lt_profile",  "mcp/tools/profile_tools.py")
_rt  = _load("_lt_risk",     "mcp/tools/risk_tools.py")
_pol = _load("_lt_policy",   "mcp/tools/policy_tools.py")
_dt  = _load("_lt_decision", "mcp/tools/decision_tools.py")
_rev = _load("_lt_review",   "mcp/tools/review_action_tools.py")
_ct  = _load("_lt_audit",    "mcp/tools/compliance_tools.py")

# ---------------------------------------------------------------------------
# Tool dispatch table
# ---------------------------------------------------------------------------
_TOOLS: dict[str, Any] = {
    "validate_profile":          _pt.validate_profile,
    "calculate_risk":            _rt.calculate_risk,
    "query_policy":              _pol.query_policy,
    "generate_decision":         _dt.generate_decision,
    "orchestrate_review_action": _rev.orchestrate_review_action,
    "create_audit":              _ct.create_audit,
}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
from fastapi import FastAPI, HTTPException, Path as FPath
from fastapi.responses import JSONResponse
import uvicorn

from config.settings import get_settings
from utils.logger import get_logger

log      = get_logger(__name__, component="mcp_server")
settings = get_settings()

app = FastAPI(title="LoanApprovalMCPServer", version="1.0.0")


# --- JSON-RPC 2.0 endpoint (primary path used by MCPClient) ----------------

@app.post("/mcp")
async def mcp_jsonrpc(body: dict) -> JSONResponse:
    """Handle JSON-RPC 2.0 tools/call requests."""
    rpc_id = body.get("id")
    method = body.get("method", "")
    if method != "tools/call":
        return JSONResponse(
            {"jsonrpc": "2.0", "id": rpc_id,
             "error": {"code": -32601, "message": f"Method not found: {method}"}},
            status_code=200,
        )
    params    = body.get("params", {})
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    fn = _TOOLS.get(tool_name)
    if fn is None:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": rpc_id,
             "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"}},
            status_code=200,
        )
    try:
        result = fn(arguments)
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})
    except Exception as exc:
        log.error("tool_error", tool=tool_name, error=str(exc))
        return JSONResponse(
            {"jsonrpc": "2.0", "id": rpc_id,
             "error": {"code": -32000, "message": str(exc)}},
            status_code=200,
        )


# --- REST fallback endpoint -------------------------------------------------

@app.post("/tools/{tool_name}")
async def call_tool_rest(
    tool_name: str = FPath(..., description="MCP tool name"),
    body: dict = None,
) -> JSONResponse:
    """REST-style fallback: POST /tools/{tool_name} with payload as body."""
    fn = _TOOLS.get(tool_name)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    try:
        result = fn(body or {})
        return JSONResponse(result)
    except Exception as exc:
        log.error("tool_error", tool=tool_name, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# --- Health endpoint --------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "tools": list(_TOOLS.keys())}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info(
        "starting_mcp_server",
        host=settings.mcp_host,
        port=settings.mcp_port,
    )
    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
    )
