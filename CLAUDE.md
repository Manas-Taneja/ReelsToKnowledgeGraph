# Reels To Knowledge Base

Turns saved Instagram reels and carousels, and saved X posts, into a
searchable, actionable knowledge base: SQLite + FTS5 for the pipeline, an
Obsidian vault as the readable view.

## Why the pipeline is split

Everything mechanical runs locally and free — download, frame sampling,
transcription, OCR. Only the judgement step needs a model, and it runs on the
Claude Code subscription rather than per-token API billing.

```
1. rkb prepare   download, sample frames, transcribe, OCR      (plain Python)
2. extraction    read the context, write structure back        (you)
3. rkb vault     render the database as markdown               (plain Python)
```

SQLite is the source of truth. The vault is a generated view, so `rkb vault` is
safe to re-run after every batch.

## Where posts come from

Three doors, all landing in the same `posts` table at status `new`:

```
rkb import      the Meta export           (Instagram, bulk backfill)
rkb bookmarks   the live X bookmark feed  (X, bulk, needs cookies)
rkb add <url>   one link, any platform    (either, no export needed)
```

`add` never downloads. It records the row and stops; `rkb prepare` is a
separate, deliberate act, because saving costs milliseconds and preparing costs
a video download, ffmpeg, whisper and OCR on this machine.

`rkb/platforms.py` is the only place a platform is described. Adding a third
source is a row in that table plus a branch in `acquire`, not a new pipeline.

## Your job: the extraction pass

When asked to extract, process or ingest a batch:

1. `./bin/rkb pending -n 25` — list posts awaiting extraction.
2. For each, read `<media_dir>/context.md`. It contains the caption, the
   transcript, and **the verbatim OCR text of every frame or slide**. A
   text-only X post has none of those: `media_kind` is `text`, and the tweet
   text under `## Tweet text` is the entire post. There are no frames to open
   and nothing is missing — do not file it as under-prepared.
3. Read images from `<media_dir>/frames/` only when the OCR is ambiguous — a
   blurred URL, a layout you can't reconstruct from text alone. OCR is cheaper
   and more literal than a vision read; prefer it.
4. Emit one JSON object per post and write them back in one call:
   `./bin/rkb record batch.json`
5. `./bin/rkb vault` to refresh Obsidian.
6. `./bin/rkb triage` to see what carries no payload — anything without a link
   lands in the user's review queue, which is theirs to decide, not yours.

### Output schema

```json
[
  {
    "shortcode": "Dbm7X5IAuEe",
    "summary": "one line — what this post is actually about",
    "detail": "2–4 sentences: what the tool/technique does and how it was used",
    "tools": ["Claude Code", "mlx-whisper"],
    "links": ["https://github.com/owner/repo"],
    "prompt": null,
    "tags": ["agents", "local-llm"],
    "actionable": "clone the repo and run the example, or null",
    "confidence": "high"
  }
]
```

## Rules that matter

**The link is the payload.** Hunt for the repo or URL before anything else —
check the OCR text, every frame including the last, and the caption. Every post
you leave without a link goes to the user's review queue, where they read the
raw OCR themselves, so an empty `links` is a claim that you looked and found
nothing.

**Do not compose prompts.** The verbatim on-screen text is already captured in
`ocr_text` and rendered in full on every vault note and dashboard card — the
user reads it there and lifts what they want. Leave `prompt` null. Do not
rewrite a checklist into a "drill", add framing, reorder items, or drop half of
it to make a nicer artefact. Your job is to find the link and describe the post,
not to design study material out of it.

**When the address bar is covered, read the chrome around it.** A screen
recording usually leaks the repo owner somewhere else in the frame: a browser
tab title, an adjacent tab, a window title, a terminal prompt, a git remote, a
Docker image name, a GitHub sidebar avatar. This is a real miss from the first
pass — FreeLLMAPI's owner (`tashfeenahmed`) was legible in a neighbouring tab
while the URL bar sat behind a caption overlay, and the post was filed as "no
link". Exhaust the frame before declaring a link unrecoverable.

**Resolve a named tool to its canonical repo** when you are certain
(`Appsmith` → `https://github.com/appsmithorg/appsmith`). If you are not
certain, leave `links` empty and set `confidence: medium`.

**Never invent.** A missing link is recoverable from the review dashboard; a
wrong one silently sends the user nowhere. `rkb record` HEAD-checks every URL,
repairs OCR truncations (`.../network/dependen` → `.../network/dependents`) and
drops dead ones — but it only proves a URL *resolves*, not that it points at the
right project. That part is still on you.

**A comment-wall is not automatically a dead end.** "Comment X and I'll send the
link" often gates a *guide* while the tool itself is public. Appsmith's setup
guide was gated; Appsmith is a 40k-star public repo. Judge what is actually
withheld.

**Trust OCR over the transcript for names.** Whisper mis-hears tool names — it
rendered `ntfy` as "Notify". When the two disagree on a name or URL, the frames
win.

**`tools` and `tags` are graph vocabulary, not description.** They become hub
notes, and the hubs link to each other by co-occurrence — that concept map is
the point of the vault (`rkb/concepts.py` builds it; the graph view shows only
`Tools/` and `Topics/`). Three consequences for how you write them:

- **Spell them the same way every time.** A name only becomes a hub once two
  posts share it, so "Claude Code" spelled two ways is two singletons and
  therefore no hub at all — the connection is silently lost, not merely
  mis-styled. Check what already exists: `ls vault/Tools vault/Topics`.
- **Reuse tags across the library.** `rag`, `agents`, `mcp`, `local-llm`,
  `evals`, `prompt-engineering`, `automation`, `self-hosted` earn their place; a
  phrase that describes one post contributes nothing to a map.
  `sqlite3 data/reels.db "SELECT DISTINCT value FROM extractions, json_each(tags)"`
- **Don't reach for the near-universal one.** A tag on more than half the
  library is dropped from the graph as a stopword — it co-occurs with everything
  and so separates nothing. `open-source` already went that way here; tagging
  everything `ai` would too.

**Respect the user's own filing.** `collection` is a category they assigned by
hand in Instagram; let it inform tags rather than contradict it.

**`actionable` is the payoff field.** The concrete next step ("clone X and run
the demo notebook", "sign up for the beta"), or null if the post is commentary.

Batch 20–30 posts per session.

## Commands

```
./bin/rkb init                    # create db + folders
./bin/rkb import [paths...]       # load the Meta export (default: data/)
./bin/rkb import --exclude food   # never import a collection
./bin/rkb add <url> [...]         # save a link (Instagram or X), no export
./bin/rkb bookmarks [-n 100]      # sweep the live X bookmark feed
./bin/rkb collections             # counts per collection
./bin/rkb prepare -n 25 [--retry] # download + frames + transcribe + OCR
./bin/rkb prepare --platform twitter   # ...one source only (instagram|twitter)
./bin/rkb ocr [--force] [codes]   # re-read text off slides / dense video frames
./bin/rkb pending -n 25           # what's awaiting extraction
./bin/rkb record batch.json       # write results back (validates links)
./bin/rkb verify                  # re-check every recorded link
./bin/rkb triage                  # link = cleared; no link = your review queue
./bin/rkb dashboard --serve       # review queue; clicks save straight to the db
./bin/rkb sync [--watch]          # (opt-in) read decisions made in Obsidian
./bin/rkb review                  # (static fallback) apply decisions via clipboard
./bin/rkb search "rag"            # FTS5 search
./bin/rkb status                  # counts per stage
./bin/rkb show <shortcode>        # everything known about one post
./bin/rkb vault                   # render the Obsidian vault
./bin/rkb graph                   # style the graph view (quit Obsidian first)
```

## Notes

- **On X, cookies are not optional.** X serves a logged-out client almost
  nothing, so `bookmarks` refuses to run without them and `prepare` fails with
  that hint rather than a generic download error. `RKB_X_BROWSER` /
  `RKB_X_COOKIES` override the Instagram settings for X only, which is what you
  want when the two accounts live in different browsers; unset, they fall back
  to `RKB_BROWSER` / `RKB_COOKIES`.
- **A tweet with no media is not a failed download.** `media_kind='text'`, no
  frames, no transcript, no OCR — the text is the post. `prepare` only raises
  when a tweet has neither media nor text.
- **Instagram cookies are opt-in and usually unnecessary.** Reels download anonymously,
  which keeps the account out of the loop entirely. Image and carousel `/p/`
  posts do hit a login wall — for those, grant the terminal Full Disk Access and
  use `RKB_BROWSER=safari`. No browser extension needed.
- `prepare` sleeps between downloads on purpose. Bulk-hammering Instagram is
  what gets accounts flagged.
- Failures never abort a batch; they're recorded on the row and retried with
  `prepare --retry`.
- Vault images are hard links in `vault/attachments/<shortcode>-NN.jpg`, one per
  slide or keyframe, embedded as `![[<shortcode>-NN.jpg|300]]`. The filename is
  the only join back to the post; there is no attachments table. Do not go back
  to a symlink — Obsidian does not index through one, and every embed silently
  breaks. A carousel's gallery comes from the downloaded slides, never from
  `frames/`, which is capped at `MAX_FRAMES` and would drop over half the
  slides on the longer listicle posts.
- **Source notes are filed by platform**: `vault/Reels/` for Instagram,
  `vault/Tweets/` for X, from `platforms.folders()`. The split is cosmetic —
  `Tools/` and `Topics/` hubs span both, so the concept map stays one map. Note
  titles are unique across the whole library, not per folder. Every post note
  still carries `reel: true`, which is what `Library.base` filters on; read it
  as "an rkb post note", and filter on `platform` when you want one source.
- `vault/Repos.md` and `vault/Prompts.md` are derived views, not stores.
  `Repos.md` normalises every `github.com` URL to `owner/repo`, so a repo seen
  in three posts is one row. `Prompts.md` is *kept, and carrying no payload
  link* — there is no `prompt` flag to read, because `extractions.prompt` is
  null by contract and the dashboard writes the same `reviewed='kept'` for
  "prompt is the payload" as for a plain keep. Do not invent a flag to make the
  set narrower; change the rule in `vault.prompt_posts()` if it needs changing.
- `rkb vault` regenerates every note it owns; never hand-edit one. Fix the
  database or the renderer. `rkb graph` is only needed when the vocabulary
  shifts enough to change the clusters, not after every batch.
- **Never edit `.obsidian/*.json` while Obsidian is running.** It holds that
  state in memory and writes it back on exit, discarding the edit without a
  word. `rkb graph` refuses to run in that situation; do the same by hand.
- Anything typed below the `rkb:end` marker in a vault note survives
  regeneration. Notes rkb didn't write are never touched.
- **The review queue is the HTML dashboard**, `rkb dashboard --serve`. The vault
  can host the same queue as note properties (`RKB_VAULT_REVIEW=1`, then
  `rkb sync`), but it is off by default: two surfaces for one decision is one
  too many. Do not turn it on unprompted.
- **Never record a review decision yourself.** The queue exists for questions
  you already declined to guess at. A link you found goes through `rkb record`.
