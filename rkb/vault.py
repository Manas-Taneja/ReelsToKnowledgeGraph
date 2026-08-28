"""Render the knowledge base as an Obsidian vault.

SQLite stays the source of truth; the vault is a view of it. That means
`rkb vault` is safe to re-run after every extraction batch -- notes are
rewritten from the database, so nothing drifts.

Anything you type below the marker at the end of a note is preserved.
"""
import itertools
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from . import concepts, config, db, platforms, triage

MARKER = "<!-- rkb:end · your own notes below this line survive regeneration -->"
STAMP = "rkb_generated"          # frontmatter flag: safe for rkb to delete/rewrite

TOOLS, TOPICS, AUTHORS = "Tools", "Topics", "Authors"

# Source notes live in a folder named for where the post came from -- Reels/
# for Instagram, Tweets/ for X. The folder is cosmetic: Tools/ and Topics/ hubs
# span every platform, so the concept map stays one map. What is split is only
# the pile of source notes, which is the pile you browse by hand.
POST_FOLDERS = platforms.folders()
ATTACH = "attachments"

# Obsidian chokes on these in filenames and wikilinks.
_BAD = re.compile(r'[\\/:*?"<>|#^\[\]]+')


# --------------------------------------------------------------------------- helpers

def _clean(text, limit=None):
    text = " ".join(_BAD.sub(" ", (text or "")).split())
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:-") + "…"
    return text


def _jlist(v):
    try:
        out = json.loads(v or "[]")
        return [x for x in out if isinstance(x, str) and x.strip()]
    except (json.JSONDecodeError, TypeError):
        return []


def _yaml(value):
    """Scalar -> a YAML value that survives colons, quotes and leading @."""
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


class _Empty:
    """A property to emit as empty, so Obsidian shows it for you to fill in."""


EMPTY = _Empty()


def _frontmatter(fields):
    out = ["---"]
    for k, v in fields.items():
        if v is EMPTY:
            out.append(f'{k}: ""')
            continue
        if v in (None, "", [], {}):
            continue
        if isinstance(v, bool):
            out.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, int):
            out.append(f"{k}: {v}")
        elif isinstance(v, list):
            out.append(f"{k}: [{', '.join(_clean(str(x)) for x in v)}]")
        else:
            out.append(f"{k}: {_yaml(v)}")
    out.append("---")
    return "\n".join(out)


def _callout(kind, title, body):
    if not body:
        return ""
    lines = "\n".join(f"> {l}" for l in body.strip().splitlines())
    return f"> [!{kind}]- {title}\n{lines}"


def _link(folder, name, label=None):
    return f"[[{folder}/{_clean(name)}|{label or name}]]"


def _write(path, body, keep_tail=True):
    """Write a generated note, preserving anything the user added below MARKER."""
    tail = ""
    if keep_tail and path.exists():
        old = path.read_text(encoding="utf-8")
        if MARKER in old:
            tail = old.split(MARKER, 1)[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    text = body.rstrip() + "\n\n" + MARKER + (tail if tail else "\n")
    path.write_text(text, encoding="utf-8")


def frontmatter(path):
    """A note's YAML properties, or None if it has none / they don't parse."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    data = yaml.safe_load(text[3:end])
    return data if isinstance(data, dict) else None


def scalar(v):
    """Obsidian may store a property as a scalar or a one-item list."""
    if isinstance(v, list):
        v = next((x for x in v if str(x).strip()), "")
    return "" if v is None else str(v).strip()


# The properties you own. Everything else in the frontmatter is regenerated.
YOURS = ("review", "add_link", "review_note")


def _carry(path):
    """What you typed that the database hasn't consumed yet.

    A rejected decision -- a URL that 404s, a word that isn't in the vocabulary
    -- must survive the re-render, or the error message points at a field that
    has already been wiped clean.
    """
    if not path.exists():
        return {}
    try:
        fm = frontmatter(path)
    except yaml.YAMLError:
        return {}
    return {k: scalar((fm or {}).get(k)) for k in YOURS}


def _generated_notes(folder):
    """Every .md in folder that rkb wrote (so we never delete the user's own)."""
    if not folder.is_dir():
        return {}
    found = {}
    for f in folder.glob("*.md"):
        head = f.read_text(encoding="utf-8", errors="replace")[:800]
        if f"{STAMP}: true" in head:
            m = re.search(r"^shortcode: \"?([A-Za-z0-9_-]+)", head, re.M)
            found[f] = m.group(1) if m else None
    return found


# --------------------------------------------------------------------------- rendering

def _title(row, taken):
    base = _clean(row["summary"], 70)
    if not base:
        cap = (row["caption"] or "").strip().splitlines()
        base = _clean(cap[0] if cap else "", 70)
    base = base or row["shortcode"]
    name = base
    if name.lower() in taken:                 # collision -> disambiguate
        name = f"{base} ({row['shortcode']})"
    taken.add(name.lower())
    return name


IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def _images(row):
    """Every image belonging to a post, in reading order.

    A carousel uses the downloaded slides, not `frames/`. `frames/` is the set
    sent to the vision pass and is capped at MAX_FRAMES (8) -- and 9 of the 14
    carousels here have more slides than that, up to 20. On a listicle post the
    slides past the eighth are not redundant stills, they are half the content,
    so showing `frames/` would quietly drop the second half of the answer.

    A video has no such original: `frames/` IS its sampled set, chosen to favour
    the opening title card and the closing outro, which is where the links live.
    """
    d = row["media_dir"]
    if not d:
        return []
    d = Path(d)
    if row["media_kind"] == "images":
        # Slide filenames end in an ascending per-slide id, so sorting them is
        # carousel order -- the same assumption frames.from_images already makes.
        slides = sorted(p for p in d.iterdir()
                        if p.suffix.lower() in IMG_EXT and p.is_file())
        if slides:
            return slides
    return sorted(d.glob("frames/*.jpg"))


def _attachments(rows, out):
    """Hard-link every post's images into the vault, named by shortcode.

    This used to be a symlink to data/media, which reads as the tidy option and
    does not work: Obsidian does not index through a symlinked folder, so every
    embed under it resolved to "could not be found". Hard links cost no disk and
    are ordinary files as far as the indexer is concerned.

    `<shortcode>-01.jpg` is the whole join between an attachment and its post --
    there is no table to carry one, and a wikilink resolves by filename from
    anywhere in the vault, so it survives you rooting the vault at the repo
    instead of at vault/. The number is the position in the post, so the first
    is always the cover.
    """
    d = out / ATTACH
    if d.is_symlink():                       # the old arrangement
        d.unlink()
    d.mkdir(parents=True, exist_ok=True)

    wanted, shots = {}, {}
    for r in rows:
        names = []
        for i, src in enumerate(_images(r), 1):
            name = f"{r['shortcode']}-{i:02d}{src.suffix.lower()}"
            wanted[name] = src
            names.append(name)
        shots[r["shortcode"]] = names

    for name, src in wanted.items():
        dst = d / name
        if dst.exists() or dst.is_symlink():
            dst.unlink()                     # re-link: the frame may have been redone
        try:
            os.link(src, dst)
        except OSError:                      # different filesystem, or no hardlinks
            shutil.copy2(src, dst)

    # Prune only what this function creates. Anything else in the folder is
    # yours, including the bare `<shortcode>.jpg` covers of the older scheme,
    # which are no longer wanted and so go on the first pass.
    for f in d.iterdir():
        if f.is_file() and f.suffix.lower() in IMG_EXT and f.name not in wanted:
            f.unlink()
    return shots


def _reel_note(row, title, shots, carry=None, hubs=None):
    # Filenames lose colons and get truncated; the heading keeps the full summary.
    heading = (row["summary"] or "").strip() or title
    tools, links, tags = _jlist(row["tools"]), _jlist(row["links"]), _jlist(row["tags"])
    hashtags = _jlist(row["hashtags"])
    author = (row["author"] or "").lstrip("@")

    # The review queue lives in Obsidian: a post with no link gets three
    # editable properties, and `rkb sync` carries your answers into the
    # database before the next render overwrites them.
    verdict, why = triage.classify(row)
    pending = verdict == "review" and config.VAULT_REVIEW

    # A still-pending post keeps whatever you last typed: if it were consumed,
    # the post would no longer be pending.
    kept = carry or {}
    word = kept.get("review", "")
    review_val = word if pending and word and word.lower() != "done" else "pending"

    plat = platforms.get(row.get("platform"))
    fm = _frontmatter({
        "shortcode": row["shortcode"],
        # `reel` is what Library.base filters on, and a .base is written once
        # and then yours to tune -- so this stays true for a tweet too. Read it
        # as "an rkb post note", not as "a video from Instagram". `platform` is
        # the field to filter on when you want one source.
        "reel": True,
        "platform": plat.key,
        # An un-extracted post has never been judged, so it is neither in the
        # queue nor decided -- it gets no `review` property at all.
        "review": (review_val if pending
                   else ("done" if verdict == "keep" and config.VAULT_REVIEW
                         else None)),
        "add_link": (kept.get("add_link") or EMPTY) if pending else None,
        "review_note": (kept.get("review_note") or EMPTY) if pending else None,
        "review_why": why if pending else None,
        "url": row["url"],
        "kind": row["media_kind"] or row["kind"],
        "author": f"@{author}" if author else None,
        "collection": row["collection"],
        "cover": f"[[{shots[0]}]]" if shots else None,
        "images": len(shots) or None,
        "tools": tools,
        "link_count": len(links),
        "prompt": True if (row["prompt"] or "").strip() else None,
        "saved": (row["saved_at"] or "")[:10],
        "status": row["status"],
        "confidence": row["confidence"],
        "tags": tags,
        STAMP: True,
    })

    body = [fm, ""]
    if shots:
        body += [f"![[{shots[0]}]]", ""]
    body += [f"# {heading}", ""]

    if row["actionable"]:
        body += [f"> [!tip] Next step\n> {row['actionable']}", ""]
    prompt = (row["prompt"] or "").strip()
    if prompt:
        body += ["## Prompt", "", "```text", prompt, "```", ""]
    if row["detail"]:
        body += [row["detail"], ""]
    if not row["summary"]:
        body += [f"*Not extracted yet — status `{row['status']}`.*", ""]

    if links:
        body += ["## Links", ""] + [f"- {l}" for l in links] + [""]
    # A name only becomes a wikilink when it has a hub note behind it. A link to
    # a page that exists solely to hold that one link is not a connection.
    h = hubs or {}

    def _maybe(folder, name, label=None):
        # A tag that is really a tool ("claude-code") resolves to the tool hub,
        # so one concept is one node rather than two lookalikes side by side.
        target = h.get((folder, name.strip().lower()))
        if target:
            return _link(target[0], target[1], label)
        return label or name

    if tools:
        body += ["## Tools", "",
                 " · ".join(_maybe(TOOLS, x) for x in tools), ""]
    if tags:
        body += ["## Topics", "",
                 " · ".join(_maybe(TOPICS, x) for x in tags), ""]

    src = [f"[Open on {plat.label}]({row['url']})"]
    if author:
        src.append(_maybe(AUTHORS, author, f"@{author}"))
    if row["collection"]:
        src.append(f"filed under **{row['collection']}**")
    body += ["## Source", "", " · ".join(src), ""]
    if hashtags:
        body += [" ".join(f"`{h}`" for h in hashtags[:15]), ""]

    # Every image, at a width that tiles into a contact sheet. Collapsed like
    # the other bulky blocks: 20 slides open by default would bury the summary,
    # the links and the tools under a page of scrolling. The count is in the
    # title so you know what is in there without opening it.
    if len(shots) > 1:
        label = "Slides" if row["media_kind"] == "images" else "Keyframes"
        grid = " ".join(f"![[{n}|{config.GALLERY_WIDTH}]]" for n in shots)
        body += [_callout("abstract", f"{label} ({len(shots)})", grid), ""]

    for kind, label, text in (("quote", "Caption", row["caption"]),
                              ("quote", "Transcript", row["transcript"]),
                              ("abstract", "Text on the slides/frames (OCR, verbatim)",
                               row["ocr_text"])):
        c = _callout(kind, label, text)
        if c:
            body += [c, ""]
    return "\n".join(body)


def _related_line(entries, display, limit=10):
    """`Related:` — strongest associations first, so the line reads as a summary."""
    if not entries:
        return None
    names = [_link(f, display[(f, k)]) for _, _, (f, k) in entries[:limit]]
    return "**Related:** " + " · ".join(names)


def _hub_note(folder, name, rows, blurb, extra=None):
    fm = _frontmatter({"title": name, "count": str(len(rows)), STAMP: True})
    body = [fm, "", f"# {name}", "", blurb, ""]
    if extra:
        body += extra + [""]
    for r in sorted(rows, key=lambda r: (r["saved_at"] or ""), reverse=True):
        line = f"- [[{r['_folder']}/{r['_title']}|{r['_title']}]]"
        if r["author"]:
            line += f"  <small>@{r['author']}</small>"
        body.append(line)
    return "\n".join(body)


# --------------------------------------------------------------------------- tables

# Two flat indexes over the whole library, for the two things you actually go
# looking for: the repo you saw once and can't name, and the block of on-screen
# text you saved to run later. Both are views of the same rows the reel notes
# come from -- nothing here is stored anywhere else.

_GITHUB = re.compile(r"^https?://(?:www\.)?github\.com/([^/?#]+)/([^/?#]+)", re.I)

# github.com/<this>/... is a site section, not somebody's account.
_NOT_OWNER = {"about", "apps", "collections", "enterprise", "events", "explore",
              "features", "login", "marketplace", "orgs", "pricing", "security",
              "settings", "sponsors", "topics", "trending"}

# A repo is usually named after the tool, but not always exactly: Postiz ships
# as gitroomhq/postiz-app, Anytype as anyproto/anytype-ts. Try the repo name,
# then the repo name without its platform suffix, then the owner.
_REPO_SUFFIX = re.compile(r"-(app|ts|js|py|node|cli|server|core|ui|web|desktop|io)$", re.I)
_OWNER_SUFFIX = re.compile(r"-(io|inc|hq|org|team|dev|devs|labs|ai|app|tools)$", re.I)


def _repo(url):
    """`owner/repo` for a GitHub URL, or None for anything else.

    A link pointing deeper into a repo -- /stargazers, /issues,
    /network/dependents -- is still that repo. Normalising to the root is what
    makes this a list of repos rather than a list of URLs, and it is what
    collapses supabase/supabase's three separate appearances into one row.
    """
    m = _GITHUB.match((url or "").strip())
    if not m:
        return None
    owner, name = m.group(1), m.group(2).removesuffix(".git")
    if not name or owner.lower() in _NOT_OWNER:
        return None
    return f"{owner}/{name}"


def _tool_for(repo, tools):
    """The recorded tool this repo is, if the post named it."""
    by_norm = {concepts.norm(t): t for t in tools}
    owner, name = repo.split("/", 1)
    for cand in (name, _REPO_SUFFIX.sub("", name),
                 owner, _OWNER_SUFFIX.sub("", owner)):
        hit = by_norm.get(concepts.norm(cand))
        if hit:
            return hit
    return None


def _cell(text):
    """One line of text, safe to put in a cell once _table escapes it."""
    return " ".join(str(text or "").split())


def _reel_link(row, limit=46):
    """Link to a post, with the label short enough that a table stays a table.

    The target keeps the full filename -- only the visible label is trimmed.
    """
    return f"[[{row['_folder']}/{_clean(row['_title'])}|{_cell(_clean(row['_title'], limit))}]]"


def _hub_link(hubs, folder, name, label=None):
    """A name links only where a hub note exists to receive it."""
    target = (hubs or {}).get((folder, name.strip().lower()))
    return _link(target[0], target[1], label) if target else _cell(label or name)


def _table(header, rows):
    """A markdown table with every cell's pipes escaped.

    Including the one inside `[[target|label]]`. A wikilink alias is written with
    an ordinary pipe everywhere else in the vault, but inside a table that pipe
    is a column separator: Obsidian renders the row as far as the `[[target`,
    then starts a new cell. It survives long enough to look fine until Obsidian's
    table editor reflows the file, at which point every aliased link is torn in
    half and the table gains a column per link. `\\|` is Obsidian's own escape
    for this, so it has to happen here rather than in the cell builders -- one
    place, applied to everything, escaped exactly once.
    """
    def esc(cell):
        return str(cell).replace("|", "\\|")

    return ["| " + " | ".join(esc(h) for h in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |"] + \
           ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]


def repos(rows):
    """`owner/repo` -> the tool it is and the posts it came from."""
    found = {}
    for r in rows:
        tools = _jlist(r["tools"])
        for url in _jlist(r["links"]):
            repo = _repo(url)
            if not repo:
                continue
            e = found.setdefault(repo, {"tool": None, "posts": {}})
            e["tool"] = e["tool"] or _tool_for(repo, tools)
            e["posts"][r["shortcode"]] = r
    return found


def _repos_note(rows, hubs):
    found = repos(rows)
    posts = {sc for e in found.values() for sc in e["posts"]}
    body = [_frontmatter({"title": "Repos", "count": str(len(found)), STAMP: True}),
            "", "# Repos", "",
            f"Every GitHub repository the library points at — **{len(found)}** "
            f"repos across **{len(posts)}** posts.", "",
            "Links that pointed *into* a repo (`/stargazers`, `/issues`, "
            "`/network/dependents`) are normalised to the repo itself, so a repo "
            "that turned up in three posts is one row here, not three.", ""]

    table = []
    for repo in sorted(found, key=str.lower):
        e = found[repo]
        tool = _hub_link(hubs, TOOLS, e["tool"]) if e["tool"] else "—"
        seen = sorted(e["posts"].values(),
                      key=lambda r: (r["saved_at"] or ""), reverse=True)
        table.append([f"[{repo}](https://github.com/{repo})", tool,
                      "<br>".join(_reel_link(r) for r in seen)])
    body += _table(["Repo", "Tool", "Saved from"], table)
    return "\n".join(body)


def prompt_posts(rows):
    """Posts kept for the text on screen rather than for a link.

    There is no stored flag for this: `extractions.prompt` is null by contract
    (the extraction rules forbid composing one, since the verbatim text is
    already in `ocr_text`), and the dashboard's "prompt is the payload" button
    writes the same `reviewed='kept'` as a plain keep. So the set is derived:
    you kept it, and it carries no payload link -- which leaves exactly the
    posts whose whole value is the text on the slides.
    """
    keep = [r for r in rows
            if r["reviewed"] == "kept"
            and not triage._payload_links(_jlist(r["links"]), r["author_link"])]
    return sorted(keep, key=lambda r: (r["saved_at"] or ""), reverse=True)


def _prompts_note(rows, hubs):
    keep = prompt_posts(rows)

    body = [_frontmatter({"title": "Prompts", "count": str(len(keep)), STAMP: True}),
            "", "# Prompts", "",
            f"**{len(keep)}** posts you kept for what was written on screen "
            f"rather than for a link — prompts, checklists, playbooks.", "",
            "> [!info] The text itself is on each note",
            "> Open the post and expand *Text on the slides/frames (OCR, "
            "verbatim)* — it is captured in full and never rewritten, so what "
            "you copy is what the creator wrote.", ""]

    table = []
    for r in keep:
        topics = " · ".join(_hub_link(hubs, TOPICS, t) for t in _jlist(r["tags"])[:3])
        author = (r["author"] or "").lstrip("@")
        table.append([_reel_link(r),
                      _hub_link(hubs, AUTHORS, author, f"@{author}") if author else "—",
                      topics or "—",
                      (r["saved_at"] or "")[:10] or "—"])
    body += _table(["What you kept", "Author", "Topics", "Saved"], table)
    return "\n".join(body)


def _index_note(rows, tools, topics, out):
    n = len(rows)
    done = [r for r in rows if r["status"] == "extracted"]
    todo = [r for r in rows if r["status"] != "extracted"]
    all_links = [l for r in rows for l in _jlist(r["links"])]
    cols = Counter(r["collection"] or "(uncollected)" for r in rows)

    fm = _frontmatter({"title": "Index", STAMP: True})
    b = [fm, "", "# Reels Knowledge Base", "",
         f"**{n}** saved posts · **{len(done)}** extracted · "
         f"**{len(set(all_links))}** links recovered · "
         f"**{len(repos(rows))}** repos · "
         f"**{len(tools)}** tools · **{len(topics)}** topics", ""]

    if todo:
        b += [f"> [!warning] {len(todo)} post(s) not extracted yet",
              "> Run `./bin/rkb pending`, extract with Claude Code, "
              "then `./bin/rkb vault` again.", ""]

    b += ["## Tables", "",
          f"- [[Repos]] — every GitHub repository the library points at "
          f"({len(repos(rows))})",
          f"- [[Prompts]] — posts kept for the text on screen, not a link "
          f"({len(prompt_posts(rows))})", ""]

    b += ["## Most-referenced tools", ""]
    for name, c in tools.most_common(15):
        b.append(f"- {_link(TOOLS, name)} — {c} post{'s' if c > 1 else ''}")
    b += ["", "## Topics", "",
          " · ".join(f"{_link(TOPICS, t)} ({c})" for t, c in topics.most_common(30)),
          "", "## Collections", ""]
    for name, c in cols.most_common():
        b.append(f"- **{name}** — {c}")

    b += ["", "## Every action worth taking", ""]
    for r in sorted(done, key=lambda r: (r["saved_at"] or ""), reverse=True):
        if r["actionable"]:
            b.append(f"- [[{r['_folder']}/{r['_title']}|{r['_title']}]]  \n  {r['actionable']}")

    if todo:
        b += ["", "## Awaiting extraction", ""]
        b += [f"- [[{r['_folder']}/{r['_title']}|{r['_title']}]] (`{r['status']}`)"
              for r in todo]
    return "\n".join(b)


# --------------------------------------------------------------------------- bases

# Obsidian Bases (1.9+) turn frontmatter into a live table. That makes the
# review queue a view *inside* the vault rather than a separate web page: you
# set `review` on a note, and `rkb sync` reads it back into SQLite.
#
# Written once, never overwritten -- these are yours to re-sort, re-filter and
# re-column once they exist.

# Filter on a property every reel note carries, never on the folder path:
# `file.inFolder("Reels")` only matches when the vault is rooted at vault/, and
# rooting it at the repo instead is a perfectly reasonable thing to do. Plain
# `==` on a property is also the one predicate that cannot fail on a function
# name that moved between Obsidian versions.
REVIEW_BASE = """filters:
  and:
    - 'review == "pending"'

properties:
  review:
    displayName: "Decision"
  add_link:
    displayName: "Repo / payload URL"
  review_note:
    displayName: "Your note"
  review_why:
    displayName: "In the queue because"
  tools:
    displayName: "Named tools"
  author:
    displayName: "From"

views:
  - type: cards
    name: "Queue"
    order:
      - cover
      - file.name
      - author
      - review
      - add_link
      - review_why

  - type: table
    name: "Decide"
    order:
      - file.name
      - author
      - tools
      - review_why
      - review
      - add_link
      - review_note
    summaries:
      review: Filled
"""

LIBRARY_BASE = """filters:
  and:
    - 'reel == true'

formulas:
  payload: 'if(link_count > 0, "\u2713 " + link_count.toString(), "\u2014")'

properties:
  formula.payload:
    displayName: "Links"
  tools:
    displayName: "Tools"
  author:
    displayName: "From"
  saved:
    displayName: "Saved"

views:
  - type: table
    name: "Everything"
    order:
      - file.name
      - author
      - formula.payload
      - tools
      - tags
      - saved

  - type: cards
    name: "Gallery"
    order:
      - cover
      - file.name
      - author
      - formula.payload

  - type: table
    name: "Has a link"
    filters:
      and:
        - 'link_count > 0'
    order:
      - file.name
      - author
      - formula.payload
      - tools
"""

BASES = {"Library.base": LIBRARY_BASE}
if config.VAULT_REVIEW:
    BASES["Review Queue.base"] = REVIEW_BASE


def _write_base(path, text, force=False):
    """Write once. You tune your own views; a re-render must not undo that.

    `rkb vault --rebuild-bases` overwrites them when the template itself has to
    change.
    """
    if path.exists() and not force:
        return False
    path.write_text(text, encoding="utf-8")
    return True


# --------------------------------------------------------------------------- entry point

def vault_dir(out=None):
    return Path(out or os.environ.get("RKB_VAULT")
                or config.ROOT / "vault").expanduser()


def build(out=None, rebuild_bases=False):
    out = vault_dir(out)
    out.mkdir(parents=True, exist_ok=True)

    con = db.init()
    rows = [dict(r) for r in con.execute(
        "SELECT p.*, e.summary, e.detail, e.tools, e.links, e.prompt, e.tags, "
        "       e.actionable, e.confidence "
        "FROM posts p LEFT JOIN extractions e USING (shortcode) "
        "WHERE p.status != 'archived' "          # triaged out; still in the db
        # Total order, not just saved_at: ties (and NULLs) would otherwise come
        # back in an arbitrary order, and _title's collision suffix goes to
        # whichever post it sees second. Flip that between runs and a note is
        # renamed, the old path pruned as stale, and the notes you typed below
        # the marker go with it.
        "ORDER BY p.saved_at DESC, p.shortcode"
    ).fetchall()]

    shots = _attachments(rows, out)

    taken = set()
    for r in rows:
        r["_title"] = _title(r, taken)
        r["_folder"] = platforms.get(r.get("platform")).folder

    # The concept graph decides which hubs exist, which tags are really tools,
    # and what links to what -- so the vault and `rkb graph` never disagree.
    g = concepts.build(rows)
    tool_rows, topic_rows = defaultdict(dict), defaultdict(dict)
    authors = defaultdict(list)
    linkmap = {}
    for (folder, key), name in g["display"].items():
        linkmap[(folder, key)] = (folder, name)
    for tag, tool in g["merge"].items():
        linkmap[(TOPICS, tag)] = (TOOLS, tool)

    for r in rows:
        for t in _jlist(r["tools"]):
            hit = linkmap.get((TOOLS, t.strip().lower()))
            if hit:
                tool_rows[hit[1]][r["shortcode"]] = r
        for t in _jlist(r["tags"]):
            hit = linkmap.get((TOPICS, t.strip().lower()))
            if hit:
                (tool_rows if hit[0] == TOOLS else topic_rows)[hit[1]][r["shortcode"]] = r
        if r["author"]:
            authors[r["author"].lstrip("@")].append(r)

    tools = {k: list(v.values()) for k, v in tool_rows.items()}
    topics = {k: list(v.values()) for k, v in topic_rows.items()}

    # A hub that connects nothing is a dead end; the name still appears on the
    # post, just not as a link to a page holding that single link.
    authors = {k: v for k, v in authors.items() if len(v) >= config.HUB_MIN}
    for k in authors:
        linkmap[(AUTHORS, k.lower())] = (AUTHORS, k)
    hubs = linkmap
    related, display = g["related"], g["display"]

    written = set()
    # Titles are unique across the whole library, not per folder, so a post
    # that changes platform (or a folder that gets renamed) is pruned from
    # wherever it used to live rather than left behind as a duplicate.
    stale = {}
    for folder in POST_FOLDERS:
        stale.update(_generated_notes(out / folder))

    for r in rows:
        path = out / r["_folder"] / f"{r['_title']}.md"
        _write(path, _reel_note(r, r["_title"], shots.get(r["shortcode"], []),
                                _carry(path), hubs))
        written.add(path)

    for folder, groups, blurb in (
        (TOOLS, tools, "Posts that mention this tool."),
        (TOPICS, topics, "Posts on this topic."),
        (AUTHORS, authors, "Posts saved from this account."),
    ):
        d = out / folder
        stale.update(_generated_notes(d))
        for name, group in groups.items():
            label = f"@{name}" if folder == AUTHORS else name
            path = d / f"{_clean(name)}.md"
            key = (folder, name.lower() if folder != TOPICS else name)
            line = _related_line(related.get(key), display)
            _write(path, _hub_note(folder, label, group, blurb,
                                   [line] if line else None))
            written.add(path)

    bases = [name for name, text in BASES.items()
             if _write_base(out / name, text, rebuild_bases)]

    idx = out / "Index.md"
    _write(idx, _index_note(rows, Counter({k: len(v) for k, v in tools.items()}),
                            Counter({k: len(v) for k, v in topics.items()}), out))
    written.add(idx)

    for name, render in (("Repos.md", _repos_note), ("Prompts.md", _prompts_note)):
        path = out / name
        _write(path, render(rows, hubs))
        written.add(path)

    removed = 0
    for path in stale:
        if path not in written and path.exists():
            path.unlink()
            removed += 1

    return {"vault": str(out), "notes": len(written), "reels": len(rows),
            "repos": len(repos(rows)), "prompts": len(prompt_posts(rows)),
            "tools": len(tools), "topics": len(topics), "authors": len(authors),
            "removed_stale": removed, "bases": bases,
            "images": sum(len(v) for v in shots.values()),
            "galleries": sum(1 for v in shots.values() if len(v) > 1),
            "edges": len(g["edges"]), "merged": len(g["merge"]),
            "stopwords": sorted(k for _, k in g["stopwords"]),
            "review_in_vault": config.VAULT_REVIEW,
            "pending": sum(1 for r in rows if triage.classify(r)[0] == "review")}
