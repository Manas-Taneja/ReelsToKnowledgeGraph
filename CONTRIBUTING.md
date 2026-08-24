# Contributing

## Setup

macOS on Apple Silicon. Transcription uses `mlx-whisper` (Metal) and OCR uses
the system Vision framework, so neither has a cross-platform path today.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
./bin/rkb init
```

You need your own Instagram data export to have anything to run against — the
repo ships no library, by design.

## The shape of the thing

Two stages, deliberately separated:

1. **`rkb prepare`** downloads media, samples frames, transcribes, OCRs, and
   writes a self-contained `context.md` per post.
2. **Extraction** is a human running Claude Code over that `context.md`, piping
   JSON into `rkb record`. There is no LLM API call anywhere in `rkb/`.

That split is the point, not an unfinished bit. It keeps every extraction
attributable and re-runnable, and it means the tool costs nothing to operate.
`CLAUDE.md` holds the extraction contract — the output schema and the rules
about what may and may not be inferred. Change that file if you change what an
extraction is allowed to say.

## What the code expects of you

**Comments explain why, not what.** The reason a threshold is `2` and not `1`
belongs next to it, ideally with the number that settled it. Most of the
non-obvious decisions in `concepts.py` and `triage.py` are documented that way,
and a change that removes the reasoning is worse than one that leaves it stale.

**Prove behaviour by running it.** Two bugs here — Obsidian not indexing through
symlinks, and Obsidian overwriting `.obsidian/*.json` while running — were only
found by checking what actually happened, and both looked fine on inspection.
Claims about thresholds should come with the counts they produce.

**Never commit anything under `data/` or `vault/`.** Both are gitignored;
`vault/` is generated, and `data/` is somebody's saved-post history.

## Verifying a change

There is no test suite. The commands are the check:

```bash
./bin/rkb status            # what's in the database
./bin/rkb triage            # dry run; never mutates without --apply
./bin/rkb vault             # regenerates every note it owns
./bin/rkb graph             # refuses while Obsidian is running
```

Regenerating twice should produce byte-identical output. If it doesn't,
something is non-deterministic and that is a bug on its own.

## Pull requests

Small and self-describing. Say what you observed, not just what you changed —
the reasoning is the part that's hard to reconstruct later.

By contributing you agree that your contributions are licensed under the
Apache License 2.0, the same terms covering the project.
