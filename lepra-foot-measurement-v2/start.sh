#!/bin/bash
set -e

CKPT_DIR="/app/checkpoints"
FOLDER_ID="1QQSOuNeG_VRafZoBVrcMCdi6CP9A1y4d"

# Required checkpoints — pipeline crashes with FileNotFoundError if any is
# missing. Previously only sam_b.pt was checked; if it was present but a
# per-side .pth was missing (failed gdown, partial download), the script
# skipped the download and the app booted into a runtime crash. Now we verify
# every required file and trigger a re-download if any is missing or empty.
REQUIRED=(
    "sam_b.pt"
    "foot_seg_best.pt"
    "unet_mobilenet_v2_best.pt"
    "card_detector.pt"
    "coin_detector.pt"
    "left_sole.pth" "right_sole.pth"
    "left_top.pth"  "right_top.pth"
    "left_side.pth" "right_side.pth"
)

mkdir -p "$CKPT_DIR"
MISSING=0
for f in "${REQUIRED[@]}"; do
    if [ ! -s "$CKPT_DIR/$f" ]; then
        echo "  Missing or empty checkpoint: $f"
        MISSING=1
    fi
done

if [ $MISSING -eq 1 ]; then
    echo "Downloading checkpoints from Google Drive..."
    gdown --folder "https://drive.google.com/drive/folders/$FOLDER_ID" -O "$CKPT_DIR"
    echo "Checkpoints downloaded. Verifying..."
    for f in "${REQUIRED[@]}"; do
        if [ ! -s "$CKPT_DIR/$f" ]; then
            echo "  STILL MISSING after download: $f"
        fi
    done
else
    echo "All checkpoints already present, skipping download."
fi

echo "Starting server..."
exec uvicorn live_app:app --host 0.0.0.0 --port 7860
