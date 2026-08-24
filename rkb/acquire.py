"""Download a post's media.

Reels are video (yt-dlp). /p/ links may be a video, a single image, or a
multi-slide carousel — so we try yt-dlp first and fall back to gallery-dl,
which is built for image sets and grabs every slide in one shot.
"""
import json
import subprocess
from pathlib import Path

from . import config

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def _cookie_args():
    """Cookies are opt-in; without them we fetch anonymously."""
    if config.COOKIES_FILE:
        return ["--cookies", config.COOKIES_FILE]
    if config.BROWSER:
        return ["--cookies-from-browser", config.BROWSER]
    return []


AUTH_HINT = (
    "Instagram served a login wall. Image/carousel posts always need auth; a "
    "reel hitting this is usually from a private or restricted account. Fix: "
    "grant your terminal Full Disk Access (System Settings > Privacy & "
    "Security), then re-run with RKB_BROWSER=safari and --retry. No browser "
    "extension is needed."
)


def _is_auth_wall(text):
    t = text.lower()
    return "login" in t or "rate-limit" in t or "empty media response" in t


def _run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _caption_from_json(media_dir):
    """Both downloaders drop a sidecar JSON; dig the caption out of whichever."""
    for jf in sorted(media_dir.glob("*.json")):
        try:
            meta = json.loads(jf.read_text(errors="replace"))
        except json.JSONDecodeError:
            continue
        if isinstance(meta, dict):
            for key in ("description", "caption", "title", "fulltitle"):
                v = meta.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


def _classify(media_dir):
    videos = [p for p in media_dir.iterdir() if p.suffix.lower() in VIDEO_EXT]
    images = [p for p in media_dir.iterdir() if p.suffix.lower() in IMAGE_EXT]
    return videos, images


def acquire(shortcode, url):
    """Returns dict(media_kind, media_dir, caption) or raises RuntimeError."""
    media_dir = config.MEDIA_DIR / shortcode
    media_dir.mkdir(parents=True, exist_ok=True)

    videos, images = _classify(media_dir)
    if videos or images:  # already downloaded on a previous run
        return {
            "media_kind": "video" if videos else "images",
            "media_dir": str(media_dir),
            "caption": _caption_from_json(media_dir),
        }

    errors = []

    # --- video path ---------------------------------------------------------
    r = _run([
        "yt-dlp", *_cookie_args(),
        "--no-playlist", "--write-info-json", "--no-warnings",
        "--socket-timeout", "30",
        "-o", str(media_dir / "%(id)s.%(ext)s"), url,
    ])
    videos, images = _classify(media_dir)
    if videos:
        return {"media_kind": "video", "media_dir": str(media_dir),
                "caption": _caption_from_json(media_dir)}
    errors.append("yt-dlp: " + (r.stderr.strip().splitlines() or ["no video stream"])[-1])

    # --- image / carousel path ---------------------------------------------
    r = _run([
        "gallery-dl", *_cookie_args(),
        "--write-metadata", "-D", str(media_dir), url,
    ])
    videos, images = _classify(media_dir)
    if videos or images:
        return {"media_kind": "video" if videos else "images",
                "media_dir": str(media_dir),
                "caption": _caption_from_json(media_dir)}
    errors.append("gallery-dl: " + (r.stderr.strip().splitlines() or ["nothing downloaded"])[-1])

    detail = " | ".join(errors)
    if not _cookie_args() and _is_auth_wall(detail):
        raise RuntimeError(f"{AUTH_HINT} [{detail}]")
    raise RuntimeError(detail)
