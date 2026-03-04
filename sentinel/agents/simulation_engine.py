"""Agent 6 — Simulation Engine.

Validates proposed interventions by applying them to the target system,
re-running the original experiments, and comparing before/after failure rates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from sqlalchemy import update

from sentinel.agents.experiment_executor import ExperimentExecutor
from sentinel.db.connection import get_session
from sentinel.db.models import Experiment, ExperimentRun, Failure, Intervention
from sentinel.agents.base import TargetSystem

if TYPE_CHECKING:
    from sentinel.core.cost_tracker import CostTracker

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Outcome of validating a single intervention."""
    intervention_id: str
    status: str               # fixed | partially_fixed | no_effect | regression
    failure_rate_before: float
    failure_rate_after: float
    delta: float              # negative = improvement, positive = regression
    notes: str

    @property
    def improved(self) -> bool:
        return self.delta < -0.1  # at least 10pp improvement

    @property
    def regressed(self) -> bool:
        return self.delta > 0.1


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_FIXED_THRESHOLD = 0.15        # after rate ≤ 15% → fixed
_PARTIAL_THRESHOLD = 0.1       # delta ≤ -10pp → partially fixed
_REGRESSION_THRESHOLD = 0.1    # delta ≥ +10pp → regression


def _classify_outcome(rate_before: float, rate_after: float) -> str:
    delta = rate_after - rate_before
    if rate_after <= _FIXED_THRESHOLD:
        return "fixed"
    if delta <= -_PARTIAL_THRESHOLD:
        return "partially_fixed"
    if delta >= _REGRESSION_THRESHOLD:
        return "regression"
    return "no_effect"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SimulationEngine:
    """Validates interventions via counterfactual replay.

    For each intervention:
      1. Apply it to the target system
      2. Re-run the original experiments
      3. Compare the new failure rate to the original
      4. Persist the result and reset the target

    Parameters
    ----------
    target:
        The system under test (must implement ``apply_intervention`` and
        ``reset_interventions``).
    cost_tracker:
        Optional shared CostTracker for budget enforcement.
    timeout_seconds:
        Per-run timeout passed to the inner ExperimentExecutor.
    """

    def __init__(
        self,
        target: TargetSystem,
        cost_tracker: Optional["CostTracker"] = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._target = target
        self._tracker = cost_tracker
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate(
        self,
        intervention: Intervention,
        experiments: list[Experiment],
        failure: Failure,
    ) -> ValidationResult:
        """Apply an intervention and measure its effect.

        Parameters
        ----------
        intervention:
            The proposed fix to test.
        experiments:
            The original experiments that triggered the failure.
        failure:
            The original failure record (contains the baseline failure rate).

        Returns
        -------
        ValidationResult
            Outcome with before/after rates and classification.
        """
        rate_before = failure.failure_rate

        # Apply the intervention
        try:
            params = _parse_intervention_params(intervention)
            await self._target.apply_intervention(intervention.type, params)
        except NotImplementedError:
            # Target doesn't support this intervention type at runtime
            result = ValidationResult(
                intervention_id=intervention.id,
                status="no_effect",
                failure_rate_before=rate_before,
                failure_rate_after=rate_before,
                delta=0.0,
                notes=f"Target does not support runtime application of '{intervention.type}'.",
            )
            await self._persist(result)
            return result

        # Re-run the experiments
        executor = ExperimentExecutor(
            target=self._target,
            cost_tracker=self._tracker,
            timeout_seconds=self._timeout,
        )
        try:
            all_new_runs = await executor.run_batch(experiments)
        finally:
            await self._target.reset_interventions()

        # Calculate new failure rate (runs with errors count as failures)
        new_runs: list[ExperimentRun] = [
            run
            for runs in all_new_runs.values()
            for run in runs
        ]
        if not new_runs:
            rate_after = rate_before
        else:
            failed = sum(1 for r in new_runs if r.error or not r.output.strip())
            rate_after = failed / len(new_runs)

        status = _classify_outcome(rate_before, rate_after)
        delta = round(rate_after - rate_before, 4)

        result = ValidationResult(
            intervention_id=intervention.id,
            status=status,
            failure_rate_before=rate_before,
            failure_rate_after=round(rate_after, 4),
            delta=delta,
            notes=self._build_notes(status, rate_before, rate_after, intervention),
        )

        await self._persist(result)
        return result

    async def validate_batch(
        self,
        interventions: list[Intervention],
        experiments_by_failure: dict[str, list[Experiment]],
        failures_by_id: dict[str, Failure],
    ) -> list[ValidationResult]:
        """Validate a list of interventions sequentially.

        Parameters
        ----------
        interventions:
            All interventions to test.
        experiments_by_failure:
            Dict mapping failure_id → list of Experiments that triggered it.
        failures_by_id:
            Dict mapping failure_id → Failure ORM object.
        """
        results: list[ValidationResult] = []
        for intervention in interventions:
            experiments = experiments_by_failure.get(intervention.failure_id, [])
            failure = failures_by_id.get(intervention.failure_id)
            if not experiments or failure is None:
                continue
            result = await self.validate(intervention, experiments, failure)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _persist(self, result: ValidationResult) -> None:
        """Write validation result back to the Intervention row."""
        async with get_session() as session:
            await session.execute(
                update(Intervention)
                .where(Intervention.id == result.intervention_id)
                .values(
                    validation_status=result.status,
                    validation_notes=result.notes,
                    failure_rate_before=result.failure_rate_before,
                    failure_rate_after=result.failure_rate_after,
                )
            )

    @staticmethod
    def _build_notes(
        status: str,
        rate_before: float,
        rate_after: float,
        intervention: Intervention,
    ) -> str:
        pct_before = f"{rate_before:.0%}"
        pct_after = f"{rate_after:.0%}"
        labels = {
            "fixed":           f"Intervention fixed the failure. Rate dropped from {pct_before} to {pct_after}.",
            "partially_fixed": f"Partial improvement. Rate dropped from {pct_before} to {pct_after}.",
            "no_effect":       f"No measurable improvement. Rate unchanged ({pct_before} → {pct_after}).",
            "regression":      f"REGRESSION detected. Rate worsened from {pct_before} to {pct_after}.",
        }
        return labels.get(status, f"{pct_before} → {pct_after}")


def _parse_intervention_params(intervention: Intervention) -> dict:
    """Extract runtime-applicable parameters from the intervention description.

    For prompt_mutation and config_change, we pass the description text as
    ``instruction`` so target systems can apply it programmatically.
    """
    return {
        "type": intervention.type,
        "description": intervention.description,
        "instruction": intervention.description,
    }
