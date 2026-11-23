#!/usr/bin/env bash
# ==============================================================================
# Microstock Generator - 1-Click Step 5 Adobe Stock SFTP Upload Launcher (macOS)
# Uploads all pending validated assets from result/ folders to Adobe Stock SFTP
# and writes a summary log to logs/run_upload_*.txt.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

"$SCRIPT_DIR/run.sh" --upload "$@"

echo ""
read -p "Press [Enter] to close this window..."
