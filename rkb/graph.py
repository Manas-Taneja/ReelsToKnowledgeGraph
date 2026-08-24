"""Apply graph-view settings to an Obsidian vault.

Obsidian owns `.obsidian/graph.json` while it is running: it holds the graph
state in memory and writes it back on quit, silently discarding anything edited
underneath it. So this refuses to run against a live Obsidian rather than
pretending to have worked.

The filter is the substantive part. Every edge in the vault runs post -> hub, so
a graph containing the posts is a document graph. Hiding them leaves the hubs,
which link to each other by co-occurrence -- a map of what the library is about
rather than of what is in it.
"""
import json
import shutil
import subprocess
from pathlib import Path

from . import concepts, config, db, vault

# Repos.md and Prompts.md link to nearly every post, so left in they would draw
# as two enormous hubs and undo the thinning below. They are tables to read, not
# concepts to place.
HIDE = ['-path:"Reels/"', '-path:"Authors/"', '-path:"Index"',
        '-path:"Repos.md"', '-path:"Prompts.md"', '-path:"attachments/"']

# One colour per detected cluster, biggest first. Picked to stay distinguishable
# on both a light and a dark canvas, and to stay apart from each other for the
# common forms of colour blindness -- amber/teal/violet/blue read as four
# different things where red/green would read as two.
PALETTE = ["#E8A33D", "#4FC3A1", "#A78BFA", "#5B9DF9",
           "#F2789F", "#E4C441", "#8FBF6A", "#C98BDB"]

LAYOUT = {
    "showTags": False,
    "showAttachments": False,
    # A node with no edges is a labelled dot saying nothing. They are still
    # notes; they are just not part of the map.
    "showOrphans": False,
    "collapse-filter": False,
    "collapse-color-groups": False,
    "textFadeMultiplier": 1.2,    # labels stay on when zoomed out
    "nodeSizeMultiplier": 1.5,
    "lineSizeMultiplier": 0.9,
    "centerStrength": 0.42,
    "repelStrength": 11,
    "linkStrength": 0.75,
    "linkDistance": 190,
    "scale": 1.0,
}


def _rgb(hexstr):
    h = hexstr.lstrip("#")
    return int(h[0:2], 16) * 65536 + int(h[2:4], 16) * 256 + int(h[4:6], 16)


def running():
    return subprocess.run(["pgrep", "-x", "Obsidian"],
                          capture_output=True).returncode == 0


def _vault_root(out=None):
    """Where .obsidian actually lives -- the vault may be rooted at the repo."""
    v = vault.vault_dir(out)
    for cand in (v, v.parent):
        if (cand / ".obsidian").is_dir():
            return cand
    return v


def _load():
    con = db.init()
    rows = [dict(r) for r in con.execute(
        "SELECT e.tools, e.tags FROM posts p LEFT JOIN extractions e "
        "USING (shortcode) WHERE p.status != 'archived'").fetchall()]
    return concepts.build(rows)


def _note(folder, name):
    return f'path:"{folder}/{vault._clean(name)}.md"'


def plan(concepts_only=True):
    """The filter and the colour groups, computed from the library itself."""
    g = _load()
    hide = list(HIDE) if concepts_only else []
    # A stopword hub keeps its note but leaves the map -- it has no edges, so
    # it would only ever draw as a stray dot.
    hide += ["-" + _note(f, g["display"][(f, k)]) for f, k in sorted(g["stopwords"])]

    groups = []
    for i, members in enumerate(concepts.communities(g)):
        if len(members) < 2:
            continue
        query = " OR ".join(_note(f, g["display"][(f, k)])
                            for f, k in sorted(members))
        groups.append((query, PALETTE[i % len(PALETTE)],
                       sorted(k for _, k in members)))
    return " ".join(hide), groups, g


def apply(out=None, concepts_only=True):
    if running():
        raise SystemExit(
            "Obsidian is running, and it rewrites .obsidian/graph.json from "
            "memory when it exits —\nanything written now would be discarded.\n\n"
            "  Quit Obsidian, run this again, then reopen.\n\n"
            "Or set the filter by hand, which takes effect immediately:\n"
            "  Graph view → Filters → search box:\n"
            f"    {' '.join(HIDE)}")

    root = _vault_root(out)
    path = root / ".obsidian" / "graph.json"
    if not path.parent.is_dir():
        raise SystemExit(f"no Obsidian config at {path.parent} — open the vault "
                         f"in Obsidian once first")

    current = {}
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
        try:
            current = json.loads(path.read_text())
        except json.JSONDecodeError:
            pass

    search, groups, g = plan(concepts_only)
    current.update(LAYOUT)
    current["search"] = search
    current["colorGroups"] = [{"query": q, "color": {"a": 1, "rgb": _rgb(c)}}
                              for q, c, _ in groups]
    path.write_text(json.dumps(current, indent=2))
    return {"path": str(path), "filter": search, "groups": groups,
            "nodes": len(g["nodes"]) - len(g["stopwords"]),
            "edges": len(g["edges"]),
            "rescued": {n[1]: o[1] for n, o in g["rescued"].items()},
            "joined": [(a[1], b[1]) for a, b in g["joined"]],
            "stopwords": sorted(k for _, k in g["stopwords"])}
