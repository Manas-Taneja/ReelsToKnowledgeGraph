"""Download a post's media, and whatever metadata came with it.

Instagram: reels are video (yt-dlp). /p/ links may be a video, a single image,
or a multi-slide carousel -- so we try yt-dlp first and fall back to gallery-dl,
which is built for image sets and grabs every slide in one shot.

X: gallery-dl does the whole job, including the video, so there is one path
rather than two. It is also the only one of the pair that will hand back a
tweet carrying no media at all -- and on X that is a normal post, not a
failure, so the text becomes the content. See `_acquire_twitter`.
"""
import json
import subprocess
from pathlib import Path

from . import config, platforms

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def _cookie_args(platform=platforms.DEFAULT):
    """Cookies are opt-in for Instagram; X serves a logged-out client nothing.

    RKB_X_COOKIES / RKB_X_BROWSER let X use a different jar from Instagram,
    which matters if you keep the two accounts in different browsers. They fall
    back to the general setting when unset.
    """
    plat = platforms.get(platform)
    if plat.key == "twitter":
        f = config.X_COOKIES_FILE or config.COOKIES_FILE
        b = config.X_BROWSER or config.BROWSER
    else:
        f, b = config.COOKIES_FILE, config.BROWSER
    if f:
        return ["--cookies", f]
    if b:
        return ["--cookies-from-browser", b]
    return []


AUTH_HINT = (
    "Instagram served a login wall. Image/carousel posts always need auth; a "
    "reel hitting this is usually from a private or restricted account. Fix: "
    "grant your terminal Full Disk Access (System Settings > Privacy & "
    "Security), then re-run with RKB_BROWSER=safari and --retry. No browser "
    "extension is needed."
)

X_AUTH_HINT = (
    "X served nothing, which is what it does for a logged-out client on almost "
    "every endpoint. Unlike Instagram, cookies here are not optional. Fix: set "
    "RKB_X_BROWSER=safari|chrome|firefox (Safari also needs Full Disk Access "
    "for your terminal), or export a cookies.txt and set RKB_X_COOKIES."
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


# --------------------------------------------------------------------------- #
# Instagram
# --------------------------------------------------------------------------- #
def _acquire_instagram(media_dir, url):
    errors = []
    cookies = _cookie_args("instagram")

    # --- video path ---------------------------------------------------------
    r = _run([
        "yt-dlp", *cookies,
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
        "gallery-dl", *cookies,
        "--write-metadata", "-D", str(media_dir), url,
    ])
    videos, images = _classify(media_dir)
    if videos or images:
        return {"media_kind": "video" if videos else "images",
                "media_dir": str(media_dir),
                "caption": _caption_from_json(media_dir)}
    errors.append("gallery-dl: " + (r.stderr.strip().splitlines() or ["nothing downloaded"])[-1])

    detail = " | ".join(errors)
    if not cookies and _is_auth_wall(detail):
        raise RuntimeError(f"{AUTH_HINT} [{detail}]")
    raise RuntimeError(detail)


# --------------------------------------------------------------------------- #
# X / Twitter
# --------------------------------------------------------------------------- #
# gallery-dl skips text-only tweets unless told otherwise, and those are
# exactly the ones whose payload is the text. Always on for us.
_X_OPTS = ["-o", "text-tweets=true", "-o", "videos=true"]


def _tweet_meta(node):
    """The first tweet object anywhere in a gallery-dl `-j` dump.

    The dump is a list of [type, ...] rows whose shape varies by entry kind, so
    this looks for the payload by its keys rather than by position.
    """
    if isinstance(node, dict):
        if "content" in node and isinstance(node.get("author"), dict):
            return node
        for v in node.values():
            hit = _tweet_meta(v)
            if hit:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = _tweet_meta(v)
            if hit:
                return hit
    return None


def _acquire_twitter(media_dir, url):
    cookies = _cookie_args("twitter")

    # Metadata first, and separately from the download: a text-only tweet
    # produces no file, so if we inferred the caption from a sidecar the way
    # Instagram does, that tweet would arrive with no content at all.
    meta, meta_err = None, ""
    r = _run(["gallery-dl", *cookies, *_X_OPTS, "-j", url])
    if r.stdout.strip():
        try:
            meta = _tweet_meta(json.loads(r.stdout))
        except json.JSONDecodeError:
            meta_err = "could not parse gallery-dl -j output"
    if meta:
        (media_dir / "tweet.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, default=str))
    else:
        meta_err = meta_err or (r.stderr.strip().splitlines() or ["no metadata"])[-1]

    # Then the media, if there is any.
    r2 = _run(["gallery-dl", *cookies, *_X_OPTS,
               "--write-metadata", "-D", str(media_dir), url])
    videos, images = _classify(media_dir)

    if not (videos or images) and not meta:
        detail = f"gallery-dl: {meta_err}"
        tail = (r2.stderr.strip().splitlines() or [])[-1:]
        if tail:
            detail += f" | {tail[0]}"
        if not cookies:
            raise RuntimeError(f"{X_AUTH_HINT} [{detail}]")
        raise RuntimeError(detail)

    author = (meta or {}).get("author") or {}
    hashtags = [h for h in ((meta or {}).get("hashtags") or []) if isinstance(h, str)]
    return {
        # A tweet with no picture and no video is not a failed download; the
        # text is the whole post. prepare/ocr/frames all branch on this.
        "media_kind": "video" if videos else "images" if images else "text",
        "media_dir": str(media_dir),
        "caption": (meta or {}).get("content") or _caption_from_json(media_dir),
        "author": author.get("nick") or author.get("name"),
        "author_link": (author.get("url")
                        or (f"https://x.com/{author['name']}" if author.get("name") else None)),
        "hashtags": [f"#{h.lstrip('#')}" for h in hashtags],
        "saved_at": str((meta or {}).get("date") or "") or None,
    }


# --------------------------------------------------------------------------- #
def acquire(shortcode, url, platform=platforms.DEFAULT):
    """Returns dict(media_kind, media_dir, caption, ...) or raises RuntimeError."""
    media_dir = config.MEDIA_DIR / shortcode
    media_dir.mkdir(parents=True, exist_ok=True)
    plat = platforms.get(platform)

    videos, images = _classify(media_dir)
    if videos or images:  # already downloaded on a previous run
        return {
            "media_kind": "video" if videos else "images",
            "media_dir": str(media_dir),
            "caption": _caption_from_json(media_dir),
        }

    if plat.key == "twitter":
        return _acquire_twitter(media_dir, url)
    return _acquire_instagram(media_dir, url)
