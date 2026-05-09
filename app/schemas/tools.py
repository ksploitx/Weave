"""Schemas for tool execution results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ToolResult(BaseModel):
    """The outcome of a single tool invocation."""

    tool_name: str
    status: Literal["success", "timeout", "empty", "parse_error", "error"]
    data: Any | None = None
    latency_ms: float = 0.0
    retry_count: int = 0
    input_used: dict = {}
