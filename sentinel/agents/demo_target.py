"""Demo target system for LAB mode testing.

A simple LLM-backed target that implements the TargetSystem protocol,
so ``sentinel research`` works immediately after ``sentinel init`` without
users writing their own adapter.
"""

from __future__ import annotations

from typing import Any, Optional

from sentinel.agents.base import TargetResult


class DemoTarget:
    """A configurable demo target that delegates to the default ModelClient.

    Parameters
    ----------
    description:
        Prose description of the simulated system (used by hypothesis engine).
    system_prompt:
        System prompt for the underlying LLM. Defaults to a generic assistant.
    client:
        An async ModelClient instance. If not provided, one is built from settings
        at first ``run()`` call.
    """

    def __init__(
        self,
        description: str = "A general-purpose LLM assistant",
        system_prompt: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        self._description = description
        self._system_prompt = system_prompt or (
            "You are a helpful AI assistant. Answer the user's question."
        )
        self._base_system_prompt = self._system_prompt
        self._client = client
        self._interventions: list[dict[str, Any]] = []

    def describe(self) -> str:
        """Return a prose description of the system."""
        return self._description

    async def run(self, query: str, context_setup: str = "") -> TargetResult:
        """Execute the demo target with the given query."""
        from sentinel.integrations.model_client import Message

        if self._client is None:
            raise RuntimeError(
                "DemoTarget requires a ModelClient. Pass one via the constructor."
            )

        system = self._system_prompt
        if context_setup:
            system = f"{system}\n\n{context_setup}"

        try:
            response = await self._client.generate(
                messages=[Message(role="user", content=query)],
                system=system,
            )
            return TargetResult(
                output=response.text,
                metadata={"model": response.model, "latency_ms": response.latency_ms},
            )
        except Exception as exc:
            return TargetResult(output="", error=str(exc))

    async def apply_intervention(
        self, intervention_type: str, params: dict[str, Any]
    ) -> None:
        """Apply an intervention by modifying the system prompt or recording it."""
        self._interventions.append({"type": intervention_type, "params": params})

        if intervention_type == "prompt_mutation":
            mutation = params.get("mutation", "")
            if mutation:
                self._system_prompt = f"{self._system_prompt}\n\n{mutation}"
        elif intervention_type == "guardrail":
            guardrail_text = params.get("instruction", "")
            if guardrail_text:
                self._system_prompt = (
                    f"{self._system_prompt}\n\nGUARDRAIL: {guardrail_text}"
                )
        # config_change, tool_policy_change, architectural_recommendation
        # are recorded but have no runtime effect on a simple LLM target.

    async def reset_interventions(self) -> None:
        """Restore the target to its default configuration."""
        self._system_prompt = self._base_system_prompt
        self._interventions.clear()
