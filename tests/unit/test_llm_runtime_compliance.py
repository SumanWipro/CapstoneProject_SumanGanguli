"""
Automated compliance checks for case-study LLM runtime requirements.

These tests verify three non-negotiable signals:
1. Default model target is Claude Sonnet 4.6.
2. Anthropic SDK invocation path exists in BaseAgent.
3. Safe boto3 Bedrock fallback path exists.
"""

from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT_DIR / rel_path).read_text(encoding="utf-8")


def test_model_target_is_sonnet_4_6() -> None:
    """Verify settings default model is Sonnet 4.6."""
    content = _read("config/settings.py")
    assert "anthropic.claude-sonnet-4-6" in content


def test_anthropic_sdk_invocation_path_exists() -> None:
    """Verify Anthropic SDK path is present in BaseAgent."""
    content = _read("agents/base_agent.py")
    assert "AnthropicBedrock" in content
    assert "messages.create" in content


def test_bedrock_fallback_path_exists() -> None:
    """Verify boto3 fallback path is present in BaseAgent."""
    content = _read("agents/base_agent.py")
    assert "invoke_model" in content
    assert "anthropic_sdk_init_failed_fallback_to_boto3" in content
