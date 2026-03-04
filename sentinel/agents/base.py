"""Base interfaces for Sentinel agents and target systems."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Target system interface
# ---------------------------------------------------------------------------

@dataclass
class TargetResult:
    """Captured output from one run of a target system."""
    output: str
    retrieved_chunks: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.error is not None


@runtime_checkable
class TargetSystem(Protocol):
    """Protocol every system-under-test must satisfy.

    Sentinel calls ``run()`` to execute experiments and
    ``apply_intervention()`` / ``reset_interventions()`` during simulation.
    """

    async def run(self, query: str, context_setup: str = "") -> TargetResult:
        """Execute the system with the given query and return a TargetResult."""
        ...

    async def apply_intervention(
        self, intervention_type: str, params: dict[str, Any]
    ) -> None:
        """Apply a proposed intervention to the target system.

        intervention_type values:
          - ``prompt_mutation``      — modify the system/user prompt
          - ``guardrail``            — add an input/output filter
          - ``tool_policy_change``   — change which tools are available
          - ``config_change``        — adjust retrieval parameters, thresholds, etc.
          - ``architectural_recommendation`` — note only; no runtime effect
        """
        ...

    async def reset_interventions(self) -> None:
        """Restore the target to its default (pre-intervention) configuration."""
        ...

    def describe(self) -> str:
        """Return a prose description of the system used for hypothesis generation."""
        ...
