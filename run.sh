#!/usr/bin/env bash
# ==============================================================================
# Run Tracky AI Assistant
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "config.json" ]; then
    echo "config.json not found! Running setup.sh first..."
    ./setup.sh
    exit $?
fi

if [ ! -d ".venv" ]; then
    echo ".venv virtual environment not found! Running setup.sh first..."
    ./setup.sh
    exit $?
fi

echo "Starting Tracky AI..."
exec .venv/bin/python app.py
