"""Classify posts by whether they carry a payload worth keeping.

Payloads are ranked, not equal:

  1. a repo/payload link  -- the thing you actually wanted
  2. a prompt, verbatim   -- the fallback when no link exists

A link clears a post automatically. Everything else goes to the review queue for
a human decision, because "no link" has several causes that only a person can
tell apart: the link was never on screen, it was on screen and extraction missed
it, the creator gated it behind a comment, or the post genuinely is a prompt and
needs no link. Guessing between those is exactly how a good post gets deleted.

  keep      a repo/payload link is recorded -- nothing to decide
  review    no link: needs your eyes (sub-flagged prompt / gated / bare)
  unknown   not extracted yet -- never judged, never proposed for removal

Posts that haven't been extracted yet are reported as `unknown` and are never
proposed for removal: with no frames read, "no links" means "nobody looked".
"""
import json
import re
import sqlite3
from urllib.parse import urlparse

from . import db

# "comment X and I'll send you the link/PDF" -- the payload is not in the post.
GATE = re.compile(
    r"(comment|dm)\s+[\"'\u201c\u2018]?[A-Za-z]{2,15}[\"'\u201d\u2019]?"
    r"[^.\n]{0,50}?(send|share|drop|receive|get\b|i'?ll)"
    r"|link\s+in\s+bio"
    r"|(send|drop)\s+(you|it)\s+the\s+(link|repo|pdf|prompt|guide|setup)",
    re.I,
)
# A caption that contains the actual goods rather than a description of them.
PROMPT_MARKER = re.compile(
    r"full prompt|prompt:|here'?s the prompt|copy this|step 1|^\s*1[.)]\s", re.I | re.M
)
PAYLOAD_HOSTS = ("github.com", "gitlab.com", "huggingface.co", "npmjs.com", "pypi.org")


def _links(raw):
    try:
        return [l for l in json.loads(raw or "[]") if isinstance(l, str)]
    except (json.JSONDecodeError, TypeError):
        return []


def _payload_links(links, author_link):
    """Drop the creator's own homepage -- that's attribution, not a payload."""
    own = urlparse(author_link or "").netloc.lower().removeprefix("www.")
    out = []
    for l in links:
        host = urlparse(l).netloc.lower().removeprefix("www.")
        if not host or (own and host == own):
            continue
        # A bare product domain (tolgee.io, miniflux.app) IS the payload for a
        # self-hosted tool. The creator's own promo link is already excluded by
        # the author_link check above, so no further filtering is needed here.
        out.append(l)
    return out


def classify(row):
    links = _payload_links(_links(row["links"]), row["author_link"])
    tools = _links(row["tools"])
    prompt = (row["prompt"] or "").strip()
    text = f"{row['caption'] or ''}\n{row['transcript'] or ''}"
    gated = bool(GATE.search(text))
    # The post is *about* a prompt -- whether or not we captured it.
    promises_prompt = bool(PROMPT_MARKER.search(text))

    if row["status"] == "archived":
        return "archived", "archived by review"
    if row["status"] != "extracted":
        return "unknown", "not extracted yet - frames never read"
    # Already been through the dashboard -- don't ask again.
    if row["reviewed"] == "kept":
        return "keep", f"reviewed by you{' - prompt kept' if prompt else ''}"

    # 1. A link is the payload. Nothing further to decide.
    if links:
        return "keep", f"{len(links)} payload link(s)"

    # 2. No link -> the user reads the OCR on the card and decides.
    if gated:
        return "review", "no link; payload withheld behind a comment-wall"
    if tools:
        return "review", f"no link; names {', '.join(tools[:3])} - findable?"
    return "review", "no link, no prompt, nothing recorded"


def triage():
    con = db.init()
    rows = con.execute(
        "SELECT p.shortcode, p.author, p.author_link, p.caption, p.transcript, "
        "       p.status, p.reviewed, p.media_dir, p.ocr_text, e.summary, e.links, "
        "       e.tools, e.prompt, "
        "       e.actionable "
        "FROM posts p LEFT JOIN extractions e USING (shortcode) "
        "ORDER BY p.saved_at DESC"
    ).fetchall()
    out = {}
    for r in rows:
        verdict, why = classify(r)
        out.setdefault(verdict, []).append((dict(r), why))
    return out


def render(groups):
    order = ["review", "keep", "archived", "unknown"]
    blurb = {
        "review":  "NO LINK — needs your review (./bin/rkb dashboard)",
        "keep":    "has a repo/payload link — cleared automatically",
        "archived": "you archived these; media is still on disk",
        "unknown": "not extracted yet — cannot be judged, never proposed for removal",
    }
    lines = []
    for k in order:
        items = groups.get(k, [])
        if not items:
            continue
        lines.append(f"\n{k.upper():<8} {len(items):>3}   {blurb[k]}")
        lines.append("─" * 78)
        if k in ("unknown", "archived"):
            lines.append(f"  ({len(items)} posts — run extraction first)")
            continue
        for r, why in items:
            cap = (r["caption"] or "").strip().splitlines()
            head = r["summary"] or (cap[0] if cap else "(no caption)")
            lines.append(f"  {r['shortcode']}  @{r['author']}")
            lines.append(f"     {head[:88]}")
            lines.append(f"     → {why}")
    return "\n".join(lines)
