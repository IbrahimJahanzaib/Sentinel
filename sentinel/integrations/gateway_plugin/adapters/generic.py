"""Generic gateway adapter for a standardized event schema."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sentinel.integrations.gateway_plugin.models import EventType, GatewayEvent

# Event types that map directly from string names
_EVENT_TYPE_MAP: dict[str, EventType] = {e.value: e for e in EventType}


class GenericAdapter:
    """Default adapter that expects a simple standardized event schema.

    Expected raw format::

        {
            "type": "llm_request" | "llm_response" | ... | "heartbeat",
            "timestamp": "2024-01-01T00:00:00Z" (ISO 8601) or Unix float,
            "request_id": "abc123",
            "source": "my-service",
            "data": { ... }
        }
    """

    def __init__(self, source: str = "generic") -> None:
        self._source = source

    @property
    def source_name(self) -> str:
        return self._source

    def parse_event(self, raw: dict[str, Any]) -> GatewayEvent | None:
        event_type_str = raw.get("type", "")

        # Filter heartbeats
        if event_type_str == "heartbeat":
            return None

        event_type = _EVENT_TYPE_MAP.get(event_type_str)
        if event_type is None:
            return None

        timestamp = self._parse_timestamp(raw.get("timestamp"))

        return GatewayEvent(
            event_type=event_type,
            timestamp=timestamp,
            source=raw.get("source", self._source),
            request_id=raw.get("request_id", ""),
            data=raw.get("data", {}),
        )

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            # Handle ISO 8601 with Z suffix
            cleaned = value.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        return datetime.now(timezone.utc)
