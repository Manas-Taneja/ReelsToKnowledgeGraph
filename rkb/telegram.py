"""Forward a post into a Telegram chat; it lands in the knowledge base.

Written straight against Telegram's Bot API over stdlib urllib -- there is no
library here to depend on or be licensed by. `verify.py` already talks HTTP the
same way.

The reason this is a bot rather than an endpoint your phone posts to: getUpdates
long-polls *outward*. Nothing about your network has to change -- no inbound
port, no tunnel, no static IP -- and it keeps working when the laptop moves
between wifi networks. That, and nothing else, is what the chat platform buys
you here. The downloading, transcription and OCR all still happen locally, and
the extraction pass is still yours in Claude Code.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, db, ingest, platforms, worker

API = "https://api.telegram.org/bot{token}/{method}"
POLL = 25          # seconds Telegram holds the connection open
MAX_TEXT = 3900    # Telegram's limit is 4096; leave room for our own framing

HELP = (
    "Send me an Instagram or X link and I'll save it.\n\n"
    "Saving is instant — nothing downloads until you ask. Transcription and "
    "OCR run on the machine at home, so they wait for you to drain the queue.\n\n"
    "/prepare [n] — download + transcribe + OCR everything waiting\n"
    "/status — what the knowledge base holds\n"
    "/show <shortcode> — everything known about one post"
)


class TelegramError(RuntimeError):
    pass


def _call(method, params=None, timeout=POLL + 15):
    url = API.format(token=config.TELEGRAM_TOKEN, method=method)
    data = json.dumps(params or {}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        # Telegram puts the useful part in the body, not the status line.
        try:
            body = json.loads(e.read())
        except Exception:
            raise TelegramError(f"{method}: HTTP {e.code}")
        raise TelegramError(f"{method}: {body.get('description') or e.code}")
    if not body.get("ok"):
        raise TelegramError(f"{method}: {body.get('description')}")
    return body["result"]


def _prepare_button(n):
    """The literal button: one tap drains the queue, from wherever you are."""
    if not n:
        return None
    return {"inline_keyboard": [[{
        "text": f"⚡ Prepare {n} waiting", "callback_data": "prepare"}]]}


def _send(chat_id, text, reply_to=None, markup=None):
    payload = {"chat_id": chat_id, "text": text[:MAX_TEXT],
               "disable_web_page_preview": True}
    if markup:
        payload["reply_markup"] = markup
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        _call("sendMessage", payload, timeout=20)
    except TelegramError as e:
        # A reply that cannot be delivered must not stop us ingesting the next
        # link -- the post is already saved either way.
        print(f"  could not reply in {chat_id}: {e}", flush=True)


def _allowed():
    """Chat ids permitted to use the bot, from RKB_TELEGRAM_ALLOW."""
    raw = config.TELEGRAM_ALLOW
    return {x.strip() for x in raw.replace(",", " ").split() if x.strip()}


def _text_of(msg):
    """Whatever text a message carries, however it was sent.

    A post forwarded from the Instagram or X share sheet can arrive as the
    message body, as a caption on an attached preview, or inside a quoted
    message -- so take all three rather than only `text`.
    """
    parts = [msg.get("text"), msg.get("caption")]
    quoted = msg.get("reply_to_message") or {}
    parts += [quoted.get("text"), quoted.get("caption")]
    for ent in (msg.get("entities") or []) + (msg.get("caption_entities") or []):
        if ent.get("url"):                 # a hyperlinked word hides its target
            parts.append(ent["url"])
    return "\n".join(p for p in parts if p)


def _start_batch(chat_id, text=""):
    """Drain the queue, reporting when it finishes rather than blocking."""
    con = db.init()
    n = worker.pending(con)
    if worker.busy():
        return _send(chat_id, f"already running — {n} left")
    if not n:
        return _send(chat_id, "nothing waiting")

    limit = None
    parts = (text or "").split()
    if len(parts) > 1 and parts[1].isdigit():
        limit = int(parts[1])

    def done(result):
        ok, bad = len(result["prepared"]), len(result["failed"])
        lines = [f"prepared {ok}" + (f", {bad} failed" if bad else "")]
        # Name the failures. A silent "3 failed" means opening a terminal to
        # find out which, which defeats the point of a button.
        for sc, err in result["failed"][:5]:
            lines.append(f"  {sc}: {err[:140]}")
        left = worker.pending()
        if left:
            lines.append(f"\n{left} still waiting")
        _send(chat_id, "\n".join(lines),
              markup=_prepare_button(left) if left else None)

    started = worker.run_batch(limit=limit, on_done=done)
    take = min(limit or config.BATCH_LIMIT, n)
    _send(chat_id, f"preparing {take}… downloading, transcribing and reading "
                   f"the frames. I'll report back."
          if started else "already running")
    print(f"     batch started ({take})", flush=True)


def _on_callback(cq):
    """A tap on the inline button arrives as a callback_query, not a message."""
    chat = ((cq.get("message") or {}).get("chat")) or {}
    chat_id = chat.get("id")
    # Telegram spins the button until it is answered, so answer first and
    # always -- an unanswered tap looks like a hung bot.
    try:
        _call("answerCallbackQuery", {"callback_query_id": cq["id"]}, timeout=15)
    except TelegramError:
        pass
    if chat_id is None or str(chat_id) not in _allowed():
        return
    print(f"  <- button: {cq.get('data')}", flush=True)
    if cq.get("data") == "prepare":
        _start_batch(chat_id)


def _handle(con, msg):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = _text_of(msg).strip()
    # One line per message, always. A bot run under a service manager is only
    # as debuggable as its log, and logging solely the failures means a
    # message that silently did nothing looks identical to one that never
    # arrived at all.
    who = chat.get("username") or chat.get("first_name") or chat_id
    print(f"  <- {who}: {' '.join(text.split())[:120] or '(no text)'}", flush=True)

    # Anyone who finds the bot's username can message it, and ingesting starts
    # downloads on your machine. So the allowlist is not optional -- an unset
    # one refuses everything and tells you the id to add, rather than defaulting
    # open.
    allow = _allowed()
    if str(chat_id) not in allow:
        who = chat.get("username") or chat.get("first_name") or "unknown"
        print(f"  refused {chat_id} ({who})", flush=True)
        _send(chat_id,
              "This bot is not set up for you.\n\n"
              f"If it is yours, add this chat id to RKB_TELEGRAM_ALLOW and "
              f"restart:\n{chat_id}")
        return

    if text.startswith("/start") or text.startswith("/help"):
        return _send(chat_id, HELP)

    if text.startswith("/prepare"):
        return _start_batch(chat_id, text)

    if text.startswith("/status"):
        rows = con.execute(
            "SELECT platform, status, COUNT(*) n FROM posts "
            "GROUP BY platform, status ORDER BY platform, n DESC").fetchall()
        lines = []
        for plat in sorted({r["platform"] for r in rows}):
            mine = [r for r in rows if r["platform"] == plat]
            lines.append(f"{platforms.get(plat).label} ({sum(r['n'] for r in mine)})")
            lines += [f"  {r['status']}: {r['n']}" for r in mine]
        n = worker.pending(con)
        if n:
            lines.append(f"\n{n} waiting to be prepared"
                         + (" (running now)" if worker.busy() else ""))
        return _send(chat_id, "\n".join(lines) or "nothing saved yet",
                     markup=None if worker.busy() else _prepare_button(n))

    if text.startswith("/show"):
        parts = text.split()
        if len(parts) < 2:
            return _send(chat_id, "usage: /show <shortcode>")
        hit = worker.summary(con, parts[1])
        return _send(chat_id, f"{hit['url']}\n{worker.describe(hit)}" if hit
                     else f"no post {parts[1]}")

    if not text:
        return

    result = ingest.add_urls(text)
    if result.get("unrecognised"):
        # In a DM every message is aimed at the bot, so saying "that had no
        # link" is useful. In a group it would answer every unrelated sentence,
        # so there it says nothing.
        if (chat.get("type") or "private") == "private":
            _send(chat_id, "No Instagram or X post link in that.",
                  msg.get("message_id"))
        return

    lines = []
    for p in result["added"]:
        print(f"     saved {p['platform']} {p['shortcode']}", flush=True)
        lines.append(f"saved {p['platform']} {p['shortcode']}")
    for p in result["known"]:
        # Re-sending a link you already have should tell you what is known
        # about it, not queue it a second time.
        hit = worker.summary(con, p["shortcode"]) or p
        lines.append(f"already have {p['shortcode']} — {worker.describe(hit)}")
    if not lines:
        return
    # Nothing has been downloaded at this point and nothing will be until you
    # ask -- so say what is waiting, and put the trigger right there.
    n = worker.pending(con)
    if n and not worker.busy():
        lines.append(f"\n{n} waiting — nothing downloads until you say so.")
    _send(chat_id, "\n".join(lines), msg.get("message_id"),
          markup=None if worker.busy() else _prepare_button(n))


def run():
    if not config.TELEGRAM_TOKEN:
        raise RuntimeError(
            "RKB_TELEGRAM_TOKEN is unset. Create a bot by messaging @BotFather "
            "on Telegram (/newbot), then export the token it gives you.")

    me = _call("getMe", timeout=20)
    # flush throughout: piped to a log or run under a service manager, stdout
    # is block-buffered, and a bot whose startup banner appears an hour later
    # looks like a bot that never started.
    print(f"rkb telegram: @{me.get('username')} listening", flush=True)
    allow = _allowed()
    print(f"  allowed chats: {', '.join(sorted(allow)) if allow else 'NONE'}",
          flush=True)
    if not allow:
        print("  message the bot once — it will print and reply with your chat "
              "id, then set RKB_TELEGRAM_ALLOW to it and restart.", flush=True)
    print("  Ctrl-C to stop.\n", flush=True)

    con = db.init()
    waiting = worker.pending(con)
    print(f"  {waiting} post(s) waiting to be prepared"
          if waiting else "  nothing waiting", flush=True)
    offset, backoff = None, 1
    while True:
        try:
            params = {"timeout": POLL,
                      "allowed_updates": ["message", "callback_query"]}
            if offset is not None:
                params["offset"] = offset
            updates = _call("getUpdates", params)
            backoff = 1
        except KeyboardInterrupt:
            print("\nstopped.")
            return
        except (TelegramError, urllib.error.URLError, TimeoutError, OSError) as e:
            # A dropped wifi connection is normal on a laptop. Back off rather
            # than exiting, so the bot is still there when the network is.
            print(f"  poll failed ({e}); retrying in {backoff}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        for u in updates:
            offset = u["update_id"] + 1
            try:
                if u.get("callback_query"):
                    _on_callback(u["callback_query"])
                elif u.get("message"):
                    _handle(con, u["message"])
            except Exception as e:      # one bad update must not stop the bot
                print(f"  handler error: {e}", flush=True)
