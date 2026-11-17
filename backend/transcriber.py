"""Speech-to-text: Groq free tier (whisper-large-v3-turbo) with local faster-whisper fallback.

Returns {"language", "engine", "segments": [{start,end,text}], "words": [{word,start,end}]}.
"""
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger("transcriber")

GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
LOCAL_MODEL_SIZE = os.getenv("WHISPER_MODEL", "tiny")  # tiny | base
CHUNK_SECONDS = 600  # keeps each upload far below Groq's free-tier 25 MB file limit
_local_model = None


class TranscriptionError(Exception):
    pass


def _to_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            return fn()
    return dict(vars(obj))


def _words_from_segments(segments: list[dict]) -> list[dict]:
    """Fallback when the engine returns no word timestamps: spread words evenly."""
    words = []
    for s in segments:
        toks = s["text"].split()
        if not toks:
            continue
        step = (s["end"] - s["start"]) / len(toks)
        for i, t in enumerate(toks):
            words.append({"word": t, "start": s["start"] + i * step, "end": s["start"] + (i + 1) * step})
    return words


def _split_audio(audio_path: str, out_dir: Path) -> list[Path]:
    cmd = [
        "ffmpeg", "-y", "-i", audio_path, "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
        "-reset_timestamps", "1", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(out_dir / "chunk_%03d.flac"),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        raise TranscriptionError(f"ffmpeg could not split audio: {p.stderr[-300:]}")
    return sorted(out_dir.glob("chunk_*.flac"))


def _transcribe_groq(audio_path: str) -> dict:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    segments, words, language = [], [], None
    with tempfile.TemporaryDirectory() as tmp:
        chunks = _split_audio(audio_path, Path(tmp))
        for idx, chunk in enumerate(chunks):
            offset = idx * CHUNK_SECONDS
            data = chunk.read_bytes()
            resp = None
            for attempt in range(3):
                try:
                    resp = client.audio.transcriptions.create(
                        file=(chunk.name, data),
                        model=GROQ_STT_MODEL,
                        response_format="verbose_json",
                        timestamp_granularities=["word", "segment"],
                        temperature=0.0,
                    )
                    break
                except Exception as exc:  # rate limit / transient errors
                    if attempt == 2:
                        raise
                    log.warning("Groq STT retry %s: %s", attempt + 1, exc)
                    time.sleep(8 * (attempt + 1))
            d = _to_dict(resp)
            language = language or d.get("language")
            for s in d.get("segments") or []:
                s = _to_dict(s)
                text = (s.get("text") or "").strip()
                if text:
                    segments.append({"start": float(s["start"]) + offset, "end": float(s["end"]) + offset, "text": text})
            for w in d.get("words") or []:
                w = _to_dict(w)
                words.append({"word": w["word"].strip(), "start": float(w["start"]) + offset, "end": float(w["end"]) + offset})
    return {"language": language, "engine": "groq", "segments": segments, "words": words}


def _transcribe_local(audio_path: str) -> dict:
    global _local_model
    from faster_whisper import WhisperModel

    if _local_model is None:
        _local_model = WhisperModel(LOCAL_MODEL_SIZE, device="cpu", compute_type="int8")
    seg_iter, info = _local_model.transcribe(audio_path, word_timestamps=True, vad_filter=True, beam_size=1)
    segments, words = [], []
    for s in seg_iter:
        text = s.text.strip()
        if not text:
            continue
        segments.append({"start": float(s.start), "end": float(s.end), "text": text})
        for w in s.words or []:
            words.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
    return {"language": info.language, "engine": f"faster-whisper-{LOCAL_MODEL_SIZE}", "segments": segments, "words": words}


def transcribe(audio_path: str) -> dict:
    mode = os.getenv("TRANSCRIBER", "auto").lower()  # auto | groq | local
    result, errors = None, []
    if mode in ("auto", "groq") and os.getenv("GROQ_API_KEY"):
        try:
            result = _transcribe_groq(audio_path)
        except Exception as exc:
            errors.append(f"groq: {exc}")
            log.warning("Groq transcription failed, falling back to local: %s", exc)
    elif mode == "groq":
        errors.append("groq: GROQ_API_KEY is not set")
    if result is None and mode in ("auto", "local", "groq"):
        try:
            result = _transcribe_local(audio_path)
        except Exception as exc:
            errors.append(f"local: {exc}")
    if result is None:
        raise TranscriptionError("Transcription failed (" + "; ".join(errors) + ")")
    if not result["segments"]:
        raise TranscriptionError("No speech was detected in this video.")
    if not result["words"]:
        result["words"] = _words_from_segments(result["segments"])
    return result
