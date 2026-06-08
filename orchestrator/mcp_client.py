"""
orchestrator/mcp_client.py
==========================
MCP client adapter used by orchestrator nodes.

Responsibilities:
- Provide a single call_tool(tool_name, payload) interface
- Apply timeout and retry policy from Settings
- Normalize transport/protocol errors into one exception type

Note:
- This adapter is intentionally transport-focused and domain-agnostic.
- Nodes should only know tool names + payloads, not HTTP details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from config.settings import get_settings
from utils.logger import get_logger

log = get_logger(__name__, component="mcp_client")


class MCPInvocationError(RuntimeError):
    """Raised when an MCP tool invocation fails after retries."""


@dataclass(frozen=True)
class MCPClientConfig:
    """Runtime configuration for MCP client calls."""

    base_url: str
    timeout_seconds: float
    max_retries: int


class MCPClient:
    """
    Small HTTP adapter for MCP tool invocation.

    The adapter supports two endpoint patterns to stay compatible with
    different server deployments:
    1. JSON-RPC endpoint: POST {base_url}/mcp with method tools/call
    2. REST-style endpoint: POST {base_url}/tools/{tool_name}
    """

    def __init__(self, config: MCPClientConfig | None = None) -> None:
        if config is None:
            settings = get_settings()
            config = MCPClientConfig(
                base_url=settings.mcp_client_base_url,
                timeout_seconds=settings.mcp_client_timeout_seconds,
                max_retries=settings.mcp_client_max_retries,
            )
        self.config = config

    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Invoke an MCP tool and return a normalized dict response.

        Args:
            tool_name: Registered MCP tool name.
            payload: Tool input payload.

        Returns:
            Tool response as dict.

        Raises:
            MCPInvocationError: If all retries fail or response is invalid.
        """
        if not tool_name:
            raise MCPInvocationError("tool_name must be a non-empty string")

        attempts = self.config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                started = httpx.Timeout(self.config.timeout_seconds)
                with httpx.Client(timeout=started) as client:
                    # Preferred protocol path: JSON-RPC style MCP endpoint.
                    rpc_url = f"{self.config.base_url}/mcp"
                    rpc_payload = {
                        "jsonrpc": "2.0",
                        "id": f"{tool_name}-{attempt}",
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": payload},
                    }
                    rpc_resp = client.post(rpc_url, json=rpc_payload)

                    if rpc_resp.status_code < 400:
                        data = rpc_resp.json()
                        if isinstance(data, dict):
                            if "error" in data:
                                raise MCPInvocationError(
                                    f"MCP JSON-RPC error for tool '{tool_name}': {data['error']}"
                                )
                            if "result" in data:
                                return self._normalize_response(data["result"])
                            return self._normalize_response(data)

                    # Fallback path: REST-style tool endpoint.
                    rest_url = f"{self.config.base_url}/tools/{tool_name}"
                    rest_resp = client.post(rest_url, json=payload)
                    rest_resp.raise_for_status()

                    return self._normalize_response(rest_resp.json())

            except (httpx.TimeoutException, httpx.HTTPError, ValueError, TypeError, MCPInvocationError) as exc:
                last_error = exc
                log.warning(
                    "mcp_tool_call_failed",
                    tool_name=tool_name,
                    attempt=attempt,
                    max_attempts=attempts,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

        raise MCPInvocationError(
            f"MCP tool '{tool_name}' failed after {attempts} attempt(s): {last_error}"
        )

    @staticmethod
    def _normalize_response(data: Any) -> dict[str, Any]:
        """Normalize non-dict tool outputs into a dict envelope."""
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {"items": data}
        return {"value": data}


_client_singleton: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    """Return process-wide MCP client singleton."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = MCPClient()
    return _client_singleton
