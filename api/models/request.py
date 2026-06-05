"""
api/models/request.py
=====================
Pydantic v2 request model for the Loan Approval API.

Responsibilities:
- Define and validate all 10 loan application input fields with strict
  type constraints and value range guards
- Cross-field validation: loan_amount vs income ratio check
- Provide a to_agent_state() helper to convert the request directly into
  the LangGraph AgentState dict without manual field mapping in the route
- Produce informative validation error messages consumed by the Streamlit UI

Design decisions:
- Pydantic v2 field-level constraints (ge/le/gt) are preferred over custom
  @field_validator for simple range checks — declarative, auto-documented
- model_validator(mode="after") is used for cross-field rules so all fields
  are resolved before the cross-check fires
- employment_type is a Literal rather than an Enum so FastAPI's OpenAPI
  schema emits a string enum without a separate $ref component
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Employment type constant
# ---------------------------------------------------------------------------

EmploymentType = Literal[
    "salaried",
    "self_employed",
    "contract",
    "government",
    "unemployed",
    "student",
]


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class LoanApplicationRequest(BaseModel):
    """
    Fully validated input model for a loan application submission.

    All 10 fields are required. Value ranges align with config/rules.yaml
    and config/loan_rules.yaml thresholds so validation errors mirror the
    exact rejection criteria used downstream by agents.

    Attributes:
        applicant_id:          Unique applicant identifier (e.g. APP-2024-001)
        age:                   Applicant age in years. Must be 18–70 inclusive.
        income:                Annual gross income in INR. Must be > 0.
        employment_type:       One of six defined employment categories.
        credit_score:          CIBIL credit score. Range 300–900.
        loan_amount:           Requested loan principal in INR. Must be > 0.
        loan_tenure:           Repayment period in months. Range 6–360.
        existing_liabilities:  Current monthly debt obligations in INR. >= 0.
        location:              Applicant city or region. 1–100 characters.
        timestamp:             ISO 8601 submission timestamp string.
    """

    # ------------------------------------------------------------------
    # Field definitions with inline constraints
    # ------------------------------------------------------------------

    applicant_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique applicant identifier. Example: APP-2024-001.",
        examples=["APP-2024-001"],
    )

    age: int = Field(
        ...,
        ge=18,
        le=70,
        description=(
            "Applicant age in whole years. Must be between 18 (minimum "
            "legal age) and 70 (maximum eligible age per lending policy)."
        ),
        examples=[35],
    )

    income: float = Field(
        ...,
        gt=0,
        description=(
            "Annual gross income in INR. Must be a positive number. "
            "Self-employed applicants should declare net profit."
        ),
        examples=[800000.0],
    )

    employment_type: EmploymentType = Field(
        ...,
        description=(
            "Current employment status. Accepted values: salaried, "
            "self_employed, contract, government, unemployed, student."
        ),
        examples=["salaried"],
    )

    credit_score: int = Field(
        ...,
        ge=300,
        le=900,
        description=(
            "CIBIL credit score. Range 300–900. Scores below 500 trigger "
            "automatic rejection per credit policy."
        ),
        examples=[720],
    )

    loan_amount: float = Field(
        ...,
        gt=0,
        description=(
            "Requested loan principal in INR. Must be positive. "
            "Maximum allowable amount is INR 10,000,000."
        ),
        examples=[500000.0],
    )

    loan_tenure: int = Field(
        ...,
        ge=6,
        le=360,
        description=(
            "Requested repayment period in months. Minimum 6 months "
            "(short-term), maximum 360 months (30-year home loan)."
        ),
        examples=[36],
    )

    existing_liabilities: float = Field(
        ...,
        ge=0,
        description=(
            "Total existing monthly debt obligation in INR (EMIs, credit "
            "card minimums, rent obligations, etc.). Cannot be negative."
        ),
        examples=[15000.0],
    )

    location: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Applicant city or region. Used for area-based risk context.",
        examples=["Mumbai"],
    )

    timestamp: str = Field(
        ...,
        description=(
            "Application submission timestamp in ISO 8601 format. "
            "Example: 2024-01-15T10:30:00Z."
        ),
        examples=["2024-01-15T10:30:00Z"],
    )

    # ------------------------------------------------------------------
    # Field-level validators
    # ------------------------------------------------------------------

    @field_validator("loan_amount")
    @classmethod
    def loan_amount_within_policy_limits(cls, v: float) -> float:
        """
        Validate that loan_amount does not exceed the absolute policy maximum.

        The per-product maximum (e.g. INR 2.5M for personal loans) is enforced
        downstream by the Policy Knowledge Agent. This validator only catches
        requests that exceed the absolute system ceiling of INR 10,000,000.
        """
        max_loan = 10_000_000.0  # INR — from config/rules.yaml loan.max_amount
        if v > max_loan:
            raise ValueError(
                f"loan_amount {v:,.0f} exceeds the maximum allowable "
                f"amount of INR {max_loan:,.0f}."
            )
        return v

    @field_validator("income")
    @classmethod
    def income_meets_minimum(cls, v: float) -> float:
        """
        Validate that income meets the absolute minimum qualifying threshold.

        The minimum of INR 150,000 is defined in config/rules.yaml under
        income.min_annual_income. This guard prevents clearly ineligible
        applications from reaching the agent pipeline.
        """
        min_income = 150_000.0  # INR — from config/rules.yaml income.min_annual_income
        if v < min_income:
            raise ValueError(
                f"Annual income {v:,.0f} is below the minimum qualifying "
                f"threshold of INR {min_income:,.0f}."
            )
        return v

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_iso_format(cls, v: str) -> str:
        """
        Validate that timestamp is a non-empty string in a recognisable
        ISO 8601 format. Full parsing is intentionally lenient — agents
        only use the timestamp for audit logging, not date arithmetic.
        """
        v = v.strip()
        if not v:
            raise ValueError("timestamp must not be empty.")
        return v

    # ------------------------------------------------------------------
    # Cross-field validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def loan_amount_income_ratio(self) -> "LoanApplicationRequest":
        """
        Cross-field check: loan_amount must not exceed 3× annual income
        for unsecured loans (personal loan category).

        This mirrors the income.min_income_multiplier rule in rules.yaml.
        The check is advisory at the API layer — the Policy Knowledge Agent
        applies the precise per-product ratio. The API guard prevents
        obviously non-qualifying requests from consuming agent resources.
        """
        max_multiplier = 3  # from config/rules.yaml income.min_income_multiplier
        if self.loan_amount > self.income * max_multiplier:
            raise ValueError(
                f"loan_amount ({self.loan_amount:,.0f}) exceeds "
                f"{max_multiplier}× annual income ({self.income:,.0f}). "
                "Maximum unsecured loan is 3× annual income."
            )
        return self

    # ------------------------------------------------------------------
    # Conversion helper
    # ------------------------------------------------------------------

    def to_agent_state(self) -> dict:
        """
        Convert this request into a flat dict suitable for initialising
        the LangGraph AgentState.

        Returns a dict with all 10 input fields plus the four intermediate
        result fields (profile_result, risk_result, policy_chunks,
        decision_result) pre-set to None and control flags initialised.

        Returns:
            dict matching the AgentState TypedDict schema.

        Usage:
            state = request.to_agent_state()
            result = graph.invoke(state, config={"configurable": {"thread_id": request.applicant_id}})
        """
        return {
            # Input fields
            "applicant_id":        self.applicant_id,
            "age":                 self.age,
            "income":              self.income,
            "employment_type":     self.employment_type,
            "credit_score":        self.credit_score,
            "loan_amount":         self.loan_amount,
            "loan_tenure":         self.loan_tenure,
            "existing_liabilities": self.existing_liabilities,
            "location":            self.location,
            "timestamp":           self.timestamp,
            # Intermediate results — populated by agent nodes
            "profile_result":      None,
            "risk_result":         None,
            "policy_chunks":       None,
            "decision_result":     None,
            "audit_record":        None,
            # Output fields — populated by final nodes
            "verdict":             None,
            "confidence_score":    None,
            "explanation":         None,
            "case_id":             None,
            # Control flags
            "error":               None,
            "early_exit":          False,
        }

    model_config = {
        "json_schema_extra": {
            "example": {
                "applicant_id":        "APP-2024-001",
                "age":                 35,
                "income":              800000.0,
                "employment_type":     "salaried",
                "credit_score":        720,
                "loan_amount":         500000.0,
                "loan_tenure":         36,
                "existing_liabilities": 15000.0,
                "location":            "Mumbai",
                "timestamp":           "2024-01-15T10:30:00Z",
            }
        }
    }
