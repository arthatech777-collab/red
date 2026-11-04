---
title: Kathaa
emoji: 🎬
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Kathaa (कथा): stories into film

Kathaa turns a one-line idea, written in any Indian language or English, into a finished short film:
**Gemini writes the story, FLUX frames every shot, Wan 2.2 animates each frame, a neural voice narrates in your language, and ffmpeg cuts it all into one 30 to 60 second film with captions.**
It's built for creators, ad agencies, and brands making regional and international content.

## How it works (all free)

| Part | What does it | Cost |
|---|---|---|
| Writer's room | Gemini Flash (free tier) reads Hindi/Kannada/Tamil/Telugu/… and writes English shot prompts plus voice-over lines in your chosen language | Free |
| Keyframes | FLUX.1-schnell (open weights) on ZeroGPU: a sharp still for every shot | Free |
| Voice-over | Edge neural voices (Kannada, Hindi, Tamil, Telugu, Malayalam, Marathi, Bengali, Gujarati, English…) with gTTS fallback | Free |
| Editor | ffmpeg: timing to voice, captions with proper Indic shaping, fades, final cut | Free |
| Swift engine | LTX-Video (open weights) on Hugging Face ZeroGPU: text-to-video and photo-to-video | Free (daily GPU minutes) |
| Rich engine | Wan 2.2 (open weights) on ZeroGPU: photo-to-video, higher quality | Free (daily GPU minutes) |
| Kathaa Native | Your own fine-tuned model on your own GPU (switch on later with `KATHAA_SELF_URL`) | Later |
| Hosting | Render free web service (Docker) | Free |

## 1. Get your two free keys (5 minutes)
1. **Gemini key**: https://aistudio.google.com/apikey, then Create API key.
2. **Hugging Face token**: make a free account, then go to https://huggingface.co/settings/tokens and create a new token (type: Read).
   Without it you share an anonymous GPU quota that runs out fast.

## 2. Run it on your computer
```bash
cd kathaa
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then paste your two keys into .env
uvicorn app:app --port 7860
```
Open http://localhost:7860

## 3. Put it online free (Render)
Hugging Face now requires PRO for Docker Spaces, so Kathaa deploys free on Render (no card needed).
1. Open https://render.com/deploy?repo=https://github.com/arthatech777-collab/red
2. Sign in with GitHub and allow Render to see the `red` repo.
3. Paste your `GEMINI_API_KEY` and `HF_TOKEN` when asked, then click **Deploy Blueprint**.
4. In about 5 minutes your studio is live at `https://kathaa-xxxx.onrender.com`.

Free Render instances sleep after 15 minutes idle (the first visit then takes about a minute to wake), and generated clips are cleared when the instance restarts. Download the ones you like.

## Free-tier limits
- ZeroGPU gives each free account a few minutes of GPU per day, enough for roughly 10 to 30 short clips. A Hugging Face PRO account ($9/mo) gives much more, when you're ready.
- Clips are 2 to 5 seconds at about 704×416. That's the prototype; quality goes up with your own GPU.
- Public Spaces can change or go down. Engines are one class each in `engines.py`, so swapping a Space name is one env var (`KATHAA_LTX_SPACE`, `KATHAA_WAN_SPACE`).

## Files
- `app.py`: API server (story, upload, render jobs, status) and serves the UI
- `storyteller.py`: Gemini prompt and the look presets (Cinematic, Ad film, Filmi song, Documentary, Folk art, Anime)
- `engines.py`: video engines with one shared `render(shot)` interface
- `static/`: hand-built UI (no framework): `index.html`, `style.css`, `app.js`

## Roadmap to "our own model"
1. **Now**: free prototype, collect real prompts and feedback.
2. **Phase 2**: rent a GPU (RunPod/Vast/E2E Networks in India, about ₹60 to ₹150/hr). Self-host Wan 2.2 and point `KATHAA_SELF_URL` at it.
3. **Phase 3**: LoRA fine-tune Wan/LTX on licensed Indian footage (festivals, regional architecture, folk-art styles, Indian faces and skin tones). That's the Kathaa Native model.
4. Then add accounts, credits/payments (Razorpay), Indian-language TTS voice-over, music, and stitching shots into one film with ffmpeg.
