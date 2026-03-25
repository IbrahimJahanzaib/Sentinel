"""Predefined benchmark profiles."""

from __future__ import annotations

from sentinel.benchmark.models import BenchmarkConfig


PROFILES: dict[str, BenchmarkConfig] = {
    "quick": BenchmarkConfig(
        name="quick",
        focus_areas=["reasoning"],
        max_hypotheses_per_focus=2,
        max_experiments_per_hypothesis=2,
        runs_per_experiment=3,
        include_attack_scan=False,
    ),
    "standard": BenchmarkConfig(
        name="standard",
        focus_areas=["reasoning", "tool_use"],
        max_hypotheses_per_focus=5,
        max_experiments_per_hypothesis=3,
        runs_per_experiment=5,
        include_attack_scan=True,
        attack_min_severity="S2",
    ),
    "comprehensive": BenchmarkConfig(
        name="comprehensive",
        focus_areas=["reasoning", "tool_use", "long_context", "security"],
        max_hypotheses_per_focus=10,
        max_experiments_per_hypothesis=5,
        runs_per_experiment=10,
        include_attack_scan=True,
        attack_min_severity="S0",
    ),
    "security_only": BenchmarkConfig(
        name="security_only",
        focus_areas=["security"],
        max_hypotheses_per_focus=5,
        max_experiments_per_hypothesis=3,
        runs_per_experiment=5,
        include_attack_scan=True,
        attack_min_severity="S0",
        attack_categories=[],
    ),
    "cost_efficient": BenchmarkConfig(
        name="cost_efficient",
        focus_areas=["reasoning"],
        max_hypotheses_per_focus=3,
        max_experiments_per_hypothesis=2,
        runs_per_experiment=3,
        include_attack_scan=True,
        attack_min_severity="S3",
    ),
}


def get_profile(name: str) -> BenchmarkConfig:
    """Get a predefined benchmark profile by name."""
    if name not in PROFILES:
        available = ", ".join(PROFILES.keys())
        raise ValueError(f"Unknown profile '{name}'. Available: {available}")
    return PROFILES[name].model_copy()
