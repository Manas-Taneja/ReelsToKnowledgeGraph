# Image and carousel posts need cookies

[← back to the README](../README.md)

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
