"""Dashboard API route modules."""

from sentinel.dashboard.routes import (
    api_attacks,
    api_benchmarks,
    api_failures,
    api_research,
    api_settings,
    websocket,
)

__all__ = [
    "api_attacks",
    "api_benchmarks",
    "api_failures",
    "api_research",
    "api_settings",
    "websocket",
]
