"""Where a post came from, and what that implies downstream.

One row in `posts` is one saved thing. Instagram was the only source at first,
so the platform was implicit -- baked into the URL regex in the importer, the
"Open on Instagram" line in the vault, the folder name `Reels/`. A second
source makes every one of those a lookup rather than a constant.

The table below is the only place a platform is described. Everything else
(acquire, importer, vault) asks it rather than testing the URL again.
"""
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Platform:
    key: str
    label: str                 # human name, for the vault's Source line
    folder: str                # vault subfolder its notes live in
    url_re: "re.Pattern"       # must expose groups: id (and optionally user/kind)
    kinds: dict = field(default_factory=dict)   # url word -> our `kind` value
    default_kind: str = "post"
    # X serves almost nothing to a logged-out client, so its cookie jar is not
    # optional the way Instagram's is. Recorded here rather than guessed from a
    # download failure, so the error can say so before the first attempt.
    needs_cookies: bool = False

    def canonical(self, ident, kind=None, user=None):
        raise NotImplementedError


class _Instagram(Platform):
    def canonical(self, ident, kind=None, user=None):
        word = "reel" if kind == "reel" else "p"
        return f"https://www.instagram.com/{word}/{ident}/"


class _Twitter(Platform):
    def canonical(self, ident, kind=None, user=None):
        # `/i/web/status/` resolves without knowing the handle, which the
        # bookmark feed and a bare status link do not always carry. Both yt-dlp
        # and gallery-dl accept it.
        if user and user.lower() not in ("i", "web", "status"):
            return f"https://x.com/{user}/status/{ident}"
        return f"https://x.com/i/web/status/{ident}"


INSTAGRAM = _Instagram(
    key="instagram",
    label="Instagram",
    folder="Reels",
    url_re=re.compile(
        r"https?://(?:www\.)?instagram\.com/"
        r"(?:(?P<user>[A-Za-z0-9_.]+)/)??"
        r"(?P<kind>reel|reels|p|tv)/(?P<id>[A-Za-z0-9_-]{5,})"
    ),
    kinds={"reel": "reel", "reels": "reel", "p": "post", "tv": "post"},
    default_kind="post",
)

TWITTER = _Twitter(
    key="twitter",
    label="X",
    folder="Tweets",
    # The mirror hosts (fx/vx/dd) are what a share sheet actually produces, so
    # accept them and normalise -- otherwise a pasted link is silently ignored.
    url_re=re.compile(
        r"https?://(?:www\.|mobile\.)?"
        r"(?:twitter\.com|x\.com|fxtwitter\.com|vxtwitter\.com|fixupx\.com|twittpr\.com|nitter\.[^/]+)/"
        # Two shapes in the wild: /<handle>/status/<id>, and the handle-less
        # /i/web/status/<id> that a copied link or the bookmark feed can give.
        r"(?:i/web/status|(?P<user>[A-Za-z0-9_]+)/status(?:es)?)/(?P<id>\d{5,25})"
    ),
    kinds={},
    default_kind="tweet",
    needs_cookies=True,
)

ALL = {p.key: p for p in (INSTAGRAM, TWITTER)}
DEFAULT = INSTAGRAM.key

# The X bookmark feed, which gallery-dl reads as a normal extractor. This is
# the direct analogue of the Meta export -- except it is live, so there is no
# export to request and wait for.
BOOKMARKS_URL = "https://x.com/i/bookmarks"


def get(key):
    return ALL.get((key or DEFAULT).strip().lower(), INSTAGRAM)


def detect(url):
    """(platform, ident, kind, user) for a URL we recognise, else None."""
    for p in ALL.values():
        m = p.url_re.search(url or "")
        if m:
            g = m.groupdict()
            kind = p.kinds.get((g.get("kind") or "").lower(), p.default_kind)
            return p, g["id"], kind, g.get("user")
    return None


def find_all(text):
    """Every recognised post URL in a blob of text, de-duplicated, in order."""
    seen, out = set(), []
    for p in ALL.values():
        for m in p.url_re.finditer(text or ""):
            g = m.groupdict()
            if g["id"] in seen:
                continue
            seen.add(g["id"])
            out.append((p, g["id"],
                        p.kinds.get((g.get("kind") or "").lower(), p.default_kind),
                        g.get("user")))
    return out


def folders():
    return sorted({p.folder for p in ALL.values()})
