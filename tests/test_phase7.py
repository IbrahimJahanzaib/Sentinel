"""Phase 7 tests — Reporting queries, markdown, and JSON generation.

All tests use an in-memory SQLite database with seeded data.
"""

from __future__ import annotations

import json

import pytest

from sentinel.db.connection import init_db, close_db, get_session
from sentinel.db.models import Cycle, Failure, Hypothesis, Intervention
from sentinel.reporting.queries import (
    get_cycles,
    get_failures,
    get_hypotheses,
    get_interventions,
    parse_severity_filter,
)
from sentinel.reporting.markdown_report import generate_markdown_report
from sentinel.reporting.json_report import generate_json_report
from sentinel.taxonomy.failure_types import Severity


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
async def seeded_db():
    """Create an in-memory DB and seed it with test data."""
    await init_db("sqlite+aiosqlite:///:memory:", echo=False)

    async with get_session() as session:
        cycle = Cycle(
            id="cyc001",
            target_description="test target",
            mode="lab",
            total_cost_usd=0.42,
            total_tokens=1500,
            hypotheses_generated=3,
            failures_found=2,
        )
        session.add(cycle)

        h1 = Hypothesis(
            id="hyp001",
            cycle_id="cyc001",
            description="Model hallucinates under long context",
            failure_class="LONG_CONTEXT",
            expected_severity="S3",
            status="confirmed",
        )
        h2 = Hypothesis(
            id="hyp002",
            cycle_id="cyc001",
            description="Tool calls use wrong parameters",
            failure_class="TOOL_USE",
            expected_severity="S2",
            status="untested",
        )
        h3 = Hypothesis(
            id="hyp003",
            cycle_id="cyc001",
            description="Reasoning drift in multi-step tasks",
            failure_class="REASONING",
            expected_severity="S1",
            status="rejected",
        )
        session.add_all([h1, h2, h3])
        await session.flush()

        # We need an experiment for the foreign key
        from sentinel.db.models import Experiment
        exp = Experiment(
            id="exp001",
            hypothesis_id="hyp001",
            input="test input",
            approval_status="approved",
        )
        session.add(exp)
        await session.flush()

        f1 = Failure(
            id="fail001",
            experiment_id="exp001",
            hypothesis_id="hyp001",
            cycle_id="cyc001",
            failure_class="LONG_CONTEXT",
            failure_subtype="attention_dilution",
            severity="S3",
            failure_rate=0.6,
            evidence="Model forgot instructions after 50k tokens",
        )
        f2 = Failure(
            id="fail002",
            experiment_id="exp001",
            hypothesis_id="hyp001",
            cycle_id="cyc001",
            failure_class="REASONING",
            failure_subtype="hallucination",
            severity="S1",
            failure_rate=0.2,
            evidence="Minor factual errors in low-stakes context",
        )
        session.add_all([f1, f2])
        await session.flush()

        iv1 = Intervention(
            id="int001",
            failure_id="fail001",
            cycle_id="cyc001",
            type="prompt_mutation",
            description="Add explicit reminder at context boundary",
            estimated_effectiveness="high",
            validation_status="fixed",
        )
        iv2 = Intervention(
            id="int002",
            failure_id="fail001",
            cycle_id="cyc001",
            type="guardrail",
            description="Add output length check",
            estimated_effectiveness="medium",
            validation_status="pending",
        )
        session.add_all([iv1, iv2])

    yield

    await close_db()


@pytest.fixture
async def empty_db():
    """Create an in-memory DB with no data."""
    await init_db("sqlite+aiosqlite:///:memory:", echo=False)
    yield
    await close_db()


# ── Severity parsing ─────────────────────────────────────────────────


class TestSeverityParsing:
    def test_parse_with_plus(self):
        assert parse_severity_filter("S2+") == Severity.S2

    def test_parse_without_plus(self):
        assert parse_severity_filter("S4") == Severity.S4

    def test_parse_s0(self):
        assert parse_severity_filter("S0+") == Severity.S0


# ── Query functions ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestQueries:
    async def test_get_cycles(self, seeded_db):
        cycles = await get_cycles()
        assert len(cycles) == 1
        assert cycles[0].id == "cyc001"

    async def test_get_failures_no_filter(self, seeded_db):
        failures = await get_failures()
        assert len(failures) == 2

    async def test_get_failures_severity_filter(self, seeded_db):
        failures = await get_failures(min_severity="S2+")
        assert len(failures) == 1
        assert failures[0].severity == "S3"

    async def test_get_failures_class_filter(self, seeded_db):
        failures = await get_failures(failure_class="REASONING")
        assert len(failures) == 1
        assert failures[0].failure_class == "REASONING"

    async def test_get_hypotheses_no_filter(self, seeded_db):
        hyps = await get_hypotheses()
        assert len(hyps) == 3

    async def test_get_hypotheses_status_filter(self, seeded_db):
        hyps = await get_hypotheses(status="confirmed")
        assert len(hyps) == 1
        assert hyps[0].id == "hyp001"

    async def test_get_interventions(self, seeded_db):
        ivs = await get_interventions()
        assert len(ivs) == 2

    async def test_get_interventions_cycle_filter(self, seeded_db):
        ivs = await get_interventions(cycle_id="nonexistent")
        assert len(ivs) == 0


# ── Markdown report ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMarkdownReport:
    async def test_sections_present(self, seeded_db):
        cycles = await get_cycles()
        failures = await get_failures()
        interventions = await get_interventions()
        md = generate_markdown_report(cycles, failures, interventions)

        assert "# Sentinel Findings Report" in md
        assert "## Executive Summary" in md
        assert "## Severity Distribution" in md
        assert "## Findings by Failure Class" in md
        assert "## Interventions & Recommendations" in md

    async def test_summary_values(self, seeded_db):
        cycles = await get_cycles()
        failures = await get_failures()
        interventions = await get_interventions()
        md = generate_markdown_report(cycles, failures, interventions)

        assert "Cycles completed:** 1" in md
        assert "Failures discovered:** 2" in md
        assert "$0.4200" in md

    async def test_empty_db_produces_valid_output(self, empty_db):
        md = generate_markdown_report([], [], [])
        assert "# Sentinel Findings Report" in md
        assert "Failures discovered:** 0" in md
        assert "No interventions proposed yet." in md


# ── JSON report ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestJsonReport:
    async def test_top_level_keys(self, seeded_db):
        cycles = await get_cycles()
        failures = await get_failures()
        interventions = await get_interventions()
        report = generate_json_report(cycles, failures, interventions)

        assert "summary" in report
        assert "severity_distribution" in report
        assert "findings" in report
        assert "interventions" in report

    async def test_summary_counts(self, seeded_db):
        cycles = await get_cycles()
        failures = await get_failures()
        interventions = await get_interventions()
        report = generate_json_report(cycles, failures, interventions)

        assert report["summary"]["cycles"] == 1
        assert report["summary"]["failures"] == 2
        assert report["summary"]["interventions"] == 2
        assert report["summary"]["total_cost_usd"] == pytest.approx(0.42)

    async def test_serialisable(self, seeded_db):
        cycles = await get_cycles()
        failures = await get_failures()
        interventions = await get_interventions()
        report = generate_json_report(cycles, failures, interventions)
        # Must be JSON-serialisable
        text = json.dumps(report, indent=2)
        parsed = json.loads(text)
        assert parsed["summary"]["cycles"] == 1

    async def test_empty_db_valid(self, empty_db):
        report = generate_json_report([], [], [])
        assert report["summary"]["cycles"] == 0
        assert report["findings"] == []
        assert report["interventions"] == []
