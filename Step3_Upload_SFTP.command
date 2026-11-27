#!/usr/bin/env bash
# ==============================================================================
# Step 3: Adobe Stock Contributor SFTP Upload (With Anti-Duplicate Tracking)
# Optional: use once SFTP is unlocked on your Adobe Stock Contributor account.
# Otherwise, upload result/ images manually via Drag & Drop + Upload CSV.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

"$SCRIPT_DIR/run.sh" --upload "$@"

echo ""
read -p "Press [Enter] to close this window..."
