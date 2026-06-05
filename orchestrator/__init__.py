"""
orchestrator/__init__.py
========================
LangGraph orchestration package for the Loan Approval System.

Exports AgentState (always importable) and build_graph (requires langgraph).
build_graph is lazily imported so modules that only need the state schema
(e.g. tests, config checks) can import without langgraph being installed.
"""

from orchestrator.state import AgentState
from orchestrator.state import state_to_response_dict, is_state_complete


def build_graph():
    """
    Lazy wrapper — imports and calls orchestrator.graph.build_graph().

    Deferred so that importing orchestrator.state does not require
    langgraph to be installed (useful for unit tests and config validation).
    """
    from orchestrator.graph import build_graph as _build
    return _build()


__all__ = ["AgentState", "build_graph", "state_to_response_dict", "is_state_complete"]
