"""Read the decisions you made in Obsidian back into the database.

The vault is a generated view of SQLite, so anything rkb writes is overwritten
on the next render. The review workflow is the one exception: three properties
on each queued note -- `review`, `add_link` and `review_note` -- belong to you,
and this module carries them into the database *before* the vault is rebuilt
from it. That keeps SQLite the source of truth while letting Obsidian be the
place you actually make the call.

    review: keep      the post is worth keeping as-is
    review: junk      archive it (reversible; media stays on disk)
    review: recheck   put it back in the extraction queue for another look
    review: reset     undo a previous decision
    add_link: <url>   record the payload URL you found in the OCR

`add_link` implies keep, so pasting a URL is a single action. A synced note is
re-rendered with `review: done` and an empty `add_link`, so the queue empties
itself as you work through it.
"""
import time

import yaml

from . import review, vault
from .vault import frontmatter, scalar as _scalar

# What you can type in the `review` property. The aliases exist because the
# obvious synonym should not be a silent no-op.
VOCAB = {
    "keep": "keep", "useful": "keep", "yes": "keep",
    "junk": "junk", "archive": "junk", "drop": "junk", "no": "junk",
    "recheck": "recheck", "re-extract": "recheck", "reextract": "recheck",
    "reset": "reset", "undo": "reset",
}
INERT = ("", "pending", "done", "none", "null")


def _decision(fm):
    """(decision, problem) for one note's properties."""
    word = _scalar(fm.get("review")).lower()
    url = _scalar(fm.get("add_link"))
    note = _scalar(fm.get("review_note"))

    if word and word not in INERT and word not in VOCAB:
        return None, (f"review: {word!r} isn't one of "
                      f"{', '.join(sorted(set(VOCAB.values())))}")
    action = VOCAB.get(word)

    if url and action in ("junk", "recheck", "reset"):
        # Contradictory: you pasted a payload and also threw the post away.
        # Guessing which you meant is exactly how a good link gets lost.
        return None, f"both add_link and review: {action} — pick one"
    if url:
        return {"action": "link", "url": url, "note": note}, None
    if action:
        return {"action": action, "note": note}, None
    return None, None


def collect(out=None):
    """Walk the vault's reel notes and gather everything you decided."""
    reels = vault.vault_dir(out) / vault.REELS
    decisions, problems = {}, []
    if not reels.is_dir():
        return decisions, problems
    for path in sorted(reels.glob("*.md")):
        try:
            fm = frontmatter(path)
        except yaml.YAMLError as e:
            problems.append((path.name, f"unreadable properties ({e.__class__.__name__})"))
            continue
        if not fm or not fm.get("shortcode"):
            continue
        decision, problem = _decision(fm)
        if problem:
            problems.append((path.name, problem))
        elif decision:
            decisions[str(fm["shortcode"])] = decision
    return decisions, problems


def sync(out=None):
    decisions, problems = collect(out)
    result = review.apply(decisions) if decisions else review.empty()
    result["problems"] = problems
    result["seen"] = len(decisions)
    return result


def changed(result):
    return any(result[k] for k in
               ("linked", "kept", "recheck", "archived", "reset"))


def watch(out=None, interval=2.0, on_change=None):
    """Poll the vault and sync the moment you change a property.

    Re-rendering rewrites the notes it just synced, which bumps their mtimes --
    but the second pass finds `review: done` and nothing to apply, so the loop
    settles instead of running away.
    """
    reels = vault.vault_dir(out) / vault.REELS
    seen, reported = {}, None
    while True:
        now = {p: p.stat().st_mtime for p in reels.glob("*.md")}
        if now != seen:
            seen = now
            result = sync(out)
            # An unfixed problem is still a problem, but repeating it on every
            # keystroke elsewhere in the vault is just noise.
            worth_saying = changed(result) or result["problems"] != reported
            reported = result["problems"]
            if worth_saying:
                if on_change:
                    on_change(result)
                seen = {p: p.stat().st_mtime for p in reels.glob("*.md")}
        time.sleep(interval)
