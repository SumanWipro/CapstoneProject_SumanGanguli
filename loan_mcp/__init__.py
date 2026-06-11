"""
mcp/__init__.py
===============
FastMCP tool server package for the Loan Approval System.

Exposes the FastMCP app instance so it can be launched from the CLI:
    python -m mcp.server
"""

from loan_mcp.server import mcp_app

__all__ = ["mcp_app"]
