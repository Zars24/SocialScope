"""Jinja2 environment, shared context, and display filters.

Every template receives `t` (the translator for the request language) plus the
language itself, so copy and dates are resolved before the page is serialized.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from app.core.i18n import LANG_COOKIE, request_lang, translator

BASE_DIR = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = BASE_DIR / "app" / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Day/month names are the only localized date parts we render.
_MONTHS = {
    "id": ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
}


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _t_for(context) -> object:
    return context.get("t") or translator("id")


@pass_context
def relative_time(context, value: str | None) -> str:
    t = _t_for(context)
    parsed = _parse_utc(value)
    if parsed is None:
        return t("time.none")
    seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
    if seconds < 60:
        return t("time.justnow")
    if seconds < 3600:
        return t("time.minutes", n=int(seconds // 60))
    if seconds < 86400:
        return t("time.hours", n=int(seconds // 3600))
    if seconds < 7 * 86400:
        return t("time.days", n=int(seconds // 86400))
    return clock_time(context, value)


@pass_context
def clock_time(context, value: str | None) -> str:
    t = _t_for(context)
    parsed = _parse_utc(value)
    if parsed is None:
        return t("time.none")
    months = _MONTHS["en" if context.get("lang") == "en" else "id"]
    return f"{parsed.day} {months[parsed.month - 1]} {parsed.year} · {parsed:%H:%M} UTC"


@pass_context
def duration_fmt(context, value: float | None) -> str:
    if not value:
        return _t_for(context)("time.duration.none")
    total = int(round(value))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def short_number(value: int | float | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M".replace(".0M", "M")
    if number >= 1_000:
        return f"{number / 1_000:.1f}k".replace(".0k", "k")
    return str(int(number))


templates.env.filters["relative_time"] = relative_time
templates.env.filters["clock_time"] = clock_time
templates.env.filters["duration"] = duration_fmt
templates.env.filters["short_number"] = short_number


def base_context(request: Request, *, active: str) -> dict[str, object]:
    settings = request.app.state.settings
    lang = request_lang(request)
    # The language switch is a plain link, so it must point at a GET route even
    # when the current view came from a POST (analyze results).
    self_path = {"/": "/", "/story": "/story", "/privacy": "/privacy"}.get(
        request.url.path, "/"
    )
    return {
        "request": request,
        "app_name": settings.app_name,
        "active": active,
        "year": datetime.now(timezone.utc).year,
        "lang": lang,
        "t": translator(lang),
        "next_lang": "en" if lang == "id" else "id",
        "self_path": self_path,
        "instagram_configured": settings.instagram_configured,
        "tiktok_configured": settings.tiktok_configured,
    }


def render(
    request: Request,
    name: str,
    *,
    active: str,
    context: dict[str, object] | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
):
    merged = base_context(request, active=active)
    if context:
        merged.update(context)
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context=merged,
        status_code=status_code,
        headers=headers,
    )
    lang = str(merged.get("lang") or "id")
    if request.cookies.get(LANG_COOKIE) != lang:
        response.set_cookie(
            LANG_COOKIE,
            lang,
            max_age=60 * 60 * 24 * 365,
            samesite="lax",
            httponly=True,
            path="/",
        )
    return response