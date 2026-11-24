"""Platform detection from a loose pasted string."""

from __future__ import annotations

from urllib.parse import urlsplit

TIKTOK_HOSTS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}
INSTAGRAM_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
}


def normalize_for_detection(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    return text


def detect_platform(raw: str) -> str | None:
    """Best-effort detection for UI feedback. Never used as a security check."""
    text = normalize_for_detection(raw)
    if not text:
        return None
    try:
        host = (urlsplit(text).hostname or "").lower().strip(".")
    except ValueError:
        return None
    if host in TIKTOK_HOSTS or host.endswith(".tiktok.com"):
        return "tiktok" if host in TIKTOK_HOSTS else None
    if host in INSTAGRAM_HOSTS or host.endswith(".instagram.com"):
        return "instagram" if host in INSTAGRAM_HOSTS else None
    return None
