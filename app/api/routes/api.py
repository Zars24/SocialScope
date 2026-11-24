"""JSON API. Same validation and provider boundary as the HTML route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.guards import enforce_rate_limits
from app.core.logging import log_event
from app.schemas.analysis import ApiAnalyzeResponse
from app.services.analysis import analyze
from app.services.capabilities import capability_matrix
from app.services.url_analyzer import analyze_url

router = APIRouter(prefix="/api/v1", tags=["api"])


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@router.post("/analyze", response_model=ApiAnalyzeResponse)
async def api_analyze(payload: AnalyzeRequest, request: Request) -> ApiAnalyzeResponse:
    ref = analyze_url(payload.url)
    await enforce_rate_limits(request)
    result = await analyze(ref, request.app.state.providers, request.app.state.settings)
    log_event(
        "api_analyze_ok",
        platform=ref.platform,
        kind=ref.kind,
        mode=result.mode,
        story_state=result.story_state or "none",
    )
    return ApiAnalyzeResponse(
        resource=result.resource,
        mode=result.mode,
        source=result.source_label,
        capabilities=result.capabilities,
        embed=result.embed,
        story=result.story,
        story_state=result.story_state,
        story_message=result.story_message,
        notices=result.notices,
        fetched_at_iso=result.fetched_at_iso,
    )


@router.get("/capabilities")
async def api_capabilities(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "matrix": capability_matrix(settings),
        "story_providers": {
            "tiktok": "configured" if settings.tiktok_configured else "disabled",
            "instagram": "configured" if settings.instagram_configured else "disabled",
        },
    }
