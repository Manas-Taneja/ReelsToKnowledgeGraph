"""Stage 1: get every post ready for the vision/extraction pass.

Downloads media, samples frames, transcribes, and writes a context.md next to
the frames. After this runs, each post is a self-contained folder that Claude
Code can read in one go -- no API wiring needed on the extraction side.
"""
import time
from pathlib import Path

from . import acquire, config, db, frames, ocr, transcribe


def _context_md(post, caption, transcript, frame_files, ocr_text=""):
    lines = [
        f"# {post['shortcode']}",
        "",
        f"- url: {post['url']}",
        f"- kind: {post['kind']}",
        f"- saved_at: {post['saved_at'] or 'unknown'}",
        f"- frames: {len(frame_files)} in ./frames/",
        "",
        "## Caption",
        "",
        (caption or "_(none)_").strip(),
        "",
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
    got = acquire.acquire(shortcode, post["url"])
    media_dir = Path(got["media_dir"])
    frames_dir = media_dir / "frames"

    transcript = ""
    if got["media_kind"] == "video":
        video = next(p for p in media_dir.iterdir()
                     if p.suffix.lower() in acquire.VIDEO_EXT)
        frame_files = frames.from_video(video, frames_dir)
        frames.for_ocr(video, media_dir / "ocr_frames")   # dense set, OCR only
        transcript = transcribe.transcribe(video)
    else:
        frame_files = frames.from_images(media_dir, frames_dir)

    if not frame_files:
        raise RuntimeError("no frames could be extracted")

    caption = got["caption"]
    # OCR is part of preparing a post, not an afterthought: on a carousel the
    # on-screen text IS the content, and paraphrasing it from sampled frames
    # loses tables, parameter lists and exact library names.
    try:
        ocr_text = ocr.frame_text(media_dir)
    except Exception as e:                      # never fail a post over OCR
        print(f"    ocr skipped: {e}")
        ocr_text = ""

    (media_dir / "context.md").write_text(
        _context_md(post, caption, transcript, frame_files, ocr_text))

    with con:
        con.execute(
            "UPDATE posts SET media_kind=?, media_dir=?, caption=?, transcript=?, "
            "ocr_text=?, status='prepared', error=NULL, prepared_at=datetime('now') "
            "WHERE shortcode=?",
            (got["media_kind"], str(media_dir), caption, transcript, ocr_text,
             shortcode),
        )
    db.reindex(con, shortcode)
    return {"frames": len(frame_files), "transcript_chars": len(transcript),
            "media_kind": got["media_kind"]}


def prepare_batch(limit=25, retry=False, kind=None):
    con = db.init()
    states = ("new", "failed") if retry else ("new",)
    sql = (f"SELECT * FROM posts WHERE status IN ({','.join('?' * len(states))}) ")
    params = list(states)
    if kind:
        sql += "AND kind = ? "
        params.append(kind)
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
