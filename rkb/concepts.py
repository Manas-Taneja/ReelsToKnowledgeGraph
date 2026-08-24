"""The concept graph: which hubs belong together, and how strongly.

Shared by `rkb vault` (which writes the Related links into hub notes) and
`rkb graph` (which colours the result), so both always describe the same graph.

Three things make the difference between a readable map and a hairball:

* **Association, not frequency.** Raw co-occurrence just re-ranks the common
  tags: `automation` co-occurs with everything because it is on a third of the
  library. Jaccard asks what fraction of the union the overlap accounts for, so
  a pair that almost always appears together outranks a pair that merely both
  appear a lot.
* **A budget per node.** Keeping every pair above a threshold lets popular nodes
  hoard edges -- one node here had 29. Keeping each node's strongest few caps
  that without silencing the small nodes, the way a k-nearest-neighbour graph
  does.
* **Dropping the stopwords.** A tag on 62% of the library separates nothing. It
  is the `the` of this vocabulary: it makes every node look related to every
  other one, which is the same as saying nothing.
"""
import collections
import itertools
import json
import re

from . import config

TOOLS, TOPICS = "Tools", "Topics"


def _jlist(v):
    try:
        return [x for x in json.loads(v or "[]") if isinstance(x, str) and x.strip()]
    except (json.JSONDecodeError, TypeError):
        return []


def norm(s):
    """`Claude Code`, `claude-code` and `claudecode` are one concept."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def build(rows):
    """Everything both callers need to agree on."""
    n_posts = len(rows) or 1

    # --- nodes ------------------------------------------------------------
    tool_df, topic_df = collections.Counter(), collections.Counter()
    for r in rows:
        for x in _jlist(r["tools"]):
            tool_df[x.strip()] += 1
        for x in _jlist(r["tags"]):
            topic_df[x.strip().lower()] += 1

    tools = {k: v for k, v in tool_df.items() if v >= config.HUB_MIN}
    topics = {k: v for k, v in topic_df.items() if v >= config.HUB_MIN}

    # A concept that is both a tool and a tag is one concept. Keep the tool --
    # it is the thing itself rather than a word about it -- and point the tag
    # at it, so the graph has one node where it should have one node.
    tool_by_norm = {norm(k): k for k in tools}
    merge = {k: tool_by_norm[norm(k)] for k in topics if norm(k) in tool_by_norm}
    for k in merge:
        topics.pop(k, None)

    display = {(TOOLS, k.lower()): k for k in tools}
    display.update({(TOPICS, k): k for k in topics})
    nodes = set(display)

    def key(folder, raw):
        raw = raw.strip()
        if folder == TOPICS:
            low = raw.lower()
            if low in merge:
                return (TOOLS, merge[low].lower())
            return (TOPICS, low)
        return (TOOLS, raw.lower())

    # --- how often each node appears, after the merge ---------------------
    df = collections.Counter()
    per_post = []
    for r in rows:
        s = set()
        for x in _jlist(r["tools"]):
            k = key(TOOLS, x)
            if k in nodes:
                s.add(k)
        for x in _jlist(r["tags"]):
            k = key(TOPICS, x)
            if k in nodes:
                s.add(k)
        per_post.append(s)
        for k in s:
            df[k] += 1

    stopwords = {k for k in nodes if df[k] / n_posts > config.STOPWORD_FRAC}

    # --- edges ------------------------------------------------------------
    co = collections.Counter()
    for s in per_post:
        for a, b in itertools.combinations(sorted(s - stopwords), 2):
            co[(a, b)] += 1

    pairs = {}
    ranked = collections.defaultdict(list)
    for (a, b), c in co.items():
        jaccard = c / (df[a] + df[b] - c)
        pairs[(a, b)] = (jaccard, c)
        if c >= config.LINK_MIN:
            ranked[a].append((jaccard, c, b))
            ranked[b].append((jaccard, c, a))

    edges = {}
    for a, lst in ranked.items():
        # sort by strength, then by shared posts, then by name -- fully
        # deterministic so the same library always draws the same map
        lst.sort(key=lambda t: (-t[0], -t[1], t[2]))
        for jaccard, c, b in lst[:config.LINK_TOPK]:
            edges[tuple(sorted([a, b]))] = (jaccard, c)

    adj = collections.defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)

    # Rescue the abandoned. A node can clear the bar to exist (HUB_MIN posts)
    # and still miss the bar to connect (LINK_MIN shared posts), which leaves it
    # invisible: present in the vault, absent from the map. Give each one its
    # single strongest association even at one shared post. The cost is at most
    # one edge per node, and what it recovers -- python/uv, privacy/homelab,
    # productivity/project-management -- is exactly the sort of pair the
    # threshold was never aimed at. It exists to thin dense nodes, not to
    # silence sparse ones.
    rescued = {}
    for n in sorted(nodes - stopwords):
        if adj[n]:
            continue
        cands = []
        for (a, b), (jaccard, c) in pairs.items():
            if n not in (a, b):
                continue
            other = b if a == n else a
            # Ties are common down here -- four concepts on two posts each,
            # sharing one, are indistinguishable by association alone. Break
            # towards the better-connected partner: that pulls the node into an
            # existing cluster, where rescuing it onto another loose node would
            # just make a two-node island belonging nowhere. Then prefer the
            # more specific partner, then the name, so it is never arbitrary.
            cands.append((-jaccard, -c, -len(adj[other]), df[other],
                          display[other], other, jaccard, c))
        if not cands:
            continue                       # shares no post with anything at all
        *_, other, jaccard, c = min(cands)
        edges[tuple(sorted([n, other]))] = (jaccard, c)
        adj[n].add(other)
        adj[other].add(n)
        rescued[n] = other

    # Same argument, one level up: a pair that found only each other is an
    # island, and an island floating off the edge of the map is as unreadable as
    # a loose dot. `sarvam`/`voice-agents` shared a post with `debugging` and
    # with `n8n`, but at one post each those pairs were pruned -- and neither
    # node was rescued above, because each already had the other. So attach
    # every stranded component to the mainland by its single strongest link.
    def _components():
        seen, out = set(), []
        for n in sorted(nodes - stopwords):
            if n in seen:
                continue
            comp, stack = set(), [n]
            while stack:
                x = stack.pop()
                if x in comp:
                    continue
                comp.add(x)
                stack += sorted(adj[x])
            seen |= comp
            out.append(comp)
        return sorted(out, key=lambda c: (-len(c), sorted(c)[0]))

    joined = []
    comps = _components()
    while len(comps) > 1:
        main = comps[0]
        best = None
        for comp in comps[1:]:
            for (a, b), (jaccard, c) in pairs.items():
                inside = (a in comp) != (b in comp)
                if not inside or (a not in main and b not in main):
                    continue
                cand = (-jaccard, -c, display[a], display[b], (a, b), jaccard, c)
                if best is None or cand < best:
                    best = cand
        if best is None:
            break                      # genuinely shares nothing with the rest
        *_, (a, b), jaccard, c = best
        edges[(a, b)] = (jaccard, c)
        adj[a].add(b)
        adj[b].add(a)
        joined.append((a, b))
        comps = _components()

    related = collections.defaultdict(list)
    for (a, b), (jaccard, c) in edges.items():
        related[a].append((jaccard, c, b))
        related[b].append((jaccard, c, a))
    for v in related.values():
        v.sort(key=lambda t: (-t[0], -t[1], t[2]))

    return {"nodes": nodes, "display": display, "df": df, "merge": merge,
            "stopwords": stopwords, "edges": edges, "adj": adj,
            "related": related, "posts": n_posts, "rescued": rescued,
            "joined": joined,
            "tools": set(tools), "topics": set(topics)}


def communities(g):
    """Label propagation over the concept graph.

    Deterministic: nodes are visited in name order and ties go to the lowest
    label, so the same vault always produces the same grouping and therefore
    the same colours from one run to the next.
    """
    adj = g["adj"]
    order = sorted(adj)
    label = {n: i for i, n in enumerate(order)}
    for _ in range(50):
        moved = False
        for n in order:
            counts = collections.Counter(label[m] for m in adj[n])
            if not counts:
                continue
            best = min(sorted(counts, key=lambda k: (-counts[k], k))[:1])
            if label[n] != best:
                label[n] = best
                moved = True
        if not moved:
            break
    out = collections.defaultdict(list)
    for n, l in label.items():
        out[l].append(n)
    # biggest first, then alphabetically -- a stable order to colour against
    return sorted(out.values(), key=lambda m: (-len(m), sorted(m)[0]))
