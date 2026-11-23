#!/usr/bin/env bash
# ==============================================================================
# macOS launchd Installer for Daily Step 1 High-Demand Research (20:00 WIB)
# Runs ONLY if the Mac is awake/on during the 20:00 hour (local time / WIB).
# Usage:
#   ./scripts/install_research_schedule.sh          # Install & enable daily 20:00 job
#   ./scripts/install_research_schedule.sh --remove # Uninstall scheduled job
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_LABEL="com.microstock.generator.research"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [ "${1:-}" = "--remove" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "✅ Removed scheduled research job: $PLIST_LABEL"
    exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$SCRIPT_DIR/logs"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>if [ "\$(date +%H)" = "20" ]; then cd "${SCRIPT_DIR}" &amp;&amp; ./run.sh --research --count 12; fi</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>20</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/logs/launchd_research_stdout.txt</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/logs/launchd_research_stderr.txt</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✅ Daily Step 1 Research schedule installed ($PLIST_LABEL)"
echo "   Schedule : Every day at 20:00 WIB (only if Mac is awake/on)"
echo "   Output   : ~/Desktop/microstock_generator/prompts/prompts_*.txt"
echo "   Logs     : ${SCRIPT_DIR}/logs/run_research_*.txt"
echo "   Remove   : ./scripts/install_research_schedule.sh --remove"
