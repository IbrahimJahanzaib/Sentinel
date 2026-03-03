"""Operating modes — LAB, SHADOW, PRODUCTION — and their transition rules."""

from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    """Sentinel operating mode.

    LAB        — unrestricted research against dev/test systems
    SHADOW     — passive observation of production traffic, no interference
    PRODUCTION — active monitoring with full human approval required
    """
    LAB = "lab"
    SHADOW = "shadow"
    PRODUCTION = "production"

    def can_transition_to(self, target: "Mode") -> bool:
        """Return True if transitioning from this mode to ``target`` is allowed."""
        return target.value in _ALLOWED_TRANSITIONS.get(self.value, set())

    def transition_to(self, target: "Mode") -> "Mode":
        """Perform a mode transition, raising ``ModeTransitionError`` if invalid."""
        if not self.can_transition_to(target):
            raise ModeTransitionError(
                f"Cannot transition from {self.value.upper()} to {target.value.upper()}. "
                f"Allowed targets: {_ALLOWED_TRANSITIONS.get(self.value, set())}"
            )
        return target

    # ------------------------------------------------------------------
    # Per-mode capability flags
    # ------------------------------------------------------------------

    @property
    def allows_destructive_tests(self) -> bool:
        """Whether destructive experiments are permitted in this mode."""
        return self == Mode.LAB

    @property
    def requires_human_approval_for_all(self) -> bool:
        """Whether every action requires explicit human approval."""
        return self == Mode.PRODUCTION

    @property
    def auto_approve_safe_actions(self) -> bool:
        """Whether SAFE-rated actions are auto-approved."""
        return self in (Mode.LAB, Mode.SHADOW)

    @property
    def description(self) -> str:
        return {
            Mode.LAB: "Unrestricted research against dev/test systems. Most actions auto-approved.",
            Mode.SHADOW: "Passive observation of production traffic. No interference. S3+ requires human review.",
            Mode.PRODUCTION: "Active monitoring. Human approval required for all actions. Destructive tests blocked.",
        }[self]


# Valid transitions: from -> set of allowed target values
# Defined after the class to avoid Enum member confusion
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "lab":        {"shadow"},
    "shadow":     {"production", "lab"},   # regression fallback allowed
    "production": {"shadow"},             # can only step down to shadow
}


class ModeTransitionError(Exception):
    """Raised when an invalid mode transition is attempted."""
