"""
agents/base_agent.py
====================
Abstract base class for all five Loan Approval System agents.

Responsibilities:
- Provide a uniform invoke() interface enforced on all subclasses
- Initialise and hold the AWS Bedrock runtime client
- Load prompt templates from prompts/ at construction time
- Implement build_prompt() — renders {placeholder} slots in the template
- Implement call_claude() — sends the prompt to Claude Sonnet via Bedrock
- Implement parse_json_response() — extracts and parses JSON from Claude's reply
- Centralise retry logic (3 attempts, exponential back-off) on Bedrock calls

Design decisions:
- ABC enforces that every subclass implements invoke(); the base class only
  owns infrastructure — it has no loan-domain logic.
- Prompt templates are loaded once at __init__ (not per-call) to avoid
  repeated disk I/O across many requests.
- Claude is instructed to return raw JSON only; parse_json_response() strips
  markdown code fences (```json ... ```) that Claude sometimes emits despite
  instructions, making parsing robust.
- Bedrock uses the Messages API (anthropic-bedrock payload format) so the
  call structure is identical to the Anthropic SDK's client.messages.create().
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import get_settings
from utils.logger import get_logger

log = get_logger(__name__, component="base_agent")

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Bedrock request defaults — overridden per-agent via loan_rules.yaml
_DEFAULT_MAX_TOKENS  = 1024
_DEFAULT_TEMPERATURE = 0.0


class BaseAgent(ABC):
    """
    Abstract base for all five loan approval agents.

    Subclasses must define:
        prompt_file (class attribute) — filename in prompts/ directory
        invoke(payload)              — agent-specific logic

    Subclasses inherit:
        build_prompt(**kwargs)       — renders the prompt template
        call_claude(prompt)          — invokes Bedrock with retry
        parse_json_response(raw)     — extracts JSON from Claude's reply
    """

    prompt_file: str = ""

    def __init__(self) -> None:
        """Initialise Bedrock client, load prompt template, read agent config."""
        self.settings         = get_settings()
        self.bedrock_client   = self._build_bedrock_client()
        self.model_id         = self.settings.bedrock_model_id
        self._prompt_template = self._load_prompt()

        # Per-agent config from loan_rules.yaml → agents section
        agent_key = self.prompt_file.replace(".txt", "")
        agents_cfg = self.settings.loan_rules.get("agents", {})
        self._max_tokens  = int(
            agents_cfg.get("max_response_tokens", {}).get(agent_key, _DEFAULT_MAX_TOKENS)
        )
        self._temperature = float(
            agents_cfg.get("temperature", {}).get(agent_key, _DEFAULT_TEMPERATURE)
        )

    # ------------------------------------------------------------------
    # Abstract interface — must be implemented by every subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the agent with the given payload and return a typed result.

        Args:
            payload: Input dict specific to this agent's responsibility.

        Returns:
            Typed result dict (ProfileResult, RiskResult, PolicyChunks, etc.)
        """

    # ------------------------------------------------------------------
    # Prompt rendering
    # ------------------------------------------------------------------

    def build_prompt(self, **kwargs: Any) -> str:
        """
        Render the agent's prompt template with keyword argument substitution.

        Replaces every {placeholder} slot in the template with the matching
        kwarg value. Uses str.format_map() so missing keys raise KeyError
        immediately rather than silently leaving un-substituted placeholders.

        Args:
            **kwargs: Values for every {placeholder} in the template.
                      All placeholders must be supplied — no partial renders.

        Returns:
            Fully rendered prompt string ready to send to Claude Sonnet.

        Raises:
            KeyError:  If a placeholder in the template has no matching kwarg.
            ValueError: If the prompt template was not loaded (empty file).

        Example:
            prompt = self.build_prompt(
                credit_band="fair", dti=0.52, loan_amount=500000
            )
        """
        if not self._prompt_template:
            raise ValueError(
                f"Prompt template for {self.__class__.__name__} is empty. "
                f"Check prompts/{self.prompt_file} exists and is not blank."
            )

        # Convert all values to strings for safe substitution
        str_kwargs = {k: str(v) for k, v in kwargs.items()}

        try:
            return self._prompt_template.format_map(str_kwargs)
        except KeyError as exc:
            raise KeyError(
                f"Prompt template '{self.prompt_file}' contains placeholder "
                f"{exc} but no matching kwarg was provided."
            ) from exc

    # ------------------------------------------------------------------
    # Claude Sonnet invocation via Bedrock
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(ClientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def call_claude(self, prompt: str) -> str:
        """
        Send a prompt to Claude Sonnet via AWS Bedrock and return the reply.

        Uses the Bedrock Messages API (anthropic-bedrock payload format).
        Retries up to 3 times on ClientError (throttling, transient errors)
        with exponential back-off: 2s → 4s → 8s.

        The system instruction tells Claude to return raw JSON only — no
        markdown fences, no prose before or after the JSON object. This
        makes parse_json_response() maximally reliable.

        Args:
            prompt: Fully rendered prompt string from build_prompt().

        Returns:
            Raw text content of Claude's first response block.

        Raises:
            ClientError: After 3 failed Bedrock calls (re-raised).
            RuntimeError: If Bedrock returns an unexpected response shape.

        Example:
            raw = self.call_claude(prompt)
            result = self.parse_json_response(raw)
        """
        log.debug(
            "calling_claude",
            agent=self.__class__.__name__,
            model=self.model_id,
            prompt_chars=len(prompt),
        )

        # Bedrock Messages API payload
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        self._max_tokens,
            "temperature":       self._temperature,
            "system": (
                "You are a precise financial analysis assistant. "
                "Always respond with valid JSON only — no markdown fences, "
                "no explanation text before or after the JSON object."
            ),
            "messages": [
                {"role": "user", "content": prompt}
            ],
        })

        response = self.bedrock_client.invoke_model(
            modelId     = self.model_id,
            body        = body,
            contentType = "application/json",
            accept      = "application/json",
        )

        response_body = json.loads(response["body"].read())

        # Extract text from the first content block
        content_blocks = response_body.get("content", [])
        if not content_blocks:
            raise RuntimeError(
                f"Bedrock returned an empty content list for model {self.model_id}."
            )

        raw_text = content_blocks[0].get("text", "")

        log.debug(
            "claude_response_received",
            agent=self.__class__.__name__,
            response_chars=len(raw_text),
        )

        return raw_text

    # ------------------------------------------------------------------
    # JSON response parser
    # ------------------------------------------------------------------

    def parse_json_response(self, raw: str) -> dict[str, Any]:
        """
        Parse a JSON response from Claude Sonnet into a Python dict.

        Despite prompt instructions, Claude occasionally wraps its JSON in
        markdown code fences (```json ... ```). This method strips those
        fences before parsing so extraction is robust to both clean JSON
        and fenced JSON responses.

        Args:
            raw: Raw string returned by call_claude().

        Returns:
            Parsed dict containing the agent's structured output.

        Raises:
            json.JSONDecodeError: If the cleaned string is not valid JSON.
            ValueError:           If the response is empty after cleaning.

        Example:
            raw = '```json\\n{"verdict": "APPROVED"}\\n```'
            result = self.parse_json_response(raw)
            # {"verdict": "APPROVED"}
        """
        cleaned = raw.strip()

        # Strip markdown code fences if present: ```json\n...\n```
        fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", cleaned)
        if fenced:
            cleaned = fenced.group(1).strip()

        if not cleaned:
            raise ValueError(
                f"{self.__class__.__name__}: Claude returned an empty response."
            )

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            log.error(
                "json_parse_failed",
                agent=self.__class__.__name__,
                raw_preview=raw[:200],
                error=str(exc),
            )
            raise json.JSONDecodeError(
                f"{self.__class__.__name__}: Failed to parse Claude's response as JSON. "
                f"Raw preview: {raw[:200]!r}",
                exc.doc,
                exc.pos,
            ) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_bedrock_client(self):
        """Create and return a Boto3 Bedrock runtime client from settings."""
        return boto3.client(
            service_name          = "bedrock-runtime",
            region_name           = self.settings.aws_region,
            aws_access_key_id     = self.settings.aws_access_key_id,
            aws_secret_access_key = self.settings.aws_secret_access_key,
        )

    def _load_prompt(self) -> str:
        """
        Load the agent's prompt template from prompts/<prompt_file>.

        Returns empty string (not an error) if prompt_file is unset so
        that subclasses that build prompts programmatically can opt out.

        Returns:
            Raw prompt template string with {placeholder} slots, or "".
        """
        if not self.prompt_file:
            return ""
        prompt_path = _PROMPTS_DIR / self.prompt_file
        if not prompt_path.exists():
            log.warning("prompt_file_not_found", path=str(prompt_path))
            return ""
        content = prompt_path.read_text(encoding="utf-8")
        log.debug("prompt_loaded", file=self.prompt_file, chars=len(content))
        return content
