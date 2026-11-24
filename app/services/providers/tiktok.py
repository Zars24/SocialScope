"""TikTok adapter: official embeds plus a third-party Story provider.

- Embed URLs are constructed locally; no fetch of the submitted URL.
- Story data comes from TikWM's public JSON API, rate-limited to 1 req/s.
- Media URLs must resolve to a TikTok CDN host before they reach a template.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.core import errors
from app.core.http import fetch_json
from app.core.limits import AsyncIntervalLimiter
from app.core.settings import Settings
from app.schemas.analysis import StoryBundle, StoryItem
from app.services.cache import TTLCache
from app.services.providers.base import (
    TIKTOK_MEDIA_DOMAINS,
    iso_from_epoch,
    safe_iso,
    safe_number,
    safe_text,
    safe_url,
    safe_username,
)


class TikTokProvider:
    platform = "tiktok"
    name = "TikWM"
    source_label = "TikTok embed"

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        interval: AsyncIntervalLimiter,
        cache: TTLCache[StoryBundle],
    ) -> None:
        self._client = client
        self._settings = settings
        self._interval = interval
        self._cache = cache

    @property
    def configured(self) -> bool:
        return self._settings.tiktok_configured

    # ---- embed URLs (no network) -------------------------------------------------

    def profile_embed_url(self, username: str) -> str:
        return f"https://www.tiktok.com/embed/@{username}"

    def content_embed_url(self, content_id: str) -> str:
        return f"https://www.tiktok.com/player/v1/{content_id}?autoplay=0&loop=0"

    # ---- Story API ---------------------------------------------------------------

    async def list_stories(self, username: str) -> StoryBundle:
        username = safe_username(username) or ""
        if not username:
            raise errors.invalid("Nama akun TikTok tidak valid.")
        if not self.configured:
            raise errors.not_configured("TikTok")

        cache_key = f"tt:list:{username.lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        await self._interval.wait()
        try:
            status, _headers, payload = await fetch_json(
                self._client,
                f"{self._settings.tikwm_base_url}/api/user/story",
                params={"unique_id": username},
                headers={"Accept": "application/json"},
                max_bytes=self._settings.max_json_bytes,
            )
        finally:
            await self._interval.complete()
        if status != 200 or not isinstance(payload, dict):
            raise errors.provider_error(internal=f"tikwm_http_{status}")

        data = payload.get("data")
        code = payload.get("code")
        if code != 0:
            self._raise_for_code(payload, username=username, item=False)
        if not isinstance(data, dict):
            raise errors.provider_error(internal="tikwm_missing_data")

        videos = data.get("videos")
        if videos is None:
            videos = []
        if not isinstance(videos, list):
            raise errors.provider_error(internal="tikwm_bad_videos")

        items: list[StoryItem] = []
        display_name: str | None = None
        avatar_url: str | None = None
        for node in videos:
            if not isinstance(node, dict):
                continue
            parsed = self._items_from_node(node, username)
            if not parsed:
                # Do not borrow identity metadata from an item we refused to render.
                continue
            items.extend(parsed)
            author = node.get("author")
            if isinstance(author, dict):
                display_name = display_name or safe_text(author.get("nickname"))
                avatar_url = avatar_url or safe_url(author.get("avatar"), TIKTOK_MEDIA_DOMAINS)

        items = self._dedupe_and_sort(items)
        bundle = StoryBundle(
            platform="tiktok",
            username=username,
            display_name=display_name,
            avatar_url=avatar_url,
            items=items,
            provider_name=self.name,
            source_label=self.source_label,
            fetched_at_iso=self._now(),
            note=(
                "Story aktif melalui server kami. Media dimuat browser langsung dari platform."
            ),
        )
        self._cache.set(cache_key, bundle)
        return bundle

    async def get_story(self, username: str | None, story_id: str) -> StoryBundle:
        username = safe_username(username)
        if not username:
            raise errors.invalid("Nama akun TikTok pada URL Story tidak valid.")
        if not story_id.isdigit():
            raise errors.invalid("ID Story TikTok tidak valid.")
        if not self.configured:
            raise errors.not_configured("TikTok")

        cache_key = f"tt:item:{story_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        canonical = f"https://www.tiktok.com/@{username}/story/{story_id}"
        await self._interval.wait()
        try:
            status, _headers, payload = await fetch_json(
                self._client,
                f"{self._settings.tikwm_base_url}/api/",
                params={"url": canonical},
                headers={"Accept": "application/json"},
                max_bytes=self._settings.max_json_bytes,
            )
        finally:
            await self._interval.complete()
        if status != 200 or not isinstance(payload, dict):
            raise errors.provider_error(internal=f"tikwm_http_{status}")

        code = payload.get("code")
        if code != 0:
            self._raise_for_code(payload, username=username, item=True)

        data = payload.get("data")
        if not isinstance(data, dict):
            raise errors.unavailable(
                "Story ini tidak dapat dibaca. Kemungkinan sudah kedaluwarsa.",
                hint="Story hanya aktif sekitar 24 jam. Coba muat ulang profil untuk Story terbaru.",
            )

        is_story = data.get("is_story")
        if is_story is not None and not is_story:
            raise errors.unavailable(
                "Konten ini bukan Story aktif.",
                hint="Gunakan URL Story yang masih aktif atau muat ulang profil.",
            )

        items = self._items_from_node(data, username)
        if not items:
            raise errors.unavailable(
                "Story tidak mengembalikan media yang dapat ditampilkan.",
                hint="Kemungkinan sudah kedaluwarsa. Coba muat ulang profil.",
            )

        author = data.get("author")
        display_name = None
        avatar_url = None
        if isinstance(author, dict):
            display_name = safe_text(author.get("nickname"))
            avatar_url = safe_url(author.get("avatar"), TIKTOK_MEDIA_DOMAINS)

        bundle = StoryBundle(
            platform="tiktok",
            username=username,
            display_name=display_name,
            avatar_url=avatar_url,
            items=items,
            provider_name=self.name,
            source_label=self.source_label,
            fetched_at_iso=self._now(),
            note="Story aktif melalui server kami. Media dimuat browser langsung dari platform.",
        )
        self._cache.set(cache_key, bundle)
        return bundle

    # ---- parsing -----------------------------------------------------------------

    def _items_from_node(self, node: dict, username: str) -> list[StoryItem]:
        raw_id = node.get("video_id") or node.get("id") or node.get("aweme_id")
        item_id = str(raw_id) if raw_id is not None else ""
        if not item_id.isdigit() or not (15 <= len(item_id) <= 25):
            return []

        taken_at, taken_at_iso = iso_from_epoch(node.get("create_time"))
        if taken_at_iso is None:
            taken_at_iso = safe_iso(node.get("create_time_iso"))

        duration = safe_number(node.get("duration"))
        thumbnail = safe_url(
            node.get("origin_cover") or node.get("cover") or node.get("ai_dynamic_cover"),
            TIKTOK_MEDIA_DOMAINS,
        )
        permalink = f"https://www.tiktok.com/@{username}/story/{item_id}"

        images = node.get("images")
        items: list[StoryItem] = []
        if isinstance(images, list) and images:
            for index, image in enumerate(images[:20]):
                media_url = safe_url(image, TIKTOK_MEDIA_DOMAINS)
                if media_url is None:
                    continue
                items.append(
                    StoryItem(
                        id=f"{item_id}-{index}",
                        media_type="photo",
                        media_url=media_url,
                        thumbnail_url=thumbnail,
                        taken_at=taken_at,
                        taken_at_iso=taken_at_iso,
                        duration=None,
                        permalink=permalink,
                    )
                )
            if items:
                return items

        media_url = safe_url(node.get("play") or node.get("wmplay"), TIKTOK_MEDIA_DOMAINS)
        if media_url is None:
            return []
        items.append(
            StoryItem(
                id=item_id,
                media_type="video",
                media_url=media_url,
                thumbnail_url=thumbnail,
                taken_at=taken_at,
                taken_at_iso=taken_at_iso,
                duration=duration,
                permalink=permalink,
            )
        )
        return items

    @staticmethod
    def _dedupe_and_sort(items: list[StoryItem]) -> list[StoryItem]:
        seen: set[str] = set()
        unique: list[StoryItem] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            unique.append(item)
        unique.sort(key=lambda item: (item.taken_at is None, item.taken_at or 0, item.id))
        return unique

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _raise_for_code(self, payload: dict, *, username: str, item: bool) -> None:
        message = str(payload.get("msg") or "").lower()
        if "limit" in message:
            raise errors.rate_limited(2, scope="permintaan ke TikWM")
        if "parsing" in message or "not found" in message or "not exist" in message:
            if item:
                raise errors.unavailable(
                    "Story tidak ditemukan atau sudah kedaluwarsa.",
                    hint="Story hanya aktif sekitar 24 jam. Muat ulang profil untuk Story terbaru.",
                )
            raise errors.unavailable(
                f"TikWM tidak menemukan Story aktif untuk @{username}.",
                hint="Akun mungkin tidak memiliki Story aktif, atau nama akunnya berubah.",
            )
        raise errors.provider_error(internal="tikwm_code")
