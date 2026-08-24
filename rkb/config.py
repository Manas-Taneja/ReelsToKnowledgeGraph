"""Everything tunable in one place."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
