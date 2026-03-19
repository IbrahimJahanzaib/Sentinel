"""API key authentication middleware."""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key() -> Optional[str]:
    """Return the configured API key, or None if auth is disabled."""
    return os.environ.get("SENTINEL_API_KEY")


async def verify_api_key(
    api_key: Optional[str] = Security(_API_KEY_HEADER),
) -> Optional[str]:
    """Dependency that validates the API key if one is configured.

    If SENTINEL_API_KEY is not set, authentication is disabled (open access).
    """
    expected = get_api_key()
    if expected is None:
        # No key configured — auth disabled
        return None

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    if not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key
