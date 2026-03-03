"""Cost tracker — per-provider token usage and USD cost accumulation with budget enforcement."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Pricing tables (USD per million tokens)
# Update as provider pricing changes.
# ---------------------------------------------------------------------------

_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-sonnet-4-20250514":  {"input": 3.0,   "output": 15.0},
    "claude-opus-4-6":           {"input": 15.0,  "output": 75.0},
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.0},
    # OpenAI
    "gpt-4o":                    {"input": 5.0,   "output": 15.0},
    "gpt-4-turbo-preview":       {"input": 10.0,  "output": 30.0},
    "gpt-4-turbo":               {"input": 10.0,  "output": 30.0},
    "gpt-3.5-turbo":             {"input": 0.5,   "output": 1.5},
    # Groq (free tier — placeholder pricing)
    "llama3-70b-8192":           {"input": 0.0,   "output": 0.0},
    "llama3-8b-8192":            {"input": 0.0,   "output": 0.0},
    "mixtral-8x7b-32768":        {"input": 0.0,   "output": 0.0},
    # Ollama (always free — local)
    "llama3":                    {"input": 0.0,   "output": 0.0},
    "llama3:8b":                 {"input": 0.0,   "output": 0.0},
    "mistral":                   {"input": 0.0,   "output": 0.0},
    # OpenRouter / Together — approximate
    "deepseek/deepseek-chat":              {"input": 0.14, "output": 0.28},
    "meta-llama/Llama-3-70b-chat-hf":     {"input": 0.9,  "output": 0.9},
}

_DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _PRICING.get(model, _DEFAULT_PRICING)
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# Per-call record
# ---------------------------------------------------------------------------

@dataclass
class CallRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------

class BudgetExceededError(Exception):
    """Raised when accumulated cost exceeds the configured budget."""


@dataclass
class ProviderUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class CostTracker:
    """Accumulates token usage and USD cost across LLM calls within a research cycle.

    Thread- and async-safe via asyncio.Lock.

    Parameters
    ----------
    budget_usd:
        Hard limit in USD. If set, ``check_budget()`` raises ``BudgetExceededError``
        once the accumulated cost exceeds this value.
    """

    def __init__(self, budget_usd: Optional[float] = None) -> None:
        self._budget = budget_usd
        self._lock = asyncio.Lock()
        self._records: list[CallRecord] = []
        self._by_provider: dict[str, ProviderUsage] = {}

        # Totals
        self.total_calls: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost_usd: float = 0.0

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int = 0,
    ) -> float:
        """Record a completed LLM call and return its cost in USD."""
        cost = _calculate_cost(model, input_tokens, output_tokens)

        async with self._lock:
            rec = CallRecord(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
            )
            self._records.append(rec)

            if provider not in self._by_provider:
                self._by_provider[provider] = ProviderUsage()
            pu = self._by_provider[provider]
            pu.calls += 1
            pu.input_tokens += input_tokens
            pu.output_tokens += output_tokens
            pu.cost_usd += cost

            self.total_calls += 1
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cost_usd += cost

        return cost

    def check_budget(self) -> None:
        """Raise BudgetExceededError if the budget has been exceeded."""
        if self._budget is not None and self.total_cost_usd > self._budget:
            raise BudgetExceededError(
                f"Cost limit exceeded: ${self.total_cost_usd:.4f} > ${self._budget:.2f}"
            )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a flat summary dict suitable for logging or DB storage."""
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "budget_usd": self._budget,
            "by_provider": {
                p: {
                    "calls": u.calls,
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cost_usd": round(u.cost_usd, 6),
                }
                for p, u in self._by_provider.items()
            },
        }

    def reset(self) -> None:
        """Reset all counters — used between research cycles."""
        self._records.clear()
        self._by_provider.clear()
        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0

    def __repr__(self) -> str:
        return (
            f"CostTracker(calls={self.total_calls}, "
            f"tokens={self.total_input_tokens}+{self.total_output_tokens}, "
            f"cost=${self.total_cost_usd:.4f})"
        )
