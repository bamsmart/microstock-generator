#!/usr/bin/env bash
# ==============================================================================
# Microstock Generator - Double-clickable macOS 1-Click Launcher
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

"$SCRIPT_DIR/run.sh" "$@"

echo ""
read -p "Press [Enter] to close this window..."
