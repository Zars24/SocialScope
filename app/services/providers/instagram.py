"""Instagram adapter: official embeds plus StoriesFly for public Stories.

StoriesFly is a metered third-party API. The key stays server-side, every call
is rate-limited to 1 req/s, and a daily unit cap stops runaway spend. Responses
are mapped field-by-field and never persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.core import errors
from app.core.http import fetch_json
from app.core.limits import AsyncIntervalLimiter, DailyUnitCounter
from app.core.settings import Settings
from app.schemas.analysis import StoryBundle, StoryItem
from app.services.cache import TTLCache
from app.services.providers.base import (
    INSTAGRAM_MEDIA_DOMAINS,
    iso_from_epoch,
    safe_iso,
    safe_number,
    safe_text,
    safe_url,
)

_FREE_STATUSES = {400, 402, 429}


class InstagramProvider:
    platform = "instagram"
    name = "StoriesFly"
    source_label = "Instagram embed"

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        interval: AsyncIntervalLimiter,
        counter: DailyUnitCounter,
        cache: TTLCache[StoryBundle],
    ) -> None:
        self._client = client
        self._settings = settings
        self._interval = interval
        self._counter = counter
        self._cache = cache

    @property
    def configured(self) -> bool:
        return self._settings.instagram_configured

    # ---- embed URLs (no network) -------------------------------------------------

    def content_embed_url(self, shortcode: str, kind: str) -> str:
        # Instagram serves one embed path for posts and reels; the canonical
        # shortcode is what matters. No metadata is read from the response.
        return f"https://www.instagram.com/p/{shortcode}/embed/captioned/"

    # ---- Story API ---------------------------------------------------------------

    async def list_stories(self, username: str) -> StoryBundle:
        cleaned = safe_text(username, limit=30)
        if not cleaned:
            raise errors.invalid("Nama akun Instagram tidak valid.")
        if not self.configured:
            raise errors.not_configured("Instagram")

        cache_key = f"ig:list:{cleaned.lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        payload = await self._request(
            "/user/stories",
            {"username": cleaned},
            label="instagram_list",
        )
        user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        stories = payload.get("stories")
        if stories is None and isinstance(payload.get("data"), dict):
            stories = payload["data"].get("stories")
        if stories is None:
            stories = []
        if not isinstance(stories, list):
            raise errors.provider_error(internal="storiesfly_bad_stories")

        items: list[StoryItem] = []
        for node in stories:
            if isinstance(node, dict):
                item = self._item_from_node(node, username=cleaned)
                if item is not None:
                    items.append(item)
        items.sort(key=lambda item: (item.taken_at is None, item.taken_at or 0, item.id))

        bundle = StoryBundle(
            platform="instagram",
            username=cleaned,
            display_name=safe_text(user.get("full_name")),
            avatar_url=safe_url(
                user.get("profile_pic_url") or user.get("avatar_url"),
                INSTAGRAM_MEDIA_DOMAINS,
            ),
            items=items,
            provider_name=self.name,
            source_label=self.source_label,
            fetched_at_iso=self._now(),
            note=(
                "Story diambil dari StoriesFly, provider pihak ketiga. Media dimuat browser "
                "langsung dari CDN Instagram; tautannya sementara dan tidak disimpan."
            ),
        )
        self._cache.set(cache_key, bundle)
        return bundle

    async def get_story(self, username: str | None, story_id: str) -> StoryBundle:
        cleaned = safe_text(username, limit=30)
        if not cleaned:
            raise errors.invalid("Nama akun Instagram pada URL Story tidak valid.")
        if not story_id.isdigit():
            raise errors.invalid("ID Story Instagram tidak valid.")
        if not self.configured:
            raise errors.not_configured("Instagram")

        cache_key = f"ig:item:{story_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        payload = await self._request("/story", {"id": story_id}, label="instagram_item")
        story = payload.get("story") if isinstance(payload.get("story"), dict) else None
        if story is None:
            raise errors.unavailable(
                "Story ini tidak dapat dibaca. Kemungkinan sudah kedaluwarsa.",
                hint="Story hanya aktif sekitar 24 jam. Muat ulang profil untuk Story terbaru.",
            )
        user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        item = self._item_from_node(story, username=cleaned)
        if item is None:
            raise errors.unavailable(
                "Story tidak mengembalikan media yang dapat ditampilkan.",
                hint="Kemungkinan sudah kedaluwarsa. Coba muat ulang profil.",
            )

        bundle = StoryBundle(
            platform="instagram",
            username=cleaned,
            display_name=safe_text(user.get("full_name")),
            avatar_url=safe_url(
                user.get("profile_pic_url") or user.get("avatar_url"),
                INSTAGRAM_MEDIA_DOMAINS,
            ),
            items=[item],
            provider_name=self.name,
            source_label=self.source_label,
            fetched_at_iso=self._now(),
            note="Story aktif melalui server kami. Media dimuat browser langsung dari platform.",
        )
        self._cache.set(cache_key, bundle)
        return bundle

    # ---- request and mapping -----------------------------------------------------

    async def _request(self, path: str, params: dict[str, str], *, label: str) -> dict:
        if not self._settings.storiesfly_api_key:
            raise errors.not_configured("Instagram")

        await self._interval.wait()
        await self._counter.consume(1)
        try:
            status, headers, payload = await fetch_json(
                self._client,
                f"{self._settings.storiesfly_base_url}{path}",
                params=params,
                headers={
                    "Accept": "application/json",
                    "X-Api-Key": self._settings.storiesfly_api_key,
                },
                max_bytes=self._settings.max_json_bytes,
            )
        except errors.AppError:
            # Network/timeout/oversize: no documented charge. Release the reserve.
            await self._counter.refund(1)
            raise
        finally:
            # Keep at least one interval between the response and the next call.
            await self._interval.complete()

        if status == 200:
            if not isinstance(payload, dict):
                raise errors.provider_error(internal=f"{label}_bad_payload")
            return payload

        if status in _FREE_STATUSES or status >= 500:
            await self._counter.refund(1)

        if status == 401:
            raise errors.provider_error(
                "Kredensial provider Story ditolak oleh server.",
                internal=f"{label}_unauthorized",
            )
        if status == 402:
            raise errors.AppError(
                errors.PROVIDER_QUOTA,
                "Kuota provider Story habis.",
                503,
                hint="Provider pihak ketiga menolak karena saldo/kuota habis. Fitur lain tetap berjalan.",
            )
        if status == 403:
            raise errors.unavailable(
                "Provider tidak dapat mengakses akun ini (kemungkinan privat atau dibatasi).",
                hint="SocialScope tidak mengakses akun privat dan tidak mencoba melewati pembatasan.",
            )
        if status == 404:
            raise errors.unavailable(
                "Akun atau Story tidak ditemukan oleh provider.",
                hint="Periksa ejaan username atau buka profil untuk Story yang masih aktif.",
            )
        if status == 429:
            try:
                retry_after = int(headers.get("retry-after", "2"))
            except (TypeError, ValueError):
                retry_after = 2
            raise errors.rate_limited(max(1, retry_after), scope="permintaan ke StoriesFly")
        if status == 400:
            raise errors.provider_error(
                "Provider menolak bentuk permintaan ini.",
                internal=f"{label}_bad_request",
            )
        raise errors.provider_error(internal=f"{label}_http_{status}")

    def _item_from_node(self, node: dict, *, username: str) -> StoryItem | None:
        raw_id = node.get("id")
        item_id = str(raw_id) if raw_id is not None else ""
        if not item_id.isdigit() or not (5 <= len(item_id) <= 25):
            return None

        media_type = str(node.get("media_type") or "").lower()
        if media_type in {"image", "photo"}:
            kind = "photo"
        elif media_type == "video":
            kind = "video"
        else:
            return None

        media_url = safe_url(node.get("media_url"), INSTAGRAM_MEDIA_DOMAINS)
        if media_url is None:
            return None

        taken_at, computed_iso = iso_from_epoch(node.get("taken_at"))
        taken_at_iso = safe_iso(node.get("taken_at_iso")) or computed_iso

        duration = safe_number(node.get("video_duration")) if kind == "video" else None

        permalink = safe_url(node.get("url"), ("instagram.com",))
        if permalink is None or "/stories/" not in permalink:
            permalink = f"https://www.instagram.com/stories/{username}/{item_id}/"

        return StoryItem(
            id=item_id,
            media_type=kind,  # type: ignore[arg-type]
            media_url=media_url,
            thumbnail_url=safe_url(node.get("thumbnail_url"), INSTAGRAM_MEDIA_DOMAINS),
            taken_at=taken_at,
            taken_at_iso=taken_at_iso,
            duration=duration,
            permalink=permalink,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
