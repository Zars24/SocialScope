from __future__ import annotations

import asyncio
import time

import pytest

from app.core import errors
from app.core.limits import AsyncIntervalLimiter, DailyUnitCounter, SlidingWindowLimiter


def run(coro):
    return asyncio.run(coro)


def test_sliding_window_allows_limit_then_blocks():
    async def scenario():
        limiter = SlidingWindowLimiter(2, 60)
        await limiter.acquire("a")
        await limiter.acquire("a")
        with pytest.raises(errors.AppError) as excinfo:
            await limiter.acquire("a")
        return excinfo.value

    error = run(scenario())
    assert error.code == errors.RATE_LIMITED
    assert error.status_code == 429
    assert error.retry_after >= 1


def test_sliding_window_is_per_key():
    async def scenario():
        limiter = SlidingWindowLimiter(1, 60)
        await limiter.acquire("a")
        await limiter.acquire("b")

    run(scenario())


def test_daily_counter_cap_and_refund():
    async def scenario():
        counter = DailyUnitCounter(2)
        assert await counter.consume(1) == 1
        assert await counter.consume(1) == 0
        with pytest.raises(errors.AppError) as excinfo:
            await counter.consume(1)
        assert excinfo.value.code == errors.PROVIDER_QUOTA
        await counter.refund(1)
        await counter.consume(1)
        return await counter.snapshot()

    snapshot = run(scenario())
    assert snapshot == {"used": 2, "cap": 2, "remaining": 0}


def test_interval_limiter_serializes_calls():
    async def scenario():
        limiter = AsyncIntervalLimiter(0.02)
        await limiter.wait()
        await limiter.wait()

    run(scenario())


def test_interval_limiter_spaces_after_completion():
    async def scenario():
        limiter = AsyncIntervalLimiter(0.05)
        await limiter.wait()
        started = time.monotonic()
        await limiter.complete()
        await limiter.wait()
        return time.monotonic() - started

    assert run(scenario()) >= 0.045
