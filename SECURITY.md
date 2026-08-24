# Security

## Reporting a vulnerability

Use [private vulnerability reporting](https://github.com/Manas-Taneja/reels-kb/security/advisories/new)
rather than a public issue. I'll acknowledge within a week.

## What this tool touches

`rkb` runs entirely on your machine. There is no server, no account, and no
telemetry. That said, it handles three things worth knowing about:

**Your Instagram session.** `RKB_COOKIES` points at a cookies file that is a
live login. Anything that can read that file can act as you on Instagram. Keep
it outside the repo — `.gitignore` has a backstop pattern, but it is a backstop,
not the arrangement. Cookies are opt-in and only needed for image and carousel
`/p/` posts; reels download anonymously.

**Your library.** `data/reels.db` holds the caption, transcript and OCR text of
every post you've saved, and `data/your_instagram_activity/` is your raw Meta
export. Both are gitignored, along with the database's write-ahead log — note
that ignoring `reels.db` alone is *not* enough, because `reels.db-wal` carries
recent pages in the clear.

**A local web server.** `rkb dashboard --serve` binds `127.0.0.1:8765`. It is
loopback-only and unauthenticated, on the assumption that anyone who can reach
loopback on your machine is you. Don't expose it through a tunnel or a reverse
proxy.

## Outbound network

Instagram (media download), Hugging Face (Whisper model, first run only), and
HEAD requests to URLs found in posts to check whether they resolve. Nothing else.

## Not a vulnerability

Rate-limiting and account flagging. `prepare` sleeps between downloads on
purpose, and bulk-fetching with your own cookies is what gets accounts
restricted. That is a property of using the tool aggressively, not a defect in
it — but it is a real risk, and you own it.
