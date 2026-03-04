"""Gateway Monitor — WebSocket consumer for real-time LLM gateway events."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable

from sentinel.integrations.gateway_plugin.adapters.base import GatewayAdapter
from sentinel.integrations.gateway_plugin.adapters.generic import GenericAdapter
from sentinel.integrations.gateway_plugin.models import (
    AlertFinding,
    EventType,
    GatewayEvent,
)

logger = logging.getLogger(__name__)

# Type for the optional analysis callback
AnalysisCallback = Callable[[GatewayEvent], Awaitable[AlertFinding | None]]


class GatewayMonitor:
    """WebSocket consumer that normalizes gateway events and dispatches alerts.

    Usage::

        monitor = GatewayMonitor("ws://gateway:8080/events")
        monitor.add_alerter(ConsoleAlerter(min_severity="S2"))
        await monitor.start()  # blocking
        # or
        task = await monitor.start_background()  # returns asyncio.Task
    """

    def __init__(
        self,
        ws_url: str,
        *,
        adapter: GatewayAdapter | None = None,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 0,
        high_latency_threshold_ms: int = 10_000,
        analysis_callback: AnalysisCallback | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.adapter: GatewayAdapter = adapter or GenericAdapter()
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.high_latency_threshold_ms = high_latency_threshold_ms
        self.analysis_callback = analysis_callback

        self._alerters: list[Any] = []
        self._running = False
        self._events_processed = 0
        self._alerts_dispatched = 0

    def add_alerter(self, alerter: Any) -> None:
        """Register an alerter to receive findings."""
        self._alerters.append(alerter)

    @property
    def events_processed(self) -> int:
        return self._events_processed

    @property
    def alerts_dispatched(self) -> int:
        return self._alerts_dispatched

    async def start(self) -> None:
        """Connect to the WebSocket and consume events (blocking)."""
        try:
            import websockets
        except ImportError:
            raise ImportError(
                "The 'websockets' package is required for GatewayMonitor. "
                "Install it with: pip install websockets>=12.0"
            )

        self._running = True
        attempt = 0

        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("Connected to %s", self.ws_url)
                    attempt = 0  # Reset on successful connection
                    await self._consume(ws)
            except Exception as exc:
                if not self._running:
                    break
                attempt += 1
                logger.warning(
                    "Connection lost (attempt %d): %s", attempt, exc
                )
                if (
                    self.max_reconnect_attempts > 0
                    and attempt >= self.max_reconnect_attempts
                ):
                    logger.error(
                        "Max reconnect attempts (%d) reached",
                        self.max_reconnect_attempts,
                    )
                    break
                await asyncio.sleep(self.reconnect_delay)

    async def start_background(self) -> asyncio.Task:
        """Start the monitor as a background task and return the Task."""
        task = asyncio.create_task(self.start())
        return task

    def stop(self) -> None:
        """Signal the monitor to stop."""
        self._running = False

    async def _consume(self, ws: Any) -> None:
        """Read messages from the WebSocket and process them."""
        async for message in ws:
            if not self._running:
                break

            try:
                raw = json.loads(message) if isinstance(message, str) else message
            except (json.JSONDecodeError, TypeError):
                logger.debug("Skipping non-JSON message")
                continue

            event = self.adapter.parse_event(raw)
            if event is None:
                continue

            self._events_processed += 1
            await self._analyze(event)

    async def _analyze(self, event: GatewayEvent) -> None:
        """Run built-in heuristics and optional callback, then dispatch findings."""
        findings: list[AlertFinding] = []

        # Built-in heuristic analysis
        heuristic_finding = self._run_heuristics(event)
        if heuristic_finding:
            findings.append(heuristic_finding)

        # Optional custom/LLM-based analysis
        if self.analysis_callback:
            try:
                custom_finding = await self.analysis_callback(event)
                if custom_finding:
                    findings.append(custom_finding)
            except Exception:
                logger.debug("Analysis callback failed", exc_info=True)

        for finding in findings:
            await self._dispatch(finding)

    def _run_heuristics(self, event: GatewayEvent) -> AlertFinding | None:
        """Apply built-in heuristic rules to an event."""

        # Error events
        if event.event_type == EventType.ERROR:
            return AlertFinding(
                severity="S2",
                failure_class="DEPLOYMENT",
                summary=f"LLM error: {event.error_message or 'unknown error'}",
                evidence=event.data,
                source_event_id=event.request_id,
                timestamp=event.timestamp,
            )

        # Timeout events
        if event.event_type == EventType.TIMEOUT:
            return AlertFinding(
                severity="S2",
                failure_class="DEPLOYMENT",
                summary=f"LLM request timed out (request: {event.request_id})",
                evidence=event.data,
                source_event_id=event.request_id,
                timestamp=event.timestamp,
            )

        # Rate limit events
        if event.event_type == EventType.RATE_LIMIT:
            return AlertFinding(
                severity="S1",
                failure_class="DEPLOYMENT",
                summary=f"Rate limit hit: {event.data.get('message', 'throttled')}",
                evidence=event.data,
                source_event_id=event.request_id,
                timestamp=event.timestamp,
            )

        # Guardrail triggered
        if event.event_type == EventType.GUARDRAIL_TRIGGERED:
            return AlertFinding(
                severity="S3",
                failure_class="SECURITY",
                summary=f"Guardrail triggered: {event.data.get('guardrail', 'unknown')}",
                evidence=event.data,
                source_event_id=event.request_id,
                timestamp=event.timestamp,
            )

        # Response-level heuristics (only for LLM_RESPONSE events)
        if event.event_type == EventType.LLM_RESPONSE:
            # High latency
            if event.latency_ms > self.high_latency_threshold_ms:
                return AlertFinding(
                    severity="S1",
                    failure_class="DEPLOYMENT",
                    summary=f"High latency: {event.latency_ms}ms (threshold: {self.high_latency_threshold_ms}ms)",
                    evidence={"latency_ms": event.latency_ms, "model": event.model},
                    source_event_id=event.request_id,
                    timestamp=event.timestamp,
                )

            # Empty response
            output = event.data.get("output", "")
            if event.data.get("output") is not None and not output.strip():
                return AlertFinding(
                    severity="S1",
                    failure_class="REASONING",
                    summary="Empty LLM response detected",
                    evidence={"model": event.model, "request_id": event.request_id},
                    source_event_id=event.request_id,
                    timestamp=event.timestamp,
                )

        return None

    async def _dispatch(self, finding: AlertFinding) -> None:
        """Send a finding to all registered alerters."""
        self._alerts_dispatched += 1
        for alerter in self._alerters:
            try:
                await alerter.alert(finding)
            except Exception:
                logger.debug(
                    "Alerter %s failed", type(alerter).__name__, exc_info=True
                )
