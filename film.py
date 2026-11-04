"""
Kathaa's editor: turns shots (clips or stills) + voice-over into one finished film.
Pure ffmpeg, light enough for a free 0.1-CPU server.
"""
import os
import subprocess
import uuid

OUT = os.path.join(os.path.dirname(__file__), "outputs")
TMP = os.path.join(os.path.dirname(__file__), "outputs", "tmp")
os.makedirs(TMP, exist_ok=True)

SIZES = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (960, 960)}  # (w, h)
FPS = 24
FADE = 0.35


def _run(cmd: list[str]):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg: " + p.stderr[-600:])


def duration(path: str) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def kenburns(image: str, seconds: float, aspect: str) -> str:
    """Free fallback when GPU time runs out: a slow cinematic push-in on the keyframe."""
    w, h = SIZES.get(aspect, SIZES["9:16"])
    frames = int(seconds * FPS)
    out = os.path.join(TMP, f"kb_{uuid.uuid4().hex[:8]}.mp4")
    vf = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},"
          f"zoompan=z='min(zoom+0.0009,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}")
    _run(["ffmpeg", "-y", "-loop", "1", "-i", image, "-vf", vf, "-t", f"{seconds:.2f}",
          "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out])
    return out


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}"


def segment(video: str, voice: str | None, line: str, aspect: str, captions: bool = True) -> str:
    """One shot: framed, timed to its voice-over, captioned, with soft fades."""
    w, h = SIZES.get(aspect, SIZES["9:16"])
    vd = max(duration(video), 0.5)
    ad = duration(voice) if voice else 0.0
    target = max(vd, ad + 0.7) if ad else vd
    slow = min(target / vd, 1.5)
    pad = max(0.0, target - vd * slow)

    vf = [f"setpts=PTS*{slow:.4f}", f"fps={FPS}",
          f"scale={w}:{h}:force_original_aspect_ratio=increase", f"crop={w}:{h}", "setsar=1"]
    if pad > 0.05:
        vf.append(f"tpad=stop_mode=clone:stop_duration={pad:.2f}")
    if captions and line.strip():
        ass = os.path.join(TMP, f"c_{uuid.uuid4().hex[:8]}.ass")
        fs = int(h * (0.034 if aspect == "9:16" else 0.05))
        mv = int(h * (0.11 if aspect == "9:16" else 0.07))
        with open(ass, "w", encoding="utf-8") as f:
            f.write(
                "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\n"
                f"PlayResX: {w}\nPlayResY: {h}\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
                "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
                "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                f"Style: Cap,Noto Sans,{fs},&H00F2F2F2,&H00F2F2F2,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,"
                f"{max(2, fs//14)},1,2,{int(w*0.08)},{int(w*0.08)},{mv},1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                f"Dialogue: 0,{_ass_time(0.25)},{_ass_time(target - 0.3)},Cap,,0,0,0,,{line.strip()}\n")
        vf.append(f"ass={ass}:shaping=complex")
    vf += [f"fade=t=in:st=0:d={FADE}", f"fade=t=out:st={target-FADE:.2f}:d={FADE}", "format=yuv420p"]

    out = os.path.join(TMP, f"seg_{uuid.uuid4().hex[:8]}.mp4")
    cmd = ["ffmpeg", "-y", "-i", video]
    if voice:
        cmd += ["-i", voice]
        af = f"adelay=350|350,apad,atrim=0:{target:.2f},afade=t=out:st={target-FADE:.2f}:d={FADE}"
        amap = ["-map", "0:v", "-map", "1:a", "-af", af]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        amap = ["-map", "0:v", "-map", "1:a"]
    cmd += ["-vf", ",".join(vf), *amap, "-t", f"{target:.2f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", out]
    _run(cmd)
    return out


def assemble(segments: list[str]) -> str:
    lst = os.path.join(TMP, f"list_{uuid.uuid4().hex[:8]}.txt")
    with open(lst, "w") as f:
        for s in segments:
            f.write(f"file '{s}'\n")
    out = os.path.join(OUT, f"film_{uuid.uuid4().hex[:10]}.mp4")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    return out
