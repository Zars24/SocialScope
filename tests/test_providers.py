from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core import errors
from app.core.limits import AsyncIntervalLimiter, DailyUnitCounter
from app.services.cache import TTLCache
from app.services.providers.instagram import InstagramProvider
from app.services.providers.tiktok import TikTokProvider
from tests.conftest import make_settings


def run(coro):
    return asyncio.run(coro)


def tikwm_item(**overrides):
    item = {
        "video_id": "7700000000000000001",
        "create_time": 1795392000,
        "duration": 16,
        "play": "https://v45.tiktokcdn-eu.com/video.mp4?token=1",
        "wmplay": "https://v45.tiktokcdn-eu.com/wm.mp4",
        "origin_cover": "https://p16-common-sign.tiktokcdn-eu.com/cover.jpg",
        "cover": "https://p16-common-sign.tiktokcdn-eu.com/cover2.jpg",
        "images": [],
        "author": {
            "unique_id": "demo",
            "nickname": "Demo Account",
            "avatar": "https://p19-common-sign.tiktokcdn-eu.com/avatar.jpg",
        },
    }
    item.update(overrides)
    return item


def make_tiktok(handler, *, settings=None, cache=None):
    settings = settings or make_settings()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    provider = TikTokProvider(
        client=client,
        settings=settings,
        interval=AsyncIntervalLimiter(0),
        cache=cache or TTLCache(ttl_seconds=60, max_entries=8),
    )
    return provider, client


def make_instagram(handler, *, settings=None, counter=None, cache=None):
    settings = settings or make_settings()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    provider = InstagramProvider(
        client=client,
        settings=settings,
        interval=AsyncIntervalLimiter(0),
        counter=counter or DailyUnitCounter(10),
        cache=cache or TTLCache(ttl_seconds=60, max_entries=8),
    )
    return provider, client


# ---- TikTok ----------------------------------------------------------------


def test_tiktok_list_parses_and_sorts_real_fields():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.url.path == "/api/user/story"
        assert request.url.params["unique_id"] == "demo"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "success",
                "data": {
                    "cursor": "1",
                    "hasMore": False,
                    "videos": [
                        tikwm_item(create_time=1795393000),
                        tikwm_item(video_id="7700000000000000002", create_time=1795392000),
                    ],
                },
            },
        )

    async def scenario():
        provider, client = make_tiktok(handler)
        bundle = await provider.list_stories("demo")
        await client.aclose()
        return bundle

    bundle = run(scenario())
    assert bundle.provider_name == "TikWM"
    assert bundle.source_label == "TikTok embed"
    assert bundle.display_name == "Demo Account"
    assert bundle.avatar_url.startswith("https://p19-common-sign.tiktokcdn-eu.com/")
    assert [item.id for item in bundle.items] == [
        "7700000000000000002",
        "7700000000000000001",
    ]
    assert all(item.media_type == "video" for item in bundle.items)
    assert bundle.items[0].duration == 16
    assert len(calls) == 1


def test_tiktok_list_drops_media_from_unexpected_hosts():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "videos": [
                        tikwm_item(play="https://evil.example/media.mp4"),
                        tikwm_item(
                            video_id="7700000000000000002",
                            play="http://v45.tiktokcdn-eu.com/insecure.mp4",
                        ),
                        tikwm_item(
                            video_id="7700000000000000003",
                            author={"nickname": "X", "avatar": "https://evil.example/a.jpg"},
                        ),
                    ]
                },
            },
        )

    async def scenario():
        provider, client = make_tiktok(handler)
        bundle = await provider.list_stories("demo")
        await client.aclose()
        return bundle

    bundle = run(scenario())
    assert [item.id for item in bundle.items] == ["7700000000000000003"]
    assert bundle.avatar_url is None


def test_tiktok_photo_images_are_real_items():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "videos": [
                        tikwm_item(
                            images=[
                                "https://p16-common-sign.tiktokcdn-eu.com/1.jpg",
                                "https://p16-common-sign.tiktokcdn-eu.com/2.jpg",
                                "https://evil.example/3.jpg",
                            ]
                        )
                    ]
                },
            },
        )

    async def scenario():
        provider, client = make_tiktok(handler)
        bundle = await provider.list_stories("demo")
        await client.aclose()
        return bundle

    bundle = run(scenario())
    assert [item.media_type for item in bundle.items] == ["photo", "photo"]
    assert [item.id for item in bundle.items] == [
        "7700000000000000001-0",
        "7700000000000000001-1",
    ]
    assert all(item.duration is None for item in bundle.items)


def test_tiktok_detail_builds_canonical_url_and_marks_story():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/"
        assert (
            request.url.params["url"]
            == "https://www.tiktok.com/@demo/story/7700000000000000001"
        )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "id": "7700000000000000001",
                    "video_id": "7700000000000000001",
                    "is_story": True,
                    "create_time": 1795392000,
                    "duration": 16,
                    "play": "https://v45.tiktokcdn-eu.com/video.mp4",
                    "origin_cover": "https://p16-common-sign.tiktokcdn-eu.com/cover.jpg",
                    "author": {"nickname": "Demo Account"},
                },
            },
        )

    async def scenario():
        provider, client = make_tiktok(handler)
        bundle = await provider.get_story("demo", "7700000000000000001")
        await client.aclose()
        return bundle

    bundle = run(scenario())
    assert bundle.username == "demo"
    assert bundle.count == 1
    assert bundle.items[0].permalink == (
        "https://www.tiktok.com/@demo/story/7700000000000000001"
    )


def test_tiktok_non_story_payload_is_not_presented_as_story():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "id": "7700000000000000001",
                    "is_story": False,
                    "play": "https://v45.tiktokcdn-eu.com/video.mp4",
                },
            },
        )

    async def scenario():
        provider, client = make_tiktok(handler)
        await provider.get_story("demo", "7700000000000000001")
        await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.UNAVAILABLE


def test_tiktok_expired_story_maps_to_unavailable():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": -1, "msg": "Url parsing is failed! Please check url."}
        )

    async def scenario():
        provider, client = make_tiktok(handler)
        await provider.get_story("demo", "7700000000000000001")
        await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.UNAVAILABLE
    assert "parsing" not in excinfo.value.message.lower()


def test_tiktok_rate_limit_message_maps_to_429():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": -1, "msg": "Free Api Limit: 1 request/second."})

    async def scenario():
        provider, client = make_tiktok(handler)
        await provider.list_stories("demo")
        await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.RATE_LIMITED
    assert excinfo.value.status_code == 429


def test_tiktok_list_is_cached():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"code": 0, "data": {"videos": [tikwm_item()]}})

    async def scenario():
        provider, client = make_tiktok(handler)
        first = await provider.list_stories("demo")
        second = await provider.list_stories("demo")
        await client.aclose()
        return first, second

    first, second = run(scenario())
    assert first is second
    assert calls == 1


# ---- Instagram -------------------------------------------------------------


def storiesfly_story(**overrides):
    story = {
        "id": "1795383141000001",
        "media_type": "photo",
        "media_url": "https://scontent-lax3-1.cdninstagram.com/story.jpg?oe=1",
        "thumbnail_url": "https://scontent-lax3-1.cdninstagram.com/thumb.jpg",
        "taken_at": 1795383141,
        "taken_at_iso": "2026-11-22T21:32:21.000Z",
        "url": "https://www.instagram.com/stories/demo/1795383141000001/",
        "video_duration": None,
    }
    story.update(overrides)
    return story


def test_instagram_list_parses_fields_and_sends_key():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/user/stories"
        assert request.url.params["username"] == "demo"
        assert request.headers["x-api-key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "user": {"id": "1", "username": "demo", "full_name": "Demo IG"},
                "stories": [
                    storiesfly_story(
                        id="1795383141000002",
                        media_type="video",
                        media_url="https://scontent-lax3-1.cdninstagram.com/v.mp4",
                        taken_at=1795383200,
                        video_duration=33.5,
                    ),
                    storiesfly_story(),
                ],
            },
        )

    async def scenario():
        provider, client = make_instagram(handler)
        bundle = await provider.list_stories("demo")
        await client.aclose()
        return bundle

    bundle = run(scenario())
    assert bundle.display_name == "Demo IG"
    assert [item.media_type for item in bundle.items] == ["photo", "video"]
    assert bundle.items[1].duration == 33.5
    assert bundle.items[0].duration is None
    assert bundle.items[0].taken_at_iso == "2026-11-22T21:32:21.000Z"
    assert bundle.items[0].media_url.startswith("https://scontent-lax3-1.cdninstagram.com/")


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, errors.PROVIDER_ERROR),
        (401, errors.PROVIDER_ERROR),
        (402, errors.PROVIDER_QUOTA),
        (403, errors.UNAVAILABLE),
        (404, errors.UNAVAILABLE),
        (429, errors.RATE_LIMITED),
        (500, errors.PROVIDER_ERROR),
    ],
)
def test_instagram_error_taxonomy(status, code):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"code": "error"},
            headers={"content-type": "application/json", "retry-after": "1"},
        )

    async def scenario():
        provider, client = make_instagram(handler)
        try:
            await provider.list_stories("demo")
        finally:
            await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == code


def test_instagram_429_uses_retry_after():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"code": "rate_limited"},
            headers={"content-type": "application/json", "retry-after": "7"},
        )

    async def scenario():
        provider, client = make_instagram(handler)
        try:
            await provider.list_stories("demo")
        finally:
            await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.retry_after == 7


def test_instagram_5xx_is_refunded_and_429_is_free():
    counter = DailyUnitCounter(10)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "upstream_unavailable"})

    async def scenario():
        provider, client = make_instagram(handler, counter=counter)
        try:
            try:
                await provider.list_stories("demo")
            except errors.AppError:
                pass
        finally:
            await client.aclose()
        return await counter.snapshot()

    snapshot = run(scenario())
    assert snapshot["used"] == 0


def test_instagram_404_is_charged():
    counter = DailyUnitCounter(10)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "not_found"})

    async def scenario():
        provider, client = make_instagram(handler, counter=counter)
        try:
            try:
                await provider.list_stories("demo")
            except errors.AppError:
                pass
        finally:
            await client.aclose()
        return await counter.snapshot()

    snapshot = run(scenario())
    assert snapshot["used"] == 1


def test_instagram_daily_cap_stops_further_calls():
    counter = DailyUnitCounter(1)
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"user": {"username": "demo"}, "stories": []})

    async def scenario():
        provider, client = make_instagram(handler, counter=counter)
        try:
            await provider.list_stories("demo")
            await provider.list_stories("other")
        finally:
            await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.PROVIDER_QUOTA
    assert calls == 1


def test_instagram_list_is_cached():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"user": {"username": "demo"}, "stories": []})

    async def scenario():
        provider, client = make_instagram(handler)
        first = await provider.list_stories("demo")
        second = await provider.list_stories("demo")
        await client.aclose()
        return first, second

    first, second = run(scenario())
    assert first is second
    assert calls == 1


def test_instagram_single_story_and_invalid_media():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/story"
        assert request.url.params["id"] == "1795383141000001"
        return httpx.Response(
            200,
            json={
                "story": storiesfly_story(
                    media_url="https://evil.example/stolen.jpg"
                ),
                "user": {"username": "demo"},
            },
        )

    async def scenario():
        provider, client = make_instagram(handler)
        try:
            await provider.get_story("demo", "1795383141000001")
        finally:
            await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.UNAVAILABLE


def test_instagram_missing_story_is_unavailable():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"story": None, "user": {}})

    async def scenario():
        provider, client = make_instagram(handler)
        try:
            await provider.get_story("demo", "1795383141000001")
        finally:
            await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.UNAVAILABLE


def test_instagram_not_configured_makes_no_request():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    settings = make_settings(storiesfly_api_key="", storiesfly_enabled=True)

    async def scenario():
        provider, client = make_instagram(handler, settings=settings)
        try:
            await provider.list_stories("demo")
        finally:
            await client.aclose()

    with pytest.raises(errors.AppError) as excinfo:
        run(scenario())
    assert excinfo.value.code == errors.PROVIDER_NOT_CONFIGURED
    assert calls == 0
