"""Provider registry. Adding a platform means adding an adapter here."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.limits import AsyncIntervalLimiter, DailyUnitCounter
from app.core.settings import Settings
from app.schemas.analysis import Platform
from app.services.cache import TTLCache
from app.services.providers.instagram import InstagramProvider
from app.services.providers.tiktok import TikTokProvider


@dataclass
class Providers:
    tiktok: TikTokProvider
    instagram: InstagramProvider

    def for_platform(self, platform: Platform):
        return self.tiktok if platform == "tiktok" else self.instagram


def build_providers(client: httpx.AsyncClient, settings: Settings) -> Providers:
    tiktok = TikTokProvider(
        client=client,
        settings=settings,
        interval=AsyncIntervalLimiter(1.05),
        cache=TTLCache(ttl_seconds=settings.story_cache_ttl, max_entries=settings.story_cache_entries),
    )
    instagram = InstagramProvider(
        client=client,
        settings=settings,
        interval=AsyncIntervalLimiter(1.05),
        counter=DailyUnitCounter(settings.storiesfly_daily_unit_cap),
        cache=TTLCache(ttl_seconds=settings.story_cache_ttl, max_entries=settings.story_cache_entries),
    )
    return Providers(tiktok=tiktok, instagram=instagram)
