#!/usr/bin/env bash
# ==============================================================================
# Microstock Generator - 1-Click Step 1 Research Launcher (macOS)
# Runs High-Demand Research -> Commercial-Grade Copy-Paste Prompt Pack (.txt)
# and automatically opens the generated prompt file for instant copy-paste.
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
