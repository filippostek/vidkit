#!/usr/bin/env python3
"""
cinema.py — the expensive-looking layer.

Higgsfield's perceived quality comes from camera language, not from the
diffusion model: crash zooms, dolly pushes, whip pans, handheld float, speed
ramps, motion blur, film grade, bloom, grain, and sound design on every move.

All of that is deterministic motion design. FFmpeg does it for free, on CPU,
on real footage — which matters because a firm selling "working systems"
cannot post synthetic video of those systems.

Exports:
    move_filter(name, dur, w, h, intensity)   -> ffmpeg filter string
    grade_filter(style, brand)                -> ffmpeg filter string
    build_sfx(moves, dur, out_wav)            -> synthesized whooshes/impacts
    MOVES, GRADES                             -> catalogues

Standalone:
    cinema.py --demo out.mp4 --move crash_zoom --grade noir
    cinema.py --list
"""

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

FPS = 30


# ---------------------------------------------------------------------------
# CAMERA MOVES
# Each returns an ffmpeg filter fragment operating on a single video stream.
# `d` is duration in seconds, `k` is intensity 0.5–2.0.
# ---------------------------------------------------------------------------
def _zoompan(zexpr, xexpr, yexpr, w, h, d):
    # NOTE: zoompan does NOT expose `t`. Time must be derived from the output
    # frame counter `on`. Every expression below uses T = (on/FPS).
    return (
        f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':"
        f"d=1:s={w}x{h}:fps={FPS}"
    )


T = f"(on/{FPS})"          # elapsed seconds inside zoompan


def move_crash_zoom(d, w, h, k=1.0):
    """Violent punch-in over ~0.5s then hold. The signature Higgsfield beat."""
    t0 = 0.45 / k
    z = f"if(lte({T},{t0:.3f}),1+{0.55*k:.3f}*pow({T}/{t0:.3f},0.55),{1+0.55*k:.3f})"
    return _zoompan(z, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)", w, h, d)


def move_dolly_in(d, w, h, k=1.0):
    """Slow continuous push. Reads as expensive because it never stops."""
    z = f"1+{0.28*k:.3f}*min({T}/{max(d,0.1):.2f},1)"
    return _zoompan(z, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)", w, h, d)


def move_dolly_out(d, w, h, k=1.0):
    z = f"{1+0.28*k:.3f}-{0.28*k:.3f}*min({T}/{max(d,0.1):.2f},1)"
    return _zoompan(z, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)", w, h, d)


def move_whip_pan(d, w, h, k=1.0):
    """Fast lateral sweep with smear. Use as a transition."""
    t0 = 0.42 / k
    z = f"{1+0.22*k:.3f}"
    x = (f"iw/2-(iw/zoom/2)+{0.30*k:.3f}*iw*sin(3.14159*min({T}/{t0:.3f},1))")
    return _zoompan(z, x, "ih/2-(ih/zoom/2)", w, h, d)


def move_handheld(d, w, h, k=1.0):
    """Organic float. Kills the 'screenshot with music' feeling instantly."""
    z = f"{1+0.10*k:.3f}"
    x = f"iw/2-(iw/zoom/2)+{7*k:.2f}*sin(2.1*{T})+{4*k:.2f}*sin(5.3*{T}+1.1)"
    y = f"ih/2-(ih/zoom/2)+{5*k:.2f}*cos(1.7*{T})+{3*k:.2f}*sin(4.1*{T}+0.4)"
    return _zoompan(z, x, y, w, h, d)


def move_orbit(d, w, h, k=1.0):
    """Slow arc around the centre of interest."""
    z = f"{1+0.20*k:.3f}"
    x = f"iw/2-(iw/zoom/2)+{26*k:.2f}*sin(6.283*{T}/{max(d,0.1):.2f})"
    y = f"ih/2-(ih/zoom/2)+{14*k:.2f}*cos(6.283*{T}/{max(d,0.1):.2f})"
    return _zoompan(z, x, y, w, h, d)


def move_tilt_reveal(d, w, h, k=1.0):
    """Vertical reveal from top. Good for long dashboards."""
    z = f"{1+0.18*k:.3f}"
    y = f"(ih-ih/zoom)*min({T}/{max(d,0.1):.2f},1)"
    return _zoompan(z, "iw/2-(iw/zoom/2)", y, w, h, d)


def move_snap_zoom_out(d, w, h, k=1.0):
    """Starts tight, snaps wide at 0.35s. Reveal beat."""
    t0 = 0.35 / k
    z = (f"if(lte({T},{t0:.3f}),{1+0.5*k:.3f},"
         f"1+{0.5*k:.3f}*exp(-6*({T}-{t0:.3f})))")
    return _zoompan(z, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)", w, h, d)


def move_static(d, w, h, k=1.0):
    return ""


MOVES = {
    "crash_zoom": (move_crash_zoom, "Violent 0.45s punch-in, then hold"),
    "dolly_in": (move_dolly_in, "Slow continuous push, never stops"),
    "dolly_out": (move_dolly_out, "Slow continuous pull back"),
    "whip_pan": (move_whip_pan, "Fast lateral sweep, use as a transition"),
    "handheld": (move_handheld, "Organic float, kills the static look"),
    "orbit": (move_orbit, "Slow arc around centre"),
    "tilt_reveal": (move_tilt_reveal, "Vertical reveal, good for dashboards"),
    "snap_zoom_out": (move_snap_zoom_out, "Tight then snap wide, reveal beat"),
    "static": (move_static, "No camera move"),
}


def move_filter(name, d, w, h, intensity=1.0):
    fn = MOVES.get(name, MOVES["static"])[0]
    return fn(d, w, h, intensity)


# ---------------------------------------------------------------------------
# MOTION BLUR — tmix is cheap on CPU, minterpolate is not.
# ---------------------------------------------------------------------------
def motion_blur(frames=3):
    if frames < 2:
        return ""
    return f"tmix=frames={frames}:weights='{' '.join(['1'] * frames)}'"


# ---------------------------------------------------------------------------
# GRADES — film curves, bloom, grain, vignette, halation
# ---------------------------------------------------------------------------
def grade_filter(style, accent_hex="00E5A0"):
    """Colour grade + texture. Returns a filter chain fragment."""
    common_grain = "noise=alls=6:allf=t+u"
    vig = "vignette=PI/4.4"

    if style == "noir":
        # deep blacks, cool shadows, crushed highlights — SaaS/tech look
        return (
            "eq=contrast=1.16:saturation=0.86:gamma=0.96,"
            "curves=r='0/0.02 0.5/0.47 1/0.98':"
            "g='0/0.02 0.5/0.5 1/1':"
            "b='0/0.06 0.5/0.55 1/1',"
            f"{common_grain},{vig}"
        )
    if style == "teal_orange":
        # the blockbuster grade
        return (
            "eq=contrast=1.20:saturation=1.12,"
            "curves=r='0/0.03 0.4/0.42 1/1':"
            "g='0/0.02 0.5/0.5 1/0.98':"
            "b='0/0.09 0.5/0.52 1/0.94',"
            f"{common_grain},{vig}"
        )
    if style == "warm_film":
        # Armonía / hospitality: golden, soft, inviting
        return (
            "eq=contrast=1.08:saturation=1.05:gamma=1.03,"
            "curves=r='0/0.04 0.5/0.55 1/1':"
            "g='0/0.03 0.5/0.5 1/0.98':"
            "b='0/0.02 0.5/0.45 1/0.92',"
            "noise=alls=8:allf=t+u,vignette=PI/4"
        )
    if style == "clean":
        # punchy but honest — best for UI footage where colour accuracy matters
        return "eq=contrast=1.07:saturation=1.03,noise=alls=3:allf=t"
    if style == "bleach":
        return (
            "eq=contrast=1.30:saturation=0.55:brightness=0.02,"
            f"{common_grain},{vig}"
        )
    return ""


GRADES = {
    "clean": "Punchy but colour-accurate. Best for UI footage.",
    "noir": "Deep blacks, cool shadows. Tech/SaaS.",
    "teal_orange": "Blockbuster grade. High contrast.",
    "warm_film": "Golden and soft. Hospitality/lifestyle.",
    "bleach": "Desaturated high contrast. Editorial.",
}


def glow_linear(strength=0.35):
    """
    Linear highlight glow. True bloom needs split/blend labels which cannot be
    inlined into a single-stream chain, so this approximates it with an
    unsharp lift plus a gentle highlight curve. Cheap and graph-safe.
    """
    if strength <= 0:
        return ""
    amt = min(1.5, max(0.05, strength * 1.4))
    return (
        f"unsharp=7:7:-{amt:.2f}:7:7:0.0,"
        f"curves=all='0/0 0.55/{0.55 + 0.06*strength:.3f} 1/1'"
    )


def bloom_chain(strength=0.35):
    """Glow on highlights — the single cheapest 'expensive' cue."""
    return (
        f"split=2[bl_a][bl_b];"
        f"[bl_b]curves=all='0/0 0.72/0 1/1',gblur=sigma=26[bl_glow];"
        f"[bl_a][bl_glow]blend=all_mode=screen:all_opacity={strength}"
    )


# ---------------------------------------------------------------------------
# SPEED RAMP
# ---------------------------------------------------------------------------
def speed_ramp(d, hold=0.6, fast=2.2):
    """
    Hold real-time for `hold` seconds, then accelerate. Reads as intentional
    editing rather than a raw capture.
    """
    return (
        f"setpts='if(lt(T,{hold}),PTS,{hold}/TB+(PTS-{hold}/TB)/{fast})'"
    )


# ---------------------------------------------------------------------------
# SOUND DESIGN — synthesized, no library needed, no licensing
# ---------------------------------------------------------------------------
def build_sfx(cues, duration, out_wav):
    """
    cues: list of (time_seconds, kind) where kind in
          {"whoosh", "impact", "riser", "tick"}
    Renders a single wav with all cues mixed at the right offsets.
    """
    if not cues:
        return None

    inputs, filters, labels = [], [], []
    idx = 0

    for t, kind in cues:
        if kind == "whoosh":
            # filtered noise sweep
            inputs += ["-f", "lavfi", "-i", "anoisesrc=d=0.55:c=pink:a=0.5"]
            filters.append(
                f"[{idx}:a]highpass=f=300,lowpass=f=5200,"
                f"volume='0.55*exp(-6*t)':eval=frame,"
                f"afade=t=in:st=0:d=0.05,adelay={int(t*1000)}|{int(t*1000)}[s{idx}]"
            )
        elif kind == "impact":
            # low sine thump with fast decay
            inputs += ["-f", "lavfi", "-i", "sine=frequency=62:duration=0.5"]
            filters.append(
                f"[{idx}:a]volume='0.9*exp(-11*t)':eval=frame,"
                f"adelay={int(t*1000)}|{int(t*1000)}[s{idx}]"
            )
        elif kind == "riser":
            inputs += ["-f", "lavfi", "-i", "anoisesrc=d=1.1:c=white:a=0.35"]
            filters.append(
                f"[{idx}:a]highpass=f=800,"
                f"volume='0.42*pow(t/1.1,2.2)':eval=frame,"
                f"adelay={int(t*1000)}|{int(t*1000)}[s{idx}]"
            )
        elif kind == "tick":
            inputs += ["-f", "lavfi", "-i", "sine=frequency=1750:duration=0.07"]
            filters.append(
                f"[{idx}:a]volume='0.30*exp(-40*t)':eval=frame,"
                f"adelay={int(t*1000)}|{int(t*1000)}[s{idx}]"
            )
        else:
            continue
        labels.append(f"[s{idx}]")
        idx += 1

    if not labels:
        return None

    mix = "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0"
    mix += f",apad=whole_dur={duration:.2f},atrim=0:{duration:.2f}[out]"

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + inputs + [
        "-filter_complex", ";".join(filters) + ";" + mix,
        "-map", "[out]", "-ac", "2", "-ar", "44100", str(out_wav),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(f"[sfx] failed: {p.stderr[:200]}\n")
        return None
    return out_wav


def auto_cues(duration, move):
    """Sensible default sound design for a given camera move."""
    cues = [(0.0, "impact")]
    if move in ("crash_zoom", "snap_zoom_out"):
        cues.append((0.02, "whoosh"))
    if move == "whip_pan":
        cues.append((0.0, "whoosh"))
    if duration > 4:
        cues.append((max(0.4, duration - 2.8), "riser"))
        cues.append((max(0.6, duration - 1.9), "impact"))
    return cues


# ---------------------------------------------------------------------------
# COMPOSITE CHAIN BUILDER — what render.py calls
# ---------------------------------------------------------------------------
def cine_chain(move, grade, w, h, dur, intensity=1.0, blur_frames=3,
               bloom=0.0, ramp=None, accent="00E5A0"):
    """
    Assemble a linear (single in / single out) cinematic chain.
    Bloom is applied via a split/blend, so it is emitted separately by the
    caller when needed. Returns a comma-joined filter string.
    """
    parts = []
    mv = move_filter(move, dur, w, h, intensity)
    if mv:
        parts.append(mv)
    if blur_frames >= 2 and move in ("crash_zoom", "whip_pan", "snap_zoom_out", "orbit"):
        parts.append(motion_blur(blur_frames))
    if ramp:
        parts.append(speed_ramp(dur, *ramp))
    g = grade_filter(grade, accent)
    if g:
        parts.append(g)
    return ",".join(p for p in parts if p)


# ---------------------------------------------------------------------------
def demo(out, move, grade, seconds=5, bloom=0.35, sound=True):
    """Render a self-contained demo so the look can be judged, not imagined."""
    W, H = 1080, 1920
    tmp = Path(tempfile.mkdtemp(prefix="cine_"))
    src = tmp / "src.mp4"

    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i",
        f"testsrc2=size=1920x1080:rate={FPS}:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(src)], check=True)

    chain = cine_chain(move, grade, W, H, seconds)
    vf = f"[0:v]scale=-2:{H},crop={W}:{H}:'(iw-{W})/2':0"
    if chain:
        vf += "," + chain
    if bloom > 0:
        vf += "," + bloom_chain(bloom)
    vf += "[v]"

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    sfx = None
    if sound:
        sfx = build_sfx(auto_cues(seconds, move), seconds, tmp / "sfx.wav")
        if sfx:
            cmd += ["-i", str(sfx)]

    cmd += ["-filter_complex", vf, "-map", "[v]"]
    if sfx:
        cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-t", str(seconds), str(out)]
    subprocess.run(cmd, check=True)
    print(f"wrote {out}  move={move} grade={grade}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--demo")
    ap.add_argument("--move", default="crash_zoom", choices=list(MOVES))
    ap.add_argument("--grade", default="noir", choices=list(GRADES))
    ap.add_argument("--seconds", type=float, default=5)
    a = ap.parse_args()

    if a.list:
        print("CAMERA MOVES")
        for k, (_, desc) in MOVES.items():
            print(f"  {k:<16} {desc}")
        print("\nGRADES")
        for k, desc in GRADES.items():
            print(f"  {k:<16} {desc}")
        return 0
    if a.demo:
        demo(a.demo, a.move, a.grade, a.seconds)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
