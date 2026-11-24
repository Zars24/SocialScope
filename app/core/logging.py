"""Structured, redacting logging.

No request bodies, no query strings, no upstream bodies, no keys, no media URLs.
Callers pass small scalar fields only; this module strips anything that looks
like a URL or a secret before it reaches the log record.
"""

from __future__ import annotations

import logging
import re

_SAFE_KEY = "socialscope"
_REDACTED = "[redacted]"
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SECRET_KEY_RE = re.compile(r"(key|token|secret|password|authorization|cookie)", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def configure_logging(debug: bool = False) -> None:
    logger = logging.getLogger(_SAFE_KEY)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s level=%(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False


def _clean_value(value: object) -> object:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        text = _CONTROL_RE.sub("", value)
        text = _URL_RE.sub("[url]", text)
        return text[:160]
    return _REDACTED


def log_event(event: str, **fields: object) -> None:
    logger = logging.getLogger(_SAFE_KEY)
    parts = [f"event={event}"]
    for key, value in fields.items():
        if _SECRET_KEY_RE.search(key):
            parts.append(f"{key}={_REDACTED}")
            continue
        parts.append(f"{key}={_clean_value(value)}")
    logger.info(" ".join(parts))


def log_warning(event: str, **fields: object) -> None:
    logger = logging.getLogger(_SAFE_KEY)
    parts = [f"event={event}"]
    for key, value in fields.items():
        if _SECRET_KEY_RE.search(key):
            parts.append(f"{key}={_REDACTED}")
            continue
        parts.append(f"{key}={_clean_value(value)}")
    logger.warning(" ".join(parts))
