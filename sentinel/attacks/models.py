"""Pydantic models for attack probes and scan results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AttackProbe(BaseModel):
    """A single attack probe loaded from YAML."""

    id: str
    name: str
    category: str
    severity: str  # S0–S4
    description: str
    payloads: list[str]
    expected_safe_behavior: str
    expected_vulnerable_behavior: str
    detection_patterns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class PayloadResult(BaseModel):
    """Result of running a single payload from a probe."""

    probe_id: str
    payload_index: int
    payload: str
    target_output: str
    vulnerable: bool
    confidence: float  # 0.0–1.0
    detection_matches: list[str]
    explanation: str
    latency_ms: float
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=_utcnow)


class ProbeResult(BaseModel):
    """Aggregated result for all payloads of a single probe."""

    probe: AttackProbe
    payload_results: list[PayloadResult]
    vulnerable: bool  # True if ANY payload succeeded
    vulnerability_rate: float  # fraction of payloads that succeeded
    max_confidence: float  # highest confidence among successful payloads
    summary: str


class ScanResult(BaseModel):
    """Full result of an attack scan."""

    scan_id: str
    target_description: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float

    # Counts
    total_probes: int
    total_payloads: int
    vulnerable_probes: int
    vulnerable_payloads: int

    # Results
    probe_results: list[ProbeResult]

    # Summaries
    by_category: dict[str, dict]
    by_severity: dict[str, dict]

    # Overall
    vulnerability_rate: float  # vulnerable_probes / total_probes

    @property
    def passed(self) -> bool:
        return self.vulnerable_probes == 0
