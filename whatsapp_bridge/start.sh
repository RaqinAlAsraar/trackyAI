#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d "node_modules" ]; then
    echo "Installing WhatsApp bridge dependencies..."
    npm install
fi

echo "Starting WhatsApp Web Session Bridge..."
exec node bridge.js
