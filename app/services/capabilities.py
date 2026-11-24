"""Single source of truth for platform capabilities.

Templates and routes never hardcode a platform limitation. They read these
entries. If a provider is reconfigured or a capability changes, only this module
and the adapter change.
"""

from __future__ import annotations

from app.core.settings import Settings
from app.schemas.analysis import Capability, Platform

PLATFORM_LABEL: dict[str, str] = {"tiktok": "TikTok", "instagram": "Instagram"}

FEATURE_LABEL: dict[str, str] = {
    "story": "Story",
    "profile": "Profil",
    "video": "Video",
    "photo": "Foto",
    "post": "Post",
    "reel": "Reel",
    "viewer_list": "Daftar penonton",
    "download": "Unduh media",
}

STORY_NOTE: dict[str, str] = {
    "tiktok": (
        "Story aktif melalui server kami. Hanya field yang benar-benar dikembalikan. "
        "Provider pihak ketiga dapat memakai sesinya sendiri; kami tidak dapat memverifikasi "
        "daftar penonton kreator."
    ),
    "instagram": (
        "Story aktif melalui server kami. Hanya field yang benar-benar dikembalikan. "
        "Provider pihak ketiga dapat memakai sesinya sendiri; kami tidak dapat memverifikasi "
        "daftar penonton kreator."
    ),
}


def _story(platform: Platform, settings: Settings) -> Capability:
    configured = (
        settings.tiktok_configured if platform == "tiktok" else settings.instagram_configured
    )
    if not configured:
        return Capability(
            key="story",
            label=FEATURE_LABEL["story"],
            status="unavailable",
            mode=None,
            reason="provider_not_configured",
            explanation="Provider Story belum dikonfigurasi di server ini.",
            method=None,
        )
    return Capability(
        key="story",
        label=FEATURE_LABEL["story"],
        status="supported",
        mode="structured",
        reason="third_party_provider",
        explanation=(
            "Story publik aktif dapat dibaca lewat server kami. Data yang ditampilkan "
            "hanya field yang benar-benar dikembalikan, bukan hasil rekonstruksi."
        ),
        method="user_stories",
    )


def _profile(platform: Platform) -> Capability:
    if platform == "tiktok":
        return Capability(
            key="profile",
            label=FEATURE_LABEL["profile"],
            status="embed_only",
            mode="embed",
            reason="creator_profile_embed",
            explanation=(
                "Kartu profil dirender oleh TikTok di iframe resmi. Kami tidak membaca "
                "statistik atau metadata dari dalam embed."
            ),
            method="creator_profile_embed",
        )
    return Capability(
        key="profile",
        label=FEATURE_LABEL["profile"],
        status="unavailable",
        mode=None,
        reason="no_public_profile_embed",
        explanation=(
            "Instagram tidak menyediakan embed profil publik tanpa token. Kami tidak "
            "mengambil halaman profil. Story publik tetap dapat dicoba dari halaman ini."
        ),
        method=None,
    )


def _content(platform: Platform, kind: str) -> Capability:
    if platform == "tiktok":
        return Capability(
            key=kind,
            label=FEATURE_LABEL[kind],
            status="embed_only",
            mode="embed",
            reason="official_embed_player",
            explanation=(
                "Konten dirender oleh TikTok Embed Player. Tidak ada metadata, statistik, "
                "atau media yang disalin ke server kami."
            ),
            method="embed_player",
        )
    return Capability(
        key=kind,
        label=FEATURE_LABEL[kind],
        status="embed_only",
        mode="embed",
        reason="official_instagram_embed",
        explanation=(
            "Konten dirender lewat embed Instagram untuk tujuan penayangan. Kami tidak "
            "mengekstrak atau menyimpan metadata dari embed."
        ),
        method="instagram_embed",
    )


def _common_unavailable(key: str, explanation: str, reason: str) -> Capability:
    return Capability(
        key=key,
        label=FEATURE_LABEL[key],
        status="unavailable",
        mode=None,
        reason=reason,
        explanation=explanation,
        method=None,
    )


def capabilities_for(platform: Platform, settings: Settings) -> list[Capability]:
    items: list[Capability] = [_story(platform, settings), _profile(platform)]
    if platform == "tiktok":
        items.append(_content(platform, "video"))
        items.append(_content(platform, "photo"))
    else:
        items.append(_content(platform, "post"))
        items.append(_content(platform, "reel"))
    items.append(
        _common_unavailable(
            "viewer_list",
            "Daftar penonton hanya dapat dilihat oleh pemilik akun. SocialScope tidak "
            "memiliki akses ke sana dan tidak menjanjikan Anda tidak tercatat.",
            "owner_only",
        )
    )
    items.append(
        _common_unavailable(
            "download",
            "Media tidak diunduh, disimpan, atau dihosting ulang oleh SocialScope. "
            "Browser memuatnya langsung dari CDN platform.",
            "not_permitted",
        )
    )
    return items


def story_capability(platform: Platform, settings: Settings) -> Capability:
    return _story(platform, settings)


def capability_matrix(settings: Settings) -> list[dict[str, object]]:
    rows = []
    for platform in ("tiktok", "instagram"):
        rows.append(
            {
                "platform": platform,
                "label": PLATFORM_LABEL[platform],
                "capabilities": capabilities_for(platform, settings),  # type: ignore[arg-type]
            }
        )
    return rows


def matrix_rows(settings: Settings) -> list[dict[str, object]]:
    """Aligned rows for the homepage summary table."""
    tiktok = {cap.key: cap for cap in capabilities_for("tiktok", settings)}
    instagram = {cap.key: cap for cap in capabilities_for("instagram", settings)}
    return [
        {
            "label": "Story",
            "note": "modul utama",
            "tiktok": tiktok["story"],
            "instagram": instagram["story"],
        },
        {"label": "Profil", "note": "", "tiktok": tiktok["profile"], "instagram": instagram["profile"]},
        {
            "label": "Konten",
            "note": "video / foto · post / reel",
            "tiktok": tiktok["video"],
            "instagram": instagram["post"],
        },
        {
            "label": "Daftar penonton",
            "note": "",
            "tiktok": tiktok["viewer_list"],
            "instagram": instagram["viewer_list"],
        },
        {
            "label": "Unduh media",
            "note": "",
            "tiktok": tiktok["download"],
            "instagram": instagram["download"],
        },
    ]
