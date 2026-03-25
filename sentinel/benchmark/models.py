"""Pydantic models for benchmark metrics, results, and comparisons."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BenchmarkConfig(BaseModel):
    """Configuration for a benchmark run."""

    name: str = "default"
    focus_areas: list[str] = Field(default_factory=lambda: ["reasoning", "tool_use"])
    max_hypotheses_per_focus: int = 5
    max_experiments_per_hypothesis: int = 3
    runs_per_experiment: int = 5
    include_attack_scan: bool = True
    attack_categories: list[str] = Field(default_factory=list)  # empty = all
    attack_min_severity: str = "S0"


class BenchmarkMetrics(BaseModel):
    """All metrics from a single benchmark run."""

    # ── Core Reliability ──
    success_rate: float  # fraction of experiments without failure (0.0-1.0)
    failure_rate: float  # 1 - success_rate
    failure_rate_by_class: dict[str, float] = Field(default_factory=dict)

    # ── Severity Distribution ──
    severity_distribution: dict[str, int] = Field(
        default_factory=lambda: {"S0": 0, "S1": 0, "S2": 0, "S3": 0, "S4": 0}
    )
    mean_severity_score: float = 0.0  # weighted avg where S0=0..S4=4
    max_severity: str = "S0"

    # ── Intervention Effectiveness ──
    interventions_proposed: int = 0
    interventions_validated: int = 0
    interventions_successful: int = 0  # validated AND actually fixed
    intervention_effectiveness_rate: float = 0.0

    # ── Discovery Efficiency ──
    unique_failures_found: int = 0
    hypotheses_tested: int = 0
    hypotheses_confirmed: int = 0
    hypothesis_confirmation_rate: float = 0.0
    failure_discovery_rate: float = 0.0  # unique_failures / hypotheses_tested

    # ── Cost Efficiency ──
    total_cost_usd: float = 0.0
    cost_per_discovery_usd: float = 0.0  # inf if 0 discoveries
    total_tokens: int = 0
    total_llm_calls: int = 0

    # ── Performance ──
    mean_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    timeout_count: int = 0
    timeout_rate: float = 0.0
    error_count: int = 0
    error_rate: float = 0.0

    # ── Consistency ──
    consistency_score: float = 1.0  # same input → same output across runs
    non_determinism_rate: float = 0.0

    # ── Attack Surface (if attack scan included) ──
    attack_probes_run: int = 0
    attack_vulnerabilities_found: int = 0
    attack_vulnerability_rate: float = 0.0
    attack_results_by_category: dict[str, dict] = Field(default_factory=dict)


class BenchmarkResult(BaseModel):
    """Result of a single benchmark run against one target with one model."""

    benchmark_id: str
    model_name: str
    model_provider: str
    target_description: str
    config: BenchmarkConfig
    metrics: BenchmarkMetrics
    started_at: datetime
    completed_at: datetime
    duration_seconds: float

    # Raw data references
    cycle_ids: list[str] = Field(default_factory=list)
    attack_scan_id: Optional[str] = None


class ComparisonResult(BaseModel):
    """Result of comparing multiple models on the same benchmark."""

    comparison_id: str
    target_description: str
    config: BenchmarkConfig
    results: list[BenchmarkResult]
    rankings: dict[str, list[str]] = Field(default_factory=dict)
    summary: str = ""
    created_at: datetime


class RegressionResult(BaseModel):
    """Result of comparing a benchmark against a saved baseline."""

    current: BenchmarkResult
    baseline: BenchmarkResult
    regressions: list[dict] = Field(default_factory=list)
    improvements: list[dict] = Field(default_factory=list)
    passed: bool = True
    max_regression_allowed: float = 0.1
    worst_regression: float = 0.0
