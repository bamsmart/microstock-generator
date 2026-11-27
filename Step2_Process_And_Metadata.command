#!/usr/bin/env bash
# ==============================================================================
# Step 2: Process Raw Assets, Vision QC, Upscale, Anti-Halo & Adobe CSV/XMP
# Run after manually generating images and placing them in <batch>/raw/:
# - Corrupt preflight + within-batch & cross-batch Portfolio pHash dedup
# - Free-Tier Vision QC & 3-tier Adobe Stock SEO Metadata
# - Smart Adaptive Upscayl 4x (>= 12 MP auto-skipped, <= 20 MP supersampling)
# - PyMatting Anti-Halo Cutouts / sRGB 4:4:4 JPEG + Pure-Python XMP/EXIF + CSV
# - Scientific IQA + Dark-Canvas qa_contact_sheet.jpg + .txt run log
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

"$SCRIPT_DIR/run.sh" "$@"

# Automatically open the newest Dark-Canvas QA Contact Sheet for 10s visual check
LATEST_SHEET=$(ls -t "$HOME/Desktop/microstock_generator/"*/qa_contact_sheet.jpg "$HOME/Desktop/microstock_generator/qa_contact_sheet.jpg" "$SCRIPT_DIR/input/"*/qa_contact_sheet.jpg "$SCRIPT_DIR/input/qa_contact_sheet.jpg" 2>/dev/null | head -n 1 || true)
if [ -n "$LATEST_SHEET" ] && command -v open &>/dev/null; then
    echo ""
    echo "🖼️  Opening Dark-Canvas QA Contact Sheet: $LATEST_SHEET"
    open "$LATEST_SHEET"
fi

echo ""
read -p "Press [Enter] to close this window..."
