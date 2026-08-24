"""Check that recorded links actually resolve, and repair the obvious breaks.

A wrong link is the one unrecoverable error in this pipeline: a missing link
sends a post to the review queue where you can fix it, but a plausible-looking
dead URL clears the post and silently sends you nowhere.

OCR is the main source of these. Text read off a slide can be cut off mid-word,
so `.../network/dependents` arrives as `.../network/dependen` -- a URL that
looks completely reasonable and 404s. That is a deterministic bug, so it gets a
deterministic fix rather than being left to whichever model did the extraction.
"""
import json
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

from . import db

TIMEOUT = 8
PAUSE = 0.2                      # be polite; these are other people's servers
UA = "Mozilla/5.0 (compatible; rkb-link-check/1.0)"

# Path segments that OCR commonly truncates. If the last segment of a dead URL
# is a strict prefix of one of these, the full form is tried.
GITHUB_TAILS = ("stargazers", "dependents", "network", "issues", "forks",
                "releases", "discussions", "pulls", "wiki", "watchers")


def _head(url):
    """Return an HTTP status, following redirects. None means unreachable."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return r.status
    except urllib.error.HTTPError as e:
        if e.code == 405:                      # server dislikes HEAD -> try GET
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                    return r.status
            except Exception:
                return None
        return e.code
    except Exception:
        return None                            # DNS/TLS/timeout -> unknown, not dead


def _candidates(url):
    """Plausible repairs for a truncated URL, most likely first."""
    p = urlparse(url)
    parts = [s for s in p.path.split("/") if s]
    if not parts:
        return []
    out, last = [], parts[-1]
    for full in GITHUB_TAILS:
        if last != full and full.startswith(last) and len(last) >= 3:
            cand = urlunparse(p._replace(path="/" + "/".join(parts[:-1] + [full])))
            # An auth-gated completion is right even though it 404s anonymously.
            if full in AUTH_GATED and _auth_gated(cand):
                return [cand]
            out.append(cand)
    # ".../network" on its own is really ".../network/dependents"
    if last == "network":
        out.append(urlunparse(p._replace(path=p.path.rstrip("/") + "/dependents")))
    # last resort: the repo root, which is better than a 404 deep link
    if len(parts) > 2 and p.netloc.endswith("github.com"):
        out.append(urlunparse(p._replace(path="/" + "/".join(parts[:2]))))
    return out


# GitHub serves these 404 to logged-out requests. They are not dead links --
# they render fine in a browser you're signed into -- so a 404 here means
# "needs auth", not "wrong URL". Verified 2026-08-24 against yt-dlp and
# py-linkedin-jobs-scraper: /stargazers 404s anonymously while the repo root 200s.
AUTH_GATED = ("stargazers", "watchers")


def _auth_gated(url):
    """True if this is a login-only GitHub page on a repo that does exist."""
    p = urlparse(url)
    parts = [s for s in p.path.split("/") if s]
    if not p.netloc.endswith("github.com") or len(parts) != 3:
        return False
    if parts[2] not in AUTH_GATED:
        return False
    root = urlunparse(p._replace(path="/" + "/".join(parts[:2])))
    return (_head(root) or 500) < 400


def check(url):
    """-> (verdict, url). verdict is 'ok' | 'repaired' | 'dead' | 'unknown'."""
    status = _head(url)
    if status is None:
        return "unknown", url
    if status < 400:
        return "ok", url
    if status == 404 and _auth_gated(url):
        return "ok", url
    for cand in _candidates(url):
        time.sleep(PAUSE)
        code = _head(cand) or 500
        # Same rule as above: a login-only page 404s anonymously but is correct.
        if code < 400 or (code == 404 and _auth_gated(cand)):
            return "repaired", cand
    return "dead", url


def verify_links(links):
    """Validate a list of URLs. Returns (kept, repairs, dead)."""
    kept, repairs, dead = [], [], []
    for url in links:
        verdict, final = check(url)
        if verdict == "repaired":
            repairs.append((url, final))
            kept.append(final)
        elif verdict == "dead":
            dead.append(url)
        else:
            kept.append(final)
        time.sleep(PAUSE)
    return kept, repairs, dead


def run(limit=None, shortcodes=None):
    """Sweep the whole knowledge base."""
    con = db.init()
    sql = ("SELECT e.shortcode, e.links FROM extractions e JOIN posts p USING (shortcode) "
           "WHERE p.status != 'archived' AND e.links != '[]'")
    params = []
    if shortcodes:
        sql += f" AND e.shortcode IN ({','.join('?' * len(shortcodes))})"
        params += list(shortcodes)
    sql += " ORDER BY p.saved_at DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    rows = con.execute(sql, params).fetchall()
    tot = {"checked": 0, "repaired": [], "dead": []}
    for i, r in enumerate(rows, 1):
        links = json.loads(r["links"] or "[]")
        print(f"[{i}/{len(rows)}] {r['shortcode']} ({len(links)} link(s)) ...", flush=True)
        kept, repairs, dead = verify_links(links)
        tot["checked"] += len(links)
        for old, new in repairs:
            print(f"    repaired: {old}\n           -> {new}")
        for d in dead:
            print(f"    DEAD, removed: {d}")
        tot["repaired"] += repairs
        tot["dead"] += [(r["shortcode"], d) for d in dead]
        if repairs or dead:
            with con:
                con.execute("UPDATE extractions SET links=? WHERE shortcode=?",
                            (json.dumps(kept, ensure_ascii=False), r["shortcode"]))
                db.reindex(con, r["shortcode"], commit=False)
    return tot
