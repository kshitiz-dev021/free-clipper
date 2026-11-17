"""YouTube VOD + Live ingestion via yt-dlp, plus 16 kHz mono audio extraction."""
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

YTDLP = [sys.executable, "-m", "yt_dlp"]
LIVE_WINDOW_SECONDS = int(os.getenv("LIVE_WINDOW_SECONDS", "600"))  # 10-minute DVR window
MAX_VOD_SECONDS = int(os.getenv("MAX_VOD_SECONDS", "5400"))  # cap very long VODs (free hosting)
COOKIES = os.getenv("YTDLP_COOKIES", "")  # optional cookies.txt path (helps on datacenter IPs)

VIDEO_FORMAT = (
    "bv*[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]/"
    "bv*[height<=1080]+ba/b[height<=1080]/b"
)

_ID = r"[\w-]{11}"
_URL_RE = re.compile(
    rf"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:[^#]*&)?v={_ID}|live/{_ID}|shorts/{_ID})|youtu\.be/{_ID})",
    re.IGNORECASE,
)


class DownloadError(Exception):
    pass


@dataclass
class DownloadResult:
    video_path: str
    audio_path: str
    title: str
    duration: float
    is_live: bool
    truncated: bool


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not _URL_RE.match(url):
        raise ValueError("Please enter a valid YouTube video, youtu.be, or YouTube Live URL.")
    return url


def _tail(text: str, n: int = 600) -> str:
    text = (text or "").strip()
    return text[-n:] if text else "unknown error"


def _run(cmd: list[str], timeout: int, cwd: str | None = None) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        raise DownloadError(f"Command timed out after {timeout}s: {Path(cmd[0]).name}") from exc
    except FileNotFoundError as exc:
        raise DownloadError(f"Required binary not found: {cmd[0]}") from exc
    if p.returncode != 0:
        raise DownloadError(_tail(p.stderr))
    return p.stdout


def _base_cmd() -> list[str]:
    cmd = YTDLP + ["--no-playlist", "--no-warnings"]
    if COOKIES and Path(COOKIES).exists():
        cmd += ["--cookies", COOKIES]
    return cmd


def get_info(url: str) -> dict:
    out = _run(_base_cmd() + ["--dump-single-json", "--skip-download", url], timeout=120)
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise DownloadError("Could not read video metadata from yt-dlp.") from exc


def probe_duration(path: str) -> float:
    out = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
        timeout=60,
    )
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def extract_audio(video_path: str, audio_path: str) -> None:
    """16 kHz mono PCM WAV: the ideal input for Whisper."""
    _run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", audio_path],
        timeout=900,
    )


def download(url: str, job_dir: Path) -> DownloadResult:
    job_dir.mkdir(parents=True, exist_ok=True)
    info = get_info(url)
    status = info.get("live_status")
    if status == "is_upcoming":
        raise DownloadError("This live stream has not started yet. Try again once it is live.")
    is_live = bool(info.get("is_live")) or status == "is_live"
    duration = float(info.get("duration") or 0)

    cmd = _base_cmd() + [
        "-f", VIDEO_FORMAT,
        "--merge-output-format", "mp4",
        "-o", str(job_dir / "source.%(ext)s"),
    ]
    truncated = False
    if is_live:
        # Never wait for the stream to end: grab a bounded window of the DVR buffer.
        cmd += ["--live-from-start", "--download-sections", f"*0-{LIVE_WINDOW_SECONDS}"]
        truncated, timeout = True, 1500
    elif duration > MAX_VOD_SECONDS:
        cmd += ["--download-sections", f"*0-{MAX_VOD_SECONDS}"]
        truncated, timeout = True, 1800
    else:
        timeout = 1800
    cmd.append(url)

    try:
        _run(cmd, timeout=timeout)
    except DownloadError as exc:
        hint = " (the stream may have DVR disabled)" if is_live else ""
        raise DownloadError(f"Download failed{hint}: {exc}") from exc

    candidates = [p for p in job_dir.glob("source.*") if p.suffix not in (".part", ".ytdl")]
    if not candidates:
        raise DownloadError("yt-dlp finished but no video file was produced.")
    video = max(candidates, key=lambda p: p.stat().st_size)

    audio = job_dir / "audio.wav"
    extract_audio(str(video), str(audio))
    real_duration = probe_duration(str(video)) or duration
    return DownloadResult(
        video_path=str(video),
        audio_path=str(audio),
        title=info.get("title") or "Untitled",
        duration=real_duration,
        is_live=is_live,
        truncated=truncated,
    )
