"""SocialScope application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import api, health, pages
from app.api.templating import render
from app.core import errors
from app.core.limits import SlidingWindowLimiter
from app.core.logging import configure_logging, log_event, log_warning
from app.core.settings import Settings, get_settings
from app.services.providers.registry import build_providers

BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "app" / "static"

CSP = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' https://*.tiktokcdn.com https://*.tiktokcdn-eu.com "
    "https://*.tiktokcdn-us.com https://*.tiktokcdn-asia.com https://*.tiktokv.com "
    "https://*.tiktok.com https://*.ibyteimg.com https://*.cdninstagram.com "
    "https://*.fbcdn.net https://*.instagram.com; "
    "media-src https://*.tiktokcdn.com https://*.tiktokcdn-eu.com "
    "https://*.tiktokcdn-us.com https://*.tiktokcdn-asia.com https://*.tiktokv.com "
    "https://*.tiktok.com https://*.ibyteimg.com https://*.cdninstagram.com "
    "https://*.fbcdn.net; "
    "frame-src https://www.tiktok.com https://www.instagram.com"
)


def _error_payload(exc: errors.AppError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {"code": exc.code, "message": exc.message, "hint": exc.hint},
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.debug)
        timeout = httpx.Timeout(
            settings.read_timeout,
            connect=settings.connect_timeout,
            write=settings.connect_timeout,
            pool=settings.connect_timeout,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            headers={"User-Agent": "SocialScope/1.0 (public content viewer)"},
        ) as client:
            app.state.providers = build_providers(client, settings)
            log_event("startup", **settings.public_summary())
            try:
                yield
            finally:
                log_event("shutdown")

    app = FastAPI(
        title="SocialScope",
        version="1.0.0",
        description="Capability-honest public content viewer for TikTok and Instagram.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.state.settings = settings
    app.state.ip_limiter = SlidingWindowLimiter(settings.per_ip_per_minute)
    app.state.global_limiter = SlidingWindowLimiter(settings.global_per_minute)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path in {"/analyze", "/story", "/api/v1/analyze"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(errors.AppError)
    async def handle_app_error(request: Request, exc: errors.AppError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                _error_payload(exc),
                status_code=exc.status_code,
                headers=headers,
            )
        return render(
            request,
            "error.html",
            active="",
            status_code=exc.status_code,
            headers=headers,
            context={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "hint": exc.hint,
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/") or request.url.path == "/health":
            return JSONResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "not_found" if exc.status_code == 404 else "http_error",
                        "message": "Endpoint tidak ditemukan."
                        if exc.status_code == 404
                        else "Permintaan tidak dapat diproses.",
                        "hint": None,
                    },
                },
                status_code=exc.status_code,
            )
        message = (
            "Halaman tidak ditemukan."
            if exc.status_code == 404
            else "Permintaan tidak dapat diproses."
        )
        return render(
            request,
            "error.html",
            active="",
            status_code=exc.status_code,
            context={
                "error": {
                    "code": "not_found" if exc.status_code == 404 else "http_error",
                    "message": message,
                    "hint": "Periksa alamat halaman atau kembali ke beranda.",
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {
                    "ok": False,
                    "error": {
                        "code": errors.INVALID_INPUT,
                        "message": "Permintaan tidak valid.",
                        "hint": "Kirim JSON dengan field url.",
                    },
                },
                status_code=422,
            )
        return render(
            request,
            "error.html",
            active="",
            status_code=400,
            context={
                "error": {
                    "code": errors.INVALID_INPUT,
                    "message": "Permintaan tidak valid.",
                    "hint": None,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        log_warning("unhandled_error", error_type=type(exc).__name__)
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {
                    "ok": False,
                    "error": {
                        "code": errors.UNKNOWN,
                        "message": "Terjadi kesalahan internal.",
                        "hint": None,
                    },
                },
                status_code=500,
            )
        return render(
            request,
            "error.html",
            active="",
            status_code=500,
            context={
                "error": {
                    "code": errors.UNKNOWN,
                    "message": "Terjadi kesalahan internal.",
                    "hint": "Coba lagi. Tidak ada data yang disimpan.",
                }
            },
        )

    app.include_router(health.router)
    app.include_router(pages.router)
    app.include_router(api.router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()
