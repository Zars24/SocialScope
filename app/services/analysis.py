"""Analysis orchestration: validated resource -> capabilities + real content.

Embeds are constructed locally. Story data is only rendered when an adapter
returned it; nothing is estimated, blurred, or reconstructed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core import errors
from app.core.settings import Settings
from app.schemas.analysis import (
    AnalysisResult,
    EmbedView,
    ResourceRef,
    StoryBundle,
    StoryState,
)
from app.services.capabilities import STORY_NOTE, capabilities_for
from app.services.providers.registry import Providers

_MEDIA_NOTICE = (
    "Media dimuat langsung oleh browser Anda dari CDN platform. CDN tersebut melihat "
    "permintaan media beserta IP dan user agent browser, sama seperti saat Anda membuka "
    "konten di platform."
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _embed_for(ref: ResourceRef, providers: Providers) -> EmbedView | None:
    if ref.platform == "tiktok":
        provider = providers.tiktok
        if ref.kind == "profile" and ref.username:
            return EmbedView(
                kind="profile",
                url=provider.profile_embed_url(ref.username),
                title=f"@{ref.username}",
                source_label="TikTok Creator Profile Embed",
                open_url=ref.canonical_url,
                aspect_ratio="9 / 16",
                max_width=340,
                note="Dirender oleh TikTok. SocialScope tidak membaca isi embed.",
            )
        if ref.kind in {"video", "photo"} and ref.content_id:
            return EmbedView(
                kind=ref.kind,
                url=provider.content_embed_url(ref.content_id),
                title="Konten TikTok",
                source_label="TikTok Embed Player",
                open_url=ref.canonical_url,
                aspect_ratio="9 / 16",
                max_width=340,
                note="Player resmi TikTok. Tidak ada metadata yang diambil server kami.",
            )
        return None

    if ref.platform == "instagram":
        if ref.kind in {"post", "reel"} and ref.content_id:
            return EmbedView(
                kind=ref.kind,
                url=providers.instagram.content_embed_url(ref.content_id, ref.kind),
                title="Post Instagram",
                source_label="Instagram Embed",
                open_url=ref.canonical_url,
                aspect_ratio="4 / 5",
                max_width=440,
                note="Embed Instagram untuk penayangan. Tidak ada metadata yang diekstrak.",
            )
        return None

    return None


def _state_for_error(exc: errors.AppError) -> StoryState:
    if exc.code == errors.PROVIDER_NOT_CONFIGURED:
        return "not_configured"
    if exc.code == errors.UNAVAILABLE:
        return "unavailable"
    return "error"


async def _load_story(ref: ResourceRef, providers: Providers) -> tuple[StoryBundle | None, StoryState | None, str | None]:
    provider = providers.for_platform(ref.platform)
    try:
        if ref.kind == "story":
            if not ref.content_id:
                raise errors.invalid("ID Story tidak ditemukan pada URL.")
            bundle = await provider.get_story(ref.username, ref.content_id)
        else:
            if not ref.username:
                raise errors.invalid("Nama akun tidak ditemukan pada URL.")
            bundle = await provider.list_stories(ref.username)
    except errors.AppError as exc:
        if ref.kind == "story":
            # A single-story request has no secondary content to show.
            raise
        return None, _state_for_error(exc), exc.message

    if not bundle.items:
        return bundle, "empty", "Provider mengembalikan 0 Story aktif pada saat pengambilan."
    return bundle, "ok", None


async def analyze(ref: ResourceRef, providers: Providers, settings: Settings) -> AnalysisResult:
    fetched_at = _now()
    capabilities = capabilities_for(ref.platform, settings)  # type: ignore[arg-type]
    embed = _embed_for(ref, providers)

    # Story lookups are metered. Only profile and single-Story requests trigger
    # them; opening a post or video must not spend an Instagram unit.
    if ref.kind in {"profile", "story"}:
        story, story_state, story_message = await _load_story(ref, providers)
        notices: list[str] = [STORY_NOTE[ref.platform], _MEDIA_NOTICE]
    else:
        story, story_state, story_message = None, None, None
        notices = [_MEDIA_NOTICE]
    if story_state == "empty":
        notices.append(
            "Daftar kosong adalah jawaban yang valid. Story bersifat sementara; tidak ada "
            "konten yang diisi atau direkonstruksi."
        )
    if story_state in {"error", "unavailable"}:
        notices.append(
            "Kegagalan provider tidak membuktikan akun privat atau dihapus. Kami tidak "
            "menyimpulkan status akun dari error."
        )
    if story_state == "not_configured":
        notices.append(
            "Fitur Story bergantung pada konfigurasi provider di server. Bagian lain dari "
            "SocialScope tetap berfungsi."
        )

    if embed and story_state == "ok":
        mode = "mixed"
    elif embed:
        mode = "embed"
    elif story_state == "ok":
        mode = "structured"
    else:
        mode = "unavailable"

    if mode == "mixed":
        source_label = f"{embed.source_label} · {story.source_label if story else ''}".strip(" ·")
    elif embed:
        source_label = embed.source_label
    elif story:
        source_label = story.source_label
    else:
        source_label = "Tidak ada sumber yang mengembalikan konten"

    if story and story.items:
        notices.insert(
            0,
            "Story adalah data terstruktur, bukan embed. Setiap field berasal dari respons "
            "provider dan tautan medianya sementara.",
        )

    # Keep the capability order stable but make the requested feature explicit.
    requested = {
        "story": "story",
        "profile": "profile",
        "video": "video",
        "photo": "photo",
        "post": "post",
        "reel": "reel",
    }.get(ref.kind)
    if requested:
        capabilities.sort(key=lambda cap: 0 if cap.key == requested else 1)

    return AnalysisResult(
        resource=ref,
        mode=mode,
        source_label=source_label,
        capabilities=capabilities,
        embed=embed,
        story=story,
        story_state=story_state,
        story_message=story_message,
        notices=notices,
        fetched_at_iso=fetched_at,
    )
