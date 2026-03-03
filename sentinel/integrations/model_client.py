"""Multi-provider async LLM client.

Providers supported:
  - anthropic   — Anthropic Claude (anthropic SDK)
  - openai      — OpenAI GPT (openai SDK)
  - groq        — Groq (openai SDK, custom base_url)
  - openrouter  — OpenRouter (openai SDK, custom base_url)
  - together    — Together AI (openai SDK, custom base_url)
  - ollama      — Ollama local (httpx, REST API)

All providers implement the same ModelClient interface:
  generate()            → Response
  generate_structured() → dict   (JSON output)
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel.core.cost_tracker import CostTracker
    from sentinel.config.settings import SentinelSettings


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A single conversation turn."""
    role: str    # "user" | "assistant" | "system"
    content: str


@dataclass
class Response:
    """Structured response from any LLM provider."""
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class ModelClient(ABC):
    """Abstract async LLM client interface."""

    def __init__(self, tracker: Optional["CostTracker"] = None) -> None:
        self._tracker = tracker

    @property
    @abstractmethod
    def provider(self) -> str:
        """Provider name string (e.g. 'anthropic')."""

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Response:
        """Generate a text response."""

    async def generate_structured(
        self,
        messages: list[Message],
        schema: Optional[dict] = None,
        *,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        retries: int = 2,
    ) -> dict:
        """Generate a response and parse it as JSON.

        Instructs the model to output pure JSON via the system prompt.
        Retries on parse failure.
        """
        json_instruction = (
            "\n\nIMPORTANT: Respond with ONLY valid JSON — no markdown fences, "
            "no explanation, no prose. Start your response with { or [."
        )
        augmented_system = (system or "") + json_instruction

        last_err: Optional[Exception] = None
        raw_text = ""
        for attempt in range(retries + 1):
            resp = await self.generate(
                messages,
                system=augmented_system,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            raw_text = resp.text.strip()
            try:
                return _parse_json(raw_text)
            except json.JSONDecodeError as exc:
                last_err = exc
                if attempt < retries:
                    # Append failure note for the retry
                    messages = messages + [
                        Message(role="assistant", content=raw_text),
                        Message(
                            role="user",
                            content="Your response was not valid JSON. Please try again — output ONLY JSON.",
                        ),
                    ]

        raise ValueError(
            f"Model returned non-JSON after {retries + 1} attempts. "
            f"Last error: {last_err}\nRaw: {raw_text[:300]}"
        )

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> float:
        """Record usage in the cost tracker and return cost in USD."""
        if self._tracker is None:
            from sentinel.core.cost_tracker import _calculate_cost
            return _calculate_cost(model, input_tokens, output_tokens)
        cost = await self._tracker.record(
            provider=self.provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        return cost


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

class AnthropicClient(ModelClient):
    """Anthropic Claude via the official anthropic SDK."""

    provider = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        tracker: Optional["CostTracker"] = None,
    ) -> None:
        super().__init__(tracker)
        import anthropic as _anthropic
        self._client = _anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate(
        self,
        messages: list[Message],
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Response:
        sdk_messages = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict[str, Any] = dict(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=sdk_messages,
        )
        if system:
            kwargs["system"] = system

        t0 = time.monotonic()
        resp = await self._client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - t0) * 1000)

        text = resp.content[0].text
        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        cost = await self._record(self._model, in_tok, out_tok, latency_ms)

        return Response(
            text=text,
            provider=self.provider,
            model=self._model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (OpenAI, Groq, OpenRouter, Together)
# ---------------------------------------------------------------------------

class OpenAICompatibleClient(ModelClient):
    """Any provider that implements the OpenAI chat completions API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        provider_name: str,
        base_url: Optional[str] = None,
        tracker: Optional["CostTracker"] = None,
    ) -> None:
        super().__init__(tracker)
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._provider = provider_name

    @property
    def provider(self) -> str:
        return self._provider

    async def generate(
        self,
        messages: list[Message],
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Response:
        sdk_messages: list[dict] = []
        if system:
            sdk_messages.append({"role": "system", "content": system})
        sdk_messages.extend({"role": m.role, "content": m.content} for m in messages)

        t0 = time.monotonic()
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=sdk_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        text = resp.choices[0].message.content or ""
        in_tok = resp.usage.prompt_tokens if resp.usage else 0
        out_tok = resp.usage.completion_tokens if resp.usage else 0
        cost = await self._record(self._model, in_tok, out_tok, latency_ms)

        return Response(
            text=text,
            provider=self.provider,
            model=self._model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        schema: Optional[dict] = None,
        *,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        retries: int = 2,
    ) -> dict:
        """Override to use native JSON mode where available."""
        sdk_messages: list[dict] = []
        if system:
            sdk_messages.append({"role": "system", "content": system})
        sdk_messages.extend({"role": m.role, "content": m.content} for m in messages)

        t0 = time.monotonic()
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=sdk_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        text = resp.choices[0].message.content or "{}"
        in_tok = resp.usage.prompt_tokens if resp.usage else 0
        out_tok = resp.usage.completion_tokens if resp.usage else 0
        await self._record(self._model, in_tok, out_tok, latency_ms)

        return json.loads(text)


# ---------------------------------------------------------------------------
# Ollama provider (local — httpx REST API)
# ---------------------------------------------------------------------------

class OllamaClient(ModelClient):
    """Ollama local model server via httpx REST API."""

    provider = "ollama"

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
        tracker: Optional["CostTracker"] = None,
    ) -> None:
        super().__init__(tracker)
        import httpx
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=120.0)

    async def generate(
        self,
        messages: list[Message],
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Response:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system

        t0 = time.monotonic()
        resp = await self._http.post(f"{self._base_url}/api/chat", json=payload)
        resp.raise_for_status()
        latency_ms = int((time.monotonic() - t0) * 1000)

        data = resp.json()
        text = data.get("message", {}).get("content", "")

        # Ollama reports eval_count (output tokens) and prompt_eval_count (input)
        in_tok = data.get("prompt_eval_count", 0)
        out_tok = data.get("eval_count", 0)
        cost = await self._record(self._model, in_tok, out_tok, latency_ms)

        return Response(
            text=text,
            provider=self.provider,
            model=self._model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
        )

    async def close(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def build_client(
    provider: str,
    settings: "SentinelSettings",
    tracker: Optional["CostTracker"] = None,
) -> ModelClient:
    """Build the right ModelClient for the given provider name.

    Parameters
    ----------
    provider:
        One of: anthropic, openai, groq, openrouter, together, ollama.
        Defaults to the value of ``settings.models.default`` if ``None``.
    settings:
        Loaded SentinelSettings.
    tracker:
        Optional CostTracker to attach to the client.
    """
    provider = provider or settings.models.default

    if provider == "anthropic":
        cfg = settings.models.get_anthropic()
        return AnthropicClient(api_key=cfg.api_key, model=cfg.model, tracker=tracker)

    if provider == "openai":
        cfg = settings.models.get_openai()
        return OpenAICompatibleClient(
            api_key=cfg.api_key, model=cfg.model,
            provider_name="openai", tracker=tracker,
        )

    if provider == "groq":
        cfg = settings.models.get_groq()
        return OpenAICompatibleClient(
            api_key=cfg.api_key, model=cfg.model,
            provider_name="groq",
            base_url="https://api.groq.com/openai/v1",
            tracker=tracker,
        )

    if provider == "openrouter":
        cfg = settings.models.get_openrouter()
        return OpenAICompatibleClient(
            api_key=cfg.api_key, model=cfg.model,
            provider_name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            tracker=tracker,
        )

    if provider == "together":
        cfg = settings.models.get_together()
        return OpenAICompatibleClient(
            api_key=cfg.api_key, model=cfg.model,
            provider_name="together",
            base_url="https://api.together.xyz/v1",
            tracker=tracker,
        )

    if provider == "ollama":
        cfg = settings.models.get_ollama()
        return OllamaClient(model=cfg.model, base_url=cfg.base_url, tracker=tracker)

    raise ValueError(
        f"Unknown provider: {provider!r}. "
        "Valid options: anthropic, openai, groq, openrouter, together, ollama"
    )


def build_default_client(
    settings: "SentinelSettings",
    tracker: Optional["CostTracker"] = None,
) -> ModelClient:
    """Build the client for the configured default provider."""
    return build_client(settings.models.default, settings, tracker)


# ---------------------------------------------------------------------------
# JSON parse helper
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _parse_json(text: str) -> Any:
    """Parse JSON from model output, stripping markdown fences if present."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try stripping markdown fences
    match = _FENCE_RE.search(text)
    if match:
        return json.loads(match.group(1).strip())
    # Try finding the first { or [ and parsing from there
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise json.JSONDecodeError("No valid JSON found", text, 0)
