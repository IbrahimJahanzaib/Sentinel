"""Pipeline Adapter — hook wrapper for intercepting existing LLM calls."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Optional

from sentinel.agents.base import TargetResult
from sentinel.integrations.gateway_plugin.models import RequestContext

logger = logging.getLogger(__name__)


class PipelineAdapter:
    """Wraps existing LLM calls via pre_request / post_request hooks.

    In SHADOW mode, pre_request is a strict no-op (read-only observation).
    Captured contexts are buffered for research cycle consumption.
    """

    def __init__(
        self,
        *,
        name: str = "pipeline",
        shadow_mode: bool = True,
        max_buffer: int = 10_000,
        cost_tracker: Any | None = None,
    ) -> None:
        self.name = name
        self.shadow_mode = shadow_mode
        self._buffer: deque[RequestContext] = deque(maxlen=max_buffer)
        self._lock = asyncio.Lock()
        self._cost_tracker = cost_tracker

    def create_context(
        self,
        *,
        model: str = "",
        provider: str = "",
        prompt: str = "",
        system_prompt: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> RequestContext:
        """Create a new request context to pass through the hook pipeline."""
        return RequestContext(
            model=model,
            provider=provider,
            prompt=prompt,
            system_prompt=system_prompt,
            parameters=parameters or {},
        )

    async def pre_request(self, ctx: RequestContext) -> RequestContext:
        """Called before the LLM request is sent.

        In shadow mode this is a strict no-op — returns the context unchanged.
        """
        if self.shadow_mode:
            return ctx
        # In non-shadow mode, could add modifications here in the future
        return ctx

    async def post_request(
        self,
        ctx: RequestContext,
        *,
        output: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        error: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RequestContext:
        """Called after the LLM response is received. Records the response and buffers."""
        ctx.output = output
        ctx.input_tokens = input_tokens
        ctx.output_tokens = output_tokens
        ctx.latency_ms = latency_ms
        ctx.error = error
        ctx.tool_calls = tool_calls or []
        ctx.metadata = metadata or {}

        async with self._lock:
            self._buffer.append(ctx)

        # Record cost if tracker available
        if self._cost_tracker and (input_tokens or output_tokens):
            try:
                await self._cost_tracker.record(
                    provider=ctx.provider or "unknown",
                    model=ctx.model or "unknown",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                )
            except Exception:
                logger.debug("Cost recording failed", exc_info=True)

        # Persist to audit trail
        try:
            from sentinel.db.audit import log_event

            await log_event(
                "pipeline.request_captured",
                actor=f"pipeline:{self.name}",
                entity_type="request",
                entity_id=ctx.id,
                details={
                    "model": ctx.model,
                    "provider": ctx.provider,
                    "latency_ms": latency_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "error": error,
                },
            )
        except Exception:
            logger.debug("Audit logging failed", exc_info=True)

        return ctx

    async def get_captured(self, limit: int | None = None) -> list[RequestContext]:
        """Return captured contexts (most recent first)."""
        async with self._lock:
            items = list(self._buffer)
        items.reverse()
        if limit:
            items = items[:limit]
        return items

    async def drain(self) -> list[RequestContext]:
        """Return and clear all buffered contexts."""
        async with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
        return items

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    def as_target_system(self) -> PipelineTargetSystem:
        """Return a TargetSystem-compatible wrapper around captured traffic."""
        return PipelineTargetSystem(self)


class PipelineTargetSystem:
    """Implements the TargetSystem protocol using captured pipeline traffic.

    Instead of executing a real system, it replays the most recent captured
    request/response pair when ``run()`` is called.
    """

    def __init__(self, adapter: PipelineAdapter) -> None:
        self._adapter = adapter
        self._description = f"Pipeline '{adapter.name}' (captured traffic)"

    async def run(self, query: str, context_setup: str = "") -> TargetResult:
        """Return the most recent captured context as a TargetResult.

        The query parameter is used for matching — if a captured context's
        prompt matches, it's preferred. Otherwise the most recent is used.
        """
        captured = await self._adapter.get_captured(limit=100)
        if not captured:
            return TargetResult(
                output="",
                error="No captured traffic available",
            )

        # Try to find a matching prompt
        best = captured[0]
        for ctx in captured:
            if query and query in ctx.prompt:
                best = ctx
                break

        return TargetResult(
            output=best.output,
            tool_calls=best.tool_calls,
            error=best.error,
            metadata={
                "request_id": best.id,
                "model": best.model,
                "provider": best.provider,
                "latency_ms": best.latency_ms,
                "input_tokens": best.input_tokens,
                "output_tokens": best.output_tokens,
            },
        )

    async def apply_intervention(
        self, intervention_type: str, params: dict[str, Any]
    ) -> None:
        """No-op — captured traffic cannot be modified."""
        logger.info(
            "Intervention %s requested on pipeline target (no-op)", intervention_type
        )

    async def reset_interventions(self) -> None:
        """No-op."""
        pass

    def describe(self) -> str:
        return self._description
