"""In-memory abuse and spend controls.

Nothing here is persisted. Restarting the process resets counters; this is
documented as a limitation, not presented as a billing guarantee.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import deque
from datetime import date

from fastapi import Request

from app.core import errors


def client_key(request: Request) -> str:
    """Pseudonymous limiter key.

    We deliberately do not trust X-Forwarded-For: this app is designed to run
    behind a single trusted proxy at most, and a spoofable header would defeat
    the per-visitor limit.
    """
    host = request.client.host if request.client else "unknown"
    return hashlib.sha256(host.encode("utf-8", "ignore")).hexdigest()[:16]


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, limit)
        self.window = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> int:
        """Consume one slot. Raise rate_limited with a retry hint when full."""
        async with self._lock:
            now = time.monotonic()
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = int(self.window - (now - events[0])) + 1
                raise errors.rate_limited(retry_after)
            events.append(now)
            if len(self._events) > 4096:
                self._prune(now)
            return self.limit - len(events)

    def _prune(self, now: float) -> None:
        stale = [
            key
            for key, events in self._events.items()
            if not events or now - events[-1] >= self.window
        ]
        for key in stale[:2048]:
            self._events.pop(key, None)


class AsyncIntervalLimiter:
    """Serialize calls so providers with a 1 request/second budget are respected.

    `wait()` spaces request *starts*. `complete()` then pushes the next allowed
    start at least one interval past the response, because some providers count
    the rate window from completion rather than from the request start.
    """

    def __init__(self, min_interval: float = 1.05) -> None:
        self.min_interval = min_interval
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next_at - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_at = time.monotonic() + self.min_interval

    async def complete(self) -> None:
        async with self._lock:
            self._next_at = max(self._next_at, time.monotonic() + self.min_interval)


class DailyUnitCounter:
    """Spend guard for a metered provider.

    Counts *attempts that may be billed*. Free error classes are not counted by
    the adapter; the adapter decides before calling `consume`.
    """

    def __init__(self, cap: int) -> None:
        self.cap = max(0, cap)
        self._day = date.today()
        self._used = 0
        self._lock = asyncio.Lock()

    def _roll(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self._used = 0

    async def consume(self, units: int = 1) -> int:
        async with self._lock:
            self._roll()
            if self._used + units > self.cap:
                raise errors.AppError(
                    errors.PROVIDER_QUOTA,
                    "Kuota Story Instagram untuk hari ini sudah habis.",
                    503,
                    hint="Kuota direset pada hari berikutnya. Ini batas biaya yang disengaja.",
                )
            self._used += units
            return self.cap - self._used

    async def refund(self, units: int = 1) -> None:
        """Return reserved units when the provider confirms the call was free."""
        async with self._lock:
            self._roll()
            self._used = max(0, self._used - units)

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            self._roll()
            return {"used": self._used, "cap": self.cap, "remaining": self.cap - self._used}
