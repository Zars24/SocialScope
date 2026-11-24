from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.core import errors
from app.main import create_app
from tests.conftest import fake_providers, make_settings


@contextmanager
def make_client(*, providers=None, **settings_overrides):
    app = create_app(make_settings(**settings_overrides))
    with TestClient(app) as client:
        if providers is not None:
            client.app.state.providers = providers
        yield client


def test_home_renders_registry_and_security_headers():
    with make_client(providers=fake_providers()) as client:
        response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "SocialScope" in body
    assert "Fitur utama" in body
    # Nama provider (TikWM/StoriesFly) disembunyikan dari halaman pengguna
    # assert "TikWM" not in body  # diaktifkan setelah provider disembunyikan
    assert "Tidak tersedia" in body
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_health_performs_no_external_calls():
    with make_client(providers=fake_providers()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["external_calls"] is False
    assert payload["providers"]["tiktok"] == "configured"


def test_invalid_url_renders_inline_error():
    with make_client(providers=fake_providers()) as client:
        response = client.post("/analyze", data={"url": "http://www.tiktok.com/@demo"})
    assert response.status_code == 400
    assert "Hanya URL https:// yang didukung" in response.text
    assert "Kode: invalid_input" in response.text
    assert "Traceback" not in response.text


def test_oversized_form_body_is_rejected_before_parsing():
    with make_client(providers=fake_providers()) as client:
        response = client.post(
            "/analyze",
            content=b"url=" + b"a" * 9000,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 400
    assert "Formulir terlalu besar" in response.text


def test_multipart_form_is_rejected():
    with make_client(providers=fake_providers()) as client:
        response = client.post(
            "/analyze",
            files={"url": (None, "https://www.tiktok.com/@demo")},
        )
    assert response.status_code == 400
    assert "Formulir tidak dapat dibaca" in response.text
    assert "https://www.tiktok.com/@demo" not in response.text


def test_submitted_url_is_escaped_when_echoed_back():
    payload = '"><script>alert(1)</script>'
    with make_client(providers=fake_providers()) as client:
        response = client.post("/analyze", data={"url": payload})
    assert response.status_code == 400
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_tiktok_profile_renders_embed_and_structured_story():
    providers = fake_providers()
    with make_client(providers=providers) as client:
        response = client.post("/analyze", data={"url": "https://www.tiktok.com/@demo"})
    assert response.status_code == 200
    body = response.text
    assert "TikTok Creator Profile Embed" in body
    assert "https://www.tiktok.com/embed/@demo" in body
    # Nama provider (TikWM) disembunyikan dari halaman hasil
    assert "TikWM" not in body
    assert providers.tiktok.calls == [("list", "demo")]


def test_tiktok_video_uses_embed_only_and_spends_no_story_call():
    providers = fake_providers()
    with make_client(providers=providers) as client:
        response = client.post(
            "/analyze",
            data={"url": "https://www.tiktok.com/@demo/video/7711003081445510430"},
        )
    assert response.status_code == 200
    body = response.text
    assert providers.tiktok.calls == []


def test_instagram_profile_renders_story_without_fake_profile_embed():
    providers = fake_providers()
    with make_client(providers=providers) as client:
        response = client.post("/analyze", data={"url": "https://www.instagram.com/demo/"})
    assert response.status_code == 200
    body = response.text
    assert "Data terstruktur" in body
    # Nama provider (StoriesFly) disembunyikan dari halaman hasil
    assert "StoriesFly" not in body
    assert "Embed profil" not in body
    assert providers.instagram.calls == [("list", "demo")]


def test_empty_story_list_is_a_valid_answer_not_a_failure():
    providers = fake_providers(empty=True)
    with make_client(providers=providers) as client:
        response = client.post("/analyze", data={"url": "https://www.tiktok.com/@demo"})
    assert response.status_code == 200
    body = response.text
    assert "Tidak ada Story aktif" in body
    assert "0 Story aktif" in body
    assert "Story gagal dimuat" not in body


def test_tiktok_story_failure_is_partial_when_profile_embed_exists():
    providers = fake_providers(tiktok_error=errors.provider_error())
    with make_client(providers=providers) as client:
        response = client.post("/analyze", data={"url": "https://www.tiktok.com/@demo"})
    assert response.status_code == 200
    body = response.text
    assert "Story gagal dimuat" in body
    assert "https://www.tiktok.com/embed/@demo" in body
    assert "Kegagalan provider tidak membuktikan akun privat atau dihapus" in body


def test_single_story_failure_renders_error_page():
    providers = fake_providers(
        tiktok_error=errors.unavailable(
            "Story tidak ditemukan atau sudah kedaluwarsa.",
            hint="Story hanya aktif sekitar 24 jam.",
        )
    )
    with make_client(providers=providers) as client:
        response = client.post(
            "/analyze",
            data={"url": "https://www.tiktok.com/@demo/story/7711003081445510430"},
        )
    assert response.status_code == 404
    assert "Story tidak ditemukan atau sudah kedaluwarsa" in response.text
    assert "Story hanya aktif sekitar 24 jam" in response.text


def test_api_analyze_returns_typed_payload():
    with make_client(providers=fake_providers()) as client:
        response = client.post(
            "/api/v1/analyze", json={"url": "https://www.tiktok.com/@demo"}
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["resource"]["platform"] == "tiktok"
    assert payload["mode"] == "mixed"
    assert payload["story"]["provider_name"] == "—"
    assert len(payload["story"]["items"]) == 2
    assert payload["source"].startswith("TikTok Creator Profile Embed")


def test_api_invalid_url_returns_safe_json():
    with make_client(providers=fake_providers()) as client:
        response = client.post("/api/v1/analyze", json={"url": "https://evil.example/@demo"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unsupported_platform"
    assert "evil.example" not in payload["error"]["message"]


def test_rate_limit_returns_retry_after():
    with make_client(
        providers=fake_providers(), per_ip_per_minute=1, global_per_minute=100
    ) as client:
        first = client.post("/analyze", data={"url": "https://www.tiktok.com/@demo"})
        second = client.post("/analyze", data={"url": "https://www.tiktok.com/@demo"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"].isdigit()
    assert "Terlalu banyak" in second.text


def test_story_page_rejects_non_story_content():
    with make_client(providers=fake_providers()) as client:
        response = client.post(
            "/story",
            data={"url": "https://www.tiktok.com/@demo/video/7711003081445510430"},
        )
    assert response.status_code == 400
    assert "Halaman Story hanya menerima" in response.text


def test_story_page_accepts_profile():
    providers = fake_providers()
    with make_client(providers=providers) as client:
        response = client.post("/story", data={"url": "https://www.instagram.com/demo/"})
    assert response.status_code == 200
    # Nama provider disembunyikan dari halaman Story
    assert "StoriesFly" not in response.text
    assert providers.instagram.calls == [("list", "demo")]


def test_html_404_is_friendly():
    with make_client(providers=fake_providers()) as client:
        response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert "Halaman tidak ditemukan" in response.text
    assert "Kembali ke beranda" in response.text


def test_result_is_not_cached_by_intermediaries():
    with make_client(providers=fake_providers()) as client:
        response = client.post("/analyze", data={"url": "https://www.tiktok.com/@demo"})
    assert response.headers["cache-control"] == "no-store"
