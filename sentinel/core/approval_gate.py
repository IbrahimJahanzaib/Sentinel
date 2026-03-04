"""Approval gate — resolves risk evaluations into approve/reject decisions.

Supports multiple approval modes:
  - interactive   : prompt user on stdin
  - auto_approve  : approve everything (useful for automated testing)
  - auto_reject   : reject everything (dry-run mode)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sentinel.core.risk_policy import RiskEvaluation, RiskLevel
from sentinel.db.audit import log_event


@dataclass
class ApprovalDecision:
    """The final outcome of passing an action through the approval gate."""
    approved: bool
    risk_level: RiskLevel
    actor: str             # "auto" | "human" | "policy"
    reason: str
    timestamp: datetime

    @property
    def rejected(self) -> bool:
        return not self.approved


class ApprovalGate:
    """Resolves risk evaluations into concrete approve/reject decisions.

    Parameters
    ----------
    mode:
        Approval mode — ``interactive``, ``auto_approve``, or ``auto_reject``.
    timeout_seconds:
        Timeout for interactive approval prompts.
    audit_mode:
        Operating mode string written to audit log entries.
    """

    def __init__(
        self,
        mode: str = "interactive",
        timeout_seconds: int = 300,
        audit_mode: str = "lab",
    ) -> None:
        self._mode = mode
        self._timeout = timeout_seconds
        self._audit_mode = audit_mode

    async def check(
        self,
        evaluation: RiskEvaluation,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> ApprovalDecision:
        """Resolve a risk evaluation into an approval decision.

        Parameters
        ----------
        evaluation:
            The risk evaluation from RiskPolicy.
        entity_type:
            What entity is being acted on (e.g. "experiment", "intervention").
        entity_id:
            The ID of that entity.

        Returns
        -------
        ApprovalDecision
        """
        now = datetime.now(timezone.utc)

        # BLOCK → always reject
        if evaluation.level == RiskLevel.BLOCK:
            decision = ApprovalDecision(
                approved=False,
                risk_level=RiskLevel.BLOCK,
                actor="policy",
                reason=f"Blocked by policy: {evaluation.reason}",
                timestamp=now,
            )
            await self._audit(decision, evaluation, entity_type, entity_id)
            return decision

        # SAFE → auto-approve
        if evaluation.level == RiskLevel.SAFE:
            decision = ApprovalDecision(
                approved=True,
                risk_level=RiskLevel.SAFE,
                actor="auto",
                reason=evaluation.reason,
                timestamp=now,
            )
            await self._audit(decision, evaluation, entity_type, entity_id)
            return decision

        # REVIEW → depends on approval mode
        decision = await self._resolve_review(evaluation, now)
        await self._audit(decision, evaluation, entity_type, entity_id)
        return decision

    # ------------------------------------------------------------------
    # Review resolution per approval mode
    # ------------------------------------------------------------------

    async def _resolve_review(
        self,
        evaluation: RiskEvaluation,
        now: datetime,
    ) -> ApprovalDecision:
        if self._mode == "auto_approve":
            return ApprovalDecision(
                approved=True,
                risk_level=RiskLevel.REVIEW,
                actor="auto",
                reason=f"Auto-approved (auto_approve mode): {evaluation.reason}",
                timestamp=now,
            )

        if self._mode == "auto_reject":
            return ApprovalDecision(
                approved=False,
                risk_level=RiskLevel.REVIEW,
                actor="auto",
                reason=f"Auto-rejected (auto_reject mode): {evaluation.reason}",
                timestamp=now,
            )

        # Interactive mode — prompt on stdin
        return await self._interactive_prompt(evaluation, now)

    async def _interactive_prompt(
        self,
        evaluation: RiskEvaluation,
        now: datetime,
    ) -> ApprovalDecision:
        """Prompt the user on stdin for an approval decision."""
        print()
        print("=" * 60)
        print("  APPROVAL REQUIRED")
        print("=" * 60)
        print(f"  Action   : {evaluation.action.value}")
        print(f"  Mode     : {evaluation.mode.value.upper()}")
        print(f"  Risk     : {evaluation.level.value.upper()}")
        if evaluation.severity:
            print(f"  Severity : {evaluation.severity.value}")
        print(f"  Reason   : {evaluation.reason}")
        print("=" * 60)

        try:
            answer = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: input("  Approve? [y/N] ").strip().lower(),
                ),
                timeout=self._timeout,
            )
        except (asyncio.TimeoutError, EOFError):
            return ApprovalDecision(
                approved=False,
                risk_level=RiskLevel.REVIEW,
                actor="human",
                reason=f"Timed out or no input after {self._timeout}s.",
                timestamp=now,
            )

        approved = answer in ("y", "yes")
        return ApprovalDecision(
            approved=approved,
            risk_level=RiskLevel.REVIEW,
            actor="human",
            reason="Approved by human." if approved else "Rejected by human.",
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    async def _audit(
        self,
        decision: ApprovalDecision,
        evaluation: RiskEvaluation,
        entity_type: Optional[str],
        entity_id: Optional[str],
    ) -> None:
        """Log the approval decision to the audit trail."""
        try:
            event = "approval.approved" if decision.approved else "approval.rejected"
            await log_event(
                event_type=event,
                actor=decision.actor,
                entity_type=entity_type,
                entity_id=entity_id,
                details={
                    "action": evaluation.action.value,
                    "risk_level": evaluation.level.value,
                    "mode": evaluation.mode.value,
                    "severity": evaluation.severity.value if evaluation.severity else None,
                    "reason": decision.reason,
                },
                mode=self._audit_mode,
            )
        except Exception:
            pass  # audit failures must not break the pipeline
