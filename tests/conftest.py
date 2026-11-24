"""Shared test helpers. No test performs a real network request."""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.settings import Settings
from app.schemas.analysis import StoryBundle, StoryItem


def make_settings(**overrides) -> Settings:
    base = Settings()
    values = {
        "app_env": "test",
        "debug": False,
        "storiesfly_api_key": "test-key",
        "storiesfly_enabled": True,
        "storiesfly_daily_unit_cap": 10,
        "tikwm_enabled": True,
        "per_ip_per_minute": 100,
        "global_per_minute": 1000,
    }
    values.update(overrides)
    return replace(base, **values)


def tiktok_bundle(username: str = "demo", *, empty: bool = False) -> StoryBundle:
    items = []
    if not empty:
        items = [
            StoryItem(
                id="7700000000000000001",
                media_type="video",
                media_url="https://v45.tiktokcdn-eu.com/video.mp4?token=1",
                thumbnail_url="https://p16-common-sign.tiktokcdn-eu.com/cover.jpg",
                taken_at=1795391000,
                taken_at_iso="2026-11-23T00:10:00Z",
                duration=16,
                permalink=f"https://www.tiktok.com/@{username}/story/7700000000000000001",
            ),
            StoryItem(
                id="7700000000000000002",
                media_type="video",
                media_url="https://v45.tiktokcdn-eu.com/video2.mp4",
                thumbnail_url=None,
                taken_at=1795392000,
                taken_at_iso="2026-11-23T00:20:00Z",
                duration=8,
                permalink=f"https://www.tiktok.com/@{username}/story/7700000000000000002",
            ),
        ]
    return StoryBundle(
        platform="tiktok",
        username=username,
        display_name="Demo Account",
        avatar_url="https://p19-common-sign.tiktokcdn-eu.com/avatar.jpg",
        items=items,
        provider_name="—",
        source_label="TikTok embed",
        fetched_at_iso="2026-11-23T00:30:00Z",
        note="test fixture",
    )


def instagram_bundle(username: str = "demo", *, empty: bool = False) -> StoryBundle:
    items = []
    if not empty:
        items = [
            StoryItem(
                id="1795383141000001",
                media_type="photo",
                media_url="https://scontent-lax3-1.cdninstagram.com/story.jpg?oe=1",
                thumbnail_url="https://scontent-lax3-1.cdninstagram.com/thumb.jpg",
                taken_at=1795383141,
                taken_at_iso="2026-11-22T21:32:21Z",
                duration=None,
                permalink=f"https://www.instagram.com/stories/{username}/1795383141000001/",
            )
        ]
    return StoryBundle(
        platform="instagram",
        username=username,
        display_name="Demo IG",
        avatar_url=None,
        items=items,
        provider_name="—",
        source_label="Instagram embed",
        fetched_at_iso="2026-11-23T00:30:00Z",
        note="test fixture",
    )


class FakeProvider:
    def __init__(self, platform: str, bundle_factory, error=None):
        self.platform = platform
        self.name = "—"
        self.source_label = "TikTok embed" if platform == "tiktok" else "Instagram embed"
        self.configured = True
        self._bundle_factory = bundle_factory
        self.error = error
        self.calls: list[tuple] = []

    def profile_embed_url(self, username: str) -> str:
        return f"https://www.tiktok.com/embed/@{username}"

    def content_embed_url(self, content_id: str, kind: str = "") -> str:
        if self.platform == "tiktok":
            return f"https://www.tiktok.com/player/v1/{content_id}"
        return f"https://www.instagram.com/p/{content_id}/embed/captioned/"

    async def list_stories(self, username: str) -> StoryBundle:
        self.calls.append(("list", username))
        if self.error is not None:
            raise self.error
        return self._bundle_factory(username)

    async def get_story(self, username: str | None, story_id: str) -> StoryBundle:
        self.calls.append(("item", username, story_id))
        if self.error is not None:
            raise self.error
        return self._bundle_factory(username or "demo")


@dataclass
class FakeProviders:
    tiktok: FakeProvider
    instagram: FakeProvider

    def for_platform(self, platform: str):
        return self.tiktok if platform == "tiktok" else self.instagram


def fake_providers(*, tiktok_error=None, instagram_error=None, empty: bool = False) -> FakeProviders:
    return FakeProviders(
        tiktok=FakeProvider(
            "tiktok", lambda username: tiktok_bundle(username, empty=empty), tiktok_error
        ),
        instagram=FakeProvider(
            "instagram", lambda username: instagram_bundle(username, empty=empty), instagram_error
        ),
    )
