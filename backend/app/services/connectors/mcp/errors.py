"""Typed MCP connector failures. No HANA / silent fallback."""

from __future__ import annotations


class McpError(Exception):
    """Named MCP failure. ``code`` is the closed machine token."""

    code = "mcp_call_failed"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()}"


class McpUnconfigured(McpError):
    code = "mcp_unconfigured"


class McpUnreachable(McpError):
    code = "mcp_unreachable"


class McpToolUnknown(McpError):
    code = "mcp_tool_unknown"


class McpCallFailed(McpError):
    code = "mcp_call_failed"
