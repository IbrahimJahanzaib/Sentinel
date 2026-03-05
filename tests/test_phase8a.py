"""Phase 8A tests — DemoTarget and CLI research command.

Tests cover:
  - DemoTarget satisfies TargetSystem protocol
  - DemoTarget.describe() returns description
  - DemoTarget.run() delegates to client
  - DemoTarget intervention apply/reset
  - CLI research --help shows options
  - Mock-based test that research command wires up correctly
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from sentinel.agents.base import TargetSystem, TargetResult
from sentinel.agents.demo_target import DemoTarget
from sentinel.cli import cli


# ── DemoTarget protocol conformance ─────────────────────────────────


class TestDemoTargetProtocol:
    def test_satisfies_target_system_protocol(self):
        target = DemoTarget(description="test system")
        assert isinstance(target, TargetSystem)

    def test_describe_returns_description(self):
        target = DemoTarget(description="My custom LLM pipeline")
        assert target.describe() == "My custom LLM pipeline"

    def test_describe_default(self):
        target = DemoTarget()
        assert "LLM assistant" in target.describe()


# ── DemoTarget run ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDemoTargetRun:
    async def test_run_delegates_to_client(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "Hello from the model"
        mock_response.model = "test-model"
        mock_response.latency_ms = 100
        mock_client.generate.return_value = mock_response

        target = DemoTarget(description="test", client=mock_client)
        result = await target.run("What is 2+2?")

        assert isinstance(result, TargetResult)
        assert result.output == "Hello from the model"
        assert not result.failed
        mock_client.generate.assert_awaited_once()

    async def test_run_with_context_setup(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "response"
        mock_response.model = "m"
        mock_response.latency_ms = 50
        mock_client.generate.return_value = mock_response

        target = DemoTarget(description="test", client=mock_client)
        await target.run("query", context_setup="extra context")

        call_kwargs = mock_client.generate.call_args
        system_arg = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")
        assert "extra context" in system_arg

    async def test_run_captures_error(self):
        mock_client = AsyncMock()
        mock_client.generate.side_effect = RuntimeError("API down")

        target = DemoTarget(description="test", client=mock_client)
        result = await target.run("query")

        assert result.failed
        assert "API down" in result.error

    async def test_run_without_client_raises(self):
        target = DemoTarget(description="test")
        with pytest.raises(RuntimeError, match="requires a ModelClient"):
            await target.run("query")


# ── DemoTarget interventions ────────────────────────────────────────


@pytest.mark.asyncio
class TestDemoTargetInterventions:
    async def test_apply_prompt_mutation(self):
        target = DemoTarget(description="test")
        await target.apply_intervention("prompt_mutation", {"mutation": "Be more careful."})
        assert "Be more careful." in target._system_prompt

    async def test_apply_guardrail(self):
        target = DemoTarget(description="test")
        await target.apply_intervention("guardrail", {"instruction": "No harmful content"})
        assert "GUARDRAIL" in target._system_prompt
        assert "No harmful content" in target._system_prompt

    async def test_reset_interventions(self):
        target = DemoTarget(description="test", system_prompt="Original prompt")
        await target.apply_intervention("prompt_mutation", {"mutation": "Extra"})
        assert "Extra" in target._system_prompt

        await target.reset_interventions()
        assert target._system_prompt == "Original prompt"


# ── CLI research command ────────────────────────────────────────────


class TestResearchCLI:
    def test_research_help_shows_options(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["research", "--help"])
        assert result.exit_code == 0
        assert "--focus" in result.output
        assert "--max-hypotheses" in result.output
        assert "--target" in result.output
        assert "--approval" in result.output

    def test_research_calls_create_sentinel(self):
        """Verify that the research command calls create_sentinel and research_cycle."""
        mock_sentinel = AsyncMock()
        mock_sentinel.settings = MagicMock()
        mock_sentinel.settings.experiments.cost_limit_usd = 10.0
        mock_sentinel.settings.approval.mode = "auto_approve"
        mock_sentinel.settings.models.default = "anthropic"

        mock_result = MagicMock()
        mock_result.cycle_id = "test_cycle"
        mock_result.hypotheses = []
        mock_result.failures = []
        mock_result.confirmed_failures = []
        mock_result.interventions = []
        mock_result.cost_summary = {"total_cost_usd": 0.0}

        mock_sentinel.research_cycle.return_value = mock_result
        mock_sentinel.close.return_value = None

        runner = CliRunner()
        with (
            patch("sentinel.create_sentinel", new_callable=AsyncMock, return_value=mock_sentinel) as mock_create,
            patch("sentinel.integrations.model_client.build_default_client", return_value=MagicMock()),
        ):
            result = runner.invoke(cli, ["research", "--focus", "reasoning"])

        assert result.exit_code == 0
        mock_create.assert_awaited_once()
