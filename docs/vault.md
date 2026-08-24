# The Obsidian vault

What `rkb vault` and `rkb graph` produce, and why the graph is thinned the
way it is.

[← back to the README](../README.md)

`rkb vault` renders the database into plain markdown — no plugins required.

```
vault/
  Index.md          counts, most-referenced tools, every next step
  Repos.md          every GitHub repo in the library, one row each
  Prompts.md        the posts whose payload is the text on screen
  Library.base      every post as a filterable table / gallery (Obsidian 1.9+)
  Reels/            one note per post: thumbnail, summary, prompt, links, transcript
  Tools/            one note per tool — backlinks every post that mentions it
  Topics/           one note per tag
  Authors/          one note per creator
  attachments/      every image, hard-linked from data/media
```

## The two flat tables

`Repos.md` and `Prompts.md` answer the two questions a reel library actually
gets asked: *what was that repo called?* and *where's that checklist I saved?*

**`Repos.md`** is every GitHub repository the library points at, one row per
repo. A URL that pointed *into* a repo — `/stargazers`, `/issues`,
`/network/dependents` — is normalised to the repo itself, which is what turns 71
links into 64 repos and collapses `supabase/supabase`'s three separate
appearances into one row that names all three posts. The **Tool** column is the
canonical name the extraction recorded, matched to the repo by name, then by the
repo name without its platform suffix (`gitroomhq/postiz-app` → Postiz,
`anyproto/anytype-ts` → Anytype), then by the owner. Two of the 71 stay
unmatched and should: `bitwarden/server` is the upstream of the Vaultwarden the
post was about, and `emilkowalski/skills` is nobody's product.

**`Prompts.md`** is the posts you kept for the words on the slides rather than
for a link. There is no stored flag for this, and adding one would be worse than
deriving it: `extractions.prompt` is null by contract (the extraction rules
forbid composing a prompt, because `ocr_text` already holds the verbatim text),
and the dashboard's *"prompt is the payload"* button writes the same
`reviewed='kept'` as a plain keep. So the set is **kept, and carrying no payload
link** — which is exactly the posts whose whole value is the text. It is a
slightly wider net than the word *prompt* suggests: checklists, playbooks and
one comment-gated post ride along with the actual prompts, because you kept
those too and for the same reason.

Both are regenerated on every `rkb vault`, and both keep anything you write
below the `rkb:end` marker.

The hub notes are the answer to *"there's no relation among each reel"*: open
`Tools/Claude Code.md` and you get every post that touched it, and the graph
view draws clusters you never filed by hand.

**A hub note is only created when it connects two or more posts** (`RKB_HUB_MIN`,
default 2). At 1 you get a node per one-off tool — 89% of them here — and the
graph turns into a dandelion of dead ends: 341 nodes for 48 posts, of which 211
had exactly one edge. Thresholded, that first cut drops to 107 nodes. A one-off
tool still appears on the post, as plain text rather than a link to a page that
exists solely to hold that one link.

`RKB_HUB_MIN=1 ./bin/rkb vault` restores a note for every name.

**Hubs link to each other, not just to posts.** Without this the vault is a
*document* graph: every edge runs post → tool or post → topic, and nothing joins
a tool to a topic, so hiding the posts leaves a field of unconnected dots. The
rules that turn raw co-occurrence into a map you can read all live in
`rkb/concepts.py`:

| | why |
|---|---|
| ranked by **Jaccard**, not raw count | raw co-occurrence just re-ranks the common tags; a pair that almost always appears together should outrank a pair that merely both appear a lot |
| each hub keeps its **strongest `RKB_LINK_TOPK`** (4) | a flat threshold lets popular nodes hoard edges — one node here reached degree 29, which draws as a wheel with everything on the rim |
| at least `RKB_LINK_MIN` (2) shared posts | one shared post is a coincidence |
| hubs on over `RKB_STOPWORD_FRAC` (50%) of the library are dropped | `open-source`, on 62% of this library, co-occurs with everything and so separates nothing — the `the` of the vocabulary. The note stays; the node goes |

A concept that exists as both a tool and a tag (`Tools/n8n` and `Topics/n8n`)
is merged into the tool, so one concept draws as one node instead of two
lookalikes side by side.

**Nothing is left off the map.** Pruning is aimed at thinning dense nodes, but
it silences sparse ones as a side effect: a hub can clear the bar to *exist*
(2 posts) and miss the bar to *connect* (2 shared posts), leaving it present in
the vault and absent from the graph. Two passes fix that, each adding at most
one edge:

- a node with no edges gets its single strongest association, even at one shared
  post — this recovered `privacy → homelab`, `productivity → project-management`,
  `gated-content → marketing`
- a whole component that found only itself gets attached to the mainland the
  same way — `sarvam`/`voice-agents` had each other and so were never rescued as
  nodes, while sharing a post with `debugging` all along

Ties this far down are common and are broken towards the **better-connected**
partner: that pulls the node into an existing cluster, where attaching it to
another loose node would only make a two-node island belonging nowhere.

The result on this library: **52 concepts, 92 links, one connected map, no
orphans**, where the worst node used to have 29 edges.

## Colouring the graph

The graph view is filtered to `Tools/` and `Topics/` — the posts are the
substrate, not the map.

```bash
./bin/rkb graph                # cluster colours + concepts-only filter
./bin/rkb graph --everything   # put posts and authors back in
```

`rkb graph` runs label propagation over the concept graph and gives each
detected cluster its own colour, so the map reads as regions rather than as one
undifferentiated mesh. It is deterministic — same library, same clusters, same
colours, run after run. Here it finds four:

```
#E8A33D  (17)  business & automation
               agency · automation · business · coolify · ghost · growth ·
               lead-generation · marketing · medusa · n8n · sales · startups ·
               supabase · sarvam · voice-agents · debugging · gated-content

#4FC3A1  (15)  AI-assisted coding
               claude · claude code · cursor · prompt-engineering · skills ·
               design · devtools · documentation · vibe-coding · webdev · seo ·
               checklist · homelab · privacy · 3d-visualization

#A78BFA  (12)  agent infrastructure
               agents · mcp · memory · architecture · claude fable 5 · docker ·
               evals · local-first · self-hosted · sqlite · project-management ·
               productivity

#5B9DF9  ( 8)  local inference & cost
               ollama · groq · local-llm · rag · ai-gateway · cost-control ·
               python · uv
```

The palette avoids red/green, so the four stay distinct under the common forms
of colour blindness. It also prints which edges were inferred rather than
observed — those are the weakest claims on the map, each resting on a single
shared post.

**Quit Obsidian before running it.** Obsidian holds the graph state in memory
and writes `.obsidian/graph.json` back on exit, silently discarding anything
edited underneath it — so the command refuses to run against a live Obsidian
rather than pretending to have worked. To change just the filter without
restarting, paste it into *Graph view → Filters* instead; that takes effect
immediately and Obsidian persists it itself.

**SQLite stays the source of truth and the vault is a generated view**, so
`rkb vault` is safe to re-run after every batch. Two things survive a
regeneration: anything you type below the `rkb:end` marker at the bottom of a
note, and the `.base` files once they exist — so re-sort and re-column those
views freely. Notes rkb didn't write are never touched.

Put the vault elsewhere with `./bin/rkb vault -o ~/Documents/MyVault` or
`RKB_VAULT=...`.

**Where to root it in Obsidian.** Either `vault/` or the repo itself works.
The `.base` filters key off a note property rather than a folder path, and
thumbnails are embedded as `![[<shortcode>.jpg]]` — a wikilink resolves by
filename from anywhere in the vault — so nothing depends on where the root is.
Rooting at the repo also pulls `README.md` and `CLAUDE.md` into the vault, which
you may or may not want.

**Attachments are hard links, not a symlink.** `attachments/` was a symlink to
`data/media` at first, which costs nothing and does not work: Obsidian does not
index through a symlinked folder, so every embed under it resolved to *"could
not be found"*. Hard links cost no disk either — same inode, the 77 MB is shared
with `data/media`, and `du -ch data/media vault/attachments` still reports the
`data/media` total. They are ordinary files to the indexer, and they are
re-linked on every `rkb vault`, so a re-sampled frame is picked up.

`<shortcode>-01.jpg` is the whole join between an image and its post — there is
no attachments table to carry one. The number is the position in the post, so
`-01` is always the cover, and a wikilink resolves by filename from anywhere in
the vault, so the scheme survives you rooting the vault at the repo.

**Every image is on the note**, as a collapsed contact sheet below the summary —
*Slides (20)* on a carousel, *Keyframes (8)* on a reel. Collapsed because twenty
slides open by default bury the summary, the links and the tools under a page of
scrolling; `RKB_GALLERY_WIDTH` sets the tile size.

A carousel's gallery is built from the **downloaded slides, not `frames/`**.
`frames/` is what goes to the vision pass and is capped at `MAX_FRAMES` (8) —
and 9 of the 14 carousels here carry more than that, up to 20. On a listicle
post the slides past the eighth are not redundant stills, they are half the
content. A video has no such original, so `frames/` *is* its set: sampled to
favour the opening title card and the closing outro, which is where links live.
