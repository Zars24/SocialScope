from __future__ import annotations

from app.services.capabilities import (
    capabilities_for,
    capability_matrix,
    matrix_rows,
    story_capability,
)


def test_story_reflects_provider_configuration():
    from tests.conftest import make_settings

    enabled = make_settings(storiesfly_api_key="test-key", storiesfly_enabled=True)
    disabled = make_settings(storiesfly_api_key="", storiesfly_enabled=True)
    off = make_settings(storiesfly_api_key="test-key", storiesfly_enabled=False)

    tiktok = story_capability("tiktok", enabled)
    assert tiktok.status == "supported"
    assert tiktok.mode == "structured"

    instagram = story_capability("instagram", enabled)
    assert instagram.status == "supported"

    missing_key = story_capability("instagram", disabled)
    assert missing_key.status == "unavailable"
    assert missing_key.reason == "provider_not_configured"

    switched_off = story_capability("instagram", off)
    assert switched_off.status == "unavailable"


def test_profile_capabilities_are_honest():
    from tests.conftest import make_settings

    settings = make_settings()
    tiktok = {cap.key: cap for cap in capabilities_for("tiktok", settings)}
    instagram = {cap.key: cap for cap in capabilities_for("instagram", settings)}

    assert tiktok["profile"].status == "embed_only"
    assert tiktok["profile"].mode == "embed"
    assert instagram["profile"].status == "unavailable"
    assert instagram["profile"].mode is None


def test_common_capabilities_are_never_claimed():
    from tests.conftest import make_settings

    settings = make_settings()
    for platform in ("tiktok", "instagram"):
        caps = {cap.key: cap for cap in capabilities_for(platform, settings)}  # type: ignore[arg-type]
        assert caps["viewer_list"].status == "unavailable"
        assert caps["download"].status == "unavailable"


def test_every_capability_has_an_explanation():
    from tests.conftest import make_settings

    settings = make_settings()
    for platform in ("tiktok", "instagram"):
        for cap in capabilities_for(platform, settings):  # type: ignore[arg-type]
            assert cap.explanation.strip()
            assert cap.reason.strip()
            assert cap.status in {"supported", "embed_only", "unavailable", "unknown"}


def test_matrix_rows_are_aligned_and_story_first():
    from tests.conftest import make_settings

    settings = make_settings()
    rows = matrix_rows(settings)
    assert [row["label"] for row in rows] == [
        "Story",
        "Profil",
        "Konten",
        "Daftar penonton",
        "Unduh media",
    ]
    for row in rows:
        assert row["tiktok"].key
        assert row["instagram"].key


def test_capability_matrix_covers_both_platforms():
    from tests.conftest import make_settings

    matrix = capability_matrix(make_settings())
    assert [entry["platform"] for entry in matrix] == ["tiktok", "instagram"]
