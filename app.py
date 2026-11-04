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
import film
import storyteller
import voice

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


class KeyIn(BaseModel):
    prompt: str
    aspect: str = "9:16"


class FilmShot(BaseModel):
    prompt: str
    motion: str = ""
    line: str = ""
    image_id: str | None = None


class FilmIn(BaseModel):
    title: str = "Untitled"
    language: str = "English"
    aspect: str = "9:16"
    seconds: float = 5
    captions: bool = True
    shots: list[FilmShot]


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


def _gpu_msg(e: Exception) -> str:
    m = str(e)
    if "ZeroGPU quota" in m or "exceeded your GPU quota" in m:
        return "free GPU minutes used up for now"
    return m[:200]


def _key_job(job_id: str, prompt: str, aspect: str):
    job = JOBS[job_id]
    with RENDER_LOCK:
        job.update(state="rolling")
        try:
            path = engines.keyframe(prompt, aspect)
            job.update(state="done", image_id=os.path.basename(path), image=f"/uploads/{os.path.basename(path)}")
        except Exception as e:
            job.update(state="failed", error=_gpu_msg(e))


@app.post("/api/keyframe")
def make_keyframe(body: KeyIn):
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"state": "queued", "created": time.time()}
    threading.Thread(target=_key_job, args=(job_id, body.prompt, body.aspect), daemon=True).start()
    return {"job_id": job_id}


def _film_job(job_id: str, req: dict):
    job = JOBS[job_id]
    aspect, n = req["aspect"], len(req["shots"])
    job["shots"] = [{} for _ in range(n)]
    segments = []
    with RENDER_LOCK:
        job["state"] = "rolling"
        try:
            for i, sh in enumerate(req["shots"]):
                rec = job["shots"][i]
                # 1. keyframe
                img = os.path.join(UPLOADS, os.path.basename(sh["image_id"])) if sh.get("image_id") else None
                if not img or not os.path.exists(img):
                    job["stage"] = f"Framing shot {i+1} of {n}"
                    try:
                        img = engines.keyframe(sh["prompt"], aspect)
                    except Exception as e:
                        rec["mode"], rec["note"] = "skipped", _gpu_msg(e)
                        continue  # keep the film going without this shot
                rec["image"] = f"/uploads/{os.path.basename(img)}"
                # 2. animate (falls back to a slow push-in if GPU time runs out)
                job["stage"] = f"Animating shot {i+1} of {n}"
                motion = sh.get("motion") or "subtle natural movement, slow cinematic camera push-in"
                try:
                    clip = engines.animate(img, motion, req["seconds"])
                    rec["mode"] = "animated"
                except Exception as e:
                    rec["mode"] = "still"
                    rec["note"] = _gpu_msg(e)
                    clip = film.kenburns(img, req["seconds"], aspect)
                rec["clip"] = f"/outputs/{os.path.basename(clip)}" if rec["mode"] == "animated" else None
                # 3. voice
                job["stage"] = f"Recording voice {i+1} of {n}"
                vo = voice.speak(sh.get("line", ""), req["language"])
                rec["voice"] = bool(vo)
                # 4. cut the shot
                job["stage"] = f"Editing shot {i+1} of {n}"
                segments.append(film.segment(clip, vo, sh.get("line", "") if req["captions"] else "", aspect))
                job["done_shots"] = i + 1
            if not segments:
                raise RuntimeError("No shot could be framed right now. Try again in a few minutes.")
            job["stage"] = "Final cut"
            out = film.assemble(segments)
            job.update(state="done", stage="Ready", video=f"/outputs/{os.path.basename(out)}",
                       seconds=round(film.duration(out), 1))
        except Exception as e:
            job.update(state="failed", error=_gpu_msg(e))


@app.post("/api/film")
def make_film(body: FilmIn):
    if not body.shots:
        raise HTTPException(400, "No shots to film.")
    req = body.model_dump()
    req["shots"] = req["shots"][:8]
    req["seconds"] = max(2.0, min(float(req["seconds"]), 5.0))
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"state": "queued", "created": time.time(), "kind": "film", "stage": "In the queue"}
    threading.Thread(target=_film_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


app.mount("/outputs", StaticFiles(directory=engines.OUT_DIR), name="outputs")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/")
def home():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/writer-check")
def writer_check():
    """Diagnostics: which Gemini models the key sees and how a tiny call behaves on each."""
    import httpx as _h
    out = {"models": storyteller._models(), "tests": {}}
    for m in out["models"]:
        t = time.time()
        try:
            r = _h.post(storyteller.URL.format(m=m), params={"key": storyteller.GEMINI_KEY},
                        json={"contents": [{"parts": [{"text": "Say ok"}]}]}, timeout=15)
            out["tests"][m] = {"status": r.status_code, "secs": round(time.time() - t, 1), "body": r.text[:160]}
        except Exception as e:
            out["tests"][m] = {"error": str(e)[:80], "secs": round(time.time() - t, 1)}
    return out
