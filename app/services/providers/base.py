"""Boundary helpers shared by provider adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

TIKTOK_MEDIA_DOMAINS = (
    "tiktokcdn.com",
    "tiktokcdn-eu.com",
    "tiktokcdn-us.com",
    "tiktokcdn-asia.com",
    "tiktokv.com",
    "tiktok.com",
    "ibyteimg.com",
)

INSTAGRAM_MEDIA_DOMAINS = (
    "cdninstagram.com",
    "fbcdn.net",
    "instagram.com",
)

TIKTOK_PERMALINK_DOMAINS = ("tiktok.com",)
INSTAGRAM_PERMALINK_DOMAINS = ("instagram.com",)


def host_matches(host: str, domains: tuple[str, ...]) -> bool:
    host = (host or "").lower().strip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def safe_url(value: object, domains: tuple[str, ...]) -> str | None:
    """Return an HTTPS URL only when its host is on the expected CDN allowlist."""
    if not isinstance(value, str) or not value:
        return None
    if len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme != "https":
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    host = parsed.hostname or ""
    if not host_matches(host, domains):
        return None
    return value


def iso_from_epoch(value: object) -> tuple[int | None, str | None]:
    if isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        stamp = int(value)
    elif isinstance(value, str) and value.isdigit():
        stamp = int(value)
    else:
        return None, None
    if stamp <= 0 or stamp > 4_102_444_800:  # year 2100 guard
        return None, None
    try:
        dt = datetime.fromtimestamp(stamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None, None
    return stamp, dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_iso(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return value


def safe_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0 or number > 86_400:
            return None
        return round(number, 1)
    return None


def safe_text(value: object, *, limit: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def safe_username(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lstrip("@")
    if not cleaned or len(cleaned) > 30:
        return None
    if not all(ch.isalnum() or ch in "._" for ch in cleaned):
        return None
    return cleaned
