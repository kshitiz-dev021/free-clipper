"""FreeClipper API: FastAPI + BackgroundTasks, local disk storage, 2-hour auto-cleanup."""
import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import downloader
import transcriber
import video_editor
import viral_analyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("freeclipper")

JOBS_DIR = Path(os.getenv("DATA_DIR", "/tmp/freeclipper")) / "jobs"
JOB_TTL = int(os.getenv("JOB_TTL_SECONDS", str(2 * 3600)))  # delete files older than 2 hours
CLEANUP_INTERVAL = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "600"))
STAGES = {
    1: "Fetching Stream/Video",
    2: "Transcribing Audio",
    3: "AI Editor Finding 20-30s Hooks",
    4: "Translating & Styling Captions",
    5: "Rendering 9:16 Clips",
}
_STAGE_PROGRESS = {1: 5, 2: 25, 3: 45, 4: 58, 5: 60}

JOBS: dict[str, dict] = {}
LOCK = threading.RLock()
_SLOTS = threading.BoundedSemaphore(int(os.getenv("MAX_CONCURRENT_JOBS", "1")))
_RERENDER_LOCK = threading.Lock()
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_CLIP_ID = re.compile(r"^clip_\d{1,2}$")


# ---------- job store ----------

def _job_dir(job_id: str) -> Path:
    if not _JOB_ID.match(job_id):
        raise HTTPException(404, "Job not found")
    return JOBS_DIR / job_id


def _persist(job: dict) -> None:
    d = JOBS_DIR / job["id"]
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(job))
    os.replace(tmp, d / "job.json")


def _update(job_id: str, **fields) -> None:
    with LOCK:
        job = JOBS[job_id]
        job.update(fields)
        job["updated_at"] = time.time()
        _persist(job)


def _update_clip(job_id: str, clip_id: str, **fields) -> None:
    with LOCK:
        job = JOBS[job_id]
        for c in job["clips"]:
            if c["id"] == clip_id:
                c.update(fields)
        job["updated_at"] = time.time()
        _persist(job)


def _get(job_id: str) -> dict:
    _job_dir(job_id)
    with LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found (it may have expired after 2 hours).")
    return job


def _public_clip(job_id: str, c: dict) -> dict:
    base = f"/api/jobs/{job_id}/clips/{c['id']}.mp4"
    return {
        "id": c["id"], "title": c["title"], "virality_score": c["virality_score"],
        "editor_notes": c["editor_notes"], "start_time": c["start_time"], "end_time": c["end_time"],
        "duration": c["duration"], "captions": c["captions"], "status": c["status"],
        "error": c.get("error"), "revision": c["revision"],
        "video_url": f"{base}?v={c['revision']}" if c["status"] == "done" else None,
        "download_url": f"{base}?download=1" if c["status"] == "done" else None,
    }


def _public(job: dict) -> dict:
    with LOCK:
        return {
            "id": job["id"], "status": job["status"], "stage": job["stage"],
            "stage_label": STAGES.get(job["stage"], "Queued"), "progress": job["progress"],
            "error": job.get("error"), "title": job.get("title"), "is_live": job.get("is_live", False),
            "truncated": job.get("truncated", False), "options": job["options"],
            "clips": [_public_clip(job["id"], c) for c in job["clips"]],
        }


# ---------- pipeline ----------

def _set_stage(job_id: str, stage: int) -> None:
    _update(job_id, status="running", stage=stage, progress=_STAGE_PROGRESS[stage])


def run_pipeline(job_id: str) -> None:
    with _SLOTS:  # free hosts are small: process one job at a time by default
        try:
            job = JOBS[job_id]
            opts, d = job["options"], _job_dir(job_id)

            _set_stage(job_id, 1)
            dl = downloader.download(opts["url"], d)
            _update(job_id, title=dl.title, is_live=dl.is_live, truncated=dl.truncated,
                    duration=dl.duration, source_video=Path(dl.video_path).name)

            _set_stage(job_id, 2)
            tr = transcriber.transcribe(dl.audio_path)
            (d / "transcript.json").write_text(json.dumps(tr))

            _set_stage(job_id, 3)
            clips = viral_analyzer.find_viral_clips(tr, opts["target_language"], dl.duration)

            _set_stage(job_id, 4)
            for i, c in enumerate(clips, 1):
                c.update(id=f"clip_{i}", status="pending", revision=0)
                video_editor.write_ass(d / f"{c['id']}.ass", c["captions"], c["start_time"], opts["caption_style"])
            _update(job_id, clips=clips)

            _set_stage(job_id, 5)
            ok = 0
            for i, c in enumerate(clips):
                _update_clip(job_id, c["id"], status="rendering")
                try:
                    video_editor.render_clip(
                        dl.video_path, d / f"{c['id']}.mp4", d / f"{c['id']}.ass",
                        c["start_time"], c["end_time"], opts["layout"],
                    )
                    _update_clip(job_id, c["id"], status="done")
                    ok += 1
                except Exception as exc:
                    log.exception("Render failed for %s", c["id"])
                    _update_clip(job_id, c["id"], status="failed", error=str(exc))
                _update(job_id, progress=60 + int(40 * (i + 1) / len(clips)))

            if ok == 0:
                raise RuntimeError("All clips failed to render.")
            _update(job_id, status="completed", progress=100)
        except Exception as exc:
            log.exception("Job %s failed", job_id)
            _update(job_id, status="failed", error=str(exc))


# ---------- cleanup ----------

def cleanup_expired() -> int:
    removed, now = 0, time.time()
    if not JOBS_DIR.exists():
        return 0
    for d in JOBS_DIR.iterdir():
        if not d.is_dir():
            continue
        marker = d / "job.json"
        mtime = marker.stat().st_mtime if marker.exists() else d.stat().st_mtime
        with LOCK:
            active = JOBS.get(d.name, {}).get("status") in ("queued", "running")
        if now - mtime > (JOB_TTL * 3 if active else JOB_TTL):
            shutil.rmtree(d, ignore_errors=True)
            with LOCK:
                JOBS.pop(d.name, None)
            removed += 1
    if removed:
        log.info("Cleanup removed %d expired job(s)", removed)
    return removed


async def _cleanup_loop():
    while True:
        try:
            await asyncio.to_thread(cleanup_expired)
        except Exception:
            log.exception("Cleanup error")
        await asyncio.sleep(CLEANUP_INTERVAL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            log.warning("%s not found on PATH: processing will fail until it is installed", tool)
    for f in JOBS_DIR.glob("*/job.json"):  # survive restarts for jobs that have not expired
        try:
            job = json.loads(f.read_text())
            if job.get("status") in ("queued", "running"):
                job.update(status="failed", error="Server restarted during processing. Please try again.")
            JOBS[job["id"]] = job
        except Exception:
            continue
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


# ---------- API ----------

app = FastAPI(title="FreeClipper", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("FRONTEND_ORIGINS", "*").split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


class JobRequest(BaseModel):
    url: str
    target_language: str = "English"
    caption_style: Literal["translated", "bilingual"] = "translated"
    layout: Literal["crop", "blur"] = "crop"


class CaptionEdit(BaseModel):
    index: int = Field(ge=0)
    translated_text: str = Field(max_length=300)
    original_text: str | None = Field(default=None, max_length=300)


class RerenderRequest(BaseModel):
    captions: list[CaptionEdit]
    caption_style: Literal["translated", "bilingual"] | None = None
    layout: Literal["crop", "blur"] | None = None


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "groq_key": bool(os.getenv("GROQ_API_KEY")),
        "gemini_key": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "languages": viral_analyzer.LANGUAGES,
    }


@app.post("/api/jobs", status_code=202)
def create_job(req: JobRequest, background: BackgroundTasks):
    try:
        url = downloader.validate_url(req.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if req.target_language not in viral_analyzer.LANGUAGES:
        raise HTTPException(400, f"target_language must be one of {viral_analyzer.LANGUAGES}")
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id, "status": "queued", "stage": 0, "progress": 0, "clips": [], "error": None,
        "created_at": time.time(), "updated_at": time.time(),
        "options": {"url": url, "target_language": req.target_language,
                    "caption_style": req.caption_style, "layout": req.layout},
    }
    with LOCK:
        JOBS[job_id] = job
        _persist(job)
    background.add_task(run_pipeline, job_id)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _public(_get(job_id))


def _find_clip(job: dict, clip_id: str) -> dict:
    if not _CLIP_ID.match(clip_id):
        raise HTTPException(404, "Clip not found")
    for c in job["clips"]:
        if c["id"] == clip_id:
            return c
    raise HTTPException(404, "Clip not found")


@app.get("/api/jobs/{job_id}/clips/{clip_id}.mp4")
def clip_file(job_id: str, clip_id: str, download: int = 0):
    job = _get(job_id)
    clip = _find_clip(job, clip_id)
    path = _job_dir(job_id) / f"{clip['id']}.mp4"
    if clip["status"] != "done" or not path.exists():
        raise HTTPException(404, "Clip is not ready")
    if download:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", clip["title"]).strip("-")[:60] or clip["id"]
        return FileResponse(path, media_type="video/mp4", filename=f"{slug}.mp4", content_disposition_type="attachment")
    return FileResponse(path, media_type="video/mp4")


@app.post("/api/jobs/{job_id}/clips/{clip_id}/rerender")
def rerender(job_id: str, clip_id: str, body: RerenderRequest):
    """Re-burn edited captions using the already-downloaded source video (no re-download)."""
    job = _get(job_id)
    clip = _find_clip(job, clip_id)
    d = _job_dir(job_id)
    source = d / job.get("source_video", "")
    if not job.get("source_video") or not source.exists():
        raise HTTPException(410, "Source video was cleaned up. Please generate the clips again.")

    with LOCK:
        for edit in body.captions:
            if edit.index < len(clip["captions"]):
                cap = clip["captions"][edit.index]
                cap["translated_text"] = edit.translated_text.strip()
                if edit.original_text is not None:
                    cap["original_text"] = edit.original_text.strip()
        opts = job["options"]
        style = body.caption_style or opts["caption_style"]
        layout = body.layout or opts["layout"]
        captions = [dict(c) for c in clip["captions"]]

    with _RERENDER_LOCK:
        _update_clip(job_id, clip_id, status="rendering")
        try:
            video_editor.write_ass(d / f"{clip_id}.ass", captions, clip["start_time"], style)
            video_editor.render_clip(str(source), d / f"{clip_id}.mp4", d / f"{clip_id}.ass",
                                     clip["start_time"], clip["end_time"], layout)
        except Exception as exc:
            _update_clip(job_id, clip_id, status="failed", error=str(exc))
            raise HTTPException(500, f"Re-render failed: {exc}") from exc
        _update_clip(job_id, clip_id, status="done", error=None, captions=captions, revision=clip["revision"] + 1)
    return _public_clip(job_id, _find_clip(_get(job_id), clip_id))
