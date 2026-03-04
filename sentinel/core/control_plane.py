"""Control Plane — orchestrates the full Sentinel research cycle.

Wires together all 6 agents, approval gate, cost tracker, and DB persistence
into a single ``research_cycle()`` call.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from rich.console import Console
from rich.rule import Rule
from sqlalchemy import update

from sentinel.agents.base import TargetSystem
from sentinel.agents.experiment_architect import ExperimentArchitect
from sentinel.agents.experiment_executor import ExperimentExecutor
from sentinel.agents.failure_discovery import FailureDiscovery
from sentinel.agents.hypothesis_engine import HypothesisEngine
from sentinel.agents.intervention_engine import InterventionEngine
from sentinel.agents.simulation_engine import SimulationEngine
from sentinel.config.modes import Mode
from sentinel.config.settings import SentinelSettings
from sentinel.core.approval_gate import ApprovalGate
from sentinel.core.cost_tracker import BudgetExceededError, CostTracker
from sentinel.core.risk_policy import ActionType, RiskPolicy
from sentinel.db.connection import get_session
from sentinel.db.models import Cycle, Experiment, ExperimentRun, Failure, Hypothesis
from sentinel.integrations.model_client import ModelClient
from sentinel.memory.graph import MemoryGraph
from sentinel.memory.repository import MemoryRepository
from sentinel.taxonomy.failure_types import Severity

if TYPE_CHECKING:
    pass

console = Console()

# ---------------------------------------------------------------------------
# Cycle result
# ---------------------------------------------------------------------------

class CycleResult:
    """Holds all artefacts produced by a research cycle."""

    def __init__(self) -> None:
        self.cycle_id: str = ""
        self.hypotheses: list[Hypothesis] = []
        self.experiments: list[Experiment] = []
        self.runs: dict[str, list[ExperimentRun]] = {}
        self.failures: list[Failure] = []
        self.interventions: list = []
        self.validations: list = []
        self.cost_summary: dict = {}

    @property
    def confirmed_failures(self) -> list[Failure]:
        return [f for f in self.failures if f.hypothesis_confirmed]


# ---------------------------------------------------------------------------
# Control Plane
# ---------------------------------------------------------------------------

class ControlPlane:
    """Orchestrates a full Sentinel research cycle.

    Parameters
    ----------
    settings:
        Loaded SentinelSettings.
    client:
        Async ModelClient for all LLM calls.
    target:
        The system under test.
    tracker:
        CostTracker for budget enforcement.
    """

    def __init__(
        self,
        settings: SentinelSettings,
        client: ModelClient,
        target: TargetSystem,
        tracker: Optional[CostTracker] = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._target = target
        self._tracker = tracker or CostTracker(
            budget_usd=settings.experiments.cost_limit_usd,
        )

        # Approval infrastructure
        self._risk_policy = RiskPolicy(
            auto_approve_safe=settings.risk.auto_approve_safe,
            block_on_destructive=settings.risk.block_on_destructive,
        )
        self._approval_gate = ApprovalGate(
            mode=settings.approval.mode,
            timeout_seconds=settings.approval.timeout_seconds,
            audit_mode=settings.mode.value,
        )

        # Memory graph
        self._memory_repo = MemoryRepository()
        self._memory_graph = MemoryGraph(repository=self._memory_repo)

        # Agents
        self._hypothesis_engine = HypothesisEngine(
            client=client,
            focus_areas=["REASONING", "TOOL_USE"],
            max_hypotheses=settings.research.max_hypotheses_per_run,
            memory_graph=self._memory_graph,
        )
        self._experiment_architect = ExperimentArchitect(
            client=client,
            max_experiments=settings.research.max_experiments_per_hypothesis,
            default_runs=settings.research.default_runs_per_experiment,
        )
        self._executor = ExperimentExecutor(
            target=target,
            cost_tracker=self._tracker,
            timeout_seconds=settings.experiments.default_timeout_seconds,
            max_parallel=settings.experiments.max_parallel,
        )
        self._failure_discovery = FailureDiscovery(client=client)
        self._intervention_engine = InterventionEngine(client=client)
        self._simulation_engine = SimulationEngine(
            target=target,
            cost_tracker=self._tracker,
            timeout_seconds=settings.experiments.default_timeout_seconds,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def research_cycle(
        self,
        focus: Optional[str] = None,
        max_hypotheses: Optional[int] = None,
        max_experiments: Optional[int] = None,
        system_description: Optional[str] = None,
    ) -> CycleResult:
        """Run a full research cycle.

        Parameters
        ----------
        focus:
            Natural language or failure class to focus on.
        max_hypotheses:
            Override max hypotheses.
        max_experiments:
            Override max experiments per hypothesis.
        system_description:
            Override the target's own description.

        Returns
        -------
        CycleResult
            All artefacts produced during the cycle.
        """
        cycle_id = f"cycle_{uuid.uuid4().hex[:8]}"
        result = CycleResult()
        result.cycle_id = cycle_id
        description = system_description or self._target.describe()

        # Create DB cycle record
        cycle = Cycle(
            id=cycle_id,
            target_description=description[:500],
            focus=focus,
            mode=self._settings.mode.value,
            started_at=datetime.now(timezone.utc),
        )
        async with get_session() as session:
            session.add(cycle)

        self._header(cycle_id, focus)
        self._tracker.reset()

        # Load memory graph so hypothesis engine can use past findings
        try:
            await self._memory_graph.load()
            if self._memory_graph.node_count > 0:
                self._log(f"  Memory graph loaded: {self._memory_graph.node_count} nodes, {self._memory_graph.edge_count} edges\n")
        except Exception:
            pass  # first cycle — no graph yet

        try:
            # ── Step 1: Generate hypotheses ──────────────────────
            self._log(Rule("[bold blue]Step 1 — Generating Hypotheses"))
            focus_areas = [focus.upper()] if focus and focus.upper() in (
                "REASONING", "LONG_CONTEXT", "TOOL_USE",
                "FEEDBACK_LOOP", "DEPLOYMENT", "SECURITY",
            ) else None

            hypotheses = await self._hypothesis_engine.generate(
                system_description=description,
                cycle_id=cycle_id,
                focus_areas=focus_areas,
                n=max_hypotheses,
            )
            result.hypotheses = hypotheses
            for h in hypotheses:
                self._log(f"  [green]+[/green] [{h.failure_class}] [{h.expected_severity}] {h.description[:80]}")
            self._log(f"  → {len(hypotheses)} hypotheses generated\n")

            # ── Step 2–7: Per-hypothesis pipeline ────────────────
            for hyp in hypotheses:
                await self._process_hypothesis(
                    hyp, description, cycle_id, max_experiments, result,
                )

        except BudgetExceededError as exc:
            self._log(f"\n[yellow]Budget exceeded — stopping early: {exc}[/yellow]")

        # ── Finalise cycle record ────────────────────────────
        cost = self._tracker.summary()
        result.cost_summary = cost

        async with get_session() as session:
            await session.execute(
                update(Cycle).where(Cycle.id == cycle_id).values(
                    hypotheses_generated=len(result.hypotheses),
                    hypotheses_confirmed=len(result.confirmed_failures),
                    experiments_run=sum(len(r) for r in result.runs.values()),
                    failures_found=len(result.failures),
                    ended_at=datetime.now(timezone.utc),
                    total_cost_usd=cost["total_cost_usd"],
                    total_tokens=cost["total_input_tokens"] + cost["total_output_tokens"],
                )
            )

        # ── Populate memory graph from this cycle ───────────
        try:
            n_nodes = await self._memory_repo.populate_from_cycle(cycle_id)
            await self._memory_repo.link_related_failures()
            self._log(f"  Memory graph updated: {n_nodes} nodes added")
        except Exception as exc:
            self._log(f"  [yellow]Memory graph update failed: {exc}[/yellow]")

        self._summary(result)
        return result

    # ------------------------------------------------------------------
    # Per-hypothesis pipeline
    # ------------------------------------------------------------------

    async def _process_hypothesis(
        self,
        hypothesis: Hypothesis,
        description: str,
        cycle_id: str,
        max_experiments: Optional[int],
        result: CycleResult,
    ) -> None:
        self._log(Rule(f"[bold cyan]Hypothesis: {hypothesis.id}"))
        self._log(f"  {hypothesis.description[:100]}")

        # ── Step 2: Design experiments ───────────────────────
        experiments = await self._experiment_architect.design(
            hypothesis=hypothesis,
            system_description=description,
            n=max_experiments,
        )
        result.experiments.extend(experiments)
        self._log(f"  → {len(experiments)} experiments designed")

        for exp in experiments:
            # ── Step 3: Approval gate ────────────────────────
            evaluation = self._risk_policy.evaluate(
                action=ActionType.EXECUTE_EXPERIMENT,
                mode=self._settings.mode,
                severity=Severity(hypothesis.expected_severity)
                if hypothesis.expected_severity in {s.value for s in Severity}
                else None,
            )
            decision = await self._approval_gate.check(
                evaluation,
                entity_type="experiment",
                entity_id=exp.id,
            )

            if decision.rejected:
                self._log(f"  [yellow]⊘[/yellow] {exp.id} — {decision.reason}")
                async with get_session() as session:
                    await session.execute(
                        update(Experiment)
                        .where(Experiment.id == exp.id)
                        .values(approval_status="rejected")
                    )
                continue

            # Update approval status
            status = "auto_approved" if decision.actor == "auto" else "approved"
            async with get_session() as session:
                await session.execute(
                    update(Experiment)
                    .where(Experiment.id == exp.id)
                    .values(approval_status=status)
                )

            # ── Step 4: Execute ──────────────────────────────
            self._tracker.check_budget()
            runs = await self._executor.run(exp)
            result.runs[exp.id] = runs
            n_errors = sum(1 for r in runs if r.error)
            self._log(
                f"  [green]✓[/green] {exp.id} — {len(runs)} runs "
                f"({n_errors} errors)"
            )

            # ── Step 5: Classify ─────────────────────────────
            failure = await self._failure_discovery.classify(
                experiment=exp,
                runs=runs,
                hypothesis=hypothesis,
                cycle_id=cycle_id,
            )
            result.failures.append(failure)

            tag = "[green]CONFIRMED[/green]" if failure.hypothesis_confirmed else "[dim]rejected[/dim]"
            self._log(
                f"    [{failure.severity}] {failure.failure_class}"
                f"/{failure.failure_subtype or '—'} — "
                f"rate {failure.failure_rate:.0%} {tag}"
            )

            if not failure.hypothesis_confirmed:
                continue

            # ── Step 6: Propose interventions ────────────────
            interventions = await self._intervention_engine.propose(
                failure=failure,
                cycle_id=cycle_id,
            )
            result.interventions.extend(interventions)
            self._log(f"    → {len(interventions)} interventions proposed")

            # ── Step 7: Validate interventions ───────────────
            for intv in interventions:
                # Only validate runtime-applicable types
                if intv.type == "architectural_recommendation":
                    self._log(f"    [dim]↷ {intv.id} — architectural; skipping simulation[/dim]")
                    continue

                val_eval = self._risk_policy.evaluate(
                    action=ActionType.VALIDATE_INTERVENTION,
                    mode=self._settings.mode,
                    severity=Severity(failure.severity)
                    if failure.severity in {s.value for s in Severity}
                    else None,
                )
                val_decision = await self._approval_gate.check(
                    val_eval,
                    entity_type="intervention",
                    entity_id=intv.id,
                )
                if val_decision.rejected:
                    self._log(f"    [yellow]⊘[/yellow] {intv.id} — validation blocked")
                    continue

                val_result = await self._simulation_engine.validate(
                    intervention=intv,
                    experiments=[exp],
                    failure=failure,
                )
                result.validations.append(val_result)
                status_icon = {
                    "fixed": "[green]FIXED[/green]",
                    "partially_fixed": "[yellow]PARTIAL[/yellow]",
                    "no_effect": "[dim]no effect[/dim]",
                    "regression": "[red]REGRESSION[/red]",
                }.get(val_result.status, val_result.status)
                self._log(f"    ↪ {intv.id} — {status_icon} ({val_result.notes[:60]})")

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        console.print(msg)

    def _header(self, cycle_id: str, focus: Optional[str]) -> None:
        self._log("")
        self._log(Rule(f"[bold]SENTINEL — Research Cycle {cycle_id}"))
        self._log(f"  Mode   : [cyan]{self._settings.mode.value.upper()}[/cyan]")
        self._log(f"  Focus  : [cyan]{focus or 'all'}[/cyan]")
        self._log(f"  Budget : [cyan]${self._tracker._budget or '∞':.2f}[/cyan]")
        self._log("")

    def _summary(self, result: CycleResult) -> None:
        self._log("")
        self._log(Rule("[bold green]Cycle Complete"))
        self._log(f"  Hypotheses generated  : {len(result.hypotheses)}")
        self._log(f"  Hypotheses confirmed  : {len(result.confirmed_failures)}")
        self._log(f"  Experiments run       : {sum(len(r) for r in result.runs.values())}")
        self._log(f"  Failures classified   : {len(result.failures)}")
        self._log(f"  Interventions proposed : {len(result.interventions)}")
        self._log(f"  Validations run       : {len(result.validations)}")

        # Severity breakdown
        sev: dict[str, int] = {}
        for f in result.confirmed_failures:
            sev[f.severity] = sev.get(f.severity, 0) + 1
        if sev:
            breakdown = " | ".join(f"{k}:{v}" for k, v in sorted(sev.items()))
            self._log(f"  Severity breakdown    : {breakdown}")

        cost = result.cost_summary
        self._log(f"  LLM calls             : {cost.get('total_calls', 0)}")
        self._log(f"  Total cost            : ${cost.get('total_cost_usd', 0):.4f}")
        self._log("")
