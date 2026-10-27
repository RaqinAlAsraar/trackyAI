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

# Auto-free configured port if occupied by previous instance
CONFIG_PORT=$(python3 -c "import json; print(json.load(open('config.json'))['app'].get('port', 8000))" 2>/dev/null || echo "8000")
PORT_PID=$(lsof -ti :$CONFIG_PORT 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    echo "Stopping previous Tracky instance on port $CONFIG_PORT (PID $PORT_PID)..."
    kill -15 $PORT_PID 2>/dev/null || kill -9 $PORT_PID 2>/dev/null || true
    sleep 1
fi

echo "Starting Tracky AI on port $CONFIG_PORT..."
exec .venv/bin/python app.py
