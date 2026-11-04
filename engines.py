"""
Kathaa video engines.

Every engine exposes the same tiny interface:  render(shot) -> local mp4 path.
Today the free engines borrow Hugging Face ZeroGPU Spaces running open-weight
models (LTX-Video, Wan 2.2). Tomorrow you swap in `SelfHostedEngine` pointing at
your own fine-tuned checkpoint on your own GPU, and nothing else in the app changes.
"""
import os
import shutil
import uuid

from gradio_client import Client, handle_file

OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

HF_TOKEN = os.getenv("HF_TOKEN") or None

# Frame sizes must be multiples of 32 for LTX-Video.
FRAMES = {
    "9:16": (704, 416),  # (height, width) – Reels, Shorts
    "16:9": (416, 704),  # YouTube, TV
    "1:1": (576, 576),   # Feed
}

NEGATIVE = "worst quality, inconsistent motion, blurry, jittery, distorted, watermark, text, extra fingers"


def _client(space: str) -> Client:
    # gradio_client renamed hf_token -> token; support both.
    try:
        return Client(space, token=HF_TOKEN, verbose=False)
    except TypeError:
        return Client(space, hf_token=HF_TOKEN, verbose=False)


def _keep(path_or_dict) -> str:
    src = path_or_dict["video"] if isinstance(path_or_dict, dict) else path_or_dict
    dst = os.path.join(OUT_DIR, f"{uuid.uuid4().hex[:12]}.mp4")
    shutil.copy(src, dst)
    return dst


class LTXEngine:
    """Lightricks LTX-Video (open weights). Text-to-video and image-to-video."""
    name = "ltx"
    label = "Swift  ·  LTX-Video"
    space = os.getenv("KATHAA_LTX_SPACE", "Lightricks/ltx-video-distilled")

    def render(self, shot: dict) -> str:
        h, w = FRAMES.get(shot.get("aspect", "9:16"), FRAMES["9:16"])
        image = shot.get("image_path")
        c = _client(self.space)
        common = dict(
            prompt=shot["prompt"],
            negative_prompt=NEGATIVE,
            input_video_filepath=None,
            height_ui=h,
            width_ui=w,
            duration_ui=float(shot.get("seconds", 3)),
            ui_frames_to_use=9,
            seed_ui=int(shot.get("seed") or 42),
            randomize_seed=shot.get("seed") is None,
            ui_guidance_scale=1,
            improve_texture_flag=True,
        )
        if image:
            video, _ = c.predict(input_image_filepath=handle_file(image), mode="image-to-video",
                                 api_name="/image_to_video", **common)
        else:
            video, _ = c.predict(input_image_filepath=None, mode="text-to-video",
                                 api_name="/text_to_video", **common)
        return _keep(video)


class WanEngine:
    """Wan 2.2 (open weights). Image-to-video only – needs a reference frame."""
    name = "wan"
    label = "Rich  ·  Wan 2.2 (needs a photo)"
    space = os.getenv("KATHAA_WAN_SPACE", "zerogpu-aoti/wan2-2-fp8da-aoti-faster")

    def render(self, shot: dict) -> str:
        if not shot.get("image_path"):
            raise ValueError("Wan needs a reference photo. Add one to this shot, or switch to Swift.")
        c = _client(self.space)
        video, _ = c.predict(
            input_image=handle_file(shot["image_path"]),
            prompt=shot["prompt"],
            steps=6,
            negative_prompt=NEGATIVE,
            duration_seconds=float(shot.get("seconds", 3.5)),
            guidance_scale=1,
            guidance_scale_2=1,
            seed=int(shot.get("seed") or 42),
            randomize_seed=shot.get("seed") is None,
            api_name="/generate_video",
        )
        return _keep(video)


class SelfHostedEngine:
    """
    Your own model. Point KATHAA_SELF_URL at a Gradio/HTTP server you run
    (e.g. Wan 2.2 or LTX fine-tuned on Indian visual styles on a rented GPU).
    Disabled until that env var is set.
    """
    name = "kathaa"
    label = "Kathaa Native  ·  your model"
    url = os.getenv("KATHAA_SELF_URL")

    def render(self, shot: dict) -> str:
        if not self.url:
            raise RuntimeError("Kathaa Native isn't switched on yet. Set KATHAA_SELF_URL.")
        c = Client(self.url, verbose=False)
        video = c.predict(shot["prompt"], shot.get("aspect", "9:16"), float(shot.get("seconds", 3)),
                          api_name="/generate")
        return _keep(video)


ENGINES = {e.name: e for e in (LTXEngine(), WanEngine(), SelfHostedEngine())}


def available():
    return [
        {"id": e.name, "label": e.label,
         "ready": not (e.name == "kathaa" and not SelfHostedEngine.url)}
        for e in ENGINES.values()
    ]


# ---------------------------------------------------------------------------
# Keyframes: a sharp still for every shot (FLUX.1-schnell, open weights).
# Animating a good still with Wan 2.2 looks far better than text-to-video.
# ---------------------------------------------------------------------------
FLUX_SPACE = os.getenv("KATHAA_FLUX_SPACE", "black-forest-labs/FLUX.1-schnell")
KEY_SIZES = {"9:16": (576, 1024), "16:9": (1024, 576), "1:1": (768, 768)}  # (w, h)
IMG_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(IMG_DIR, exist_ok=True)


def keyframe(prompt: str, aspect: str = "9:16", seed: int | None = None) -> str:
    """FLUX.1-schnell on ZeroGPU first (best quality, ~3s of GPU); free Pollinations FLUX if GPU time is out."""
    w, h = KEY_SIZES.get(aspect, KEY_SIZES["9:16"])
    full = prompt + ", highly detailed, photographic, professional cinematography, sharp focus"
    try:
        c = _client(FLUX_SPACE)
        img, _ = c.predict(prompt=full, seed=float(seed or 0), randomize_seed=seed is None,
                           width=float(w), height=float(h), num_inference_steps=4.0, api_name="/infer")
        src = img["path"] if isinstance(img, dict) else img
        dst = os.path.join(IMG_DIR, f"kf_{uuid.uuid4().hex[:12]}{os.path.splitext(src)[1] or '.webp'}")
        shutil.copy(src, dst)
        return dst
    except Exception as e:
        flux_err = e
    import random, subprocess, urllib.parse
    import httpx
    hh = int(h * 1.06)  # render taller, then crop off the free tier's corner badge
    r = None
    for attempt in range(4):  # the free tier allows one image at a time; wait and retry
        try:
            r = httpx.get("https://image.pollinations.ai/prompt/" + urllib.parse.quote(full[:1500]),
                          params={"width": w, "height": hh, "model": "flux", "nologo": "true",
                                  "seed": seed if seed is not None else random.randint(1, 10**6)},
                          timeout=120, follow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                break
        except Exception:
            r = None
        import time
        time.sleep(6 + attempt * 6)
    if r is None or r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"No frame (image service busy): {getattr(r, 'status_code', 'timeout')}")
    raw = os.path.join(IMG_DIR, f"raw_{uuid.uuid4().hex[:8]}.jpg")
    with open(raw, "wb") as f:
        f.write(r.content)
    dst = os.path.join(IMG_DIR, f"kf_{uuid.uuid4().hex[:12]}.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-vf", f"crop=iw:ih-{hh-h}:0:0", "-q:v", "2", dst], check=True)
    os.remove(raw)
    return dst


def animate(image_path: str, motion: str, seconds: float = 5.0) -> str:
    """Wan 2.2 image-to-video. Returns a local mp4."""
    return ENGINES["wan"].render({"image_path": image_path, "prompt": motion, "seconds": seconds})
