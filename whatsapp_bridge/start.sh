#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Free port 3001 if occupied by previous instance
PORT_PID=$(lsof -ti :3001 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    echo "Stopping previous bridge on port 3001 (PID $PORT_PID)..."
    kill -15 $PORT_PID 2>/dev/null || kill -9 $PORT_PID 2>/dev/null || true
    sleep 1
fi

if [ ! -d "node_modules" ]; then
    echo "Installing WhatsApp bridge dependencies..."
    npm install
fi

echo "============================================================"
echo "Starting WhatsApp Web Session Bridge..."
echo "Open http://localhost:3001/qr in your browser if terminal QR"
echo "is distorted."
echo "============================================================"
exec node bridge.js

