#!/usr/bin/env python3
"""
autoscene.py — videos that create themselves. No camera, no OBS, ever.

Draws branded, animated 1080x1920 scenes from data (your real numbers),
then render.py adds hook card, voice, captions on top. Fully automatic:
a sheet row with raw_url = "scene:counter" produces a finished short.

Scenes:
  counter   big number counts up (posts, revenue, hours saved) + cost line
  grid      platform / system names light up one by one
  timeline  the 14-day / 45-day delivery bars filling

  autoscene.py --scene counter --brand nexalead --title "posts published this week" \
               --value 47 --sub "total cost $2.14" --out /tmp/scene.mp4
  autoscene.py --scene grid --items "Bluesky,Mastodon,Telegram,..." ...
  autoscene.py --scene timeline ...

Honesty rule: these are motion graphics, not fake screencasts. Feed them
REAL numbers from the sheet; never invent metrics.
"""
import argparse, math, shutil, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
BRANDS = {
    "nexalead": {"accent": (0, 229, 160), "bg": (10, 10, 15), "fg": (240, 244, 248),
                 "muted": (120, 130, 142), "tag": "nexalead.ai"},
    "armonia": {"accent": (200, 176, 122), "bg": (8, 8, 8), "fg": (245, 242, 235),
                "muted": (140, 132, 118), "tag": "armoniaairbnb.com"},
}

def F(sz, bold=True):
    for p in ("/usr/share/fonts/truetype/google-fonts/Poppins-%s.ttf" % ("SemiBold" if bold else "Regular"),
              "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else "")):
        try: return ImageFont.truetype(p, sz)
        except Exception: continue
    return ImageFont.load_default()

def ease(t):  # smooth 0..1
    return 0.5 - 0.5 * math.cos(min(max(t, 0), 1) * math.pi)

import random as _rnd

def spring(t, w=8.0, z=0.55):
    """Overshoot easing: snaps past 1.0 then settles. The 'expensive' pop."""
    t = min(max(t, 0.0), 1.0)
    if t >= 1: return 1.0
    return 1 - math.exp(-z*w*t) * math.cos(w*math.sqrt(max(1-z*z,1e-4))*t)

def base(b, t, dur):
    img = Image.new("RGB", (W, H), b["bg"]); d = ImageDraw.Draw(img)
    # vertical gradient: slightly lifted top, deep bottom
    top = tuple(min(255, c+16) for c in b["bg"])
    for y in range(0, H, 4):
        k = y/H
        col = tuple(int(tc+(bc-tc)*k) for tc, bc in zip(top, b["bg"]))
        d.rectangle([0, y, W, y+4], fill=col)
    # breathing accent glow behind subject
    pulse = 0.5 + 0.5*math.sin(t*1.4)
    cx = W/2 + 120*math.sin(t*0.4); cy = H*0.40 + 80*math.cos(t*0.3)
    for r in range(560, 80, -48):
        k = (r/560)
        a = 0.05*(1-k) + 0.03*pulse
        col = tuple(int(bg+(ac-bg)*a) for bg, ac in zip(b["bg"], b["accent"]))
        d.ellipse([cx-r, cy-r*1.18, cx+r, cy+r*1.18], fill=col)
    # faint grid texture
    gcol = tuple(min(255, c+7) for c in b["bg"])
    for x in range(0, W, 90): d.line([x,0,x,H], fill=gcol)
    for y in range(0, H, 90): d.line([0,y,W,y], fill=gcol)
    return img, d

def finish(img, t, seed):
    """Vignette + animated film grain. Applied last, every frame."""
    d = ImageDraw.Draw(img, "RGBA")
    # vignette
    for i, a in ((0,110),(60,70),(130,40)):
        d.rectangle([i, i, W-i, H-i], outline=(0,0,0,a), width=60)
    # grain
    _rnd.seed(seed)
    for _ in range(2600):
        x = _rnd.randrange(W); y = _rnd.randrange(H)
        v = _rnd.choice((-14, -9, 10, 15))
        d.point((x, y), fill=(128+v*8, 128+v*8, 128+v*8, 26))
    return img

def scene_counter(b, dur, title, value, sub):
    frames = int(dur*FPS); val = float(value)
    for i in range(frames):
        t = i/FPS; img, d = base(b, t, dur)
        # value counts up over first 60%
        k = ease(t/(dur*0.55)); shown = val*k
        txt = f"{shown:,.0f}" if val >= 10 else f"{shown:,.2f}"
        pop = spring(t/0.9)
        size = int(210 + 40*pop)
        vf = F(size); tw = d.textlength(txt, font=vf)
        # soft shadow then face
        d.text(((W-tw)/2+6, H*0.33+8), txt, font=vf, fill=tuple(max(0,c-6) for c in b["bg"]))
        d.text(((W-tw)/2, H*0.33), txt, font=vf, fill=b["fg"])
        # underline sweep synced to count
        uw = int((W-320)*k)
        d.rounded_rectangle([(W-uw)/2, H*0.33+size+26, (W+uw)/2, H*0.33+size+38], 6, fill=b["accent"])
        tf = F(56); tw = d.textlength(title, font=tf)
        d.text(((W-tw)/2, H*0.33+size+70), title, font=tf, fill=b["accent"])
        if sub:
            sf = F(44, False); sw = d.textlength(sub, font=sf)
            # sub fades in late
            a = ease((t-dur*0.55)/(dur*0.2))
            col = tuple(int(m+(f-m)*a) for m, f in zip(b["bg"], b["muted"]))
            d.text(((W-sw)/2, H*0.33+size+170), sub, font=sf, fill=col)
        # progress tick
        d.rectangle([80, H-220, 80+int((W-160)*(t/dur)), H-214], fill=b["accent"])
        yield img

def scene_grid(b, dur, title, items):
    frames = int(dur*FPS); n = len(items)
    cols = 2; rows = math.ceil(n/cols)
    bw, bh, gx, gy = 470, 118, 40, 26
    x0 = (W - cols*bw - (cols-1)*gx)/2
    y0 = H*0.24
    per = (dur*0.75)/max(n, 1)
    for i in range(frames):
        t = i/FPS; img, d = base(b, t, dur)
        tf = F(58); tw = d.textlength(title, font=tf)
        d.text(((W-tw)/2, 260), title, font=tf, fill=b["fg"])
        lit = int(t/per)
        for j, name in enumerate(items):
            r, c = divmod(j, cols)
            x = x0 + c*(bw+gx); y = y0 + r*(bh+gy)
            on = j < lit
            pop = spring((t - j*per)/0.5) if on else 0
            grow = int(6*pop)
            box = [x-grow, y-grow, x+bw+grow, y+bh+grow]
            if on and pop > 1.0:
                halo = int(14*(pop-1.0)*10)
                d.rounded_rectangle([box[0]-halo,box[1]-halo,box[2]+halo,box[3]+halo], 26,
                    outline=tuple(int(c*0.6) for c in b["accent"]), width=2)
            d.rounded_rectangle(box, 22,
                fill=tuple(int(bg+(a-bg)*0.16*pop) for bg, a in zip(b["bg"], b["accent"])),
                outline=b["accent"] if on else b["muted"], width=3 if on else 1)
            nf = F(40); nw = d.textlength(name, font=nf)
            d.text((x+(bw-nw)/2, y+bh/2-26), name, font=nf,
                   fill=b["fg"] if on else b["muted"])
            if on:
                d.ellipse([x+bw-40, y+18, x+bw-18, y+40], fill=b["accent"])
        cnt = f"{min(lit,n)} / {n}"
        cf = F(64); cw = d.textlength(cnt, font=cf)
        d.text(((W-cw)/2, H-330), cnt, font=cf, fill=b["accent"])
        yield img

def scene_timeline(b, dur, title, items):
    # items like "Board-ready roadmap:14|Three live systems:45"
    parsed = []
    for part in items:
        if ":" in part:
            lbl, days = part.rsplit(":", 1)
            try: parsed.append((lbl.strip(), int(days)))
            except ValueError: pass
    if not parsed: parsed = [("Board-ready roadmap", 14), ("Three live systems", 45)]
    mx = max(d2 for _, d2 in parsed)
    frames = int(dur*FPS)
    for i in range(frames):
        t = i/FPS; img, d = base(b, t, dur)
        tf = F(58); tw = d.textlength(title, font=tf)
        d.text(((W-tw)/2, 280), title, font=tf, fill=b["fg"])
        y = H*0.34
        for j, (lbl, days) in enumerate(parsed):
            lf = F(46); d.text((90, y), lbl, font=lf, fill=b["fg"])
            barw = W-180
            d.rounded_rectangle([90, y+70, 90+barw, y+118], 14, outline=b["muted"], width=2)
            k = ease((t - 0.5 - j*0.9)/1.4)
            fillw = int(barw * (days/mx) * k)
            if fillw > 8:
                d.rounded_rectangle([90, y+70, 90+fillw, y+118], 14, fill=b["accent"])
            if fillw > 8:
                d.ellipse([90+fillw-16, y+78, 90+fillw+16, y+110], fill=b["fg"])
            dtxt = f"{int(days*k)} days"
            df = F(44); dw = d.textlength(dtxt, font=df)
            d.text((90+barw-dw, y+8), dtxt, font=df, fill=b["accent"])
            y += 230
        yield img

def render(scene, brand, dur, title, value, sub, items, out):
    b = BRANDS.get(brand, BRANDS["nexalead"])
    tmp = Path(tempfile.mkdtemp(prefix="scene_"))
    gen = {"counter": lambda: scene_counter(b, dur, title, value, sub),
           "grid": lambda: scene_grid(b, dur, title, items),
           "timeline": lambda: scene_timeline(b, dur, title, items)}[scene]()
    for i, img in enumerate(gen):
        finish(img, i/FPS, i).save(tmp/f"f{i:05d}.png")
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error",
        "-framerate",str(FPS),"-i",str(tmp/"f%05d.png"),
        "-f","lavfi","-i",f"anullsrc=r=44100:cl=stereo",
        "-shortest","-c:v","libx264","-preset","veryfast","-crf","20",
        "-pix_fmt","yuv420p","-c:a","aac",str(out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[scene] {out}  {scene} {dur:.0f}s")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True, choices=["counter","grid","timeline"])
    ap.add_argument("--brand", default="nexalead")
    ap.add_argument("--seconds", type=float, default=12)
    ap.add_argument("--title", default="")
    ap.add_argument("--value", default="0")
    ap.add_argument("--sub", default="")
    ap.add_argument("--items", default="", help="comma list; timeline uses label:days")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    items = [x.strip() for x in a.items.split(",") if x.strip()]
    render(a.scene, a.brand, a.seconds, a.title, a.value, a.sub, items, a.out)

if __name__ == "__main__":
    main()
