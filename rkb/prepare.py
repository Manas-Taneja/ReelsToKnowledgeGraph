"""Stage 1: get every post ready for the vision/extraction pass.

Downloads media, samples frames, transcribes, and writes a context.md next to
the frames. After this runs, each post is a self-contained folder that Claude
Code can read in one go -- no API wiring needed on the extraction side.

A tweet carrying no media has no frames and no speech, so none of the
mechanical stages have anything to chew on. That is not a failure: the tweet
text IS the post, and context.md is built from it alone.
"""
import json
import time
from pathlib import Path

from . import acquire, config, db, frames, ocr, platforms, transcribe


def _context_md(post, caption, transcript, frame_files, ocr_text="", media_kind=None):
    plat = platforms.get(post["platform"] if "platform" in post.keys() else None)
    text_only = media_kind == "text"
    lines = [
        f"# {post['shortcode']}",
        "",
        f"- url: {post['url']}",
        f"- platform: {plat.label}",
        f"- kind: {post['kind']}",
        f"- saved_at: {post['saved_at'] or 'unknown'}",
        f"- frames: {len(frame_files)} in ./frames/" if frame_files
        else "- frames: none (text-only post)",
        "",
        "## Tweet text" if plat.key == "twitter" else "## Caption",
        "",
        (caption or "_(none)_").strip(),
        "",
    ]
    if text_only:
        # Say it plainly, so the extraction pass does not go hunting for frames
        # that were never sampled and file the post as under-prepared.
        lines += [
            "_This post has no video and no images. The text above is the whole"
            " post -- there is nothing else to read. Hunt the link in it._",
            "",
        ]
        return "\n".join(lines)

    lines += [
        "## Transcript",
        "",
        (transcript.strip() if transcript else
         "_(no speech detected -- read the frames; this is a text-over-video or carousel post)_"),
        "",
    ]
    if ocr_text:
        lines += [
            "## Text on the frames (OCR, verbatim)",
            "",
            "_Read this before the images. It is the literal on-screen text, so a"
            " prompt, checklist or table can be copied out of it exactly rather"
            " than paraphrased from a sampled frame._",
            "",
            ocr_text.strip(),
            "",
        ]
    return "\n".join(lines)


def prepare_one(con, post):
    shortcode = post["shortcode"]
    platform = post["platform"] if "platform" in post.keys() else platforms.DEFAULT
    got = acquire.acquire(shortcode, post["url"], platform)
    media_dir = Path(got["media_dir"])
    frames_dir = media_dir / "frames"

    transcript, frame_files, ocr_text = "", [], ""
    if got["media_kind"] == "video":
        video = next(p for p in media_dir.iterdir()
                     if p.suffix.lower() in acquire.VIDEO_EXT)
        frame_files = frames.from_video(video, frames_dir)
        frames.for_ocr(video, media_dir / "ocr_frames")   # dense set, OCR only
        transcript = transcribe.transcribe(video)
    elif got["media_kind"] == "images":
        frame_files = frames.from_images(media_dir, frames_dir)

    if got["media_kind"] != "text" and not frame_files:
        raise RuntimeError("no frames could be extracted")

    caption = got["caption"]
    if got["media_kind"] == "text" and not (caption or "").strip():
        raise RuntimeError("tweet has neither media nor text")

    # OCR is part of preparing a post, not an afterthought: on a carousel the
    # on-screen text IS the content, and paraphrasing it from sampled frames
    # loses tables, parameter lists and exact library names.
    if frame_files:
        try:
            ocr_text = ocr.frame_text(media_dir)
        except Exception as e:                  # never fail a post over OCR
            print(f"    ocr skipped: {e}")
            ocr_text = ""

    (media_dir / "context.md").write_text(
        _context_md(post, caption, transcript, frame_files, ocr_text,
                    got["media_kind"]))

    # X hands us the author and hashtags at download time -- there is no export
    # to have supplied them earlier. COALESCE keeps the Instagram contract
    # intact: an export that already filled these in still wins.
    hashtags = got.get("hashtags")
    with con:
        con.execute(
            "UPDATE posts SET media_kind=?, media_dir=?, caption=?, transcript=?, "
            "ocr_text=?, author=COALESCE(author, ?), "
            "author_link=COALESCE(author_link, ?), "
            "saved_at=COALESCE(saved_at, ?), "
            "hashtags=CASE WHEN hashtags IN ('', '[]') THEN COALESCE(?, hashtags) "
            "              ELSE hashtags END, "
            "status='prepared', error=NULL, prepared_at=datetime('now') "
            "WHERE shortcode=?",
            (got["media_kind"], str(media_dir), caption, transcript, ocr_text,
             got.get("author"), got.get("author_link"), got.get("saved_at"),
             json.dumps(hashtags, ensure_ascii=False) if hashtags else None,
             shortcode),
        )
    db.reindex(con, shortcode)
    return {"frames": len(frame_files), "transcript_chars": len(transcript),
            "media_kind": got["media_kind"]}


def prepare_batch(limit=25, retry=False, kind=None, platform=None):
    con = db.init()
    states = ("new", "failed") if retry else ("new",)
    sql = (f"SELECT * FROM posts WHERE status IN ({','.join('?' * len(states))}) ")
    params = list(states)
    if kind:
        sql += "AND kind = ? "
        params.append(kind)
    if platform:
        sql += "AND platform = ? "
        params.append(platform)
    sql += "ORDER BY saved_at DESC, shortcode LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()

    done, failed = [], []
    for i, post in enumerate(rows, 1):
        sc = post["shortcode"]
        print(f"[{i}/{len(rows)}] {sc} ...", flush=True)
        try:
            info = prepare_one(con, post)
            done.append(sc)
            print(f"    ok: {info['media_kind']}, {info['frames']} frames, "
                  f"{info['transcript_chars']} transcript chars", flush=True)
        except Exception as e:  # one bad post must not stop the batch
            with con:
                con.execute("UPDATE posts SET status='failed', error=? WHERE shortcode=?",
                            (str(e)[:500], sc))
            failed.append((sc, str(e)[:200]))
            print(f"    FAILED: {str(e)[:200]}", flush=True)
        if i < len(rows):
            time.sleep(config.SLEEP_BETWEEN)

    return {"prepared": done, "failed": failed}
