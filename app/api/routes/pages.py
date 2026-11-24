"""Server-rendered pages and the form-based analyze action."""

from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.guards import enforce_rate_limits
from app.api.templating import render
from app.core import errors
from app.core.logging import log_event, log_warning
from app.services.analysis import analyze
from app.services.capabilities import STORY_NOTE, capability_matrix, matrix_rows, story_capability
from app.services.url_analyzer import analyze_url

router = APIRouter(tags=["pages"])

MAX_FORM_BYTES = 8 * 1024


async def _read_url_field(request: Request) -> str:
    """Read the single `url` field from a urlencoded form.

    Starlette's `request.form()` requires `python-multipart` even for urlencoded
    bodies. SocialScope only needs one text field, so it parses the body itself:
    no new dependency, no multipart/file handling, and a hard byte cap while
    streaming.
    """
    content_type = (
        (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    )
    if content_type not in {"application/x-www-form-urlencoded", ""}:
        raise errors.invalid("Formulir tidak dapat dibaca.")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FORM_BYTES:
            raise errors.invalid("Formulir terlalu besar.")
    try:
        text = bytes(body).decode("utf-8")
        values = parse_qs(text, keep_blank_values=True, max_num_fields=8)
    except (UnicodeDecodeError, ValueError) as exc:
        raise errors.invalid("Formulir tidak dapat dibaca.") from exc

    raw = values.get("url") or [""]
    return raw[0]


def _story_cards(request: Request) -> list[dict[str, object]]:
    settings = request.app.state.settings
    cards = []
    for platform, label in (("tiktok", "TikTok"), ("instagram", "Instagram")):
        capability = story_capability(platform, settings)  # type: ignore[arg-type]
        cards.append(
            {
                "platform": platform,
                "label": label,
                "capability": capability,
                "note": STORY_NOTE[platform],
                "configured": (
                    settings.tiktok_configured
                    if platform == "tiktok"
                    else settings.instagram_configured
                ),
            }
        )
    return cards


def _error_view(exc: errors.AppError) -> dict[str, object]:
    return {
        "code": exc.code,
        "message": exc.message,
        "hint": exc.hint,
    }


@router.get("/")
async def home(request: Request):
    settings = request.app.state.settings
    return render(
        request,
        "index.html",
        active="home",
        context={
            "matrix": capability_matrix(settings),
            "matrix_rows": matrix_rows(settings),
            "story_cards": _story_cards(request),
            "raw_url": "",
            "result": None,
            "error": None,
            "form_action": "/analyze",
        },
    )


@router.post("/analyze")
async def analyze_form(request: Request):
    """Accept the homepage form.

    The submitted URL is parsed, never fetched. The response is fully rendered so
    the feature works without JavaScript.
    """
    raw_url = ""
    try:
        raw_url = await _read_url_field(request)
        ref = analyze_url(raw_url)
        await enforce_rate_limits(request)
        result = await analyze(ref, request.app.state.providers, request.app.state.settings)
    except errors.AppError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        status = exc.status_code
        log_event(
            "analyze_rejected",
            code=exc.code,
            platform="unknown",
            status=status,
        )
        return render(
            request,
            "index.html",
            active="home",
            status_code=status,
            headers=headers,
            context=_home_context(request, raw_url=raw_url, error=_error_view(exc)),
        )
    except Exception as exc:  # noqa: BLE001 - never leak internals
        log_warning("analyze_unhandled", error_type=type(exc).__name__)
        return render(
            request,
            "index.html",
            active="home",
            status_code=500,
            context=_home_context(
                request,
                raw_url=raw_url,
                error={
                    "code": errors.UNKNOWN,
                    "message": "Terjadi kesalahan internal.",
                    "hint": "Coba lagi. Tidak ada data yang disimpan.",
                },
            ),
        )

    log_event(
        "analyze_ok",
        platform=ref.platform,
        kind=ref.kind,
        mode=result.mode,
        story_state=result.story_state or "none",
        items=result.story.count if result.story else 0,
    )
    return render(
        request,
        "index.html",
        active="home",
        context=_home_context(request, raw_url=raw_url, result=result),
    )


def _home_context(
    request: Request,
    *,
    raw_url: str,
    result=None,
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "matrix": capability_matrix(settings),
        "matrix_rows": matrix_rows(settings),
        "story_cards": _story_cards(request),
        "raw_url": raw_url,
        "result": result,
        "error": error,
        "form_action": "/analyze",
    }


@router.get("/story")
async def story_page(request: Request):
    return render(
        request,
        "story.html",
        active="story",
        context={
            "story_cards": _story_cards(request),
            "raw_url": "",
            "error": None,
        },
    )


@router.post("/story")
async def story_post(request: Request):
    # Same handler as the homepage form, but keeps the Story page as the surface.
    raw_url = ""
    try:
        raw_url = await _read_url_field(request)
        ref = analyze_url(raw_url)
        if ref.kind not in {"story", "profile"}:
            raise errors.unsupported_resource(
                "Halaman Story hanya menerima tautan Story atau profil.",
                hint="Tempel URL Story (/stories/…/…/) atau URL profil untuk melihat Story aktif.",
            )
        await enforce_rate_limits(request)
        result = await analyze(ref, request.app.state.providers, request.app.state.settings)
    except errors.AppError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return render(
            request,
            "story.html",
            active="story",
            status_code=exc.status_code,
            headers=headers,
            context=_story_context(request, raw_url=raw_url, error=_error_view(exc)),
        )
    except Exception as exc:  # noqa: BLE001
        log_warning("story_unhandled", error_type=type(exc).__name__)
        return render(
            request,
            "story.html",
            active="story",
            status_code=500,
            context=_story_context(
                request,
                raw_url=raw_url,
                error={
                    "code": errors.UNKNOWN,
                    "message": "Terjadi kesalahan internal.",
                    "hint": "Coba lagi beberapa saat lagi.",
                },
            ),
        )

    return render(
        request,
        "story.html",
        active="story",
        context=_story_context(request, raw_url=raw_url, result=result),
    )


def _story_context(
    request: Request,
    *,
    raw_url: str = "",
    result=None,
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "story_cards": _story_cards(request),
        "raw_url": raw_url,
        "result": result,
        "error": error,
        "form_action": "/story",
    }


@router.get("/privacy")
async def privacy_page(request: Request):
    return render(request, "privacy.html", active="privacy")


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)
