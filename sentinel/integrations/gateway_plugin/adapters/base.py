"""Base protocol for gateway adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sentinel.integrations.gateway_plugin.models import GatewayEvent


@runtime_checkable
class GatewayAdapter(Protocol):
    """Protocol for parsing raw gateway events into normalized GatewayEvent objects."""

    @property
    def source_name(self) -> str: ...

    def parse_event(self, raw: dict) -> GatewayEvent | None:
        """Parse a raw event dict into a GatewayEvent, or None to skip (e.g. heartbeats)."""
        ...
