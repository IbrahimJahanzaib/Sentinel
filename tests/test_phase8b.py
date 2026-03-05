"""Phase 8B tests — TUI app and dashboard screen.

Tests cover:
  - SentinelApp instantiation and config
  - DashboardScreen mounts via Textual pilot
  - Dashboard queries DB and displays cycle/failure data
  - Dashboard handles empty DB gracefully
  - CLI tui --help works
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from sentinel.cli import cli
from sentinel.db.connection import init_db, close_db, get_session
from sentinel.db.models import Cycle, Experiment, Failure, Hypothesis
from sentinel.tui.app import SentinelApp
from sentinel.tui.screens.dashboard import DashboardScreen


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
async def seeded_db():
    """In-memory DB with test data for dashboard."""
    await init_db("sqlite+aiosqlite:///:memory:", echo=False)

    async with get_session() as session:
        cycle = Cycle(
            id="cyc_dash1",
            target_description="Dashboard test target",
            focus="reasoning",
            mode="lab",
            total_cost_usd=1.23,
            total_tokens=5000,
            hypotheses_generated=5,
            failures_found=3,
            started_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        )
        session.add(cycle)

        h1 = Hypothesis(
            id="hyp_d1",
            cycle_id="cyc_dash1",
            description="Test hypothesis",
            failure_class="REASONING",
            expected_severity="S2",
            status="confirmed",
        )
        session.add(h1)
        await session.flush()

        exp = Experiment(
            id="exp_d1",
            hypothesis_id="hyp_d1",
            input="test",
            approval_status="approved",
        )
        session.add(exp)
        await session.flush()

        f1 = Failure(
            id="fail_d1",
            experiment_id="exp_d1",
            hypothesis_id="hyp_d1",
            cycle_id="cyc_dash1",
            failure_class="REASONING",
            severity="S2",
            failure_rate=0.5,
            evidence="Test evidence",
        )
        f2 = Failure(
            id="fail_d2",
            experiment_id="exp_d1",
            hypothesis_id="hyp_d1",
            cycle_id="cyc_dash1",
            failure_class="LONG_CONTEXT",
            severity="S0",
            failure_rate=0.8,
            evidence="Critical failure",
        )
        session.add_all([f1, f2])

    yield

    await close_db()


@pytest.fixture
async def empty_db():
    """In-memory DB with no data."""
    await init_db("sqlite+aiosqlite:///:memory:", echo=False)
    yield
    await close_db()


# ── App instantiation ────────────────────────────────────────────────


class TestSentinelApp:
    def test_app_instantiation(self):
        app = SentinelApp(db_url="sqlite+aiosqlite:///:memory:", mode="lab")
        assert app.sentinel_mode == "LAB"
        assert app.TITLE == "Sentinel"

    def test_app_default_mode(self):
        app = SentinelApp()
        assert app.sentinel_mode == "LAB"

    def test_app_has_keybindings(self):
        app = SentinelApp()
        keys = [b.key for b in app.BINDINGS]
        assert "d" in keys
        assert "f" in keys
        assert "h" in keys
        assert "q" in keys


# ── Dashboard screen (Textual pilot) ────────────────────────────────


@pytest.mark.asyncio
class TestDashboardScreen:
    async def test_dashboard_mounts(self, seeded_db):
        """Dashboard screen mounts without error using Textual pilot."""
        app = SentinelApp(db_url=None, mode="lab")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

    async def test_dashboard_has_widgets(self, seeded_db):
        """Dashboard should have stats panel, severity panel, and cycles table."""
        app = SentinelApp(db_url=None, mode="lab")
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert screen.query_one("#stats-panel") is not None
            assert screen.query_one("#severity-panel") is not None
            assert screen.query_one("#cycles-table") is not None

    async def test_dashboard_empty_db(self, empty_db):
        """Dashboard handles empty database gracefully."""
        app = SentinelApp(db_url=None, mode="shadow")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)
            stats = app.screen.query_one("#stats-panel")
            assert stats is not None


# ── CLI tui command ──────────────────────────────────────────────────


class TestTuiCLI:
    def test_tui_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tui", "--help"])
        assert result.exit_code == 0
        assert "Launch the interactive terminal UI" in result.output
