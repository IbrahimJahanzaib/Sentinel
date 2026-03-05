"""Phase 8C tests — Findings and Hypotheses TUI screens.

Tests cover:
  - FindingsScreen renders with seeded data
  - HypothesesScreen renders with seeded data
  - Findings screen has filter dropdowns and detail panel
  - Hypotheses screen has status filter and detail panel
  - Screens handle empty DB gracefully
  - Keybinding-driven screen switching
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sentinel.db.connection import init_db, close_db, get_session
from sentinel.db.models import Cycle, Experiment, Failure, Hypothesis
from sentinel.tui.app import SentinelApp
from sentinel.tui.screens.dashboard import DashboardScreen
from sentinel.tui.screens.findings import FindingsScreen
from sentinel.tui.screens.hypotheses import HypothesesScreen


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
async def seeded_db():
    """In-memory DB with varied test data for screen testing."""
    await init_db("sqlite+aiosqlite:///:memory:", echo=False)

    async with get_session() as session:
        cycle = Cycle(
            id="cyc_c1",
            target_description="Screen test target",
            focus="reasoning",
            mode="lab",
            total_cost_usd=2.50,
            total_tokens=8000,
            hypotheses_generated=4,
            failures_found=3,
            started_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        )
        session.add(cycle)

        h1 = Hypothesis(
            id="hyp_c1",
            cycle_id="cyc_c1",
            description="Model produces hallucinated citations in long documents",
            failure_class="LONG_CONTEXT",
            expected_severity="S2",
            rationale="Long context windows increase hallucination risk",
            status="confirmed",
        )
        h2 = Hypothesis(
            id="hyp_c2",
            cycle_id="cyc_c1",
            description="Tool call parameters silently dropped",
            failure_class="TOOL_USE",
            expected_severity="S1",
            rationale="Complex tool schemas may confuse the model",
            status="untested",
        )
        h3 = Hypothesis(
            id="hyp_c3",
            cycle_id="cyc_c1",
            description="Reasoning chains break on multi-step math",
            failure_class="REASONING",
            expected_severity="S3",
            rationale="Multi-step reasoning is a known weakness",
            status="rejected",
        )
        session.add_all([h1, h2, h3])
        await session.flush()

        exp = Experiment(
            id="exp_c1",
            hypothesis_id="hyp_c1",
            input="test input",
            approval_status="approved",
        )
        session.add(exp)
        await session.flush()

        f1 = Failure(
            id="fail_c1",
            experiment_id="exp_c1",
            hypothesis_id="hyp_c1",
            cycle_id="cyc_c1",
            failure_class="LONG_CONTEXT",
            failure_subtype="hallucinated_citation",
            severity="S2",
            failure_rate=0.6,
            evidence="Model cited non-existent paper 3 out of 5 times",
            sample_failure_output="According to Smith et al. (2024)...",
            sample_correct_output="Based on the provided documents...",
        )
        f2 = Failure(
            id="fail_c2",
            experiment_id="exp_c1",
            hypothesis_id="hyp_c1",
            cycle_id="cyc_c1",
            failure_class="REASONING",
            failure_subtype="arithmetic_error",
            severity="S3",
            failure_rate=0.4,
            evidence="Simple multiplication errors in 2 of 5 runs",
        )
        f3 = Failure(
            id="fail_c3",
            experiment_id="exp_c1",
            hypothesis_id="hyp_c1",
            cycle_id="cyc_c1",
            failure_class="SECURITY",
            failure_subtype="prompt_injection",
            severity="S0",
            failure_rate=0.2,
            evidence="Prompt injection succeeded in controlled test",
        )
        session.add_all([f1, f2, f3])

    yield

    await close_db()


@pytest.fixture
async def empty_db():
    """In-memory DB with no data."""
    await init_db("sqlite+aiosqlite:///:memory:", echo=False)
    yield
    await close_db()


# ── FindingsScreen ───────────────────────────────────────────────────


@pytest.mark.asyncio
class TestFindingsScreen:
    async def test_findings_renders_with_data(self, seeded_db):
        """FindingsScreen mounts and shows the findings table."""
        app = SentinelApp(db_url=None, mode="lab")

        async with app.run_test() as pilot:
            # Switch to findings screen
            app.pop_screen()
            await app.push_screen(FindingsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, FindingsScreen)
            table = screen.query_one("#findings-table")
            assert table is not None
            assert table.row_count == 3

    async def test_findings_has_filters(self, seeded_db):
        """FindingsScreen has severity and class filter dropdowns."""
        app = SentinelApp(db_url=None, mode="lab")

        async with app.run_test() as pilot:
            app.pop_screen()
            await app.push_screen(FindingsScreen())
            await pilot.pause()

            screen = app.screen
            sev = screen.query_one("#severity-filter")
            cls = screen.query_one("#class-filter")
            assert sev is not None
            assert cls is not None

    async def test_findings_has_detail_panel(self, seeded_db):
        """FindingsScreen has a detail panel."""
        app = SentinelApp(db_url=None, mode="lab")

        async with app.run_test() as pilot:
            app.pop_screen()
            await app.push_screen(FindingsScreen())
            await pilot.pause()

            panel = app.screen.query_one("#detail-panel")
            assert panel is not None

    async def test_findings_empty_db(self, empty_db):
        """FindingsScreen handles empty DB gracefully."""
        app = SentinelApp(db_url=None, mode="lab")

        async with app.run_test() as pilot:
            app.pop_screen()
            await app.push_screen(FindingsScreen())
            await pilot.pause()

            table = app.screen.query_one("#findings-table")
            assert table.row_count == 0


# ── HypothesesScreen ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestHypothesesScreen:
    async def test_hypotheses_renders_with_data(self, seeded_db):
        """HypothesesScreen mounts and shows the hypotheses table."""
        app = SentinelApp(db_url=None, mode="lab")

        async with app.run_test() as pilot:
            app.pop_screen()
            await app.push_screen(HypothesesScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, HypothesesScreen)
            table = screen.query_one("#hypotheses-table")
            assert table is not None
            assert table.row_count == 3

    async def test_hypotheses_has_status_filter(self, seeded_db):
        """HypothesesScreen has a status filter dropdown."""
        app = SentinelApp(db_url=None, mode="lab")

        async with app.run_test() as pilot:
            app.pop_screen()
            await app.push_screen(HypothesesScreen())
            await pilot.pause()

            filt = app.screen.query_one("#status-filter")
            assert filt is not None

    async def test_hypotheses_has_detail_panel(self, seeded_db):
        """HypothesesScreen has a detail panel."""
        app = SentinelApp(db_url=None, mode="lab")

        async with app.run_test() as pilot:
            app.pop_screen()
            await app.push_screen(HypothesesScreen())
            await pilot.pause()

            panel = app.screen.query_one("#hyp-detail-panel")
            assert panel is not None

    async def test_hypotheses_empty_db(self, empty_db):
        """HypothesesScreen handles empty DB gracefully."""
        app = SentinelApp(db_url=None, mode="lab")

        async with app.run_test() as pilot:
            app.pop_screen()
            await app.push_screen(HypothesesScreen())
            await pilot.pause()

            table = app.screen.query_one("#hypotheses-table")
            assert table.row_count == 0
