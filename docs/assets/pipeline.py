"""Generate the pipeline diagram in docs/assets/, light and dark.

Run me after changing the pipeline, then export:

    python3 docs/assets/pipeline.py
    # then, per the diagram-design skill, HTML -> SVG (and PNG if you have playwright)

Drawn in the diagram-design skill's system (cathrynlavery/diagram-design):

viewBox 1280x920 (doc-wide 1280x720 + extra bands + 60px legend strip).
Every coordinate, size and gap divisible by 4.
"""
import pathlib

CX = 640
VW, VH = 1280, 920

LIGHT = dict(
    key="light", paper="#f5f5f5", paper2="#ececec", ink="#2d3142", muted="#4f5d75",
    soft="#7a8399", rule="rgba(45,49,66,0.12)", accent="#eb6c36",
    zone_fill="rgba(45,49,66,0.02)", zone_stroke="rgba(45,49,66,0.10)",
    zone_label="rgba(45,49,66,0.40)",
    backend_fill="#ffffff", store_fill="rgba(45,49,66,0.05)",
    input_fill="rgba(79,93,117,0.10)",
    accent_zone_fill="rgba(235,108,54,0.05)", accent_zone_stroke="rgba(235,108,54,0.50)",
    tag_stroke="rgba(45,49,66,0.40)", tag_text="rgba(45,49,66,0.75)",
)
DARK = dict(
    key="dark", paper="#2d3142", paper2="#393e53", ink="#f5f5f5", muted="#bfc0c0",
    soft="#8e98ac", rule="rgba(245,245,245,0.12)", accent="#f08a59",
    zone_fill="rgba(245,245,245,0.03)", zone_stroke="rgba(245,245,245,0.10)",
    zone_label="rgba(245,245,245,0.40)",
    backend_fill="#393e53", store_fill="rgba(245,245,245,0.05)",
    input_fill="rgba(191,192,192,0.10)",
    accent_zone_fill="rgba(240,138,89,0.06)", accent_zone_stroke="rgba(240,138,89,0.50)",
    tag_stroke="rgba(245,245,245,0.40)", tag_text="rgba(245,245,245,0.75)",
)

SANS = "'Geist', system-ui, sans-serif"
MONO = "'Geist Mono', ui-monospace, monospace"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def node(t, x, y, w, h, tag, name, sub, kind="backend"):
    """Mask + box + type tag + name + mono sublabel."""
    fill = {"backend": t["backend_fill"], "store": t["store_fill"],
            "input": t["input_fill"]}[kind]
    stroke = {"backend": t["ink"], "store": t["muted"], "input": t["soft"]}[kind]
    cx = x + w // 2
    tw = max(28, (len(tag) * 6 + 12 + 3) // 4 * 4)
    ty = y + (10 if h >= 72 else 8)
    ny = y + (44 if h >= 72 else 38)
    sy = y + (60 if h >= 72 else 54)
    return f"""
    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{t['paper']}"/>
    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1"/>
    <rect x="{x+12}" y="{ty}" width="{tw}" height="12" rx="2" fill="transparent" stroke="{t['tag_stroke']}" stroke-width="0.8"/>
    <text x="{x+12+tw//2}" y="{ty+9}" fill="{t['tag_text']}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.08em">{esc(tag)}</text>
    <text x="{cx}" y="{ny}" fill="{t['ink']}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{esc(name)}</text>
    <text x="{cx}" y="{sy}" fill="{t['muted']}" font-size="9" font-family="{MONO}" text-anchor="middle">{esc(sub)}</text>"""


def zone(t, x, y, w, h, label, accent=False):
    fill = t["accent_zone_fill"] if accent else t["zone_fill"]
    stroke = t["accent_zone_stroke"] if accent else t["zone_stroke"]
    dash = ' stroke-dasharray="6,4"' if accent else ""
    col = t["accent"] if accent else t["zone_label"]
    mw = (len(label) * 7 + 24) // 4 * 4
    return f"""
    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="{1 if accent else 0.8}"{dash}/>
    <rect x="{x+16}" y="{y+4}" width="{mw}" height="12" rx="2" fill="{t['paper']}"/>
    <text x="{x+16+mw//2}" y="{y+13}" fill="{col}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.14em">{esc(label)}</text>"""


def vline(t, x, y1, y2, mid=""):
    out = f'\n    <line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{t["muted"]}" stroke-width="1.2" marker-end="url(#{t["key"]}-arrow)"/>'
    if mid:
        mw = (len(mid) * 6 + 16) // 4 * 4
        my = (y1 + y2) // 2 - 6
        out += (f'\n    <rect x="{x+10}" y="{my}" width="{mw}" height="12" rx="2" fill="{t["paper"]}"/>'
                f'\n    <text x="{x+10+mw//2}" y="{my+9}" fill="{t["soft"]}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{esc(mid)}</text>')
    return out


def hline(t, x1, x2, y):
    return f'\n    <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{t["muted"]}" stroke-width="1.2" marker-end="url(#{t["key"]}-arrow)"/>'


def elbow(t, x1, y1, lane, x2, y2):
    """Down from (x1,y1) to `lane`, across to x2, then down into (x2,y2)."""
    if x2 < x1:
        d = (f"M {x1},{y1} V {lane-8} Q {x1},{lane} {x1-8},{lane} "
             f"H {x2+8} Q {x2},{lane} {x2},{lane+8} V {y2}")
    else:
        d = (f"M {x1},{y1} V {lane-8} Q {x1},{lane} {x1+8},{lane} "
             f"H {x2-8} Q {x2},{lane} {x2},{lane+8} V {y2}")
    return f'\n    <path d="{d}" fill="none" stroke="{t["muted"]}" stroke-width="1.2" marker-end="url(#{t["key"]}-arrow)"/>'


def build(t):
    s = []
    s.append(f'<rect width="100%" height="100%" fill="{t["paper"]}"/>')

    # --- zones first (z-order: bg -> zones -> arrows -> nodes) -------------
    s.append(zone(t, 40, 144, 1200, 136,
                  "RUNS ENTIRELY ON YOUR MACHINE · NO API · NO QUOTA", accent=True))
    s.append(zone(t, 280, 408, 720, 136, "YOU + AN AGENT · NO LLM CALL IN RKB/"))
    s.append(zone(t, 40, 712, 1200, 136, "OUTPUTS"))

    # --- arrows ------------------------------------------------------------
    s.append(vline(t, CX, 112, 144, "RKB IMPORT"))
    s.append(vline(t, CX, 280, 312))
    s.append(vline(t, CX, 376, 408))
    s.append(vline(t, CX, 544, 576))
    s.append(hline(t, 620, 660, 484))
    s.append(elbow(t, 584, 640, 652, 208, 752))
    s.append(elbow(t, 640, 640, 668, 496, 752))
    s.append(elbow(t, 696, 640, 684, 784, 752))
    s.append(hline(t, 916, 940, 788))

    # --- nodes -------------------------------------------------------------
    s.append(node(t, 528, 48, 224, 64, "EXPORT", "Meta export", "saved_posts.json", "input"))
    for x, tag, name, sub in (
            (76,  "FETCH",  "yt-dlp · gallery-dl", "reel · carousel"),
            (364, "FRAMES", "ffmpeg",                  "8 keyframes / post"),
            (652, "AUDIO",  "mlx-whisper",             "24.6× realtime"),
            (940, "OCR",    "Apple Vision",            "on-device")):
        s.append(node(t, x, 184, 264, 72, tag, name, sub))
    s.append(node(t, 528, 312, 224, 64, "HANDOFF", "context.md", "one folder / post"))
    s.append(node(t, 312, 448, 308, 72, "AGENT", "Claude Code", "reads context.md"))
    s.append(node(t, 660, 448, 308, 72, "WRITE", "rkb record", "every URL verified"))
    s.append(node(t, 528, 576, 224, 64, "STORE", "SQLite + FTS5", "extractions", "store"))
    for x, tag, name, sub in (
            (76,  "CLI",    "rkb search", "full-text, terminal"),
            (364, "REVIEW", "rkb triage", "only posts with no link"),
            (652, "VAULT",  "rkb vault",  "Obsidian markdown"),
            (940, "GRAPH",  "rkb graph",  "52 concepts · 4 clusters")):
        s.append(node(t, x, 752, 264, 72, tag, name, sub))

    # --- legend strip ------------------------------------------------------
    s.append(f'\n    <line x1="40" y1="872" x2="{VW-40}" y2="872" stroke="{t["zone_stroke"]}" stroke-width="0.8"/>')
    s.append(f'\n    <text x="40" y="892" fill="{t["muted"]}" font-size="8" font-family="{MONO}" letter-spacing="0.14em">LEGEND</text>')
    items = [(160, t["input_fill"], t["soft"], "", "SOURCE"),
             (376, t["backend_fill"], t["ink"], "", "STEP"),
             (592, t["store_fill"], t["muted"], "", "STORE"),
             (808, t["accent_zone_fill"], t["accent_zone_stroke"], ' stroke-dasharray="4,3"', "YOUR MACHINE, NO API")]
    for x, fill, stroke, dash, label in items:
        s.append(f'\n    <rect x="{x}" y="{880}" width="16" height="12" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="0.8"{dash}/>')
        s.append(f'\n    <text x="{x+24}" y="{892}" fill="{t["muted"]}" font-size="8" font-family="{MONO}" letter-spacing="0.06em">{esc(label)}</text>')
    return "".join(s)


TITLE = "From a saved reel to a linked knowledge base"
DESC = ("Pipeline diagram. A Meta export of saved Instagram posts enters rkb import. "
        "A dashed accent boundary marks the stage that runs entirely on your machine with no API "
        "and no quota: yt-dlp or gallery-dl fetches the media, ffmpeg samples eight keyframes, "
        "mlx-whisper transcribes the audio and Apple Vision reads the on-screen text. "
        "That stage emits one context.md folder per post. A second boundary marks the extraction "
        "stage, where Claude Code reads context.md and rkb record verifies every URL before storing "
        "it. Results land in SQLite with a full-text index, which feeds three outputs: rkb search, "
        "rkb triage for the review queue, and rkb vault for Obsidian, which in turn feeds rkb graph.")


def page(t):
    k = t["key"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>reels-kb · pipeline</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&amp;family=Geist:wght@400;500;600&amp;family=Geist+Mono:wght@400;500;600&amp;display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --color-paper: {t['paper']};
    --color-ink:   {t['ink']};
    --color-muted: {t['muted']};
    --font-sans:   {SANS};
    --font-serif:  'Instrument Serif', serif;
    --font-mono:   {MONO};
  }}
  body {{
    font-family: var(--font-sans);
    background: var(--color-paper);
    color: var(--color-ink);
    min-height: 100vh;
    display: flex; align-items: center; justify-content: center;
    padding: 3rem 2rem;
  }}
  .frame {{ max-width: 1280px; width: 100%; }}
  .eyebrow {{
    font-family: var(--font-mono); font-size: 0.66rem; font-weight: 500;
    letter-spacing: 0.18em; text-transform: uppercase;
    color: var(--color-muted); margin-bottom: 0.5rem;
  }}
  h1 {{
    font-family: var(--font-serif);
    font-size: clamp(1.5rem, 2.4vw + 0.75rem, 2rem);
    font-weight: 400; letter-spacing: -0.02em; line-height: 1.15;
    color: var(--color-ink); margin-bottom: 1.5rem;
  }}
  svg {{ width: 100%; display: block; }}
</style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">reels-kb · architecture</p>
    <h1>{TITLE}</h1>
    <svg viewBox="0 0 {VW} {VH}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{k}-title {k}-desc">
      <title id="{k}-title">{TITLE}</title>
      <desc id="{k}-desc">{DESC}</desc>
      <defs>
        <marker id="{k}-arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{t['muted']}"/></marker>
        <marker id="{k}-arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{t['accent']}"/></marker>
      </defs>
    {build(t)}
    </svg>
  </div>
</body>
</html>
"""


out = pathlib.Path("/Users/mnz/reels-kb/docs/assets")
for t in (LIGHT, DARK):
    name = "pipeline.html" if t["key"] == "light" else "pipeline-dark.html"
    (out / name).write_text(page(t))
    print("wrote", out / name)
