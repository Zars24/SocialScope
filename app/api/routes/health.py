"""Health endpoint. Performs no external calls."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": request.app.version,
        "external_calls": False,
        "providers": {
            "tiktok": "configured" if settings.tiktok_configured else "disabled",
            "instagram": "configured" if settings.instagram_configured else "disabled",
        },
    }
