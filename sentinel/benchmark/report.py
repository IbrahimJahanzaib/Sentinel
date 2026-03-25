"""Benchmark-specific report generation (markdown, JSON)."""

from __future__ import annotations

from sentinel.benchmark.models import BenchmarkResult, ComparisonResult, RegressionResult


class BenchmarkReporter:

    def result_to_markdown(self, result: BenchmarkResult) -> str:
        """Generate markdown report for a single benchmark run."""
        m = result.metrics
        lines: list[str] = []
        lines.append("# Sentinel Benchmark Report")
        lines.append("")
        lines.append(f"**Benchmark ID:** {result.benchmark_id}")
        lines.append(f"**Model:** {result.model_name} ({result.model_provider})")
        lines.append(f"**Date:** {result.started_at.strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"**Duration:** {result.duration_seconds:.1f}s")
        lines.append(f"**Profile:** {result.config.name}")
        lines.append("")

        lines.append("## Reliability")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Success Rate | {m.success_rate:.1%} |")
        lines.append(f"| Failure Rate | {m.failure_rate:.1%} |")
        lines.append(f"| Max Severity | {m.max_severity} |")
        lines.append(f"| Mean Severity | {m.mean_severity_score:.2f} |")
        lines.append(f"| Consistency | {m.consistency_score:.1%} |")
        lines.append("")

        lines.append("## Failure Distribution")
        lines.append("| Severity | Count |")
        lines.append("|----------|-------|")
        for sev in ["S4", "S3", "S2", "S1", "S0"]:
            count = m.severity_distribution.get(sev, 0)
            if count > 0:
                lines.append(f"| {sev} | {count} |")
        lines.append("")

        if m.failure_rate_by_class:
            lines.append("## Failures by Class")
            lines.append("| Class | Rate |")
            lines.append("|-------|------|")
            for cls, rate in sorted(
                m.failure_rate_by_class.items(), key=lambda x: -x[1]
            ):
                lines.append(f"| {cls} | {rate:.1%} |")
            lines.append("")

        lines.append("## Discovery Efficiency")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Hypotheses Tested | {m.hypotheses_tested} |")
        lines.append(
            f"| Hypotheses Confirmed | {m.hypotheses_confirmed} "
            f"({m.hypothesis_confirmation_rate:.0%}) |"
        )
        lines.append(f"| Unique Failures Found | {m.unique_failures_found} |")
        lines.append(
            f"| Discovery Rate | {m.failure_discovery_rate:.2f} per hypothesis |"
        )
        lines.append(f"| Cost per Discovery | ${m.cost_per_discovery_usd:.2f} |")
        lines.append("")

        lines.append("## Interventions")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Proposed | {m.interventions_proposed} |")
        lines.append(f"| Validated | {m.interventions_validated} |")
        lines.append(f"| Effective | {m.interventions_successful} |")
        lines.append(
            f"| Effectiveness Rate | {m.intervention_effectiveness_rate:.0%} |"
        )
        lines.append("")

        lines.append("## Performance")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Mean Latency | {m.mean_latency_ms:.0f}ms |")
        lines.append(f"| P50 Latency | {m.p50_latency_ms:.0f}ms |")
        lines.append(f"| P95 Latency | {m.p95_latency_ms:.0f}ms |")
        lines.append(f"| P99 Latency | {m.p99_latency_ms:.0f}ms |")
        lines.append(f"| Error Rate | {m.error_rate:.1%} |")
        lines.append(f"| Timeout Rate | {m.timeout_rate:.1%} |")
        lines.append("")

        lines.append("## Cost")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Cost | ${m.total_cost_usd:.2f} |")
        lines.append(f"| Total Tokens | {m.total_tokens:,} |")
        lines.append(f"| Total LLM Calls | {m.total_llm_calls} |")
        lines.append("")

        if m.attack_probes_run > 0:
            lines.append("## Attack Surface")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Probes Run | {m.attack_probes_run} |")
            lines.append(f"| Vulnerabilities | {m.attack_vulnerabilities_found} |")
            lines.append(
                f"| Vulnerability Rate | {m.attack_vulnerability_rate:.1%} |"
            )
            lines.append("")

            if m.attack_results_by_category:
                lines.append("| Category | Total | Vulnerable | Rate |")
                lines.append("|----------|-------|------------|------|")
                for cat, data in sorted(m.attack_results_by_category.items()):
                    total = data.get("total", 1)
                    vuln = data.get("vulnerable", 0)
                    rate = vuln / total if total > 0 else 0
                    lines.append(f"| {cat} | {total} | {vuln} | {rate:.0%} |")
                lines.append("")

        return "\n".join(lines)

    def comparison_to_markdown(self, comparison: ComparisonResult) -> str:
        """Generate markdown report for a cross-model comparison."""
        lines: list[str] = []
        lines.append("# Sentinel Cross-Model Comparison")
        lines.append("")
        lines.append(f"**Comparison ID:** {comparison.comparison_id}")
        lines.append(
            f"**Date:** {comparison.created_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        lines.append(
            f"**Models:** {', '.join(r.model_name for r in comparison.results)}"
        )
        lines.append(f"**Profile:** {comparison.config.name}")
        lines.append("")

        # Overview table
        lines.append("## Overview")
        lines.append("")
        header = "| Metric |" + " | ".join(
            r.model_name for r in comparison.results
        ) + " |"
        separator = "|--------|" + " | ".join(
            "------" for _ in comparison.results
        ) + " |"
        lines.append(header)
        lines.append(separator)

        metrics_to_show = [
            ("Success Rate", lambda m: f"{m.success_rate:.1%}"),
            ("Failure Rate", lambda m: f"{m.failure_rate:.1%}"),
            ("Max Severity", lambda m: m.max_severity),
            ("Unique Failures", lambda m: str(m.unique_failures_found)),
            ("Consistency", lambda m: f"{m.consistency_score:.1%}"),
            ("Mean Latency", lambda m: f"{m.mean_latency_ms:.0f}ms"),
            ("P95 Latency", lambda m: f"{m.p95_latency_ms:.0f}ms"),
            ("Cost", lambda m: f"${m.total_cost_usd:.2f}"),
            ("Cost/Discovery", lambda m: f"${m.cost_per_discovery_usd:.2f}"),
            ("Vuln Rate", lambda m: f"{m.attack_vulnerability_rate:.1%}"),
            (
                "Intervention Effectiveness",
                lambda m: f"{m.intervention_effectiveness_rate:.0%}",
            ),
        ]

        for label, formatter in metrics_to_show:
            row = f"| {label} |"
            for r in comparison.results:
                row += f" {formatter(r.metrics)} |"
            lines.append(row)
        lines.append("")

        # Rankings
        lines.append("## Rankings (Best to Worst)")
        lines.append("")
        lines.append("| Metric | Ranking |")
        lines.append("|--------|---------|")
        for metric, ranking in comparison.rankings.items():
            lines.append(f"| {metric} | {' > '.join(ranking)} |")
        lines.append("")

        if comparison.summary:
            lines.append("## Analysis")
            lines.append("")
            lines.append(comparison.summary)
            lines.append("")

        return "\n".join(lines)

    def regression_to_markdown(self, regression: RegressionResult) -> str:
        """Generate markdown report for a regression check."""
        status = "PASSED" if regression.passed else "FAILED"
        lines: list[str] = []
        lines.append(f"# Sentinel Regression Report: {status}")
        lines.append("")
        lines.append(
            f"**Threshold:** {regression.max_regression_allowed:.0%} "
            "max regression allowed"
        )
        lines.append(f"**Worst regression:** {regression.worst_regression:.1%}")
        lines.append(f"**Status:** {'PASS' if regression.passed else 'FAIL'}")
        lines.append("")

        if regression.regressions:
            lines.append(f"## Regressions ({len(regression.regressions)})")
            lines.append("| Metric | Baseline | Current | Delta |")
            lines.append("|--------|----------|---------|-------|")
            for r in sorted(
                regression.regressions, key=lambda x: abs(x["delta"]), reverse=True
            ):
                lines.append(
                    f"| {r['metric']} | {r['baseline']} | {r['current']} "
                    f"| {r['delta']:+.4f} |"
                )
            lines.append("")

        if regression.improvements:
            lines.append(f"## Improvements ({len(regression.improvements)})")
            lines.append("| Metric | Baseline | Current | Delta |")
            lines.append("|--------|----------|---------|-------|")
            for r in sorted(
                regression.improvements, key=lambda x: abs(x["delta"]), reverse=True
            ):
                lines.append(
                    f"| {r['metric']} | {r['baseline']} | {r['current']} "
                    f"| {r['delta']:+.4f} |"
                )
            lines.append("")

        return "\n".join(lines)

    def result_to_json(self, result: BenchmarkResult) -> dict:
        """Convert to JSON-serializable dict."""
        return result.model_dump(mode="json")

    def comparison_to_json(self, comparison: ComparisonResult) -> dict:
        """Convert to JSON-serializable dict."""
        return comparison.model_dump(mode="json")
