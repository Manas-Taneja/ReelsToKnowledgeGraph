"""Serve the review dashboard so decisions write straight to the database.

The file:// dashboard needed a clipboard round-trip, and every layer of that
(browser cache, localStorage, the copy step) had its own way of going stale.
Serving the page removes the whole class of problem: it is rendered fresh from
the database on every request, and each click is a write. Nothing to copy,
nothing to paste, nothing to reload.

Binds to 127.0.0.1 only.
"""
import json
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import config, dashboard, review

HOST, PORT = "127.0.0.1", 8765

JS = """
function note(){}          // serve mode saves on click, not on keystroke
async function decide(sc,action){
  const u=(document.querySelector('#u-'+sc)||{}).value||'';
  const n=(document.querySelector('#n-'+sc)||{}).value||'';
  if(action==='link'&&!u.trim()){alert('Paste the repo URL first.');return}
  const card=document.querySelector('.card[data-sc="'+sc+'"]');
  const v=card.querySelector('.verdict');
  v.textContent='saving…';
  try{
    const r=await fetch('/decide',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({shortcode:sc,action:action,url:u,note:n})});
    const j=await r.json();
    if(!r.ok){v.textContent='✗ '+(j.error||'failed');return}
    v.textContent=j.message;
    card.classList.toggle('done',action!=='reset');
    document.getElementById('tally').textContent=j.tally;
  }catch(e){ v.textContent='✗ '+e; }
}
"""


class Handler(BaseHTTPRequestHandler):
    revisit = False

    def log_message(self, *a):
        pass                                   # keep the terminal readable

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")   # never serve a stale page
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._send(200, dashboard.render(revisit=self.revisit, serve=True),
                              "text/html; charset=utf-8")
        if path.startswith("/media/"):
            target = (config.MEDIA_DIR / path[len("/media/"):]).resolve()
            if not str(target).startswith(str(config.MEDIA_DIR.resolve())):
                return self._send(403, {"error": "outside media dir"})
            if not target.is_file():
                return self._send(404, {"error": "not found"})
            return self._send(200, target.read_bytes(), "image/jpeg")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/decide":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(n) or b"{}")
            sc, action = d.get("shortcode"), d.get("action")
            if not sc or action not in review.ACTIONS:
                return self._send(400, {"error": f"bad action {action!r}"})
            entry = {"action": action}
            if d.get("url"):
                entry["url"] = d["url"]
            if d.get("note"):
                entry["note"] = d["note"]
            r = review.apply({sc: entry})
        except Exception as e:                          # never kill the server
            return self._send(500, {"error": str(e)})

        if r["dead"]:
            # Verification rejected it -- say so plainly instead of falling
            # through to a message about an unknown shortcode.
            return self._send(200, {
                "message": f"✗ that URL doesn't resolve — {r['dead'][0][1]}",
                "tally": dashboard.tally(self.revisit)})
        stored = r["urls"].get(sc)
        if stored and stored != d.get("url"):
            return self._send(200, {"message": f"✓ link saved, repaired to {stored}",
                                    "tally": dashboard.tally(self.revisit)})

        msg = ("✓ link saved" if r["linked"] else
               "✓ kept" if r["kept"] else
               "↻ back in the extraction queue" if r["recheck"] else
               "✓ archived" if r["archived"] else
               "↺ reset" if r["reset"] else
               "· already in that state" if r["unchanged"] else
               "✗ unknown shortcode")
        return self._send(200, {"message": msg,
                                "tally": dashboard.tally(self.revisit)})


def run(revisit=False, open_browser=True, port=PORT):
    Handler.revisit = revisit
    try:
        srv = ThreadingHTTPServer((HOST, port), Handler)
    except OSError as e:
        raise SystemExit(
            f"port {port} is already in use ({e}).\n"
            f"Something else is serving there — find it with:\n"
            f"    lsof -nP -iTCP:{port} -sTCP:LISTEN\n"
            f"Stop it, or pass a different port.") from None
    url = f"http://{HOST}:{port}/"
    print(f"review dashboard → {url}")
    # Say which database, out loud: a server left over from a test can silently
    # be writing somewhere else entirely.
    print(f"writing to  {config.DB_PATH}")
    print("every click saves straight to the database. Ctrl-C when you're done.")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        srv.server_close()
