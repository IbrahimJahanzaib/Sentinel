"""Agent 5 — Intervention Engine.

Proposes concrete fixes for classified failures and persists
Intervention records to the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sentinel.db.connection import get_session
from sentinel.db.models import Failure, Intervention
from sentinel.integrations.model_client import Message

if TYPE_CHECKING:
    from sentinel.integrations.model_client import ModelClient

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an AI systems reliability engineer. Given a classified failure in an
LLM-based system, propose concrete, actionable fixes.

Intervention types:
  prompt_mutation              — change the system prompt or user prompt template
  guardrail                    — add an input filter, output validator, or safety check
  tool_policy_change           — change which tools are available, their order, or usage rules
  config_change                — adjust retrieval parameters, model settings, thresholds
  architectural_recommendation — structural change (cannot be applied at runtime)

For each intervention, assess:
  estimated_effectiveness: high | medium | low
  implementation_effort:   high | medium | low

Prioritise interventions that are high effectiveness AND low effort.

Respond with a JSON array. Each element must have exactly these keys:
  type, description, estimated_effectiveness, implementation_effort
"""

_USER = """\
FAILURE DETAILS
===============
Failure class : {failure_class}
Subtype       : {failure_subtype}
Severity      : {severity}
Failure rate  : {failure_rate_pct}% ({failure_rate_pct}% of runs failed)
Evidence      : {evidence}

EXAMPLE FAILURE OUTPUT
======================
{sample_failure}

EXAMPLE CORRECT OUTPUT
======================
{sample_correct}

Propose {n} concrete interventions to fix this failure. Return a JSON array:
[
  {{
    "type": "prompt_mutation",
    "description": "Add the following instruction to the system prompt: ...",
    "estimated_effectiveness": "high",
    "implementation_effort": "low"
  }},
  ...
]
"""

_VALID_TYPES = {
    "prompt_mutation",
    "guardrail",
    "tool_policy_change",
    "config_change",
    "architectural_recommendation",
}
_VALID_LEVELS = {"high", "medium", "low"}

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class InterventionEngine:
    """Proposes concrete fixes for classified failures.

    Parameters
    ----------
    client:
        Async ModelClient.
    max_interventions:
        Number of interventions to propose per failure.
    """

    def __init__(
        self,
        client: "ModelClient",
        max_interventions: int = 3,
    ) -> None:
        self._client = client
        self._max = max_interventions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def propose(
        self,
        failure: Failure,
        cycle_id: Optional[str] = None,
        n: Optional[int] = None,
    ) -> list[Intervention]:
        """Propose interventions for a single failure and save them to the DB.

        Parameters
        ----------
        failure:
            The classified Failure ORM object.
        cycle_id:
            Research cycle ID for provenance.
        n:
            Override max interventions for this call.

        Returns
        -------
        list[Intervention]
            Saved ORM objects.
        """
        count = n or self._max
        failure_rate_pct = int(failure.failure_rate * 100)

        user_prompt = _USER.format(
            failure_class=failure.failure_class,
            failure_subtype=failure.failure_subtype or "—",
            severity=failure.severity,
            failure_rate_pct=failure_rate_pct,
            evidence=failure.evidence or "(no evidence recorded)",
            sample_failure=(failure.sample_failure_output or "(none)")[:400],
            sample_correct=(failure.sample_correct_output or "(none)")[:400],
            n=count,
        )

        raw: list[dict] = await self._client.generate_structured(
            messages=[Message(role="user", content=user_prompt)],
            system=_SYSTEM,
            temperature=0.7,
        )

        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, dict) else []

        return await self._save(raw, failure.id, cycle_id)

    async def propose_batch(
        self,
        failures: list[Failure],
        cycle_id: Optional[str] = None,
        n: Optional[int] = None,
    ) -> dict[str, list[Intervention]]:
        """Propose interventions for a list of failures.

        Returns a dict mapping failure_id → list of Interventions.
        """
        result: dict[str, list[Intervention]] = {}
        for failure in failures:
            if not failure.hypothesis_confirmed:
                continue  # only propose fixes for confirmed failures
            result[failure.id] = await self.propose(failure, cycle_id, n)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _save(
        self,
        raw: list[dict],
        failure_id: str,
        cycle_id: Optional[str],
    ) -> list[Intervention]:
        saved: list[Intervention] = []

        async with get_session() as session:
            for item in raw:
                if not isinstance(item, dict):
                    continue

                int_type = str(item.get("type", "prompt_mutation")).strip().lower()
                if int_type not in _VALID_TYPES:
                    int_type = "prompt_mutation"

                description = str(item.get("description", "")).strip()
                if not description:
                    continue

                effectiveness = str(
                    item.get("estimated_effectiveness", "medium")
                ).strip().lower()
                effort = str(
                    item.get("implementation_effort", "medium")
                ).strip().lower()

                if effectiveness not in _VALID_LEVELS:
                    effectiveness = "medium"
                if effort not in _VALID_LEVELS:
                    effort = "medium"

                intervention = Intervention(
                    id=f"int_{uuid.uuid4().hex[:8]}",
                    failure_id=failure_id,
                    cycle_id=cycle_id,
                    type=int_type,
                    description=description,
                    estimated_effectiveness=effectiveness,
                    implementation_effort=effort,
                    validation_status="pending",
                    created_at=datetime.now(timezone.utc),
                )
                session.add(intervention)
                saved.append(intervention)

        return saved
