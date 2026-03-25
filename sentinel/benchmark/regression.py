"""Baseline save/load and regression detection between benchmark runs."""

from __future__ import annotations

import json
from pathlib import Path

from sentinel.benchmark.models import BenchmarkResult, RegressionResult


class RegressionDetector:
    """Save baselines and detect regressions between benchmark runs."""

    def save_baseline(self, result: BenchmarkResult, path: str) -> None:
        """Save a benchmark result as a baseline JSON file."""
        data = result.model_dump(mode="json")
        Path(path).write_text(json.dumps(data, indent=2))

    def load_baseline(self, path: str) -> BenchmarkResult:
        """Load a baseline from a JSON file."""
        data = json.loads(Path(path).read_text())
        return BenchmarkResult(**data)

    def detect_regression(
        self,
        current: BenchmarkResult,
        baseline: BenchmarkResult,
        max_regression: float = 0.1,
    ) -> RegressionResult:
        """Compare current benchmark against a baseline.

        max_regression: maximum allowed regression as a fraction (e.g. 0.1 = 10%).
        """
        regressions: list[dict] = []
        improvements: list[dict] = []

        # Higher is better (regression = current < baseline)
        higher_better = [
            "success_rate",
            "consistency_score",
            "intervention_effectiveness_rate",
            "hypothesis_confirmation_rate",
            "failure_discovery_rate",
        ]

        # Lower is better (regression = current > baseline)
        lower_better = [
            "failure_rate",
            "mean_severity_score",
            "attack_vulnerability_rate",
            "error_rate",
            "timeout_rate",
            "non_determinism_rate",
            "mean_latency_ms",
            "cost_per_discovery_usd",
        ]

        for metric in higher_better:
            baseline_val = getattr(baseline.metrics, metric, 0)
            current_val = getattr(current.metrics, metric, 0)
            delta = current_val - baseline_val

            entry = {
                "metric": metric,
                "baseline": round(baseline_val, 4),
                "current": round(current_val, 4),
                "delta": round(delta, 4),
                "direction": "higher_better",
            }

            if delta < 0:
                regressions.append(entry)
            elif delta > 0:
                improvements.append(entry)

        for metric in lower_better:
            baseline_val = getattr(baseline.metrics, metric, 0)
            current_val = getattr(current.metrics, metric, 0)
            delta = current_val - baseline_val

            entry = {
                "metric": metric,
                "baseline": round(baseline_val, 4),
                "current": round(current_val, 4),
                "delta": round(delta, 4),
                "direction": "lower_better",
            }

            if delta > 0:  # got worse
                regressions.append(entry)
            elif delta < 0:  # improved
                improvements.append(entry)

        # Worst regression as fraction of baseline
        worst_regression = 0.0
        for r in regressions:
            baseline_val = r["baseline"]
            if baseline_val == 0:
                continue
            pct_change = abs(r["delta"]) / abs(baseline_val)
            worst_regression = max(worst_regression, pct_change)

        passed = worst_regression <= max_regression

        return RegressionResult(
            current=current,
            baseline=baseline,
            regressions=regressions,
            improvements=improvements,
            passed=passed,
            max_regression_allowed=max_regression,
            worst_regression=worst_regression,
        )
