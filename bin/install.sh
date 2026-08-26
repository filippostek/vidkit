#!/usr/bin/env bash
# vidkit installer — Ubuntu/Debian. Idempotent, safe to re-run.
# Installs: ffmpeg, fonts, python deps, auto-editor, faster-whisper, kokoro TTS
# Adds a swapfile (critical on 2GB Hetzner boxes) and a media dir served by Caddy.
set -euo pipefail

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
say() { echo "${BOLD}${GREEN}==>${RESET} $*"; }
warn() { echo "${BOLD}${YELLOW}[!]${RESET} $*"; }

VIDKIT_DIR="${VIDKIT_DIR:-/opt/vidkit}"
MEDIA_DIR="${MEDIA_DIR:-/opt/n8n/videos}"
SWAP_GB="${SWAP_GB:-4}"
FULL="${FULL:-0}"          # FULL=1 also installs kokoro + faster-whisper (~2GB)

# ---------------------------------------------------------------- swap
if ! swapon --show | grep -q .; then
  say "Creating ${SWAP_GB}GB swapfile (prevents OOM on 2GB boxes)"
  fallocate -l "${SWAP_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10 >/dev/null
  grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf
else
  say "Swap already present — skipping"
fi

# ---------------------------------------------------------------- packages
say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  ffmpeg python3 python3-pip python3-venv \
  fonts-dejavu-core fontconfig curl ca-certificates \
  libass9 unzip jq >/dev/null

# Poppins (brand font). Falls back silently if the download fails.
if ! fc-list | grep -qi poppins; then
  say "Installing Poppins font"
  mkdir -p /usr/share/fonts/truetype/poppins
  for w in Regular Medium SemiBold Bold; do
    curl -fsSL -o "/usr/share/fonts/truetype/poppins/Poppins-${w}.ttf" \
      "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-${w}.ttf" || \
      warn "could not fetch Poppins-${w}"
  done
  fc-cache -f >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------- python env
say "Creating python venv at ${VIDKIT_DIR}/venv"
mkdir -p "$VIDKIT_DIR"
python3 -m venv "$VIDKIT_DIR/venv" 2>/dev/null || true
PIP="$VIDKIT_DIR/venv/bin/pip"
$PIP install -q --upgrade pip wheel

say "Installing auto-editor (silence removal)"
$PIP install -q auto-editor || warn "auto-editor install failed — renders still work, just untrimmed"

if [ "$FULL" = "1" ]; then
  say "Installing faster-whisper (captions) — this pulls ~1GB"
  $PIP install -q faster-whisper || warn "faster-whisper failed"
  say "Installing kokoro TTS (voiceover) — this pulls ~1GB"
  $PIP install -q kokoro soundfile || warn "kokoro failed — use --no-tts"
else
  warn "Skipping kokoro + faster-whisper (run with FULL=1 to include them)."
  warn "Without them: use --no-tts --no-asr, or pass --srt for captions."
fi

# ---------------------------------------------------------------- wiring
say "Installing render.py"
install -m 0755 "$(dirname "$0")/render.py" "$VIDKIT_DIR/render.py"

cat > /usr/local/bin/vidkit <<EOF
#!/usr/bin/env bash
exec "$VIDKIT_DIR/venv/bin/python" "$VIDKIT_DIR/render.py" "\$@"
EOF
chmod +x /usr/local/bin/vidkit

mkdir -p "$MEDIA_DIR"
chmod 755 "$MEDIA_DIR"

# ---------------------------------------------------------------- caddy cdn
CADDYFILE="/opt/n8n/Caddyfile"
if [ -f "$CADDYFILE" ] && ! grep -q "cdn\." "$CADDYFILE"; then
  say "Adding cdn vhost to Caddyfile"
  cat >> "$CADDYFILE" <<'EOF'

cdn.getnexalead.online {
  root * /srv/videos
  file_server browse
  header Access-Control-Allow-Origin *
  header Cache-Control "public, max-age=31536000"
}
EOF
  warn "Add this volume to the caddy service in docker-compose.yml:"
  warn "      - ./videos:/srv/videos"
  warn "Then: cd /opt/n8n && docker compose up -d --force-recreate"
  warn "And add DNS: A record  cdn  ->  this server IP"
fi

# ---------------------------------------------------------------- verify
say "Verifying"
vidkit --selftest && say "vidkit installed. Try: vidkit --input raw.mp4 --out out.mp4 --hook 'Hello'"
