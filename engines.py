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
