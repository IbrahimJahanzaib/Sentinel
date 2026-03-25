"""Tests for sentinel.benchmark — models, metrics, profiles, regression, reporter, suite."""

from __future__ import annotations

import json
import math
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from sentinel.benchmark.models import (
    BenchmarkConfig,
    BenchmarkMetrics,
    BenchmarkResult,
    ComparisonResult,
    RegressionResult,
)
from sentinel.benchmark.metrics import MetricsCalculator
from sentinel.benchmark.profiles import PROFILES, get_profile
from sentinel.benchmark.regression import RegressionDetector
from sentinel.benchmark.report import BenchmarkReporter


# ═══════════════════════════════════════════════════════════════════
# Helpers — lightweight fakes for CycleResult artefacts
# ═══════════════════════════════════════════════════════════════════

def _fake_run(experiment_id: str, run_number: int, output: str = "ok",
              latency_ms: int = 100, error: str | None = None):
    return SimpleNamespace(
        experiment_id=experiment_id,
        run_number=run_number,
        output=output,
        latency_ms=latency_ms,
        error=error,
    )


def _fake_experiment(exp_id: str = "exp_1", hypothesis_id: str = "hyp_1"):
    return SimpleNamespace(id=exp_id, hypothesis_id=hypothesis_id)


def _fake_hypothesis(hyp_id: str = "hyp_1", status: str = "confirmed"):
    return SimpleNamespace(id=hyp_id, status=status)


def _fake_failure(fail_id: str = "fail_1", experiment_id: str = "exp_1",
                  failure_class: str = "REASONING", severity: str = "S2"):
    return SimpleNamespace(
        id=fail_id, experiment_id=experiment_id,
        failure_class=failure_class, severity=severity,
    )


def _fake_intervention(int_id: str = "int_1", validation_status: str = "fixed"):
    return SimpleNamespace(id=int_id, validation_status=validation_status)


def _fake_cycle_result(
    cycle_id: str = "cyc_1",
    hypotheses=None,
    experiments=None,
    failures=None,
    interventions=None,
    runs=None,
):
    cr = SimpleNamespace()
    cr.cycle_id = cycle_id
    cr.hypotheses = hypotheses or []
    cr.experiments = experiments or []
    cr.failures = failures or []
    cr.interventions = interventions or []
    cr.runs = runs or {}
    cr.validations = []
    cr.cost_summary = {}
    return cr


def _make_benchmark_result(
    success_rate=0.8, failure_rate=0.2, benchmark_id="bench_test",
    **metric_overrides,
) -> BenchmarkResult:
    """Create a BenchmarkResult with customizable metrics."""
    defaults = dict(
        success_rate=success_rate,
        failure_rate=failure_rate,
        failure_rate_by_class={"REASONING": 0.2},
        severity_distribution={"S0": 0, "S1": 1, "S2": 2, "S3": 0, "S4": 0},
        mean_severity_score=1.67,
        max_severity="S2",
        interventions_proposed=3,
        interventions_validated=2,
        interventions_successful=1,
        intervention_effectiveness_rate=0.5,
        unique_failures_found=3,
        hypotheses_tested=5,
        hypotheses_confirmed=3,
        hypothesis_confirmation_rate=0.6,
        failure_discovery_rate=0.6,
        total_cost_usd=0.50,
        cost_per_discovery_usd=0.17,
        total_tokens=5000,
        total_llm_calls=20,
        mean_latency_ms=120.0,
        p50_latency_ms=100.0,
        p95_latency_ms=250.0,
        p99_latency_ms=400.0,
        max_latency_ms=500.0,
        timeout_count=1,
        timeout_rate=0.05,
        error_count=2,
        error_rate=0.1,
        consistency_score=0.85,
        non_determinism_rate=0.15,
        attack_probes_run=10,
        attack_vulnerabilities_found=2,
        attack_vulnerability_rate=0.2,
        attack_results_by_category={"prompt_injection": {"total": 5, "vulnerable": 1}},
    )
    defaults.update(metric_overrides)
    metrics = BenchmarkMetrics(**defaults)
    now = datetime.now(timezone.utc)
    return BenchmarkResult(
        benchmark_id=benchmark_id,
        model_name="test-model",
        model_provider="test",
        target_description="Test target",
        config=BenchmarkConfig(name="quick"),
        metrics=metrics,
        started_at=now,
        completed_at=now,
        duration_seconds=10.0,
    )


# ═══════════════════════════════════════════════════════════════════
# BenchmarkConfig / BenchmarkMetrics model tests
# ═══════════════════════════════════════════════════════════════════

class TestModels:

    def test_benchmark_config_defaults(self):
        cfg = BenchmarkConfig()
        assert cfg.name == "default"
        assert cfg.focus_areas == ["reasoning", "tool_use"]
        assert cfg.include_attack_scan is True

    def test_benchmark_metrics_defaults(self):
        m = BenchmarkMetrics(success_rate=1.0, failure_rate=0.0)
        assert m.max_severity == "S0"
        assert m.consistency_score == 1.0

    def test_benchmark_result_serialization(self):
        result = _make_benchmark_result()
        data = result.model_dump(mode="json")
        restored = BenchmarkResult(**data)
        assert restored.benchmark_id == result.benchmark_id
        assert restored.metrics.success_rate == result.metrics.success_rate

    def test_comparison_result(self):
        r1 = _make_benchmark_result(benchmark_id="b1")
        r2 = _make_benchmark_result(benchmark_id="b2")
        comp = ComparisonResult(
            comparison_id="cmp_1",
            target_description="test",
            config=BenchmarkConfig(),
            results=[r1, r2],
            rankings={"success_rate": ["test-model", "test-model"]},
            summary="Summary text",
            created_at=datetime.now(timezone.utc),
        )
        assert len(comp.results) == 2

    def test_regression_result(self):
        current = _make_benchmark_result(success_rate=0.7, failure_rate=0.3)
        baseline = _make_benchmark_result(success_rate=0.8, failure_rate=0.2)
        reg = RegressionResult(
            current=current,
            baseline=baseline,
            regressions=[{"metric": "success_rate", "baseline": 0.8, "current": 0.7, "delta": -0.1}],
            passed=False,
            worst_regression=0.125,
        )
        assert reg.passed is False


# ═══════════════════════════════════════════════════════════════════
# MetricsCalculator tests
# ═══════════════════════════════════════════════════════════════════

class TestMetricsCalculator:

    def test_empty_cycles(self):
        calc = MetricsCalculator()
        m = calc.calculate(cycle_results=[])
        assert m.success_rate == 1.0
        assert m.failure_rate == 0.0
        assert m.hypotheses_tested == 0
        assert m.consistency_score == 1.0

    def test_basic_metrics(self):
        exp1 = _fake_experiment("exp_1")
        exp2 = _fake_experiment("exp_2")
        hyp1 = _fake_hypothesis("hyp_1", "confirmed")
        hyp2 = _fake_hypothesis("hyp_2", "rejected")
        fail1 = _fake_failure("fail_1", "exp_1", "REASONING", "S2")

        runs = {
            "exp_1": [
                _fake_run("exp_1", 1, "output_a", 100),
                _fake_run("exp_1", 2, "output_a", 150),
            ],
            "exp_2": [
                _fake_run("exp_2", 1, "output_b", 200),
                _fake_run("exp_2", 2, "output_b", 250),
            ],
        }

        cycle = _fake_cycle_result(
            hypotheses=[hyp1, hyp2],
            experiments=[exp1, exp2],
            failures=[fail1],
            interventions=[],
            runs=runs,
        )

        calc = MetricsCalculator()
        m = calc.calculate([cycle])

        assert m.success_rate == 0.5  # 1/2 experiments failed
        assert m.failure_rate == 0.5
        assert m.hypotheses_tested == 2
        assert m.hypotheses_confirmed == 1
        assert m.hypothesis_confirmation_rate == 0.5
        assert m.unique_failures_found == 1
        assert m.max_severity == "S2"
        assert m.severity_distribution["S2"] == 1

    def test_latency_percentiles(self):
        exp1 = _fake_experiment("exp_1")
        # Create 100 runs with varying latencies
        runs_list = [_fake_run("exp_1", i, "ok", latency_ms=i * 10) for i in range(1, 101)]
        runs = {"exp_1": runs_list}

        cycle = _fake_cycle_result(
            experiments=[exp1],
            runs=runs,
        )

        calc = MetricsCalculator()
        m = calc.calculate([cycle])

        assert m.mean_latency_ms > 0
        assert m.p50_latency_ms > 0
        assert m.p95_latency_ms > m.p50_latency_ms
        assert m.p99_latency_ms >= m.p95_latency_ms
        assert m.max_latency_ms == 1000.0

    def test_error_and_timeout_rates(self):
        exp1 = _fake_experiment("exp_1")
        runs = {
            "exp_1": [
                _fake_run("exp_1", 1, "ok", 100, error=None),
                _fake_run("exp_1", 2, "", 0, error="timeout exceeded"),
                _fake_run("exp_1", 3, "", 0, error="connection error"),
                _fake_run("exp_1", 4, "ok", 200, error=None),
            ]
        }
        cycle = _fake_cycle_result(experiments=[exp1], runs=runs)

        calc = MetricsCalculator()
        m = calc.calculate([cycle])

        assert m.error_count == 2
        assert m.error_rate == 0.5
        assert m.timeout_count == 1
        assert m.timeout_rate == 0.25

    def test_intervention_effectiveness(self):
        int1 = _fake_intervention("int_1", "fixed")
        int2 = _fake_intervention("int_2", "no_effect")
        int3 = _fake_intervention("int_3", "pending")

        cycle = _fake_cycle_result(interventions=[int1, int2, int3])

        calc = MetricsCalculator()
        m = calc.calculate([cycle])

        assert m.interventions_proposed == 3
        assert m.interventions_validated == 2  # fixed + no_effect
        assert m.interventions_successful == 1  # only fixed
        assert m.intervention_effectiveness_rate == 0.5

    def test_consistency_score(self):
        exp1 = _fake_experiment("exp_1")
        exp2 = _fake_experiment("exp_2")

        # exp_1: all same output → consistency=1.0
        # exp_2: 3 different outputs from 3 runs → consistency=0.0
        runs = {
            "exp_1": [
                _fake_run("exp_1", 1, "same"),
                _fake_run("exp_1", 2, "same"),
                _fake_run("exp_1", 3, "same"),
            ],
            "exp_2": [
                _fake_run("exp_2", 1, "alpha"),
                _fake_run("exp_2", 2, "beta"),
                _fake_run("exp_2", 3, "gamma"),
            ],
        }
        cycle = _fake_cycle_result(experiments=[exp1, exp2], runs=runs)

        calc = MetricsCalculator()
        m = calc.calculate([cycle])

        assert m.consistency_score == 0.5  # mean(1.0, 0.0)
        assert m.non_determinism_rate == 0.5

    def test_with_attack_scan(self):
        scan = SimpleNamespace(
            total_probes=20,
            vulnerable_probes=4,
            vulnerability_rate=0.2,
            by_category={"prompt_injection": {"total": 10, "vulnerable": 2}},
        )
        calc = MetricsCalculator()
        m = calc.calculate([], attack_scan=scan)

        assert m.attack_probes_run == 20
        assert m.attack_vulnerabilities_found == 4
        assert m.attack_vulnerability_rate == 0.2

    def test_with_cost_tracker(self):
        tracker = SimpleNamespace(
            total_cost_usd=1.25,
            total_input_tokens=3000,
            total_output_tokens=2000,
            total_calls=15,
        )
        fail1 = _fake_failure("f1", "exp_1")
        exp1 = _fake_experiment("exp_1")
        cycle = _fake_cycle_result(experiments=[exp1], failures=[fail1])

        calc = MetricsCalculator()
        m = calc.calculate([cycle], cost_tracker=tracker)

        assert m.total_cost_usd == 1.25
        assert m.total_tokens == 5000
        assert m.total_llm_calls == 15
        assert m.cost_per_discovery_usd == 1.25

    def test_cost_per_discovery_inf_when_no_failures(self):
        calc = MetricsCalculator()
        tracker = SimpleNamespace(
            total_cost_usd=1.0,
            total_input_tokens=1000,
            total_output_tokens=500,
            total_calls=5,
        )
        m = calc.calculate([], cost_tracker=tracker)
        assert math.isinf(m.cost_per_discovery_usd)

    def test_multiple_cycles(self):
        cycle1 = _fake_cycle_result(
            cycle_id="c1",
            hypotheses=[_fake_hypothesis("h1", "confirmed")],
            experiments=[_fake_experiment("e1")],
            failures=[_fake_failure("f1", "e1", "REASONING", "S2")],
            runs={"e1": [_fake_run("e1", 1, "ok", 100)]},
        )
        cycle2 = _fake_cycle_result(
            cycle_id="c2",
            hypotheses=[_fake_hypothesis("h2", "rejected")],
            experiments=[_fake_experiment("e2")],
            failures=[_fake_failure("f2", "e2", "TOOL_USE", "S3")],
            runs={"e2": [_fake_run("e2", 1, "ok", 200)]},
        )

        calc = MetricsCalculator()
        m = calc.calculate([cycle1, cycle2])

        assert m.hypotheses_tested == 2
        assert m.hypotheses_confirmed == 1
        assert m.unique_failures_found == 2
        assert m.max_severity == "S3"
        assert m.severity_distribution["S2"] == 1
        assert m.severity_distribution["S3"] == 1
        assert "REASONING" in m.failure_rate_by_class
        assert "TOOL_USE" in m.failure_rate_by_class


# ═══════════════════════════════════════════════════════════════════
# Profiles tests
# ═══════════════════════════════════════════════════════════════════

class TestProfiles:

    def test_all_profiles_exist(self):
        assert "quick" in PROFILES
        assert "standard" in PROFILES
        assert "comprehensive" in PROFILES
        assert "security_only" in PROFILES
        assert "cost_efficient" in PROFILES

    def test_get_profile_returns_copy(self):
        p1 = get_profile("quick")
        p2 = get_profile("quick")
        assert p1 == p2
        p1.name = "modified"
        assert p2.name == "quick"

    def test_get_profile_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown profile"):
            get_profile("nonexistent")

    def test_quick_profile_no_attacks(self):
        p = get_profile("quick")
        assert p.include_attack_scan is False
        assert p.focus_areas == ["reasoning"]

    def test_comprehensive_profile(self):
        p = get_profile("comprehensive")
        assert p.include_attack_scan is True
        assert len(p.focus_areas) == 4
        assert p.runs_per_experiment == 10

    def test_security_only_profile(self):
        p = get_profile("security_only")
        assert p.focus_areas == ["security"]
        assert p.include_attack_scan is True


# ═══════════════════════════════════════════════════════════════════
# RegressionDetector tests
# ═══════════════════════════════════════════════════════════════════

class TestRegressionDetector:

    def test_no_regression(self):
        baseline = _make_benchmark_result(success_rate=0.8, failure_rate=0.2)
        current = _make_benchmark_result(success_rate=0.85, failure_rate=0.15)

        detector = RegressionDetector()
        result = detector.detect_regression(current, baseline, max_regression=0.1)

        assert result.passed is True
        assert result.worst_regression == 0.0  # no regressions at all

    def test_regression_detected(self):
        baseline = _make_benchmark_result(success_rate=0.8, failure_rate=0.2)
        current = _make_benchmark_result(success_rate=0.6, failure_rate=0.4)

        detector = RegressionDetector()
        result = detector.detect_regression(current, baseline, max_regression=0.1)

        assert result.passed is False
        assert result.worst_regression > 0.1
        assert len(result.regressions) > 0

    def test_regression_within_threshold(self):
        baseline = _make_benchmark_result(success_rate=0.8, failure_rate=0.2)
        current = _make_benchmark_result(success_rate=0.75, failure_rate=0.25)

        detector = RegressionDetector()
        result = detector.detect_regression(current, baseline, max_regression=0.5)

        assert result.passed is True

    def test_save_and_load_baseline(self):
        original = _make_benchmark_result()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        detector = RegressionDetector()
        detector.save_baseline(original, path)
        loaded = detector.load_baseline(path)

        assert loaded.benchmark_id == original.benchmark_id
        assert loaded.metrics.success_rate == original.metrics.success_rate

    def test_improvements_tracked(self):
        baseline = _make_benchmark_result(
            success_rate=0.7, failure_rate=0.3, consistency_score=0.6
        )
        current = _make_benchmark_result(
            success_rate=0.9, failure_rate=0.1, consistency_score=0.9
        )

        detector = RegressionDetector()
        result = detector.detect_regression(current, baseline)

        assert len(result.improvements) > 0
        improved_metrics = [r["metric"] for r in result.improvements]
        assert "success_rate" in improved_metrics

    def test_zero_baseline_no_division_error(self):
        baseline = _make_benchmark_result(
            success_rate=0.0, failure_rate=1.0, mean_severity_score=0.0
        )
        current = _make_benchmark_result(
            success_rate=0.5, failure_rate=0.5, mean_severity_score=1.0
        )

        detector = RegressionDetector()
        result = detector.detect_regression(current, baseline)
        # Should not raise ZeroDivisionError
        assert isinstance(result.worst_regression, float)


# ═══════════════════════════════════════════════════════════════════
# BenchmarkReporter tests
# ═══════════════════════════════════════════════════════════════════

class TestBenchmarkReporter:

    def test_result_to_markdown(self):
        result = _make_benchmark_result()
        reporter = BenchmarkReporter()
        md = reporter.result_to_markdown(result)

        assert "# Sentinel Benchmark Report" in md
        assert "Reliability" in md
        assert "Failure Distribution" in md
        assert "Discovery Efficiency" in md
        assert "Interventions" in md
        assert "Performance" in md
        assert "Cost" in md
        assert "Attack Surface" in md

    def test_result_to_markdown_no_attacks(self):
        result = _make_benchmark_result(
            attack_probes_run=0,
            attack_vulnerabilities_found=0,
            attack_vulnerability_rate=0.0,
            attack_results_by_category={},
        )
        reporter = BenchmarkReporter()
        md = reporter.result_to_markdown(result)
        assert "Attack Surface" not in md

    def test_result_to_json(self):
        result = _make_benchmark_result()
        reporter = BenchmarkReporter()
        data = reporter.result_to_json(result)
        assert data["benchmark_id"] == "bench_test"
        assert "metrics" in data
        assert data["metrics"]["success_rate"] == 0.8

    def test_comparison_to_markdown(self):
        r1 = _make_benchmark_result(benchmark_id="b1", success_rate=0.8)
        r1.model_name = "model-a"
        r2 = _make_benchmark_result(benchmark_id="b2", success_rate=0.9)
        r2.model_name = "model-b"

        comp = ComparisonResult(
            comparison_id="cmp_1",
            target_description="test",
            config=BenchmarkConfig(),
            results=[r1, r2],
            rankings={"success_rate": ["model-b", "model-a"]},
            summary="Model B is better.",
            created_at=datetime.now(timezone.utc),
        )

        reporter = BenchmarkReporter()
        md = reporter.comparison_to_markdown(comp)

        assert "Cross-Model Comparison" in md
        assert "model-a" in md
        assert "model-b" in md
        assert "Rankings" in md
        assert "Model B is better." in md

    def test_regression_to_markdown_pass(self):
        baseline = _make_benchmark_result(success_rate=0.8)
        current = _make_benchmark_result(success_rate=0.85)

        reg = RegressionResult(
            current=current,
            baseline=baseline,
            passed=True,
            max_regression_allowed=0.1,
            worst_regression=0.0,
        )

        reporter = BenchmarkReporter()
        md = reporter.regression_to_markdown(reg)

        assert "PASSED" in md
        assert "PASS" in md

    def test_regression_to_markdown_fail(self):
        baseline = _make_benchmark_result(success_rate=0.8)
        current = _make_benchmark_result(success_rate=0.6)

        reg = RegressionResult(
            current=current,
            baseline=baseline,
            regressions=[{
                "metric": "success_rate",
                "baseline": 0.8,
                "current": 0.6,
                "delta": -0.2,
                "direction": "higher_better",
            }],
            passed=False,
            max_regression_allowed=0.1,
            worst_regression=0.25,
        )

        reporter = BenchmarkReporter()
        md = reporter.regression_to_markdown(reg)

        assert "FAILED" in md
        assert "success_rate" in md


# ═══════════════════════════════════════════════════════════════════
# BenchmarkSuite tests (mocked — no real LLM calls)
# ═══════════════════════════════════════════════════════════════════

class TestBenchmarkSuite:

    @pytest.mark.asyncio
    async def test_suite_run_mocked(self):
        """Test that BenchmarkSuite.run orchestrates correctly with mocks."""
        from sentinel.benchmark.suite import BenchmarkSuite
        from sentinel.core.control_plane import CycleResult

        # Mock cycle result
        mock_cycle = CycleResult()
        mock_cycle.cycle_id = "cyc_mock"
        mock_cycle.hypotheses = [_fake_hypothesis("h1", "confirmed")]
        mock_cycle.experiments = [_fake_experiment("e1")]
        mock_cycle.failures = [_fake_failure("f1", "e1")]
        mock_cycle.interventions = []
        mock_cycle.runs = {"e1": [_fake_run("e1", 1, "ok", 100)]}

        with patch("sentinel.benchmark.suite.ControlPlane") as MockCP, \
             patch("sentinel.benchmark.suite.load_settings") as mock_settings, \
             patch("sentinel.benchmark.suite.build_default_client") as mock_client:

            mock_settings.return_value = MagicMock()
            mock_client.return_value = MagicMock(model="test-model", provider="test")

            cp_instance = AsyncMock()
            cp_instance.research_cycle.return_value = mock_cycle
            MockCP.return_value = cp_instance

            target = MagicMock()
            target.describe.return_value = "Test target system"

            suite = BenchmarkSuite()
            result = await suite.run(target, profile="quick")

            assert result.benchmark_id.startswith("bench_")
            assert result.metrics.hypotheses_tested == 1
            assert result.metrics.unique_failures_found == 1
            cp_instance.research_cycle.assert_called_once()

    @pytest.mark.asyncio
    async def test_suite_run_with_attacks(self):
        """Test that attack scan is included when configured."""
        from sentinel.benchmark.suite import BenchmarkSuite
        from sentinel.core.control_plane import CycleResult

        mock_cycle = CycleResult()
        mock_cycle.cycle_id = "cyc_mock"

        mock_scan = SimpleNamespace(
            scan_id="scan_1",
            total_probes=10,
            vulnerable_probes=2,
            vulnerability_rate=0.2,
            by_category={},
        )

        with patch("sentinel.benchmark.suite.ControlPlane") as MockCP, \
             patch("sentinel.benchmark.suite.load_settings") as mock_settings, \
             patch("sentinel.benchmark.suite.build_default_client") as mock_client:

            mock_settings.return_value = MagicMock()
            mock_client.return_value = MagicMock(model="test-model", provider="test")

            cp_instance = AsyncMock()
            cp_instance.research_cycle.return_value = mock_cycle
            MockCP.return_value = cp_instance

            # Patch the lazy imports inside BenchmarkSuite.run
            mock_classifier_cls = MagicMock()
            mock_runner_cls = MagicMock()
            ar_instance = AsyncMock()
            ar_instance.scan.return_value = mock_scan
            mock_runner_cls.return_value = ar_instance

            target = MagicMock()
            target.describe.return_value = "Test target"

            with patch.dict("sys.modules", {}):
                # Patch the modules that get imported lazily
                import sentinel.attacks.classifier as classifier_mod
                import sentinel.attacks.runner as runner_mod
                orig_vc = classifier_mod.VulnerabilityClassifier
                orig_ar = runner_mod.AttackRunner
                classifier_mod.VulnerabilityClassifier = mock_classifier_cls
                runner_mod.AttackRunner = mock_runner_cls
                try:
                    suite = BenchmarkSuite()
                    result = await suite.run(target, profile="standard")

                    assert result.metrics.attack_probes_run == 10
                    assert result.metrics.attack_vulnerabilities_found == 2
                    assert result.attack_scan_id == "scan_1"
                finally:
                    classifier_mod.VulnerabilityClassifier = orig_vc
                    runner_mod.AttackRunner = orig_ar

    def test_generate_rankings(self):
        from sentinel.benchmark.suite import BenchmarkSuite

        r1 = _make_benchmark_result(benchmark_id="b1", success_rate=0.9, failure_rate=0.1)
        r1.model_name = "model-a"
        r2 = _make_benchmark_result(benchmark_id="b2", success_rate=0.7, failure_rate=0.3)
        r2.model_name = "model-b"

        suite = BenchmarkSuite()
        rankings = suite._generate_rankings([r1, r2])

        assert rankings["success_rate"] == ["model-a", "model-b"]
        assert rankings["failure_rate"] == ["model-a", "model-b"]  # lower is better

    def test_generate_rankings_empty(self):
        from sentinel.benchmark.suite import BenchmarkSuite

        suite = BenchmarkSuite()
        rankings = suite._generate_rankings([])
        assert rankings == {}

    @pytest.mark.asyncio
    async def test_compare_models_mocked(self):
        from sentinel.benchmark.suite import BenchmarkSuite
        from sentinel.core.control_plane import CycleResult

        mock_cycle = CycleResult()
        mock_cycle.cycle_id = "cyc_mock"

        with patch("sentinel.benchmark.suite.ControlPlane") as MockCP, \
             patch("sentinel.benchmark.suite.load_settings") as mock_settings, \
             patch("sentinel.benchmark.suite.build_default_client") as mock_client:

            mock_settings.return_value = MagicMock()
            mock_client.return_value = MagicMock(model="test", provider="test")

            cp_instance = AsyncMock()
            cp_instance.research_cycle.return_value = mock_cycle
            MockCP.return_value = cp_instance

            target = MagicMock()
            target.describe.return_value = "Test"

            suite = BenchmarkSuite()
            result = await suite.compare_models(
                target_factory=lambda model_name: target,
                models=[
                    {"provider": "test", "model": "model-a"},
                    {"provider": "test", "model": "model-b"},
                ],
                profile="quick",
            )

            assert result.comparison_id.startswith("cmp_")
            assert len(result.results) == 2
            assert "success_rate" in result.rankings


# ═══════════════════════════════════════════════════════════════════
# DB models exist tests
# ═══════════════════════════════════════════════════════════════════

class TestDBModels:

    @pytest.mark.asyncio
    async def test_benchmark_run_table_created(self, db):
        from sentinel.db.connection import get_session
        from sentinel.db.models import BenchmarkRun
        from datetime import datetime, timezone

        async with get_session() as session:
            run = BenchmarkRun(
                id="bench_test",
                model_name="claude-sonnet",
                model_provider="anthropic",
                target_description="Test",
                profile="quick",
                started_at=datetime.now(timezone.utc),
                duration_seconds=5.0,
                metrics_json='{"success_rate": 0.8}',
            )
            session.add(run)

        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(BenchmarkRun).where(BenchmarkRun.id == "bench_test")
            )
            loaded = result.scalar_one()
            assert loaded.model_name == "claude-sonnet"
            assert loaded.profile == "quick"

    @pytest.mark.asyncio
    async def test_model_comparison_table_created(self, db):
        from sentinel.db.connection import get_session
        from sentinel.db.models import ModelComparison

        async with get_session() as session:
            comp = ModelComparison(
                id="cmp_test",
                benchmark_ids='["bench_1", "bench_2"]',
                rankings_json='{"success_rate": ["model-a", "model-b"]}',
                summary="Test comparison",
            )
            session.add(comp)

        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ModelComparison).where(ModelComparison.id == "cmp_test")
            )
            loaded = result.scalar_one()
            assert loaded.summary == "Test comparison"
