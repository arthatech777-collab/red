"""
The Kathaa "writer's room": turns a one-line idea (in any Indian language or English)
into a shot list that video models understand. Runs on Gemini's free tier.
If no key is set it falls back to a simple offline template so the app still works.
"""
import json
import os

import httpx

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
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

Turn the client's idea into a tight shot list. Rules:
- The client may write in any language (Hindi, Kannada, Tamil, Telugu, Marathi, Bengali, Malayalam,
  Gujarati, Punjabi, Odia, English, Hinglish...). Understand it fully.
- Each shot's "prompt" MUST be in English (video models only read English) and be one vivid paragraph:
  subject, action, setting, camera move, lens, light, mood. Respect real Indian culture accurately:
  clothing, architecture, food, festivals, skin tones, regional detail. No stereotypes.
- Each shot's "line" is the voice-over/caption for that shot, written in the client's chosen OUTPUT LANGUAGE,
  natural and idiomatic (not a literal translation).
- 2 to 3 seconds of action per shot. Never ask for on-screen text or logos.
Return ONLY JSON: {"title": str, "logline": str, "shots": [{"prompt": str, "line": str, "camera": str}]}"""


def write_shots(idea: str, language: str, look: str, shots: int = 3) -> dict:
    shots = max(1, min(int(shots), 6))
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
    r = httpx.post(URL.format(m=GEMINI_MODEL), params={"key": GEMINI_KEY}, json=body, timeout=60)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(text)
    data["shots"] = data.get("shots", [])[:shots]
    return data


def _offline(idea: str, style: str, n: int) -> dict:
    beats = ["establishing wide shot", "medium shot following the subject", "close-up detail, emotional beat",
             "slow push-in", "over-the-shoulder reveal", "final wide pull-back"]
    return {
        "title": idea[:48],
        "logline": idea,
        "shots": [{"prompt": f"{idea}. {beats[i]}, {style}.", "line": "", "camera": beats[i]} for i in range(n)],
        "offline": True,
    }
