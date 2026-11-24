"""Shared request guards."""

from __future__ import annotations

from fastapi import Request

from app.core.limits import client_key


async def enforce_rate_limits(request: Request) -> None:
    await request.app.state.ip_limiter.acquire(client_key(request))
    await request.app.state.global_limiter.acquire("global")
