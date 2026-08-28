# The Telegram front door

Forward a post from your phone's share sheet and it lands in the knowledge
base — no Meta export, no pasting into a terminal.

It is a bot rather than an endpoint your phone posts to for one reason:
`getUpdates` long-polls *outward*. Nothing about your network has to change —
no inbound port, no tunnel, no static IP — and it keeps working when the laptop
moves between wifi networks. That is the whole of what the chat platform buys
you. Downloading, transcription and OCR still happen locally, and the
extraction pass is still yours in Claude Code.

There is no library here. It is Telegram's HTTP Bot API over stdlib `urllib`,
the same way `verify.py` already checks links, so it adds no dependency and no
licence to reason about.

## Setup

**1. Make a bot.** Message [@BotFather](https://t.me/botfather) on Telegram,
send `/newbot`, answer the two questions. It replies with a token.

```sh
export RKB_TELEGRAM_TOKEN='123456:AA...'
```

**2. Find your chat id.** Run `./bin/rkb telegram` and message your new bot
anything. It refuses you and replies with the id — that is the point, an unset
allowlist defaults closed rather than open. Anyone who finds the bot's username
can message it, and ingesting starts downloads on your machine.

```sh
export RKB_TELEGRAM_ALLOW='987654321'      # space- or comma-separated
```

**3. Restart it.** Put both exports in your shell profile so it survives a new
terminal.

```sh
./bin/rkb telegram
```

## Using it

- **Send or forward any post link.** Instagram share sheet → Telegram → your
  bot. The link can be bare, buried in commentary, in a caption, hyperlinked
  behind a word, or in a message you reply to.
- **Saving downloads nothing.** The link is recorded and that is all. The reply
  tells you how many posts are waiting and carries a **⚡ Prepare N waiting**
  button.
- **Tap the button when you are at the machine** — or send `/prepare`, or
  `/prepare 5` for just the first five. That is when the downloading,
  transcription and OCR happen. The bot reports back with what worked and
  names anything that failed.
- A link you already have comes back with its summary and repo link instead of
  being queued twice.
- `/status` — counts per platform and stage, plus the button if anything waits.
- `/show <shortcode>` — everything known about one post.

The split is the point: transcription and OCR run on your own hardware, so
forwarding a link from the train should not spin the fans on a laptop at home.
Links accumulate; you drain them when it suits you.

Only one batch runs at a time. Asking again while one is in flight tells you so
rather than starting a second, which would fetch in parallel — the thing
`prepare`'s sleep between posts exists to avoid.

In a group chat the bot stays silent on messages with no link, so it does not
answer every unrelated sentence. In a DM it tells you it found nothing.

## Caveat

Links you send transit Telegram's servers. For public posts that is likely a
non-issue; if it is not, `rkb ingest --serve` plus an iOS Shortcut keeps the
traffic between your phone and your Mac, at the cost of needing the Mac
reachable (Tailscale or similar).
