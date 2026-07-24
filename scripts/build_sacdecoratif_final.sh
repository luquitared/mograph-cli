#!/bin/bash
set -euo pipefail
RUN="runs/Sac_Decoratif_-_Made_To_Order_Colorway_Ad-20260722-175959"
V="$RUN/videos"
W="$RUN/edit"
FONT="/System/Library/Fonts/Supplemental/Didot.ttc"
mkdir -p "$W"

# --- 1. trim + normalize each clip (720x1280 @ 24fps, silent) ---
norm() { # infile outfile start dur
  ffmpeg -y -loglevel error -ss "$3" -t "$4" -i "$1" \
    -vf "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=24,format=yuv420p,setsar=1" \
    -an -c:v libx264 -crf 17 -preset slow "$2"
}

norm "$V/cw1-ivory.mp4"          "$W/c1.mp4" 0.0 1.4
norm "$V/cw2-coral.mp4"          "$W/c2.mp4" 0.0 1.2
norm "$V/cw3-forest.mp4"         "$W/c3.mp4" 0.0 1.2
norm "$V/cw4-blue.mp4"           "$W/c4.mp4" 0.0 1.2
norm "$V/cw5-brown.mp4"          "$W/c5.mp4" 0.0 1.2
norm "$V/cw6-midnight.mp4"       "$W/c6.mp4" 0.0 1.2
norm "$V/cw7-champagne.mp4"      "$W/c7.mp4" 0.0 1.2
norm "$V/cw8-hero-burgundy.mp4"  "$W/hero.mp4" 0.6 2.6
norm "$V/endcard_still.mp4"      "$W/end.mp4" 0.0 2.92

# --- 2. concat the 7 rapid colorway cuts ---
printf "file 'c1.mp4'\nfile 'c2.mp4'\nfile 'c3.mp4'\nfile 'c4.mp4'\nfile 'c5.mp4'\nfile 'c6.mp4'\nfile 'c7.mp4'\n" > "$W/montage.txt"
ffmpeg -y -loglevel error -f concat -safe 0 -i "$W/montage.txt" -c:v libx264 -crf 17 -preset slow "$W/montage.mp4"
MDUR=$(ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "$W/montage.mp4")

# --- 3. overlay tagline PNG on the montage (fade the overlay's alpha in/out) ---
ffmpeg -y -loglevel error -i "$W/montage.mp4" -loop 1 -framerate 24 -i "$W/tagline.png" -filter_complex \
"[1:v]format=rgba,fade=t=in:st=0.3:d=0.5:alpha=1,fade=t=out:st=$(echo "${MDUR}-0.5" | bc):d=0.5:alpha=1[ov];[0:v][ov]overlay=0:0:shortest=1[v]" \
-map "[v]" -c:v libx264 -crf 17 -preset slow "$W/montage_txt.mp4"

# --- 4. final concat: montage(+text) -> hero -> endcard, gentle fade in/out ---
printf "file 'montage_txt.mp4'\nfile 'hero.mp4'\nfile 'end.mp4'\n" > "$W/final.txt"
ffmpeg -y -loglevel error -f concat -safe 0 -i "$W/final.txt" -c:v libx264 -crf 17 -preset slow "$W/joined.mp4"
JDUR=$(ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "$W/joined.mp4")

OUT="$RUN/sacdecoratif_colorway_ad_9x16.mp4"
ffmpeg -y -loglevel error -i "$W/joined.mp4" -vf \
"fade=t=in:st=0:d=0.4,fade=t=out:st=$(echo "$JDUR-0.5" | bc):d=0.5,format=yuv420p" \
-c:v libx264 -crf 18 -preset slow -movflags +faststart "$OUT"

echo "TOTAL: ${JDUR}s"
echo "OUTPUT: $OUT"
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -show_entries format=duration -of default=noprint_wrappers=1 "$OUT"
