"""Typed view models shared by routes, adapters, templates, and the JSON API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["tiktok", "instagram"]
ResourceKind = Literal["profile", "video", "photo", "reel", "post", "story"]
Mode = Literal["embed", "structured"]
CapabilityStatus = Literal["supported", "embed_only", "unavailable", "unknown"]
StoryState = Literal["ok", "empty", "unavailable", "error", "not_configured"]


class ResourceRef(BaseModel):
    platform: Platform
    kind: ResourceKind
    canonical_url: str
    username: str | None = None
    content_id: str | None = None

    @property
    def platform_label(self) -> str:
        return "TikTok" if self.platform == "tiktok" else "Instagram"

    @property
    def kind_label(self) -> str:
        return {
            "profile": "Profil",
            "video": "Video",
            "photo": "Foto",
            "reel": "Reel",
            "post": "Post",
            "story": "Story",
        }[self.kind]


class Capability(BaseModel):
    key: str
    label: str
    status: CapabilityStatus
    mode: Mode | None = None
    reason: str
    explanation: str
    method: str | None = None


class StoryItem(BaseModel):
    id: str
    media_type: Literal["photo", "video"]
    media_url: str
    thumbnail_url: str | None = None
    taken_at: int | None = None
    taken_at_iso: str | None = None
    duration: float | None = None
    permalink: str | None = None


class StoryBundle(BaseModel):
    platform: Platform
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    items: list[StoryItem] = Field(default_factory=list)
    provider_name: str
    source_label: str
    mode: Mode = "structured"
    fetched_at_iso: str
    note: str | None = None

    @property
    def count(self) -> int:
        return len(self.items)


class EmbedView(BaseModel):
    kind: ResourceKind
    url: str
    title: str
    source_label: str
    open_url: str
    aspect_ratio: str = "9 / 16"
    max_width: int = 360
    mode: Mode = "embed"
    note: str | None = None


class AnalysisResult(BaseModel):
    resource: ResourceRef
    mode: Literal["embed", "structured", "mixed", "unavailable"]
    source_label: str
    capabilities: list[Capability]
    embed: EmbedView | None = None
    story: StoryBundle | None = None
    story_state: StoryState | None = None
    story_message: str | None = None
    notices: list[str] = Field(default_factory=list)
    fetched_at_iso: str = ""


class ApiAnalyzeResponse(BaseModel):
    ok: bool = True
    resource: ResourceRef
    mode: str
    source: str
    capabilities: list[Capability]
    embed: EmbedView | None = None
    story: StoryBundle | None = None
    story_state: StoryState | None = None
    story_message: str | None = None
    notices: list[str] = Field(default_factory=list)
    fetched_at_iso: str = ""
