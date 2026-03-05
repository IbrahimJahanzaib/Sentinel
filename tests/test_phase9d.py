"""Phase 9D tests — FailureDiscovery, InterventionEngine, SimulationEngine.

All agents use mocked ModelClient.generate_structured() and in-memory DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from sentinel.agents.base import TargetResult, TargetSystem
from sentinel.agents.failure_discovery import FailureDiscovery
from sentinel.agents.intervention_engine import InterventionEngine
from sentinel.agents.simulation_engine import (
    SimulationEngine,
    ValidationResult,
    _classify_outcome,
)
from sentinel.db.connection import get_session
from sentinel.db.models import (
    Experiment,
    ExperimentRun,
    Failure,
    Hypothesis,
    Intervention,
)


# ── Helpers ───────────────────────────────────────────────────────────


async def _seed_experiment_data(db):
    """Create a hypothesis + experiment + runs for testing."""
    async with get_session() as session:
        hyp = Hypothesis(
            id="hyp_fd",
            description="Model hallucinates stats",
            failure_class="REASONING",
            expected_severity="S2",
            status="untested",
        )
        session.add(hyp)

    async with get_session() as session:
        exp = Experiment(
            id="exp_fd",
            hypothesis_id="hyp_fd",
            input="Summarise the revenue data",
            expected_correct_behavior="Accurate numbers",
            expected_failure_behavior="Fabricated numbers",
            num_runs=3,
            approval_status="approved",
        )
        session.add(exp)

    runs = []
    for i in range(1, 4):
        async with get_session() as session:
            run = ExperimentRun(
                experiment_id="exp_fd",
                run_number=i,
                input="Summarise the revenue data",
                output=f"Output {i}",
                latency_ms=100,
            )
            session.add(run)
        runs.append(run)

    return runs


# ── FailureDiscovery ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestFailureDiscovery:
    async def test_classify_calls_generate_structured(self, db, mock_client):
        runs = await _seed_experiment_data(db)
        # Per-run eval returns
        mock_client.generate_structured.side_effect = [
            {"failed": True, "failure_class": "REASONING", "severity": "S2", "reasoning": "bad"},
            {"failed": False, "failure_class": None, "severity": None, "reasoning": "ok"},
            {"failed": True, "failure_class": "REASONING", "severity": "S2", "reasoning": "bad"},
            # Summary call
            {
                "hypothesis_confirmed": True,
                "failure_class": "REASONING",
                "failure_subtype": "hallucination",
                "severity": "S2",
                "evidence": "Model fabricated stats in 2/3 runs",
                "sample_failure_output": "Revenue was $5M",
                "sample_correct_output": "Accurate summary",
            },
        ]
        async with get_session() as session:
            hyp = (await session.execute(select(Hypothesis).where(Hypothesis.id == "hyp_fd"))).scalar_one()
            exp = (await session.execute(select(Experiment).where(Experiment.id == "exp_fd"))).scalar_one()

        fd = FailureDiscovery(client=mock_client)
        failure = await fd.classify(exp, runs, hyp, cycle_id="cyc_1")
        # 3 run evals + 1 summary = 4 calls
        assert mock_client.generate_structured.await_count == 4

    async def test_failure_saved_to_db(self, db, mock_client):
        runs = await _seed_experiment_data(db)
        mock_client.generate_structured.side_effect = [
            {"failed": True, "failure_class": "REASONING", "severity": "S2", "reasoning": "bad"},
            {"failed": False, "failure_class": None, "severity": None, "reasoning": "ok"},
            {"failed": False, "failure_class": None, "severity": None, "reasoning": "ok"},
            {
                "hypothesis_confirmed": True,
                "failure_class": "REASONING",
                "severity": "S2",
                "evidence": "Fabrication detected",
            },
        ]
        async with get_session() as session:
            hyp = (await session.execute(select(Hypothesis).where(Hypothesis.id == "hyp_fd"))).scalar_one()
            exp = (await session.execute(select(Experiment).where(Experiment.id == "exp_fd"))).scalar_one()

        fd = FailureDiscovery(client=mock_client)
        failure = await fd.classify(exp, runs, hyp, cycle_id="cyc_1")
        assert failure.cycle_id == "cyc_1"
        assert failure.hypothesis_id == "hyp_fd"

        async with get_session() as session:
            rows = (await session.execute(select(Failure))).scalars().all()
            assert len(rows) == 1

    async def test_hypothesis_status_updated(self, db, mock_client):
        runs = await _seed_experiment_data(db)
        mock_client.generate_structured.side_effect = [
            {"failed": True, "failure_class": "REASONING", "severity": "S2", "reasoning": "x"},
            {"failed": True, "failure_class": "REASONING", "severity": "S2", "reasoning": "x"},
            {"failed": True, "failure_class": "REASONING", "severity": "S2", "reasoning": "x"},
            {"hypothesis_confirmed": True, "failure_class": "REASONING", "severity": "S2", "evidence": "all failed"},
        ]
        async with get_session() as session:
            hyp = (await session.execute(select(Hypothesis).where(Hypothesis.id == "hyp_fd"))).scalar_one()
            exp = (await session.execute(select(Experiment).where(Experiment.id == "exp_fd"))).scalar_one()

        fd = FailureDiscovery(client=mock_client)
        await fd.classify(exp, runs, hyp)

        async with get_session() as session:
            updated = (await session.execute(select(Hypothesis).where(Hypothesis.id == "hyp_fd"))).scalar_one()
            assert updated.status == "confirmed"

    async def test_invalid_failure_class_falls_back(self, db, mock_client):
        runs = await _seed_experiment_data(db)
        mock_client.generate_structured.side_effect = [
            {"failed": True, "failure_class": "BOGUS", "severity": "S2", "reasoning": "x"},
            {"failed": False, "reasoning": "ok"},
            {"failed": False, "reasoning": "ok"},
            {"hypothesis_confirmed": False, "failure_class": "BOGUS_CLASS", "severity": "S1", "evidence": "nope"},
        ]
        async with get_session() as session:
            hyp = (await session.execute(select(Hypothesis).where(Hypothesis.id == "hyp_fd"))).scalar_one()
            exp = (await session.execute(select(Experiment).where(Hypothesis.id == "hyp_fd"))).scalar_one()

        fd = FailureDiscovery(client=mock_client)
        failure = await fd.classify(exp, runs, hyp)
        # Falls back to hypothesis's failure_class
        assert failure.failure_class == "REASONING"

    async def test_invalid_severity_falls_back_to_s1(self, db, mock_client):
        runs = await _seed_experiment_data(db)
        mock_client.generate_structured.side_effect = [
            {"failed": False, "reasoning": "ok"},
            {"failed": False, "reasoning": "ok"},
            {"failed": False, "reasoning": "ok"},
            {"hypothesis_confirmed": False, "failure_class": "REASONING", "severity": "INVALID", "evidence": "nope"},
        ]
        async with get_session() as session:
            hyp = (await session.execute(select(Hypothesis).where(Hypothesis.id == "hyp_fd"))).scalar_one()
            exp = (await session.execute(select(Experiment).where(Experiment.id == "exp_fd"))).scalar_one()

        fd = FailureDiscovery(client=mock_client)
        failure = await fd.classify(exp, runs, hyp)
        assert failure.severity == "S1"

    async def test_failure_rate_calculated(self, db, mock_client):
        runs = await _seed_experiment_data(db)
        mock_client.generate_structured.side_effect = [
            {"failed": True, "failure_class": "REASONING", "severity": "S2", "reasoning": "x"},
            {"failed": False, "reasoning": "ok"},
            {"failed": True, "failure_class": "REASONING", "severity": "S2", "reasoning": "x"},
            {"hypothesis_confirmed": True, "failure_class": "REASONING", "severity": "S2", "evidence": "2/3 failed"},
        ]
        async with get_session() as session:
            hyp = (await session.execute(select(Hypothesis).where(Hypothesis.id == "hyp_fd"))).scalar_one()
            exp = (await session.execute(select(Experiment).where(Experiment.id == "exp_fd"))).scalar_one()

        fd = FailureDiscovery(client=mock_client)
        failure = await fd.classify(exp, runs, hyp)
        assert abs(failure.failure_rate - 2 / 3) < 0.01


# ── InterventionEngine ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestInterventionEngine:
    async def _seed_failure(self):
        async with get_session() as session:
            hyp = Hypothesis(
                id="hyp_ie", description="Test hyp",
                failure_class="REASONING", expected_severity="S2",
            )
            session.add(hyp)
        async with get_session() as session:
            exp = Experiment(
                id="exp_ie", hypothesis_id="hyp_ie",
                input="Test query", num_runs=3,
            )
            session.add(exp)
        async with get_session() as session:
            fail = Failure(
                id="fail_ie", experiment_id="exp_ie",
                hypothesis_id="hyp_ie", hypothesis_confirmed=True,
                failure_class="REASONING", severity="S2",
                failure_rate=0.6, evidence="Model hallucinated",
            )
            session.add(fail)
        return fail

    async def test_propose_calls_generate_structured_and_saves(self, db, mock_client):
        fail = await self._seed_failure()
        mock_client.generate_structured.return_value = [
            {
                "type": "prompt_mutation",
                "description": "Add instruction to cite sources",
                "estimated_effectiveness": "high",
                "implementation_effort": "low",
            }
        ]
        engine = InterventionEngine(client=mock_client)
        result = await engine.propose(fail)
        mock_client.generate_structured.assert_awaited_once()
        assert len(result) == 1

        async with get_session() as session:
            rows = (await session.execute(select(Intervention))).scalars().all()
            assert len(rows) == 1

    async def test_invalid_type_normalized_to_prompt_mutation(self, db, mock_client):
        fail = await self._seed_failure()
        mock_client.generate_structured.return_value = [
            {"type": "INVALID_TYPE", "description": "Some fix", "estimated_effectiveness": "high", "implementation_effort": "low"}
        ]
        engine = InterventionEngine(client=mock_client)
        result = await engine.propose(fail)
        assert result[0].type == "prompt_mutation"

    async def test_invalid_effectiveness_normalized_to_medium(self, db, mock_client):
        fail = await self._seed_failure()
        mock_client.generate_structured.return_value = [
            {"type": "guardrail", "description": "Add validator", "estimated_effectiveness": "ULTRA", "implementation_effort": "low"}
        ]
        engine = InterventionEngine(client=mock_client)
        result = await engine.propose(fail)
        assert result[0].estimated_effectiveness == "medium"

    async def test_invalid_effort_normalized_to_medium(self, db, mock_client):
        fail = await self._seed_failure()
        mock_client.generate_structured.return_value = [
            {"type": "guardrail", "description": "Add validator", "estimated_effectiveness": "high", "implementation_effort": "HUGE"}
        ]
        engine = InterventionEngine(client=mock_client)
        result = await engine.propose(fail)
        assert result[0].implementation_effort == "medium"

    async def test_empty_description_skipped(self, db, mock_client):
        fail = await self._seed_failure()
        mock_client.generate_structured.return_value = [
            {"type": "guardrail", "description": "", "estimated_effectiveness": "high", "implementation_effort": "low"},
            {"type": "config_change", "description": "Reduce temperature", "estimated_effectiveness": "medium", "implementation_effort": "low"},
        ]
        engine = InterventionEngine(client=mock_client)
        result = await engine.propose(fail)
        assert len(result) == 1
        assert result[0].description == "Reduce temperature"

    async def test_propose_batch_skips_unconfirmed(self, db, mock_client):
        await self._seed_failure()
        # Create an unconfirmed failure
        async with get_session() as session:
            unconfirmed = Failure(
                id="fail_unc", experiment_id="exp_ie",
                hypothesis_id="hyp_ie", hypothesis_confirmed=False,
                failure_class="REASONING", severity="S1",
                failure_rate=0.1,
            )
            session.add(unconfirmed)

        async with get_session() as session:
            confirmed = (await session.execute(select(Failure).where(Failure.id == "fail_ie"))).scalar_one()
            unconf = (await session.execute(select(Failure).where(Failure.id == "fail_unc"))).scalar_one()

        mock_client.generate_structured.return_value = [
            {"type": "prompt_mutation", "description": "Fix it", "estimated_effectiveness": "high", "implementation_effort": "low"}
        ]
        engine = InterventionEngine(client=mock_client)
        result = await engine.propose_batch([confirmed, unconf])
        assert confirmed.id in result
        assert unconf.id not in result

    async def test_interventions_linked_to_failure(self, db, mock_client):
        fail = await self._seed_failure()
        mock_client.generate_structured.return_value = [
            {"type": "guardrail", "description": "Add output filter", "estimated_effectiveness": "medium", "implementation_effort": "medium"}
        ]
        engine = InterventionEngine(client=mock_client)
        result = await engine.propose(fail)
        assert result[0].failure_id == fail.id


# ── SimulationEngine ──────────────────────────────────────────────────


class TestClassifyOutcome:
    def test_fixed(self):
        assert _classify_outcome(0.6, 0.1) == "fixed"

    def test_partially_fixed(self):
        assert _classify_outcome(0.6, 0.4) == "partially_fixed"

    def test_regression(self):
        assert _classify_outcome(0.3, 0.5) == "regression"

    def test_no_effect(self):
        assert _classify_outcome(0.5, 0.45) == "no_effect"


@pytest.mark.asyncio
class TestSimulationEngine:
    async def _seed_data_for_validation(self):
        """Seed a hypothesis, experiment, failure, and intervention."""
        async with get_session() as session:
            hyp = Hypothesis(
                id="hyp_sim", description="Test", failure_class="REASONING",
                expected_severity="S2",
            )
            session.add(hyp)
        async with get_session() as session:
            exp = Experiment(
                id="exp_sim", hypothesis_id="hyp_sim",
                input="Test query", num_runs=2, approval_status="approved",
            )
            session.add(exp)
        async with get_session() as session:
            fail = Failure(
                id="fail_sim", experiment_id="exp_sim",
                hypothesis_id="hyp_sim", hypothesis_confirmed=True,
                failure_class="REASONING", severity="S2",
                failure_rate=0.6,
            )
            session.add(fail)
        async with get_session() as session:
            intervention = Intervention(
                id="int_sim", failure_id="fail_sim",
                type="prompt_mutation", description="Add grounding instruction",
                estimated_effectiveness="high", implementation_effort="low",
            )
            session.add(intervention)
        return exp, fail, intervention

    async def test_validate_applies_and_measures(self, db):
        exp, fail, intervention = await self._seed_data_for_validation()
        target = AsyncMock(spec=TargetSystem)
        target.run.return_value = TargetResult(output="Good output")
        target.apply_intervention = AsyncMock()
        target.reset_interventions = AsyncMock()

        engine = SimulationEngine(target=target)
        result = await engine.validate(intervention, [exp], fail)

        target.apply_intervention.assert_awaited_once()
        assert isinstance(result, ValidationResult)
        assert result.failure_rate_before == 0.6

    async def test_improved_property(self, db):
        exp, fail, intervention = await self._seed_data_for_validation()
        target = AsyncMock(spec=TargetSystem)
        target.run.return_value = TargetResult(output="Good output")
        target.apply_intervention = AsyncMock()
        target.reset_interventions = AsyncMock()

        engine = SimulationEngine(target=target)
        result = await engine.validate(intervention, [exp], fail)
        # All runs succeed (no error, output present) → rate_after = 0
        # delta = 0 - 0.6 = -0.6 → improved
        assert result.improved is True
        assert result.regressed is False

    async def test_regressed_property(self, db):
        result = ValidationResult(
            intervention_id="int_x", status="regression",
            failure_rate_before=0.3, failure_rate_after=0.5,
            delta=0.2, notes="Worsened",
        )
        assert result.regressed is True
        assert result.improved is False

    async def test_reset_called_after_validation(self, db):
        exp, fail, intervention = await self._seed_data_for_validation()
        target = AsyncMock(spec=TargetSystem)
        target.run.return_value = TargetResult(output="Output")
        target.apply_intervention = AsyncMock()
        target.reset_interventions = AsyncMock()

        engine = SimulationEngine(target=target)
        await engine.validate(intervention, [exp], fail)
        target.reset_interventions.assert_awaited_once()

    async def test_not_implemented_gives_no_effect(self, db):
        exp, fail, intervention = await self._seed_data_for_validation()
        target = AsyncMock(spec=TargetSystem)
        target.apply_intervention = AsyncMock(side_effect=NotImplementedError)
        target.reset_interventions = AsyncMock()

        engine = SimulationEngine(target=target)
        result = await engine.validate(intervention, [exp], fail)
        assert result.status == "no_effect"
        assert result.delta == 0.0

    async def test_build_notes_generates_strings(self, db):
        exp, fail, intervention = await self._seed_data_for_validation()
        notes = SimulationEngine._build_notes("fixed", 0.6, 0.1, intervention)
        assert "fixed" in notes.lower()
        assert "60%" in notes
        assert "10%" in notes
