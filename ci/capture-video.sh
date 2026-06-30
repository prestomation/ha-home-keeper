#!/usr/bin/env bash
# Capture the Home Keeper panel *video* walkthrough and transcode it for embedding.
#
# Produces, under docs/videos/ (override with VIDEO_DIR):
#   walkthrough.webm  — raw Chromium recording (intermediate)
#   walkthrough.mp4   — h264/yuv420p, faststart — primary embed (<video>)
#   walkthrough.gif   — palette-optimised fallback that embeds like a screenshot (<img>)
#
# Assumes (same as ci/test-e2e.sh): the Home Assistant Docker container is already
# running on $HA_URL, the panel JS is built, and Chromium is installed. The quickest
# way to satisfy that is to leave HA up first:
#   KEEP_UP=1 bash ci/e2e-up.sh        # build panel + start HA (and run the suite)
#   bash ci/capture-video.sh           # then capture the video
#
# In the Claude Code remote environment, point Playwright at the pre-installed
# Chromium (the CDN is blocked) — playwright.config.ts wires CHROMIUM_EXEC up:
#   CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1) \
#     bash ci/capture-video.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VIDEO_DIR="${VIDEO_DIR:-$ROOT/docs/videos}"
# GIF width / framerate — keep the fallback small. The mp4 keeps full resolution.
GIF_WIDTH="${GIF_WIDTH:-820}"
GIF_FPS="${GIF_FPS:-12}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[capture-video] ffmpeg is required (transcodes webm -> mp4/gif). Install it and retry." >&2
  exit 1
fi

mkdir -p "$VIDEO_DIR"

echo "[capture-video] recording walkthrough (Playwright)..."
( cd tests/e2e
  if [ ! -d node_modules ]; then npm ci 2>/dev/null || npm install --no-audit --no-fund; fi
  VIDEO_DIR="$VIDEO_DIR" npx playwright test --config=walkthrough.config.ts )

WEBM="$VIDEO_DIR/walkthrough.webm"
MP4="$VIDEO_DIR/walkthrough.mp4"
GIF="$VIDEO_DIR/walkthrough.gif"
if [ ! -f "$WEBM" ]; then
  echo "[capture-video] expected recording not found at $WEBM" >&2
  exit 1
fi

echo "[capture-video] transcoding -> mp4 (h264)..."
ffmpeg -y -loglevel error -i "$WEBM" \
  -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -movflags +faststart -an "$MP4"

echo "[capture-video] transcoding -> gif (fallback)..."
# Two-pass palette for a clean, small GIF.
PALETTE="$(mktemp --suffix=.png)"
trap 'rm -f "$PALETTE"' EXIT
ffmpeg -y -loglevel error -i "$WEBM" \
  -vf "fps=${GIF_FPS},scale=${GIF_WIDTH}:-1:flags=lanczos,palettegen" "$PALETTE"
ffmpeg -y -loglevel error -i "$WEBM" -i "$PALETTE" \
  -lavfi "fps=${GIF_FPS},scale=${GIF_WIDTH}:-1:flags=lanczos[x];[x][1:v]paletteuse" "$GIF"

echo "[capture-video] done:"
ls -lh "$MP4" "$GIF" "$WEBM" | sed 's/^/[capture-video]   /'
