"""Everything tunable in one place."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path=ROOT / ".env"):
    """Read KEY=value lines from .env, without adding a dependency.

    Secrets that would otherwise live in your shell profile -- the Telegram bot
    token, a cookies path -- belong in a file the repo already ignores. A real
    environment variable always wins, so `RKB_X=1 ./bin/rkb ...` still overrides
    for one run.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if val[:1] == val[-1:] and val[:1] in ("'", '"'):
            val = val[1:-1]
        os.environ.setdefault(key, val)


_load_env()
DATA = ROOT / "data"
EXPORT_DIR = DATA / "export"
MEDIA_DIR = DATA / "media"
DB_PATH = Path(os.environ.get("RKB_DB", DATA / "reels.db"))

# Cookies are OPT-IN. Public posts download fine anonymously, which keeps your
# account entirely out of the loop -- bulk-fetching with your own cookies is the
# pattern that gets accounts flagged. Set RKB_BROWSER=safari|chrome|firefox only
# if you need private/restricted posts. (Safari also needs Full Disk Access for
# your terminal, since its cookie jar is TCC-protected.)
BROWSER = os.environ.get("RKB_BROWSER", "").strip()

# Alternative to RKB_BROWSER: a Netscape-format cookies.txt exported with a
# browser extension. More reliable than RKB_BROWSER on macOS, since Safari's
# cookie jar needs Full Disk Access granted to your terminal.
COOKIES_FILE = os.environ.get("RKB_COOKIES", "").strip()

# X is not Instagram: it serves a logged-out client almost nothing, so cookies
# there are required rather than opt-in. These override the two above for X
# only, which is what you want when the two accounts live in different
# browsers. Unset, they fall back to RKB_BROWSER / RKB_COOKIES.
X_BROWSER = os.environ.get("RKB_X_BROWSER", "").strip()
X_COOKIES_FILE = os.environ.get("RKB_X_COOKIES", "").strip()

# How many bookmarks `rkb bookmarks` walks back through in one sweep. The feed
# is newest-first, so a small number is the usual "what did I save this week".
X_BOOKMARK_LIMIT = int(os.environ.get("RKB_X_BOOKMARK_LIMIT", "100"))

# Whisper model. large-v3-turbo is the sweet spot on Apple Silicon; use
# RKB_WHISPER=mlx-community/whisper-small-mlx if you want it even faster.
WHISPER_MODEL = os.environ.get("RKB_WHISPER", "mlx-community/whisper-large-v3-turbo")

# Frame sampling. Tech reels put the link/tool on a title card in the opening
# beat, so the head is sampled densely and the tail sparsely.
HEAD_SECONDS = 3.0     # length of the "hook" window
HEAD_FPS = 2.0         # 1 frame every 0.5s inside it
TAIL_FPS = 0.5         # 1 frame every 2s after it
MAX_FRAMES = 8         # cap sent to vision per post

# OCR has none of vision's token cost -- it runs locally at ~0.13s/image -- so
# it gets its own, much denser sampling. Many "reels" are slideshows: eight
# frames of a 52-second deck reads a third of the screens. mpdecimate collapses
# each held screen to one frame, so the real frame count lands far below the cap.
OCR_FPS = float(os.environ.get("RKB_OCR_FPS", "2"))
OCR_MAX_FRAMES = int(os.environ.get("RKB_OCR_MAX_FRAMES", "80"))
FRAME_WIDTH = 768      # plenty to read on-screen text; keeps tokens down
# Width of each image in a reel note's contact sheet. Wide enough to tell the
# slides apart at a glance; click one to read it full size.
GALLERY_WIDTH = int(os.environ.get("RKB_GALLERY_WIDTH", "300"))

# Reviewing happens on the HTML dashboard (`rkb dashboard --serve`). The vault
# can host the same queue as editable note properties + a Bases view, but that
# means two places a decision can be made, so it is off unless you ask for it:
#   RKB_VAULT_REVIEW=1 ./bin/rkb vault --rebuild-bases
VAULT_REVIEW = os.environ.get("RKB_VAULT_REVIEW", "").strip() not in ("", "0")

# A hub note (Tools/, Topics/, Authors/) only earns a place in the graph if it
# connects at least this many posts. At 1 you get a node per one-off tool -- 89%
# of them, in practice -- and the graph becomes a dandelion of dead ends instead
# of a map of what your library actually has in common. Singletons still appear
# on the post itself, as plain text.
HUB_MIN = int(os.environ.get("RKB_HUB_MIN", "2"))

# Two hubs may be linked when this many posts use both. The reel notes carry the
# raw co-occurrence, but a graph of them is a document graph; linking the hubs
# directly is what turns it into a map of ideas.
LINK_MIN = int(os.environ.get("RKB_LINK_MIN", "2"))

# ...and each hub keeps only its strongest LINK_TOPK associations, ranked by
# Jaccard. A flat threshold lets popular nodes hoard edges -- one node here
# reached degree 29, which draws as a wheel with everything else on the rim.
LINK_TOPK = int(os.environ.get("RKB_LINK_TOPK", "4"))

# A hub on more than this fraction of the library is a stopword: it co-occurs
# with everything, so it separates nothing. Kept as a note, dropped from the
# graph. (`open-source`, on 62% of this library, is the canonical example.)
STOPWORD_FRAC = float(os.environ.get("RKB_STOPWORD_FRAC", "0.5"))

# Be a good citizen: these are your own cookies, so keep volume low.
SLEEP_BETWEEN = float(os.environ.get("RKB_SLEEP", "4"))

# How many posts one `/prepare` (or the button) drains by default. Matches the
# `rkb prepare -n` default, so the chat and the CLI behave the same.
BATCH_LIMIT = int(os.environ.get("RKB_BATCH_LIMIT", "25"))

# The Telegram front door (`rkb telegram`). The token comes from @BotFather.
# ALLOW is a list of chat ids permitted to use the bot -- unset refuses
# everything, because anyone who finds the bot's username can message it and
# ingesting starts downloads on this machine.
TELEGRAM_TOKEN = os.environ.get("RKB_TELEGRAM_TOKEN", "").strip()
TELEGRAM_ALLOW = os.environ.get("RKB_TELEGRAM_ALLOW", "").strip()

# Where `rkb ingest --serve` listens. Loopback by default: this endpoint starts
# downloads on your machine, so it should not be reachable from the network
# without you deciding that explicitly.
INGEST_HOST = os.environ.get("RKB_INGEST_HOST", "127.0.0.1")
INGEST_PORT = int(os.environ.get("RKB_INGEST_PORT", "8787"))
# Shared secret the plugin sends as X-RKB-Token. Empty disables the check,
# which is only safe while the host stays on loopback.
INGEST_TOKEN = os.environ.get("RKB_INGEST_TOKEN", "").strip()
