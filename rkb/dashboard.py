"""A local review dashboard for posts that have no link.

A link is the payload, so a post that has one needs no human attention. A post
without one might be a missed URL on a frame, a deliberately gated link, or a
post whose whole value is a prompt -- and only a person can tell those apart.

This renders every such post with ALL of its frames at full size, because the
usual reason a link is missing is that it was on screen and extraction didn't
read it. Decisions are kept in the browser and copied out as JSON for
`rkb review` to apply; nothing here writes to the database directly.
"""
import hashlib
import html
import json
from pathlib import Path

from . import config, db, triage

OUT = config.ROOT / "dashboard.html"

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Reels review queue</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#faf9f7;--fg:#1a1a1a;--mut:#6b6b6b;--card:#fff;--line:#e3e0da;
      --accent:#b8442a;--ok:#2f6f4e;--warn:#8a6d1f}
@media(prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#e8e6e3;--mut:#9a9792;
      --card:#1e1e23;--line:#32323a;--accent:#e0724f;--ok:#5aa77c;--warn:#c9a227}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:9;background:var(--card);
       border-bottom:1px solid var(--line);padding:14px 20px;
       display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
h1{font-size:17px;margin:0;font-weight:650}
.sub{color:var(--mut);font-size:13px}
.spacer{flex:1}
button{font:inherit;padding:6px 12px;border:1px solid var(--line);border-radius:7px;
       background:var(--card);color:var(--fg);cursor:pointer}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
main{max-width:1080px;margin:0 auto;padding:22px 20px 120px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
      padding:18px;margin-bottom:22px}
.card.done{opacity:.45}
.flag{display:inline-block;font-size:11.5px;letter-spacing:.04em;text-transform:uppercase;
      color:var(--warn);border:1px solid var(--warn);border-radius:99px;padding:2px 9px}
h2{font-size:17px;margin:10px 0 4px;line-height:1.35}
.meta{color:var(--mut);font-size:13px;margin-bottom:12px}
.meta a{color:var(--accent)}
.frames{display:flex;gap:8px;overflow-x:auto;padding:4px 0 10px}
.frames img{height:190px;border-radius:7px;border:1px solid var(--line);cursor:zoom-in;
            flex:0 0 auto}
details{margin:8px 0;border-top:1px solid var(--line);padding-top:8px}
summary{cursor:pointer;color:var(--mut);font-size:13.5px}
pre{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);
    border-radius:8px;padding:12px;font-size:13px;overflow-x:auto;margin:8px 0}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:14px;
         border-top:1px solid var(--line);padding-top:14px}
input[type=url]{flex:1;min-width:260px;font:inherit;padding:7px 10px;border-radius:7px;
                border:1px solid var(--line);background:var(--bg);color:var(--fg)}
.verdict{font-size:13px;color:var(--ok);font-weight:600}
footer{position:fixed;bottom:0;left:0;right:0;background:var(--card);
       border-top:1px solid var(--line);padding:12px 20px;display:flex;gap:14px;
       align-items:center}
#zoom{position:fixed;inset:0;background:#000d;display:none;z-index:99;
      align-items:center;justify-content:center;cursor:zoom-out}
#zoom img{max-width:96vw;max-height:96vh}
code{background:var(--bg);padding:1px 5px;border-radius:4px;font-size:12.5px}
</style>
<header>
  <h1>Review queue</h1>
  <span class="sub">__COUNT__ posts with no link · __MODE__</span>
  <span class="spacer"></span>
  <span class="sub" id="tally">__TALLY__</span>
  __HEADBTN__
</header>
<main>__CARDS__</main>
<footer>__FOOT__</footer>
<div id="zoom" onclick="this.style.display='none'"><img></div>
<script>
__JS__
__FILEJS__
</script>
"""

CARD = """<div class="card" data-sc="__SC__">
  <span class="flag">__FLAG__</span>
  <h2>__SUMMARY__</h2>
  <div class="meta">__AUTHOR____COLLECTION__ · <a href="__URL__" target="_blank">open on Instagram ↗</a>
     · <code>__SC__</code></div>
  <div class="frames">__FRAMES__</div>
  __PROMPT__
  __CAPTION__
  __TRANSCRIPT__
  __OCR__
  <div class="actions">
    <input type="url" id="u-__SC__" placeholder="paste the repo / payload URL if you spot one">
    <button class="primary" onclick="decide('__SC__','link')">Save link</button>
  </div>
  <div class="actions" style="border-top:none;padding-top:6px">
    __KEEPBTN__
    <button onclick="decide('__SC__','keep')">Keep anyway</button>
    <button onclick="decide('__SC__','recheck')">Look again — I think there's a link</button>
    <button onclick="decide('__SC__','junk')">Archive as junk</button>
    <button onclick="decide('__SC__',null)">Reset</button>
    <span class="verdict"></span>
  </div>
  <div class="actions" style="border-top:none;padding-top:6px">
    <input type="text" id="n-__SC__" placeholder="why? (optional — tells me how to judge the other 49)"
           oninput="note('__SC__',this.value)" value="__NOTE__">
  </div>
</div>"""


def _esc(t):
    return html.escape(t or "", quote=True)


def _block(label, text, pre=True, open_=False):
    if not (text or "").strip():
        return ""
    body = f"<pre>{_esc(text)}</pre>" if pre else f"<p>{_esc(text)}</p>"
    o = " open" if open_ else ""
    return f"<details{o}><summary>{label}</summary>{body}</details>"


FILE_JS = """const KEY='rkb-review', BUILD='__BUILD__';
let state=JSON.parse(localStorage.getItem(KEY)||'{}');
// A rebuilt dashboard reflects the database, not what this browser remembers.
// If the build stamp changed, last session's decisions are already applied (or
// deliberately reset) -- starting from them would re-export stale choices and
// make every card open pre-decided.
(function reconcile(){
  if(localStorage.getItem(KEY+'-build')!==BUILD){
    state={}; localStorage.setItem(KEY,'{}'); localStorage.setItem(KEY+'-build',BUILD);
    return;
  }
  const here=new Set([...document.querySelectorAll('.card')].map(c=>c.dataset.sc));
  let dropped=0;
  for(const k of Object.keys(state)) if(!here.has(k)){delete state[k];dropped++}
  if(dropped) localStorage.setItem(KEY,JSON.stringify(state));
})();
function clearAll(){
  if(!confirm('Clear every decision on this page?'))return;
  state={};save();
}
function save(){localStorage.setItem(KEY,JSON.stringify(state));paint()}
function decide(sc,action){
  const prev=state[sc]||{}, n=(document.querySelector('#n-'+sc)||{}).value||prev.note;
  if(action==='link'){
    const u=document.querySelector('#u-'+sc).value.trim();
    if(!u){alert('Paste the repo URL first.');return}
    state[sc]={action:'link',url:u};
  } else if(action===null){ delete state[sc]; save(); return }
  else { state[sc]={action:action} }
  if(n) state[sc].note=n;
  save();
}
function note(sc,v){ if(state[sc]){ state[sc].note=v; localStorage.setItem(KEY,JSON.stringify(state)) } }
function paint(){
  if(typeof KEY==='undefined')return;
  let n=0;
  document.querySelectorAll('.card').forEach(c=>{
    const sc=c.dataset.sc, d=state[sc];
    c.classList.toggle('done',!!d);
    const v=c.querySelector('.verdict');
    const label={link:d&&d.action==='link'?'✓ link: '+d.url:'',
                 prompt:'✓ kept — the prompt is the payload',
                 keep:'✓ kept',
                 recheck:'↻ queued for another extraction pass',
                 junk:'✓ archived'};
    v.textContent = d ? (d.action==='link' ? label.link : label[d.action]||'') : '';
    if(d)n++;
  });
  document.getElementById('tally').textContent=n+' / '+
    document.querySelectorAll('.card').length+' decided';
}
function copyOut(){
  if(!Object.keys(state).length){alert('No decisions to copy — nothing is marked yet.');return}
  const payload=Object.assign({_build:BUILD},state);
  navigator.clipboard.writeText(JSON.stringify(payload,null,2))
    .then(()=>alert('Copied. Now run:  ./bin/rkb review'))
    .catch(()=>prompt('Copy this:',JSON.stringify(payload)));
}
document.addEventListener('click',e=>{
  if(e.target.tagName==='IMG'&&e.target.closest('.frames')){
    const z=document.getElementById('zoom');
    z.querySelector('img').src=e.target.src;z.style.display='flex';
  }
});
paint();"""

SERVE_HEAD = ('<span class="sub">every click saves straight to the database</span>')
SERVE_FOOT = ('<span class="sub">Decisions are written immediately — there is nothing '
              'to copy and nothing to reload. Close the tab and press Ctrl-C in the '
              'terminal when you are done.</span>')
FILE_HEAD = ('<button onclick="clearAll()">Clear all</button>'
             '<button class="primary" onclick="copyOut()">Copy decisions</button>')
FILE_FOOT = ('<span class="sub">Decisions are saved in this browser. Hit '
             '<b>Copy decisions</b>, then run <code>./bin/rkb review</code>. '
             'Prefer <code>./bin/rkb dashboard --serve</code> — it skips all of this.</span>')


def _collect(revisit):
    """revisit=True also re-opens posts you already decided, so a decision made
    under a worse set of options can be revised without losing anything."""
    groups = triage.triage()
    items = list(groups.get("review", []))
    if revisit:
        seen = {r["shortcode"] for r, _ in items}
        for bucket in ("keep", "archived"):
            for r, why in groups.get(bucket, []):
                # A post with a real link is settled; only re-open the link-less.
                if r["shortcode"] in seen or triage._payload_links(
                        triage._links(r["links"]), r["author_link"]):
                    continue
                state = r["reviewed"] or ("archived" if r["status"] == "archived" else "?")
                items.append((r, f"you marked this '{state}' — revise if you like"))
    return items


def tally(revisit=False):
    """Progress, phrased so it actually moves when you click.

    Counting decisions *among the posts still on the page* is always zero in
    normal mode -- deciding one is exactly what takes it off the page. So count
    what you have decided across the whole library against what is still queued.
    """
    left = len(_collect(revisit))
    con = db.init()
    decided = con.execute(
        "SELECT COUNT(*) FROM posts WHERE reviewed IS NOT NULL "
        "OR status = 'archived'").fetchone()[0]
    if not left:
        return f"{decided} decided · queue empty"
    return f"{decided} decided · {left} left"


def render(revisit=False, serve=False):
    """The page. In serve mode images come from /media/ and clicks POST."""
    from . import serve as _serve
    items = _collect(revisit)
    cards = []
    for r, why in items:
        frames = sorted(Path(r["media_dir"] or ".").glob("frames/*.jpg"))
        def _src(f):
            # served: an absolute /media/ URL. static file: a path relative to
            # the repo root, since dashboard.html is written there.
            if serve:
                return "/media/" + str(f.relative_to(config.MEDIA_DIR))
            return str(f.relative_to(config.ROOT))

        imgs = "".join(
            f'<img loading="lazy" src="{_esc(_src(f))}" alt="{f.name}">'
            for f in frames
        ) or '<span class="sub">no frames</span>'
        card = (CARD
                .replace("__SC__", _esc(r["shortcode"]))
                .replace("__FLAG__", _esc(why))
                .replace("__SUMMARY__", _esc(r["summary"] or "(not extracted)"))
                .replace("__AUTHOR__", f"@{_esc(r['author'])}" if r["author"] else "")
                .replace("__COLLECTION__", "")
                .replace("__URL__", _esc(f"https://www.instagram.com/p/{r['shortcode']}/"))
                .replace("__FRAMES__", imgs)
                .replace("__KEEPBTN__",
                         '<button onclick="decide(\'%s\',\'prompt\')">Prompt is the payload</button>'
                         % _esc(r["shortcode"]) if (r["prompt"] or "").strip() else "")
                .replace("__NOTE__", "")
                .replace("__PROMPT__", _block("Prompt captured", r["prompt"], open_=True))
                .replace("__CAPTION__", _block("Caption", r["caption"]))
                .replace("__TRANSCRIPT__", _block("Transcript", r["transcript"]))
                .replace("__OCR__", _block("Text on the slides/frames (OCR, verbatim)",
                                           r["ocr_text"], open_=True)))
        cards.append(card)

    # Stamp the build from what is actually on the page *and* its current db
    # state, so any change invalidates a browser's remembered decisions.
    stamp = hashlib.sha1(
        json.dumps([[r["shortcode"], r["status"], r["reviewed"], why]
                    for r, why in items], sort_keys=True).encode()
    ).hexdigest()[:12]
    page = (PAGE.replace("__FILEJS__", "" if serve else FILE_JS)
                .replace("__BUILD__", stamp)
                .replace("__JS__", _serve.JS if serve else "")
                .replace("__HEADBTN__", SERVE_HEAD if serve else FILE_HEAD)
                .replace("__FOOT__", SERVE_FOOT if serve else FILE_FOOT)
                .replace("__COUNT__", str(len(items)))
                .replace("__TALLY__", tally(revisit) if serve else "")
                .replace("__MODE__", "including ones you already decided — "
                         "click to revise" if revisit
                         else "a link clears a post automatically")
                .replace("__CARDS__", "\n".join(cards) or
                         "<p>Nothing to review — every extracted post has a link.</p>"))
    return page


def build(out=None, revisit=False):
    out = Path(out or OUT)
    items = _collect(revisit)
    out.write_text(render(revisit=revisit, serve=False), encoding="utf-8")
    return {"path": str(out), "posts": len(items)}
