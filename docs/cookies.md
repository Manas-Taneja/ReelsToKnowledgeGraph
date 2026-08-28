# Cookies: when they are optional, and when they are not

[← back to the README](../README.md)

## Instagram

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

## X

X is the stricter case: it serves a logged-out client almost nothing, so cookies
here are **required, not opt-in**. `rkb bookmarks` refuses to run without them,
and `rkb prepare` fails a tweet with that hint rather than a generic download
error.

Same two routes, but with X-specific variables so the two accounts can live in
different browsers:

```bash
RKB_X_BROWSER=safari ./bin/rkb bookmarks
RKB_X_COOKIES=/path/to/x-cookies.txt ./bin/rkb bookmarks
```

Both fall back to `RKB_BROWSER` / `RKB_COOKIES` when unset, so if you use one
browser for everything you can ignore them entirely.

> The same warning applies, more so: that jar is a live X session, and the
> bookmark feed is your whole saved library. Keep it out of the repo.

`rkb bookmarks -n 25` walks only the most recent 25, which is usually what you
want — the feed is newest-first, so a small number is "what did I save this
week" rather than a full re-scrape.
