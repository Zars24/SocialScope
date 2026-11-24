"""Bilingual copy, resolved on the server.

A page is translated before it is rendered, so the first paint is already
correct: no flash of Indonesian, no JavaScript required to read the site, and
no key left untranslated. The browser only flips the language cookie.

`ui` holds interface copy keyed by name. `phrases` maps an Indonesian sentence
produced by the backend (error taxonomy, capability explanations, provider
notices) to its English version, so the raise sites stay readable and a missing
translation degrades to Indonesian instead of an empty box.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parents[1] / "locales"

SUPPORTED = ("id", "en")
DEFAULT_LANG = "id"
LANG_COOKIE = "ss_lang"


def normalize_lang(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in SUPPORTED else DEFAULT_LANG


@lru_cache(maxsize=4)
def catalog(lang: str) -> dict[str, dict[str, str]]:
    path = LOCALES_DIR / f"{normalize_lang(lang)}.json"
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return {"ui": data.get("ui", {}), "phrases": data.get("phrases", {})}


def translator(lang: str):
    """Return `t(key, **params)` bound to one language."""
    primary = catalog(lang)
    fallback = catalog(DEFAULT_LANG)

    def t(key: str, **params: object) -> str:
        value = primary["ui"].get(key)
        if value is None:
            value = primary["phrases"].get(key)
        if value is None:
            value = fallback["ui"].get(key) or fallback["phrases"].get(key) or key
        if params:
            try:
                return value.format(**params)
            except (KeyError, IndexError, ValueError):
                return value
        return value

    return t


def request_lang(request) -> str:
    """Explicit `?lang=` wins over the cookie, which wins over the default."""
    query = request.query_params.get("lang")
    if query is not None:
        return normalize_lang(query)
    return normalize_lang(request.cookies.get(LANG_COOKIE))


def english_phrases() -> dict[str, str]:
    return catalog("en")["phrases"]


def indonesian_phrases() -> dict[str, str]:
    return catalog("id")["phrases"]