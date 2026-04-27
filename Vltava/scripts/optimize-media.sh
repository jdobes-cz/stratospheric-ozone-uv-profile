#!/usr/bin/env bash
#
# Generates responsive image and video variants for the Vltava gallery.
# Reads originals from Vltava/images/, writes to Vltava/images/optimized/.
# Idempotent: skips outputs that already exist.
#
# Per JPG source: 480w, 1200w, 2000w in JPEG and WebP (six files).
# Per MP4 source: 720p H.264 with HDR->SDR tonemap + 1280w poster JPG.
#
# Run from anywhere: paths resolve relative to this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/../images" && pwd)"
OUT_DIR="$SRC_DIR/optimized"
mkdir -p "$OUT_DIR"

IMG_WIDTHS=(480 1200 2000)
JPEG_QUALITY=82
WEBP_QUALITY=78

JPG_COUNT=0
MP4_COUNT=0
SKIPPED=0
GENERATED=0

# ---------- Images ----------
shopt -s nullglob nocaseglob
for src in "$SRC_DIR"/*.jpg "$SRC_DIR"/*.jpeg; do
  base="$(basename "$src")"
  base="${base%.*}"
  JPG_COUNT=$((JPG_COUNT + 1))
  for w in "${IMG_WIDTHS[@]}"; do
    jpg_out="$OUT_DIR/${base}-${w}.jpg"
    webp_out="$OUT_DIR/${base}-${w}.webp"
    if [[ ! -f "$jpg_out" ]]; then
      convert "$src" -auto-orient -strip -resize "${w}x>" \
              -quality "$JPEG_QUALITY" "$jpg_out"
      GENERATED=$((GENERATED + 1))
    else
      SKIPPED=$((SKIPPED + 1))
    fi
    if [[ ! -f "$webp_out" ]]; then
      convert "$src" -auto-orient -strip -resize "${w}x>" \
              -quality "$WEBP_QUALITY" "$webp_out"
      GENERATED=$((GENERATED + 1))
    else
      SKIPPED=$((SKIPPED + 1))
    fi
  done
  printf '  img  %s\n' "$base"
done
shopt -u nocaseglob

# ---------- Videos ----------
# HDR10 -> SDR BT.709 tonemap chain via zscale + tonemap; scale to 720p height.
# -movflags +faststart moves the moov atom to the front for instant playback.
TONEMAP_VF="zscale=t=linear:npl=100,format=gbrpf32le,tonemap=tonemap=hable:desat=0,zscale=t=bt709:p=bt709:m=bt709:r=tv,format=yuv420p,scale=-2:720"

for src in "$SRC_DIR"/*.mp4; do
  base="$(basename "$src")"
  base="${base%.*}"
  MP4_COUNT=$((MP4_COUNT + 1))
  mp4_out="$OUT_DIR/${base}-720.mp4"
  poster_out="$OUT_DIR/${base}-poster.jpg"

  if [[ ! -f "$mp4_out" ]]; then
    ffmpeg -hide_banner -loglevel warning -y -i "$src" \
      -vf "$TONEMAP_VF" \
      -c:v libx264 -crf 24 -preset medium -pix_fmt yuv420p \
      -c:a aac -b:a 96k -ac 2 \
      -movflags +faststart \
      "$mp4_out"
    GENERATED=$((GENERATED + 1))
  else
    SKIPPED=$((SKIPPED + 1))
  fi

  if [[ ! -f "$poster_out" ]]; then
    ffmpeg -hide_banner -loglevel warning -y -ss 1 -i "$src" \
      -frames:v 1 \
      -vf "${TONEMAP_VF%,scale=*},scale=1280:-2" \
      -q:v 3 \
      "$poster_out"
    GENERATED=$((GENERATED + 1))
  else
    SKIPPED=$((SKIPPED + 1))
  fi
  printf '  mp4  %s\n' "$base"
done

shopt -u nullglob

printf '\nDone. %d JPG sources, %d MP4 sources. Generated %d, skipped %d.\n' \
  "$JPG_COUNT" "$MP4_COUNT" "$GENERATED" "$SKIPPED"
printf 'Output: %s\n' "$OUT_DIR"
