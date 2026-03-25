"""Tests for sentinel.dashboard — server, API routes, static files."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sentinel.db.connection import close_db, get_session, init_db
from sentinel.db.models import (
    AttackScan,
    BenchmarkRun,
    Cycle,
    Failure,
    Hypothesis,
    Intervention,
    ModelComparison,
)


@pytest_asyncio.fixture
async def app():
    """Create dashboard app with in-memory DB."""
    await init_db("sqlite+aiosqlite:///:memory:")

    from sentinel.dashboard.server import create_dashboard_app

    _app = create_dashboard_app()
    # Override the lifespan (DB already initialized)
    _app.router.lifespan_context = None
    yield _app

    await close_db()


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seeded_app(app):
    """App with seed data."""
    now = datetime.now(timezone.utc)
    cycle_id = f"cyc_{uuid.uuid4().hex[:8]}"
    hyp_id = f"hyp_{uuid.uuid4().hex[:8]}"
    fail_id = f"fail_{uuid.uuid4().hex[:8]}"
    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    int_id = f"int_{uuid.uuid4().hex[:8]}"
    scan_id = f"scan_{uuid.uuid4().hex[:8]}"
    bench_id = f"bench_{uuid.uuid4().hex[:8]}"

    async with get_session() as session:
        session.add(Cycle(
            id=cycle_id, target_description="Test target", focus="reasoning",
            mode="lab", started_at=now, hypotheses_generated=2,
            hypotheses_confirmed=1, experiments_run=3, failures_found=1,
        ))

    async with get_session() as session:
        session.add(Hypothesis(
            id=hyp_id, cycle_id=cycle_id,
            description="Model hallucinates under pressure",
            failure_class="REASONING", expected_severity="S2", status="confirmed",
        ))

    async with get_session() as session:
        from sentinel.db.models import Experiment
        session.add(Experiment(
            id=exp_id, hypothesis_id=hyp_id,
            input="Test query", num_runs=3, approval_status="approved",
        ))

    async with get_session() as session:
        session.add(Failure(
            id=fail_id, experiment_id=exp_id, hypothesis_id=hyp_id,
            cycle_id=cycle_id, failure_class="REASONING", severity="S2",
            failure_rate=0.6, evidence="Fabricated statistics",
        ))

    async with get_session() as session:
        session.add(Intervention(
            id=int_id, failure_id=fail_id, cycle_id=cycle_id,
            type="prompt_mutation", description="Add grounding instruction",
            validation_status="fixed",
        ))

    async with get_session() as session:
        session.add(AttackScan(
            id=scan_id, target_description="Test target", started_at=now,
            total_probes=20, vulnerable_probes=3, vulnerability_rate=0.15,
            results_json='{"by_category": {}}',
        ))

    async with get_session() as session:
        session.add(BenchmarkRun(
            id=bench_id, model_name="test-model", model_provider="test",
            target_description="Test target", profile="quick",
            started_at=now, duration_seconds=10.0,
            metrics_json='{"success_rate": 0.85, "failure_rate": 0.15}',
        ))

    async with get_session() as session:
        session.add(ModelComparison(
            id="cmp_test", benchmark_ids='["bench_1"]',
            rankings_json='{}', summary="Comparison summary",
        ))

    return {
        "cycle_id": cycle_id, "hyp_id": hyp_id, "fail_id": fail_id,
        "exp_id": exp_id, "int_id": int_id, "scan_id": scan_id,
        "bench_id": bench_id,
    }


# ═══════════════════════════════════════════════════════════════════
# Health & Index
# ═══════════════════════════════════════════════════════════════════

class TestServerBasics:

    @pytest.mark.asyncio
    async def test_health(self, client):
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_index_returns_html(self, client):
        res = await client.get("/")
        assert res.status_code == 200
        assert "Sentinel Dashboard" in res.text

    @pytest.mark.asyncio
    async def test_static_css(self, client):
        res = await client.get("/static/css/style.css")
        assert res.status_code == 200
        assert "sidebar" in res.text

    @pytest.mark.asyncio
    async def test_static_js(self, client):
        res = await client.get("/static/js/app.js")
        assert res.status_code == 200
        assert "App" in res.text

    @pytest.mark.asyncio
    async def test_api_docs(self, client):
        res = await client.get("/api/docs")
        assert res.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# Settings & Stats
# ═══════════════════════════════════════════════════════════════════

class TestSettingsAPI:

    @pytest.mark.asyncio
    async def test_global_stats_empty(self, client):
        res = await client.get("/api/settings/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["total_cycles"] == 0
        assert data["total_failures"] == 0

    @pytest.mark.asyncio
    async def test_global_stats_with_data(self, client, seeded_app):
        res = await client.get("/api/settings/stats")
        data = res.json()
        assert data["total_cycles"] == 1
        assert data["total_failures"] == 1
        assert data["total_benchmarks"] == 1
        assert data["total_attack_scans"] == 1

    @pytest.mark.asyncio
    async def test_settings(self, client):
        res = await client.get("/api/settings")
        assert res.status_code == 200
        data = res.json()
        assert "mode" in data
        assert "default_model" in data


# ═══════════════════════════════════════════════════════════════════
# Cycles API
# ═══════════════════════════════════════════════════════════════════

class TestCyclesAPI:

    @pytest.mark.asyncio
    async def test_list_cycles_empty(self, client):
        res = await client.get("/api/cycles")
        assert res.status_code == 200
        assert res.json() == []

    @pytest.mark.asyncio
    async def test_list_cycles(self, client, seeded_app):
        res = await client.get("/api/cycles")
        data = res.json()
        assert len(data) == 1
        assert data[0]["id"] == seeded_app["cycle_id"]
        assert data[0]["focus"] == "reasoning"

    @pytest.mark.asyncio
    async def test_get_cycle(self, client, seeded_app):
        res = await client.get(f"/api/cycles/{seeded_app['cycle_id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["cycle"]["id"] == seeded_app["cycle_id"]
        assert len(data["hypotheses"]) == 1
        assert len(data["failures"]) == 1
        assert len(data["interventions"]) == 1

    @pytest.mark.asyncio
    async def test_get_cycle_404(self, client):
        res = await client.get("/api/cycles/nonexistent")
        assert res.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Failures API
# ═══════════════════════════════════════════════════════════════════

class TestFailuresAPI:

    @pytest.mark.asyncio
    async def test_list_failures_empty(self, client):
        res = await client.get("/api/failures")
        assert res.status_code == 200
        assert res.json() == []

    @pytest.mark.asyncio
    async def test_list_failures(self, client, seeded_app):
        res = await client.get("/api/failures")
        data = res.json()
        assert len(data) == 1
        assert data[0]["severity"] == "S2"

    @pytest.mark.asyncio
    async def test_filter_by_severity(self, client, seeded_app):
        res = await client.get("/api/failures?severity=S2")
        assert len(res.json()) == 1
        res2 = await client.get("/api/failures?severity=S4")
        assert len(res2.json()) == 0

    @pytest.mark.asyncio
    async def test_filter_by_class(self, client, seeded_app):
        res = await client.get("/api/failures?failure_class=REASONING")
        assert len(res.json()) == 1

    @pytest.mark.asyncio
    async def test_failure_stats(self, client, seeded_app):
        res = await client.get("/api/failures/stats")
        data = res.json()
        assert data["total"] == 1
        assert "REASONING" in data["by_class"]
        assert "S2" in data["by_severity"]

    @pytest.mark.asyncio
    async def test_get_failure(self, client, seeded_app):
        res = await client.get(f"/api/failures/{seeded_app['fail_id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["failure"]["severity"] == "S2"
        assert len(data["interventions"]) == 1

    @pytest.mark.asyncio
    async def test_get_failure_404(self, client):
        res = await client.get("/api/failures/nonexistent")
        assert res.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Benchmarks API
# ═══════════════════════════════════════════════════════════════════

class TestBenchmarksAPI:

    @pytest.mark.asyncio
    async def test_list_benchmarks_empty(self, client):
        res = await client.get("/api/benchmarks")
        assert res.status_code == 200
        assert res.json() == []

    @pytest.mark.asyncio
    async def test_list_benchmarks(self, client, seeded_app):
        res = await client.get("/api/benchmarks")
        data = res.json()
        assert len(data) == 1
        assert data[0]["model_name"] == "test-model"

    @pytest.mark.asyncio
    async def test_get_benchmark(self, client, seeded_app):
        res = await client.get(f"/api/benchmarks/{seeded_app['bench_id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["metrics"]["success_rate"] == 0.85

    @pytest.mark.asyncio
    async def test_get_benchmark_404(self, client):
        res = await client.get("/api/benchmarks/nonexistent")
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_list_comparisons(self, client, seeded_app):
        res = await client.get("/api/benchmarks/comparisons")
        data = res.json()
        assert len(data) == 1
        assert data[0]["id"] == "cmp_test"


# ═══════════════════════════════════════════════════════════════════
# Attacks API
# ═══════════════════════════════════════════════════════════════════

class TestAttacksAPI:

    @pytest.mark.asyncio
    async def test_list_scans_empty(self, client):
        res = await client.get("/api/attacks/scans")
        assert res.status_code == 200
        assert res.json() == []

    @pytest.mark.asyncio
    async def test_list_scans(self, client, seeded_app):
        res = await client.get("/api/attacks/scans")
        data = res.json()
        assert len(data) == 1
        assert data[0]["total_probes"] == 20

    @pytest.mark.asyncio
    async def test_get_scan(self, client, seeded_app):
        res = await client.get(f"/api/attacks/scans/{seeded_app['scan_id']}")
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_get_scan_404(self, client):
        res = await client.get("/api/attacks/scans/nonexistent")
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_list_probes(self, client):
        res = await client.get("/api/attacks/probes")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) > 0  # probes exist from Phase 10


# ═══════════════════════════════════════════════════════════════════
# WebSocket
# ═══════════════════════════════════════════════════════════════════

class TestWebSocket:

    @pytest.mark.asyncio
    async def test_publish_no_subscribers(self):
        """publish_update should not error when no subscribers."""
        from sentinel.dashboard.routes.websocket import publish_update
        await publish_update("nonexistent_cycle", {"type": "test"})
