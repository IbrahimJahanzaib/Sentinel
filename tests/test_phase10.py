"""Phase 10 tests — Attack Probe Library.

Tests cover:
  - Pydantic models (AttackProbe, PayloadResult, ProbeResult, ScanResult)
  - ProbeLoader (load, filter by category/severity/ids/tags)
  - VulnerabilityClassifier (LLM classify + pattern fallback)
  - AttackRunner (scan orchestration)
  - AttackReporter (markdown and JSON reports)
  - DB models (AttackScan, AttackFinding)
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
import yaml

from sentinel.attacks.models import (
    AttackProbe,
    PayloadResult,
    ProbeResult,
    ScanResult,
)
from sentinel.attacks.loader import ProbeLoader
from sentinel.attacks.classifier import VulnerabilityClassifier
from sentinel.attacks.runner import AttackRunner
from sentinel.attacks.reporter import AttackReporter
from sentinel.agents.base import TargetResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_probe() -> AttackProbe:
    return AttackProbe(
        id="TEST-001",
        name="Test Probe",
        category="prompt_injection",
        severity="S3",
        description="A test probe for unit testing.",
        payloads=["payload1", "payload2"],
        expected_safe_behavior="System refuses.",
        expected_vulnerable_behavior="System complies.",
        detection_patterns=["leaked", "secret"],
        tags=["test", "unit"],
    )


@pytest.fixture
def probes_dir(tmp_path: Path) -> Path:
    """Create a temporary probes directory with test YAML files."""
    cat_dir = tmp_path / "prompt_injection"
    cat_dir.mkdir()

    probe1 = {
        "id": "PI-TEST-001",
        "name": "Test Probe 1",
        "category": "prompt_injection",
        "severity": "S3",
        "description": "Test probe one.",
        "payloads": ["payload A", "payload B"],
        "expected_safe_behavior": "Refuses.",
        "expected_vulnerable_behavior": "Complies.",
        "detection_patterns": ["leaked"],
        "tags": ["jailbreak", "test"],
    }
    probe2 = {
        "id": "PI-TEST-002",
        "name": "Test Probe 2",
        "category": "prompt_injection",
        "severity": "S1",
        "description": "Test probe two.",
        "payloads": ["payload C", "payload D", "payload E"],
        "expected_safe_behavior": "Ignores.",
        "expected_vulnerable_behavior": "Follows.",
        "detection_patterns": [],
        "tags": ["encoding"],
    }
    (cat_dir / "PI-TEST-001.yaml").write_text(yaml.dump(probe1))
    (cat_dir / "PI-TEST-002.yaml").write_text(yaml.dump(probe2))

    cat_dir2 = tmp_path / "data_exfiltration"
    cat_dir2.mkdir()
    probe3 = {
        "id": "DE-TEST-001",
        "name": "Data Exfil Test",
        "category": "data_exfiltration",
        "severity": "S4",
        "description": "Test probe three.",
        "payloads": ["exfil payload 1", "exfil payload 2"],
        "expected_safe_behavior": "Refuses.",
        "expected_vulnerable_behavior": "Leaks data.",
        "detection_patterns": ["api_key"],
        "tags": ["exfil", "test"],
    }
    (cat_dir2 / "DE-TEST-001.yaml").write_text(yaml.dump(probe3))

    return tmp_path


@pytest.fixture
def loader(probes_dir: Path) -> ProbeLoader:
    return ProbeLoader(probes_dir=str(probes_dir))


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.provider = "mock"
    return client


@pytest.fixture
def mock_target() -> AsyncMock:
    target = AsyncMock()
    target.describe = Mock(return_value="Test target system")
    target.run.return_value = TargetResult(output="I refuse to comply with that request.")
    return target


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_attack_probe_creation(self, sample_probe: AttackProbe):
        assert sample_probe.id == "TEST-001"
        assert sample_probe.category == "prompt_injection"
        assert len(sample_probe.payloads) == 2
        assert len(sample_probe.detection_patterns) == 2
        assert "test" in sample_probe.tags

    def test_attack_probe_defaults(self):
        probe = AttackProbe(
            id="X-001",
            name="Minimal",
            category="test",
            severity="S0",
            description="Minimal probe.",
            payloads=["p1"],
            expected_safe_behavior="safe",
            expected_vulnerable_behavior="vuln",
        )
        assert probe.detection_patterns == []
        assert probe.tags == []

    def test_payload_result(self):
        pr = PayloadResult(
            probe_id="TEST-001",
            payload_index=0,
            payload="test payload",
            target_output="refused",
            vulnerable=False,
            confidence=0.9,
            detection_matches=[],
            explanation="Safe response",
            latency_ms=123.4,
        )
        assert pr.error is None
        assert isinstance(pr.timestamp, datetime)

    def test_probe_result(self, sample_probe: AttackProbe):
        pr = ProbeResult(
            probe=sample_probe,
            payload_results=[],
            vulnerable=False,
            vulnerability_rate=0.0,
            max_confidence=0.0,
            summary="SAFE: 0/0 payloads succeeded",
        )
        assert not pr.vulnerable
        assert pr.vulnerability_rate == 0.0

    def test_scan_result_passed(self):
        now = datetime.now(timezone.utc)
        scan = ScanResult(
            scan_id="scan_test",
            target_description="test",
            started_at=now,
            completed_at=now,
            duration_seconds=1.0,
            total_probes=5,
            total_payloads=10,
            vulnerable_probes=0,
            vulnerable_payloads=0,
            probe_results=[],
            by_category={},
            by_severity={},
            vulnerability_rate=0.0,
        )
        assert scan.passed is True

    def test_scan_result_failed(self):
        now = datetime.now(timezone.utc)
        scan = ScanResult(
            scan_id="scan_test",
            target_description="test",
            started_at=now,
            completed_at=now,
            duration_seconds=1.0,
            total_probes=5,
            total_payloads=10,
            vulnerable_probes=2,
            vulnerable_payloads=3,
            probe_results=[],
            by_category={},
            by_severity={},
            vulnerability_rate=0.4,
        )
        assert scan.passed is False


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------

class TestProbeLoader:
    def test_load_all(self, loader: ProbeLoader):
        probes = loader.load_all()
        assert len(probes) == 3

    def test_load_category(self, loader: ProbeLoader):
        probes = loader.load_category("prompt_injection")
        assert len(probes) == 2
        assert all(p.category == "prompt_injection" for p in probes)

    def test_load_category_invalid(self, loader: ProbeLoader):
        with pytest.raises(ValueError, match="not found"):
            loader.load_category("nonexistent")

    def test_load_by_severity(self, loader: ProbeLoader):
        probes = loader.load_by_severity("S3")
        assert len(probes) == 2  # S3 and S4
        assert all(p.severity in ("S3", "S4") for p in probes)

    def test_load_by_ids(self, loader: ProbeLoader):
        probes = loader.load_by_ids(["PI-TEST-001"])
        assert len(probes) == 1
        assert probes[0].id == "PI-TEST-001"

    def test_load_by_ids_invalid(self, loader: ProbeLoader):
        with pytest.raises(ValueError, match="not found"):
            loader.load_by_ids(["NONEXISTENT"])

    def test_load_by_tags(self, loader: ProbeLoader):
        probes = loader.load_by_tags(["jailbreak"])
        assert len(probes) == 1
        assert probes[0].id == "PI-TEST-001"

    def test_load_by_tags_multiple(self, loader: ProbeLoader):
        probes = loader.load_by_tags(["test", "encoding"])
        # PI-TEST-001 has "test", PI-TEST-002 has "encoding", DE-TEST-001 has "test"
        assert len(probes) == 3

    def test_list_categories(self, loader: ProbeLoader):
        cats = loader.list_categories()
        assert "prompt_injection" in cats
        assert "data_exfiltration" in cats

    def test_count(self, loader: ProbeLoader):
        counts = loader.count()
        assert counts["prompt_injection"] == 2
        assert counts["data_exfiltration"] == 1
        assert counts["total"] == 3

    def test_invalid_yaml_skipped(self, probes_dir: Path):
        bad_file = probes_dir / "prompt_injection" / "BAD.yaml"
        bad_file.write_text("not: valid: yaml: probe:")
        loader = ProbeLoader(probes_dir=str(probes_dir))
        probes = loader.load_all()
        # Should still load the 3 valid probes, skipping the bad one
        assert len(probes) == 3


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------

class TestVulnerabilityClassifier:
    @pytest.mark.asyncio
    async def test_classify_safe(self, mock_client: AsyncMock, sample_probe: AttackProbe):
        mock_client.generate_structured.return_value = {
            "vulnerable": False,
            "confidence": 0.9,
            "explanation": "The system refused the attack.",
        }
        classifier = VulnerabilityClassifier(model_client=mock_client)
        vulnerable, confidence, explanation = await classifier.classify(
            sample_probe, "payload1", "I cannot help with that."
        )
        assert vulnerable is False
        assert confidence == 0.9
        assert "refused" in explanation

    @pytest.mark.asyncio
    async def test_classify_vulnerable(self, mock_client: AsyncMock, sample_probe: AttackProbe):
        mock_client.generate_structured.return_value = {
            "vulnerable": True,
            "confidence": 0.85,
            "explanation": "The system leaked its system prompt.",
        }
        classifier = VulnerabilityClassifier(model_client=mock_client)
        vulnerable, confidence, explanation = await classifier.classify(
            sample_probe, "payload1", "Here is my secret configuration..."
        )
        assert vulnerable is True
        assert confidence == 0.85

    @pytest.mark.asyncio
    async def test_classify_llm_fails_with_patterns(self, mock_client: AsyncMock, sample_probe: AttackProbe):
        mock_client.generate_structured.side_effect = Exception("LLM error")
        classifier = VulnerabilityClassifier(model_client=mock_client)
        # Output contains "leaked" which is a detection pattern
        vulnerable, confidence, explanation = await classifier.classify(
            sample_probe, "payload1", "Here is the leaked data"
        )
        assert vulnerable is True
        assert confidence == 0.6
        assert "detection patterns matched" in explanation

    @pytest.mark.asyncio
    async def test_classify_llm_fails_no_patterns(self, mock_client: AsyncMock, sample_probe: AttackProbe):
        mock_client.generate_structured.side_effect = Exception("LLM error")
        classifier = VulnerabilityClassifier(model_client=mock_client)
        vulnerable, confidence, explanation = await classifier.classify(
            sample_probe, "payload1", "I refuse."
        )
        assert vulnerable is False
        assert confidence == 0.3

    def test_quick_check_match(self, mock_client: AsyncMock, sample_probe: AttackProbe):
        classifier = VulnerabilityClassifier(model_client=mock_client)
        matches = classifier.quick_check(sample_probe, "The data was LEAKED to the attacker")
        assert "leaked" in matches

    def test_quick_check_no_match(self, mock_client: AsyncMock, sample_probe: AttackProbe):
        classifier = VulnerabilityClassifier(model_client=mock_client)
        matches = classifier.quick_check(sample_probe, "I cannot help with that.")
        assert matches == []


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------

class TestAttackRunner:
    @pytest.mark.asyncio
    async def test_scan_basic(self, mock_client: AsyncMock, mock_target: AsyncMock, loader: ProbeLoader):
        mock_client.generate_structured.return_value = {
            "vulnerable": False,
            "confidence": 0.9,
            "explanation": "Safe response.",
        }
        classifier = VulnerabilityClassifier(model_client=mock_client)
        runner = AttackRunner(classifier=classifier, loader=loader)
        result = await runner.scan(mock_target)

        assert result.total_probes == 3
        assert result.vulnerability_rate == 0.0
        assert result.passed

    @pytest.mark.asyncio
    async def test_scan_with_category_filter(self, mock_client: AsyncMock, mock_target: AsyncMock, loader: ProbeLoader):
        mock_client.generate_structured.return_value = {
            "vulnerable": False,
            "confidence": 0.9,
            "explanation": "Safe.",
        }
        classifier = VulnerabilityClassifier(model_client=mock_client)
        runner = AttackRunner(classifier=classifier, loader=loader)
        result = await runner.scan(mock_target, categories=["prompt_injection"])

        assert result.total_probes == 2

    @pytest.mark.asyncio
    async def test_scan_vulnerability_detected(self, mock_client: AsyncMock, mock_target: AsyncMock, loader: ProbeLoader):
        mock_client.generate_structured.return_value = {
            "vulnerable": True,
            "confidence": 0.8,
            "explanation": "System was compromised.",
        }
        classifier = VulnerabilityClassifier(model_client=mock_client)
        runner = AttackRunner(classifier=classifier, loader=loader)
        result = await runner.scan(mock_target)

        assert result.vulnerable_probes == 3
        assert not result.passed

    @pytest.mark.asyncio
    async def test_scan_target_error(self, mock_client: AsyncMock, mock_target: AsyncMock, loader: ProbeLoader):
        mock_target.run.return_value = TargetResult(output="", error="Connection timeout")
        mock_client.generate_structured.return_value = {
            "vulnerable": False,
            "confidence": 0.5,
            "explanation": "Error.",
        }
        classifier = VulnerabilityClassifier(model_client=mock_client)
        runner = AttackRunner(classifier=classifier, loader=loader)
        result = await runner.scan(mock_target)

        # All payloads should have errors and be classified safe
        for pr in result.probe_results:
            for payload_r in pr.payload_results:
                assert payload_r.error == "Connection timeout"
                assert not payload_r.vulnerable

    @pytest.mark.asyncio
    async def test_scan_no_probes_raises(self, mock_client: AsyncMock, mock_target: AsyncMock, loader: ProbeLoader):
        classifier = VulnerabilityClassifier(model_client=mock_client)
        runner = AttackRunner(classifier=classifier, loader=loader)
        with pytest.raises(ValueError, match="No probes matched"):
            await runner.scan(mock_target, min_severity="S4", categories=["prompt_injection"])
            # prompt_injection has S3 and S1, no S4

    @pytest.mark.asyncio
    async def test_run_single(self, mock_client: AsyncMock, mock_target: AsyncMock, loader: ProbeLoader):
        mock_client.generate_structured.return_value = {
            "vulnerable": False,
            "confidence": 0.9,
            "explanation": "Safe.",
        }
        classifier = VulnerabilityClassifier(model_client=mock_client)
        runner = AttackRunner(classifier=classifier, loader=loader)
        result = await runner.run_single("PI-TEST-001", mock_target)

        assert result.probe.id == "PI-TEST-001"
        assert len(result.payload_results) == 2

    @pytest.mark.asyncio
    async def test_scan_target_exception(self, mock_client: AsyncMock, mock_target: AsyncMock, loader: ProbeLoader):
        mock_target.run.side_effect = RuntimeError("Crash")
        classifier = VulnerabilityClassifier(model_client=mock_client)
        runner = AttackRunner(classifier=classifier, loader=loader)
        result = await runner.scan(mock_target, probe_ids=["PI-TEST-001"])

        assert result.total_probes == 1
        for pr in result.probe_results:
            for payload_r in pr.payload_results:
                assert payload_r.error == "Crash"


# ---------------------------------------------------------------------------
# Reporter tests
# ---------------------------------------------------------------------------

class TestAttackReporter:
    def _make_scan(self, vulnerable: bool = False) -> ScanResult:
        now = datetime.now(timezone.utc)
        probe = AttackProbe(
            id="PI-001",
            name="Test Probe",
            category="prompt_injection",
            severity="S3",
            description="A test probe.",
            payloads=["p1"],
            expected_safe_behavior="Refuses.",
            expected_vulnerable_behavior="Complies.",
            detection_patterns=[],
            tags=[],
        )
        payload_result = PayloadResult(
            probe_id="PI-001",
            payload_index=0,
            payload="test payload",
            target_output="test output",
            vulnerable=vulnerable,
            confidence=0.8 if vulnerable else 0.9,
            detection_matches=[],
            explanation="Test explanation",
            latency_ms=100.0,
        )
        probe_result = ProbeResult(
            probe=probe,
            payload_results=[payload_result],
            vulnerable=vulnerable,
            vulnerability_rate=1.0 if vulnerable else 0.0,
            max_confidence=0.8 if vulnerable else 0.0,
            summary="VULNERABLE" if vulnerable else "SAFE",
        )
        return ScanResult(
            scan_id="scan_test",
            target_description="Test target",
            started_at=now,
            completed_at=now,
            duration_seconds=1.5,
            total_probes=1,
            total_payloads=1,
            vulnerable_probes=1 if vulnerable else 0,
            vulnerable_payloads=1 if vulnerable else 0,
            probe_results=[probe_result],
            by_category={"prompt_injection": {"total": 1, "vulnerable": 1 if vulnerable else 0, "safe": 0 if vulnerable else 1}},
            by_severity={"S3": {"total": 1, "vulnerable": 1 if vulnerable else 0, "safe": 0 if vulnerable else 1}},
            vulnerability_rate=1.0 if vulnerable else 0.0,
        )

    def test_markdown_report_pass(self):
        scan = self._make_scan(vulnerable=False)
        reporter = AttackReporter()
        md = reporter.to_markdown(scan)
        assert "# Sentinel Attack Scan Report" in md
        assert "PASS" in md
        assert "No Vulnerabilities Found" in md

    def test_markdown_report_fail(self):
        scan = self._make_scan(vulnerable=True)
        reporter = AttackReporter()
        md = reporter.to_markdown(scan)
        assert "FAIL" in md
        assert "Vulnerabilities Found" in md
        assert "PI-001" in md
        assert "Test Probe" in md

    def test_json_report(self):
        scan = self._make_scan(vulnerable=True)
        reporter = AttackReporter()
        data = reporter.to_json(scan)
        assert data["scan_id"] == "scan_test"
        assert data["vulnerable_probes"] == 1
        assert len(data["probe_results"]) == 1

    def test_markdown_report_has_category_table(self):
        scan = self._make_scan(vulnerable=True)
        reporter = AttackReporter()
        md = reporter.to_markdown(scan)
        assert "Results by Category" in md
        assert "prompt_injection" in md

    def test_markdown_report_has_severity_table(self):
        scan = self._make_scan(vulnerable=True)
        reporter = AttackReporter()
        md = reporter.to_markdown(scan)
        assert "Results by Severity" in md
        assert "S3" in md


# ---------------------------------------------------------------------------
# DB model tests
# ---------------------------------------------------------------------------

class TestDBModels:
    @pytest.mark.asyncio
    async def test_attack_scan_crud(self, db):
        from sentinel.db.connection import get_session
        from sentinel.db.models import AttackScan

        async with get_session() as session:
            scan = AttackScan(
                id="scan_test_001",
                target_description="Test target",
                total_probes=10,
                vulnerable_probes=3,
                vulnerability_rate=0.3,
                results_json="{}",
            )
            session.add(scan)
            await session.commit()

        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(select(AttackScan).where(AttackScan.id == "scan_test_001"))
            row = result.scalar_one()
            assert row.total_probes == 10
            assert row.vulnerable_probes == 3
            assert row.vulnerability_rate == 0.3

    @pytest.mark.asyncio
    async def test_attack_finding_crud(self, db):
        from sentinel.db.connection import get_session
        from sentinel.db.models import AttackScan, AttackFinding

        async with get_session() as session:
            scan = AttackScan(id="scan_test_002", total_probes=1, vulnerable_probes=1)
            session.add(scan)
            await session.commit()

        async with get_session() as session:
            finding = AttackFinding(
                scan_id="scan_test_002",
                probe_id="PI-001",
                probe_name="Test Probe",
                category="prompt_injection",
                severity="S3",
                vulnerable=True,
                vulnerability_rate=1.0,
                summary="Vulnerable",
            )
            session.add(finding)
            await session.commit()

        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(AttackFinding).where(AttackFinding.scan_id == "scan_test_002")
            )
            row = result.scalar_one()
            assert row.probe_id == "PI-001"
            assert row.vulnerable is True

    @pytest.mark.asyncio
    async def test_scan_finding_relationship(self, db):
        from sentinel.db.connection import get_session
        from sentinel.db.models import AttackScan, AttackFinding
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select

        async with get_session() as session:
            scan = AttackScan(id="scan_rel", total_probes=2, vulnerable_probes=1)
            session.add(scan)
            await session.commit()

        async with get_session() as session:
            f1 = AttackFinding(scan_id="scan_rel", probe_id="PI-001", probe_name="P1", category="pi", severity="S3", vulnerable=True)
            f2 = AttackFinding(scan_id="scan_rel", probe_id="PI-002", probe_name="P2", category="pi", severity="S1", vulnerable=False)
            session.add_all([f1, f2])
            await session.commit()

        async with get_session() as session:
            result = await session.execute(
                select(AttackScan)
                .options(selectinload(AttackScan.findings))
                .where(AttackScan.id == "scan_rel")
            )
            scan = result.scalar_one()
            assert len(scan.findings) == 2


# ---------------------------------------------------------------------------
# Real probes validation (tests that actual YAML files load correctly)
# ---------------------------------------------------------------------------

class TestRealProbes:
    def test_probes_load(self):
        """Verify that all shipped YAML probes load without errors."""
        loader = ProbeLoader()
        probes = loader.load_all()
        assert len(probes) >= 77, f"Expected 77+ probes, got {len(probes)}"

    def test_all_probes_valid(self):
        """Every probe must have required fields and valid severity."""
        loader = ProbeLoader()
        probes = loader.load_all()
        for p in probes:
            assert p.id, f"Probe missing ID"
            assert len(p.payloads) >= 2, f"{p.id}: needs at least 2 payloads, has {len(p.payloads)}"
            assert p.severity in ("S0", "S1", "S2", "S3", "S4"), f"{p.id}: invalid severity {p.severity}"
            assert p.category, f"{p.id}: missing category"
            assert p.description, f"{p.id}: missing description"

    def test_category_counts(self):
        """Verify expected categories exist."""
        loader = ProbeLoader()
        cats = loader.list_categories()
        expected = [
            "data_exfiltration",
            "evasion_bypass",
            "indirect_injection",
            "memory_poisoning",
            "privilege_escalation",
            "prompt_injection",
            "tool_exfiltration",
            "unauthorized_action",
        ]
        for cat in expected:
            assert cat in cats, f"Missing category: {cat}"

    def test_count_per_category(self):
        """Check minimum probe counts per category."""
        loader = ProbeLoader()
        counts = loader.count()
        assert counts.get("prompt_injection", 0) >= 15
        assert counts.get("data_exfiltration", 0) >= 10
        assert counts.get("tool_exfiltration", 0) >= 10
        assert counts.get("privilege_escalation", 0) >= 8
        assert counts.get("evasion_bypass", 0) >= 10
        assert counts.get("memory_poisoning", 0) >= 8
        assert counts.get("indirect_injection", 0) >= 8
        assert counts.get("unauthorized_action", 0) >= 8
