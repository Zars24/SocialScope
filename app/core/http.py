"""Outbound HTTP with hard limits.

Every call is built by a provider adapter from a fixed base URL plus a validated
identifier. The visitor-submitted URL is never passed to this module.

Guarantees:
- redirects are refused (3xx is an error),
- connect/read/write/pool timeouts,
- streaming byte cap,
- JSON content-type check before parsing,
- no cookies, no proxy, no retries.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core import errors


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    max_bytes: int = 512 * 1024,
) -> tuple[int, httpx.Headers, Any | None]:
    """Return (status, headers, parsed_json_or_none).

    Non-2xx responses are returned to the caller so an adapter can map the
    provider's documented error code. A 3xx is always an error.
    """
    try:
        async with client.stream("GET", url, params=params, headers=headers) as response:
            if response.is_redirect:
                raise errors.provider_error(internal="upstream_redirect")
            if response.status_code >= 400 and response.status_code < 500:
                # These are expected, priced, and mapped by the adapter.
                pass

            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise errors.provider_error(
                        internal=f"response_too_large:{len(body)}"
                    )

            status = response.status_code
            response_headers = response.headers
            content_type = (response_headers.get("content-type") or "").lower()
    except httpx.TimeoutException as exc:
        raise errors.upstream_timeout() from exc
    except httpx.HTTPError as exc:
        raise errors.provider_error(internal=type(exc).__name__) from exc

    is_json = "application/json" in content_type or "text/json" in content_type
    if not is_json:
        if 200 <= status < 300:
            raise errors.provider_error(internal=f"unexpected_content_type:{content_type[:40]}")
        return status, response_headers, None

    if not body:
        return status, response_headers, None

    try:
        payload = json.loads(bytes(body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise errors.provider_error(internal="malformed_json") from exc

    return status, response_headers, payload
