#!/usr/bin/env python3
"""
styles.py — Higgsfield-style visual presets, implemented in pure FFmpeg.

Higgsfield sells named looks. Roughly two thirds of its catalogue are colour,
edge and texture transformations of existing footage — those are deterministic
image processing and cost nothing. The remaining third invents new scenery and
genuinely requires a diffusion model.

This module implements the first category. See IMPOSSIBLE below for an honest
list of what it cannot do.

    styles.py --list
    styles.py --demo out.mp4 --style toxic
    styles.py --contact-sheet sheet.png        # every style, one image
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Brand duotone targets. TWO COLOR / INK RIOT style presets read these.
# ---------------------------------------------------------------------------
BRAND_DUOTONE = {
    "nexalead": ("00E5A0", "0A0A0F"),
    "armonia": ("C8B07A", "080808"),
}


def _duotone(hi_hex, lo_hex):
    """Map luminance onto a two-colour ramp using per-channel curves."""
    hr, hg, hb = (int(hi_hex[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lr, lg, lb = (int(lo_hex[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (
        "format=gray,format=rgb24,"
        f"curves=r='0/{lr:.3f} 1/{hr:.3f}':"
        f"g='0/{lg:.3f} 1/{hg:.3f}':"
        f"b='0/{lb:.3f} 1/{hb:.3f}'"
    )


# ---------------------------------------------------------------------------
# STYLE PRESETS
# Each value is an FFmpeg filter chain fragment (single in, single out).
# ---------------------------------------------------------------------------
def build_styles(brand="nexalead"):
    hi, lo = BRAND_DUOTONE.get(brand, BRAND_DUOTONE["nexalead"])

    return {
        # ---- colour transforms -------------------------------------------
        "toxic": (
            "Thermal false-colour. Acid greens and magentas.",
            "format=gray,format=rgb24,"
            "curves=r='0/0.05 0.3/0.15 0.6/0.95 1/1':"
            "g='0/0.02 0.35/0.85 0.7/1 1/0.9':"
            "b='0/0.25 0.4/0.35 0.7/0.1 1/0.6',"
            "eq=saturation=1.5:contrast=1.25,noise=alls=9:allf=t"
        ),
        "two_color": (
            "Brand duotone. Everything in two colours.",
            _duotone(hi, lo) + ",eq=contrast=1.18"
        ),
        "ultraviolet": (
            "Neon UV wash. Deep purples with electric highlights.",
            "eq=saturation=1.35:contrast=1.22,"
            "colorchannelmixer=rr=0.75:rb=0.45:gg=0.55:gb=0.30:br=0.55:bb=1.25,"
            "curves=b='0/0.18 0.5/0.62 1/1',gblur=sigma=1.2,"
            "eq=brightness=0.02"
        ),
        "acid": (
            "Psychedelic hue rotation. Colours drift through the clip.",
            "hue=h='mod(45*t,360)':s=1.6,eq=contrast=1.3,noise=alls=6:allf=t"
        ),
        "cold_vision": (
            "Frozen blue scan. Clinical and cold.",
            "eq=saturation=0.35:contrast=1.35,"
            "colorchannelmixer=rr=0.55:gg=0.75:bb=1.35,"
            "curves=b='0/0.15 0.5/0.6 1/1',vignette=PI/4"
        ),
        "overexposed": (
            "Blown highlights, washed film. Sun-bleached.",
            "eq=brightness=0.14:contrast=1.28:saturation=0.82,"
            "curves=all='0/0.10 0.55/0.86 1/1',gblur=sigma=1.6,"
            "noise=alls=7:allf=t"
        ),
        "ink_riot": (
            "Black and one colour, blown contrast. Poster art.",
            "format=gray,format=rgb24,"
            "curves=all='0/0 0.42/0.05 0.58/0.95 1/1',"
            + _duotone(hi, "050505")
        ),

        # ---- edge / illustration ------------------------------------------
        "sketch": (
            "Pencil sketch. Edge detection on white.",
            "format=gray,edgedetect=low=0.06:high=0.22:mode=colormix,"
            "negate,eq=contrast=1.5:brightness=0.12,format=rgb24"
        ),
        "comic": (
            "Flat cel shading with black linework.",
            "split=2[cm_a][cm_b];"
            "[cm_a]curves=all='0/0 0.25/0.12 0.5/0.5 0.75/0.88 1/1',"
            "eq=saturation=1.6:contrast=1.25[cm_flat];"
            "[cm_b]format=gray,edgedetect=low=0.10:high=0.30,negate,"
            "format=rgb24[cm_edge];"
            "[cm_flat][cm_edge]blend=all_mode=multiply"
        ),
        "blueprint": (
            "Technical drawing. White lines on deep blue.",
            "format=gray,edgedetect=low=0.05:high=0.18,"
            "format=rgb24,curves=r='0/0.02 1/0.85':"
            "g='0/0.10 1/0.95':b='0/0.35 1/1',eq=contrast=1.3"
        ),

        # ---- texture / era -------------------------------------------------
        "vintage": (
            "VHS. Chroma bleed, scanlines, heavy grain.",
            "chromashift=cbh=4:crh=-4,"
            "eq=saturation=0.78:contrast=1.06:brightness=0.03,"
            "curves=r='0/0.08 0.5/0.55 1/0.96':"
            "b='0/0.05 0.5/0.46 1/0.9',"
            "noise=alls=16:allf=t+u,"
            "geq=lum='lum(X,Y)*(0.92+0.08*sin(Y*3.14159/2))':"
            "cb='cb(X,Y)':cr='cr(X,Y)'"
        ),
        "film_16mm": (
            "16mm stock. Halation, weave, organic grain.",
            "eq=saturation=0.95:contrast=1.12,"
            "curves=r='0/0.05 0.5/0.54 1/0.98':"
            "g='0/0.04 0.5/0.5 1/0.97':"
            "b='0/0.07 0.5/0.47 1/0.93',"
            "noise=alls=14:allf=t+u,vignette=PI/4.2,unsharp=5:5:-0.6"
        ),
        "paper": (
            "Printed on paper. Desaturated with texture.",
            "eq=saturation=0.62:contrast=1.10:brightness=0.06,"
            "curves=all='0/0.12 0.5/0.55 1/0.97',"
            "noise=alls=22:allf=t+u,unsharp=7:7:-1.0"
        ),
        "halftone": (
            "Print dot pattern. Newspaper reproduction.",
            "format=gray,"
            "geq=lum='if(gt(lum(X,Y)+90*sin(X*0.7)*sin(Y*0.7),150),255,0)',"
            "format=rgb24,eq=contrast=1.1"
        ),

        # ---- glitch --------------------------------------------------------
        "glitch": (
            "RGB displacement and scan tearing.",
            "rgbashift=rh=-6:bh=6:rv=2:bv=-2,"
            "eq=contrast=1.18:saturation=1.25,"
            "geq=lum='lum(X,Y)*(1-0.22*lt(mod(Y+random(1)*40,90),3))':"
            "cb='cb(X,Y)':cr='cr(X,Y)',"
            "noise=alls=14:allf=t"
        ),
        "fragments": (
            "High contrast cutout. Stark black and white shapes.",
            "format=gray,format=rgb24,"
            "curves=all='0/0 0.46/0.02 0.54/0.98 1/1',"
            "eq=contrast=1.6,noise=alls=8:allf=t"
        ),

        # ---- clean ----------------------------------------------------------
        "none": ("No style transform.", ""),
    }


# ---------------------------------------------------------------------------
# What FFmpeg genuinely cannot do — be honest about this.
# ---------------------------------------------------------------------------
IMPOSSIBLE = {
    "FALLEN ANGEL / FAIRYTALE CASTLE / AGAMEMNON":
        "Invents entirely new scenery and subjects. Needs a diffusion model.",
    "DOLPHIN RIDE / PENGUIN RIDE / SKATEDOG":
        "Composites a subject onto an animal that was never filmed.",
    "SELFIE TWIN / ACTION FIGURE":
        "Generates a second instance of a person, or reposes them.",
    "MONET MUSE / PEARL EARRING / HAND PAINT":
        "True painterly style transfer. A neural model, not a colour curve. "
        "The closest free equivalent here is 'paper' or 'comic'.",
    "BULLET TIME / ORBIT 360 / EARTH ZOOM":
        "Synthesizes camera angles that were never filmed. Partial equivalents "
        "exist in cinema.py (orbit, crash_zoom) but only within the real frame.",
    "BROKEN MIRROR / ORIGAMI / MARBLE / 3D RENDER":
        "Rebuilds the subject in a new material or geometry. Diffusion only.",
}


# ---------------------------------------------------------------------------
# Styles that survive UI / screen-recording footage. The rest need
# photographic tonal range or they flatten a mostly-white frame to one colour.
# Verified empirically against a real n8n canvas capture.
UI_SAFE = {"none", "blueprint", "film_16mm", "vintage", "cold_vision", "paper"}


def style_filter(name, brand="nexalead"):
    styles = build_styles(brand)
    entry = styles.get(name)
    return entry[1] if entry else ""


def is_multistream(name, brand="nexalead"):
    """Some styles use split/blend and need their own labels."""
    return "split=" in style_filter(name, brand)


def demo(out, style, brand="nexalead", seconds=4, src=None):
    tmp = Path(tempfile.mkdtemp(prefix="sty_"))
    if src is None:
        src = tmp / "src.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc2=size=1280x720:rate=30:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(src)], check=True)

    chain = style_filter(style, brand)
    vf = "[0:v]" + (chain if chain else "null") + "[v]"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
        "-filter_complex", vf, "-map", "[v]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-t", str(seconds), str(out)], check=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--impossible", action="store_true")
    ap.add_argument("--demo")
    ap.add_argument("--style", default="toxic")
    ap.add_argument("--brand", default="nexalead")
    ap.add_argument("--source")
    ap.add_argument("--seconds", type=float, default=4)
    a = ap.parse_args()

    if a.list:
        for k, (desc, _) in build_styles(a.brand).items():
            tag = "UI-safe " if k in UI_SAFE else "photo   "
            print(f"  {k:<14} [{tag}] {desc}")
        print("\n  UI-safe   = works on screen recordings")
        print("  photo     = needs photographic footage; flattens UI captures")
        return 0
    if a.impossible:
        print("Needs a diffusion model — cannot be done with FFmpeg:\n")
        for k, v in IMPOSSIBLE.items():
            print(f"  {k}\n      {v}\n")
        return 0
    if a.demo:
        demo(a.demo, a.style, a.brand, a.seconds,
             Path(a.source) if a.source else None)
        print(f"wrote {a.demo}  style={a.style}")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
