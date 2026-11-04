"""
Voice-over in Indian and world languages, free.
Primary: Microsoft Edge neural voices (edge-tts). Fallback: Google Translate TTS (gTTS).
"""
import asyncio
import os
import uuid

OUT = os.path.join(os.path.dirname(__file__), "outputs")

VOICES = {  # language -> (edge voice, gTTS code)
    "English": ("en-IN-NeerjaNeural", "en"), "Hinglish": ("hi-IN-SwaraNeural", "hi"),
    "Hindi": ("hi-IN-SwaraNeural", "hi"), "Kannada": ("kn-IN-SapnaNeural", "kn"),
    "Tamil": ("ta-IN-PallaviNeural", "ta"), "Telugu": ("te-IN-ShrutiNeural", "te"),
    "Malayalam": ("ml-IN-SobhanaNeural", "ml"), "Marathi": ("mr-IN-AarohiNeural", "mr"),
    "Bengali": ("bn-IN-TanishaaNeural", "bn"), "Gujarati": ("gu-IN-DhwaniNeural", "gu"),
    "Punjabi": (None, "pa"), "Odia": (None, "or"),
    "Spanish": ("es-ES-ElviraNeural", "es"), "Arabic": ("ar-AE-FatimaNeural", "ar"),
    "French": ("fr-FR-DeniseNeural", "fr"),
}


def speak(text: str, language: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    edge_voice, gcode = VOICES.get(language, VOICES["English"])
    path = os.path.join(OUT, f"vo_{uuid.uuid4().hex[:10]}.mp3")
    if edge_voice:
        try:
            import edge_tts
            asyncio.run(edge_tts.Communicate(text, edge_voice, rate="-5%").save(path))
            if os.path.getsize(path) > 1000:
                return path
        except Exception:
            pass
    try:
        from gtts import gTTS
        gTTS(text, lang=gcode).save(path)
        if os.path.getsize(path) > 1000:
            return path
    except Exception:
        pass
    return None
