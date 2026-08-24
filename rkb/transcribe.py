"""Local transcription via mlx-whisper (runs on the Neural Engine / GPU, no API quota).

Returns "" rather than raising when a post has no speech -- a silent b-roll reel
is a normal case here, not an error, and the vision pass carries it.
"""
import re
import subprocess
import tempfile
from pathlib import Path

from . import config, frames

# Whisper reliably invents these over music or silence. Treat as no speech.
HALLUCINATIONS = {
    "thanks for watching", "thank you for watching", "subscribe to my channel",
    "please subscribe", "thanks for watching!", "you", "bye", "sub by",
    "subtitles by the amara.org community", "www.mooji.org", "amara.org",
    "transcription by castingwords", "for more information visit",
}

_model = None


def _audio(video, wav):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "-y", str(wav)],
        capture_output=True, text=True, timeout=300)
    return wav.exists() and wav.stat().st_size > 1024 and r.returncode == 0


def _looks_like_noise(text):
    t = text.strip().lower().strip(".!? ")
    if len(t) < 12:
        return True
    if t in HALLUCINATIONS:
        return True
    # A single phrase looped over and over is whisper spinning on music.
    words = re.findall(r"\w+", t)
    if len(words) >= 8 and len(set(words)) / len(words) < 0.25:
        return True
    return False


def transcribe(video):
    """Transcribe a video file. Returns transcript text ('' if no usable speech)."""
    global _model
    video = Path(video)
    if not frames.has_audio(video):
        return ""

    import mlx_whisper  # imported lazily: ~2s and only needed on the video path

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        if not _audio(video, wav):
            return ""
        result = mlx_whisper.transcribe(
            str(wav),
            path_or_hf_repo=config.WHISPER_MODEL,
            condition_on_previous_text=False,  # curbs runaway repetition
            no_speech_threshold=0.6,
        )

    text = (result.get("text") or "").strip()
    return "" if _looks_like_noise(text) else text
