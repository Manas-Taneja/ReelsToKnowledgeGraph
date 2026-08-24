"""Apply decisions made on the dashboard back into the database."""
import json
import re
import shutil
import subprocess
import sys

from . import config, db, verify

ACTIONS = ("link", "prompt", "keep", "recheck", "junk", "reset")


def empty():
    return {"linked": [], "kept": [], "recheck": [], "archived": [],
            "reset": [], "unchanged": [], "unknown": [], "dead": [],
            "urls": {}, "notes": {}}


def apply(decisions):
    con = db.init()
    done = empty()
    for sc, d in decisions.items():
        action = (d or {}).get("action")
        if action not in ACTIONS:
            continue
        row = con.execute(
            "SELECT e.links, p.status, p.reviewed FROM extractions e "
            "JOIN posts p USING (shortcode) WHERE e.shortcode=?", (sc,)).fetchone()
        if row is None:
            done["unknown"].append(sc)
            continue

        url = (d.get("url") or "").strip()
        if action == "link":
            # A wrong link is the one unrecoverable error here: a missing one
            # comes back round the queue, a dead one just sends you nowhere.
            # Check it before it lands, and repair OCR truncations.
            state, url = verify.check(url)
            if state == "dead":
                done["dead"].append((sc, url))
                continue

        # Applying the same decision twice is a no-op -- say so, rather than
        # reporting a success that makes a stale clipboard look like new work.
        links_now = json.loads(row["links"] or "[]")
        already = (
            (action == "link" and url in links_now)
            or (action in ("prompt", "keep") and row["reviewed"] == "kept")
            or (action == "junk" and row["status"] == "archived")
            or (action == "recheck" and row["status"] == "prepared")
            or (action == "reset" and row["reviewed"] is None
                and row["status"] == "extracted")
        )
        if already:
            done["unchanged"].append(sc)
            continue
        with con:
            if action == "link":
                links = links_now
                links.append(url)
                done["urls"][sc] = url
                con.execute("UPDATE extractions SET links=? WHERE shortcode=?",
                            (json.dumps(links, ensure_ascii=False), sc))
                con.execute("UPDATE posts SET reviewed='kept' WHERE shortcode=?", (sc,))
                done["linked"].append(sc)
            elif action in ("prompt", "keep"):
                con.execute("UPDATE posts SET reviewed='kept' WHERE shortcode=?", (sc,))
                done["kept"].append(sc)
            elif action == "reset":
                con.execute("UPDATE posts SET reviewed=NULL, status='extracted' "
                            "WHERE shortcode=?", (sc,))
                done["reset"].append(sc)
            elif action == "recheck":
                # Back into the extraction queue for another look at the frames.
                con.execute("UPDATE posts SET status='prepared', reviewed=NULL "
                            "WHERE shortcode=?", (sc,))
                done["recheck"].append(sc)
            else:
                con.execute("UPDATE posts SET status='archived', reviewed='archived' "
                            "WHERE shortcode=?", (sc,))
                done["archived"].append(sc)
            # Same transaction: if the index update fails, the decision rolls
            # back too, so an error on screen means nothing was written.
            db.reindex(con, sc, commit=False)
        if (d.get("note") or "").strip():
            done["notes"][sc] = d["note"].strip()
    return done


HELP = """no decisions found.

The dashboard's 'Copy decisions' button puts them on your clipboard, so:

    ./bin/rkb dashboard      # build it
    open dashboard.html      # decide, then hit 'Copy decisions'
    ./bin/rkb review         # reads the clipboard

Or pipe them in explicitly:  ./bin/rkb review - < decisions.json"""


def _read(path):
    """No arg -> the clipboard (that's where the dashboard puts them).
    '-' -> stdin. Anything else -> a file."""
    if path == "-":
        return sys.stdin.read()
    if path:
        return open(path).read()
    if shutil.which("pbpaste"):
        return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    return "" if sys.stdin.isatty() else sys.stdin.read()


def _current_build():
    f = config.ROOT / "dashboard.html"
    if not f.exists():
        return None
    m = re.search(r"BUILD='([0-9a-f]+)'", f.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def _check_build(sent):
    """Tell the user plainly when a paste came from a stale page."""
    now = _current_build()
    if now is None or sent == now:
        return
    # A stale stamp is worth flagging, never worth discarding real decisions.
    print(f"note: these came from dashboard build {sent or '(unstamped)'}, "
          f"current is {now}.\n      Applying them anyway.\n", file=sys.stderr)


def apply_from(path):
    raw = (_read(path) or "").strip()
    if not raw:
        sys.exit(HELP)
    try:
        decisions = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"that isn't valid JSON ({e}).\n\n"
                 f"Expected what the dashboard's 'Copy decisions' button produces, "
                 f"e.g.\n"
                 f'  {{"Db6Z0QXsyK2": {{"action": "junk"}}}}\n\n'
                 f"got: {raw[:120]!r}")
    if not isinstance(decisions, dict):
        sys.exit(f"expected a JSON object of shortcode -> decision, "
                 f"got {type(decisions).__name__}")
    _check_build(decisions.pop("_build", None))
    return apply(decisions)
