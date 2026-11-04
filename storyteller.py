"""
The Kathaa "writer's room": turns a one-line idea (in any Indian language or English)
into a shot list that video models understand. Runs on Gemini's free tier.
If no key is set it falls back to a simple offline template so the app still works.
"""
import json
import time
import os

import httpx

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
PREFERRED = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-latest"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"

LOOKS = {
    "cinematic": "anamorphic cinematic film look, shallow depth of field, natural film grain, motivated lighting",
    "ad-film": "premium Indian TV commercial look, clean bright key light, hero product framing, crisp detail",
    "filmi": "vibrant Bollywood song-sequence look, saturated colour, sweeping crane moves, festive energy",
    "documentary": "handheld documentary realism, available light, honest textures, observational framing",
    "folk": "animated in the style of Indian folk art (Madhubani, Kalamkari, Warli), flat patterned colour, hand-drawn line",
    "anime": "hand-painted 2D anime style, soft cel shading, painterly backgrounds",
}

SYSTEM = """You are the head writer and cinematographer at Kathaa, a studio that makes short videos
for creators, ad agencies and brands across India and the world.

Turn the client's idea into a tight shot list for a short film. Rules:
- The client may write in any language (Hindi, Kannada, Tamil, Telugu, Marathi, Bengali, Malayalam,
  Gujarati, Punjabi, Odia, English, Hinglish...). Understand it fully.
- The shots must tell ONE continuous story with a beginning, middle and end, and keep the same characters
  (describe each recurring person identically in every shot: age, face, hair, clothing, jewellery).
- "prompt" (English) describes the opening FRAME of the shot as a photograph: subject, pose, setting,
  composition, lens, light, colour, mood. Rich, specific, 50-80 words. Respect real Indian culture accurately:
  clothing, architecture, food, festivals, skin tones, regional detail. No stereotypes. No text or logos in frame.
- "motion" (English) is ONE sentence for what moves during the 5 seconds and how the camera moves
  (e.g. "She turns toward the sunrise as her dupatta lifts in the breeze; slow dolly in").
- "line" is the voice-over for that shot in the client's OUTPUT LANGUAGE, natural and idiomatic,
  at most 12 words so it can be spoken in about 4 seconds. The lines together read as one narration.
- "camera" is a short label like "Wide, 24mm, slow dolly in".
Return ONLY JSON: {"title": str, "logline": str, "shots": [{"prompt": str, "motion": str, "line": str, "camera": str}]}"""


def write_shots(idea: str, language: str, look: str, shots: int = 3) -> dict:
    shots = max(1, min(int(shots), 8))
    style = LOOKS.get(look, LOOKS["cinematic"])
    if not GEMINI_KEY:
        return _offline(idea, style, shots)

    user = (f"IDEA: {idea}\nOUTPUT LANGUAGE for lines: {language}\nVISUAL LOOK: {style}\n"
            f"NUMBER OF SHOTS: {shots}")
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
    }
    r, last_err = None, None
    for attempt in range(2):  # free models spike; one more lap after a pause
        for model in _models():
            for cfg in ({"thinkingConfig": {"thinkingLevel": "low"}}, {}):
                b = dict(body, generationConfig={**body["generationConfig"], **cfg})
                try:
                    r = httpx.post(URL.format(m=model), params={"key": GEMINI_KEY}, json=b, timeout=35)
                except httpx.TimeoutException as e:
                    last_err, r = e, None
                    break  # busy model, next one
                if r.status_code == 400 and cfg:
                    continue  # model doesn't take thinkingLevel; retry plain
                break
            if r is not None and r.status_code in (200, 401, 403):
                break
        if r is not None and r.status_code in (200, 401, 403):
            break
        time.sleep(3)
    if r is None:
        raise RuntimeError(f"Gemini timed out ({last_err})")
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = r.text
        raise RuntimeError(f"Gemini {r.status_code}: {msg[:200]}")
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(text)
    data["shots"] = data.get("shots", [])[:shots]
    return data


_MODEL_CACHE: list[str] = []


def _models() -> list[str]:
    """Configured model first, then whatever free Flash models this key can see."""
    if _MODEL_CACHE:
        return _MODEL_CACHE
    found = []
    try:
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models",
                      params={"key": GEMINI_KEY, "pageSize": 200}, timeout=20)
        for m in r.json().get("models", []):
            name = m["name"].split("/", 1)[-1]
            if ("generateContent" in m.get("supportedGenerationMethods", [])
                    and "flash" in name and not any(x in name for x in ("image", "tts", "live", "omni", "audio"))):
                found.append(name)
    except Exception:
        pass
    full = sorted([n for n in found if "lite" not in n], key=lambda n: ("preview" in n or "exp" in n, n))
    lite = sorted([n for n in found if "lite" in n], key=lambda n: ("preview" in n or "exp" in n, n))
    order = []
    for n in [GEMINI_MODEL] + PREFERRED[:2] + lite[:2] + PREFERRED[2:] + full + lite[2:]:
        if n not in order:
            order.append(n)
    _MODEL_CACHE.extend(order[:8])
    return _MODEL_CACHE


def _offline(idea: str, style: str, n: int) -> dict:
    beats = ["establishing wide shot", "medium shot following the subject", "close-up detail, emotional beat",
             "slow push-in", "over-the-shoulder reveal", "final wide pull-back"]
    return {
        "title": idea[:48],
        "logline": idea,
        "shots": [{"prompt": f"{idea}. {beats[i % len(beats)]}, {style}.", "motion": "subtle natural movement, slow cinematic camera push-in",
                   "line": "", "camera": beats[i % len(beats)]} for i in range(n)],
        "offline": True,
    }
