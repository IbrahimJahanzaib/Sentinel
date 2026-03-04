"""Agent 2 — Experiment Architect.

Turns a hypothesis into concrete, runnable test cases.
"""

from __future__ import annotations

import uuid
from typing import Optional, TYPE_CHECKING

from sentinel.db.connection import get_session
from sentinel.db.models import Experiment, Hypothesis
from sentinel.integrations.model_client import Message

if TYPE_CHECKING:
    from sentinel.integrations.model_client import ModelClient

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an expert AI systems tester. Given a hypothesis about how an LLM-based
system might fail, you design concrete, minimal test cases that will either
confirm or refute it.

A good experiment:
- Has a specific, realistic user query (not "test question 1")
- Uses the MINIMUM context needed to expose the failure
- Clearly separates correct behavior from failure behavior
- Tests ONE thing — it isolates the failure mode
- Can be run repeatedly to check consistency

Respond with a JSON array. Each element must have exactly these keys:
  id, hypothesis_id, input, context_setup, expected_correct_behavior,
  expected_failure_behavior, num_runs
"""

_USER = """\
TARGET SYSTEM
=============
{system_description}

HYPOTHESIS TO TEST
==================
ID          : {hyp_id}
Description : {hyp_description}
Failure class: {failure_class}
Severity    : {expected_severity}
Rationale   : {rationale}

Design {n} test case(s). Approach the hypothesis from slightly different angles —
vary the query phrasing, context, or edge case to maximise coverage.

Return a JSON array:
[
  {{
    "id": "exp_{short_id}",
    "hypothesis_id": "{hyp_id}",
    "input": "exact user query to send to the target system",
    "context_setup": "any setup needed before running (e.g. which documents to load, state to configure). Empty string if none.",
    "expected_correct_behavior": "what a well-behaved system response looks like",
    "expected_failure_behavior": "what the failure looks like if the hypothesis is confirmed",
    "num_runs": 5
  }},
  ...
]
"""

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ExperimentArchitect:
    """Designs experiment definitions for a given hypothesis.

    Parameters
    ----------
    client:
        Async ModelClient.
    max_experiments:
        Max experiments to generate per hypothesis.
    default_runs:
        Default ``num_runs`` per experiment (clamped to 1–10).
    """

    def __init__(
        self,
        client: "ModelClient",
        max_experiments: int = 3,
        default_runs: int = 5,
    ) -> None:
        self._client = client
        self._max = max_experiments
        self._default_runs = default_runs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def design(
        self,
        hypothesis: Hypothesis,
        system_description: str,
        n: Optional[int] = None,
    ) -> list[Experiment]:
        """Design experiments for a single hypothesis and save them to the DB.

        Parameters
        ----------
        hypothesis:
            The hypothesis ORM object to design experiments for.
        system_description:
            Prose description of the target system.
        n:
            Override max experiments for this call.

        Returns
        -------
        list[Experiment]
            Saved ORM objects.
        """
        count = n or self._max

        user_prompt = _USER.format(
            system_description=system_description.strip(),
            hyp_id=hypothesis.id,
            hyp_description=hypothesis.description,
            failure_class=hypothesis.failure_class,
            expected_severity=hypothesis.expected_severity,
            rationale=hypothesis.rationale or "—",
            n=count,
            short_id="{short_id}",
        )

        raw: list[dict] = await self._client.generate_structured(
            messages=[Message(role="user", content=user_prompt)],
            system=_SYSTEM,
            temperature=0.7,
        )

        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, dict) else []

        return await self._save(raw, hypothesis.id)

    async def design_batch(
        self,
        hypotheses: list[Hypothesis],
        system_description: str,
        n: Optional[int] = None,
    ) -> dict[str, list[Experiment]]:
        """Design experiments for multiple hypotheses.

        Returns a dict mapping hypothesis_id → list of Experiments.
        """
        result: dict[str, list[Experiment]] = {}
        for hyp in hypotheses:
            result[hyp.id] = await self.design(hyp, system_description, n)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _save(self, raw: list[dict], hypothesis_id: str) -> list[Experiment]:
        saved: list[Experiment] = []
        seen_ids: set[str] = set()

        async with get_session() as session:
            for item in raw:
                if not isinstance(item, dict):
                    continue

                exp_id = str(item.get("id", "")).strip()
                if not exp_id or "{short_id}" in exp_id or exp_id in seen_ids:
                    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
                seen_ids.add(exp_id)

                input_text = str(item.get("input", "")).strip()
                if not input_text:
                    continue

                runs = int(item.get("num_runs", self._default_runs))
                runs = max(1, min(runs, 10))

                exp = Experiment(
                    id=exp_id,
                    hypothesis_id=hypothesis_id,
                    input=input_text,
                    context_setup=str(item.get("context_setup", "")).strip(),
                    expected_correct_behavior=str(
                        item.get("expected_correct_behavior", "")
                    ).strip(),
                    expected_failure_behavior=str(
                        item.get("expected_failure_behavior", "")
                    ).strip(),
                    num_runs=runs,
                    approval_status="pending",
                )
                session.add(exp)
                saved.append(exp)

        return saved
