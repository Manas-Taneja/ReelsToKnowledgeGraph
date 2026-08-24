"""FTS5 search over the knowledge base."""
import json
import sqlite3

from . import db


def _quote(query):
    """Make a query FTS5-safe without losing ordinary punctuation.

    FTS5 treats +, -, *, ^, : and quotes as operators, so a literal search for
    'chrF++' or 'C++' is a syntax error. Wrapping each bareword in double quotes
    turns it into a phrase term, which is what someone typing a tool name means.
    """
    terms = []
    for tok in query.split():
        if tok.upper() in ("AND", "OR", "NOT", "NEAR"):
            terms.append(tok.upper())          # keep deliberate operators
        else:
            terms.append('"' + tok.replace('"', '""') + '"')
    return " ".join(terms)


def search(query, limit=20):
    con = db.init()
    try:
        return _run(con, query, limit)
    except sqlite3.OperationalError:
        # Punctuation the user meant literally -- retry as quoted phrases.
        return _run(con, _quote(query), limit)


def _run(con, query, limit):
    rows = con.execute(
        "SELECT s.shortcode, p.url, p.saved_at, p.author, p.collection, p.status, "
        "       e.summary, e.tools, e.links, e.tags, e.actionable, "
        "       snippet(search_idx, -1, '\u2039', '\u203a', ' ... ', 14) AS hit "
        "FROM search_idx s "
        "JOIN posts p ON p.shortcode = s.shortcode "
        "LEFT JOIN extractions e ON e.shortcode = s.shortcode "
        "WHERE search_idx MATCH ? ORDER BY bm25(search_idx) LIMIT ?",
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def render(results):
    if not results:
        return "no matches"
    out = []
    for r in results:
        tools = ", ".join(json.loads(r["tools"] or "[]"))
        links = json.loads(r["links"] or "[]")
        tags = ", ".join(json.loads(r["tags"] or "[]"))
        head = r["summary"] or f"[{r['status']}] not yet extracted"
        by = f"@{r['author']}" if r["author"] else ""
        col = f" · {r['collection']}" if r["collection"] else ""
        out.append(f"— {head}")
        if by or col:
            out.append(f"  {by}{col}")
        if not r["summary"] and r["hit"]:
            out.append(f"  match: {' '.join(r['hit'].split())}")
        if tools:
            out.append(f"  tools: {tools}")
        for l in links:
            out.append(f"  link:  {l}")
        if tags:
            out.append(f"  tags:  {tags}")
        if r["actionable"]:
            out.append(f"  next:  {r['actionable']}")
        out.append(f"  {r['url']}")
        out.append("")
    return "\n".join(out)
