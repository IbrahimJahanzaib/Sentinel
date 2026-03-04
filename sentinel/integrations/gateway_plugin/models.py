"""Shared Pydantic models for Pipeline Adapter and Gateway Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    GUARDRAIL_TRIGGERED = "guardrail_triggered"


class RequestContext(BaseModel):
    """Captures a full request/response pair, populated incrementally via pre/post hooks."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Request fields (populated in pre_request)
    model: str = ""
    provider: str = ""
    prompt: str = ""
    system_prompt: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    # Response fields (populated in post_request)
    output: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.error is not None


class GatewayEvent(BaseModel):
    """A single event from a WebSocket gateway stream."""

    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""
    request_id: str = ""
    data: dict[str, Any] = Field(default_factory=dict)

    # Convenience accessors
    @property
    def model(self) -> str:
        return self.data.get("model", "")

    @property
    def latency_ms(self) -> int:
        return self.data.get("latency_ms", 0)

    @property
    def error_message(self) -> str:
        return self.data.get("error", "")

    @property
    def tokens_total(self) -> int:
        return self.data.get("input_tokens", 0) + self.data.get("output_tokens", 0)


class AlertFinding(BaseModel):
    """A finding dispatched to alerters."""

    severity: str  # S0–S4
    failure_class: str  # FailureClass value
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    source_event_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
