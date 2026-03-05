"""Phase 9B tests — Risk Policy and Approval Gate.

Tests cover:
  - RiskPolicy.evaluate() across LAB/SHADOW/PRODUCTION modes
  - Destructive test handling and block_on_destructive flag
  - Severity-triggered overrides
  - ApprovalGate.check() for BLOCK/SAFE/REVIEW evaluations
  - Auto-approve, auto-reject, and interactive timeout modes
  - ApprovalDecision.rejected property
  - Audit entries written for each decision
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from sentinel.config.modes import Mode
from sentinel.core.approval_gate import ApprovalDecision, ApprovalGate
from sentinel.core.risk_policy import (
    ActionType,
    RiskEvaluation,
    RiskLevel,
    RiskPolicy,
)
from sentinel.db.audit import get_audit_log
from sentinel.taxonomy.failure_types import Severity


# ── RiskPolicy ────────────────────────────────────────────────────────


class TestRiskPolicy:
    def setup_method(self):
        self.policy = RiskPolicy()

    def test_lab_analysis_action_safe(self):
        result = self.policy.evaluate(ActionType.GENERATE_HYPOTHESES, Mode.LAB)
        assert result.level == RiskLevel.SAFE

    def test_lab_execution_action_safe(self):
        result = self.policy.evaluate(ActionType.EXECUTE_EXPERIMENT, Mode.LAB)
        assert result.level == RiskLevel.SAFE

    def test_lab_destructive_safe(self):
        result = self.policy.evaluate(ActionType.DESTRUCTIVE_TEST, Mode.LAB)
        assert result.level == RiskLevel.SAFE

    def test_lab_s4_triggers_review(self):
        result = self.policy.evaluate(
            ActionType.GENERATE_HYPOTHESES, Mode.LAB, severity=Severity.S4
        )
        assert result.level == RiskLevel.REVIEW

    def test_shadow_analysis_safe(self):
        result = self.policy.evaluate(ActionType.CLASSIFY_FAILURE, Mode.SHADOW)
        assert result.level == RiskLevel.SAFE

    def test_shadow_execution_review(self):
        result = self.policy.evaluate(ActionType.EXECUTE_EXPERIMENT, Mode.SHADOW)
        assert result.level == RiskLevel.REVIEW

    def test_shadow_destructive_block(self):
        result = self.policy.evaluate(ActionType.DESTRUCTIVE_TEST, Mode.SHADOW)
        assert result.level == RiskLevel.BLOCK

    def test_shadow_s3_analysis_triggers_review(self):
        result = self.policy.evaluate(
            ActionType.DESIGN_EXPERIMENTS, Mode.SHADOW, severity=Severity.S3
        )
        assert result.level == RiskLevel.REVIEW

    def test_production_everything_review(self):
        result = self.policy.evaluate(ActionType.GENERATE_HYPOTHESES, Mode.PRODUCTION)
        assert result.level == RiskLevel.REVIEW

    def test_production_destructive_block(self):
        result = self.policy.evaluate(ActionType.DESTRUCTIVE_TEST, Mode.PRODUCTION)
        assert result.level == RiskLevel.BLOCK

    def test_block_on_destructive_false_lets_through_as_review(self):
        policy = RiskPolicy(block_on_destructive=False)
        result = policy.evaluate(ActionType.DESTRUCTIVE_TEST, Mode.SHADOW)
        assert result.level == RiskLevel.REVIEW


# ── ApprovalGate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestApprovalGate:
    async def test_block_always_rejected(self, db):
        gate = ApprovalGate(mode="auto_approve")
        evaluation = RiskEvaluation(
            level=RiskLevel.BLOCK,
            action=ActionType.DESTRUCTIVE_TEST,
            mode=Mode.SHADOW,
            reason="Blocked by policy",
        )
        decision = await gate.check(evaluation)
        assert decision.approved is False
        assert decision.actor == "policy"

    async def test_safe_always_approved(self, db):
        gate = ApprovalGate(mode="interactive")
        evaluation = RiskEvaluation(
            level=RiskLevel.SAFE,
            action=ActionType.GENERATE_HYPOTHESES,
            mode=Mode.LAB,
            reason="Safe in LAB",
        )
        decision = await gate.check(evaluation)
        assert decision.approved is True
        assert decision.actor == "auto"

    async def test_review_auto_approve_mode(self, db):
        gate = ApprovalGate(mode="auto_approve")
        evaluation = RiskEvaluation(
            level=RiskLevel.REVIEW,
            action=ActionType.EXECUTE_EXPERIMENT,
            mode=Mode.SHADOW,
            reason="Needs review",
        )
        decision = await gate.check(evaluation)
        assert decision.approved is True

    async def test_review_auto_reject_mode(self, db):
        gate = ApprovalGate(mode="auto_reject")
        evaluation = RiskEvaluation(
            level=RiskLevel.REVIEW,
            action=ActionType.EXECUTE_EXPERIMENT,
            mode=Mode.SHADOW,
            reason="Needs review",
        )
        decision = await gate.check(evaluation)
        assert decision.approved is False

    async def test_rejected_property(self, db):
        gate = ApprovalGate(mode="auto_reject")
        evaluation = RiskEvaluation(
            level=RiskLevel.REVIEW,
            action=ActionType.EXECUTE_EXPERIMENT,
            mode=Mode.PRODUCTION,
            reason="Needs review",
        )
        decision = await gate.check(evaluation)
        assert decision.rejected is True

    async def test_audit_entry_written_on_approval(self, db):
        gate = ApprovalGate(mode="auto_approve")
        evaluation = RiskEvaluation(
            level=RiskLevel.SAFE,
            action=ActionType.GENERATE_HYPOTHESES,
            mode=Mode.LAB,
            reason="Safe",
        )
        await gate.check(evaluation, entity_type="hypothesis", entity_id="hyp_123")
        entries = await get_audit_log(event_type="approval.approved")
        assert len(entries) == 1
        assert entries[0].entity_id == "hyp_123"

    async def test_audit_entry_written_on_rejection(self, db):
        gate = ApprovalGate(mode="auto_reject")
        evaluation = RiskEvaluation(
            level=RiskLevel.REVIEW,
            action=ActionType.EXECUTE_EXPERIMENT,
            mode=Mode.SHADOW,
            reason="Needs review",
        )
        await gate.check(evaluation, entity_type="experiment", entity_id="exp_456")
        entries = await get_audit_log(event_type="approval.rejected")
        assert len(entries) == 1
        assert entries[0].entity_id == "exp_456"

    async def test_interactive_timeout_rejected(self, db):
        gate = ApprovalGate(mode="interactive", timeout_seconds=1)
        evaluation = RiskEvaluation(
            level=RiskLevel.REVIEW,
            action=ActionType.EXECUTE_EXPERIMENT,
            mode=Mode.PRODUCTION,
            reason="Needs review",
        )
        with patch("sentinel.core.approval_gate.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            decision = await gate.check(evaluation)
        assert decision.approved is False
        assert decision.actor == "human"
