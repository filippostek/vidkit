#!/usr/bin/env bash
# One-command demo: renders a sample short so you can see the output format.
set -e
OUT="${1:-demo.mp4}"
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "testsrc2=size=1920x1080:rate=30:duration=8" \
  -f lavfi -i "sine=frequency=200:duration=8" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac -shortest /tmp/_vk_raw.mp4
python3 "$(dirname "$0")/render.py" \
  --input /tmp/_vk_raw.mp4 --out "$OUT" --brand nexalead \
  --hook '$2.14 ran this all week.' \
  --script 'One sentence in. Twelve platforms out. Total cost two dollars fourteen.' \
  --stats '47 posts|12 platforms|$2.14' \
  --no-tts --no-asr --preset ultrafast --crf 26
rm -f /tmp/_vk_raw.mp4
echo "wrote $OUT"
