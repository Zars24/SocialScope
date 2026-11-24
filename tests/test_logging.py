from __future__ import annotations

import logging

from app.core.logging import log_event


def test_logs_redact_urls_and_secrets(caplog):
    caplog.set_level(logging.INFO, logger="socialscope")
    log_event(
        "test_event",
        platform="tiktok",
        url="https://www.tiktok.com/@demo?secret=1",
        api_key="sf_live_should_not_appear",
        authorization="Bearer abc",
        count=2,
    )
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "test_event" in message
    assert "platform=tiktok" in message
    assert "count=2" in message
    assert "https://" not in message
    assert "sf_live_should_not_appear" not in message
    assert "Bearer" not in message
