"""Stage 2 write-back: store extraction results and mark posts extracted."""
import json
import sys

from . import db, verify

FIELDS = ("summary", "detail", "tools", "links", "prompt", "tags", "actionable",
          "confidence")


def record(items, by="claude-code", check_links=True):
    if isinstance(items, dict):
        items = [items]
    con = db.init()
    written, unknown = [], []
    for item in items:
        sc = item.get("shortcode")
        if not sc:
            raise ValueError(f"entry is missing 'shortcode': {item}")
        if con.execute("SELECT 1 FROM posts WHERE shortcode=?", (sc,)).fetchone() is None:
            unknown.append(sc)
            continue
        vals = {k: item.get(k) for k in FIELDS}
        # A dead link is worse than no link: it clears the post from review and
        # sends you nowhere. Validate before storing, repairing OCR truncations.
        if check_links and vals.get("links"):
            kept, repairs, dead = verify.verify_links(
                vals["links"] if isinstance(vals["links"], list) else [vals["links"]])
            for old_u, new_u in repairs:
                print(f"  {sc}: repaired {old_u} -> {new_u}")
            for d in dead:
                print(f"  {sc}: DROPPED dead link {d}")
            vals["links"] = kept
        for k in ("tools", "links", "tags"):
            v = vals[k] or []
            vals[k] = json.dumps(v if isinstance(v, list) else [v], ensure_ascii=False)
        with con:
            con.execute(
                "INSERT INTO extractions (shortcode, summary, detail, tools, links, "
                "prompt, tags, actionable, confidence, extracted_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(shortcode) DO UPDATE SET "
                "summary=excluded.summary, detail=excluded.detail, tools=excluded.tools, "
                "links=excluded.links, prompt=excluded.prompt, tags=excluded.tags, "
                "actionable=excluded.actionable, "
                "confidence=excluded.confidence, extracted_by=excluded.extracted_by, "
                "extracted_at=datetime('now')",
                (sc, vals["summary"] or "", vals["detail"], vals["tools"], vals["links"],
                 vals["prompt"], vals["tags"], vals["actionable"], vals["confidence"], by),
            )
            con.execute("UPDATE posts SET status='extracted' WHERE shortcode=?", (sc,))
            db.reindex(con, sc, commit=False)
        written.append(sc)
    return {"written": written, "unknown_shortcodes": unknown}


def record_from(path, check_links=True):
    raw = sys.stdin.read() if path in (None, "-") else open(path).read()
    return record(json.loads(raw), check_links=check_links)
