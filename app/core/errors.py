"""Error taxonomy.

One exception type carries a machine-readable code, a safe user-facing message,
and an HTTP status. Nothing from an upstream response body, header, URL, or
query string is ever attached to the message that reaches a visitor or a log.
"""

from __future__ import annotations

from dataclasses import dataclass

# Codes are stable and safe to expose.
INVALID_INPUT = "invalid_input"
UNSUPPORTED_PLATFORM = "unsupported_platform"
UNSUPPORTED_RESOURCE = "unsupported_resource"
UNAVAILABLE = "unavailable"
RATE_LIMITED = "rate_limited"
PROVIDER_ERROR = "provider_error"
PROVIDER_NOT_CONFIGURED = "provider_not_configured"
PROVIDER_QUOTA = "provider_quota"
TIMEOUT = "timeout"
UNKNOWN = "unknown"


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    hint: str | None = None
    retry_after: int | None = None
    # Internal marker for logs/tests. Never rendered.
    internal: str | None = None

    def __str__(self) -> str:  # pragma: no cover - defensive
        return f"{self.code}: {self.message}"


def invalid(message: str, *, hint: str | None = None) -> AppError:
    return AppError(INVALID_INPUT, message, 400, hint=hint)


def unsupported_platform(message: str, *, hint: str | None = None) -> AppError:
    return AppError(UNSUPPORTED_PLATFORM, message, 400, hint=hint)


def unsupported_resource(message: str, *, hint: str | None = None) -> AppError:
    return AppError(UNSUPPORTED_RESOURCE, message, 400, hint=hint)


def unavailable(message: str, *, hint: str | None = None) -> AppError:
    return AppError(UNAVAILABLE, message, 404, hint=hint)


def not_configured(platform_label: str) -> AppError:
    return AppError(
        PROVIDER_NOT_CONFIGURED,
        f"Story {platform_label} belum aktif di server ini.",
        503,
        hint="Provider Story belum dikonfigurasi. Fitur lain tetap dapat digunakan.",
    )


def rate_limited(retry_after: int, *, scope: str = "permintaan") -> AppError:
    return AppError(
        RATE_LIMITED,
        f"Terlalu banyak {scope}. Coba lagi sebentar.",
        429,
        hint="Batas ini melindungi platform dan provider dari lonjakan trafik.",
        retry_after=max(1, int(retry_after)),
    )


def provider_error(message: str = "Sumber data sedang tidak dapat diakses.", *, internal: str | None = None) -> AppError:
    return AppError(
        PROVIDER_ERROR,
        message,
        502,
        hint="Ini masalah di sisi sumber data, bukan bukti bahwa akun privat atau dihapus.",
        internal=internal,
    )


def upstream_timeout() -> AppError:
    return AppError(
        TIMEOUT,
        "Sumber data tidak menjawab tepat waktu.",
        504,
        hint="Coba lagi. Kami tidak melakukan percobaan berulang otomatis.",
        internal="upstream_timeout",
    )
