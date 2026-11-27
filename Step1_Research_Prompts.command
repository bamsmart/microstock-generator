#!/usr/bin/env bash
# ==============================================================================
# Step 1: High-Demand Seasonal Research -> Commercial-Grade Prompt Pack (.txt)
# Runs 3-4 months ahead (H-90..H-120) research with 120-day anti-repeat history
# and automatically opens the newest prompts_*.txt file for copy-paste.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

"$SCRIPT_DIR/run.sh" --research --count 12 "$@"

# Automatically open the newest generated prompt pack .txt on macOS
LATEST_PROMPT=$(ls -t "$HOME/Desktop/microstock_generator/prompts/"prompts_*.txt "$SCRIPT_DIR/output/prompts/"prompts_*.txt 2>/dev/null | head -n 1 || true)
if [ -n "$LATEST_PROMPT" ] && command -v open &>/dev/null; then
    echo ""
    echo "📂 Opening prompt pack for copy-paste: $LATEST_PROMPT"
    open "$LATEST_PROMPT"
fi

echo ""
read -p "Press [Enter] to close this window..."
