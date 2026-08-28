# Reference

Every environment variable, the database schema, and where each module
lives.

[← back to the README](../README.md)

## Configuration

All via environment variables (see `rkb/config.py`):

| variable | default | what it does |
|---|---|---|
| `RKB_DB` | `data/reels.db` | database path |
| `RKB_VAULT` | `./vault` | vault output directory |
| `RKB_BROWSER` | *unset* | `safari`/`chrome`/`firefox` — read cookies from a browser |
| `RKB_COOKIES` | *unset* | path to a Netscape `cookies.txt` |
| `RKB_X_BROWSER` | falls back to `RKB_BROWSER` | cookie source for X only |
| `RKB_X_COOKIES` | falls back to `RKB_COOKIES` | `cookies.txt` for X only |
| `RKB_X_BOOKMARK_LIMIT` | `100` | how far back `rkb bookmarks` walks the feed |
| `RKB_BATCH_LIMIT` | `25` | posts one `/prepare` or button tap drains |
| `RKB_TELEGRAM_TOKEN` | *unset* | bot token from @BotFather; required by `rkb telegram` |
| `RKB_TELEGRAM_ALLOW` | *unset* | chat ids allowed to use the bot; unset refuses everything |
| `RKB_INGEST_HOST` | `127.0.0.1` | bind address for `rkb ingest --serve` |
| `RKB_INGEST_PORT` | `8787` | its port |
| `RKB_INGEST_TOKEN` | *unset* | shared secret; required if the host is not loopback |
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
posts(shortcode PK, url, kind, platform, saved_at, media_kind, caption,
      transcript, ocr_text, media_dir, status, error, imported_at,
      prepared_at, collection, author, author_link, hashtags, reviewed)

extractions(shortcode PK→posts, summary, detail, tools, links, prompt, tags,
            actionable, confidence, extracted_by, extracted_at)

search_idx  -- FTS5, porter unicode61, bm25 ranked
            -- covers summary, detail, tools, links, prompt, tags,
            --        caption, transcript, ocr_text, collection, author, hashtags
```

`status`: `new → prepared → extracted`, or `failed` / `archived`.
`platform`: `instagram` / `twitter`, backfilled to `instagram` on upgrade.
`kind`: `reel` / `post` / `tweet`. `media_kind`: `video` / `images` / `text` —
`text` is an X post carrying no media, which has no frames and no transcript by
nature rather than by failure.
`reviewed`: `kept` / `archived`, set only by `rkb sync` or `rkb review`.

`tools`, `links`, `tags` and `hashtags` are JSON arrays. Schema changes are
applied to existing databases on open (`db._migrate`), including rebuilding the
FTS index when its columns change.

## Layout

```
rkb/
  config.py      all tunables
  db.py          connection, migrations, FTS reindex
  platforms.py   the platform registry: URL shapes, vault folders, cookies
  importer.py    Meta export → posts
  ingest.py      a pasted link, or the X bookmark feed → posts
  worker.py      runs one prepare batch at a time, off the calling thread
  telegram.py    Telegram front door (stdlib urllib, no library)
  ingestd.py     HTTP front door (iOS Shortcut, curl)
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
