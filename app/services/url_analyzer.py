"""Strict URL validation.

The submitted URL is parsed locally and then discarded. It is never fetched.
A `ResourceRef` is produced only from validated identifiers, and outbound
requests are later built from fixed templates plus those identifiers.

Defence in depth:
- HTTPS only (a missing scheme is upgraded to HTTPS),
- exact hostname allowlist, never substring matching,
- no credentials, no non-default port, no IP literal, no encoded host,
- ASCII-only host and identifier segments,
- explicit path grammar per platform,
- query strings and fragments are discarded.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from app.core import errors
from app.schemas.analysis import ResourceRef
from app.services.detect import INSTAGRAM_HOSTS, TIKTOK_HOSTS

MAX_INPUT = 2048

_TIKTOK_USER = re.compile(r"^[A-Za-z0-9._]{2,24}$")
_TIKTOK_ID = re.compile(r"^\d{15,25}$")
_IG_USER = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_IG_CODE = re.compile(r"^[A-Za-z0-9_-]{5,40}$")
_IG_STORY_ID = re.compile(r"^\d{5,25}$")

_IG_RESERVED = {
    "about",
    "accounts",
    "api",
    "ar",
    "challenge",
    "developer",
    "directory",
    "emojis",
    "explore",
    "graphql",
    "legal",
    "nametag",
    "p",
    "reel",
    "reels",
    "session",
    "share",
    "stories",
    "tv",
    "web",
    "your_activity",
}

_IG_CONTENT = {"p": "post", "reel": "reel", "reels": "reel", "tv": "video"}


def _reject(message: str, *, hint: str | None = None) -> errors.AppError:
    return errors.invalid(message, hint=hint)


def _validate_shape(text: str) -> None:
    if not text:
        raise _reject("Masukkan URL TikTok atau Instagram.")
    if len(text) > MAX_INPUT:
        raise _reject("URL terlalu panjang.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise _reject("URL mengandung karakter kontrol.")
    if "\\" in text:
        raise _reject("URL mengandung garis miring terbalik.")
    if any(ch.isspace() for ch in text):
        raise _reject("URL tidak boleh mengandung spasi.")


def _split(text: str) -> tuple[str, str, str]:
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise _reject("URL tidak dapat dibaca.") from exc

    if parsed.scheme.lower() != "https":
        raise _reject(
            "Hanya URL https:// yang didukung.",
            hint="Ganti awalan http:// menjadi https:// lalu coba lagi.",
        )
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise _reject("URL tidak boleh memuat kredensial atau karakter @ pada host.")
    if "%" in parsed.netloc:
        raise _reject("Host tidak boleh memakai encoding.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise _reject("Port pada URL tidak valid.") from exc
    if port is not None and port != 443:
        raise _reject("Hanya port 443 (HTTPS standar) yang didukung.")

    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        raise _reject("Host pada URL tidak ditemukan.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise _reject("Alamat IP tidak didukung; gunakan domain platform.")

    path = parsed.path or "/"
    if not path.startswith("/"):
        raise _reject("Bentuk path URL tidak valid.")
    if "%" in path:
        raise _reject("Path tidak boleh memakai encoding.")
    if "//" in path or "/./" in path or "/../" in path:
        raise _reject("Path URL tidak valid.")
    if len(path) > 512:
        raise _reject("Path URL terlalu panjang.")
    return host, path, parsed.query


def _segments(path: str) -> list[str]:
    trimmed = path.strip("/")
    if not trimmed:
        return []
    return [segment for segment in trimmed.split("/") if segment]


def _tiktok(host: str, path: str) -> ResourceRef:
    if host in {"vm.tiktok.com", "vt.tiktok.com"}:
        raise errors.unsupported_resource(
            "Tautan pendek TikTok tidak dapat dibuka di sini.",
            hint="Buka tautan itu di browser, lalu tempel URL lengkap yang muncul (mengandung /@username).",
        )

    segments = _segments(path)
    if not segments:
        raise errors.unsupported_resource(
            "URL TikTok harus memuat nama akun.",
            hint="Contoh: https://www.tiktok.com/@username",
        )

    first = segments[0]
    if not first.startswith("@"):
        raise errors.unsupported_resource(
            "Bentuk URL TikTok ini belum didukung.",
            hint="Gunakan /@username, /@username/video/…, atau /@username/story/…",
        )
    username = first[1:]
    if not _TIKTOK_USER.match(username):
        raise _reject("Nama akun TikTok tidak valid.")

    if len(segments) == 1:
        return ResourceRef(
            platform="tiktok",
            kind="profile",
            username=username,
            canonical_url=f"https://www.tiktok.com/@{username}",
        )

    if len(segments) == 3 and segments[1] in {"video", "photo", "story"}:
        content_id = segments[2]
        if not _TIKTOK_ID.match(content_id):
            raise _reject("ID konten TikTok tidak valid.")
        kind = {"video": "video", "photo": "photo", "story": "story"}[segments[1]]
        return ResourceRef(
            platform="tiktok",
            kind=kind,  # type: ignore[arg-type]
            username=username,
            content_id=content_id,
            canonical_url=f"https://www.tiktok.com/@{username}/{segments[1]}/{content_id}",
        )

    if len(segments) == 2 and segments[1] == "live":
        raise errors.unsupported_resource("Live TikTok tidak termasuk cakupan SocialScope.")

    raise errors.unsupported_resource(
        "Bentuk URL TikTok ini belum didukung.",
        hint="Yang didukung: profil, video, foto, dan Story pada akun publik.",
    )


def _instagram(host: str, path: str) -> ResourceRef:
    segments = _segments(path)
    if not segments:
        raise errors.unsupported_resource(
            "URL Instagram harus memuat nama akun atau kode konten.",
            hint="Contoh: https://www.instagram.com/username/",
        )

    first = segments[0].lower()

    if first == "stories":
        if len(segments) == 3:
            username, story_id = segments[1], segments[2]
            if not _IG_USER.match(username) or not _IG_STORY_ID.match(story_id):
                raise _reject("Bentuk URL Story Instagram tidak valid.")
            return ResourceRef(
                platform="instagram",
                kind="story",
                username=username,
                content_id=story_id,
                canonical_url=f"https://www.instagram.com/stories/{username}/{story_id}/",
            )
        raise errors.unsupported_resource(
            "Story Highlight atau daftar Story tanpa satu ID belum didukung.",
            hint="Tempel URL satu Story, atau tempel URL profil untuk melihat Story yang sedang aktif.",
        )

    if first in {"s", "share"}:
        raise errors.unsupported_resource(
            "Tautan bagikan Instagram belum didukung.",
            hint="Buka tautan itu di browser sampai muncul URL /p/, /reel/, atau /stories/, lalu tempel URL tersebut.",
        )

    if first in _IG_CONTENT and len(segments) == 2:
        code = segments[1]
        if not _IG_CODE.match(code):
            raise _reject("Kode konten Instagram tidak valid.")
        kind = _IG_CONTENT[first]
        canonical_first = "reel" if kind == "reel" else "p"
        return ResourceRef(
            platform="instagram",
            kind=kind,  # type: ignore[arg-type]
            content_id=code,
            canonical_url=f"https://www.instagram.com/{canonical_first}/{code}/",
        )

    if len(segments) == 1 and first not in _IG_RESERVED:
        if not _IG_USER.match(segments[0]):
            raise _reject("Nama akun Instagram tidak valid.")
        return ResourceRef(
            platform="instagram",
            kind="profile",
            username=segments[0],
            canonical_url=f"https://www.instagram.com/{segments[0]}/",
        )

    if first in _IG_RESERVED:
        raise errors.unsupported_resource(
            "Halaman Instagram ini belum didukung.",
            hint="Gunakan URL profil, post, reel, atau satu Story.",
        )

    raise errors.unsupported_resource(
        "Bentuk URL Instagram ini belum didukung.",
        hint="Yang didukung: profil, /p/, /reel/, dan /stories/username/id/.",
    )


def analyze_url(raw: str) -> ResourceRef:
    text = (raw or "").strip()
    _validate_shape(text)
    host, path, _query = _split(text)

    if host in TIKTOK_HOSTS:
        return _tiktok(host, path)
    if host in INSTAGRAM_HOSTS:
        return _instagram(host, path)

    if host.endswith(".tiktok.com") or host.endswith(".instagram.com"):
        raise errors.unsupported_platform(
            "Subdomain platform ini tidak termasuk daftar yang diizinkan.",
            # The hint stays generic so it does not teach host-spoofing patterns.
        )

    raise errors.unsupported_platform(
        "Platform belum didukung. SocialScope hanya membaca TikTok dan Instagram.",
        hint="Tempel URL dari tiktok.com atau instagram.com.",
    )
