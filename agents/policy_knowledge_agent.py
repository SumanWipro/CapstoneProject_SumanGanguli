"""
agents/policy_knowledge_agent.py
==================================
Policy Knowledge Agent — Agent 3 of 5.

Agent Responsibility:
- Accept structured applicant risk context (credit_band, DTI, employment_band,
  loan_amount, loan_tenure, risk_flags)
- Delegate query construction and ChromaDB retrieval to rag.policy_search.search()
- Build a prompt injecting the retrieved policy chunks as context
- Call Claude Sonnet to identify which specific policy clauses apply and
  synthesise a policy_summary for the Loan Decision Agent
- Return a structured PolicyChunks dict

What this agent does NOT do:
- Does not calculate risk scores (FinancialRiskAgent)
- Does not make the final loan decision (LoanDecisionAgent)
- Does not generate Case IDs or audit records (ComplianceAgent)

Data flow:
    RiskAgentOutput + ProfileAgentOutput
        → PolicyAgentInput
        → rag.policy_search.search()       (ChromaDB retrieval)
        → build_prompt()                   (inject chunks into template)
        → call_claude()                    (Claude Sonnet reasoning)
        → parse_json_response()            (extract structured output)
        → PolicyChunks                     (returned to orchestrator node)
"""

from __future__ import annotations

from typing import Any

from agents.base_agent import BaseAgent
from orchestrator.state import PolicyChunks
from rag.policy_search import search as policy_search
from utils.logger import get_logger

log = get_logger(__name__, component="policy_knowledge_agent")


class PolicyKnowledgeAgent(BaseAgent):
    """
    Retrieves relevant loan policy context using RAG + Claude Sonnet.

    Inherits from BaseAgent:
        build_prompt(**kwargs)     — renders prompts/policy_knowledge.txt
        call_claude(prompt)        — invokes Bedrock with retry
        parse_json_response(raw)   — extracts JSON from Claude's reply

    Prompt file: prompts/policy_knowledge.txt
    Input model: api.models.agents.PolicyAgentInput
    Returns:     orchestrator.state.PolicyChunks TypedDict
    """

    prompt_file = "policy_knowledge.txt"

    def invoke(self, payload: dict[str, Any]) -> PolicyChunks:
        """
        Retrieve applicable policy context and return a PolicyChunks dict.

        Execution steps:
            1. Extract context fields from payload
            2. Call rag.policy_search.search() to retrieve and filter chunks
            3. Build the LLM prompt by injecting chunks into the template
            4. Call Claude Sonnet to reason over the policy text
            5. Parse Claude's JSON response into a PolicyChunks structure

        Args:
            payload: Dict matching PolicyAgentInput schema:
                - credit_band     (str)       — from RiskAgentOutput
                - dti             (float)      — from RiskAgentOutput
                - employment_band (str)       — from ProfileAgentOutput
                - loan_amount     (float)     — from LoanApplicationRequest
                - loan_tenure     (int)       — from LoanApplicationRequest
                - risk_flags      (list[str]) — from RiskAgentOutput
                - top_k           (int)       — optional, default 5

        Returns:
            PolicyChunks TypedDict with keys:
                - chunks             (list[str]) — raw policy text segments
                - sources            (list[str]) — source document names
                - applicable_clauses (list[str]) — Claude-identified clauses
                - policy_summary     (str)       — one-paragraph synthesis

        Raises:
            ValueError:          If ChromaDB collection not populated.
            json.JSONDecodeError: If Claude returns malformed JSON.
            ClientError:          If Bedrock call fails after 3 retries.
        """
        # ------------------------------------------------------------------
        # Step 1: Extract fields from payload
        # ------------------------------------------------------------------
        credit_band     = str(payload.get("credit_band", "fair"))
        dti             = float(payload.get("dti", 0.0))
        employment_band = str(payload.get("employment_band", "stable"))
        loan_amount     = float(payload.get("loan_amount", 0.0))
        loan_tenure     = int(payload.get("loan_tenure", 12))
        risk_flags      = list(payload.get("risk_flags", []))
        top_k           = int(payload.get("top_k", self.settings.rag_top_k))

        log.info(
            "policy_knowledge_agent_invoked",
            credit_band=credit_band,
            dti=round(dti, 4),
            employment_band=employment_band,
            loan_amount=loan_amount,
            top_k=top_k,
        )

        # ------------------------------------------------------------------
        # Step 2: Retrieve policy chunks via RAG
        # ------------------------------------------------------------------
        search_result = policy_search(
            credit_band=credit_band,
            dti=dti,
            employment_band=employment_band,
            loan_amount=loan_amount,
            loan_tenure=loan_tenure,
            risk_flags=risk_flags,
            top_k=top_k,
        )

        formatted_chunks = search_result["formatted_text"]
        retrieved_sources = search_result["sources"]
        raw_chunk_texts = [
            c["text"] for c in search_result["filtered_chunks"]
        ]

        log.info(
            "rag_retrieval_complete",
            chunks_used=search_result["chunks_used"],
            sources=retrieved_sources,
        )

        # ------------------------------------------------------------------
        # Step 3: Build the LLM prompt
        # ------------------------------------------------------------------
        prompt = self.build_prompt(
            credit_band=credit_band,
            dti=f"{dti:.4f}",
            employment_band=employment_band,
            loan_amount=f"{loan_amount:,.0f}",
            loan_tenure=str(loan_tenure),
            risk_flags=", ".join(risk_flags) if risk_flags else "none",
            policy_chunks=formatted_chunks,
        )

        # ------------------------------------------------------------------
        # Step 4: Call Claude Sonnet
        # ------------------------------------------------------------------
        raw_response = self.call_claude(prompt)

        # ------------------------------------------------------------------
        # Step 5: Parse structured JSON response
        # ------------------------------------------------------------------
        parsed = self.parse_json_response(raw_response)

        # Build PolicyChunks — Claude adds applicable_clauses and policy_summary;
        # we preserve the raw retrieved chunks and sources from the RAG step
        result: PolicyChunks = {
            "chunks":             raw_chunk_texts,
            "sources":            list(set(
                retrieved_sources + parsed.get("sources", [])
            )),
            "applicable_clauses": parsed.get("applicable_clauses", []),
            "policy_summary":     parsed.get("policy_summary", ""),
        }

        log.info(
            "policy_knowledge_agent_complete",
            clauses_found=len(result["applicable_clauses"]),
            sources=result["sources"],
            summary_chars=len(result.get("policy_summary", "")),
        )

        return result
