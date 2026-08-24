# Reels To Knowledge Base

Saved Instagram reels and carousels → a searchable knowledge base you can act on,
readable as an Obsidian vault.

**The problem:** the useful part of a tech reel is usually a GitHub URL flashed on
a title card for one second and never spoken, or a checklist that exists only as
pixels. Transcription alone loses all of it. One reel in this library ends with
*"comment memory and I'll send you the repo link"* — the link is deliberately
withheld from the audio, and sits on screen the whole time.

So every post gets a transcript **and** OCR of every frame or slide, and
extraction reads them together.

---

## Requirements

| | | |
|---|---|---|
| macOS | Apple Silicon | OCR uses the system Vision framework; transcription uses MLX |
| Python | 3.11+ | 3.11 recommended (`.venv`) |
| ffmpeg | any recent | frame sampling and audio extraction |
| yt-dlp | recent | reels (video) |
| gallery-dl | recent | carousels (image posts) |
| Obsidian | 1.9+ | optional — reading the vault and the `.base` review queue |

The Apple Vision and MLX dependencies are the only macOS-specific parts. On
Linux you'd swap `rkb/ocr.py` for tesseract and `rkb/transcribe.py` for
faster-whisper; nothing else changes.

## Install

```bash
brew install ffmpeg yt-dlp gallery-dl

cd reels-kb
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

./bin/rkb init
```

`bin/rkb` is a shim that runs the venv's Python directly, so you never need to
activate anything.

`requirements.txt`:

```
mlx-whisper                 # local transcription on the GPU
pyobjc-framework-Vision     # on-device OCR
pyobjc-framework-Quartz     # image loading for Vision
```

## Use

**1. Export your saved posts.** Instagram → Accounts Center → Your information
and permissions → Export your information → *Saved items*, as **JSON**. Unzip
into `data/export/`.

**2. Import.**

```bash
./bin/rkb import
./bin/rkb import --exclude food,adhd     # collections you never want
./bin/rkb collections                    # counts per collection
```

Pulls every post out of the export with its caption, hashtags, creator, and
which of **your own Instagram collections** it was filed in. Exclusions persist
in `data/excluded_collections.txt`, so re-imports never resurrect them.

**3. Prepare.** Downloads, samples frames, transcribes, and OCRs.

```bash
./bin/rkb prepare -n 25
./bin/rkb prepare -n 25 --retry          # also retry previous failures
./bin/rkb prepare -n 25 --kind reel      # only reels, or --kind post
```

Runs entirely locally — no API, no quota. Failures are recorded per-post and
never abort the batch.

**4. Extract.** Ask Claude Code to process the batch. It reads each post's
`context.md` and writes results back via `./bin/rkb record`. See `CLAUDE.md` for
the instructions it follows.

**5. Render and review.**

```bash
./bin/rkb vault                          # write the Obsidian vault
./bin/rkb triage                         # what has a payload, what needs you
./bin/rkb dashboard --serve              # review queue; every click saves
./bin/rkb search "rag"                   # FTS5 search from the terminal
```

---

## How it works

```
saved_posts.json + saved_collections.json
      │  rkb import      url, caption, hashtags, creator, collection
      ▼
   posts (status=new)
      │  rkb prepare     yt-dlp (video) ─or─ gallery-dl (carousel)
      │                  ffmpeg frame sampling
      │                  mlx-whisper transcript
      │                  Apple Vision OCR
      ▼
   posts (status=prepared)     media/<shortcode>/{frames/, ocr_frames/, context.md}
      │  Claude Code     reads context.md, extracts structure
      │  rkb record      validates every URL before storing
      ▼
   extractions + FTS5 index
      ├─ rkb search      terminal
      ├─ rkb triage →    rkb dashboard --serve → your review decisions
      └─ rkb vault  →    vault/  Reels + Tools + Topics + Authors → Obsidian
                            └─ rkb graph → concept map, coloured by cluster
```

### Frame sampling

Weighted toward the opening beat, because tech reels put the tool name or link
on a title card in the first second and then cut away: every 0.5 s for the first
3 s, every 2 s after, `mpdecimate` to drop near-identical frames, capped at 8
frames scaled to 768 px. Frames are extracted for *every* post, never
conditionally on whether speech was found.

### OCR

Apple's Vision framework, on-device — free, fast (~0.13 s/image), no API.

**OCR samples separately from vision, and much more densely.** `MAX_FRAMES = 8`
exists to cap vision tokens; OCR runs locally and costs nothing per image, so
reusing that cap just throws screens away. Many Instagram "reels" are slideshows
— eight frames of a 52-second deck reads a third of it. Videos get their own
`ocr_frames/` set sampled at `OCR_FPS` (default 2) across the whole video, with
`mpdecimate` collapsing each held screen to roughly one frame, capped at
`OCR_MAX_FRAMES` (default 80). On one slideshow reel that took the text from
7,926 to 33,754 characters — and surfaced a `git clone` URL that had been
hidden behind a caption overlay in all eight sampled frames.

Three details that matter:

- **Carousels are OCR'd from their original slides, not the sampled frames.**
  Frame extraction caps at 8; a 20-slide deck would lose 12 slides. There's no
  sampling budget to respect when the images are already stills.
- **Repeated overlay text is deduplicated across frames.** A caption sits on top
  of every frame of a reel, so naive concatenation gives eight copies of one
  sentence and buries the slide that actually differs.
- **A held screen costs one frame, not twenty.** `mpdecimate` runs inside the
  ffmpeg filter chain, so a slideshow that holds each panel for three seconds
  yields roughly one frame per panel rather than six.

Across this library OCR produced **260k characters of on-screen text vs 40k of
transcript** — roughly 6.5× more content than the audio carried.

### Link verification

A wrong link is the only unrecoverable error here: a missing one sends the post
to your review queue, a plausible dead URL clears the post and sends you
nowhere. So `rkb record` HEAD-checks every URL before storing it, and
`rkb verify` re-sweeps the library.

OCR is the usual culprit — text read off a slide can be cut mid-word, so
`.../network/dependents` arrives as `.../network/dependen`, which looks
perfectly reasonable and 404s. Those are repaired automatically.

One case is deliberately **not** treated as dead: GitHub serves `/stargazers`
and `/watchers` as 404 to logged-out requests. Those pages work fine in a
signed-in browser, so if the repo root resolves the link is kept.

### Triage

**The link is the payload.** A post with one clears automatically; a post
without one goes to your review queue — because "no link" has several causes and
only you can tell them apart: the URL was on a frame and extraction missed it,
the creator gated it behind a comment, or the post is a technique that has no
repo. Every card shows the full verbatim OCR, so you read the source and lift
what you want rather than being handed a summary of it.

#### The review dashboard

`rkb dashboard --serve` runs a local server on `127.0.0.1:8765` and opens it.
Each click writes straight to SQLite and the page is re-rendered from the
database on every request, so there is nothing to copy, paste or reload. Per
post: paste a URL you spot, keep it anyway, send it back for another extraction
pass, or archive it — plus a free-text *why?* box.

Every pasted URL is HEAD-checked before it lands, and OCR truncations are
repaired (`.../network/dependen` → `.../network/dependents`). A URL that does
not resolve is **not** recorded; you get the error instead, and the post stays
in the queue. Nothing is silently discarded and nothing is silently guessed.

Archiving sets `status='archived'` — reversible, and the media stays on disk.

> A static `rkb dashboard` (no `--serve`) writes `dashboard.html` and needs
> `rkb review` to apply decisions from your clipboard. It works, but the
> clipboard round-trip has more ways to go stale. Prefer `--serve`.

#### Reviewing inside Obsidian instead (opt-in)

The same queue can live in the vault as editable note properties plus a Bases
view. It is off by default — two places to make a decision is one too many —
and reviewing by typing a word into a property is slower than clicking a button,
so reach for this only if you want everything in one app:

```bash
RKB_VAULT_REVIEW=1 ./bin/rkb vault --rebuild-bases
```

Each queued post then carries `review` (`keep` / `junk` / `recheck` / `reset`),
`add_link` and `review_note`, and `Review Queue.base` lists exactly those notes.
`./bin/rkb sync` reads them back into SQLite; `./bin/rkb sync --watch` does it
as you type. `rkb vault` syncs before rendering, so a re-render never overwrites
a decision you hadn't saved, and a rejected one is left in the note to correct
in place.

### The Obsidian vault

`rkb vault` renders the database into plain markdown — no plugins required.

```
vault/
  Index.md          counts, most-referenced tools, every next step
  Repos.md          every GitHub repo in the library, one row each
  Prompts.md        the posts whose payload is the text on screen
  Library.base      every post as a filterable table / gallery (Obsidian 1.9+)
  Reels/            one note per post: thumbnail, summary, prompt, links, transcript
  Tools/            one note per tool — backlinks every post that mentions it
  Topics/           one note per tag
  Authors/          one note per creator
  attachments/      every image, hard-linked from data/media
```

### The two flat tables

`Repos.md` and `Prompts.md` answer the two questions a reel library actually
gets asked: *what was that repo called?* and *where's that checklist I saved?*

**`Repos.md`** is every GitHub repository the library points at, one row per
repo. A URL that pointed *into* a repo — `/stargazers`, `/issues`,
`/network/dependents` — is normalised to the repo itself, which is what turns 71
links into 64 repos and collapses `supabase/supabase`'s three separate
appearances into one row that names all three posts. The **Tool** column is the
canonical name the extraction recorded, matched to the repo by name, then by the
repo name without its platform suffix (`gitroomhq/postiz-app` → Postiz,
`anyproto/anytype-ts` → Anytype), then by the owner. Two of the 71 stay
unmatched and should: `bitwarden/server` is the upstream of the Vaultwarden the
post was about, and `emilkowalski/skills` is nobody's product.

**`Prompts.md`** is the posts you kept for the words on the slides rather than
for a link. There is no stored flag for this, and adding one would be worse than
deriving it: `extractions.prompt` is null by contract (the extraction rules
forbid composing a prompt, because `ocr_text` already holds the verbatim text),
and the dashboard's *"prompt is the payload"* button writes the same
`reviewed='kept'` as a plain keep. So the set is **kept, and carrying no payload
link** — which is exactly the posts whose whole value is the text. It is a
slightly wider net than the word *prompt* suggests: checklists, playbooks and
one comment-gated post ride along with the actual prompts, because you kept
those too and for the same reason.

Both are regenerated on every `rkb vault`, and both keep anything you write
below the `rkb:end` marker.

The hub notes are the answer to *"there's no relation among each reel"*: open
`Tools/Claude Code.md` and you get every post that touched it, and the graph
view draws clusters you never filed by hand.

**A hub note is only created when it connects two or more posts** (`RKB_HUB_MIN`,
default 2). At 1 you get a node per one-off tool — 89% of them here — and the
graph turns into a dandelion of dead ends: 341 nodes for 48 posts, of which 211
had exactly one edge. Thresholded, that first cut drops to 107 nodes. A one-off
tool still appears on the post, as plain text rather than a link to a page that
exists solely to hold that one link.

`RKB_HUB_MIN=1 ./bin/rkb vault` restores a note for every name.

**Hubs link to each other, not just to posts.** Without this the vault is a
*document* graph: every edge runs post → tool or post → topic, and nothing joins
a tool to a topic, so hiding the posts leaves a field of unconnected dots. The
rules that turn raw co-occurrence into a map you can read all live in
`rkb/concepts.py`:

| | why |
|---|---|
| ranked by **Jaccard**, not raw count | raw co-occurrence just re-ranks the common tags; a pair that almost always appears together should outrank a pair that merely both appear a lot |
| each hub keeps its **strongest `RKB_LINK_TOPK`** (4) | a flat threshold lets popular nodes hoard edges — one node here reached degree 29, which draws as a wheel with everything on the rim |
| at least `RKB_LINK_MIN` (2) shared posts | one shared post is a coincidence |
| hubs on over `RKB_STOPWORD_FRAC` (50%) of the library are dropped | `open-source`, on 62% of this library, co-occurs with everything and so separates nothing — the `the` of the vocabulary. The note stays; the node goes |

A concept that exists as both a tool and a tag (`Tools/n8n` and `Topics/n8n`)
is merged into the tool, so one concept draws as one node instead of two
lookalikes side by side.

**Nothing is left off the map.** Pruning is aimed at thinning dense nodes, but
it silences sparse ones as a side effect: a hub can clear the bar to *exist*
(2 posts) and miss the bar to *connect* (2 shared posts), leaving it present in
the vault and absent from the graph. Two passes fix that, each adding at most
one edge:

- a node with no edges gets its single strongest association, even at one shared
  post — this recovered `privacy → homelab`, `productivity → project-management`,
  `gated-content → marketing`
- a whole component that found only itself gets attached to the mainland the
  same way — `sarvam`/`voice-agents` had each other and so were never rescued as
  nodes, while sharing a post with `debugging` all along

Ties this far down are common and are broken towards the **better-connected**
partner: that pulls the node into an existing cluster, where attaching it to
another loose node would only make a two-node island belonging nowhere.

The result on this library: **52 concepts, 92 links, one connected map, no
orphans**, where the worst node used to have 29 edges.

### Colouring the graph

The graph view is filtered to `Tools/` and `Topics/` — the posts are the
substrate, not the map.

```bash
./bin/rkb graph                # cluster colours + concepts-only filter
./bin/rkb graph --everything   # put posts and authors back in
```

`rkb graph` runs label propagation over the concept graph and gives each
detected cluster its own colour, so the map reads as regions rather than as one
undifferentiated mesh. It is deterministic — same library, same clusters, same
colours, run after run. Here it finds four:

```
#E8A33D  (17)  business & automation
               agency · automation · business · coolify · ghost · growth ·
               lead-generation · marketing · medusa · n8n · sales · startups ·
               supabase · sarvam · voice-agents · debugging · gated-content

#4FC3A1  (15)  AI-assisted coding
               claude · claude code · cursor · prompt-engineering · skills ·
               design · devtools · documentation · vibe-coding · webdev · seo ·
               checklist · homelab · privacy · 3d-visualization

#A78BFA  (12)  agent infrastructure
               agents · mcp · memory · architecture · claude fable 5 · docker ·
               evals · local-first · self-hosted · sqlite · project-management ·
               productivity

#5B9DF9  ( 8)  local inference & cost
               ollama · groq · local-llm · rag · ai-gateway · cost-control ·
               python · uv
```

The palette avoids red/green, so the four stay distinct under the common forms
of colour blindness. It also prints which edges were inferred rather than
observed — those are the weakest claims on the map, each resting on a single
shared post.

**Quit Obsidian before running it.** Obsidian holds the graph state in memory
and writes `.obsidian/graph.json` back on exit, silently discarding anything
edited underneath it — so the command refuses to run against a live Obsidian
rather than pretending to have worked. To change just the filter without
restarting, paste it into *Graph view → Filters* instead; that takes effect
immediately and Obsidian persists it itself.

**SQLite stays the source of truth and the vault is a generated view**, so
`rkb vault` is safe to re-run after every batch. Two things survive a
regeneration: anything you type below the `rkb:end` marker at the bottom of a
note, and the `.base` files once they exist — so re-sort and re-column those
views freely. Notes rkb didn't write are never touched.

Put the vault elsewhere with `./bin/rkb vault -o ~/Documents/MyVault` or
`RKB_VAULT=...`.

**Where to root it in Obsidian.** Either `vault/` or the repo itself works.
The `.base` filters key off a note property rather than a folder path, and
thumbnails are embedded as `![[<shortcode>.jpg]]` — a wikilink resolves by
filename from anywhere in the vault — so nothing depends on where the root is.
Rooting at the repo also pulls `README.md` and `CLAUDE.md` into the vault, which
you may or may not want.

**Attachments are hard links, not a symlink.** `attachments/` was a symlink to
`data/media` at first, which costs nothing and does not work: Obsidian does not
index through a symlinked folder, so every embed under it resolved to *"could
not be found"*. Hard links cost no disk either — same inode, the 77 MB is shared
with `data/media`, and `du -ch data/media vault/attachments` still reports the
`data/media` total. They are ordinary files to the indexer, and they are
re-linked on every `rkb vault`, so a re-sampled frame is picked up.

`<shortcode>-01.jpg` is the whole join between an image and its post — there is
no attachments table to carry one. The number is the position in the post, so
`-01` is always the cover, and a wikilink resolves by filename from anywhere in
the vault, so the scheme survives you rooting the vault at the repo.

**Every image is on the note**, as a collapsed contact sheet below the summary —
*Slides (20)* on a carousel, *Keyframes (8)* on a reel. Collapsed because twenty
slides open by default bury the summary, the links and the tools under a page of
scrolling; `RKB_GALLERY_WIDTH` sets the tile size.

A carousel's gallery is built from the **downloaded slides, not `frames/`**.
`frames/` is what goes to the vision pass and is capped at `MAX_FRAMES` (8) —
and 9 of the 14 carousels here carry more than that, up to 20. On a listicle
post the slides past the eighth are not redundant stills, they are half the
content. A video has no such original, so `frames/` *is* its set: sampled to
favour the opening title card and the closing outro, which is where links live.

---

## Image and carousel posts need cookies

Reels download anonymously. Image and carousel `/p/` posts hit a login wall.

**The no-extension route (recommended):** grant your terminal **Full Disk
Access** in System Settings → Privacy & Security, restart it, then:

```bash
RKB_BROWSER=safari ./bin/rkb prepare -n 25 --retry
```

yt-dlp reads Safari's cookie jar directly. Safari's cookies are TCC-protected,
which is the only reason the permission is needed.

**The alternative:** export a Netscape-format `cookies.txt` and point at it with
`RKB_COOKIES=/path/to/cookies.txt` if you'd rather not leave Full Disk Access
granted.

> That file is a live Instagram login. Keep it outside the repo and re-create it
> when it expires.

Cookies are **opt-in** on purpose: anonymous downloads keep your account out of
the loop entirely, which is the safest default. Keep batches modest either way —
bulk-hammering Instagram is what gets accounts flagged.

---

## Configuration

All via environment variables (see `rkb/config.py`):

| variable | default | what it does |
|---|---|---|
| `RKB_DB` | `data/reels.db` | database path |
| `RKB_VAULT` | `./vault` | vault output directory |
| `RKB_BROWSER` | *unset* | `safari`/`chrome`/`firefox` — read cookies from a browser |
| `RKB_COOKIES` | *unset* | path to a Netscape `cookies.txt` |
| `RKB_WHISPER` | `mlx-community/whisper-large-v3-turbo` | try `whisper-small-mlx` for speed |
| `RKB_SLEEP` | `4` | seconds between downloads |
| `RKB_OCR_FPS` | `2` | frames per second sampled for OCR |
| `RKB_OCR_MAX_FRAMES` | `80` | cap on the dense OCR set per post |
| `RKB_GALLERY_WIDTH` | `300` | tile width of the image gallery on a reel note |
| `RKB_HUB_MIN` | `2` | posts a tool/tag needs before it gets a hub note |
| `RKB_LINK_MIN` | `2` | posts two hubs must share before they may be linked |
| `RKB_LINK_TOPK` | `4` | strongest associations each hub keeps |
| `RKB_STOPWORD_FRAC` | `0.5` | above this share of the library, a hub leaves the graph |
| `RKB_VAULT_REVIEW` | *unset* | `1` puts the review queue in the vault as note properties |

Frame sampling constants (`HEAD_SECONDS`, `HEAD_FPS`, `TAIL_FPS`, `MAX_FRAMES`,
`FRAME_WIDTH`) are edited in `rkb/config.py` directly.

## Data model

```sql
posts(shortcode PK, url, kind, saved_at, media_kind, caption, transcript,
      ocr_text, media_dir, status, error, imported_at, prepared_at,
      collection, author, author_link, hashtags, reviewed)

extractions(shortcode PK→posts, summary, detail, tools, links, prompt, tags,
            actionable, confidence, extracted_by, extracted_at)

search_idx  -- FTS5, porter unicode61, bm25 ranked
            -- covers summary, detail, tools, links, prompt, tags,
            --        caption, transcript, ocr_text, collection, author, hashtags
```

`status`: `new → prepared → extracted`, or `failed` / `archived`.
`reviewed`: `kept` / `archived`, set only by `rkb sync` or `rkb review`.

`tools`, `links`, `tags` and `hashtags` are JSON arrays. Schema changes are
applied to existing databases on open (`db._migrate`), including rebuilding the
FTS index when its columns change.

## Layout

```
rkb/
  config.py      all tunables
  db.py          connection, migrations, FTS reindex
  importer.py    Meta export → posts
  acquire.py     yt-dlp / gallery-dl
  frames.py      ffmpeg sampling
  transcribe.py  mlx-whisper + hallucination guard
  ocr.py         Apple Vision, slides for carousels
  prepare.py     stage 1 orchestration + context.md
  record.py      stage 2 write-back (validates links)
  verify.py      link checking and repair
  triage.py      payload classification
  dashboard.py   review queue rendering (browser)
  serve.py       local server; clicks write to the db
  review.py      apply review decisions
  search.py      FTS5 queries
  concepts.py    the hub graph: pruning, merging, clustering
  vault.py       Obsidian rendering
  graph.py       Obsidian graph-view settings
  vaultsync.py   read review decisions back out of Obsidian (opt-in)
  cli.py         argparse entry point
bin/rkb          shim (no venv activation needed)
data/            export/, media/, reels.db
vault/           generated Obsidian vault (safe to delete)
CLAUDE.md        extraction instructions for Claude Code
```

## Cost

The local pipeline is effectively free — measured on this library (69 posts,
39 min of audio, 683 images):

| stage | time |
|---|---|
| download (network-bound, throttled) | ~7 min |
| ffmpeg frame extraction | ~0.5 min |
| mlx-whisper (24.6× realtime) | 1.6 min |
| Apple Vision OCR | 1.2 min |
| **compute** | **~3.3 min** (≈6.7 Wh) |

The same transcription + OCR on cloud APIs would be about **$1.11**. The
extraction pass is where cost actually sits: reading 8 frames per post is ~0.9M
input tokens, so roughly **$15 on Opus** or **$1 on Haiku** per full pass — which
is why the pipeline stops at "prepared" and hands off a folder.

With OCR in place, extraction can run from text instead of images: ~82k input
tokens for the whole library, about **9× cheaper** than the image route.

---

## Contributing

Setup, the extraction contract, and what the code expects of a change are in
[CONTRIBUTING.md](CONTRIBUTING.md). Security-relevant behaviour — cookies, the
local dashboard server, what leaves your machine — is in
[SECURITY.md](SECURITY.md).

## A note on Instagram

This downloads media you have already saved to your own account, using either
anonymous access or your own session. Bulk-fetching with your cookies is against
Instagram's terms and is what gets accounts restricted, which is why cookies are
opt-in, `prepare` throttles on purpose, and neither is something to work around.
Downloaded posts remain the property of the people who made them; this builds a
private index of what you saved, not a redistribution of it.

## License

[Apache License 2.0](LICENSE) — permissive, with an explicit patent grant.
Copyright 2026 Manas Taneja.
