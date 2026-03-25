"""Benchmark orchestrator — runs research cycles + attack scans + calculates metrics."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional

from rich.console import Console

from sentinel.benchmark.metrics import MetricsCalculator
from sentinel.benchmark.models import (
    BenchmarkConfig,
    BenchmarkResult,
    ComparisonResult,
)
from sentinel.benchmark.profiles import get_profile
from sentinel.config.settings import load_settings
from sentinel.core.control_plane import ControlPlane
from sentinel.core.cost_tracker import CostTracker
from sentinel.integrations.model_client import build_default_client

if TYPE_CHECKING:
    from sentinel.agents.base import TargetSystem
    from sentinel.attacks.models import ScanResult

console = Console()


class BenchmarkSuite:
    """Orchestrates benchmark runs: research cycles + attack scans + metric calculation."""

    def __init__(self) -> None:
        self.metrics_calculator = MetricsCalculator()

    async def run(
        self,
        target: TargetSystem,
        config: Optional[BenchmarkConfig] = None,
        profile: Optional[str] = None,
    ) -> BenchmarkResult:
        """Run a full benchmark against a single target."""
        if profile and not config:
            config = get_profile(profile)
        config = config or get_profile("standard")

        benchmark_id = f"bench_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc)
        cost_tracker = CostTracker()
        settings = load_settings()
        client = build_default_client(settings)

        console.print(f"\n{'=' * 60}")
        console.print(f"  SENTINEL BENCHMARK: {config.name}")
        console.print(f"  Target: {target.describe()[:80]}...")
        console.print(f"  Focus: {', '.join(config.focus_areas)}")
        console.print(f"  Attack scan: {'Yes' if config.include_attack_scan else 'No'}")
        console.print(f"{'=' * 60}\n")

        # ── Run research cycles for each focus area ──
        control_plane = ControlPlane(
            settings=settings,
            client=client,
            target=target,
            tracker=cost_tracker,
        )
        all_cycle_results = []
        cycle_ids: list[str] = []

        for i, focus in enumerate(config.focus_areas):
            console.print(
                f"[{i + 1}/{len(config.focus_areas)}] Research cycle: focus={focus}"
            )
            result = await control_plane.research_cycle(
                focus=focus,
                max_hypotheses=config.max_hypotheses_per_focus,
                max_experiments=config.max_experiments_per_hypothesis,
            )
            all_cycle_results.append(result)
            cycle_ids.append(result.cycle_id)
            console.print(
                f"    Hypotheses: {len(result.hypotheses)}, "
                f"Failures: {len(result.failures)}, "
                f"Interventions: {len(result.interventions)}"
            )

        # ── Run attack scan if configured ──
        attack_scan: Optional[ScanResult] = None
        attack_scan_id: Optional[str] = None
        if config.include_attack_scan:
            console.print("\nRunning attack scan...")
            from sentinel.attacks.classifier import VulnerabilityClassifier
            from sentinel.attacks.runner import AttackRunner

            classifier = VulnerabilityClassifier(client=client)
            attack_runner = AttackRunner(
                classifier=classifier,
                cost_tracker=cost_tracker,
            )
            attack_scan = await attack_runner.scan(
                target=target,
                categories=config.attack_categories or None,
                min_severity=config.attack_min_severity,
            )
            attack_scan_id = attack_scan.scan_id
            console.print(
                f"    Probes: {attack_scan.total_probes}, "
                f"Vulnerabilities: {attack_scan.vulnerable_probes}"
            )

        # ── Calculate metrics ──
        console.print("\nCalculating metrics...")
        metrics = self.metrics_calculator.calculate(
            cycle_results=all_cycle_results,
            attack_scan=attack_scan,
            cost_tracker=cost_tracker,
        )

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        model_name = getattr(client, "model", "unknown")
        model_provider = getattr(client, "provider", "unknown")

        bench_result = BenchmarkResult(
            benchmark_id=benchmark_id,
            model_name=str(model_name),
            model_provider=str(model_provider),
            target_description=target.describe(),
            config=config,
            metrics=metrics,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            cycle_ids=cycle_ids,
            attack_scan_id=attack_scan_id,
        )

        self._print_summary(bench_result)
        return bench_result

    async def compare_models(
        self,
        target_factory: Callable[..., Any],
        models: list[dict[str, str]],
        config: Optional[BenchmarkConfig] = None,
        profile: Optional[str] = None,
    ) -> ComparisonResult:
        """Run the same benchmark across multiple models and compare.

        Parameters
        ----------
        target_factory:
            callable(model_name=str) -> TargetSystem
        models:
            [{"provider": "anthropic", "model": "claude-sonnet-4-20250514"}, ...]
        """
        if profile and not config:
            config = get_profile(profile)
        config = config or get_profile("standard")

        comparison_id = f"cmp_{uuid.uuid4().hex[:8]}"
        results: list[BenchmarkResult] = []

        console.print(f"\n{'=' * 60}")
        console.print("  CROSS-MODEL COMPARISON")
        console.print(f"  Models: {', '.join(m['model'] for m in models)}")
        console.print(f"  Profile: {config.name}")
        console.print(f"{'=' * 60}\n")

        for idx, model_info in enumerate(models):
            provider = model_info["provider"]
            model_name = model_info["model"]

            console.print(
                f"\n[{idx + 1}/{len(models)}] Benchmarking: {model_name} ({provider})"
            )
            console.print(f"{'-' * 40}")

            target = target_factory(model_name=model_name)
            try:
                result = await self.run(target, config=config)
                result.model_name = model_name
                result.model_provider = provider
                results.append(result)
            except Exception as exc:
                console.print(f"  [red]FAILED: {exc}[/red]")

        rankings = self._generate_rankings(results)
        summary = self._generate_comparison_summary_sync(results, rankings)

        return ComparisonResult(
            comparison_id=comparison_id,
            target_description=results[0].target_description if results else "",
            config=config,
            results=results,
            rankings=rankings,
            summary=summary,
            created_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_rankings(
        self, results: list[BenchmarkResult]
    ) -> dict[str, list[str]]:
        """Rank models by each metric."""
        if not results:
            return {}

        rankings: dict[str, list[str]] = {}

        # Higher is better
        for metric in [
            "success_rate",
            "consistency_score",
            "intervention_effectiveness_rate",
            "hypothesis_confirmation_rate",
            "failure_discovery_rate",
        ]:
            sorted_r = sorted(
                results,
                key=lambda r: getattr(r.metrics, metric, 0),
                reverse=True,
            )
            rankings[metric] = [r.model_name for r in sorted_r]

        # Lower is better
        for metric in [
            "failure_rate",
            "mean_severity_score",
            "cost_per_discovery_usd",
            "mean_latency_ms",
            "p95_latency_ms",
            "attack_vulnerability_rate",
            "error_rate",
            "timeout_rate",
            "non_determinism_rate",
        ]:
            sorted_r = sorted(
                results,
                key=lambda r: getattr(r.metrics, metric, float("inf")),
            )
            rankings[metric] = [r.model_name for r in sorted_r]

        return rankings

    def _generate_comparison_summary_sync(
        self, results: list[BenchmarkResult], rankings: dict[str, list[str]]
    ) -> str:
        """Generate a deterministic comparison summary (no LLM call)."""
        if not results:
            return "No results to compare."

        lines = ["Cross-model comparison summary:\n"]
        for r in results:
            m = r.metrics
            lines.append(f"## {r.model_name} ({r.model_provider})")
            lines.append(f"  Success rate: {m.success_rate:.1%}")
            lines.append(f"  Failure rate: {m.failure_rate:.1%}")
            lines.append(f"  Mean severity: {m.mean_severity_score:.2f}")
            lines.append(f"  Unique failures: {m.unique_failures_found}")
            lines.append(f"  Consistency: {m.consistency_score:.1%}")
            lines.append(f"  Mean latency: {m.mean_latency_ms:.0f}ms")
            lines.append(f"  Cost: ${m.total_cost_usd:.2f}")
            lines.append(
                f"  Attack vulnerability rate: {m.attack_vulnerability_rate:.1%}"
            )
            lines.append("")

        lines.append("Rankings (best to worst):")
        for metric, ranking in rankings.items():
            lines.append(f"  {metric}: {' > '.join(ranking)}")

        return "\n".join(lines)

    def _print_summary(self, result: BenchmarkResult) -> None:
        """Print formatted summary to console."""
        m = result.metrics
        console.print(f"\n{'=' * 60}")
        console.print(f"  BENCHMARK SUMMARY: {result.benchmark_id}")
        console.print(f"{'=' * 60}")
        console.print(f"  Model: {result.model_name}")
        console.print(f"  Duration: {result.duration_seconds:.1f}s")
        console.print(
            f"  Cost: ${m.total_cost_usd:.2f} "
            f"({m.total_tokens} tokens, {m.total_llm_calls} calls)"
        )
        console.print()
        console.print("  RELIABILITY")
        console.print(f"    Success rate:     {m.success_rate:.1%}")
        console.print(f"    Failure rate:     {m.failure_rate:.1%}")
        console.print(f"    Max severity:     {m.max_severity}")
        console.print(f"    Mean severity:    {m.mean_severity_score:.2f}")
        console.print(f"    Consistency:      {m.consistency_score:.1%}")
        console.print()
        console.print("  DISCOVERY")
        console.print(
            f"    Hypotheses:       {m.hypotheses_tested} tested, "
            f"{m.hypotheses_confirmed} confirmed"
        )
        console.print(f"    Unique failures:  {m.unique_failures_found}")
        console.print(
            f"    Discovery rate:   {m.failure_discovery_rate:.2f} failures/hypothesis"
        )
        console.print(f"    Cost/discovery:   ${m.cost_per_discovery_usd:.2f}")
        console.print()
        console.print("  INTERVENTIONS")
        console.print(f"    Proposed:         {m.interventions_proposed}")
        console.print(f"    Validated:        {m.interventions_validated}")
        console.print(f"    Effective:        {m.interventions_successful}")
        console.print(f"    Effectiveness:    {m.intervention_effectiveness_rate:.1%}")
        console.print()
        console.print("  PERFORMANCE")
        console.print(f"    Mean latency:     {m.mean_latency_ms:.0f}ms")
        console.print(f"    P95 latency:      {m.p95_latency_ms:.0f}ms")
        console.print(f"    Error rate:       {m.error_rate:.1%}")
        console.print(f"    Timeout rate:     {m.timeout_rate:.1%}")
        if m.attack_probes_run > 0:
            console.print()
            console.print("  ATTACK SURFACE")
            console.print(f"    Probes run:       {m.attack_probes_run}")
            console.print(f"    Vulnerabilities:  {m.attack_vulnerabilities_found}")
            console.print(f"    Vuln rate:        {m.attack_vulnerability_rate:.1%}")
        console.print(f"{'=' * 60}\n")
