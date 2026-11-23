#!/usr/bin/env bash
# ==============================================================================
# Microstock Generator - Cross-Platform 1-Click Launcher (Linux & macOS)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Detect or bootstrap Python environment
PYTHON_CMD="python3"
if ! command -v python3 &>/dev/null; then
    if command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        echo "❌ Error: Python 3 not found. Please install Python 3.10+ first."
        exit 1
    fi
fi

# 2. Auto-create or self-heal virtual environment if missing or relocated
RECREATE_VENV=0
if [ ! -d "$SCRIPT_DIR/.venv" ] && [ ! -d "$SCRIPT_DIR/venv" ]; then
    RECREATE_VENV=1
elif [ -d "$SCRIPT_DIR/.venv" ]; then
    if ! "$SCRIPT_DIR/.venv/bin/python" -c "import sys" &>/dev/null; then
        echo "⚠️ Stale or invalid virtual environment detected. Self-healing..."
        rm -rf "$SCRIPT_DIR/.venv"
        RECREATE_VENV=1
    fi
fi

if [ "$RECREATE_VENV" -eq 1 ]; then
    echo "=================================================="
    echo "⚡ Setting Up Python Virtual Environment..."
    echo "=================================================="
    "$PYTHON_CMD" -m venv "$SCRIPT_DIR/.venv"
    "$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip
    if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        echo "📦 Installing required dependencies..."
        "$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
    fi
    echo "✅ Setup complete! Launching pipeline..."
    echo ""
fi

# 3. Determine virtualenv python binary
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
else
    PYTHON_BIN="$PYTHON_CMD"
fi

export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8

# Prevent macOS sleep while processing batches
if command -v caffeinate &>/dev/null; then
    caffeinate -i "$PYTHON_BIN" "$SCRIPT_DIR/main.py" "$@"
else
    "$PYTHON_BIN" "$SCRIPT_DIR/main.py" "$@"
fi
