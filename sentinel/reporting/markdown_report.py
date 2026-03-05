"""Markdown report generation for Sentinel findings."""

from __future__ import annotations

from collections import Counter, defaultdict

from sentinel.db.models import Cycle, Failure, Intervention
from sentinel.taxonomy.failure_types import (
    FAILURE_CLASS_DESCRIPTIONS,
    FailureClass,
    Severity,
)


def generate_markdown_report(
    cycles: list[Cycle],
    failures: list[Failure],
    interventions: list[Intervention],
) -> str:
    """Build a full Markdown report string from query results."""
    sections: list[str] = []

    # --- Executive Summary ---
    total_cost = sum(c.total_cost_usd for c in cycles)
    sections.append("# Sentinel Findings Report")
    sections.append("")
    sections.append("## Executive Summary")
    sections.append("")
    sections.append(f"- **Cycles completed:** {len(cycles)}")
    sections.append(f"- **Failures discovered:** {len(failures)}")
    sections.append(f"- **Interventions proposed:** {len(interventions)}")
    sections.append(f"- **Total cost:** ${total_cost:.4f}")

    # --- Severity Distribution ---
    sev_counts: Counter[str] = Counter()
    for f in failures:
        sev_counts[f.severity] += 1

    sections.append("")
    sections.append("## Severity Distribution")
    sections.append("")
    sections.append("| Severity | Label | Action | Count |")
    sections.append("|----------|-------|--------|-------|")
    for sev in (Severity.S4, Severity.S3, Severity.S2, Severity.S1, Severity.S0):
        count = sev_counts.get(sev.value, 0)
        if count > 0:
            sections.append(
                f"| {sev.value} | {sev.label} | {sev.automated_action} | {count} |"
            )

    # --- Findings by Failure Class ---
    by_class: defaultdict[str, list[Failure]] = defaultdict(list)
    for f in failures:
        by_class[f.failure_class].append(f)

    sections.append("")
    sections.append("## Findings by Failure Class")

    for fc in FailureClass:
        class_failures = by_class.get(fc.value, [])
        if not class_failures:
            continue
        desc = FAILURE_CLASS_DESCRIPTIONS.get(fc, "")
        sections.append("")
        sections.append(f"### {fc.value} ({len(class_failures)} findings)")
        sections.append("")
        sections.append(f"> {desc}")
        sections.append("")
        for f in class_failures:
            sev = Severity(f.severity)
            sections.append(
                f"- **[{sev.value}]** {f.failure_subtype or 'general'} "
                f"(rate: {f.failure_rate:.0%}) — {f.evidence[:120]}"
            )

    # --- Interventions & Recommendations ---
    sections.append("")
    sections.append("## Interventions & Recommendations")

    if not interventions:
        sections.append("")
        sections.append("No interventions proposed yet.")
    else:
        by_status: defaultdict[str, list[Intervention]] = defaultdict(list)
        for iv in interventions:
            by_status[iv.validation_status].append(iv)

        for status, items in by_status.items():
            sections.append("")
            sections.append(f"### {status.replace('_', ' ').title()} ({len(items)})")
            sections.append("")
            for iv in items:
                sections.append(
                    f"- **{iv.type}**: {iv.description[:150]} "
                    f"(effectiveness: {iv.estimated_effectiveness})"
                )

    sections.append("")
    return "\n".join(sections)
