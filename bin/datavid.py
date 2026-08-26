#!/usr/bin/env python3
"""
datavid.py — video with no camera.

The video pipeline's only human dependency was "record something". This
removes it. Every template here renders a finished, branded, animated clip
from numbers alone, so the autopilot can publish video on days when you never
opened OBS.

Templates:
    stats       big figures counting up, one at a time
    versus      before/after bars racing against each other
    canvas      an automation graph executing, nodes lighting green
    list        numbered points revealing in sequence
    quote       a single claim, held, with a slow push

Output feeds straight into render.py for captions, camera move and grade.

    datavid.py --template stats --data "47 posts|12 platforms|$2.14" --out s.mp4
    datavid.py --template versus --data "Agency $5,000/mo|This system $30/mo"
    datavid.py --template canvas --data "Read Sheet|Write Copy|Post x9"
    datavid.py --demo-all
"""

import argparse
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30

# render.py draws the accent rule, the url tag and burns captions at ~1290.
# datavid therefore paints only inside this band and adds no brand chrome,
# so the two never collide.
SAFE_TOP = 380
SAFE_BOTTOM = 1180

BRANDS = {
    "nexalead": {
        "bg": (10, 10, 15), "fg": (255, 255, 255), "accent": (0, 229, 160),
        "muted": (120, 126, 138), "panel": (22, 23, 30), "url": "nexalead.ai",
    },
    "armonia": {
        "bg": (8, 8, 8), "fg": (255, 255, 255), "accent": (200, 176, 122),
        "muted": (128, 124, 116), "panel": (24, 22, 18), "url": "armoniaairbnb.com",
    },
}

FONTS = [
    "/usr/share/fonts/truetype/poppins/Poppins-{w}.ttf",
    "/usr/share/fonts/truetype/google-fonts/Poppins-{w}.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans{d}.ttf",
]


def F(size, weight="SemiBold"):
    for pat in FONTS:
        p = pat.format(w=weight, d="-Bold" if weight in ("Bold", "SemiBold") else "")
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def ease_out(t):
    return 1 - pow(1 - max(0.0, min(1.0, t)), 3)


def ease_out_back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def centered(d, text, font, y, fill):
    bb = d.textbbox((0, 0), text, font=font)
    d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y), text, font=font, fill=fill)
    return bb[3] - bb[1]


def split_num(s):
    """'47 posts' -> ('47', 'posts'). '$2.14' -> ('$2.14', '')."""
    s = s.strip()
    parts = s.split(" ", 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


# ---------------------------------------------------------------------------
# TEMPLATES — each returns a PIL Image for frame index i
# ---------------------------------------------------------------------------
def tpl_stats(i, dur, items, b, title=None):
    img = Image.new("RGB", (W, H), b["bg"])
    d = ImageDraw.Draw(img)
    t = i / FPS

    if title:
        centered(d, title.upper(), F(34, "Medium"), SAFE_TOP - 70, b["muted"])

    n = max(1, len(items))
    slot = (dur - 0.8) / n
    band = SAFE_BOTTOM - SAFE_TOP
    block_h = min(300, band / n)
    top = SAFE_TOP + (band - block_h * n) / 2

    for k, raw in enumerate(items):
        start = 0.5 + k * slot
        p = ease_out_back((t - start) / max(slot * 0.55, 0.25))
        if p <= 0:
            continue
        p = min(p, 1.15)
        num, label = split_num(raw)

        # count the number up rather than popping it in
        shown = num
        digits = "".join(c for c in num if c.isdigit() or c == ".")
        if digits and p < 1.0:
            try:
                target = float(digits)
                cur = target * ease_out((t - start) / max(slot * 0.5, 0.2))
                cur_s = f"{cur:,.2f}" if "." in digits else f"{int(cur):,}"
                shown = num.replace(digits, cur_s)
            except ValueError:
                pass

        y = top + k * block_h
        size = int(min(150, block_h * 0.52) * min(p, 1.0))
        if size > 8:
            centered(d, shown, F(size, "Bold"), y, b["accent"])
        if p > 0.55 and label:
            centered(d, label.upper(), F(int(min(40, block_h * 0.15)), "Medium"),
                     y + size * 1.12, b["fg"])
    return img


def tpl_versus(i, dur, items, b, title=None):
    img = Image.new("RGB", (W, H), b["bg"])
    d = ImageDraw.Draw(img)
    t = i / FPS
    if title:
        centered(d, title.upper(), F(34, "Medium"), SAFE_TOP - 70, b["muted"])

    rows = items[:2] if len(items) >= 2 else items
    vals = []
    for r in rows:
        digits = "".join(c for c in r if c.isdigit() or c == ".")
        try:
            vals.append(float(digits) if digits else 1.0)
        except ValueError:
            vals.append(1.0)
    mx = max(vals) or 1.0

    bar_top = SAFE_TOP + 90
    for k, raw in enumerate(rows):
        p = ease_out((t - 0.5 - k * 0.35) / 1.1)
        if p <= 0:
            continue
        y = bar_top + k * 300
        label = raw.strip()
        col = b["muted"] if k == 0 else b["accent"]
        # Log-ish floor: a $30 bar against $5,000 is 0.6% wide and invisible.
        # Keep proportion legible while guaranteeing the small bar still reads.
        ratio = vals[k] / mx
        floor = 0.16
        scaled = floor + (1 - floor) * ratio
        full = int((W - 200) * scaled)
        d.text((100, y - 66), label, font=F(46, "SemiBold"), fill=b["fg"])
        d.rounded_rectangle([100, y, 100 + max(60, int(full * p)), y + 88],
                            radius=14, fill=col)

    if t > 1.9 and len(vals) >= 2 and min(vals) > 0:
        factor = max(vals) / min(vals)
        pop = ease_out_back((t - 1.9) / 0.5)
        if pop > 0:
            centered(d, f"{factor:,.0f}x", F(int(170 * min(pop, 1.0)), "Bold"),
                     SAFE_BOTTOM - 260, b["accent"])
            if pop > 0.6:
                centered(d, "CHEAPER", F(42, "Medium"), SAFE_BOTTOM - 80, b["fg"])
    return img


def tpl_canvas(i, dur, items, b, title=None):
    """An automation graph executing. Nodes light up in sequence."""
    img = Image.new("RGB", (W, H), b["bg"])
    d = ImageDraw.Draw(img)
    t = i / FPS

    for x in range(0, W, 46):
        for y in range(SAFE_TOP - 40, SAFE_BOTTOM + 40, 46):
            d.point((x, y), fill=(b["panel"][0] + 8, b["panel"][1] + 8, b["panel"][2] + 10))

    centered(d, (title or "EXECUTION").upper(), F(34, "Medium"),
             SAFE_TOP - 70, b["muted"])

    nodes = items[:7]
    n = max(1, len(nodes))
    active = int(max(0.0, t - 0.7) / max((dur - 1.4) / n, 0.25))

    band = SAFE_BOTTOM - SAFE_TOP - 70
    gap = 22
    nh = max(70, min(132, (band - (n - 1) * gap) / n))
    total = n * nh + (n - 1) * gap
    top = SAFE_TOP + (band - total) / 2

    for k, name in enumerate(nodes):
        on = k < active
        y = top + k * (nh + gap)
        if k:
            col = b["accent"] if on else b["panel"]
            d.rectangle([W / 2 - 3, y - gap, W / 2 + 3, y], fill=col)
        d.rounded_rectangle([120, y, W - 120, y + nh], radius=18,
                            fill=b["panel"] if not on else (
                                int(b["accent"][0] * .13 + b["bg"][0]),
                                int(b["accent"][1] * .13 + b["bg"][1]),
                                int(b["accent"][2] * .13 + b["bg"][2])),
                            outline=b["accent"] if on else (46, 48, 56),
                            width=3 if on else 2)
        pad = nh * 0.28
        d.rounded_rectangle([152, y + pad, 152 + nh * 0.42, y + pad + nh * 0.42],
                            radius=10, fill=b["accent"] if on else (52, 54, 62))
        d.text((236, y + nh * 0.18), name[:26],
               font=F(int(nh * 0.33), "SemiBold"), fill=b["fg"])
        d.text((236, y + nh * 0.60), "done" if on else "waiting",
               font=F(int(nh * 0.22), "Medium"),
               fill=b["accent"] if on else b["muted"])
        if on:
            r = nh * 0.16
            cy = y + nh / 2
            d.ellipse([W - 190, cy - r, W - 190 + 2 * r, cy + r], fill=b["accent"])

    done = min(active, n)
    centered(d, f"{done} / {n} complete", F(40, "SemiBold"),
             SAFE_BOTTOM - 40, b["accent"] if done == n else b["muted"])
    return img


def tpl_list(i, dur, items, b, title=None):
    img = Image.new("RGB", (W, H), b["bg"])
    d = ImageDraw.Draw(img)
    t = i / FPS
    if title:
        centered(d, title.upper(), F(38, "Medium"), SAFE_TOP - 70, b["muted"])

    n = max(1, len(items))
    slot = (dur - 1.0) / n
    shown_items = items[:6]
    step = min(190, (SAFE_BOTTOM - SAFE_TOP) / max(len(shown_items), 1))
    top = SAFE_TOP + 20
    for k, raw in enumerate(shown_items):
        p = ease_out((t - 0.5 - k * slot) / max(slot * 0.6, 0.3))
        if p <= 0:
            continue
        y = top + k * step
        x = int(110 + (1 - min(p, 1.0)) * 90)
        d.text((x, y), f"{k+1:02d}", font=F(58, "Bold"), fill=b["accent"])
        d.text((x + 110, y + 6), raw.strip()[:30], font=F(50, "SemiBold"), fill=b["fg"])
        d.rectangle([x + 110, y + 82, x + 110 + int(560 * min(p, 1.0)), y + 85],
                    fill=(46, 48, 56))
    return img


def tpl_quote(i, dur, items, b, title=None):
    img = Image.new("RGB", (W, H), b["bg"])
    d = ImageDraw.Draw(img)
    t = i / FPS
    text = " ".join(items)
    p = ease_out(t / 0.9)
    words = text.split()
    per = max(1, int(len(words) * min(1.0, t / max(dur * 0.55, 0.6))))
    shown = " ".join(words[:per])

    # wrap
    lines, cur = [], ""
    f = F(72, "Bold")
    for w in shown.split():
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=f) > W - 200:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)

    y = SAFE_TOP + ((SAFE_BOTTOM - SAFE_TOP) - len(lines) * 104) / 2
    for ln in lines:
        centered(d, ln, f, y, b["fg"])
        y += 104

    if p > 0.3:
        d.rectangle([W / 2 - 60, y + 50, W / 2 + 60, y + 56], fill=b["accent"])
    return img


TEMPLATES = {
    "stats": (tpl_stats, "Big figures counting up, one at a time"),
    "versus": (tpl_versus, "Before/after bars with an Nx multiplier reveal"),
    "canvas": (tpl_canvas, "Automation graph executing, nodes going green"),
    "list": (tpl_list, "Numbered points revealing in sequence"),
    "quote": (tpl_quote, "One claim, typed out, held"),
}


# ---------------------------------------------------------------------------
def build(template, items, out, brand="nexalead", seconds=6.0, title=None,
          silent=False):
    if template not in TEMPLATES:
        raise SystemExit(f"unknown template. options: {', '.join(TEMPLATES)}")
    b = BRANDS.get(brand, BRANDS["nexalead"])
    fn = TEMPLATES[template][0]
    tmp = Path(tempfile.mkdtemp(prefix="datavid_"))
    try:
        frames = int(seconds * FPS)
        for i in range(frames):
            fn(i, seconds, items, b, title).save(tmp / f"f{i:05d}.png")

        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(FPS), "-i", str(tmp / "f%05d.png")]
        if not silent:
            cmd += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={seconds}"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p"]
        if not silent:
            cmd += ["-c:a", "aac", "-shortest"]
        cmd += ["-t", str(seconds), str(out)]
        subprocess.run(cmd, check=True)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def demo_all(outdir="."):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    samples = {
        "stats": (["47 posts", "12 platforms", "$2.14 cost"], "last week"),
        "versus": (["Agency $5000", "This system $30"], "monthly cost"),
        "canvas": (["Read Calendar", "Write Copy", "Bluesky", "Mastodon",
                    "Telegram", "Blogger", "dev.to"], "execution"),
        "list": (["Invoice matching", "Lead routing", "Report building",
                  "Inbox triage"], "still done by hand"),
        "quote": (["Most AI consultants deliver a PDF."], None),
    }
    made = []
    for name, (items, title) in samples.items():
        p = outdir / f"datavid_{name}.mp4"
        build(name, items, p, seconds=6.0, title=title)
        made.append(p)
        print(f"  wrote {p}", file=sys.stderr)
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", choices=list(TEMPLATES))
    ap.add_argument("--data", help="pipe separated, e.g. '47 posts|12 platforms|$2.14'")
    ap.add_argument("--title")
    ap.add_argument("--out", default="datavid.mp4")
    ap.add_argument("--brand", default="nexalead", choices=list(BRANDS))
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--silent", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--demo-all", action="store_true")
    a = ap.parse_args()

    if a.list:
        for k, (_, d) in TEMPLATES.items():
            print(f"  {k:<9} {d}")
        return 0
    if a.demo_all:
        demo_all(Path(a.out).parent if Path(a.out).suffix else a.out)
        return 0
    if not a.template or not a.data:
        ap.error("--template and --data required (or --demo-all / --list)")

    items = [x for x in a.data.split("|") if x.strip()]
    build(a.template, items, a.out, a.brand, a.seconds, a.title, a.silent)
    print(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
