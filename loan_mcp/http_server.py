"""
loan_mcp/http_server.py
=======================
Thin FastAPI HTTP server that exposes MCP tools over REST.
The orchestrator's MCPClient falls back to POST /tools/{tool_name}
when the JSON-RPC /mcp endpoint is unavailable.
"""

from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from config.settings import get_settings
from loan_mcp.tools.profile_tools import validate_profile
from loan_mcp.tools.risk_tools import calculate_risk
from loan_mcp.tools.policy_tools import query_policy
from loan_mcp.tools.decision_tools import generate_decision
from loan_mcp.tools.review_action_tools import orchestrate_review_action
from loan_mcp.tools.compliance_tools import create_audit

settings = get_settings()

app = FastAPI(title="LoanApprovalMCPServer")

_TOOLS: dict[str, Any] = {
    "validate_profile": validate_profile,
    "calculate_risk": calculate_risk,
    "query_policy": query_policy,
    "generate_decision": generate_decision,
    "orchestrate_review_action": orchestrate_review_action,
    "create_audit": create_audit,
}


@app.post("/tools/{tool_name}")
async def call_tool(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    fn = _TOOLS.get(tool_name)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return fn(payload)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "tools": list(_TOOLS)}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
