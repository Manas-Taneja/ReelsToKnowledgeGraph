"""Get posts into the database without an export file.

`importer.py` reads the Meta dump: a file you request, wait for, download and
unzip. That works, but it is the slowest possible loop for something you saw
thirty seconds ago. Two faster doors, both landing in the same `posts` table at
status 'new' so `rkb prepare` picks them up unchanged:

  add_urls()   one or more links, pasted or forwarded (this is what both
               front doors call -- rkb/telegram.py and rkb/ingestd.py)
  bookmarks()  a sweep of your live X bookmark feed, which is the direct
               analogue of the Meta export except that it needs no export

Neither knows anything about a platform beyond asking `platforms.detect`.
"""
import json
import subprocess

from . import acquire, config, db, platforms

# What a post gets filed under when it arrives this way. `collection` is
# normally your own hand-filing in Instagram, and CLAUDE.md says to respect it
# -- so a post that you never filed says so, rather than borrowing a label.
VIA_BOT = "Shared"
VIA_BOOKMARKS = "X Bookmarks"


def _tweet_metas(node, out=None):
    """Every tweet object in a gallery-dl `-j` dump, in feed order."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if "content" in node and isinstance(node.get("author"), dict):
            out.append(node)
            return out
        for v in node.values():
            _tweet_metas(v, out)
    elif isinstance(node, list):
        for v in node:
            _tweet_metas(v, out)
    return out


def _add(con, plat, ident, kind, user, saved_at=None, collection=None,
         caption=None, author=None):
    url = plat.canonical(ident, kind, user)
    new = db.upsert_post(con, ident, url, kind, saved_at, plat.key)
    # Never clobber: a tweet re-shared after extraction must not lose its
    # caption to a thinner second read of the same tweet.
    con.execute(
        "UPDATE posts SET collection=COALESCE(collection, ?), "
        "author=COALESCE(author, ?), caption=COALESCE(caption, ?), "
        "saved_at=COALESCE(saved_at, ?) WHERE shortcode=?",
        (collection, author, caption, saved_at, ident),
    )
    return new, url


def add_urls(urls, collection=VIA_BOT):
    """Ingest every recognised post URL found in `urls` (strings or one blob).

    Accepts raw text, so a forwarded chat message with commentary around the
    link works without the caller having to pick the URL out first.
    """
    text = "\n".join(urls) if isinstance(urls, (list, tuple)) else str(urls)
    found = platforms.find_all(text)
    con = db.init()

    added, known = [], []
    for plat, ident, kind, user in found:
        with con:
            new, url = _add(con, plat, ident, kind, user, collection=collection)
        db.reindex(con, ident)
        (added if new else known).append(
            {"shortcode": ident, "platform": plat.key, "url": url})
    return {"added": added, "known": known,
            "unrecognised": not found and bool(text.strip())}


def bookmarks(limit=None, collection=VIA_BOOKMARKS):
    """Sweep the live X bookmark feed into the database.

    saved_at is the tweet's own date, not the moment you bookmarked it -- X
    does not expose a bookmark timestamp. It still sorts the feed sensibly,
    which is all `prepare` and the vault use it for.
    """
    limit = limit or config.X_BOOKMARK_LIMIT
    cookies = acquire._cookie_args("twitter")
    if not cookies:
        raise RuntimeError(acquire.X_AUTH_HINT)

    r = subprocess.run(
        ["gallery-dl", *cookies, "-o", "text-tweets=true", "-j",
         "--range", f"1-{limit}", platforms.BOOKMARKS_URL],
        capture_output=True, text=True, timeout=600,
    )
    if not r.stdout.strip():
        tail = (r.stderr.strip().splitlines() or ["nothing returned"])[-1]
        raise RuntimeError(f"gallery-dl: {tail}")
    try:
        metas = _tweet_metas(json.loads(r.stdout))
    except json.JSONDecodeError:
        raise RuntimeError("could not parse gallery-dl -j output for the bookmark feed")

    con = db.init()
    added, known = [], []
    seen = set()
    for m in metas:
        ident = str(m.get("tweet_id") or m.get("id") or "").strip()
        if not ident.isdigit() or ident in seen:
            continue
        seen.add(ident)
        author = (m.get("author") or {})
        with con:
            new, url = _add(
                con, platforms.TWITTER, ident, "tweet", author.get("name"),
                saved_at=str(m.get("date") or "") or None,
                collection=collection,
                caption=m.get("content"),
                author=author.get("nick") or author.get("name"),
            )
        db.reindex(con, ident)
        (added if new else known).append(
            {"shortcode": ident, "platform": "twitter", "url": url})
    return {"added": added, "known": known, "scanned": len(seen)}
