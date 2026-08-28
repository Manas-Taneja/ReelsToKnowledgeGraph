"""The front door: a small HTTP endpoint that turns a shared link into a post.

This exists so something outside the terminal can put a link into the pipeline
over HTTP -- an iOS Shortcut on the share sheet, a curl from another machine,
anything that can POST JSON. The Telegram bot in `rkb/telegram.py` does not
need this: it calls the same functions in-process.

What it does NOT do is any of the work. Ingest records the row and hands it to
the worker, which runs the existing `prepare` stage on this machine, where
yt-dlp, ffmpeg and the local models already live. The extraction pass stays
where CLAUDE.md puts it: in Claude Code, on the subscription, not per token.

Loopback-only by default. This endpoint starts downloads on your machine, so
exposing it wants a deliberate RKB_INGEST_HOST plus a token.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, db, ingest, worker

_summary = worker.summary


class _Handler(BaseHTTPRequestHandler):
    server_version = "rkb-ingest"

    def log_message(self, fmt, *args):        # one line, not three
        print(f"  {self.address_string()} {fmt % args}", flush=True)

    def _reply(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if not config.INGEST_TOKEN:
            return True
        if self.headers.get("X-RKB-Token") == config.INGEST_TOKEN:
            return True
        self._reply(401, {"error": "bad or missing X-RKB-Token"})
        return False

    def do_GET(self):
        if not self._authed():
            return
        con = db.init()
        if self.path.startswith("/post/"):
            hit = _summary(con, self.path.rsplit("/", 1)[-1])
            return self._reply(200 if hit else 404, hit or {"error": "unknown post"})
        if self.path.rstrip("/") in ("", "/status"):
            rows = con.execute("SELECT platform, status, COUNT(*) n FROM posts "
                               "GROUP BY platform, status").fetchall()
            return self._reply(200, {
                "counts": [dict(r) for r in rows],
                "waiting": worker.pending(con),
                "preparing": worker.busy(),
            })
        self._reply(404, {"error": "no such endpoint"})

    def do_POST(self):
        if not self._authed():
            return
        if self.path.rstrip("/") == "/prepare":
            n = worker.pending()
            if worker.busy():
                return self._reply(409, {"error": "a batch is already running",
                                         "waiting": n})
            if not n:
                return self._reply(200, {"started": False, "waiting": 0})
            worker.run_batch()
            return self._reply(202, {"started": True, "waiting": n})
        if self.path.rstrip("/") != "/ingest":
            return self._reply(404, {"error": "no such endpoint"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._reply(400, {"error": "body must be JSON"})

        text = body.get("text") or body.get("url") or ""
        result = ingest.add_urls(text, collection=body.get("collection")
                                 or ingest.VIA_BOT)
        if result.get("unrecognised"):
            return self._reply(422, {
                "error": "no Instagram or X post link in that message",
                **result})

        # Recording a link is instant; preparing it costs a download, whisper
        # and OCR on this machine. They are separate acts, so ingest never
        # starts one -- pass {"prepare": true}, or POST /prepare, to drain.
        if body.get("prepare"):
            worker.run_batch()

        con = db.init()
        result["known"] = [_summary(con, p["shortcode"]) or p
                           for p in result["known"]]
        result["waiting"] = worker.pending(con)
        result["preparing"] = worker.busy()
        self._reply(200, result)


def serve(host=None, port=None):
    host = host or config.INGEST_HOST
    port = port if port is not None else config.INGEST_PORT
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"rkb ingest listening on http://{host}:{port}")
    print(f"  token: {'set' if config.INGEST_TOKEN else 'NONE (loopback only)'}")
    print("  POST /ingest   {\"text\": \"...link...\"}  — records, does not download")
    print("  POST /prepare  — drain the queue")
    print("  GET  /status   ·  GET /post/<shortcode>")
    if host not in ("127.0.0.1", "localhost", "::1") and not config.INGEST_TOKEN:
        print("  WARNING: reachable off-machine with no token. Set RKB_INGEST_TOKEN.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return {"host": host, "port": port}
