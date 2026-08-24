"""rkb — Reels To Knowledge Base."""
import argparse
import json
import sys
from pathlib import Path

from . import (config, dashboard, db, graph, importer, ocr, prepare, record,
               review, search, serve, triage, vault, vaultsync, verify)


def cmd_init(a):
    db.init()
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    config.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"db ready at {config.DB_PATH}")
    print(f"drop your Meta export JSON into {config.EXPORT_DIR}")


def cmd_import(a):
    paths = a.paths or [config.DATA]
    if a.exclude is not None:
        names = [n.strip() for c in a.exclude for n in c.split(",") if n.strip()]
        importer.set_excluded(names)
    print(json.dumps(importer.import_paths(paths), indent=2))


def cmd_collections(a):
    con = db.init()
    rows = con.execute(
        "SELECT COALESCE(collection,'(uncollected)') c, COUNT(*) n, "
        "  SUM(status='extracted') done "
        "FROM posts GROUP BY c ORDER BY n DESC"
    ).fetchall()
    ex = importer.excluded_collections()
    for r in rows:
        print(f"  {r['c']:<20} {r['n']:>4} posts   {r['done'] or 0} extracted")
    if ex:
        print(f"\nexcluded from import: {', '.join(sorted(ex))}")
        print(f"(edit {importer.EXCLUDE_FILE})")


def cmd_prepare(a):
    r = prepare.prepare_batch(limit=a.limit, retry=a.retry, kind=a.kind)
    print(f"\nprepared {len(r['prepared'])}, failed {len(r['failed'])}")
    for sc, err in r["failed"]:
        print(f"  {sc}: {err}")


def cmd_pending(a):
    con = db.init()
    rows = con.execute(
        "SELECT shortcode, url, media_kind, media_dir, length(transcript) AS tlen "
        "FROM posts WHERE status='prepared' ORDER BY saved_at DESC LIMIT ?",
        (a.limit,),
    ).fetchall()
    if a.json:
        print(json.dumps([dict(r) for r in rows], indent=2))
        return
    if not rows:
        print("nothing prepared and awaiting extraction")
        return
    print(f"{len(rows)} post(s) ready for extraction:\n")
    for r in rows:
        frames = len(list((Path(r["media_dir"]) / "frames").glob("*.jpg")))
        print(f"  {r['shortcode']}  [{r['media_kind']}, {frames} frames, "
              f"{r['tlen'] or 0} transcript chars]")
        print(f"    {r['media_dir']}/context.md")


def cmd_record(a):
    print(json.dumps(record.record_from(a.file, check_links=not a.no_verify), indent=2))


def cmd_verify(a):
    r = verify.run(limit=a.limit, shortcodes=a.shortcode or None)
    print(f"\nchecked {r['checked']} link(s): "
          f"{len(r['repaired'])} repaired, {len(r['dead'])} dead and removed")
    for sc, d in r["dead"]:
        print(f"  {sc}: {d}")
    if r["dead"]:
        print("\nposts that lost their only link are back in the review queue")


def cmd_search(a):
    print(search.render(search.search(a.query, a.limit)))


def cmd_status(a):
    con = db.init()
    rows = con.execute(
        "SELECT status, COUNT(*) n FROM posts GROUP BY status ORDER BY n DESC"
    ).fetchall()
    total = sum(r["n"] for r in rows)
    print(f"{total} posts in the knowledge base")
    for r in rows:
        print(f"  {r['status']:<10} {r['n']}")
    fails = con.execute(
        "SELECT shortcode, error FROM posts WHERE status='failed' LIMIT 10"
    ).fetchall()
    if fails:
        print("\nrecent failures:")
        for f in fails:
            print(f"  {f['shortcode']}: {(f['error'] or '')[:120]}")


def cmd_triage(a):
    groups = triage.triage()
    print(triage.render(groups))
    drop = [r for k in ("junk", "gated") for r, _ in groups.get(k, [])]
    print(f"\n{'─' * 78}")
    if not a.apply:
        print(f"DRY RUN — nothing changed. {len(drop)} post(s) would be archived.")
        print("Archive them with:  ./bin/rkb triage --apply")
        print("Archiving is reversible (status='archived'); media is left on disk.")
        return
    con = db.init()
    with con:
        for r in drop:
            con.execute("UPDATE posts SET status='archived' WHERE shortcode=?",
                        (r["shortcode"],))
    print(f"archived {len(drop)} post(s). Run ./bin/rkb vault to refresh Obsidian.")
    print("Undo:  sqlite3 data/reels.db \"UPDATE posts SET status='extracted' "
          "WHERE status='archived'\"")


def cmd_ocr(a):
    r = ocr.run(limit=a.limit, force=a.force, shortcodes=a.shortcode or None)
    print(f"\nocr'd {len(r['ocr'])}, no text {len(r['no_text'])}, "
          f"failed {len(r['failed'])}")
    for sc, err in r["failed"]:
        print(f"  {sc}: {err}")


def cmd_dashboard(a):
    if a.serve:
        return serve.run(revisit=a.revisit, port=a.port)
    r = dashboard.build(a.out, revisit=a.revisit)
    if not r["posts"]:
        print("nothing to review — every extracted post has a link")
        return
    print(f"{r['posts']} post(s) need review → {r['path']}")
    print("open it, decide, hit 'Copy decisions', then: ./bin/rkb review")


def _report_decisions(r):
    """Shared by `review` (dashboard) and `sync` (Obsidian)."""
    for k in ("linked", "kept", "recheck", "archived", "reset"):
        if r[k]:
            print(f"{k}: {len(r[k])}  ({', '.join(r[k])})")
    if r["unchanged"]:
        print(f"unchanged: {len(r['unchanged'])}  "
              f"(already in that state — {', '.join(r['unchanged'])})")
    if r["dead"]:
        print(f"\nNOT recorded — {len(r['dead'])} link(s) did not resolve:")
        for sc, url in r["dead"]:
            print(f"  {sc}: {url}")
        print("  (check the OCR for a typo; the decision was left untouched)")
    if r.get("problems"):
        print(f"\n{len(r['problems'])} note(s) I could not read a decision from:")
        for name, why in r["problems"]:
            print(f"  {name}: {why}")
    if r["unknown"]:
        print(f"unknown shortcodes: {', '.join(r['unknown'])}")
    if r["notes"]:
        print("\nyour notes:")
        for sc, n in r["notes"].items():
            print(f"  {sc}: {n}")


def cmd_sync(a):
    if a.watch:
        return _watch_vault(a.out)
    r = vaultsync.sync(a.out)
    _report_decisions(r)
    if vaultsync.changed(r):
        v = vault.build(a.out)
        print(f"\nvault refreshed — {v['pending']} post(s) still in the queue")
    elif not r["problems"]:
        print(f"nothing new — read {r['seen'] or 'no'} decision(s) in the vault")


def _watch_vault(out):
    print(f"watching {vault.vault_dir(out) / vault.REELS} — edit `review` in "
          f"Obsidian and it saves itself.\nCtrl-C to stop.\n")

    def on_change(r):
        _report_decisions(r)
        if vaultsync.changed(r):
            v = vault.build(out)
            print(f"  → synced; {v['pending']} left in the queue\n", flush=True)

    try:
        vaultsync.watch(out, on_change=on_change)
    except KeyboardInterrupt:
        print("\nstopped.")


def cmd_review(a):
    r = review.apply_from(a.file)
    _report_decisions(r)
    if r["recheck"]:
        print(f"\n{len(r['recheck'])} post(s) back in the extraction queue "
              f"— ask me to re-extract them")
    if any(r[k] for k in ("linked", "kept", "recheck", "archived", "reset")):
        print("\nrun ./bin/rkb vault to refresh Obsidian")
    elif r["unchanged"]:
        print("\nnothing changed. If you meant to submit new decisions, rebuild the\n"
              "dashboard (./bin/rkb dashboard --revisit), decide, then Copy decisions\n"
              "again — the clipboard still held the previous set.")


def cmd_vault(a):
    # Read your Obsidian decisions back BEFORE regenerating over them.
    if not a.no_sync:
        pulled = vaultsync.sync(a.out)
        if vaultsync.changed(pulled) or pulled["problems"]:
            print("picked up decisions you made in Obsidian:")
            _report_decisions(pulled)
            print()
    r = vault.build(a.out, rebuild_bases=a.rebuild_bases)
    print(f"vault written to {r['vault']}")
    print(f"  {r['reels']} reel notes, {r['tools']} tools, "
          f"{r['topics']} topics, {r['authors']} authors")
    print(f"  Repos.md ({r['repos']} repos) · Prompts.md ({r['prompts']} posts)")
    print(f"  {r['images']} images linked into attachments/ "
          f"({r['galleries']} posts with a gallery)")
    if r["removed_stale"]:
        print(f"  removed {r['removed_stale']} stale note(s)")
    for name in r["bases"]:
        print(f"  created {name}")
    if r["pending"] and r["review_in_vault"]:
        print(f"\n{r['pending']} post(s) awaiting your review — open "
              f"'Review Queue.base' in Obsidian, set `review` on each,\n"
              f"then run ./bin/rkb sync (or ./bin/rkb sync --watch to have it "
              f"save as you go).")
    elif r["pending"]:
        print(f"\n{r['pending']} post(s) awaiting your review — "
              f"./bin/rkb dashboard --serve")
    print("\nOpen Obsidian > 'Open folder as vault' > select that folder.")


def cmd_graph(a):
    r = graph.apply(a.out, concepts_only=not a.everything)
    print(f"graph settings written to {r['path']}")
    print(f"  {r['nodes']} concepts · {r['edges']} links\n")
    for i, (_, colour, members) in enumerate(r["groups"], 1):
        head = ", ".join(members[:6])
        more = f" +{len(members) - 6}" if len(members) > 6 else ""
        print(f"  {colour}  cluster {i} ({len(members)}): {head}{more}")
    if r["stopwords"]:
        print(f"\n  hidden as too common to separate anything: "
              f"{', '.join(r['stopwords'])}")
    if r["rescued"]:
        print(f"\n  would have been left off the map, attached by their "
              f"strongest single link:")
        for n, o in sorted(r["rescued"].items()):
            print(f"    {n} → {o}")
    for a, b in r["joined"]:
        print(f"    (island) {a} → {b}")
    print("\nReopen Obsidian to see it.")


def cmd_show(a):
    con = db.init()
    r = con.execute(
        "SELECT p.*, e.summary, e.detail, e.tools, e.links, e.tags, e.actionable "
        "FROM posts p LEFT JOIN extractions e USING (shortcode) WHERE p.shortcode=?",
        (a.shortcode,),
    ).fetchone()
    if not r:
        sys.exit(f"unknown shortcode: {a.shortcode}")
    print(json.dumps(dict(r), indent=2, ensure_ascii=False))


def main(argv=None):
    p = argparse.ArgumentParser(prog="rkb", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the database and folders").set_defaults(fn=cmd_init)

    s = sub.add_parser("import", help="load saved posts from a Meta export")
    s.add_argument("paths", nargs="*", help="files/dirs (default: data/)")
    s.add_argument("--exclude", action="append", metavar="COLLECTION",
                   help="collections to never import (comma-separated, repeatable); "
                        "saved to data/excluded_collections.txt")
    s.set_defaults(fn=cmd_import)

    sub.add_parser("collections", help="post counts per collection"
                   ).set_defaults(fn=cmd_collections)

    s = sub.add_parser("prepare", help="download + frame + transcribe a batch")
    s.add_argument("-n", "--limit", type=int, default=25)
    s.add_argument("--retry", action="store_true", help="also retry failed posts")
    s.add_argument("--kind", choices=("reel", "post"),
                   help="only reels (no login needed) or only image posts")
    s.set_defaults(fn=cmd_prepare)

    s = sub.add_parser("pending", help="list posts awaiting extraction")
    s.add_argument("-n", "--limit", type=int, default=30)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_pending)

    s = sub.add_parser("record", help="write extraction results back (JSON)")
    s.add_argument("file", nargs="?", default="-", help="JSON file, or - for stdin")
    s.add_argument("--no-verify", action="store_true",
                   help="skip checking that the links resolve")
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("verify", help="check every recorded link still resolves")
    s.add_argument("-n", "--limit", type=int)
    s.add_argument("shortcode", nargs="*")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("search", help="full-text search the knowledge base")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.set_defaults(fn=cmd_search)

    sub.add_parser("status", help="counts by pipeline stage").set_defaults(fn=cmd_status)

    s = sub.add_parser("triage", help="classify posts by whether they carry a payload")
    s.add_argument("--apply", action="store_true",
                   help="archive the junk/gated posts (default is a dry run)")
    s.set_defaults(fn=cmd_triage)

    s = sub.add_parser("ocr", help="read text off every frame (Apple Vision, on-device)")
    s.add_argument("-n", "--limit", type=int)
    s.add_argument("--force", action="store_true", help="redo posts already OCR'd")
    s.add_argument("shortcode", nargs="*", help="specific posts (default: all missing)")
    s.set_defaults(fn=cmd_ocr)

    s = sub.add_parser("dashboard", help="build the review queue for link-less posts")
    s.add_argument("-o", "--out", metavar="FILE", help="default: ./dashboard.html")
    s.add_argument("--port", type=int, default=serve.PORT,
                   help=f"port for --serve (default {serve.PORT})")
    s.add_argument("--serve", action="store_true",
                   help="serve it locally so clicks save straight to the db "
                        "(no copy/paste)")
    s.add_argument("--revisit", action="store_true",
                   help="also re-open link-less posts you already decided")
    s.set_defaults(fn=cmd_dashboard)

    s = sub.add_parser("review", help="apply decisions copied from the dashboard")
    s.add_argument("file", nargs="?", default=None,
                   help="JSON file; omit to read the clipboard, - for stdin")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("sync", help="read your Obsidian review decisions into the db")
    s.add_argument("--out", help="vault folder (default: ./vault)")
    s.add_argument("--watch", action="store_true",
                   help="keep running and sync the moment you change a property")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("vault", help="render the knowledge base as an Obsidian vault")
    s.add_argument("--no-sync", action="store_true",
                   help="skip reading Obsidian decisions back first")
    s.add_argument("--rebuild-bases", action="store_true",
                   help="overwrite the .base views (normally written once)")
    s.add_argument("-o", "--out", metavar="DIR",
                   help="vault folder (default: ./vault, or $RKB_VAULT)")
    s.set_defaults(fn=cmd_vault)

    s = sub.add_parser("graph", help="style Obsidian's graph view (quit Obsidian first)")
    s.add_argument("--out", help="vault folder (default: ./vault)")
    s.add_argument("--everything", action="store_true",
                   help="show posts and authors too, not just tools/topics")
    s.set_defaults(fn=cmd_graph)

    s = sub.add_parser("show", help="dump everything known about one post")
    s.add_argument("shortcode")
    s.set_defaults(fn=cmd_show)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
