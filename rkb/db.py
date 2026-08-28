"""SQLite access. One file, no server, FTS5 for search."""
import contextlib
import json
import sqlite3
from . import config


def connect():
    config.DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    # prepare and record can run concurrently; wait rather than failing outright.
    con.execute("PRAGMA busy_timeout = 15000")
    con.execute("PRAGMA journal_mode = WAL")
    return con


# Columns added after the first release; applied to existing databases on open.
_ADDED_EXTRACTION_COLUMNS = {"prompt": "TEXT"}

_ADDED_COLUMNS = {
    "reviewed": "TEXT",          # 'kept' | 'archived' -- set by `rkb review`
    # Which service the post came from. Backfills to 'instagram' because every
    # row that predates a second source came from there.
    "platform": "TEXT NOT NULL DEFAULT 'instagram'",
    "collection": "TEXT",
    "author": "TEXT",
    "author_link": "TEXT",
    "hashtags": "TEXT NOT NULL DEFAULT '[]'",
    "ocr_text": "TEXT",          # verbatim text read off the frames
}


def init():
    con = connect()
    with con:
        con.executescript((config.ROOT / "rkb" / "schema.sql").read_text())
    _migrate(con)
    return con


def _migrate(con):
    have = {r["name"] for r in con.execute("PRAGMA table_info(posts)")}
    with con:
        for col, decl in _ADDED_COLUMNS.items():
            if col not in have:
                con.execute(f"ALTER TABLE posts ADD COLUMN {col} {decl}")
    have = {r["name"] for r in con.execute("PRAGMA table_info(extractions)")}
    with con:
        for col, decl in _ADDED_EXTRACTION_COLUMNS.items():
            if col not in have:
                con.execute(f"ALTER TABLE extractions ADD COLUMN {col} {decl}")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(search_idx)")}
    if not {"collection", "prompt", "ocr_text"} <= cols:  # FTS changed -> rebuild
        with con:
            con.execute("DROP TABLE IF EXISTS search_idx")
            con.executescript((config.ROOT / "rkb" / "schema.sql").read_text())
        for r in con.execute("SELECT shortcode FROM posts").fetchall():
            reindex(con, r["shortcode"])


def upsert_post(con, shortcode, url, kind, saved_at=None, platform="instagram"):
    """Insert a saved post. Never clobbers work already done on it."""
    cur = con.execute(
        "INSERT INTO posts (shortcode, url, kind, saved_at, platform) "
        "VALUES (?,?,?,?,?) ON CONFLICT(shortcode) DO NOTHING",
        (shortcode, url, kind, saved_at, platform),
    )
    return cur.rowcount == 1


def reindex(con, shortcode, commit=True):
    """Rebuild the FTS row for one post from posts + extractions.

    Pass commit=False to run inside a caller's transaction. Callers that change
    a post AND reindex it must do both atomically: otherwise a failure here
    leaves the change committed with a stale index, and the caller reports an
    error for something that already happened.
    """
    row = con.execute(
        "SELECT p.shortcode, p.caption, p.transcript, p.collection, p.author, "
        "       p.hashtags, p.ocr_text, e.summary, e.detail, e.tools, e.links, "
        "       e.prompt, e.tags "
        "FROM posts p LEFT JOIN extractions e USING (shortcode) "
        "WHERE p.shortcode = ?",
        (shortcode,),
    ).fetchone()
    if row is None:
        return

    def flat(v):
        if not v:
            return ""
        try:
            return " ".join(str(x) for x in json.loads(v))
        except (json.JSONDecodeError, TypeError):
            return str(v)

    ctx = con if commit else contextlib.nullcontext()
    with ctx:
        con.execute("DELETE FROM search_idx WHERE shortcode = ?", (shortcode,))
        con.execute(
            "INSERT INTO search_idx "
            "(shortcode, summary, detail, tools, links, prompt, tags, caption, "
            " transcript, ocr_text, collection, author, hashtags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["shortcode"], row["summary"] or "", row["detail"] or "",
                flat(row["tools"]), flat(row["links"]), row["prompt"] or "",
                flat(row["tags"]),
                row["caption"] or "", row["transcript"] or "",
                row["ocr_text"] or "",
                row["collection"] or "", row["author"] or "", flat(row["hashtags"]),
            ),
        )
