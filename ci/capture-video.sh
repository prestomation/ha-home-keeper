#!/usr/bin/env bash
# Capture the Home Keeper panel *video* walkthrough and transcode it for embedding.
#
# Produces, under docs/videos/ (override with VIDEO_DIR):
#   <tour>.webm  — raw Chromium recording (intermediate)
#   <tour>.mp4   — h264/yuv420p, faststart — primary embed (<video>)
#   <tour>.gif   — palette-optimised fallback that embeds like a screenshot (<img>)
#
# One <tour> per entry in walkthrough.capture.ts's TOURS table: `walkthrough` (the
# desktop layout) and `walkthrough-phone`.
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

# Each tour records its own WebM (see the TOURS table in walkthrough.capture.ts).
# name:gif_width — the gif is what the PR comment embeds, so the phone one is narrow
# on purpose; upscaling a 390px source to 820 would give a ~1774px-tall gif.
VARIANTS="${VARIANTS:-walkthrough:${GIF_WIDTH:-820} walkthrough-phone:${GIF_WIDTH_PHONE:-300}}"

PALETTE="$(mktemp --suffix=.png)"
trap 'rm -f "$PALETTE"' EXIT

produced=""
for variant in $VARIANTS; do
  name="${variant%%:*}"
  width="${variant##*:}"
  WEBM="$VIDEO_DIR/$name.webm"
  MP4="$VIDEO_DIR/$name.mp4"
  GIF="$VIDEO_DIR/$name.gif"

  # Transcode whatever the capture actually produced. A missing one is not fatal
  # here: the tours are two independent tests, this whole job is a soft gate, and
  # one flaky tour should not throw away the other's embed. Nothing at all is.
  if [ ! -f "$WEBM" ]; then
    echo "[capture-video] no recording at $WEBM — skipping $name" >&2
    continue
  fi

  echo "[capture-video] $name: transcoding -> mp4 (h264)..."
  # The scale filter only rounds an odd dimension to even; yuv420p needs that, and a
  # phone viewport is one config change away from being odd.
  ffmpeg -y -loglevel error -i "$WEBM" \
    -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \
    -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -movflags +faststart -an "$MP4"

  echo "[capture-video] $name: transcoding -> gif (fallback)..."
  # Two-pass palette for a clean, small GIF.
  ffmpeg -y -loglevel error -i "$WEBM" \
    -vf "fps=${GIF_FPS},scale=${width}:-1:flags=lanczos,palettegen" "$PALETTE"
  ffmpeg -y -loglevel error -i "$WEBM" -i "$PALETTE" \
    -lavfi "fps=${GIF_FPS},scale=${width}:-1:flags=lanczos[x];[x][1:v]paletteuse" "$GIF"

  produced="$produced $name"
done

if [ -z "$produced" ]; then
  echo "[capture-video] no recordings found in $VIDEO_DIR at all" >&2
  exit 1
fi

echo "[capture-video] done:$produced"
ls -lh "$VIDEO_DIR"/*.mp4 "$VIDEO_DIR"/*.gif | sed 's/^/[capture-video]   /'
