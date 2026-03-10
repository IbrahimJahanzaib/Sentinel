"""Executes attack probes against target systems."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from .models import AttackProbe, PayloadResult, ProbeResult, ScanResult
from .loader import ProbeLoader
from .classifier import VulnerabilityClassifier

if TYPE_CHECKING:
    from sentinel.agents.base import TargetSystem
    from sentinel.core.cost_tracker import CostTracker


class AttackRunner:
    """Orchestrates running attack probes against a target."""

    def __init__(
        self,
        classifier: VulnerabilityClassifier,
        loader: Optional[ProbeLoader] = None,
        cost_tracker: Optional["CostTracker"] = None,
        max_concurrent: int = 3,
    ) -> None:
        self.loader = loader or ProbeLoader()
        self.classifier = classifier
        self.cost_tracker = cost_tracker
        self.max_concurrent = max_concurrent

    async def scan(
        self,
        target: "TargetSystem",
        categories: list[str] | None = None,
        min_severity: str | None = None,
        probe_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> ScanResult:
        """Run an attack scan against a target.

        Filter probes by categories, min_severity, specific IDs, or tags.
        If no filters, runs ALL probes.
        """
        started_at = datetime.now(timezone.utc)
        scan_id = f"scan_{uuid.uuid4().hex[:8]}"

        probes = self._load_probes(categories, min_severity, probe_ids, tags)
        if not probes:
            raise ValueError("No probes matched the given filters.")

        semaphore = asyncio.Semaphore(self.max_concurrent)
        probe_results: list[ProbeResult] = []

        async def run_one(probe: AttackProbe) -> None:
            async with semaphore:
                result = await self._run_probe(probe, target)
                probe_results.append(result)

        tasks = [run_one(p) for p in probes]
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            await coro

        # Sort by probe ID for consistent output
        probe_results.sort(key=lambda r: r.probe.id)

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        # Build summaries
        by_category: dict[str, dict] = {}
        by_severity: dict[str, dict] = {}
        for pr in probe_results:
            cat = pr.probe.category
            sev = pr.probe.severity

            if cat not in by_category:
                by_category[cat] = {"total": 0, "vulnerable": 0, "safe": 0}
            by_category[cat]["total"] += 1
            by_category[cat]["vulnerable" if pr.vulnerable else "safe"] += 1

            if sev not in by_severity:
                by_severity[sev] = {"total": 0, "vulnerable": 0, "safe": 0}
            by_severity[sev]["total"] += 1
            by_severity[sev]["vulnerable" if pr.vulnerable else "safe"] += 1

        vulnerable_probes = sum(1 for r in probe_results if r.vulnerable)
        vulnerable_payloads = sum(
            sum(1 for pr in r.payload_results if pr.vulnerable)
            for r in probe_results
        )
        total_payloads = sum(len(r.payload_results) for r in probe_results)

        return ScanResult(
            scan_id=scan_id,
            target_description=target.describe(),
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            total_probes=len(probe_results),
            total_payloads=total_payloads,
            vulnerable_probes=vulnerable_probes,
            vulnerable_payloads=vulnerable_payloads,
            probe_results=probe_results,
            by_category=by_category,
            by_severity=by_severity,
            vulnerability_rate=vulnerable_probes / len(probe_results) if probe_results else 0,
        )

    async def run_single(self, probe_id: str, target: "TargetSystem") -> ProbeResult:
        """Run a single probe by ID."""
        probe = self.loader.load_by_ids([probe_id])[0]
        return await self._run_probe(probe, target)

    async def _run_probe(self, probe: AttackProbe, target: "TargetSystem") -> ProbeResult:
        """Run all payloads for a single probe and aggregate results."""
        payload_results: list[PayloadResult] = []

        for idx, payload in enumerate(probe.payloads):
            start = time.time()

            try:
                result = await target.run(payload)
                output = result.output
                error = result.error
            except Exception as e:
                output = ""
                error = str(e)

            latency = (time.time() - start) * 1000

            if error and not output:
                payload_results.append(PayloadResult(
                    probe_id=probe.id,
                    payload_index=idx,
                    payload=payload,
                    target_output=f"[TARGET ERROR: {error}]",
                    vulnerable=False,
                    confidence=0.5,
                    detection_matches=[],
                    explanation=f"Target returned an error: {error}",
                    latency_ms=latency,
                    error=error,
                ))
                continue

            vulnerable, confidence, explanation = await self.classifier.classify(
                probe, payload, output
            )
            detection_matches = self.classifier.quick_check(probe, output)

            payload_results.append(PayloadResult(
                probe_id=probe.id,
                payload_index=idx,
                payload=payload,
                target_output=output,
                vulnerable=vulnerable,
                confidence=confidence,
                detection_matches=detection_matches,
                explanation=explanation,
                latency_ms=latency,
            ))

        # Aggregate
        any_vulnerable = any(pr.vulnerable for pr in payload_results)
        vuln_count = sum(1 for pr in payload_results if pr.vulnerable)
        vuln_rate = vuln_count / len(payload_results) if payload_results else 0
        max_conf = max((pr.confidence for pr in payload_results if pr.vulnerable), default=0.0)

        summary = f"{'VULNERABLE' if any_vulnerable else 'SAFE'}: {vuln_count}/{len(payload_results)} payloads succeeded"
        if any_vulnerable:
            best = max((pr for pr in payload_results if pr.vulnerable), key=lambda x: x.confidence)
            summary += f" — {best.explanation}"

        return ProbeResult(
            probe=probe,
            payload_results=payload_results,
            vulnerable=any_vulnerable,
            vulnerability_rate=vuln_rate,
            max_confidence=max_conf,
            summary=summary,
        )

    def _load_probes(
        self,
        categories: list[str] | None,
        min_severity: str | None,
        probe_ids: list[str] | None,
        tags: list[str] | None,
    ) -> list[AttackProbe]:
        """Load probes based on whatever filters are provided."""
        if probe_ids:
            return self.loader.load_by_ids(probe_ids)

        probes: list[AttackProbe] | None = None

        if categories:
            probes = []
            for cat in categories:
                probes.extend(self.loader.load_category(cat))

        if tags:
            tag_probes = self.loader.load_by_tags(tags)
            if probes is not None:
                tag_ids = {p.id for p in tag_probes}
                probes = [p for p in probes if p.id in tag_ids]
            else:
                probes = tag_probes

        if probes is None:
            probes = self.loader.load_all()

        if min_severity:
            order = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4}
            min_level = order.get(min_severity, 0)
            probes = [p for p in probes if order.get(p.severity, 0) >= min_level]

        return probes
