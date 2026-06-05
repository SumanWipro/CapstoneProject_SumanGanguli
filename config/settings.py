"""
config/settings.py
==================
Central configuration loader for the Loan Approval System.

Responsibilities:
- Load all environment variables from .env via pydantic-settings
- Parse config/rules.yaml into Settings.rules (core business rules)
- Parse config/loan_rules.yaml into Settings.loan_rules (extended rules)
- Parse config/logging_config.yaml into Settings.logging_config
- Expose a singleton get_settings() accessor consumed by every module

Design decisions:
- pydantic-settings BaseSettings handles env var loading, type coercion,
  and validation — no manual os.environ access anywhere in the codebase
- YAML files hold business rules and logging config separately from env vars
  because they change on different cadences (rules change with policy;
  env vars change with deployment environment)
- lru_cache(maxsize=1) makes get_settings() a process-wide singleton so
  YAML is parsed exactly once per process, not once per import

Module contract:
    from config.settings import get_settings
    settings = get_settings()
    region     = settings.aws_region
    dti_limit  = settings.rules["debt_to_income"]["auto_reject_above"]
    top_k      = settings.loan_rules["agents"]["rag"]["top_k_chunks"]
    log_level  = settings.log_level
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_BASE_DIR    = Path(__file__).resolve().parent.parent
_RULES_PATH  = _BASE_DIR / "config" / "rules.yaml"
_LOAN_RULES_PATH = _BASE_DIR / "config" / "loan_rules.yaml"
_LOG_CFG_PATH    = _BASE_DIR / "config" / "logging_config.yaml"


# ---------------------------------------------------------------------------
# YAML loaders (module-level, called once during Settings construction)
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    """
    Safely load a YAML file and return its contents as a dict.

    Returns an empty dict if the file does not exist so that the app
    can start in environments where config files are partially absent
    (e.g. running a single unit test that only needs env vars).

    Args:
        path: Absolute Path to the YAML file.

    Returns:
        Parsed YAML as a dict, or {} if the file is missing or empty.
    """
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_rules() -> dict[str, Any]:
    """Load config/rules.yaml — core business thresholds."""
    return _load_yaml(_RULES_PATH)


def _load_loan_rules() -> dict[str, Any]:
    """Load config/loan_rules.yaml — extended loan rules and agent config."""
    return _load_yaml(_LOAN_RULES_PATH)


def _load_logging_config() -> dict[str, Any]:
    """Load config/logging_config.yaml — per-module logging settings."""
    return _load_yaml(_LOG_CFG_PATH)


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """
    Application-wide settings for the Loan Approval System.

    All environment-variable fields have safe defaults so the app starts
    without a .env file in development. Production deployments must
    supply valid AWS credentials and override defaults as needed.

    YAML-backed fields (rules, loan_rules, logging_config) are populated
    in model_post_init after all env vars have been resolved.

    Attribute groups:
        AWS / Bedrock  — credentials and model selection
        FastAPI        — gateway host, port, versioning
        FastMCP        — MCP server host and port
        Streamlit      — UI port and gateway URL
        ChromaDB       — vector store path and collection name
        Logging        — log level and format
        Audit          — audit log directory
        YAML rules     — parsed business rule trees (not from env vars)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",             # silently ignore unknown env vars
        case_sensitive=False,       # AWS_REGION and aws_region both work
    )

    # ------------------------------------------------------------------
    # AWS / Bedrock
    # ------------------------------------------------------------------

    aws_access_key_id: str = Field(
        default="",
        description="AWS access key ID for Bedrock authentication.",
    )
    aws_secret_access_key: str = Field(
        default="",
        description="AWS secret access key for Bedrock authentication.",
    )
    aws_region: str = Field(
        default="us-east-1",
        description="AWS region where the Bedrock endpoint is located.",
    )
    bedrock_model_id: str = Field(
        default="anthropic.claude-sonnet-4-5",
        description=(
            "Bedrock model ID for Claude Sonnet. "
            "Example: anthropic.claude-sonnet-4-5"
        ),
    )

    # ------------------------------------------------------------------
    # FastAPI Gateway
    # ------------------------------------------------------------------

    api_host: str = Field(
        default="0.0.0.0",
        description="FastAPI bind host. 0.0.0.0 for all interfaces.",
    )
    api_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="FastAPI listen port.",
    )
    api_version: str = Field(
        default="v1",
        description="API version prefix used in route paths (e.g. /api/v1/).",
    )

    # ------------------------------------------------------------------
    # FastMCP Server
    # ------------------------------------------------------------------

    mcp_host: str = Field(
        default="0.0.0.0",
        description="FastMCP server bind host.",
    )
    mcp_port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="FastMCP server listen port.",
    )

    # ------------------------------------------------------------------
    # Streamlit UI
    # ------------------------------------------------------------------

    streamlit_port: int = Field(
        default=8501,
        ge=1,
        le=65535,
        description="Streamlit server listen port.",
    )
    fastapi_base_url: str = Field(
        default="http://localhost:8000",
        description=(
            "Base URL of the FastAPI gateway as seen from the Streamlit UI. "
            "Must not have a trailing slash."
        ),
    )

    # ------------------------------------------------------------------
    # ChromaDB
    # ------------------------------------------------------------------

    chroma_persist_dir: str = Field(
        default="./chroma_db",
        description=(
            "Directory where ChromaDB persists its vector store to disk. "
            "Created automatically if it does not exist."
        ),
    )
    chroma_collection_name: str = Field(
        default="loan_policy_docs",
        description="Name of the ChromaDB collection for policy documents.",
    )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    log_level: str = Field(
        default="INFO",
        description=(
            "Minimum log level. One of: DEBUG, INFO, WARNING, ERROR, CRITICAL. "
            "Case-insensitive."
        ),
    )
    log_format: str = Field(
        default="json",
        description=(
            "Log output format. 'json' for structured production logs; "
            "'console' for human-readable development output."
        ),
    )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    audit_log_dir: str = Field(
        default="./audit/logs",
        description=(
            "Directory where compliance audit JSONL files are written. "
            "One file per day: YYYY-MM-DD.jsonl."
        ),
    )

    # ------------------------------------------------------------------
    # YAML-backed rule trees (not from env vars — populated in post_init)
    # ------------------------------------------------------------------

    rules: dict = Field(
        default_factory=dict,
        description="Parsed contents of config/rules.yaml.",
        exclude=True,               # exclude from .env serialisation
    )
    loan_rules: dict = Field(
        default_factory=dict,
        description="Parsed contents of config/loan_rules.yaml.",
        exclude=True,
    )
    logging_config: dict = Field(
        default_factory=dict,
        description="Parsed contents of config/logging_config.yaml.",
        exclude=True,
    )

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        """Normalise log level to uppercase and validate it is a known level."""
        upper = v.upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if upper not in valid:
            raise ValueError(
                f"log_level '{v}' is not valid. Must be one of: {sorted(valid)}"
            )
        return upper

    @field_validator("log_format")
    @classmethod
    def normalise_log_format(cls, v: str) -> str:
        """Normalise log format to lowercase and validate."""
        lower = v.lower()
        if lower not in {"json", "console"}:
            raise ValueError(
                f"log_format '{v}' is not valid. Must be 'json' or 'console'."
            )
        return lower

    @field_validator("fastapi_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        """Remove trailing slash from base URL to prevent double-slash in paths."""
        return v.rstrip("/")

    # ------------------------------------------------------------------
    # Post-init: load YAML config trees
    # ------------------------------------------------------------------

    def model_post_init(self, __context: object) -> None:
        """
        Load all YAML configuration files after env vars are resolved.

        Called automatically by Pydantic v2 after __init__ completes.
        Populates rules, loan_rules, and logging_config from their
        respective YAML files.
        """
        # Use object.__setattr__ to bypass Pydantic's immutability
        # (fields with default_factory are mutable; this is safe)
        object.__setattr__(self, "rules", _load_rules())
        object.__setattr__(self, "loan_rules", _load_loan_rules())
        object.__setattr__(self, "logging_config", _load_logging_config())

    # ------------------------------------------------------------------
    # Convenience accessors for deeply nested rule values
    # ------------------------------------------------------------------

    @property
    def dti_auto_reject_threshold(self) -> float:
        """
        DTI value above which a loan application is automatically rejected.

        Returns:
            float from rules.debt_to_income.auto_reject_above, or 0.60 fallback.
        """
        return float(
            self.rules.get("debt_to_income", {}).get("auto_reject_above", 0.60)
        )

    @property
    def credit_score_auto_reject_threshold(self) -> int:
        """
        CIBIL credit score below which a loan application is automatically rejected.

        Returns:
            int from rules.credit_score.auto_reject_below, or 500 fallback.
        """
        return int(
            self.rules.get("credit_score", {}).get("auto_reject_below", 500)
        )

    @property
    def risk_score_thresholds(self) -> dict:
        """
        Risk score decision thresholds dict.

        Returns:
            Dict with keys: approved_below, review_required_below, rejected_above.
        """
        return self.rules.get("risk_score", {
            "approved_below": 40,
            "review_required_below": 70,
            "rejected_above": 70,
        })

    @property
    def rag_top_k(self) -> int:
        """
        Default number of policy chunks to retrieve from ChromaDB.

        Returns:
            int from loan_rules.agents.rag.top_k_chunks, or 5 fallback.
        """
        return int(
            self.loan_rules.get("agents", {})
                           .get("rag", {})
                           .get("top_k_chunks", 5)
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached singleton Settings instance.

    Parses .env, all YAML files, and applies validators exactly once per
    process. Subsequent calls return the cached object at zero cost.

    Returns:
        The application-wide Settings singleton.

    Usage:
        from config.settings import get_settings
        settings = get_settings()
        print(settings.aws_region)
        print(settings.dti_auto_reject_threshold)
    """
    return Settings()
