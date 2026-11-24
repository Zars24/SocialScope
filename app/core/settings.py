"""Application settings.

Values come from environment variables (loaded from the repository `.env`).
The StoriesFly key is never logged and never rendered; see `safe_summary`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env", override=False)


def _str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _int(name: str, default: int, *, minimum: int = 0, maximum: int = 1_000_000) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: _str("APP_NAME", "SocialScope"))
    app_env: str = field(default_factory=lambda: _str("APP_ENV", "development"))
    debug: bool = field(default_factory=lambda: _bool("APP_DEBUG", False))
    host: str = field(default_factory=lambda: _str("APP_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("APP_PORT", 8000, minimum=1, maximum=65535))

    # Instagram Story provider (StoriesFly API v1). Server-side only.
    storiesfly_api_key: str = field(
        default_factory=lambda: _str("STORIESFLY_API_KEY", ""), repr=False
    )
    storiesfly_enabled: bool = field(
        default_factory=lambda: _bool("STORIESFLY_ENABLED", True)
    )
    storiesfly_base_url: str = "https://storiesfly.com/api/v1"
    storiesfly_daily_unit_cap: int = field(
        default_factory=lambda: _int("STORIESFLY_DAILY_UNIT_CAP", 40, minimum=0, maximum=5000)
    )

    # TikTok Story provider (TikWM). No key.
    tikwm_enabled: bool = field(default_factory=lambda: _bool("TIKWM_ENABLED", True))
    tikwm_base_url: str = "https://tikwm.com"

    # Outbound limits. Provider responses are small JSON documents.
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    max_json_bytes: int = 512 * 1024
    max_html_bytes: int = 1024 * 1024

    # In-memory caches. Never persisted.
    story_cache_ttl: int = field(default_factory=lambda: _int("STORY_CACHE_TTL", 45, maximum=300))
    story_cache_entries: int = 32

    # Abuse limits.
    per_ip_per_minute: int = field(
        default_factory=lambda: _int("RATE_LIMIT_PER_IP_PER_MINUTE", 12, minimum=1, maximum=600)
    )
    global_per_minute: int = field(
        default_factory=lambda: _int("RATE_LIMIT_GLOBAL_PER_MINUTE", 90, minimum=1, maximum=6000)
    )

    @property
    def instagram_configured(self) -> bool:
        return bool(self.storiesfly_api_key) and self.storiesfly_enabled

    @property
    def tiktok_configured(self) -> bool:
        return self.tikwm_enabled

    def public_summary(self) -> dict[str, object]:
        """Safe, non-secret summary for health and startup logs."""
        return {
            "app_env": self.app_env,
            "debug": self.debug,
            "tiktok_provider": self.tiktok_configured,
            "instagram_provider": self.instagram_configured,
            "instagram_daily_unit_cap": self.storiesfly_daily_unit_cap,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
