"""
agents/__init__.py
==================
Agent package for the Loan Approval System.

All five agents extend BaseAgent and are registered here for easy import
by the MCP tool layer.
"""

from agents.base_agent import BaseAgent
from agents.applicant_profile_agent import ApplicantProfileAgent
from agents.financial_risk_agent import FinancialRiskAgent
from agents.policy_knowledge_agent import PolicyKnowledgeAgent
from agents.loan_decision_agent import LoanDecisionAgent
from agents.compliance_agent import ComplianceAgent

__all__ = [
    "BaseAgent",
    "ApplicantProfileAgent",
    "FinancialRiskAgent",
    "PolicyKnowledgeAgent",
    "LoanDecisionAgent",
    "ComplianceAgent",
]
