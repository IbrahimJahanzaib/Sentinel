"""Sentinel web dashboard — self-hosted FastAPI + vanilla JS frontend."""

from sentinel.dashboard.server import create_dashboard_app, run_dashboard

__all__ = ["create_dashboard_app", "run_dashboard"]
