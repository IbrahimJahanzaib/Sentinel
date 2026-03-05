"""Phase 9A tests — Config/Taxonomy/Audit foundation modules.

Tests cover:
  - Mode enum values, transitions, and capability flags
  - Severity ordering, labels, and properties
  - FailureClass/SecuritySubtype enum member counts and metadata
  - Audit log_event() and get_audit_log() with filters
"""

from __future__ import annotations

import pytest

from sentinel.config.modes import Mode, ModeTransitionError, _ALLOWED_TRANSITIONS
from sentinel.db.audit import log_event, get_audit_log
from sentinel.taxonomy.failure_types import (
    FAILURE_CLASS_DESCRIPTIONS,
    FailureClass,
    SecuritySubtype,
    Severity,
)


# ── Mode ──────────────────────────────────────────────────────────────


class TestMode:
    def test_enum_values(self):
        assert Mode.LAB.value == "lab"
        assert Mode.SHADOW.value == "shadow"
        assert Mode.PRODUCTION.value == "production"

    def test_can_transition_to_valid(self):
        assert Mode.LAB.can_transition_to(Mode.SHADOW) is True
        assert Mode.SHADOW.can_transition_to(Mode.PRODUCTION) is True
        assert Mode.SHADOW.can_transition_to(Mode.LAB) is True
        assert Mode.PRODUCTION.can_transition_to(Mode.SHADOW) is True

    def test_can_transition_to_invalid(self):
        assert Mode.LAB.can_transition_to(Mode.PRODUCTION) is False
        assert Mode.PRODUCTION.can_transition_to(Mode.LAB) is False
        assert Mode.LAB.can_transition_to(Mode.LAB) is False

    def test_transition_to_raises_on_invalid(self):
        with pytest.raises(ModeTransitionError):
            Mode.LAB.transition_to(Mode.PRODUCTION)

    def test_transition_to_returns_target_on_valid(self):
        result = Mode.LAB.transition_to(Mode.SHADOW)
        assert result == Mode.SHADOW

    def test_allows_destructive_tests(self):
        assert Mode.LAB.allows_destructive_tests is True
        assert Mode.SHADOW.allows_destructive_tests is False
        assert Mode.PRODUCTION.allows_destructive_tests is False

    def test_requires_human_approval_for_all(self):
        assert Mode.PRODUCTION.requires_human_approval_for_all is True
        assert Mode.LAB.requires_human_approval_for_all is False
        assert Mode.SHADOW.requires_human_approval_for_all is False


# ── Severity ──────────────────────────────────────────────────────────


class TestSeverity:
    def test_ordering_s0_lt_s4(self):
        assert Severity.S0 < Severity.S4

    def test_ordering_s3_ge_s2(self):
        assert Severity.S3 >= Severity.S2

    def test_ordering_s1_le_s2(self):
        assert Severity.S1 <= Severity.S2

    def test_label_property(self):
        assert Severity.S0.label == "Benign"
        assert Severity.S4.label == "Critical"

    def test_automated_action(self):
        assert Severity.S0.automated_action == "Monitor"
        assert Severity.S3.automated_action == "Mitigate"
        assert Severity.S4.automated_action == "Immediate action"

    def test_requires_human_review(self):
        assert Severity.S3.requires_human_review is True
        assert Severity.S4.requires_human_review is True
        assert Severity.S2.requires_human_review is False
        assert Severity.S0.requires_human_review is False


# ── FailureClass / SecuritySubtype ────────────────────────────────────


class TestFailureClassAndSecuritySubtype:
    def test_failure_class_has_6_members(self):
        assert len(FailureClass) == 6

    def test_security_subtype_has_8_members(self):
        assert len(SecuritySubtype) == 8

    def test_failure_class_descriptions_has_all_keys(self):
        for fc in FailureClass:
            assert fc in FAILURE_CLASS_DESCRIPTIONS, f"Missing description for {fc}"


# ── Audit ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAudit:
    async def test_log_event_writes_entry(self, db):
        await log_event("test.event", actor="tester", details={"key": "value"})
        entries = await get_audit_log()
        assert len(entries) == 1
        assert entries[0].event_type == "test.event"
        assert entries[0].actor == "tester"
        assert entries[0].details == {"key": "value"}

    async def test_get_audit_log_returns_entries(self, db):
        await log_event("a.first")
        await log_event("b.second")
        entries = await get_audit_log()
        assert len(entries) == 2

    async def test_filter_by_event_type(self, db):
        await log_event("cycle.started")
        await log_event("experiment.approved")
        await log_event("cycle.started")
        entries = await get_audit_log(event_type="cycle.started")
        assert len(entries) == 2
        assert all(e.event_type == "cycle.started" for e in entries)

    async def test_filter_by_entity_id(self, db):
        await log_event("failure.classified", entity_id="fail_abc")
        await log_event("failure.classified", entity_id="fail_xyz")
        await log_event("experiment.run", entity_id="fail_abc")
        entries = await get_audit_log(entity_id="fail_abc")
        assert len(entries) == 2
        assert all(e.entity_id == "fail_abc" for e in entries)
