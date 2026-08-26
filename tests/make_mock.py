#!/usr/bin/env python3
"""Generate a realistic n8n-canvas screen recording to test vidkit against
real-world footage (light UI, small text) rather than colour bars."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import subprocess, math, shutil

W, H, FPS, DUR = 1920, 1080, 30, 10
OUT = Path("/tmp/n8nmock"); OUT.mkdir(exist_ok=True)

BG      = (247, 248, 250)
GRID    = (231, 233, 237)
PANEL   = (255, 255, 255)
BORDER  = (207, 211, 218)
TEXT    = (60, 64, 72)
MUTED   = (140, 146, 156)
GREEN   = (48, 187, 120)
GREENBG = (233, 250, 241)
ORANGE  = (255, 107, 53)
LINE    = (176, 182, 192)

def F(sz, bold=False):
    p = "/usr/share/fonts/truetype/google-fonts/Poppins-%s.ttf" % ("SemiBold" if bold else "Regular")
    try: return ImageFont.truetype(p, sz)
    except Exception:
        try: return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""), sz)
        except Exception: return ImageFont.load_default()

NODES = [
    ("Schedule Trigger",   130, 500),
    ("Read Calendar",      400, 500),
    ("ChatGPT Generate",   670, 500),
    ("UTM Enforce",        940, 500),
    ("Bluesky",           1240, 250),
    ("Mastodon",          1240, 360),
    ("Telegram",          1240, 470),
    ("Truth Social",      1240, 580),
    ("Blogger",           1240, 690),
    ("dev.to",            1240, 800),
    ("Hashnode",          1240, 910),
]
NW, NH = 200, 62

def rr(d, box, r, fill, outline=None, w=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)

def frame(i):
    t = i / FPS
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # dotted canvas grid
    for x in range(0, W, 26):
        for y in range(120, H, 26):
            d.point((x, y), fill=GRID)

    # top chrome
    d.rectangle([0, 0, W, 64], fill=PANEL)
    d.line([0, 64, W, 64], fill=BORDER)
    d.rounded_rectangle([24, 18, 40, 34], radius=4, fill=ORANGE)
    d.text((54, 22), "Nexalead Text Autopilot", font=F(19, True), fill=TEXT)
    d.text((330, 24), "Executions", font=F(15), fill=MUTED)
    rr(d, [W - 250, 16, W - 150, 48], 6, (240, 242, 245), BORDER)
    d.text((W - 236, 24), "Inactive", font=F(14), fill=MUTED)
    rr(d, [W - 132, 16, W - 24, 48], 6, ORANGE)
    d.text((W - 118, 24), "Execute", font=F(14, True), fill=(255, 255, 255))

    # left sidebar
    d.rectangle([0, 64, 88, H], fill=PANEL)
    d.line([88, 64, 88, H], fill=BORDER)
    for k in range(5):
        rr(d, [30, 110 + k * 58, 58, 138 + k * 58], 6, (238, 240, 244))

    # sequential activation: one node lights every 0.7s
    active = int(max(0, (t - 1.0)) / 0.62)

    # connections
    for a in range(3):
        x1 = NODES[a][1] + NW; y1 = NODES[a][2] + NH // 2
        x2 = NODES[a + 1][1]; y2 = NODES[a + 1][2] + NH // 2
        col = GREEN if a < active else LINE
        d.line([x1, y1, x1 + 34, y1, x2 - 34, y2, x2, y2], fill=col, width=3 if a < active else 2)
    hub_x = NODES[3][1] + NW; hub_y = NODES[3][2] + NH // 2
    for j in range(4, len(NODES)):
        nx, ny = NODES[j][1], NODES[j][2] + NH // 2
        col = GREEN if (j - 1) < active else LINE
        d.line([hub_x, hub_y, hub_x + 40, hub_y, hub_x + 40, ny, nx, ny],
               fill=col, width=3 if (j - 1) < active else 2)

    # nodes
    for idx, (label, x, y) in enumerate(NODES):
        on = idx < active
        rr(d, [x, y, x + NW, y + NH], 10, GREENBG if on else PANEL,
           GREEN if on else BORDER, 2 if on else 1)
        rr(d, [x + 12, y + 17, x + 40, y + 45], 6, GREEN if on else (236, 238, 242))
        d.text((x + 52, y + 16), label[:16], font=F(14, True), fill=TEXT)
        d.text((x + 52, y + 36), "done" if on else "waiting",
               font=F(12), fill=GREEN if on else MUTED)
        if on:
            d.ellipse([x + NW - 26, y + 8, x + NW - 10, y + 24], fill=GREEN)

    # running counter, bottom-left
    posts = min(active * 4, 47)
    d.text((130, 960), f"{posts} posts published", font=F(26, True), fill=TEXT)
    d.text((130, 998), f"{max(0,min(active,7))} of 7 platforms complete",
           font=F(17), fill=MUTED)

    # log panel
    rr(d, [W - 470, 900, W - 40, 1040], 10, PANEL, BORDER)
    d.text((W - 450, 918), "Execution log", font=F(15, True), fill=TEXT)
    for k in range(min(3, active)):
        idx_log = max(0, min(active - 1 - k, len(NODES) - 1))
        d.text((W - 450, 948 + k * 26),
               f"OK  {NODES[idx_log][0][:22]}", font=F(13), fill=GREEN)
    return img

print("rendering frames...")
for i in range(FPS * DUR):
    frame(i).save(OUT / f"f{i:05d}.png")

subprocess.run([
    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
    "-framerate", str(FPS), "-i", str(OUT / "f%05d.png"),
    "-f", "lavfi", "-i", f"anoisesrc=d={DUR}:c=pink:a=0.02",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    "/tmp/n8n_capture.mp4"], check=True)
shutil.rmtree(OUT, ignore_errors=True)
print("wrote /tmp/n8n_capture.mp4")
