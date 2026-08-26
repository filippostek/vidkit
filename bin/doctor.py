#!/usr/bin/env python3
"""
doctor.py — preflight the whole stack before you flip anything on.

Checks every dependency, credential, endpoint and config the pipeline needs,
prints exactly what is missing and the command to fix it, and exits non-zero
if anything critical is broken.

    doctor.py                 # full check
    doctor.py --quick         # skip network calls
    doctor.py --fix           # print copy-paste remediation for failures
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

OK, WARN, FAIL = "PASS", "WARN", "FAIL"
results = []


def check(name, status, detail="", fix=""):
    results.append({"name": name, "status": status, "detail": detail, "fix": fix})
    icon = {OK: "\033[32m✓\033[0m", WARN: "\033[33m!\033[0m", FAIL: "\033[31m✗\033[0m"}[status]
    line = f"  {icon} {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def have(b):
    return shutil.which(b) is not None


def run(cmd):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def http_ok(url, timeout=8, headers=None):
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(400)
    except Exception as e:
        return None, str(e).encode()[:200]


# ---------------------------------------------------------------------------
def section(t):
    print(f"\n\033[1m{t}\033[0m")


def check_binaries():
    section("Binaries")
    for b, critical, fix in [
        ("ffmpeg", True, "apt-get install -y ffmpeg"),
        ("ffprobe", True, "apt-get install -y ffmpeg"),
        ("python3", True, "apt-get install -y python3"),
        ("auto-editor", False, "pip install auto-editor"),
        ("curl", True, "apt-get install -y curl"),
        ("jq", False, "apt-get install -y jq"),
    ]:
        if have(b):
            check(b, OK)
        else:
            check(b, FAIL if critical else WARN, "not installed", fix)


def check_ffmpeg_features():
    section("FFmpeg capabilities")
    rc, out, _ = run("ffmpeg -hide_banner -filters 2>/dev/null")
    for f, why in [("ass", "burned-in captions"),
                   ("zoompan", "camera moves"),
                   ("edgedetect", "sketch/comic styles"),
                   ("rgbashift", "glitch style"),
                   ("noise", "film grain"),
                   ("vignette", "grades")]:
        if f" {f} " in out:
            check(f"filter: {f}", OK, why)
        else:
            check(f"filter: {f}", FAIL, f"missing — {why} will break",
                  "apt-get install -y ffmpeg libass9")

    rc, out, _ = run("ffmpeg -hide_banner -encoders 2>/dev/null")
    check("encoder: libx264", OK if "libx264" in out else FAIL,
          "", "apt-get install -y ffmpeg")
    check("encoder: aac", OK if " aac " in out else FAIL, "",
          "apt-get install -y ffmpeg")


def check_fonts():
    section("Fonts")
    rc, out, _ = run("fc-list 2>/dev/null")
    if "Poppins" in out:
        check("Poppins", OK)
    elif out:
        check("Poppins", WARN, "missing, falling back to DejaVu",
              "bash bin/install.sh  (installs Poppins)")
    else:
        check("fontconfig", FAIL, "fc-list unavailable",
              "apt-get install -y fontconfig")


def check_python_libs():
    section("Python libraries")
    for mod, critical, why, fix in [
        ("faster_whisper", False, "word-level captions", "pip install faster-whisper"),
        ("kokoro", False, "voiceover", "pip install kokoro soundfile"),
        ("soundfile", False, "TTS output", "pip install soundfile"),
        ("boto3", False, "R2 upload", "pip install boto3"),
        ("PIL", False, "test mock generator", "pip install pillow"),
    ]:
        try:
            __import__(mod)
            check(mod, OK, why)
        except Exception:
            check(mod, FAIL if critical else WARN, f"missing — {why} unavailable", fix)


def check_modules():
    section("vidkit modules")
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    for m in ("render", "cinema", "styles", "generate"):
        f = here / f"{m}.py"
        if not f.exists():
            check(m, FAIL, "file missing")
            continue
        rc, _, err = run(f"python3 -c \"import ast;ast.parse(open('{f}').read())\"")
        check(m, OK if rc == 0 else FAIL, "" if rc == 0 else err[:80])


def check_selftest():
    section("Render self-test")
    here = Path(__file__).resolve().parent
    rc, out, err = run(f"cd {here.parent} && timeout 600 python3 bin/render.py --selftest 2>&1")
    passes = out.count("PASS")
    fails = out.count("FAIL")
    if rc == 0 and fails == 0:
        check("render.py --selftest", OK, f"{passes} assertions")
    else:
        check("render.py --selftest", FAIL, f"{passes} pass / {fails} fail",
              "python3 bin/render.py --selftest   # read the output")


def check_env():
    section("Environment variables")
    groups = {
        "core": [("OPENAI_API_KEY", True), ("GOOGLE_SHEET_ID", False)],
        "posting": [("TELEGRAM_BOT_TOKEN", False), ("TELEGRAM_CHANNEL_ID", False),
                    ("BLUESKY_DID", False), ("MASTODON_INSTANCE", False),
                    ("TUMBLR_BLOG_NAME", False), ("BLOGGER_BLOG_ID", False),
                    ("HASHNODE_PUBLICATION_ID", False)],
        "video": [("GITHUB_USERNAME", False), ("N8N_RENDER_CALLBACK", False),
                  ("R2_PUBLIC_BASE", False)],
        "generative": [("FAL_KEY", False)],
    }
    for g, items in groups.items():
        for var, critical in items:
            if os.environ.get(var):
                check(f"{g}: {var}", OK, "set")
            else:
                check(f"{g}: {var}", FAIL if critical else WARN, "not set",
                      f"add {var}= to docker-compose.yml under n8n environment")


def check_endpoints(quick):
    if quick:
        return
    section("Endpoints")
    cdn = os.environ.get("R2_PUBLIC_BASE") or "https://cdn.getnexalead.online"
    n8n = os.environ.get("N8N_BASE") or "https://n8n.getnexalead.online"
    for name, url in [("CDN", cdn), ("n8n", n8n)]:
        st, body = http_ok(url)
        if st and st < 500:
            check(name, OK, f"HTTP {st}")
        else:
            check(name, WARN, f"unreachable: {body.decode(errors='ignore')[:60]}",
                  "check DNS A record and Caddy vhost")

    st, _ = http_ok("https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY','')}"})
    if st == 200:
        check("OpenAI API", OK, "key valid")
    elif st == 401:
        check("OpenAI API", FAIL, "key rejected", "check OPENAI_API_KEY")
    else:
        check("OpenAI API", WARN, "could not verify")


def check_disk():
    section("Resources")
    try:
        st = shutil.disk_usage("/")
        free_gb = st.free / 1e9
        check("disk free", OK if free_gb > 5 else WARN, f"{free_gb:.1f} GB",
              "prune /opt/n8n/videos and ~/.vidkit/generated")
    except Exception:
        pass
    try:
        mem = Path("/proc/meminfo").read_text()
        total = int([l for l in mem.splitlines() if l.startswith("MemTotal")][0].split()[1]) / 1e6
        swap = int([l for l in mem.splitlines() if l.startswith("SwapTotal")][0].split()[1]) / 1e6
        check("RAM", OK if total > 1.5 else WARN, f"{total:.1f} GB")
        if swap < 0.5 and total < 4:
            check("swap", FAIL, "no swap on a small box — FFmpeg will get OOM-killed",
                  "fallocate -l 4G /swapfile && chmod 600 /swapfile && "
                  "mkswap /swapfile && swapon /swapfile")
        else:
            check("swap", OK, f"{swap:.1f} GB")
    except Exception:
        pass


def check_spend():
    section("Generative spend")
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    try:
        import generate
        spent = generate.spent_this_month()
        check("month-to-date", OK if spent < 10 else WARN, f"${spent:.2f}")
    except Exception as e:
        check("ledger", WARN, str(e)[:60])


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip network checks")
    ap.add_argument("--fix", action="store_true", help="print remediation commands")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    print("\n\033[1mvidkit doctor\033[0m")
    check_binaries()
    check_ffmpeg_features()
    check_fonts()
    check_python_libs()
    check_modules()
    check_env()
    check_disk()
    check_spend()
    check_endpoints(a.quick)
    if not a.quick:
        check_selftest()

    fails = [r for r in results if r["status"] == FAIL]
    warns = [r for r in results if r["status"] == WARN]

    print(f"\n\033[1mSummary\033[0m  "
          f"\033[32m{len([r for r in results if r['status']==OK])} pass\033[0m  "
          f"\033[33m{len(warns)} warn\033[0m  "
          f"\033[31m{len(fails)} fail\033[0m")

    if a.fix and (fails or warns):
        print("\n\033[1mRemediation\033[0m")
        seen = set()
        for r in fails + warns:
            if r["fix"] and r["fix"] not in seen:
                seen.add(r["fix"])
                print(f"  # {r['name']}\n  {r['fix']}\n")

    if a.json:
        print(json.dumps(results, indent=2))

    if fails:
        print("\nCritical failures present. Fix them before enabling any workflow.")
        return 1
    if warns:
        print("\nUsable, with optional features degraded. Run --fix for commands.")
    else:
        print("\nEverything green. Safe to activate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
