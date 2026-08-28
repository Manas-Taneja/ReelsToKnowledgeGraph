"""Turn a Meta 'Export your information' dump into rows in the posts table.

The export ships two files worth reading:
  saved_posts.json       one entry per saved post: URL, caption, hashtags, owner
  saved_collections.json your own hand-filed collections, each listing its posts

Collections matter because they are categorisation you already did by hand, so
they are recorded on the post and are searchable. They also drive exclusions:
collections listed in data/excluded_collections.txt never enter the database at
all, which keeps re-imports idempotent instead of resurrecting dropped posts.

The export's exact shape shifts between versions, so anything we can't parse
structurally falls back to scraping Instagram permalinks out of the raw text.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config, db

URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(reel|reels|p|tv)/([A-Za-z0-9_-]{5,})"
)
EXCLUDE_FILE = config.DATA / "excluded_collections.txt"


# --------------------------------------------------------------------------- #
# generic helpers
# --------------------------------------------------------------------------- #
def _shortcodes(node):
    """Every Instagram shortcode anywhere under this node, in order."""
    if isinstance(node, dict):
        for v in node.values():
            yield from _shortcodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _shortcodes(v)
    elif isinstance(node, str):
        m = URL_RE.search(node)
        if m:
            yield m.group(2), ("reel" if m.group(1) in ("reel", "reels") else "post")


def _labels(entry):
    """Flatten an entry's label_values into {label: value} for the simple ones."""
    out = {}
    for lv in entry.get("label_values", []) or []:
        if "label" in lv and "value" in lv:
            out[lv["label"]] = lv["value"]
    return out


def _section(entry, title):
    for lv in entry.get("label_values", []) or []:
        if lv.get("title") == title:
            return lv.get("dict") or []
    return []


def _iso(ts):
    if not isinstance(ts, (int, float)) or ts <= 0:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(timespec="seconds")


def _mojibake(s):
    """Meta writes UTF-8 bytes as latin-1 escapes; recover the real characters."""
    if not s:
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


# --------------------------------------------------------------------------- #
# the two known files
# --------------------------------------------------------------------------- #
def parse_collections(path):
    """-> {shortcode: collection_name}"""
    try:
        data = json.loads(Path(path).read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    for entry in data if isinstance(data, list) else []:
        name = _mojibake(_labels(entry).get("Name")) or "?"
        for sc, _kind in _shortcodes(entry.get("label_values", [])):
            out.setdefault(sc, name)
    return out


def parse_posts(path):
    """-> [dict] one per saved post, richest data we can pull from the export."""
    try:
        data = json.loads(Path(path).read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = []
    for entry in data if isinstance(data, list) else []:
        found = list(_shortcodes(entry.get("label_values", [])))
        if not found:
            continue
        shortcode, kind = found[0]          # first URL is the post itself
        lab = _labels(entry)

        hashtags = [_mojibake(h.get("value")) for tag in _section(entry, "Hashtags")
                    for h in (tag.get("dict") or [])
                    if h.get("label") == "Name" and h.get("value")]

        author = author_link = None
        for owner in _section(entry, "Owner"):
            for f in owner.get("dict") or []:
                if f.get("label") == "Username":
                    author = f.get("value")
                elif f.get("label") == "URL" and not author_link:
                    author_link = f.get("value")

        rows.append({
            "shortcode": shortcode,
            "kind": kind,
            "saved_at": _iso(entry.get("timestamp")),
            "caption": _mojibake(lab.get("Caption")) or None,
            "hashtags": hashtags,
            "author": author,
            "author_link": author_link,
        })
    return rows


# --------------------------------------------------------------------------- #
def excluded_collections():
    if not EXCLUDE_FILE.exists():
        return set()
    return {l.strip().lower() for l in EXCLUDE_FILE.read_text().splitlines()
            if l.strip() and not l.startswith("#")}


def set_excluded(names):
    EXCLUDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXCLUDE_FILE.write_text(
        "# Collections in this list are never imported.\n"
        + "\n".join(sorted(names)) + "\n")


def import_paths(paths, exclude=None):
    """Import every export file under the given paths. Returns a report dict."""
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += sorted(p.rglob("*.json")) + sorted(p.rglob("*.txt"))
        elif p.exists():
            files.append(p)
    # Never re-ingest the downloader's own sidecar JSON as if it were an export.
    files = [f for f in files if config.MEDIA_DIR not in f.resolve().parents]

    exclude = {e.lower() for e in (exclude if exclude is not None
                                   else excluded_collections())}

    collections, posts, loose = {}, {}, {}
    for f in files:
        if f.name == "saved_collections.json":
            collections.update(parse_collections(f))
        elif f.name == "saved_posts.json":
            for row in parse_posts(f):
                posts.setdefault(row["shortcode"], row)
        else:
            # Unknown file: still harvest any permalinks it contains.
            try:
                node = json.loads(f.read_text(errors="replace"))
            except (json.JSONDecodeError, OSError):
                node = f.read_text(errors="replace")
            for sc, kind in _shortcodes(node):
                loose.setdefault(sc, {"shortcode": sc, "kind": kind, "saved_at": None,
                                      "caption": None, "hashtags": [], "author": None,
                                      "author_link": None})
    for sc, row in loose.items():
        posts.setdefault(sc, row)

    con = db.init()
    added = updated = skipped = 0
    skipped_by = {}
    for sc, row in posts.items():
        col = collections.get(sc)
        if col and col.lower() in exclude:
            skipped += 1
            skipped_by[col] = skipped_by.get(col, 0) + 1
            continue
        url = f"https://www.instagram.com/{'reel' if row['kind'] == 'reel' else 'p'}/{sc}/"
        with con:
            new = db.upsert_post(con, sc, url, row["kind"], row["saved_at"])
            # Export metadata is authoritative, but never clobber pipeline
            # output -- and a later, thinner export that omits the collection
            # or owner block must not null out what an earlier one supplied.
            con.execute(
                "UPDATE posts SET collection=COALESCE(?, collection), "
                "author=COALESCE(?, author), "
                "author_link=COALESCE(?, author_link), "
                "hashtags=COALESCE(?, hashtags), "
                "caption=COALESCE(caption, ?) WHERE shortcode=?",
                (col, row["author"], row["author_link"],
                 json.dumps(row["hashtags"], ensure_ascii=False)
                 if row["hashtags"] else None,
                 row["caption"], sc),
            )
        db.reindex(con, sc)
        added += 1 if new else 0
        updated += 0 if new else 1

    total = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    return {"files": len(files), "in_export": len(posts),
            "added": added, "updated": updated,
            "skipped_excluded": skipped, "skipped_by_collection": skipped_by,
            "excluded_collections": sorted(exclude), "total_in_db": total}
