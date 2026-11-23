#!/usr/bin/env bash
# ==============================================================================
# Optional macOS launchd Installer for Scheduled Daily Microstock Processing & Upload
# Runs Step 4 (process) + Step 5 (SFTP upload) automatically every night at 02:00.
# Usage:
#   ./scripts/install_daily_schedule.sh          # Install & enable daily 02:00 job
#   ./scripts/install_daily_schedule.sh --remove # Uninstall scheduled job
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_LABEL="com.microstock.generator.daily"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [ "${1:-}" = "--remove" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "✅ Removed scheduled job: $PLIST_LABEL"
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
        <string>cd "${SCRIPT_DIR}" &amp;&amp; ./run.sh &amp;&amp; ./run.sh --upload</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>2</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/logs/launchd_stdout.txt</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/logs/launchd_stderr.txt</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✅ Daily schedule installed ($PLIST_LABEL): runs every day at 02:00 AM"
echo "   Steps : Step 4 (Process + QC + SEO + CSV) -> Step 5 (Adobe Stock SFTP Upload)"
echo "   Logs  : ${SCRIPT_DIR}/logs/"
echo "   Remove: ./scripts/install_daily_schedule.sh --remove"
