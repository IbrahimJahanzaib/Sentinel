"""Metric calculation from raw research cycle and attack scan results."""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Optional

from sentinel.benchmark.models import BenchmarkMetrics

if TYPE_CHECKING:
    from sentinel.attacks.models import ScanResult
    from sentinel.core.control_plane import CycleResult
    from sentinel.core.cost_tracker import CostTracker


# Severity numeric scores
_SEVERITY_SCORES = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4}


class MetricsCalculator:
    """Computes benchmark metrics from raw research cycle and attack scan results."""

    def calculate(
        self,
        cycle_results: list[CycleResult],
        attack_scan: Optional[ScanResult] = None,
        cost_tracker: Optional[CostTracker] = None,
    ) -> BenchmarkMetrics:
        # ── Collect all artefacts across cycles ──
        all_experiments = []
        all_failures = []
        all_interventions = []
        all_hypotheses = []
        all_latencies: list[float] = []
        all_runs = []

        for cycle in cycle_results:
            all_hypotheses.extend(cycle.hypotheses)
            all_experiments.extend(cycle.experiments)
            all_failures.extend(cycle.failures)
            all_interventions.extend(cycle.interventions)

            # Collect runs from the CycleResult's runs dict {experiment_id: [runs]}
            for exp_id, runs in cycle.runs.items():
                all_runs.extend(runs)
                for run in runs:
                    if run.latency_ms:
                        all_latencies.append(float(run.latency_ms))

        total_experiments = len(all_experiments)
        total_runs = len(all_runs)

        # ── Core Reliability ──
        # An experiment has failures if any Failure references it
        failed_exp_ids = {f.experiment_id for f in all_failures}
        failed_count = len(
            [e for e in all_experiments if e.id in failed_exp_ids]
        )
        success_rate = (
            1.0 - (failed_count / total_experiments)
            if total_experiments > 0
            else 1.0
        )
        failure_rate = 1.0 - success_rate

        # Failure rate by class
        failure_rate_by_class: dict[str, float] = {}
        class_counts: dict[str, int] = {}
        for f in all_failures:
            cls = f.failure_class
            class_counts[cls] = class_counts.get(cls, 0) + 1
        for cls, count in class_counts.items():
            failure_rate_by_class[cls] = (
                count / total_experiments if total_experiments > 0 else 0
            )

        # ── Severity Distribution ──
        severity_distribution = {"S0": 0, "S1": 0, "S2": 0, "S3": 0, "S4": 0}
        for f in all_failures:
            sev = f.severity
            if sev in severity_distribution:
                severity_distribution[sev] += 1

        total_failures = len(all_failures)
        mean_severity = 0.0
        max_severity = "S0"
        if total_failures > 0:
            mean_severity = (
                sum(_SEVERITY_SCORES.get(f.severity, 0) for f in all_failures)
                / total_failures
            )
            max_severity = max(
                all_failures,
                key=lambda f: _SEVERITY_SCORES.get(f.severity, 0),
            ).severity

        # ── Intervention Effectiveness ──
        interventions_proposed = len(all_interventions)
        # validated = anything not pending
        interventions_validated = len(
            [i for i in all_interventions if i.validation_status != "pending"]
        )
        interventions_successful = len(
            [i for i in all_interventions if i.validation_status == "fixed"]
        )
        intervention_effectiveness = (
            interventions_successful / interventions_validated
            if interventions_validated > 0
            else 0.0
        )

        # ── Discovery Efficiency ──
        unique_failures = len({f.id for f in all_failures})
        hypotheses_tested = len(all_hypotheses)
        hypotheses_confirmed = len(
            [h for h in all_hypotheses if h.status == "confirmed"]
        )
        hypothesis_confirmation_rate = (
            hypotheses_confirmed / hypotheses_tested
            if hypotheses_tested > 0
            else 0.0
        )
        failure_discovery_rate = (
            unique_failures / hypotheses_tested
            if hypotheses_tested > 0
            else 0.0
        )

        # ── Cost ──
        total_cost = cost_tracker.total_cost_usd if cost_tracker else 0.0
        total_tokens = (
            cost_tracker.total_input_tokens + cost_tracker.total_output_tokens
            if cost_tracker
            else 0
        )
        total_llm_calls = cost_tracker.total_calls if cost_tracker else 0
        cost_per_discovery = (
            total_cost / unique_failures
            if unique_failures > 0
            else float("inf")
        )

        # ── Performance ──
        if all_latencies:
            sorted_lat = sorted(all_latencies)
            n = len(sorted_lat)
            mean_latency = statistics.mean(sorted_lat)
            p50_latency = sorted_lat[int(n * 0.50)]
            p95_latency = sorted_lat[min(int(n * 0.95), n - 1)]
            p99_latency = sorted_lat[min(int(n * 0.99), n - 1)]
            max_latency = sorted_lat[-1]
        else:
            mean_latency = p50_latency = p95_latency = p99_latency = max_latency = 0.0

        timeout_count = len(
            [r for r in all_runs if r.error and "timeout" in r.error.lower()]
        )
        error_count = len([r for r in all_runs if r.error])
        timeout_rate = timeout_count / total_runs if total_runs > 0 else 0.0
        error_rate = error_count / total_runs if total_runs > 0 else 0.0

        # ── Consistency ──
        # Group runs by experiment, check if same input → same output
        exp_to_runs: dict[str, list] = {}
        for run in all_runs:
            exp_to_runs.setdefault(run.experiment_id, []).append(run)

        consistency_scores: list[float] = []
        for runs in exp_to_runs.values():
            if len(runs) < 2:
                continue
            outputs = [r.output.strip() for r in runs if r.output]
            if len(outputs) < 2:
                continue
            unique_outputs = len(set(outputs))
            score = 1.0 - ((unique_outputs - 1) / (len(outputs) - 1))
            consistency_scores.append(max(0.0, score))

        consistency_score = (
            statistics.mean(consistency_scores) if consistency_scores else 1.0
        )
        non_determinism_rate = 1.0 - consistency_score

        # ── Attack Surface ──
        attack_probes_run = 0
        attack_vulns_found = 0
        attack_vulnerability_rate = 0.0
        attack_by_category: dict[str, dict] = {}

        if attack_scan:
            attack_probes_run = attack_scan.total_probes
            attack_vulns_found = attack_scan.vulnerable_probes
            attack_vulnerability_rate = attack_scan.vulnerability_rate
            attack_by_category = attack_scan.by_category

        return BenchmarkMetrics(
            success_rate=success_rate,
            failure_rate=failure_rate,
            failure_rate_by_class=failure_rate_by_class,
            severity_distribution=severity_distribution,
            mean_severity_score=mean_severity,
            max_severity=max_severity,
            interventions_proposed=interventions_proposed,
            interventions_validated=interventions_validated,
            interventions_successful=interventions_successful,
            intervention_effectiveness_rate=intervention_effectiveness,
            unique_failures_found=unique_failures,
            hypotheses_tested=hypotheses_tested,
            hypotheses_confirmed=hypotheses_confirmed,
            hypothesis_confirmation_rate=hypothesis_confirmation_rate,
            failure_discovery_rate=failure_discovery_rate,
            total_cost_usd=total_cost,
            cost_per_discovery_usd=cost_per_discovery,
            total_tokens=total_tokens,
            total_llm_calls=total_llm_calls,
            mean_latency_ms=mean_latency,
            p50_latency_ms=p50_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            max_latency_ms=max_latency,
            timeout_count=timeout_count,
            timeout_rate=timeout_rate,
            error_count=error_count,
            error_rate=error_rate,
            consistency_score=consistency_score,
            non_determinism_rate=non_determinism_rate,
            attack_probes_run=attack_probes_run,
            attack_vulnerabilities_found=attack_vulns_found,
            attack_vulnerability_rate=attack_vulnerability_rate,
            attack_results_by_category=attack_by_category,
        )
