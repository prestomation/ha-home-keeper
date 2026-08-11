#!/usr/bin/env bash
# Stage the custom_components that tests/upgrade mounts: the three Home Keeper glue
# integrations plus the two upstreams they read entities from.
#
# A glue is inert without its upstream — bambu-lab reads `bambu_lab` firmware
# entities, battery-notes reads Battery Notes' battery-low sensors — so the upgrade
# suite needs both halves. The glues are fetched real (their logic is the thing under
# test); the upstreams are stubbed from tests/upgrade/stubs, because the real ones
# need hardware or vendor-cloud credentials. Pawsistant needs no upstream at all — it
# owns its own devices.
#
# Every repo is pinned to a COMMIT SHA, not a branch. The upgrade suite already has
# two moving parts it is deliberately measuring (the old and new HA versions); if it
# also floated on five third-party HEADs, a red run would be unattributable. Bump the
# pins deliberately, in their own commit, so a bump is a reviewable event.
#
# Usage:  bash ci/fetch-glues.sh
# Override a pin for a one-off experiment:  BAMBU_GLUE_REF=<sha> bash ci/fetch-glues.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$ROOT/tests/upgrade/custom_components"

# ── pins ─────────────────────────────────────────────────────────────────────
# Glues (this project's own companions).
BN_GLUE_REPO="${BN_GLUE_REPO:-https://github.com/prestomation/ha-home-keeper-battery-notes}"
BN_GLUE_REF="${BN_GLUE_REF:-946a1b63781c4f454a3e4c23794574818af80b0a}"
BAMBU_GLUE_REPO="${BAMBU_GLUE_REPO:-https://github.com/prestomation/ha-home-keeper-bambu-lab}"
BAMBU_GLUE_REF="${BAMBU_GLUE_REF:-50235e254c3d2089a0e4d6575e3a3b30c1b0349d}"
PAW_REPO="${PAW_REPO:-https://github.com/prestomation/Pawsistant}"
PAW_REF="${PAW_REF:-4763e55685d308358f65604236d816f05d69caf1}"

# The last released Home Keeper, staged separately so the upgrade suite can run
# phase 1 as the *previous* version. Without it both boots would run the code in this
# working tree, which is not a journey any user takes — a real upgrade changes Home
# Assistant and Home Keeper together, and the interesting question is what the new
# version does with state the old one left behind.
HK_PREV_REPO="${HK_PREV_REPO:-https://github.com/prestomation/ha-home-keeper}"
HK_PREV_REF="${HK_PREV_REF:-4ac32effee016f4805a670c6dfc55c1be3c44c39}"

rm -rf "$STAGE"
mkdir -p "$STAGE"

# Clone at a pinned SHA. `--depth 1 --branch` only accepts a ref name, so fetch the
# single commit instead — cheap, and it works for a SHA that is not a branch tip.
# fetch <repo> <ref> <component> [dest]  — dest defaults to $STAGE.
fetch() {
  local repo="$1" ref="$2" component="$3" dest="${4:-$STAGE}"
  local tmp
  tmp="$(mktemp -d)"
  echo "[fetch-glues] $component <- $repo@${ref:0:12}"
  git -C "$tmp" init -q
  git -C "$tmp" remote add origin "$repo"
  git -C "$tmp" fetch -q --depth 1 origin "$ref"
  git -C "$tmp" checkout -q FETCH_HEAD
  if [ ! -d "$tmp/custom_components/$component" ]; then
    echo "[fetch-glues] ERROR: $repo@$ref has no custom_components/$component" >&2
    rm -rf "$tmp"
    return 1
  fi
  cp -r "$tmp/custom_components/$component" "$dest/"
  rm -rf "$tmp"
}

fetch "$BN_GLUE_REPO" "$BN_GLUE_REF" "home_keeper_battery_notes"
fetch "$BAMBU_GLUE_REPO" "$BAMBU_GLUE_REF" "home_keeper_bambu_lab"
fetch "$PAW_REPO" "$PAW_REF" "pawsistant"

# The *upstreams* the glues read (`battery_notes`, `bambu_lab`) are stubbed, not
# fetched. The real ones need discovered hardware or vendor-cloud credentials, which
# an upgrade test can't supply — and what the glues actually consume from them is a
# narrow set of registry shapes the stubs reproduce exactly. See tests/upgrade/stubs.
# `hk_upgrade_source` owns the "physical" devices the upstreams attach to.
#
# Copied in rather than mounted: the container bind-mounts this whole directory
# read-only at /config/custom_components, and Docker can't create nested mountpoints
# underneath a read-only bind.
echo "[fetch-glues] upstream stubs <- tests/upgrade/stubs"
cp -r "$ROOT/tests/upgrade/stubs/." "$STAGE/"

# Home Keeper itself comes from the working tree, not a clone — the whole point is to
# test the code in this branch. The panel JS is a gitignored build artifact, so build
# it if it is missing; the upgrade suite is REST/websocket-only, but a missing panel
# makes the HA log noisy enough to obscure real errors.
echo "[fetch-glues] home_keeper <- working tree"
cp -r "$ROOT/custom_components/home_keeper" "$STAGE/"
if [ ! -f "$STAGE/home_keeper/frontend/home-keeper-panel.js" ] \
   && [ "${SKIP_PANEL_BUILD:-0}" != "1" ]; then
  echo "[fetch-glues] building the panel..."
  bash "$ROOT/ci/build-panel.sh"
  cp -r "$ROOT/custom_components/home_keeper/frontend/." "$STAGE/home_keeper/frontend/"
fi

# Both Home Keeper builds are staged *alongside* the mounted tree, and conftest.py
# swaps whichever one a step needs into it. Staging both here (rather than letting the
# harness cache a copy on first use) is deliberate: a cached copy silently survives
# between runs, so an edit to the integration would not reach the container and the
# suite would report on stale code. That happened once; don't reintroduce it.
PREV_STAGE="$ROOT/tests/upgrade/home_keeper_previous"
rm -rf "$PREV_STAGE"
mkdir -p "$PREV_STAGE"
fetch "$HK_PREV_REPO" "$HK_PREV_REF" "home_keeper" "$PREV_STAGE"
# The released panel JS is a build artifact too; the upgrade suite is API-only.

WT_STAGE="$ROOT/tests/upgrade/home_keeper_working_tree"
rm -rf "$WT_STAGE"
mkdir -p "$WT_STAGE"
echo "[fetch-glues] home_keeper (working tree copy) -> $WT_STAGE"
cp -r "$STAGE/home_keeper" "$WT_STAGE/"

echo "[fetch-glues] staged into $STAGE:"
ls -1 "$STAGE"
echo "[fetch-glues] previous release staged into $PREV_STAGE"
