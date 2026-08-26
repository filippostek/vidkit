#!/usr/bin/env python3
"""
vidkit render engine
Raw screen recording  ->  branded 9:16 short with karaoke captions.

Pipeline:
  1. probe source
  2. (optional) auto-editor silence removal
  3. (optional) Kokoro TTS voiceover from script
  4. (optional) WhisperX / whisper.cpp word-level transcript
  5. build styled ASS karaoke captions
  6. FFmpeg: crop/pad to 1080x1920, brand bar, hook card, captions, audio mix
  7. emit MP4 + thumbnail + sidecar JSON

Zero paid dependencies. Everything runs on CPU.

Usage:
  render.py --input raw.mp4 --out out.mp4 --hook "..." --script "..." 
  render.py --input raw.mp4 --out out.mp4 --srt captions.srt --no-tts
  render.py --selftest
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import cinema
    HAVE_CINEMA = True
except Exception:
    HAVE_CINEMA = False
try:
    import styles as stylelib
    HAVE_STYLES = True
except Exception:
    HAVE_STYLES = False

# ----------------------------------------------------------------------------
# BRAND (edit here or pass --brand nexalead|armonia)
# ----------------------------------------------------------------------------
BRANDS = {
    "nexalead": {
        "_key": "nexalead",
        "name": "Nexalead",
        "url": "nexalead.ai",
        "accent": "00E5A0",      # ASS colours are BGR, converted below
        "accent_hex": "#00E5A0",
        "bg": "0A0A0F",
        "text": "FFFFFF",
        "font": "Poppins",
        "font_bold": "Poppins",
        "caption_fill": "FFFFFF",
        "caption_highlight": "00E5A0",
    },
    "armonia": {
        "_key": "armonia",
        "name": "Armonía",
        "url": "armoniaairbnb.com",
        "accent": "C8B07A",
        "accent_hex": "#C8B07A",
        "bg": "080808",
        "text": "FFFFFF",
        "font": "Poppins",
        "font_bold": "Poppins",
        "caption_fill": "FFFFFF",
        "caption_highlight": "C8B07A",
    },
}

W, H = 1080, 1920            # target canvas
SAFE_TOP = 260               # keep clear of platform UI
SAFE_BOTTOM = 420
CAPTION_Y = 1290             # caption baseline
HOOK_MARGIN = 148            # hook / stat card distance from top
FPS = 30


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def run(cmd, check=True, capture=True):
    """Run a command, return (rc, stdout, stderr)."""
    p = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        capture_output=capture,
        text=True,
    )
    if check and p.returncode != 0:
        sys.stderr.write(f"\n[FAIL] {cmd}\n{p.stderr}\n")
        raise SystemExit(p.returncode)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def have(binary):
    return shutil.which(binary) is not None


def hex_to_ass(hex_rgb, alpha="00"):
    """ASS uses &HAABBGGRR — reverse the RGB byte order."""
    hex_rgb = hex_rgb.lstrip("#")
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H{alpha}{b}{g}{r}"


def probe(path):
    rc, out, _ = run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)]
    )
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    dur = float(data["format"].get("duration", 0) or 0)
    return {
        "duration": dur,
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "has_audio": a is not None,
        "vcodec": v["codec_name"] if v else None,
    }


def ass_escape(s):
    return (s or "").replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def ts(seconds):
    """seconds -> ASS 0:00:00.00"""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# ----------------------------------------------------------------------------
# step: silence removal
# ----------------------------------------------------------------------------
def auto_edit(src, workdir, threshold="0.04", margin="0.25sec"):
    """Strip silences with auto-editor if installed. Returns path."""
    if not have("auto-editor"):
        print("[skip] auto-editor not installed — using raw timing")
        return src
    out = workdir / "tightened.mp4"
    rc, _, err = run(
        ["auto-editor", str(src),
         "--edit", f"audio:threshold={threshold}",
         "--margin", margin,
         "--no-open",
         "-o", str(out)],
        check=False,
    )
    if rc != 0 or not out.exists():
        print(f"[warn] auto-editor failed, continuing with raw: {err[:200]}")
        return src
    print(f"[ok] auto-editor: {probe(src)['duration']:.1f}s -> {probe(out)['duration']:.1f}s")
    return out


# ----------------------------------------------------------------------------
# step: TTS
# ----------------------------------------------------------------------------
def synth_voice(script, workdir, voice="af_heart"):
    """
    Kokoro-82M (Apache-2.0) -> wav. Falls back to piper, then silence.
    Returns (wav_path | None, engine_name)
    """
    wav = workdir / "voice.wav"

    # 1) Kokoro via python package
    try:
        import importlib
        importlib.import_module("kokoro")
        code = textwrap.dedent(f"""
            import soundfile as sf, numpy as np
            from kokoro import KPipeline
            p = KPipeline(lang_code='a')
            chunks = []
            for _, _, audio in p({json.dumps(script)}, voice={json.dumps(voice)}, speed=1.0):
                chunks.append(audio)
            sf.write({json.dumps(str(wav))}, np.concatenate(chunks), 24000)
        """)
        rc, _, err = run([sys.executable, "-c", code], check=False)
        if rc == 0 and wav.exists():
            print("[ok] TTS: kokoro-82M")
            return wav, "kokoro"
        print(f"[warn] kokoro failed: {err[:200]}")
    except Exception:
        pass

    # 2) piper CLI
    if have("piper"):
        model = os.environ.get("PIPER_MODEL", "")
        if model:
            rc, _, _ = run(
                f'echo {json.dumps(script)} | piper --model {model} --output_file {wav}',
                check=False,
            )
            if rc == 0 and wav.exists():
                print("[ok] TTS: piper")
                return wav, "piper"

    print("[skip] no TTS engine available — video will use source audio only")
    return None, "none"


# ----------------------------------------------------------------------------
# step: transcription -> word timings
# ----------------------------------------------------------------------------
def transcribe_words(audio, workdir, model="base"):
    """
    Returns list of {word, start, end}.
    Tries faster-whisper (word_timestamps) then whisper.cpp, else [].
    """
    # 1) faster-whisper
    try:
        import importlib
        importlib.import_module("faster_whisper")
        out_json = workdir / "words.json"
        code = textwrap.dedent(f"""
            import json
            from faster_whisper import WhisperModel
            m = WhisperModel({json.dumps(model)}, device="cpu", compute_type="int8")
            segs, _ = m.transcribe({json.dumps(str(audio))}, word_timestamps=True, vad_filter=True)
            words = []
            for s in segs:
                for w in (s.words or []):
                    words.append({{"word": w.word.strip(), "start": w.start, "end": w.end}})
            open({json.dumps(str(out_json))}, "w").write(json.dumps(words))
        """)
        rc, _, err = run([sys.executable, "-c", code], check=False)
        if rc == 0 and out_json.exists():
            words = json.loads(out_json.read_text())
            print(f"[ok] transcript: faster-whisper ({len(words)} words)")
            return words
        print(f"[warn] faster-whisper failed: {err[:200]}")
    except Exception:
        pass

    # 2) whisper.cpp
    if have("whisper-cli") or have("main"):
        binary = "whisper-cli" if have("whisper-cli") else "main"
        mdl = os.environ.get("WHISPER_CPP_MODEL", "")
        if mdl:
            base = workdir / "wcpp"
            rc, _, _ = run(
                [binary, "-m", mdl, "-f", str(audio), "-ml", "1",
                 "-oj", "-of", str(base)],
                check=False,
            )
            j = Path(str(base) + ".json")
            if rc == 0 and j.exists():
                raw = json.loads(j.read_text())
                words = [
                    {"word": t["text"].strip(),
                     "start": t["offsets"]["from"] / 1000.0,
                     "end": t["offsets"]["to"] / 1000.0}
                    for t in raw.get("transcription", [])
                    if t["text"].strip()
                ]
                print(f"[ok] transcript: whisper.cpp ({len(words)} words)")
                return words

    print("[skip] no transcriber available — captions from --script fallback")
    return []


def fake_words_from_script(script, duration):
    """Evenly distribute script words across duration when no ASR exists."""
    toks = [w for w in re.split(r"\s+", script.strip()) if w]
    if not toks or duration <= 0:
        return []
    per = duration / len(toks)
    return [
        {"word": w, "start": i * per, "end": (i + 1) * per}
        for i, w in enumerate(toks)
    ]


# ----------------------------------------------------------------------------
# step: build ASS karaoke captions
# ----------------------------------------------------------------------------
def build_ass(words, brand, out_path, group=3, hook=None, hook_dur=1.6,
              stat_lines=None):
    """
    Karaoke captions: words grouped in threes, active word highlighted.
    Optional opening hook card and closing stat card.
    """
    b = brand
    fill = hex_to_ass(b["caption_fill"])
    hi = hex_to_ass(b["caption_highlight"])
    accent = hex_to_ass(b["accent"])
    outline = hex_to_ass("000000")

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{b['font']},74,{fill},{fill},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,80,80,{H - CAPTION_Y},1
Style: Hook,{b['font']},88,{hex_to_ass(b['text'])},{fill},{hex_to_ass(b['bg'],'0A')},{hex_to_ass(b['bg'],'0A')},-1,0,0,0,100,100,0,0,3,30,0,8,80,80,{HOOK_MARGIN},1
Style: Stat,{b['font']},80,{accent},{fill},{outline},&HC0000000,-1,0,0,0,100,100,1,0,1,7,4,8,80,80,{HOOK_MARGIN},1
Style: Tag,{b['font']},40,{accent},{fill},{outline},&H00000000,-1,0,0,0,100,100,2,0,1,3,0,2,60,60,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []

    # opening hook card
    if hook:
        lines.append(
            f"Dialogue: 1,{ts(0)},{ts(hook_dur)},Hook,,0,0,0,,"
            f"{{\\fad(150,250)\\blur2}}{ass_escape(hook)}"
        )

    # karaoke word groups
    for i in range(0, len(words), group):
        chunk = words[i:i + group]
        if not chunk:
            continue
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        if end <= start:
            end = start + 0.4

        for j, w in enumerate(chunk):
            parts = []
            for k, ww in enumerate(chunk):
                txt = ass_escape(ww["word"])
                if k == j:
                    parts.append(f"{{\\c{hi}\\fscx108\\fscy108}}{txt}{{\\c{fill}\\fscx100\\fscy100}}")
                else:
                    parts.append(txt)
            wstart = w["start"]
            wend = w["end"] if w["end"] > w["start"] else w["start"] + 0.25
            lines.append(
                f"Dialogue: 0,{ts(wstart)},{ts(wend)},Cap,,0,0,0,,"
                f"{{\\an2}}" + " ".join(parts)
            )

    # persistent brand tag
    total = max([w["end"] for w in words], default=0) or 5
    lines.append(
        f"Dialogue: 2,{ts(0)},{ts(total)},Tag,,0,0,0,,{ass_escape(brand['url'])}"
    )

    # closing stat card
    if stat_lines:
        s0 = max(total - 2.6, 0)
        body = r"\N".join(ass_escape(x) for x in stat_lines)
        lines.append(
            f"Dialogue: 3,{ts(s0)},{ts(total)},Stat,,0,0,0,,"
            f"{{\\fad(200,150)}}{body}"
        )

    out_path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path


# ----------------------------------------------------------------------------
# step: compose with ffmpeg
# ----------------------------------------------------------------------------
def compose(src, ass, brand, out, voice=None, music=None,
            zoom=True, duck=True, preset="veryfast", crf="23",
            duck_level=0.18, fit="fill", focus="0.5,0.5", punch=1.9,
            move="none", grade="none", bloom=0.0, sfx=None, intensity=1.0,
            style="none"):
    """
    fit modes:
      fill       — whole frame visible over a blurred plate. Good for footage
                   that is already vertical or near-square.
      screencast — punch into a region so small UI text stays readable on a
                   phone, over a clean brand backdrop. Use for OBS captures.
      native     — no zoom, letterboxed on the brand colour.
    focus: "x,y" as fractions of the source frame, the centre of the punch-in.
    punch: magnification. 1.9 makes 14px UI text read like ~26px.
    """
    b = brand
    accent = "0x" + b["accent"]
    bg = "0x" + b["bg"]

    info = probe(src)
    dur = info["duration"]
    try:
        fx, fy = [max(0.0, min(1.0, float(v))) for v in focus.split(",")]
    except Exception:
        fx, fy = 0.5, 0.5

    CINE = ""
    if HAVE_STYLES and style and style != "none":
        sf = stylelib.style_filter(style, brand.get("_key", "nexalead"))
        if sf and "split=" not in sf:
            CINE += sf + ","
        elif sf:
            sys.stderr.write(f"[warn] style '{style}' needs its own filter "
                             f"labels and is only available via styles.py\n")
    if HAVE_CINEMA and (move not in ("none", "static", None) or grade not in ("none", None)):
        chain = cinema.cine_chain(
            move if move else "static",
            grade if grade and grade != "none" else "",
            W, H, dur, intensity=intensity,
        )
        if chain:
            CINE = chain + ","
        if bloom and bloom > 0:
            g = cinema.glow_linear(bloom)
            if g:
                CINE = CINE + g + ","

    if fit == "screencast":
        # Upscale, then crop a 1080-wide window centred on the focus point so
        # small interface text survives the trip to a 9:16 phone screen.
        sw, sh = info["width"] or 1920, info["height"] or 1080
        tw = int(W * punch)
        th = max(2, int(round(sh * tw / sw)))
        ch = min(int(H * 0.62), th)                  # crop height
        cx = int(max(0, min(tw - W, tw * fx - W / 2)))
        cy = int(max(0, min(th - ch, th * fy - ch / 2)))
        drift = min(70, max(0, tw - W - cx))         # slow horizontal pan
        xexpr = (f"'{cx}+({drift}*t/{max(dur,0.1):.3f})'" if (zoom and drift > 4)
                 else str(cx))
        vf = (
            f"color=c={bg}:s={W}x{H}:d={dur}[bgplate];"
            f"[0:v]scale={tw}:{th}:flags=lanczos,"
            f"crop={W}:{ch}:x={xexpr}:y={cy}[fg];"
            f"[bgplate][fg]overlay=(W-w)/2:(H-h)/2+30[stacked];"
            f"color=c={accent}:s={W}x8:d={dur}[bar];"
            f"[stacked][bar]overlay=0:{SAFE_TOP-40}[barred];"
            f"[barred]{CINE}ass={ass}[v]"
        )
    elif fit == "native":
        vf = (
            f"color=c={bg}:s={W}x{H}:d={dur}[bgplate];"
            f"[0:v]scale={W}:-2:force_original_aspect_ratio=decrease[fg];"
            f"[bgplate][fg]overlay=(W-w)/2:(H-h)/2[stacked];"
            f"color=c={accent}:s={W}x8:d={dur}[bar];"
            f"[stacked][bar]overlay=0:{SAFE_TOP-40}[barred];"
            f"[barred]{CINE}ass={ass}[v]"
        )
    else:
        zf = (
            f"zoompan=z='min(zoom+0.00035,1.10)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{int(W*9/16)}:fps={FPS},"
            if zoom else ""
        )
        vf = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},boxblur=28:2,eq=brightness=-0.30:saturation=0.5[bgplate];"
            f"[0:v]{zf}scale={W-24}:-2:force_original_aspect_ratio=decrease[fg];"
            f"[bgplate][fg]overlay=(W-w)/2:(H-h)/2+40[stacked];"
            f"color=c={accent}:s={W}x10:d={dur}[bar];"
            f"[stacked][bar]overlay=0:{SAFE_TOP-40}[barred];"
            f"[barred]drawbox=x=0:y=0:w={W}:h={SAFE_TOP-40}:color={bg}@0.55:t=fill[topmask];"
            f"[topmask]drawbox=x=0:y={H-SAFE_BOTTOM+120}:w={W}:h={SAFE_BOTTOM-120}:color={bg}@0.55:t=fill[masked];"
            f"[masked]{CINE}ass={ass}[v]"
        )

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]

    inputs = 1
    voice_idx = music_idx = None
    if voice:
        cmd += ["-i", str(voice)]
        voice_idx = inputs
        inputs += 1
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        music_idx = inputs
        inputs += 1

    filter_complex = vf
    amap = None

    if voice_idx is not None and info["has_audio"] and duck:
        # duck the screencap audio under the narration
        filter_complex += (
            f";[0:a]volume={duck_level}[srcq];"
            f"[{voice_idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[vo];"
            f"[srcq][vo]amix=inputs=2:duration=longest:dropout_transition=0[a]"
        )
        amap = "[a]"
    elif voice_idx is not None:
        filter_complex += f";[{voice_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[a]"
        amap = "[a]"
    elif info["has_audio"]:
        amap = "0:a"

    if music_idx is not None and amap:
        prev = amap.strip("[]") if amap.startswith("[") else amap
        filter_complex += (
            f";[{music_idx}:a]volume=0.06,atrim=0:{dur}[mus];"
            f"[{prev}][mus]amix=inputs=2:duration=first:dropout_transition=0[afin]"
        )
        amap = "[afin]"

    cmd += ["-filter_complex", filter_complex, "-map", "[v]"]
    if amap:
        cmd += ["-map", amap]

    cmd += [
        "-c:v", "libx264", "-preset", preset, "-crf", crf,
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-g", str(FPS * 2),
        "-movflags", "+faststart",
        "-t", f"{dur:.3f}",
    ]
    if amap:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
    else:
        cmd += ["-an"]
    cmd += [str(out)]

    run(cmd)
    return out


def make_thumbnail(video, out, at=1.2):
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", str(at), "-i", str(video), "-frames:v", "1",
         "-q:v", "2", str(out)])
    return out


# ----------------------------------------------------------------------------
# orchestrator
# ----------------------------------------------------------------------------
def build(args):
    brand = BRANDS[args.brand]
    src = Path(args.input).resolve()
    if not src.exists():
        raise SystemExit(f"input not found: {src}")

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="vidkit_"))
    try:
        info = probe(src)
        print(f"[in ] {src.name}  {info['width']}x{info['height']}  "
              f"{info['duration']:.1f}s  audio={info['has_audio']}")

        # 1. tighten
        work = auto_edit(src, workdir) if args.autoedit else src

        # 2. voice
        voice = None
        if args.script and not args.no_tts:
            voice, _ = synth_voice(args.script, workdir, args.voice)

        # 3. word timings
        words = []
        if args.srt:
            words = words_from_srt(Path(args.srt))
        elif voice:
            words = transcribe_words(voice, workdir, args.whisper_model)
        elif info["has_audio"] and not args.no_asr:
            wav = workdir / "src.wav"
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-i", str(work), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
            words = transcribe_words(wav, workdir, args.whisper_model)

        if not words and args.script:
            words = fake_words_from_script(args.script, probe(work)["duration"])

        # 4. captions
        ass = build_ass(
            words, brand, workdir / "caps.ass",
            group=args.caption_group,
            hook=args.hook,
            stat_lines=(args.stats.split("|") if args.stats else None),
        )

        # 5. compose
        compose(
            work, ass, brand, out,
            voice=voice,
            music=Path(args.music) if args.music else None,
            zoom=not args.no_zoom,
            preset=args.preset,
            crf=args.crf,
            fit=args.fit,
            focus=args.focus,
            punch=args.punch,
            move=args.move,
            grade=args.grade,
            bloom=args.bloom,
            intensity=args.intensity,
            style=args.style,
        )

        thumb = out.with_suffix(".jpg")
        make_thumbnail(out, thumb)

        final = probe(out)
        meta = {
            "output": str(out),
            "thumbnail": str(thumb),
            "brand": args.brand,
            "duration": round(final["duration"], 2),
            "resolution": f"{final['width']}x{final['height']}",
            "size_mb": round(out.stat().st_size / 1024 / 1024, 2),
            "words": len(words),
            "hook": args.hook,
            "has_voiceover": voice is not None,
        }
        out.with_suffix(".json").write_text(json.dumps(meta, indent=2))

        print(f"[out] {out}  {meta['resolution']}  {meta['duration']}s  {meta['size_mb']}MB")
        print(json.dumps(meta, indent=2))
        return meta
    finally:
        if not args.keep_temp:
            shutil.rmtree(workdir, ignore_errors=True)


def words_from_srt(path):
    """Parse SRT into pseudo word timings (line-level)."""
    txt = path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", txt.strip())
    out = []
    for blk in blocks:
        m = re.search(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            blk,
        )
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = " ".join(blk.split("\n")[2:]).strip()
        toks = [t for t in body.split() if t]
        if not toks:
            continue
        per = (end - start) / len(toks)
        for i, t in enumerate(toks):
            out.append({"word": t, "start": start + i * per,
                        "end": start + (i + 1) * per})
    return out


# ----------------------------------------------------------------------------
# self test — generates a synthetic clip and renders it end to end
# ----------------------------------------------------------------------------
def selftest():
    print("=== vidkit selftest ===")
    tmp = Path(tempfile.mkdtemp(prefix="vidkit_test_"))
    raw = tmp / "raw.mp4"

    # synthetic 8s 1920x1080 "screen recording" with tone
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate={FPS}:duration=8",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(raw),
    ])
    print(f"[test] synthetic source: {probe(raw)}")

    ok = True
    for brand in ("nexalead", "armonia"):
        out = tmp / f"out_{brand}.mp4"
        args = argparse.Namespace(
            input=str(raw), out=str(out), brand=brand,
            hook="$2.14 ran this for a week.",
            script="This is the system publishing to twelve platforms. "
                   "One sentence in. Twelve posts out. Total cost, two dollars.",
            stats="47 posts|12 platforms|$2.14",
            srt=None, music=None, voice="af_heart",
            no_tts=True, no_asr=True, no_zoom=False,
            autoedit=False, whisper_model="base", caption_group=3,
            preset="ultrafast", crf="26", keep_temp=False,
            fit="fill", focus="0.5,0.5", punch=1.9,
            move="none", grade="none", bloom=0.0, intensity=1.0, sound=False,
            style="none",
        )
        meta = build(args)

        checks = {
            "file exists": out.exists(),
            "is 1080x1920": meta["resolution"] == "1080x1920",
            "has duration": meta["duration"] > 1,
            "thumbnail written": Path(meta["thumbnail"]).exists(),
            "sidecar json": out.with_suffix(".json").exists(),
            "captions present": meta["words"] > 0,
            "under 60MB": meta["size_mb"] < 60,
        }
        for k, v in checks.items():
            print(f"   [{'PASS' if v else 'FAIL'}] {brand}: {k}")
            ok = ok and v

    # ASS generator unit checks
    brand = BRANDS["nexalead"]
    words = [{"word": "one", "start": 0.0, "end": 0.4},
             {"word": "two", "start": 0.4, "end": 0.8},
             {"word": "three", "start": 0.8, "end": 1.2}]
    a = build_ass(words, brand, tmp / "t.ass", hook="Hook", stat_lines=["A", "B"])
    body = a.read_text()
    unit = {
        "ass has styles": "[V4+ Styles]" in body,
        "ass has hook": "Hook," in body,
        "ass has karaoke lines": body.count("Dialogue:") >= len(words),
        "ass colour converted": "&H" in body,
        "playres matches canvas": f"PlayResX: {W}" in body,
    }
    for k, v in unit.items():
        print(f"   [{'PASS' if v else 'FAIL'}] ass: {k}")
        ok = ok and v

    # srt parser check
    srt = tmp / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nhello world here\n\n")
    parsed = words_from_srt(srt)
    v = len(parsed) == 3 and abs(parsed[0]["start"]) < 0.01
    print(f"   [{'PASS' if v else 'FAIL'}] srt: parses to word timings")
    ok = ok and v

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n=== {'ALL TESTS PASSED' if ok else 'FAILURES PRESENT'} ===")
    return 0 if ok else 1


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="vidkit — screen recording to branded short")
    ap.add_argument("--input", help="raw video (OBS capture, phone clip, anything)")
    ap.add_argument("--out", help="output mp4 path")
    ap.add_argument("--brand", choices=list(BRANDS), default="nexalead")
    ap.add_argument("--hook", help="opening card text, first 1.6s")
    ap.add_argument("--script", help="narration script (drives TTS + captions)")
    ap.add_argument("--stats", help="closing card, pipe separated e.g. '47 posts|12 platforms|$2.14'")
    ap.add_argument("--srt", help="use an existing SRT instead of transcribing")
    ap.add_argument("--music", help="background music file (looped, -24dB)")
    ap.add_argument("--voice", default="af_heart", help="kokoro voice id")
    ap.add_argument("--whisper-model", default="base", choices=["tiny", "base", "small"])
    ap.add_argument("--caption-group", type=int, default=3)
    ap.add_argument("--fit", choices=["fill", "screencast", "native"], default="fill",
                    help="screencast = punch in so UI text stays readable on a phone")
    ap.add_argument("--focus", default="0.5,0.5",
                    help="punch-in centre as x,y fractions e.g. 0.62,0.5")
    ap.add_argument("--punch", type=float, default=1.9,
                    help="screencast magnification")
    ap.add_argument("--move", default="none",
                    help="camera move: crash_zoom, dolly_in, whip_pan, handheld, orbit, tilt_reveal, snap_zoom_out, static")
    ap.add_argument("--grade", default="none",
                    help="colour grade: clean, noir, teal_orange, warm_film, bleach")
    ap.add_argument("--style", default="none",
                    help="visual preset: toxic, two_color, ultraviolet, acid, cold_vision, "
                         "overexposed, ink_riot, sketch, blueprint, vintage, film_16mm, "
                         "paper, halftone, glitch, fragments. Run styles.py --list")
    ap.add_argument("--bloom", type=float, default=0.0, help="highlight glow 0-1")
    ap.add_argument("--intensity", type=float, default=1.0, help="camera move strength 0.5-2.0")
    ap.add_argument("--sound", action="store_true", help="synthesize whoosh/impact sound design")
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--crf", default="23")
    ap.add_argument("--autoedit", action="store_true", help="strip silences first")
    ap.add_argument("--no-tts", action="store_true")
    ap.add_argument("--no-asr", action="store_true")
    ap.add_argument("--no-zoom", action="store_true")
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        raise SystemExit(selftest())
    if not args.input or not args.out:
        ap.error("--input and --out required (or use --selftest)")
    build(args)


if __name__ == "__main__":
    main()
