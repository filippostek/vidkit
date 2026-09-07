#!/usr/bin/env python3
"""
generate.py — direct access to the same models Higgsfield resells.

Higgsfield is an aggregator: Kling, WAN, Sora, Veo, Seedance, Flux, MiniMax.
It adds a credit layer on top, credits expire after 90 days, and generated
files stop resolving after 7 days. This module calls the underlying providers
directly, caps spend, and keeps every artifact forever on your own disk.

Design rules:
  1. Hard spend cap. The script refuses to exceed it. No surprise bills.
  2. Cache by prompt hash. You never pay twice for the same prompt.
  3. Download immediately. Provider URLs expire; your files do not.
  4. Dry run by default when no key is present, so cost is knowable up front.

    generate.py --estimate --model wan --seconds 5 --count 4
    generate.py --prompt "abstract data flowing through dark space" --model wan
    generate.py --compare
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CACHE = Path(os.environ.get("VIDKIT_GEN_CACHE", "~/.vidkit/generated")).expanduser()
LEDGER = CACHE / "_ledger.json"

# ---------------------------------------------------------------------------
# MODEL CATALOGUE
# Prices are per-second of output unless noted. Verify before relying on them —
# providers reprice often. Run --compare to see the table with your settings.
# ---------------------------------------------------------------------------
MODELS = {
    "wan": {
        "provider": "fal",
        "endpoint": "fal-ai/wan-t2v",
        "usd_per_sec": 0.05,
        "max_seconds": 5,
        "license": "Apache-2.0 weights (self-hostable)",
        "note": "Best value. Also runs locally in ComfyUI for $0.",
    },
    "wan-i2v": {
        "provider": "fal",
        "endpoint": "fal-ai/wan-i2v",
        "usd_per_sec": 0.05,
        "max_seconds": 5,
        "license": "Apache-2.0 weights",
        "note": "Image-to-video. Animate a still you already own.",
    },
    "ltx": {
        "provider": "fal",
        "endpoint": "fal-ai/ltx-video",
        "usd_per_sec": 0.04,
        "max_seconds": 8,
        "license": "open weights",
        "note": "Fastest. Native audio+video in one pass on 2.5.",
    },
    "kling": {
        "provider": "fal",
        "endpoint": "fal-ai/kling-video/v2/master/text-to-video",
        "usd_per_sec": 0.14,
        "max_seconds": 10,
        "license": "proprietary API",
        "note": "Strong character motion. Higgsfield's cheapest tier.",
    },
    "minimax": {
        "provider": "fal",
        "endpoint": "fal-ai/minimax-video",
        "usd_per_sec": 0.10,
        "max_seconds": 6,
        "license": "proprietary API",
        "note": "Fast short-form.",
    },
    "veo": {
        "provider": "fal",
        "endpoint": "fal-ai/veo3",
        "usd_per_sec": 0.50,
        "max_seconds": 8,
        "license": "proprietary API",
        "note": "Premium. Only worth it for hero shots.",
    },
    "local": {
        "provider": "comfyui",
        "endpoint": "http://127.0.0.1:8188",
        "usd_per_sec": 0.0,
        "max_seconds": 10,
        "license": "your hardware",
        "note": "ComfyUI on your own GPU. Zero marginal cost.",
    },
}

# What Higgsfield charges for the same thing, after real-world retries.
HIGGSFIELD_REAL = {
    "kling": (0.61, 1.18),
    "veo": (3.36, 12.00),
    "sora": (3.36, 12.00),
}


# ---------------------------------------------------------------------------
def _ledger():
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text())
        except Exception:
            pass
    return {"spent_usd": 0.0, "runs": []}


def _save_ledger(l):
    CACHE.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(l, indent=2))


def spent_this_month():
    l = _ledger()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return round(sum(r["cost"] for r in l["runs"]
                     if r["at"].startswith(month)), 4)


def cost_of(model, seconds, count=1):
    m = MODELS.get(model)
    if not m:
        raise SystemExit(f"unknown model '{model}'. options: {', '.join(MODELS)}")
    sec = min(seconds, m["max_seconds"])
    return round(m["usd_per_sec"] * sec * count, 4)


def cache_key(model, prompt, seconds, extra=""):
    h = hashlib.sha256(f"{model}|{prompt}|{seconds}|{extra}".encode()).hexdigest()[:16]
    return h


def cached_path(key):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{key}.mp4"
    return p if p.exists() else None


# ---------------------------------------------------------------------------
def generate(prompt, model="wan", seconds=5, cap=5.00, image=None,
             force=False, dry=False):
    """
    Returns dict with path + cost. Refuses to exceed the monthly cap.
    """
    m = MODELS[model]
    sec = min(seconds, m["max_seconds"])
    key = cache_key(model, prompt, sec, image or "")
    cost = cost_of(model, sec)

    hit = cached_path(key)
    if hit and not force:
        print(f"[cache] already generated, $0.00 — {hit}", file=sys.stderr)
        return {"path": str(hit), "cost": 0.0, "cached": True, "key": key}

    already = spent_this_month()
    if already + cost > cap:
        raise SystemExit(
            f"REFUSED: this run costs ${cost:.2f}, spent ${already:.2f} "
            f"this month, cap is ${cap:.2f}. Raise --cap deliberately."
        )

    if dry:
        print(json.dumps({
            "would_generate": True, "model": model, "seconds": sec,
            "cost_usd": cost, "spent_this_month": already,
            "remaining_under_cap": round(cap - already - cost, 4),
            "cache_key": key,
        }, indent=2))
        return {"path": None, "cost": cost, "cached": False, "key": key,
                "dry": True}

    if m["provider"] == "fal":
        url = _fal(m["endpoint"], prompt, sec, image)
    elif m["provider"] == "comfyui":
        url = _comfy(m["endpoint"], prompt, sec)
    else:
        raise SystemExit(f"provider {m['provider']} not implemented")

    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{key}.mp4"
    print(f"[dl] {url[:70]}...", file=sys.stderr)
    urllib.request.urlretrieve(url, out)

    (CACHE / f"{key}.json").write_text(json.dumps({
        "prompt": prompt, "model": model, "seconds": sec,
        "cost_usd": cost, "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
    }, indent=2))

    l = _ledger()
    l["runs"].append({"at": datetime.now(timezone.utc).isoformat(), "model": model,
                      "cost": cost, "key": key, "prompt": prompt[:120]})
    l["spent_usd"] = round(l["spent_usd"] + cost, 4)
    _save_ledger(l)

    print(f"[ok] ${cost:.3f} — {out}", file=sys.stderr)
    return {"path": str(out), "cost": cost, "cached": False, "key": key}


def _fal(endpoint, prompt, seconds, image=None):
    key = os.environ.get("FAL_KEY")
    if not key:
        raise SystemExit("FAL_KEY not set. Get one at fal.ai/dashboard/keys")
    payload = {"prompt": prompt, "duration": seconds}
    if image:
        payload["image_url"] = image
    req = urllib.request.Request(
        f"https://fal.run/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Key {key}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read())
    url = _find_media_url(data)
    if not url:
        raise SystemExit(
            "Could not locate a media URL in the provider response.\n"
            "This is the most likely first-run failure — providers change\n"
            "their response shape. Paste this into the issue and it takes\n"
            "one line to fix:\n\n" + json.dumps(data, indent=2)[:1200]
        )
    return url


def _find_media_url(obj, _depth=0):
    """
    Recursively locate the first plausible media URL in an arbitrary response.
    Provider payload shapes drift constantly; this survives that.
    """
    if _depth > 6:
        return None
    if isinstance(obj, str):
        low = obj.lower()
        if obj.startswith("http") and any(
            low.split("?")[0].endswith(e) for e in (".mp4", ".webm", ".mov", ".m4v")
        ):
            return obj
        return None
    if isinstance(obj, dict):
        # prefer conventional keys first
        for k in ("video", "output", "videos", "url", "video_url",
                  "result", "data", "assets"):
            if k in obj:
                hit = _find_media_url(obj[k], _depth + 1)
                if hit:
                    return hit
        for v in obj.values():
            hit = _find_media_url(v, _depth + 1)
            if hit:
                return hit
        return None
    if isinstance(obj, (list, tuple)):
        for v in obj:
            hit = _find_media_url(v, _depth + 1)
            if hit:
                return hit
    return None


def _comfy(base, prompt, seconds):
    raise SystemExit(
        "ComfyUI path needs a workflow JSON for your local models.\n"
        "Install ComfyUI (126k stars, GPL-3.0), load the first-party LTX or\n"
        "WAN template, export the API-format workflow, then wire it here.\n"
        "Marginal cost after that is $0."
    )


# ---------------------------------------------------------------------------
def compare(seconds=5, per_month=8):
    print(f"\nCost for {per_month} clips of {seconds}s per month\n")
    print(f"  {'option':<34} {'per clip':>10} {'per month':>11}")
    print("  " + "-" * 57)
    for name, m in MODELS.items():
        c = cost_of(name, seconds)
        print(f"  {name + ' (direct, ' + m['provider'] + ')':<34} "
              f"{'$' + format(c, '.3f'):>10} {'$' + format(c * per_month, '.2f'):>11}")
    print()
    for name, (lo, hi) in HIGGSFIELD_REAL.items():
        print(f"  {'Higgsfield ' + name + ' (after retries)':<34} "
              f"{'$' + format(lo, '.2f') + '-' + format(hi, '.2f'):>10} "
              f"{'$' + format(lo * per_month, '.2f') + '-' + format(hi * per_month, '.2f'):>11}")
    print(f"\n  {'Higgsfield subscription floor':<34} {'':>10} "
          f"{'$15-99/mo':>11}")
    print("  Credits expire after 90 days. Generated files stop resolving "
          "after 7 days.\n")
    print(f"  Spent this month via this tool: ${spent_this_month():.2f}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt")
    ap.add_argument("--model", default="wan", choices=list(MODELS))
    ap.add_argument("--seconds", type=int, default=5)
    ap.add_argument("--image", help="image url for image-to-video")
    ap.add_argument("--cap", type=float, default=5.00,
                    help="hard monthly spend cap in USD")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="ignore cache")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--ledger", action="store_true")
    a = ap.parse_args()

    if a.compare:
        compare(a.seconds, a.count if a.count > 1 else 8)
        return 0
    if a.ledger:
        l = _ledger()
        print(json.dumps({"spent_all_time": l["spent_usd"],
                          "spent_this_month": spent_this_month(),
                          "runs": len(l["runs"])}, indent=2))
        return 0
    if a.estimate:
        c = cost_of(a.model, a.seconds, a.count)
        print(json.dumps({
            "model": a.model, "seconds": a.seconds, "count": a.count,
            "total_usd": c, "per_clip_usd": round(c / max(a.count, 1), 4),
            "spent_this_month": spent_this_month(),
        }, indent=2))
        return 0
    if not a.prompt:
        ap.error("--prompt required (or use --compare / --estimate)")

    dry = a.dry_run or not os.environ.get("FAL_KEY")
    if dry and not a.dry_run:
        print("[note] FAL_KEY not set — running as dry run", file=sys.stderr)
    for i in range(a.count):
        generate(a.prompt, a.model, a.seconds, a.cap, a.image, a.force, dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
