from __future__ import annotations

import pytest

from app.core import errors
from app.services.url_analyzer import analyze_url


@pytest.mark.parametrize(
    ("raw", "platform", "kind", "canonical"),
    [
        (
            "https://www.tiktok.com/@demo",
            "tiktok",
            "profile",
            "https://www.tiktok.com/@demo",
        ),
        (
            "www.tiktok.com/@demo/",
            "tiktok",
            "profile",
            "https://www.tiktok.com/@demo",
        ),
        (
            "https://tiktok.com/@demo/video/7711003081445510430?is_from_webapp=1",
            "tiktok",
            "video",
            "https://www.tiktok.com/@demo/video/7711003081445510430",
        ),
        (
            "https://m.tiktok.com/@demo/photo/7711003081445510430",
            "tiktok",
            "photo",
            "https://www.tiktok.com/@demo/photo/7711003081445510430",
        ),
        (
            "https://www.tiktok.com/@demo/story/7711003081445510430",
            "tiktok",
            "story",
            "https://www.tiktok.com/@demo/story/7711003081445510430",
        ),
        (
            "https://www.instagram.com/natgeo/",
            "instagram",
            "profile",
            "https://www.instagram.com/natgeo/",
        ),
        (
            "https://instagram.com/p/CabcDEF_12/?igsh=tracking",
            "instagram",
            "post",
            "https://www.instagram.com/p/CabcDEF_12/",
        ),
        (
            "https://www.instagram.com/reel/CabcDEF_12/",
            "instagram",
            "reel",
            "https://www.instagram.com/reel/CabcDEF_12/",
        ),
        (
            "https://www.instagram.com/reels/CabcDEF_12/",
            "instagram",
            "reel",
            "https://www.instagram.com/reel/CabcDEF_12/",
        ),
        (
            "https://www.instagram.com/stories/natgeo/1795383141000001/",
            "instagram",
            "story",
            "https://www.instagram.com/stories/natgeo/1795383141000001/",
        ),
        (
            "https://www.tiktok.com./@demo",
            "tiktok",
            "profile",
            "https://www.tiktok.com/@demo",
        ),
        (
            "HTTPS://WWW.TIKTOK.COM/@demo",
            "tiktok",
            "profile",
            "https://www.tiktok.com/@demo",
        ),
    ],
)
def test_valid_urls(raw, platform, kind, canonical):
    ref = analyze_url(raw)
    assert ref.platform == platform
    assert ref.kind == kind
    assert ref.canonical_url == canonical
    assert "?" not in ref.canonical_url
    assert "#" not in ref.canonical_url


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", errors.INVALID_INPUT),
        ("   ", errors.INVALID_INPUT),
        ("not a url", errors.INVALID_INPUT),
        ("https://www.tiktok.com", errors.UNSUPPORTED_RESOURCE),
        ("https://www.tiktok.com/", errors.UNSUPPORTED_RESOURCE),
        ("http://www.tiktok.com/@demo", errors.INVALID_INPUT),
        ("ftp://www.tiktok.com/@demo", errors.INVALID_INPUT),
        ("https://user:pass@www.tiktok.com/@demo", errors.INVALID_INPUT),
        ("https://www.tiktok.com:8443/@demo", errors.INVALID_INPUT),
        ("https://127.0.0.1/@demo", errors.INVALID_INPUT),
        ("https://[::1]/@demo", errors.INVALID_INPUT),
        ("https://www.tiktok.com.evil.com/@demo", errors.UNSUPPORTED_PLATFORM),
        ("https://evil.com/@demo", errors.UNSUPPORTED_PLATFORM),
        ("https://tiktok.com@evil.com/@demo", errors.INVALID_INPUT),
        ("https://www.tiktok.com/%40demo", errors.INVALID_INPUT),
        ("https://www.tiktok.com/@demo/../video/7711003081445510430", errors.INVALID_INPUT),
        ("https://www.tiktok.com/@demo/video/abc", errors.INVALID_INPUT),
        ("https://www.tiktok.com/@demo/video/123", errors.INVALID_INPUT),
        ("https://www.tiktok.com/@demo/live", errors.UNSUPPORTED_RESOURCE),
        ("https://www.tiktok.com/t/ZM123abc/", errors.UNSUPPORTED_RESOURCE),
        ("https://vm.tiktok.com/ZM123abc/", errors.UNSUPPORTED_RESOURCE),
        ("https://vt.tiktok.com/ZS123abc/", errors.UNSUPPORTED_RESOURCE),
        ("https://www.tiktok.com/@demo?lang=en", "profile"),
        ("https://www.instagram.com/s/abcDEF/", errors.UNSUPPORTED_RESOURCE),
        ("https://www.instagram.com/share/abcDEF/", errors.UNSUPPORTED_RESOURCE),
        ("https://www.instagram.com/explore/", errors.UNSUPPORTED_RESOURCE),
        ("https://www.instagram.com/p/ab/", errors.INVALID_INPUT),
        ("https://www.instagram.com/stories/natgeo/abc/", errors.INVALID_INPUT),
        ("https://www.instagram.com/stories/natgeo/", errors.UNSUPPORTED_RESOURCE),
        ("https://www.instagram.com/p/CabcDEF_12/extra/", errors.UNSUPPORTED_RESOURCE),
        ("https://evil.com\\@www.tiktok.com/@demo", errors.INVALID_INPUT),
        ("https://www.instagram.com/nat geo/", errors.INVALID_INPUT),
        ("https://www.instagram.com/" + "a" * 40 + "/", errors.INVALID_INPUT),
        ("https://www.tiktok.com/@de\x00mo", errors.INVALID_INPUT),
        ("https://" + "a" * 2100 + ".com/@demo", errors.INVALID_INPUT),
    ],
)
def test_rejected_urls(raw, code):
    if code == "profile":
        assert analyze_url(raw).kind == "profile"
        return
    with pytest.raises(errors.AppError) as excinfo:
        analyze_url(raw)
    assert excinfo.value.code == code


def test_query_and_fragment_are_dropped():
    ref = analyze_url(
        "https://www.tiktok.com/@demo/video/7711003081445510430?utm_source=x#fragment"
    )
    assert ref.canonical_url == "https://www.tiktok.com/@demo/video/7711003081445510430"
    assert ref.content_id == "7711003081445510430"


def test_transparent_error_messages_do_not_echo_input():
    raw = "https://www.tiktok.com/@demo/video/not-an-id"
    with pytest.raises(errors.AppError) as excinfo:
        analyze_url(raw)
    assert "not-an-id" not in excinfo.value.message
    assert "not-an-id" not in (excinfo.value.hint or "")
