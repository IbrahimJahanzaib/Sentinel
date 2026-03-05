"""JSON report generation for Sentinel findings."""

from __future__ import annotations

from collections import Counter

from sentinel.db.models import Cycle, Failure, Intervention
from sentinel.taxonomy.failure_types import Severity


def generate_json_report(
    cycles: list[Cycle],
    failures: list[Failure],
    interventions: list[Intervention],
) -> dict:
    """Build a JSON-serialisable dict from query results."""
    total_cost = sum(c.total_cost_usd for c in cycles)

    # Severity distribution
    sev_counts: Counter[str] = Counter()
    for f in failures:
        sev_counts[f.severity] += 1

    severity_distribution = {}
    for sev in (Severity.S0, Severity.S1, Severity.S2, Severity.S3, Severity.S4):
        count = sev_counts.get(sev.value, 0)
        if count > 0:
            severity_distribution[sev.value] = {
                "label": sev.label,
                "action": sev.automated_action,
                "count": count,
            }

    # Findings
    findings = [
        {
            "id": f.id,
            "cycle_id": f.cycle_id,
            "failure_class": f.failure_class,
            "failure_subtype": f.failure_subtype,
            "severity": f.severity,
            "failure_rate": f.failure_rate,
            "evidence": f.evidence,
            "hypothesis_confirmed": f.hypothesis_confirmed,
        }
        for f in failures
    ]

    # Interventions
    intervention_list = [
        {
            "id": iv.id,
            "cycle_id": iv.cycle_id,
            "type": iv.type,
            "description": iv.description,
            "estimated_effectiveness": iv.estimated_effectiveness,
            "validation_status": iv.validation_status,
            "failure_rate_before": iv.failure_rate_before,
            "failure_rate_after": iv.failure_rate_after,
        }
        for iv in interventions
    ]

    return {
        "summary": {
            "cycles": len(cycles),
            "failures": len(failures),
            "interventions": len(interventions),
            "total_cost_usd": total_cost,
        },
        "severity_distribution": severity_distribution,
        "findings": findings,
        "interventions": intervention_list,
    }
