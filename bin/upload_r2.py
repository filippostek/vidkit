#!/usr/bin/env python3
"""
Upload rendered media to Cloudflare R2 (zero egress) and print public URLs.

Env:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
  R2_BUCKET, R2_PUBLIC_BASE   e.g. https://cdn.getnexalead.online

Usage:
  upload_r2.py --file out.mp4 --also out.jpg
  upload_r2.py --file out.mp4 --prefix nexalead/2026-08
"""
import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--also", nargs="*", default=[])
    ap.add_argument("--prefix", default=None,
                    help="key prefix, default videos/YYYY-MM")
    args = ap.parse_args()

    need = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        sys.stderr.write(f"missing env: {', '.join(missing)}\n")
        return 2

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        sys.stderr.write("pip install boto3\n")
        return 2

    acct = os.environ["R2_ACCOUNT_ID"]
    bucket = os.environ["R2_BUCKET"]
    public = os.environ.get("R2_PUBLIC_BASE", "").rstrip("/")
    prefix = args.prefix or f"videos/{datetime.utcnow():%Y-%m}"

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        region_name="auto",
    )

    urls = {}
    for f in [args.file, *args.also]:
        p = Path(f)
        if not p.exists():
            sys.stderr.write(f"skip missing {p}\n")
            continue
        key = f"{prefix}/{p.name}"
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        s3.upload_file(
            str(p), bucket, key,
            ExtraArgs={"ContentType": ctype,
                       "CacheControl": "public, max-age=31536000"},
        )
        url = f"{public}/{key}" if public else f"r2://{bucket}/{key}"
        urls[p.suffix.lstrip(".")] = url
        print(f"[up] {p.name} -> {url}", file=sys.stderr)

    print(json.dumps({
        "video_url": urls.get("mp4", ""),
        "thumbnail_url": urls.get("jpg", ""),
        "all": urls,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
