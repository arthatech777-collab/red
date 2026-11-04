"""Kathaa: stories into film. FastAPI server. Run:  uvicorn app:app --port 7860"""
import os
import shutil

# Load .env without extra dependencies (must run before engines/storyteller read env).
_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env):
    for _l in open(_env, encoding="utf-8"):
        if "=" in _l and not _l.lstrip().startswith("#"):
            _k, _v = _l.strip().split("=", 1)
            if _v and _k not in os.environ:
                os.environ[_k] = _v

import threading
import time
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import engines
import storyteller

app = FastAPI(title="Kathaa")
BASE = os.path.dirname(__file__)
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

JOBS: dict[str, dict] = {}
# ZeroGPU Spaces queue per user anyway; one render at a time keeps quota predictable.
RENDER_LOCK = threading.Semaphore(int(os.getenv("KATHAA_PARALLEL", "1")))


class StoryIn(BaseModel):
    idea: str
    language: str = "English"
    look: str = "cinematic"
    shots: int = 3


class ShotIn(BaseModel):
    prompt: str
    engine: str = "ltx"
    aspect: str = "9:16"
    seconds: float = 3
    image_id: str | None = None
    seed: int | None = None


@app.get("/api/status")
def status():
    return {
        "writer": "gemini" if storyteller.GEMINI_KEY else "offline",
        "hf_token": bool(engines.HF_TOKEN),
        "engines": engines.available(),
        "looks": list(storyteller.LOOKS),
    }


@app.post("/api/story")
def story(body: StoryIn):
    if not body.idea.strip():
        raise HTTPException(400, "Tell me the idea first.")
    try:
        return storyteller.write_shots(body.idea, body.language, body.look, body.shots)
    except Exception as e:  # keep the desk usable even if the writer hiccups
        out = storyteller._offline(body.idea, storyteller.LOOKS.get(body.look, ""), body.shots)
        out["warning"] = f"Writer unavailable ({e}); used a plain shot list."
        return out


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(400, "Photos only: png, jpg or webp.")
    fid = uuid.uuid4().hex[:12] + ext
    with open(os.path.join(UPLOADS, fid), "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"image_id": fid}


def _run(job_id: str, shot: dict, engine_id: str):
    job = JOBS[job_id]
    with RENDER_LOCK:
        job.update(state="rolling", started=time.time())
        try:
            path = engines.ENGINES[engine_id].render(shot)
            job.update(state="done", video=f"/outputs/{os.path.basename(path)}")
        except Exception as e:
            msg = str(e)
            if "ZeroGPU quota" in msg:
                msg = ("Today's free GPU minutes are used up. Add a free Hugging Face token "
                       "for more, or try again later.")
            job.update(state="failed", error=msg[:400])


@app.post("/api/render")
def render(body: ShotIn):
    if body.engine not in engines.ENGINES:
        raise HTTPException(400, "Unknown engine.")
    shot = body.model_dump()
    if body.image_id:
        p = os.path.join(UPLOADS, os.path.basename(body.image_id))
        if not os.path.exists(p):
            raise HTTPException(400, "That photo is gone; upload it again.")
        shot["image_path"] = p
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"state": "queued", "created": time.time()}
    threading.Thread(target=_run, args=(job_id, shot, body.engine), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/render/{job_id}")
def render_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "No such take.")
    return JOBS[job_id]


app.mount("/outputs", StaticFiles(directory=engines.OUT_DIR), name="outputs")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/")
def home():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/writer-check")
def writer_check():
    """Diagnostics: which Gemini models the key sees and how a tiny call behaves."""
    import httpx as _h
    out = {"models": storyteller._models()}
    t = time.time()
    try:
        r = _h.post(storyteller.URL.format(m=out["models"][0]), params={"key": storyteller.GEMINI_KEY},
                    json={"contents": [{"parts": [{"text": "Say ok"}]}]}, timeout=60)
        out["first"] = {"status": r.status_code, "secs": round(time.time() - t, 1), "body": r.text[:300]}
    except Exception as e:
        out["first"] = {"error": str(e), "secs": round(time.time() - t, 1)}
    return out
