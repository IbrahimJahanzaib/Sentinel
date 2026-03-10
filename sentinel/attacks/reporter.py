"""Report generation for attack scan results."""

from __future__ import annotations

from .models import ScanResult


class AttackReporter:
    """Generates markdown and JSON reports from scan results."""

    def to_markdown(self, scan: ScanResult) -> str:
        """Generate a markdown report from scan results."""
        lines: list[str] = []
        lines.append("# Sentinel Attack Scan Report")
        lines.append("")
        lines.append(f"**Scan ID:** {scan.scan_id}")
        lines.append(f"**Date:** {scan.started_at.strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"**Duration:** {scan.duration_seconds:.1f}s")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total probes | {scan.total_probes} |")
        lines.append(f"| Total payloads | {scan.total_payloads} |")
        lines.append(f"| Vulnerable probes | {scan.vulnerable_probes} |")
        lines.append(f"| Vulnerable payloads | {scan.vulnerable_payloads} |")
        lines.append(f"| Vulnerability rate | {scan.vulnerability_rate:.1%} |")
        lines.append(f"| Status | {'FAIL' if scan.vulnerable_probes > 0 else 'PASS'} |")
        lines.append("")

        # By category
        lines.append("## Results by Category")
        lines.append("")
        lines.append("| Category | Total | Vulnerable | Safe | Rate |")
        lines.append("|----------|-------|------------|------|------|")
        for cat, data in sorted(scan.by_category.items()):
            rate = data["vulnerable"] / data["total"] if data["total"] > 0 else 0
            lines.append(f"| {cat} | {data['total']} | {data['vulnerable']} | {data['safe']} | {rate:.0%} |")
        lines.append("")

        # By severity
        lines.append("## Results by Severity")
        lines.append("")
        lines.append("| Severity | Total | Vulnerable | Safe | Rate |")
        lines.append("|----------|-------|------------|------|------|")
        for sev in ["S4", "S3", "S2", "S1", "S0"]:
            if sev in scan.by_severity:
                data = scan.by_severity[sev]
                rate = data["vulnerable"] / data["total"] if data["total"] > 0 else 0
                lines.append(f"| {sev} | {data['total']} | {data['vulnerable']} | {data['safe']} | {rate:.0%} |")
        lines.append("")

        # Vulnerable probes detail
        vulnerable_results = [r for r in scan.probe_results if r.vulnerable]
        if vulnerable_results:
            lines.append(f"## Vulnerabilities Found ({len(vulnerable_results)})")
            lines.append("")
            sev_order = {"S4": 0, "S3": 1, "S2": 2, "S1": 3, "S0": 4}
            for pr in sorted(vulnerable_results, key=lambda x: sev_order.get(x.probe.severity, 5)):
                lines.append(f"### [{pr.probe.severity}] {pr.probe.id}: {pr.probe.name}")
                lines.append("")
                lines.append(f"- **Category:** {pr.probe.category}")
                lines.append(f"- **Severity:** {pr.probe.severity}")
                vuln_count = sum(1 for p in pr.payload_results if p.vulnerable)
                lines.append(f"- **Vulnerability rate:** {pr.vulnerability_rate:.0%} ({vuln_count}/{len(pr.payload_results)} payloads)")
                lines.append(f"- **Description:** {pr.probe.description}")
                lines.append("")

                best = max(
                    (p for p in pr.payload_results if p.vulnerable),
                    key=lambda x: x.confidence,
                    default=None,
                )
                if best:
                    lines.append("**Most effective payload:**")
                    lines.append("```")
                    lines.append(best.payload)
                    lines.append("```")
                    lines.append("")
                    lines.append("**Target response (excerpt):**")
                    lines.append("```")
                    lines.append(best.target_output[:500])
                    lines.append("```")
                    lines.append("")
                    lines.append(f"**Classification:** {best.explanation} (confidence: {best.confidence:.0%})")
                    lines.append("")
                lines.append("---")
                lines.append("")
        else:
            lines.append("## No Vulnerabilities Found")
            lines.append("")
            lines.append(f"All {scan.total_probes} probes passed. The target system resisted all attack payloads.")
            lines.append("")

        # Safe probes
        safe_results = [r for r in scan.probe_results if not r.vulnerable]
        if safe_results:
            lines.append(f"## Probes Passed ({len(safe_results)})")
            lines.append("")
            for pr in safe_results:
                lines.append(f"- **{pr.probe.id}**: {pr.probe.name} ({pr.probe.category}, {pr.probe.severity})")
            lines.append("")

        return "\n".join(lines)

    def to_json(self, scan: ScanResult) -> dict:
        """Convert scan result to JSON-serializable dict."""
        return scan.model_dump(mode="json")
