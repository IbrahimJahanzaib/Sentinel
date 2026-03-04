"""Risk policy — evaluates actions and returns a risk tier (SAFE / REVIEW / BLOCK).

The risk level depends on:
  - The current operating mode (LAB / SHADOW / PRODUCTION)
  - The action being performed
  - The severity of any associated findings
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sentinel.config.modes import Mode
from sentinel.taxonomy.failure_types import Severity


class RiskLevel(str, Enum):
    """Outcome of a risk evaluation."""
    SAFE = "safe"        # Auto-approved
    REVIEW = "review"    # Requires human decision
    BLOCK = "block"      # Always rejected


class ActionType(str, Enum):
    """Categories of actions the system can take."""
    GENERATE_HYPOTHESES = "generate_hypotheses"
    DESIGN_EXPERIMENTS = "design_experiments"
    EXECUTE_EXPERIMENT = "execute_experiment"
    CLASSIFY_FAILURE = "classify_failure"
    PROPOSE_INTERVENTION = "propose_intervention"
    VALIDATE_INTERVENTION = "validate_intervention"
    DESTRUCTIVE_TEST = "destructive_test"


@dataclass
class RiskEvaluation:
    """Result of evaluating an action's risk."""
    level: RiskLevel
    action: ActionType
    mode: Mode
    reason: str
    severity: Optional[Severity] = None


class RiskPolicy:
    """Evaluates actions against the current operating mode and returns a risk tier.

    Rules
    -----
    LAB mode:
      - Almost everything is SAFE (auto-approved)
      - Destructive tests are SAFE in LAB (that's what it's for)
      - S4 findings still trigger REVIEW

    SHADOW mode:
      - Read-only analysis actions are SAFE
      - Executing experiments is REVIEW (passive observation only)
      - Destructive tests are BLOCK
      - S3+ findings trigger REVIEW

    PRODUCTION mode:
      - Everything is REVIEW (human must approve every action)
      - Destructive tests are BLOCK (always)

    Parameters
    ----------
    auto_approve_safe:
        Whether SAFE-level actions skip human approval entirely.
    block_on_destructive:
        Whether destructive tests are always blocked outside LAB mode.
    """

    def __init__(
        self,
        auto_approve_safe: bool = True,
        block_on_destructive: bool = True,
    ) -> None:
        self._auto_approve_safe = auto_approve_safe
        self._block_on_destructive = block_on_destructive

    def evaluate(
        self,
        action: ActionType,
        mode: Mode,
        severity: Optional[Severity] = None,
    ) -> RiskEvaluation:
        """Evaluate the risk of performing an action in the given mode.

        Parameters
        ----------
        action:
            What the system wants to do.
        mode:
            Current operating mode.
        severity:
            Severity of associated finding (if applicable).

        Returns
        -------
        RiskEvaluation
            Contains the risk level (SAFE/REVIEW/BLOCK) and a human-readable reason.
        """
        # ------- Destructive tests -------
        if action == ActionType.DESTRUCTIVE_TEST:
            if mode == Mode.LAB:
                return RiskEvaluation(
                    level=RiskLevel.SAFE,
                    action=action, mode=mode, severity=severity,
                    reason="Destructive tests are permitted in LAB mode.",
                )
            if self._block_on_destructive:
                return RiskEvaluation(
                    level=RiskLevel.BLOCK,
                    action=action, mode=mode, severity=severity,
                    reason=f"Destructive tests are blocked in {mode.value.upper()} mode.",
                )
            return RiskEvaluation(
                level=RiskLevel.REVIEW,
                action=action, mode=mode, severity=severity,
                reason=f"Destructive test requires human approval in {mode.value.upper()} mode.",
            )

        # ------- PRODUCTION mode: everything needs review -------
        if mode == Mode.PRODUCTION:
            return RiskEvaluation(
                level=RiskLevel.REVIEW,
                action=action, mode=mode, severity=severity,
                reason="All actions require human approval in PRODUCTION mode.",
            )

        # ------- SHADOW mode -------
        if mode == Mode.SHADOW:
            # Analysis-only actions are safe
            if action in (
                ActionType.GENERATE_HYPOTHESES,
                ActionType.DESIGN_EXPERIMENTS,
                ActionType.CLASSIFY_FAILURE,
                ActionType.PROPOSE_INTERVENTION,
            ):
                # S3+ findings still need review even for analysis
                if severity is not None and severity >= Severity.S3:
                    return RiskEvaluation(
                        level=RiskLevel.REVIEW,
                        action=action, mode=mode, severity=severity,
                        reason=f"S3+ severity ({severity.value}) requires human review in SHADOW mode.",
                    )
                return RiskEvaluation(
                    level=RiskLevel.SAFE,
                    action=action, mode=mode, severity=severity,
                    reason="Analysis action is safe in SHADOW mode.",
                )
            # Execution / validation need review in SHADOW
            return RiskEvaluation(
                level=RiskLevel.REVIEW,
                action=action, mode=mode, severity=severity,
                reason=f"Active action '{action.value}' requires review in SHADOW mode.",
            )

        # ------- LAB mode: nearly everything is safe -------
        # S4 still gets flagged
        if severity is not None and severity >= Severity.S4:
            return RiskEvaluation(
                level=RiskLevel.REVIEW,
                action=action, mode=mode, severity=severity,
                reason="S4 (critical) finding requires human review even in LAB mode.",
            )

        return RiskEvaluation(
            level=RiskLevel.SAFE,
            action=action, mode=mode, severity=severity,
            reason="Action is safe in LAB mode.",
        )
