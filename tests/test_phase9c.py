"""Phase 9C tests — HypothesisEngine, ExperimentArchitect, ExperimentExecutor.

All agents use mocked ModelClient.generate_structured() and in-memory DB.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from sentinel.agents.base import TargetResult, TargetSystem
from sentinel.agents.experiment_architect import ExperimentArchitect
from sentinel.agents.experiment_executor import ExperimentExecutor
from sentinel.agents.hypothesis_engine import HypothesisEngine
from sentinel.db.connection import get_session
from sentinel.db.models import Experiment, ExperimentRun, Hypothesis


# ── HypothesisEngine ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestHypothesisEngine:
    async def test_generate_calls_generate_structured(self, db, mock_client):
        mock_client.generate_structured.return_value = [
            {
                "id": "hyp_test1",
                "description": "Model hallucinates on long context",
                "failure_class": "REASONING",
                "expected_severity": "S2",
                "rationale": "Long inputs dilute attention",
            }
        ]
        engine = HypothesisEngine(client=mock_client)
        await engine.generate("Test LLM system")
        mock_client.generate_structured.assert_awaited_once()

    async def test_hypotheses_saved_to_db(self, db, mock_client):
        mock_client.generate_structured.return_value = [
            {
                "id": "hyp_db1",
                "description": "Fabricated citations",
                "failure_class": "REASONING",
                "expected_severity": "S3",
                "rationale": "No grounding mechanism",
            }
        ]
        engine = HypothesisEngine(client=mock_client)
        result = await engine.generate("Test system", cycle_id="cyc_001")
        assert len(result) == 1
        assert result[0].cycle_id == "cyc_001"

        async with get_session() as session:
            rows = (await session.execute(select(Hypothesis))).scalars().all()
            assert len(rows) == 1
            assert rows[0].description == "Fabricated citations"

    async def test_invalid_failure_class_normalized_to_reasoning(self, db, mock_client):
        mock_client.generate_structured.return_value = [
            {
                "id": "hyp_bad_fc",
                "description": "Some hypothesis",
                "failure_class": "INVALID_CLASS",
                "expected_severity": "S2",
                "rationale": "test",
            }
        ]
        engine = HypothesisEngine(client=mock_client)
        result = await engine.generate("Test system")
        assert result[0].failure_class == "REASONING"

    async def test_invalid_severity_normalized_to_s1(self, db, mock_client):
        mock_client.generate_structured.return_value = [
            {
                "id": "hyp_bad_sev",
                "description": "Some hypothesis",
                "failure_class": "TOOL_USE",
                "expected_severity": "INVALID",
                "rationale": "test",
            }
        ]
        engine = HypothesisEngine(client=mock_client)
        result = await engine.generate("Test system")
        assert result[0].expected_severity == "S1"

    async def test_empty_description_skipped(self, db, mock_client):
        mock_client.generate_structured.return_value = [
            {
                "id": "hyp_empty",
                "description": "",
                "failure_class": "REASONING",
                "expected_severity": "S1",
                "rationale": "test",
            },
            {
                "id": "hyp_valid",
                "description": "Valid hypothesis",
                "failure_class": "REASONING",
                "expected_severity": "S2",
                "rationale": "test",
            },
        ]
        engine = HypothesisEngine(client=mock_client)
        result = await engine.generate("Test system")
        assert len(result) == 1
        assert result[0].description == "Valid hypothesis"

    async def test_format_findings_empty_list(self):
        result = HypothesisEngine._format_findings([])
        assert "first research cycle" in result


# ── ExperimentArchitect ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestExperimentArchitect:
    async def _make_hypothesis(self, cycle_id: str | None = None) -> Hypothesis:
        """Create and save a Hypothesis for testing."""
        async with get_session() as session:
            hyp = Hypothesis(
                id="hyp_arch_test",
                cycle_id=cycle_id,
                description="Model fails on long docs",
                failure_class="LONG_CONTEXT",
                expected_severity="S2",
                rationale="Attention dilution",
                status="untested",
            )
            session.add(hyp)
        return hyp

    async def test_design_calls_generate_structured_and_saves(self, db, mock_client):
        hyp = await self._make_hypothesis()
        mock_client.generate_structured.return_value = [
            {
                "id": "exp_test1",
                "hypothesis_id": hyp.id,
                "input": "Summarise this 10-page doc",
                "context_setup": "",
                "expected_correct_behavior": "Accurate summary",
                "expected_failure_behavior": "Hallucinated facts",
                "num_runs": 5,
            }
        ]
        architect = ExperimentArchitect(client=mock_client)
        result = await architect.design(hyp, "Test LLM pipeline")
        mock_client.generate_structured.assert_awaited_once()
        assert len(result) == 1

        async with get_session() as session:
            rows = (await session.execute(select(Experiment))).scalars().all()
            assert len(rows) == 1

    async def test_num_runs_clamped_to_range(self, db, mock_client):
        hyp = await self._make_hypothesis()
        mock_client.generate_structured.return_value = [
            {
                "id": "exp_clamp",
                "input": "Test query",
                "num_runs": 99,
            }
        ]
        architect = ExperimentArchitect(client=mock_client)
        result = await architect.design(hyp, "Test system")
        assert result[0].num_runs == 10  # clamped to max 10

    async def test_empty_input_skipped(self, db, mock_client):
        hyp = await self._make_hypothesis()
        mock_client.generate_structured.return_value = [
            {"id": "exp_empty", "input": "", "num_runs": 5},
            {"id": "exp_valid", "input": "Valid query", "num_runs": 3},
        ]
        architect = ExperimentArchitect(client=mock_client)
        result = await architect.design(hyp, "Test system")
        assert len(result) == 1

    async def test_duplicate_ids_get_new_uuids(self, db, mock_client):
        hyp = await self._make_hypothesis()
        mock_client.generate_structured.return_value = [
            {"id": "exp_dup", "input": "Query A", "num_runs": 3},
            {"id": "exp_dup", "input": "Query B", "num_runs": 3},
        ]
        architect = ExperimentArchitect(client=mock_client)
        result = await architect.design(hyp, "Test system")
        assert len(result) == 2
        assert result[0].id != result[1].id

    async def test_design_batch_processes_multiple(self, db, mock_client):
        hyp = await self._make_hypothesis()
        mock_client.generate_structured.return_value = [
            {"id": "exp_batch", "input": "Test query", "num_runs": 3}
        ]
        architect = ExperimentArchitect(client=mock_client)
        result = await architect.design_batch([hyp], "Test system")
        assert hyp.id in result
        assert len(result[hyp.id]) == 1

    async def test_experiments_linked_to_hypothesis(self, db, mock_client):
        hyp = await self._make_hypothesis()
        mock_client.generate_structured.return_value = [
            {"id": "exp_link", "input": "Query", "num_runs": 2}
        ]
        architect = ExperimentArchitect(client=mock_client)
        result = await architect.design(hyp, "Test system")
        assert result[0].hypothesis_id == hyp.id


# ── ExperimentExecutor ────────────────────────────────────────────────


def _make_mock_target(output: str = "Model response", error: str | None = None) -> AsyncMock:
    """Create an AsyncMock TargetSystem."""
    target = AsyncMock(spec=TargetSystem)
    target.run.return_value = TargetResult(
        output=output,
        retrieved_chunks=[],
        tool_calls=[],
        error=error,
    )
    return target


def _make_experiment(hyp_id: str = "hyp_exec", num_runs: int = 3) -> Experiment:
    """Create an Experiment ORM object (not saved to DB)."""
    return Experiment(
        id="exp_exec_test",
        hypothesis_id=hyp_id,
        input="What is 2+2?",
        expected_correct_behavior="4",
        expected_failure_behavior="Wrong answer",
        num_runs=num_runs,
        approval_status="approved",
    )


@pytest.mark.asyncio
class TestExperimentExecutor:
    async def _seed_hypothesis(self):
        async with get_session() as session:
            hyp = Hypothesis(
                id="hyp_exec",
                description="Test",
                failure_class="REASONING",
                expected_severity="S1",
            )
            session.add(hyp)

    async def test_run_calls_target_n_times(self, db):
        await self._seed_hypothesis()
        target = _make_mock_target()
        exp = _make_experiment(num_runs=3)
        executor = ExperimentExecutor(target=target)
        runs = await executor.run(exp)
        assert len(runs) == 3
        assert target.run.await_count == 3

    async def test_timeout_captured_in_error(self, db):
        await self._seed_hypothesis()
        target = AsyncMock(spec=TargetSystem)
        target.run.side_effect = asyncio.TimeoutError()
        exp = _make_experiment(num_runs=1)
        executor = ExperimentExecutor(target=target, timeout_seconds=1.0)
        runs = await executor.run(exp)
        assert len(runs) == 1
        assert runs[0].error is not None
        assert "Timeout" in runs[0].error or "TimeoutError" in runs[0].error

    async def test_target_exception_captured(self, db):
        await self._seed_hypothesis()
        target = AsyncMock(spec=TargetSystem)
        target.run.side_effect = RuntimeError("Connection refused")
        exp = _make_experiment(num_runs=1)
        executor = ExperimentExecutor(target=target)
        runs = await executor.run(exp)
        assert runs[0].error is not None
        assert "Connection refused" in runs[0].error

    async def test_budget_check_called(self, db):
        await self._seed_hypothesis()
        target = _make_mock_target()
        tracker = MagicMock()
        tracker.check_budget = MagicMock()
        exp = _make_experiment(num_runs=1)
        executor = ExperimentExecutor(target=target, cost_tracker=tracker)
        await executor.run(exp)
        tracker.check_budget.assert_called_once()

    async def test_run_batch_processes_multiple(self, db):
        await self._seed_hypothesis()
        target = _make_mock_target()
        exp1 = Experiment(
            id="exp_batch_1", hypothesis_id="hyp_exec",
            input="Q1", num_runs=1, approval_status="approved",
        )
        exp2 = Experiment(
            id="exp_batch_2", hypothesis_id="hyp_exec",
            input="Q2", num_runs=1, approval_status="approved",
        )
        executor = ExperimentExecutor(target=target)
        results = await executor.run_batch([exp1, exp2])
        assert "exp_batch_1" in results
        assert "exp_batch_2" in results

    async def test_latency_recorded(self, db):
        await self._seed_hypothesis()
        target = _make_mock_target()
        exp = _make_experiment(num_runs=1)
        executor = ExperimentExecutor(target=target)
        runs = await executor.run(exp)
        assert runs[0].latency_ms >= 0
