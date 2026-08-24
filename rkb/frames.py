"""Sample frames for the vision pass.

Frames are extracted for EVERY post, never conditionally on whether there is
speech. A reel can have a clean voiceover and still flash the only GitHub URL
on screen for one second -- transcript-only would silently lose it.

Sampling is weighted toward the opening beat, because tech reels put the tool
name or link on a title card in the first second or two and then cut away.
mpdecimate throws away near-identical frames, so a static title card costs one
frame instead of six, and the budget goes to frames that actually differ.
"""
import shutil
import subprocess
from pathlib import Path

from . import config

SCALE = f"scale='min({config.FRAME_WIDTH},iw)':-2"


def _ffmpeg(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args],
                          capture_output=True, text=True, timeout=300)


def duration(video):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def has_audio(video):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, timeout=60)
    return bool(r.stdout.strip())


def _pass(video, out_dir, prefix, fps, start=None, dur=None):
    args = []
    if start:
        args += ["-ss", str(start)]
    args += ["-i", str(video)]
    if dur:
        args += ["-t", str(dur)]
    args += ["-vf", f"fps={fps},mpdecimate,{SCALE}", "-fps_mode", "vfr",
             "-q:v", "3", str(out_dir / f"{prefix}_%03d.jpg")]
    _ffmpeg(args)
    return sorted(out_dir.glob(f"{prefix}_*.jpg"))


def for_ocr(video, out_dir):
    """Dense sampling for the OCR pass, kept separate from the vision frames.

    The vision budget (MAX_FRAMES) exists to cap tokens. OCR is local and costs
    nothing per image, so applying the same cap just throws away screens. Here
    the whole video is walked at OCR_FPS with mpdecimate doing the work: a
    slideshow holds each screen for seconds, so it collapses to roughly one
    frame per screen rather than one per sampled instant.
    """
    video, out_dir = Path(video), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    got = _pass(video, out_dir, "ocr", config.OCR_FPS)
    # Trim evenly if a very long video still blows past the cap, always keeping
    # the first and last frame -- links live at both ends.
    if len(got) > config.OCR_MAX_FRAMES:
        step = len(got) / config.OCR_MAX_FRAMES
        keep = {got[min(int(i * step), len(got) - 1)] for i in range(config.OCR_MAX_FRAMES)}
        keep.add(got[0]); keep.add(got[-1])
        for f in got:
            if f not in keep:
                f.unlink()
        got = sorted(keep)
    return got


def from_video(video, out_dir):
    video, out_dir = Path(video), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    head = _pass(video, out_dir, "head", config.HEAD_FPS, dur=config.HEAD_SECONDS)
    if not head:  # nothing survived dedup -- force the very first frame
        _ffmpeg(["-i", str(video), "-vf", SCALE, "-frames:v", "1", "-q:v", "3",
                 str(out_dir / "head_001.jpg")])
        head = sorted(out_dir.glob("head_*.jpg"))

    tail = []
    if duration(video) > config.HEAD_SECONDS + 1:
        tail = _pass(video, out_dir, "tail", config.TAIL_FPS,
                     start=config.HEAD_SECONDS)

    keep = _budget(head, tail)
    for f in head + tail:
        if f not in keep:
            f.unlink()
    return _renumber(keep, out_dir)


def _budget(head, tail):
    """Head gets up to half the budget; tail is thinned evenly but always keeps
    its last frame, which is usually the outro card with the link."""
    head_cap = max(1, config.MAX_FRAMES // 2)
    keep = head[:head_cap]
    room = config.MAX_FRAMES - len(keep)
    if tail and room > 0:
        if len(tail) <= room:
            keep += tail
        else:
            step = len(tail) / room
            picked = [tail[min(int(i * step), len(tail) - 1)] for i in range(room)]
            if tail[-1] not in picked:
                picked[-1] = tail[-1]
            keep += picked
    return keep


def _renumber(files, out_dir):
    out = []
    for i, f in enumerate(sorted(set(files)), 1):
        dest = out_dir / f"frame_{i:02d}.jpg"
        if f != dest:
            f.rename(dest)
        out.append(dest)
    return out


def from_images(media_dir, out_dir):
    """Carousel slides: no sampling needed, just downscale each slide."""
    media_dir, out_dir = Path(media_dir), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    slides = sorted(p for p in media_dir.iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic"})
    out = []
    for i, src in enumerate(slides[:config.MAX_FRAMES], 1):
        dest = out_dir / f"frame_{i:02d}.jpg"
        _ffmpeg(["-i", str(src), "-vf", SCALE, "-q:v", "3", str(dest)])
        if dest.exists():
            out.append(dest)
    return out
