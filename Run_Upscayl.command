#!/usr/bin/env bash
# Backward-compatibility launcher for Run_Upscayl.command
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/Run_Microstock_Generator.command" "$@"
