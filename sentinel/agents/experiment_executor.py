"""Agent 3 — Experiment Executor.

Runs experiment definitions against a target system, captures all outputs,
and persists ExperimentRun records to the database.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sentinel.core.cost_tracker import BudgetExceededError
from sentinel.db.connection import get_session
from sentinel.db.models import Experiment, ExperimentRun
from sentinel.agents.base import TargetResult, TargetSystem

if TYPE_CHECKING:
    from sentinel.core.cost_tracker import CostTracker

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ExperimentExecutor:
    """Executes approved experiments against a TargetSystem.

    Parameters
    ----------
    target:
        The system under test.
    cost_tracker:
        Optional shared CostTracker; ``check_budget()`` is called before each run.
    timeout_seconds:
        Per-run wall-clock timeout. Runs that exceed this are recorded as errors.
    max_parallel:
        Max concurrent runs across experiments. Defaults to 1 (sequential).
    """

    def __init__(
        self,
        target: TargetSystem,
        cost_tracker: Optional["CostTracker"] = None,
        timeout_seconds: float = 300.0,
        max_parallel: int = 1,
    ) -> None:
        self._target = target
        self._tracker = cost_tracker
        self._timeout = timeout_seconds
        self._semaphore = asyncio.Semaphore(max(1, max_parallel))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        experiment: Experiment,
        override_runs: Optional[int] = None,
    ) -> list[ExperimentRun]:
        """Execute a single experiment N times and return the saved runs.

        Parameters
        ----------
        experiment:
            The approved experiment to run.
        override_runs:
            Override the experiment's ``num_runs`` field.
        """
        if self._tracker:
            self._tracker.check_budget()

        n = override_runs if override_runs is not None else experiment.num_runs
        runs: list[ExperimentRun] = []

        for i in range(1, n + 1):
            run = await self._execute_once(experiment, i)
            runs.append(run)

        return runs

    async def run_batch(
        self,
        experiments: list[Experiment],
    ) -> dict[str, list[ExperimentRun]]:
        """Run a list of experiments respecting the parallelism limit.

        Returns a dict mapping experiment_id → list of ExperimentRun.
        Stops early on BudgetExceededError.
        """
        results: dict[str, list[ExperimentRun]] = {}

        async def _run_one(exp: Experiment) -> None:
            async with self._semaphore:
                if self._tracker:
                    self._tracker.check_budget()
                runs = await self.run(exp)
                results[exp.id] = runs

        tasks = [asyncio.create_task(_run_one(exp)) for exp in experiments]
        for task in asyncio.as_completed(tasks):
            try:
                await task
            except BudgetExceededError:
                # Cancel remaining tasks and bail
                for t in tasks:
                    t.cancel()
                break
            except Exception:
                # Individual experiment failures don't stop the batch
                pass

        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute_once(
        self, experiment: Experiment, run_number: int
    ) -> ExperimentRun:
        """Run the target once and persist the result."""
        output = ""
        retrieved_chunks: list[str] = []
        tool_calls: list[dict] = []
        error: Optional[str] = None

        t0 = time.monotonic()
        try:
            result: TargetResult = await asyncio.wait_for(
                self._target.run(
                    query=experiment.input,
                    context_setup=experiment.context_setup,
                ),
                timeout=self._timeout,
            )
            output = result.output or ""
            retrieved_chunks = result.retrieved_chunks
            tool_calls = result.tool_calls
            if result.error:
                error = result.error

        except asyncio.TimeoutError:
            error = f"Timeout after {self._timeout:.0f}s"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        latency_ms = int((time.monotonic() - t0) * 1000)

        run = ExperimentRun(
            experiment_id=experiment.id,
            run_number=run_number,
            input=experiment.input,
            output=output,
            retrieved_chunks=retrieved_chunks,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            error=error,
            timestamp=datetime.now(timezone.utc),
        )

        async with get_session() as session:
            session.add(run)

        return run
