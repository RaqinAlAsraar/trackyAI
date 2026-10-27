#!/usr/bin/env bash
# ==============================================================================
# Quick LLM Mode Switcher for Tracky AI
# Allows fast switching between Local-Only, Hybrid, and Cloud-Only modes
# Usage:
#   ./switch_mode.sh local    -> 100% Local Ollama (zero API quota consumption)
#   ./switch_mode.sh hybrid   -> Cloud Gemma 4 primary + Local Ollama fallback
#   ./switch_mode.sh cloud    -> Cloud API only
#   ./switch_mode.sh          -> Interactive mode
# ==============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG_FILE="config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: config.json not found! Please run ./setup.sh first."
    exit 1
fi

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

TARGET_MODE="$1"

if [ -z "$TARGET_MODE" ]; then
    CURRENT_MODE=$(python3 -c "import json; print(json.load(open('config.json')).get('app', {}).get('llm_mode', 'hybrid'))" 2>/dev/null || echo "hybrid")
    echo -e "${BOLD}${CYAN}--- Tracky AI LLM Mode Switcher ---${NC}"
    echo -e "Current active mode: ${GREEN}${CURRENT_MODE}${NC}\n"
    echo "1) Completely Local LLM (local_only) - Zero API Quota usage, Fast Offline Testing"
    echo "2) Hybrid Mode (hybrid) - Cloud Gemma 4 Primary + Local Ollama fallback"
    echo "3) Cloud API Only (cloud_only) - Google GenAI models only"
    read -rp "Select mode [1-3]: " CHOICE
    case "$CHOICE" in
        1) TARGET_MODE="local" ;;
        2) TARGET_MODE="hybrid" ;;
        3) TARGET_MODE="cloud" ;;
        *) echo "Invalid choice. Exiting."; exit 1 ;;
    esac
fi

TARGET_MODE=$(echo "$TARGET_MODE" | tr '[:upper:]' '[:lower:]')

case "$TARGET_MODE" in
    local|local_only|offline)
        python3 -c "
import json
with open('config.json', 'r') as f:
    cfg = json.load(f)
cfg.setdefault('app', {})['llm_mode'] = 'local_only'
cfg.setdefault('local_llm', {})['enabled'] = True
cfg['local_llm']['local_only'] = True
with open('config.json', 'w') as f:
    json.dump(cfg, f, indent=2)
print('✓ config.json updated to LOCAL_ONLY mode')
"
        echo -e "${GREEN}${BOLD}✓ Tracky AI set to COMPLETELY LOCAL LLM mode!${NC}"
        echo -e "• Zero Google API calls will be made (0 quota used)."
        echo -e "• Uses local Ollama model directly."
        ;;
    hybrid|both)
        python3 -c "
import json
with open('config.json', 'r') as f:
    cfg = json.load(f)
cfg.setdefault('app', {})['llm_mode'] = 'hybrid'
cfg.setdefault('local_llm', {})['enabled'] = True
cfg['local_llm']['local_only'] = False
with open('config.json', 'w') as f:
    json.dump(cfg, f, indent=2)
print('✓ config.json updated to HYBRID mode')
"
        echo -e "${GREEN}${BOLD}✓ Tracky AI set to HYBRID mode!${NC}"
        echo -e "• Primary: Cloud Gemma 4"
        echo -e "• Fallback: Local Ollama on quota limit or error"
        ;;
    cloud|cloud_only)
        python3 -c "
import json
with open('config.json', 'r') as f:
    cfg = json.load(f)
cfg.setdefault('app', {})['llm_mode'] = 'cloud_only'
cfg.setdefault('local_llm', {})['local_only'] = False
with open('config.json', 'w') as f:
    json.dump(cfg, f, indent=2)
print('✓ config.json updated to CLOUD_ONLY mode')
"
        echo -e "${GREEN}${BOLD}✓ Tracky AI set to CLOUD-ONLY mode!${NC}"
        ;;
    *)
        echo -e "Unknown mode: '$TARGET_MODE'. Supported: local | hybrid | cloud"
        exit 1
        ;;
esac

echo ""
echo -e "Restart Tracky with: ${BOLD}./run.sh${NC}"
