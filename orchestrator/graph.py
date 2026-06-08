"""
orchestrator/graph.py
=====================
LangGraph StateGraph builder for the Loan Approval pipeline.

Responsibilities:
- Register all 8 node functions from orchestrator/nodes.py
- Define sequential and conditional edges
- Implement _profile_gate — the conditional router after profile validation
- Attach MemorySaver checkpointer for state persistence and observability
- Compile and return the runnable graph via build_graph()

Graph topology:
    START
      │
    validate_input
      │
    applicant_profile_node
      │
      ├─(profile valid)──────────────► financial_risk_node
      │                                       │
      │                               policy_knowledge_node
      │                                       │
        │                               loan_decision_node
        │                                       │
        │                                review_action_node
        │                                       │
        └─(profile invalid)──► early_rejection_node
                                                    │
                                          review_action_node
                                                    │
                                                compliance_node
                                       │
                                      END

Design decisions:
- MemorySaver checkpointer: stores intermediate state after each node.
  The Streamlit workflow page reads checkpointed state to visualise
  node-by-node execution. Replace with SqliteSaver/PostgresSaver for
  multi-process or persistent deployments.
- Conditional edge _profile_gate: checks both early_exit flag (set by
    validate_input_node) and profile_result.completeness_flags (set by profile agent).
  Two conditions because validate_input_node can set early_exit without
  a profile_result being present.
- The graph is compiled once at API startup (via lifespan in api/main.py)
  and reused across all requests. build_graph() is idempotent.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.state import AgentState
from orchestrator import nodes
from utils.logger import get_logger

log = get_logger(__name__, component="graph_builder")


# ===========================================================================
# Conditional edge router
# ===========================================================================

def _profile_gate(
    state: AgentState,
) -> Literal["financial_risk_node", "early_rejection_node"]:
    """
    Route the graph after applicant_profile_node executes.

    Routing logic (checked in order):
        1. If early_exit == True  → early_rejection_node
           (set by validate_input_node for missing fields or age out-of-range,
            or by applicant_profile_node when completeness_flags is non-empty)
        2. If profile_result is missing (node errored) → early_rejection_node
        3. If profile_result.completeness_flags is non-empty → early_rejection_node
        4. Otherwise → financial_risk_node

    Why check early_exit first:
        validate_input_node runs before applicant_profile_node. If it sets
        early_exit=True, profile_result will not be present. Checking early_exit
        first avoids a KeyError on profile_result.

    Args:
        state: Current AgentState after applicant_profile_node has run.

    Returns:
        "financial_risk_node"  — continue full pipeline
        "early_rejection_node" — bypass risk/policy/decision agents
    """
    # Condition 1: explicit early_exit flag
    if state.get("early_exit", False):
        log.info(
            "profile_gate_early_exit",
            applicant_id=state.get("applicant_id"),
            reason=state.get("error", "early_exit_flag_set"),
        )
        return "early_rejection_node"

    # Condition 2 & 3: profile_result absent or has completeness issues
    profile_result = state.get("profile_result")
    if profile_result is None or (profile_result or {}).get("completeness_flags", []):
        flags = (profile_result or {}).get("completeness_flags", [])
        log.info(
            "profile_gate_invalid_profile",
            applicant_id=state.get("applicant_id"),
            flags=flags,
        )
        return "early_rejection_node"

    # Happy path
    log.info(
        "profile_gate_proceed",
        applicant_id=state.get("applicant_id"),
        employment_risk=profile_result.get("employment_risk"),
    )
    return "financial_risk_node"


# ===========================================================================
# Graph builder
# ===========================================================================

def build_graph():
    """
    Build, compile, and return the LoanApproval StateGraph.

    Registers all nodes, wires all edges (sequential + conditional), attaches
    a MemorySaver checkpointer, and compiles the graph into a runnable.

    Returns:
        Compiled LangGraph runnable. Accepts AgentState as input via .invoke()
        or .stream(). Thread-safe for concurrent requests when each request
        uses a unique thread_id in the config.

    Usage:
        graph = build_graph()

        # Invoke synchronously
        result = graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": applicant_id}},
        )

        # Stream node-by-node (for Streamlit workflow page)
        for chunk in graph.stream(initial_state, config=...):
            print(chunk)
    """
    log.info("building_langgraph_pipeline")

    builder = StateGraph(AgentState)

    # -----------------------------------------------------------------------
    # Register nodes — order of registration does not affect execution order;
    # edges define the execution sequence.
    # -----------------------------------------------------------------------
    builder.add_node("validate_input",         nodes.validate_input_node)
    builder.add_node("applicant_profile_node", nodes.applicant_profile_node)
    builder.add_node("financial_risk_node",    nodes.financial_risk_node)
    builder.add_node("policy_knowledge_node",  nodes.policy_knowledge_node)
    builder.add_node("loan_decision_node",     nodes.loan_decision_node)
    builder.add_node("review_action_node",     nodes.review_action_node)
    builder.add_node("compliance_node",        nodes.compliance_node)
    builder.add_node("early_rejection_node",   nodes.early_rejection_node)

    # -----------------------------------------------------------------------
    # Entry point
    # -----------------------------------------------------------------------
    builder.set_entry_point("validate_input")

    # -----------------------------------------------------------------------
    # Sequential edges (unconditional)
    # -----------------------------------------------------------------------
    builder.add_edge("validate_input",        "applicant_profile_node")
    builder.add_edge("financial_risk_node",   "policy_knowledge_node")
    builder.add_edge("policy_knowledge_node", "loan_decision_node")
    builder.add_edge("loan_decision_node",    "review_action_node")
    builder.add_edge("early_rejection_node",  "review_action_node")
    builder.add_edge("review_action_node",    "compliance_node")
    builder.add_edge("compliance_node",       END)

    # -----------------------------------------------------------------------
    # Conditional edge: profile_gate after applicant_profile_node
    # -----------------------------------------------------------------------
    builder.add_conditional_edges(
        "applicant_profile_node",   # source node
        _profile_gate,              # router function
        {
            "financial_risk_node":  "financial_risk_node",
            "early_rejection_node": "early_rejection_node",
        },
    )

    # -----------------------------------------------------------------------
    # Checkpointer: MemorySaver for in-process state snapshots
    # Enables graph.stream() for the Streamlit workflow visualisation page
    # and graph.get_state() for post-hoc inspection.
    # -----------------------------------------------------------------------
    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    log.info(
        "langgraph_pipeline_compiled",
        nodes=list(builder.nodes.keys()) if hasattr(builder, "nodes") else "8 nodes",
    )
    return graph
