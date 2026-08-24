# The pipeline

What happens to a post between saving it on Instagram and reading it in
Obsidian.

[← back to the README](../README.md)

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

## Frame sampling

Weighted toward the opening beat, because tech reels put the tool name or link
on a title card in the first second and then cut away: every 0.5 s for the first
3 s, every 2 s after, `mpdecimate` to drop near-identical frames, capped at 8
frames scaled to 768 px. Frames are extracted for *every* post, never
conditionally on whether speech was found.

## OCR

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

## Link verification

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

## Triage

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
