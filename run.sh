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

# Auto-free port 8000 if occupied by previous instance
PORT_PID=$(lsof -ti :8000 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    echo "Freeing port 8000 (stopping old process $PORT_PID)..."
    kill -9 $PORT_PID 2>/dev/null || true
    sleep 1
fi

echo "Starting Tracky AI..."
exec .venv/bin/python app.py
