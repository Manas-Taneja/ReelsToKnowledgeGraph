"""On-device OCR for frames, via Apple's Vision framework.

Vision sampling reads a couple of frames per post and paraphrases what it sees.
That is fine for a title card with a repo URL on it and badly wrong for a dense
slide: a single carousel page can carry a comparison table, a parameter list and
three specific library names, and none of it survives being summarised.

So every frame gets OCR'd verbatim and stored alongside the transcript. It is
local, free and fast (no API, no quota), the text goes into the FTS index so it
is searchable on its own, and extraction reads it instead of guessing from two
sampled frames.

Requires: pyobjc-framework-Vision (macOS only).
"""
import sys
from pathlib import Path

from . import acquire, config, db, frames

# Vision's own confidence floor; below this it is usually background noise
# (watermarks, UI chrome bleeding through, compression artefacts).
MIN_CONFIDENCE = 0.35


def _recognise(path):
    """OCR one image. Returns lines in reading order."""
    import Quartz
    import Vision

    url = Quartz.NSURL.fileURLWithPath_(str(path))
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        return []
    image = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if image is None:
        return []

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision failed on {path.name}: {err}")

    out = []
    for obs in req.results() or []:
        best = obs.topCandidates_(1)
        if not best:
            continue
        cand = best[0]
        if cand.confidence() < MIN_CONFIDENCE:
            continue
        box = obs.boundingBox()
        # Vision's origin is bottom-left; sort top-to-bottom, then left-to-right
        # so multi-column slides come out in something like reading order.
        out.append((-box.origin.y, box.origin.x, cand.string()))
    out.sort()
    return [text for _, _, text in out]


def _sources(media_dir):
    """What to OCR, and what to call each piece.

    For a carousel the sampled frames are the wrong input: frame extraction caps
    at MAX_FRAMES, so a 20-slide deck gets read as 8. The original slides are
    already on disk, every one of them, so OCR those instead -- there is no
    sampling budget to respect when the images are stills to begin with.

    Videos have no equivalent: the frames ARE the sampling, so they stand.
    """
    media_dir = Path(media_dir)
    slides = sorted(p for p in media_dir.iterdir()
                    if p.suffix.lower() in acquire.IMAGE_EXT)
    if slides:
        return [(f"slide_{i:02d}", p) for i, p in enumerate(slides, 1)]

    # Video: use the dense OCR sampling, generating it if this post predates it.
    dense_dir = media_dir / "ocr_frames"
    dense = sorted(dense_dir.glob("*.jpg"))
    if not dense:
        video = next(iter(p for p in media_dir.iterdir()
                          if p.suffix.lower() in acquire.VIDEO_EXT), None)
        if video is not None:
            dense = frames.for_ocr(video, dense_dir)
    if dense:
        return [(f"frame_{i:03d}", p) for i, p in enumerate(dense, 1)]

    return [(f.stem, f) for f in sorted((media_dir / "frames").glob("*.jpg"))]


def frame_text(media_dir):
    """OCR every image of one post, labelled so slides stay separable.

    A caption overlay or a title card sits on top of every frame, so naive
    concatenation gives eight copies of the same sentence and buries the one
    slide that actually differs. Lines already seen on an earlier frame of the
    same post are dropped, which leaves the new content per frame.
    """
    chunks, seen = [], set()
    for label, f in _sources(media_dir):
        fresh = []
        for line in _recognise(f):
            key = " ".join(line.split()).casefold()
            if len(key) > 3 and key in seen:      # keep short labels like "1." or "Fix:"
                continue
            seen.add(key)
            fresh.append(line)
        if fresh:
            chunks.append(f"[{label}]\n" + "\n".join(fresh))
    return "\n\n".join(chunks)


def run(limit=None, force=False, shortcodes=None):
    con = db.init()
    sql = ("SELECT shortcode, media_dir FROM posts "
           "WHERE media_dir IS NOT NULL AND status != 'archived'")
    params = []
    if shortcodes:
        sql += f" AND shortcode IN ({','.join('?' * len(shortcodes))})"
        params += list(shortcodes)
    elif not force:
        sql += " AND (ocr_text IS NULL OR ocr_text = '')"
    sql += " ORDER BY saved_at DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    rows = con.execute(sql, params).fetchall()
    done, empty, failed = [], [], []
    for i, r in enumerate(rows, 1):
        sc = r["shortcode"]
        print(f"[{i}/{len(rows)}] {sc} ...", flush=True)
        try:
            text = frame_text(r["media_dir"])
        except Exception as e:                       # one bad frame never stops a run
            failed.append((sc, str(e)))
            print(f"    failed: {e}")
            continue
        with con:
            con.execute("UPDATE posts SET ocr_text=? WHERE shortcode=?", (text, sc))
        db.reindex(con, sc)
        if text:
            done.append(sc)
            n = text.count("[frame_") + text.count("[slide_")
            kind = "slide" if "[slide_" in text else "frame"
            print(f"    ok: {len(text)} chars from {n} {kind}(s)")
        else:
            empty.append(sc)
            print("    no text found on any frame")
    return {"ocr": done, "no_text": empty, "failed": failed}
