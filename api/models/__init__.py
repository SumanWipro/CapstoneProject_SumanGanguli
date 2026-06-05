"""
api/models/__init__.py
======================
Pydantic models package for the Loan Approval API.

Exports all request, response, and agent I/O models so that routes,
tests, and MCP tools import from a single namespace:

    from api.models import LoanApplicationRequest, LoanDecisionResponse
    from api.models import ProfileAgentInput, ProfileAgentOutput
"""

# Request models
from api.models.request import LoanApplicationRequest, EmploymentType

# Response models
from api.models.response import (
    LoanDecisionResponse,
    AgentTraceResponse,
    AgentTrace,
    ErrorResponse,
    HealthResponse,
    VerdictType,
)

# Agent I/O models
from api.models.agents import (
    ProfileAgentInput,
    ProfileAgentOutput,
    RiskAgentInput,
    RiskAgentOutput,
    PolicyAgentInput,
    PolicyAgentOutput,
    DecisionAgentInput,
    DecisionAgentOutput,
    ComplianceAgentInput,
    ComplianceAgentOutput,
)

__all__ = [
    # Request
    "LoanApplicationRequest",
    "EmploymentType",
    # Response
    "LoanDecisionResponse",
    "AgentTraceResponse",
    "AgentTrace",
    "ErrorResponse",
    "HealthResponse",
    "VerdictType",
    # Agent I/O
    "ProfileAgentInput",
    "ProfileAgentOutput",
    "RiskAgentInput",
    "RiskAgentOutput",
    "PolicyAgentInput",
    "PolicyAgentOutput",
    "DecisionAgentInput",
    "DecisionAgentOutput",
    "ComplianceAgentInput",
    "ComplianceAgentOutput",
]
