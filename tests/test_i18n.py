"""The two catalogs must stay in lockstep, or a page renders a raw key."""

from __future__ import annotations

import ast
from pathlib import Path

from app.core.i18n import catalog, normalize_lang, translator

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_ui_keys_match_between_languages():
    indonesian = set(catalog("id")["ui"])
    english = set(catalog("en")["ui"])
    assert indonesian == english, indonesian ^ english


def test_every_ui_value_is_non_empty():
    for lang in ("id", "en"):
        empty = [key for key, value in catalog(lang)["ui"].items() if not value.strip()]
        assert not empty, (lang, empty)


def test_backend_sentences_have_english_phrases():
    """Every Indonesian sentence the backend can emit must be translated."""
    phrases = catalog("en")["phrases"]
    missing: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value
            if len(text) > 12 and any(ord(char) > 127 for char in text) and text not in phrases:
                missing.append(f"{path.name}: {text[:60]}")
    assert not missing, missing


def test_unknown_language_falls_back_to_indonesian():
    assert normalize_lang("xx") == "id"
    assert normalize_lang(None) == "id"
    assert normalize_lang("EN") == "en"
    assert translator("xx")("nav.story") == translator("id")("nav.story")


def test_unknown_key_returns_the_key_instead_of_blank():
    assert translator("en")("does.not.exist") == "does.not.exist"
