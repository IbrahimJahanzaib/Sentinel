"""Phase 2 smoke tests — LLM client and cost tracker (no real API calls)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sentinel.core.cost_tracker import BudgetExceededError, CostTracker
from sentinel.integrations.model_client import (
    AnthropicClient,
    Message,
    ModelClient,
    OpenAICompatibleClient,
    OllamaClient,
    Response,
    _parse_json,
    build_client,
    build_default_client,
)


# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cost_tracker_records_correctly():
    tracker = CostTracker(budget_usd=10.0)
    cost = await tracker.record(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        input_tokens=1000,
        output_tokens=500,
        latency_ms=300,
    )
    # 1000 * 3.0/1M + 500 * 15.0/1M = 0.003 + 0.0075 = 0.0105
    assert abs(cost - 0.0105) < 1e-9
    assert tracker.total_calls == 1
    assert tracker.total_input_tokens == 1000
    assert tracker.total_output_tokens == 500
    assert abs(tracker.total_cost_usd - 0.0105) < 1e-9


@pytest.mark.asyncio
async def test_cost_tracker_budget_enforcement():
    tracker = CostTracker(budget_usd=0.001)  # tiny budget
    await tracker.record("anthropic", "claude-sonnet-4-20250514", 10000, 5000)
    with pytest.raises(BudgetExceededError):
        tracker.check_budget()


@pytest.mark.asyncio
async def test_cost_tracker_per_provider_breakdown():
    tracker = CostTracker()
    await tracker.record("anthropic", "claude-sonnet-4-20250514", 100, 50)
    await tracker.record("ollama", "llama3", 200, 100)

    summary = tracker.summary()
    assert "anthropic" in summary["by_provider"]
    assert "ollama" in summary["by_provider"]
    assert summary["by_provider"]["ollama"]["cost_usd"] == 0.0  # free
    assert summary["total_calls"] == 2


@pytest.mark.asyncio
async def test_cost_tracker_reset():
    tracker = CostTracker()
    await tracker.record("openai", "gpt-4-turbo", 500, 200)
    tracker.reset()
    assert tracker.total_calls == 0
    assert tracker.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# _parse_json helper
# ---------------------------------------------------------------------------

def test_parse_json_plain():
    assert _parse_json('{"key": "value"}') == {"key": "value"}


def test_parse_json_with_fence():
    text = '```json\n{"key": "value"}\n```'
    assert _parse_json(text) == {"key": "value"}


def test_parse_json_with_prose():
    text = 'Here is the result: {"key": "value"} as requested.'
    assert _parse_json(text) == {"key": "value"}


def test_parse_json_array():
    assert _parse_json('[1, 2, 3]') == [1, 2, 3]


# ---------------------------------------------------------------------------
# AnthropicClient (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anthropic_client_generate():
    tracker = CostTracker()

    # Mock the anthropic SDK response
    mock_content = MagicMock()
    mock_content.text = "Hello from Claude!"

    mock_usage = MagicMock()
    mock_usage.input_tokens = 20
    mock_usage.output_tokens = 10

    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage = mock_usage

    with patch("anthropic.AsyncAnthropic") as MockAnthropic:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        MockAnthropic.return_value = mock_instance

        client = AnthropicClient(api_key="fake-key", model="claude-sonnet-4-20250514", tracker=tracker)
        resp = await client.generate(
            [Message(role="user", content="Say hello")],
            system="You are helpful.",
        )

    assert resp.text == "Hello from Claude!"
    assert resp.provider == "anthropic"
    assert resp.input_tokens == 20
    assert resp.output_tokens == 10
    assert tracker.total_calls == 1
    assert tracker.total_cost_usd > 0


@pytest.mark.asyncio
async def test_anthropic_client_generate_structured():
    tracker = CostTracker()

    mock_content = MagicMock()
    mock_content.text = '{"result": "structured", "value": 42}'

    mock_usage = MagicMock()
    mock_usage.input_tokens = 30
    mock_usage.output_tokens = 15

    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage = mock_usage

    with patch("anthropic.AsyncAnthropic") as MockAnthropic:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        MockAnthropic.return_value = mock_instance

        client = AnthropicClient(api_key="fake-key", tracker=tracker)
        result = await client.generate_structured(
            [Message(role="user", content="Give me JSON")]
        )

    assert result == {"result": "structured", "value": 42}


# ---------------------------------------------------------------------------
# OpenAICompatibleClient (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openai_client_generate():
    tracker = CostTracker()

    mock_choice = MagicMock()
    mock_choice.message.content = "Hello from GPT!"

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 15
    mock_usage.completion_tokens = 8

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    with patch("openai.AsyncOpenAI") as MockOpenAI:
        mock_instance = AsyncMock()
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)
        MockOpenAI.return_value = mock_instance

        client = OpenAICompatibleClient(
            api_key="fake", model="gpt-4-turbo", provider_name="openai", tracker=tracker
        )
        resp = await client.generate([Message(role="user", content="Hi")])

    assert resp.text == "Hello from GPT!"
    assert resp.provider == "openai"
    assert resp.input_tokens == 15
    assert resp.output_tokens == 8


# ---------------------------------------------------------------------------
# build_client factory
# ---------------------------------------------------------------------------

def test_build_client_unknown_provider():
    from sentinel.config.settings import SentinelSettings
    settings = SentinelSettings()
    with pytest.raises(ValueError, match="Unknown provider"):
        build_client("nonexistent_provider", settings)


def test_build_client_anthropic():
    from sentinel.config.settings import SentinelSettings
    settings = SentinelSettings()
    with patch("anthropic.AsyncAnthropic"):
        client = build_client("anthropic", settings)
    assert client.provider == "anthropic"


def test_build_client_ollama():
    from sentinel.config.settings import SentinelSettings
    import httpx
    settings = SentinelSettings()
    with patch("httpx.AsyncClient"):
        client = build_client("ollama", settings)
    assert client.provider == "ollama"
