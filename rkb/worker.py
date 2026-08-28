"""Run one prepare batch at a time, off the calling thread.

Ingest deliberately does not download. Recording a forwarded link costs
milliseconds; preparing it costs a video download, ffmpeg, whisper and OCR on
this machine. Those are not the same act and should not share a trigger --
otherwise saving a link while you are out spins the fans on a laptop you are
not sitting at.

So the queue is just `posts.status = 'new'`, durable in SQLite, and something
has to ask for it to be drained: `rkb prepare`, /prepare in the chat, or the
button on the save reply. This module is only the "don't run two at once, and
don't block the caller" part.
"""
import threading

from . import config, db, ingest, prepare

_LOCK = threading.Lock()
_RUNNING = False


def busy():
    return _RUNNING


def pending(con=None, collection=None):
    """How many posts are waiting to be prepared."""
    con = con or db.init()
    sql = "SELECT COUNT(*) n FROM posts WHERE status IN ('new','failed')"
    args = []
    if collection:
        sql += " AND collection = ?"
        args.append(collection)
    return con.execute(sql, args).fetchone()["n"]


def run_batch(limit=None, on_done=None, retry=True):
    """Drain the queue in a background thread.

    Returns False if a batch is already running -- two concurrent batches would
    fight over the same rows and hammer Instagram in parallel, which is the one
    thing `prepare`'s sleep exists to prevent.
    """
    global _RUNNING
    with _LOCK:
        if _RUNNING:
            return False
        _RUNNING = True

    def go():
        global _RUNNING
        try:
            result = prepare.prepare_batch(
                limit=limit or config.BATCH_LIMIT, retry=retry)
        except Exception as e:                  # never leave the flag stuck
            result = {"prepared": [], "failed": [("batch", str(e)[:200])]}
        finally:
            with _LOCK:
                _RUNNING = False
        if on_done:
            try:
                on_done(result)
            except Exception:
                pass

    threading.Thread(target=go, daemon=True).start()
    return True


def summary(con, shortcode):
    """What a front door says back about one post."""
    import json
    row = con.execute(
        "SELECT p.shortcode, p.url, p.platform, p.status, p.error, p.author, "
        "       e.summary, e.links, e.actionable "
        "FROM posts p LEFT JOIN extractions e USING (shortcode) "
        "WHERE p.shortcode=?", (shortcode,)).fetchone()
    if not row:
        return None
    out = dict(row)
    try:
        out["links"] = json.loads(out["links"] or "[]")
    except json.JSONDecodeError:
        out["links"] = []
    return out


def describe(post):
    """One line about a post we already hold."""
    bits = [post.get("summary") or f"status: {post.get('status')}"]
    bits += (post.get("links") or [])[:3]
    if post.get("error"):
        bits.append(f"last error: {post['error'][:120]}")
    return " — ".join(bits)
