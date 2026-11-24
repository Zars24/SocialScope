from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core import errors
from app.core.http import fetch_json


def run(coro):
    return asyncio.run(coro)


def test_json_success_and_headers():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/test"
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_json(client, "https://provider.example/api/test")

    status, headers, payload = run(scenario())
    assert status == 200
    assert payload == {"ok": True}
    assert headers["content-type"] == "application/json"


def test_redirect_is_rejected_even_if_client_follows():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            await fetch_json(client, "https://provider.example/api/test")

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.PROVIDER_ERROR
    assert "evil.example" not in excinfo.value.message


def test_non_json_success_is_rejected():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nope</html>", headers={"content-type": "text/html"})

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await fetch_json(client, "https://provider.example/api/test")

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.PROVIDER_ERROR


def test_error_status_json_is_returned_for_adapter_mapping():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"code": "rate_limited"},
            headers={"content-type": "application/json", "retry-after": "1"},
        )

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_json(client, "https://provider.example/api/test")

    status, headers, payload = run(scenario())
    assert status == 429
    assert payload == {"code": "rate_limited"}
    assert headers["retry-after"] == "1"


def test_malformed_json_is_rejected():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"{not json", headers={"content-type": "application/json"}
        )

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await fetch_json(client, "https://provider.example/api/test")

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.PROVIDER_ERROR


def test_byte_cap_is_enforced_while_streaming():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"data":"' + b"x" * 500 + b'"}',
            headers={"content-type": "application/json"},
        )

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await fetch_json(client, "https://provider.example/api/test", max_bytes=50)

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.PROVIDER_ERROR
    assert "response_too_large" in (excinfo.value.internal or "")


def test_timeout_maps_to_safe_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await fetch_json(client, "https://provider.example/api/test")

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.TIMEOUT
    assert excinfo.value.status_code == 504
