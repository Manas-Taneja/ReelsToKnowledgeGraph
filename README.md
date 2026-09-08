# Recall

Your saved internet, made searchable.

Recall turns saved Instagram reels, carousels, and X posts into a local, searchable knowledge base you can read and navigate as an Obsidian vault.

## Why

The useful part of a tech reel is often not the audio. It is a GitHub URL flashed on a title card for one second, a checklist that exists only as pixels, or a diagram buried in a carousel.

Transcription alone misses all of that.

Recall processes every post with both transcription and OCR, then extracts the useful information and links related concepts together.

![Pipeline: a Meta export runs through yt-dlp/gallery-dl, ffmpeg, mlx-whisper and Apple Vision on your machine, emits context.md per post, is processed by Claude Code, verified into SQLite, then rendered into search, triage, vault and graph views.](docs/assets/pipeline.svg)

Everything up to `context.md` runs on your machine with no API and no quota. There is no LLM call inside `rkb/`.

## What you get

![Obsidian graph view showing connected concept clusters.](docs/assets/graph.jpg)

Every tool and topic that appears across multiple posts becomes a hub note. Hubs link to each other by co-occurrence, so related saves stop living in isolation.

![Animated force-directed concept graph.](docs/assets/graph.gif)

![An Obsidian hub note showing related concepts and the posts that mention them.](docs/assets/hub-note.png)

Search for a concept and get the posts that touched it, strongest associations first.

## Requirements

| | | |
|---|---|---|
| macOS | Apple Silicon | OCR uses the system Vision framework; transcription uses MLX |
| Python | 3.11+ | 3.11 recommended (`.venv`) |
| ffmpeg | recent | frame sampling and audio extraction |
| yt-dlp | recent | reels and video posts |
| gallery-dl | recent | carousels and X |
| Obsidian | 1.9+ | optional — vault and review queue |

Apple Vision and MLX are the macOS-specific parts. On Linux, swap `rkb/ocr.py` for tesseract and `rkb/transcribe.py` for faster-whisper.

## Install

```bash
git clone https://github.com/Manas-Taneja/ReelsToKnowledgeGraph.git
cd ReelsToKnowledgeGraph

brew install ffmpeg yt-dlp gallery-dl
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

./bin/rkb init
```

`bin/rkb` runs the venv's Python directly, so activation is optional.

## Use

### 1. Add saved posts

There are three ways to get content into Recall.

**Instagram, in bulk**

Instagram → Accounts Center → Your information and permissions → Export your information → *Saved items*, as JSON. Unzip into `data/export/`, then:

```bash
./bin/rkb import
./bin/rkb collections
```

**X, in bulk**

```bash
./bin/rkb bookmarks
```

This uses your own session cookies; see `docs/cookies.md`.

**One link**

```bash
./bin/rkb add https://www.instagram.com/reel/Dbm7X5IAuEe/
./bin/rkb add https://x.com/simonw/status/1839283746152938495
```

Adding a link does not download anything.

### 2. Prepare

```bash
./bin/rkb prepare -n 25
./bin/rkb prepare -n 25 --retry
./bin/rkb prepare -n 25 --kind reel
./bin/rkb prepare --platform twitter
```

Prepare downloads media, samples frames, transcribes audio, and OCRs frames or slides. It runs locally with no API or quota.

### 3. Extract

Ask Claude Code to process the prepared batch. It reads each post's `context.md` and writes structured results through `./bin/rkb record`. See `CLAUDE.md` for the extraction contract.

### 4. Render and search

```bash
./bin/rkb vault
./bin/rkb triage
./bin/rkb dashboard --serve
./bin/rkb search "rag"
```

The output is an Obsidian vault plus SQLite-backed search and review tools.

## From your phone

Forward a saved post into your own Telegram bot:

```bash
./bin/rkb telegram
```

Saving only adds the post to the queue. A **Prepare N waiting** button lets you start processing when you are back at your machine.

There is also:

```bash
./bin/rkb ingest --serve
```

for driving the same queue from an iOS Shortcut over HTTP.

## Documentation

| | |
|---|---|
| **[The pipeline](docs/pipeline.md)** | Frame sampling, OCR, link verification, triage, and processing cost |
| **[The Obsidian vault](docs/vault.md)** | Notes, tables, and the concept graph |
| **[Reference](docs/reference.md)** | Environment variables, schema, and module layout |
| **[Cookies](docs/cookies.md)** | Session handling for Instagram and X |
| **[Telegram](docs/telegram.md)** | Bot setup and queue handling |

## A note on Instagram and X

Recall works on media you have already saved to your own accounts, using anonymous access where possible and your own session cookies where required. Keep volume low and respect platform terms. Downloaded posts stay in your private index; Recall does not redistribute them.

## License

Apache License 2.0 — permissive, with an explicit patent grant.

Copyright 2026 Manas Taneja.
