"""Configuration loading — YAML with ${ENV_VAR} expansion and Pydantic validation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

from .modes import Mode

# ---------------------------------------------------------------------------
# Provider config models
# ---------------------------------------------------------------------------

class AnthropicConfig(BaseModel):
    api_key: str = Field(default="")
    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.7
    max_tokens: int = 4096


class OpenAIConfig(BaseModel):
    api_key: str = Field(default="")
    model: str = "gpt-4-turbo-preview"
    temperature: float = 0.7
    max_tokens: int = 4096


class GroqConfig(BaseModel):
    api_key: str = Field(default="")
    model: str = "llama3-70b-8192"
    temperature: float = 0.7
    max_tokens: int = 4096


class OllamaConfig(BaseModel):
    model: str = "llama3"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.7
    max_tokens: int = 4096


class OpenRouterConfig(BaseModel):
    api_key: str = Field(default="")
    model: str = "deepseek/deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096


class TogetherConfig(BaseModel):
    api_key: str = Field(default="")
    model: str = "meta-llama/Llama-3-70b-chat-hf"
    temperature: float = 0.7
    max_tokens: int = 4096


class ModelsConfig(BaseModel):
    default: str = "anthropic"
    providers: dict[str, Any] = Field(default_factory=dict)

    def get_anthropic(self) -> AnthropicConfig:
        raw = self.providers.get("anthropic", {})
        cfg = AnthropicConfig(**raw) if isinstance(raw, dict) else AnthropicConfig()
        if not cfg.api_key:
            cfg.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        return cfg

    def get_openai(self) -> OpenAIConfig:
        raw = self.providers.get("openai", {})
        cfg = OpenAIConfig(**raw) if isinstance(raw, dict) else OpenAIConfig()
        if not cfg.api_key:
            cfg.api_key = os.environ.get("OPENAI_API_KEY", "")
        return cfg

    def get_groq(self) -> GroqConfig:
        raw = self.providers.get("groq", {})
        cfg = GroqConfig(**raw) if isinstance(raw, dict) else GroqConfig()
        if not cfg.api_key:
            cfg.api_key = os.environ.get("GROQ_API_KEY", "")
        return cfg

    def get_ollama(self) -> OllamaConfig:
        raw = self.providers.get("ollama", {})
        return OllamaConfig(**raw) if isinstance(raw, dict) else OllamaConfig()

    def get_openrouter(self) -> OpenRouterConfig:
        raw = self.providers.get("openrouter", {})
        cfg = OpenRouterConfig(**raw) if isinstance(raw, dict) else OpenRouterConfig()
        if not cfg.api_key:
            cfg.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        return cfg

    def get_together(self) -> TogetherConfig:
        raw = self.providers.get("together", {})
        cfg = TogetherConfig(**raw) if isinstance(raw, dict) else TogetherConfig()
        if not cfg.api_key:
            cfg.api_key = os.environ.get("TOGETHER_API_KEY", "")
        return cfg


# ---------------------------------------------------------------------------
# Top-level config models
# ---------------------------------------------------------------------------

class DatabaseConfig(BaseModel):
    url: str = "sqlite+aiosqlite:///sentinel.db"
    pool_size: int = 10
    echo: bool = False


class ResearchConfig(BaseModel):
    max_hypotheses_per_run: int = 10
    max_experiments_per_hypothesis: int = 3
    default_runs_per_experiment: int = 5


class ExperimentsConfig(BaseModel):
    max_parallel: int = 5
    default_timeout_seconds: int = 300
    cost_limit_usd: float = 10.0


class RiskConfig(BaseModel):
    auto_approve_safe: bool = True
    block_on_destructive: bool = True


class ApprovalConfig(BaseModel):
    mode: str = "interactive"   # interactive | async | auto_approve | auto_reject
    timeout_seconds: int = 300


class SentinelSettings(BaseModel):
    """Root settings object loaded from .sentinel/config.yaml."""
    mode: Mode = Mode.LAB
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    experiments: ExperimentsConfig = Field(default_factory=ExperimentsConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)

    @field_validator("mode", mode="before")
    @classmethod
    def _parse_mode(cls, v: Any) -> Mode:
        if isinstance(v, Mode):
            return v
        return Mode(str(v).lower())


# ---------------------------------------------------------------------------
# YAML loader with ${ENV_VAR} expansion
# ---------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(obj: Any) -> Any:
    """Recursively expand ${VAR} placeholders using environment variables."""
    if isinstance(obj, str):
        def _replace(match: re.Match) -> str:
            var = match.group(1)
            return os.environ.get(var, match.group(0))  # keep original if not set
        return _ENV_VAR_RE.sub(_replace, obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(config_path: Optional[Path] = None) -> SentinelSettings:
    """Load and validate Sentinel settings.

    Search order:
    1. Explicit ``config_path`` argument
    2. ``.sentinel/config.yaml`` in the current working directory
    3. Built-in defaults + environment variables
    """
    from dotenv import load_dotenv
    load_dotenv()

    raw: dict[str, Any] = {}

    candidates: list[Path] = []
    if config_path:
        candidates.append(Path(config_path))
    candidates.append(Path.cwd() / ".sentinel" / "config.yaml")

    for candidate in candidates:
        if candidate.exists():
            with candidate.open() as fh:
                loaded = yaml.safe_load(fh) or {}
            raw = _deep_merge(raw, loaded)
            break

    raw = _expand_env_vars(raw)
    return SentinelSettings.model_validate(raw)


# ---------------------------------------------------------------------------
# Default config YAML template (written by `sentinel init`)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_YAML = """\
mode: lab  # lab | shadow | production

database:
  url: sqlite+aiosqlite:///sentinel.db
  pool_size: 10

models:
  default: anthropic
  providers:
    anthropic:
      api_key: ${ANTHROPIC_API_KEY}
      model: claude-sonnet-4-20250514
      temperature: 0.7
    openai:
      api_key: ${OPENAI_API_KEY}
      model: gpt-4-turbo-preview
    groq:
      api_key: ${GROQ_API_KEY}
      model: llama3-70b-8192
    ollama:
      model: llama3
      base_url: http://localhost:11434
    openrouter:
      api_key: ${OPENROUTER_API_KEY}
      model: deepseek/deepseek-chat
    together:
      api_key: ${TOGETHER_API_KEY}
      model: meta-llama/Llama-3-70b-chat-hf

research:
  max_hypotheses_per_run: 10
  max_experiments_per_hypothesis: 3
  default_runs_per_experiment: 5

experiments:
  max_parallel: 5
  default_timeout_seconds: 300
  cost_limit_usd: 10.0

risk:
  auto_approve_safe: true
  block_on_destructive: true

approval:
  mode: interactive  # interactive | async | auto_approve | auto_reject
  timeout_seconds: 300
"""
