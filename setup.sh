#!/usr/bin/env bash
# ==============================================================================
# Tracky AI - Interactive Setup Wizard
# Supports Local Linux machines and DigitalOcean / VPS deployments
# ==============================================================================

set -e

# Terminal colors
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BOLD}${CYAN}"
echo "=============================================================="
echo "          🤖 Welcome to Tracky AI Setup Wizard                "
echo "  Your personal assistant for Tasks, Schedules & Reminders    "
echo "=============================================================="
echo -e "${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Check Python version
echo -e "${BLUE}[1/6] Checking system environment...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 is not installed. Please install Python 3.10+ first.${NC}"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${GREEN}✓ Found Python $PY_VERSION${NC}"

# Check ffmpeg for voice processing
if command -v ffmpeg &> /dev/null; then
    echo -e "${GREEN}✓ Found ffmpeg (Voice audio ready)${NC}"
else
    echo -e "${YELLOW}! ffmpeg not found. You can install it with: sudo apt install ffmpeg${NC}"
fi

# 2. Virtual Environment Setup
echo -e "\n${BLUE}[2/6] Setting up Python virtual environment...${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}✓ Created virtual environment in .venv${NC}"
else
    echo -e "${GREEN}✓ Virtual environment already exists.${NC}"
fi

echo -e "Installing/updating dependencies from requirements.txt..."
.venv/bin/pip install --upgrade pip > /dev/null
.venv/bin/pip install -r requirements.txt > /dev/null
echo -e "${GREEN}✓ Dependencies installed successfully.${NC}"

# 3. Interactive Configuration Prompts
echo -e "\n${BOLD}${CYAN}--- Configuration Wizard ---${NC}"

# Load existing configuration defaults if config.json exists
EXISTING_LLM_MODE="hybrid"
EXISTING_KEY=""
EXISTING_PRIMARY="models/gemma-4-26b-a4b-it"
EXISTING_BACKUP="models/gemini-3.1-flash-lite"
EXISTING_OLLAMA_ENABLED=true
EXISTING_OLLAMA_HOST="http://127.0.0.1:11434"
EXISTING_OLLAMA_MODEL="gemma2:2b"
EXISTING_PORT=8002
EXISTING_ASSISTANT_NAME="Tracky"
EXISTING_USER_NAME="User"
EXISTING_TG_TOKEN=""
EXISTING_TG_ALLOWED=""

if [ -f "config.json" ]; then
    EXISTING_LLM_MODE=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('app', {}).get('llm_mode', 'hybrid'))" 2>/dev/null || echo "hybrid")
    EXISTING_KEY=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('gemini', {}).get('api_key', ''))" 2>/dev/null || true)
    EXISTING_PRIMARY=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('gemini', {}).get('primary_model', 'models/gemma-4-26b-a4b-it'))" 2>/dev/null || echo "models/gemma-4-26b-a4b-it")
    EXISTING_BACKUP=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('gemini', {}).get('backup_model', 'models/gemini-3.1-flash-lite'))" 2>/dev/null || echo "models/gemini-3.1-flash-lite")
    EXISTING_OLLAMA_HOST=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('local_llm', {}).get('host', 'http://127.0.0.1:11434'))" 2>/dev/null || echo "http://127.0.0.1:11434")
    EXISTING_OLLAMA_MODEL=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('local_llm', {}).get('model', 'gemma2:2b'))" 2>/dev/null || echo "gemma2:2b")
    EXISTING_PORT=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('app', {}).get('port', 8002))" 2>/dev/null || echo "8002")
    EXISTING_ASSISTANT_NAME=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('app', {}).get('assistant_name', 'Tracky'))" 2>/dev/null || echo "Tracky")
    EXISTING_USER_NAME=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('app', {}).get('user_name', 'User'))" 2>/dev/null || echo "User")
    EXISTING_TG_TOKEN=$(.venv/bin/python3 -c "import json; print(json.load(open('config.json')).get('telegram', {}).get('bot_token', ''))" 2>/dev/null || true)
    EXISTING_TG_ALLOWED=$(.venv/bin/python3 -c "import json; print(','.join(str(x) for x in json.load(open('config.json')).get('telegram', {}).get('allowed_user_ids', [])))" 2>/dev/null || true)
fi

# Server Deployment Type
echo -e "\n${YELLOW}Where will you run Tracky AI?${NC}"
echo "1) Local Linux machine"
echo "2) DigitalOcean / Cloud VPS (with systemd service option)"
read -rp "Select option [1/2] (default: 1): " SERVER_CHOICE
SERVER_CHOICE=${SERVER_CHOICE:-1}

# Web Server Port
read -rp "Web Server Port (default: $EXISTING_PORT): " CONFIG_PORT
CONFIG_PORT=${CONFIG_PORT:-$EXISTING_PORT}

# LLM Execution Mode Selection
echo -e "\n${BOLD}${CYAN}--- LLM Execution Mode ---${NC}"
echo -e "${YELLOW}Choose how you want Tracky AI to run:${NC}"
echo "1) Hybrid Mode: Cloud Gemma 4 primary + Local Ollama fallback on error/quota (Recommended for daily use)"
echo "2) Completely Local LLM: 100% Offline via Ollama (Zero API Quota usage, Fast Testing)"
echo "3) Cloud API Only: Google Cloud AI models only"
DEFAULT_MODE_OPT=1
if [ "$EXISTING_LLM_MODE" == "local_only" ] || [ "$EXISTING_LLM_MODE" == "local" ]; then
    DEFAULT_MODE_OPT=2
elif [ "$EXISTING_LLM_MODE" == "cloud_only" ]; then
    DEFAULT_MODE_OPT=3
fi
read -rp "Select mode [1-3] (default: $DEFAULT_MODE_OPT): " LLM_MODE_CHOICE
LLM_MODE_CHOICE=${LLM_MODE_CHOICE:-$DEFAULT_MODE_OPT}

if [ "$LLM_MODE_CHOICE" -eq 2 ]; then
    LLM_MODE="local_only"
    LOCAL_LLM_ENABLED=true
    LOCAL_ONLY_CONFIG=true
    echo -e "${GREEN}✓ Selected: Completely Local LLM Mode (Zero API quota used!)${NC}"
    
    echo -e "\n${BOLD}${CYAN}--- Local Ollama LLM Configuration ---${NC}"
    read -rp "Enter Ollama Host URL (default: ${EXISTING_OLLAMA_HOST}): " OLLAMA_HOST
    OLLAMA_HOST=${OLLAMA_HOST:-$EXISTING_OLLAMA_HOST}
    read -rp "Enter Ollama Model Name (default: ${EXISTING_OLLAMA_MODEL}): " OLLAMA_MODEL
    OLLAMA_MODEL=${OLLAMA_MODEL:-$EXISTING_OLLAMA_MODEL}
    echo -e "${GREEN}✓ Local Ollama configured with model: $OLLAMA_MODEL at $OLLAMA_HOST${NC}"
    
    # Optional Gemini Key in local mode
    if [ -n "$EXISTING_KEY" ]; then
        GEMINI_KEY="$EXISTING_KEY"
    else
        read -rp "Enter Gemini API Key (Optional in local-only mode, press Enter to skip): " GEMINI_KEY
    fi
    PRIMARY_MODEL="${EXISTING_PRIMARY:-models/gemma-4-26b-a4b-it}"
    BACKUP_MODEL="${EXISTING_BACKUP:-models/gemini-3.1-flash-lite}"

elif [ "$LLM_MODE_CHOICE" -eq 3 ]; then
    LLM_MODE="cloud_only"
    LOCAL_LLM_ENABLED=false
    LOCAL_ONLY_CONFIG=false
    OLLAMA_HOST="$EXISTING_OLLAMA_HOST"
    OLLAMA_MODEL="$EXISTING_OLLAMA_MODEL"
    echo -e "${GREEN}✓ Selected: Cloud API Only Mode${NC}"

    # Gemini API Key
    echo -e "\n${YELLOW}Google Gemini API Key:${NC}"
    if [ -n "$EXISTING_KEY" ]; then
        read -rp "Enter your Gemini API Key (press Enter to keep existing key): " INPUT_KEY
        GEMINI_KEY=${INPUT_KEY:-$EXISTING_KEY}
    else
        read -rp "Enter your Gemini API Key: " GEMINI_KEY
        while [ -z "$GEMINI_KEY" ]; do
            echo -e "${RED}API key cannot be empty in cloud mode.${NC}"
            read -rp "Enter your Gemini API Key: " GEMINI_KEY
        done
    fi

    # Fetch and List All Available Models
    echo -e "\n${BLUE}Querying available models from Google AI Studio API...${NC}"
    AVAILABLE_MODELS_RAW=$(.venv/bin/python3 scripts/list_models.py "$GEMINI_KEY" --json 2>/dev/null || .venv/bin/python3 scripts/list_models.py "" --json)
    MODEL_NAMES=($(.venv/bin/python3 -c "
import json
data = json.loads('''$AVAILABLE_MODELS_RAW''')
print(' '.join(m['name'] for m in data))
"))
    TOTAL_MODELS=${#MODEL_NAMES[@]}
    echo -e "\n${BOLD}${CYAN}--- Available Google Models ---${NC}"
    .venv/bin/python3 -c "
import json
data = json.loads('''$AVAILABLE_MODELS_RAW''')
for idx, m in enumerate(data, 1):
    print(f\"{idx}) \033[1m{m['name']}\033[0m - {m['description']}\")
"
    CUSTOM_IDX=$((TOTAL_MODELS + 1))
    echo -e "${CUSTOM_IDX}) \033[1mCustom model name\033[0m (enter manually)"

    # Primary Model Selection
    DEFAULT_PRIMARY_IDX=1
    for i in "${!MODEL_NAMES[@]}"; do
        if [[ "${MODEL_NAMES[$i]}" == *"gemma-4-26b"* ]] || [[ "${MODEL_NAMES[$i]}" == *"gemma-4"* ]]; then
            DEFAULT_PRIMARY_IDX=$((i + 1))
            break
        fi
    done
    read -rp "Select primary model [1-${CUSTOM_IDX}] (default: ${DEFAULT_PRIMARY_IDX} [${MODEL_NAMES[$((DEFAULT_PRIMARY_IDX - 1))]}]): " MODEL_CHOICE
    MODEL_CHOICE=${MODEL_CHOICE:-$DEFAULT_PRIMARY_IDX}
    if [ "$MODEL_CHOICE" -ge 1 ] && [ "$MODEL_CHOICE" -le "$TOTAL_MODELS" ]; then
        PRIMARY_MODEL="${MODEL_NAMES[$((MODEL_CHOICE - 1))]}"
    elif [ "$MODEL_CHOICE" -eq "$CUSTOM_IDX" ]; then
        read -rp "Enter custom primary model name: " PRIMARY_MODEL
    else
        PRIMARY_MODEL="${MODEL_NAMES[$((DEFAULT_PRIMARY_IDX - 1))]}"
    fi

    # Backup Model Selection
    DEFAULT_BACKUP_IDX=1
    for i in "${!MODEL_NAMES[@]}"; do
        if [[ "${MODEL_NAMES[$i]}" == *"gemini-3.1-flash-lite"* ]] || [[ "${MODEL_NAMES[$i]}" == *"flash-lite"* ]]; then
            DEFAULT_BACKUP_IDX=$((i + 1))
            break
        fi
    done
    read -rp "Select backup model [1-${CUSTOM_IDX}] (default: ${DEFAULT_BACKUP_IDX} [${MODEL_NAMES[$((DEFAULT_BACKUP_IDX - 1))]}]): " BACKUP_CHOICE
    BACKUP_CHOICE=${BACKUP_CHOICE:-$DEFAULT_BACKUP_IDX}
    if [ "$BACKUP_CHOICE" -ge 1 ] && [ "$BACKUP_CHOICE" -le "$TOTAL_MODELS" ]; then
        BACKUP_MODEL="${MODEL_NAMES[$((BACKUP_CHOICE - 1))]}"
    elif [ "$BACKUP_CHOICE" -eq "$CUSTOM_IDX" ]; then
        read -rp "Enter custom backup model name: " BACKUP_MODEL
    else
        BACKUP_MODEL="${MODEL_NAMES[$((DEFAULT_BACKUP_IDX - 1))]}"
    fi

else
    # Hybrid Mode
    LLM_MODE="hybrid"
    LOCAL_LLM_ENABLED=true
    LOCAL_ONLY_CONFIG=false
    echo -e "${GREEN}✓ Selected: Hybrid Mode (Cloud Primary + Local Ollama Fallback)${NC}"

    # Gemini API Key
    echo -e "\n${YELLOW}Google Gemini API Key:${NC}"
    if [ -n "$EXISTING_KEY" ]; then
        read -rp "Enter your Gemini API Key (press Enter to keep existing key): " INPUT_KEY
        GEMINI_KEY=${INPUT_KEY:-$EXISTING_KEY}
    else
        read -rp "Enter your Gemini API Key: " GEMINI_KEY
        while [ -z "$GEMINI_KEY" ]; do
            echo -e "${RED}API key cannot be empty.${NC}"
            read -rp "Enter your Gemini API Key: " GEMINI_KEY
        done
    fi

    # Fetch and List All Available Models
    echo -e "\n${BLUE}Querying available models from Google AI Studio API...${NC}"
    AVAILABLE_MODELS_RAW=$(.venv/bin/python3 scripts/list_models.py "$GEMINI_KEY" --json 2>/dev/null || .venv/bin/python3 scripts/list_models.py "" --json)
    MODEL_NAMES=($(.venv/bin/python3 -c "
import json
data = json.loads('''$AVAILABLE_MODELS_RAW''')
print(' '.join(m['name'] for m in data))
"))
    TOTAL_MODELS=${#MODEL_NAMES[@]}
    echo -e "\n${BOLD}${CYAN}--- Available Google Models ---${NC}"
    .venv/bin/python3 -c "
import json
data = json.loads('''$AVAILABLE_MODELS_RAW''')
for idx, m in enumerate(data, 1):
    print(f\"{idx}) \033[1m{m['name']}\033[0m - {m['description']}\")
"
    CUSTOM_IDX=$((TOTAL_MODELS + 1))
    echo -e "${CUSTOM_IDX}) \033[1mCustom model name\033[0m (enter manually)"

    # Primary Model Selection
    DEFAULT_PRIMARY_IDX=1
    for i in "${!MODEL_NAMES[@]}"; do
        if [[ "${MODEL_NAMES[$i]}" == *"gemma-4-26b"* ]] || [[ "${MODEL_NAMES[$i]}" == *"gemma-4"* ]]; then
            DEFAULT_PRIMARY_IDX=$((i + 1))
            break
        fi
    done
    read -rp "Select primary model [1-${CUSTOM_IDX}] (default: ${DEFAULT_PRIMARY_IDX} [${MODEL_NAMES[$((DEFAULT_PRIMARY_IDX - 1))]}]): " MODEL_CHOICE
    MODEL_CHOICE=${MODEL_CHOICE:-$DEFAULT_PRIMARY_IDX}
    if [ "$MODEL_CHOICE" -ge 1 ] && [ "$MODEL_CHOICE" -le "$TOTAL_MODELS" ]; then
        PRIMARY_MODEL="${MODEL_NAMES[$((MODEL_CHOICE - 1))]}"
    elif [ "$MODEL_CHOICE" -eq "$CUSTOM_IDX" ]; then
        read -rp "Enter custom primary model name: " PRIMARY_MODEL
    else
        PRIMARY_MODEL="${MODEL_NAMES[$((DEFAULT_PRIMARY_IDX - 1))]}"
    fi

    # Backup Model Selection
    DEFAULT_BACKUP_IDX=1
    for i in "${!MODEL_NAMES[@]}"; do
        if [[ "${MODEL_NAMES[$i]}" == *"gemini-3.1-flash-lite"* ]] || [[ "${MODEL_NAMES[$i]}" == *"flash-lite"* ]]; then
            DEFAULT_BACKUP_IDX=$((i + 1))
            break
        fi
    done
    read -rp "Select backup model [1-${CUSTOM_IDX}] (default: ${DEFAULT_BACKUP_IDX} [${MODEL_NAMES[$((DEFAULT_BACKUP_IDX - 1))]}]): " BACKUP_CHOICE
    BACKUP_CHOICE=${BACKUP_CHOICE:-$DEFAULT_BACKUP_IDX}
    if [ "$BACKUP_CHOICE" -ge 1 ] && [ "$BACKUP_CHOICE" -le "$TOTAL_MODELS" ]; then
        BACKUP_MODEL="${MODEL_NAMES[$((BACKUP_CHOICE - 1))]}"
    elif [ "$BACKUP_CHOICE" -eq "$CUSTOM_IDX" ]; then
        read -rp "Enter custom backup model name: " BACKUP_MODEL
    else
        BACKUP_MODEL="${MODEL_NAMES[$((DEFAULT_BACKUP_IDX - 1))]}"
    fi

    # Local Ollama Fallback
    echo -e "\n${BOLD}${CYAN}--- Local Ollama LLM Fallback ---${NC}"
    read -rp "Enter Ollama Host URL (default: ${EXISTING_OLLAMA_HOST}): " OLLAMA_HOST
    OLLAMA_HOST=${OLLAMA_HOST:-$EXISTING_OLLAMA_HOST}
    read -rp "Enter Ollama Model Name (default: ${EXISTING_OLLAMA_MODEL}): " OLLAMA_MODEL
    OLLAMA_MODEL=${OLLAMA_MODEL:-$EXISTING_OLLAMA_MODEL}
    echo -e "${GREEN}✓ Local Ollama configured with model: $OLLAMA_MODEL at $OLLAMA_HOST${NC}"
fi

# Messaging Platform Selection
echo -e "\n${YELLOW}Which messaging platform(s) do you want to configure?${NC}"
echo "1) Telegram only (Easiest & recommended for daily use)"
echo "2) WhatsApp only (via WhatsApp Web Session - QR Link)"
echo "3) Both Telegram and WhatsApp (Web Session)"
echo "4) WhatsApp via Twilio"
read -rp "Select platform [1-4] (default: 1): " PLATFORM_CHOICE
PLATFORM_CHOICE=${PLATFORM_CHOICE:-1}

TELEGRAM_ENABLED=false
WHATSAPP_ENABLED=false
WA_PROVIDER="web_session"
TELEGRAM_TOKEN=""
TELEGRAM_MODE="polling"
TG_USER_ID=""
TWILIO_SID=""
TWILIO_TOKEN=""
TWILIO_PHONE="whatsapp:+14155238886"
WA_USER_PHONE=""

if [ "$PLATFORM_CHOICE" == "1" ] || [ "$PLATFORM_CHOICE" == "3" ]; then
    TELEGRAM_ENABLED=true
    echo -e "\n${BOLD}${BLUE}--- Telegram Bot Setup ---${NC}"
    echo "Create a bot in Telegram by messaging @BotFather and copy the HTTP API Token."
    if [ -n "$EXISTING_TG_TOKEN" ]; then
        read -rp "Enter your Telegram Bot Token (press Enter to keep existing): " INPUT_TG_TOKEN
        TELEGRAM_TOKEN=${INPUT_TG_TOKEN:-$EXISTING_TG_TOKEN}
    else
        read -rp "Enter your Telegram Bot Token: " TELEGRAM_TOKEN
    fi
    
    echo "Connection mode:"
    echo "1) Polling (Works immediately locally & VPS without public domain or SSL)"
    echo "2) Webhook (Requires public HTTPS domain)"
    read -rp "Select Telegram mode [1/2] (default: 1): " TG_MODE_CHOICE
    if [ "$TG_MODE_CHOICE" == "2" ]; then
        TELEGRAM_MODE="webhook"
    else
        TELEGRAM_MODE="polling"
    fi

    echo -e "\n${YELLOW}Telegram User ID Restriction (Sole User Access):${NC}"
    echo "To restrict Tracky so it operates solely for you and ignores strangers:"
    echo "(Tip: Send any message to @userinfobot on Telegram to see your numeric User ID)"
    if [ -n "$EXISTING_TG_ALLOWED" ]; then
        read -rp "Enter your Telegram User ID (default: ${EXISTING_TG_ALLOWED}): " INPUT_TG_ID
        TG_USER_ID=${INPUT_TG_ID:-$EXISTING_TG_ALLOWED}
    else
        read -rp "Enter your Telegram User ID (press Enter to skip restriction): " TG_USER_ID
    fi
fi

if [ "$PLATFORM_CHOICE" == "2" ] || [ "$PLATFORM_CHOICE" == "3" ]; then
    WHATSAPP_ENABLED=true
    WA_PROVIDER="web_session"
    echo -e "\n${BOLD}${GREEN}--- WhatsApp Web Session Setup ---${NC}"
    echo "Uses WhatsApp Web Multi-Device link (No Twilio or Meta account needed!)."
    echo "When Tracky starts, you simply scan the QR code with WhatsApp (Linked Devices)."
    echo -e "\n${YELLOW}WhatsApp Phone Number Restriction (Sole User Access):${NC}"
    echo "Enter your personal phone number (with country code, e.g. +919876543210) to restrict Tracky solely to you."
    read -rp "Enter your phone number (or press Enter to allow your linked session): " WA_USER_PHONE
fi

if [ "$PLATFORM_CHOICE" == "4" ]; then
    WHATSAPP_ENABLED=true
    WA_PROVIDER="twilio"
    echo -e "\n${BOLD}${BLUE}--- WhatsApp (Twilio) Setup ---${NC}"
    echo "Get credentials at https://console.twilio.com/ -> Messaging -> Try WhatsApp Sandbox"
    read -rp "Enter Twilio Account SID: " TWILIO_SID
    read -rp "Enter Twilio Auth Token: " TWILIO_TOKEN
    read -rp "Enter Twilio WhatsApp Number (default: whatsapp:+14155238886): " INPUT_TWILIO_PHONE
    if [ -n "$INPUT_TWILIO_PHONE" ]; then
        TWILIO_PHONE="$INPUT_TWILIO_PHONE"
    fi

    echo -e "\n${YELLOW}WhatsApp Phone Number Restriction (Sole User Access):${NC}"
    echo "Enter your personal phone number to restrict Tracky solely to you."
    read -rp "Enter your phone number (e.g. +1234567890, or press Enter to skip restriction): " WA_USER_PHONE
fi

# Personalization
echo -e "\n${BOLD}${CYAN}--- Personalization ---${NC}"
read -rp "What is your name? (default: $EXISTING_USER_NAME): " USER_NAME
USER_NAME=${USER_NAME:-$EXISTING_USER_NAME}

read -rp "What would you like to name your AI assistant? (default: $EXISTING_ASSISTANT_NAME): " ASSISTANT_NAME
ASSISTANT_NAME=${ASSISTANT_NAME:-$EXISTING_ASSISTANT_NAME}
echo -e "${GREEN}✓ Great! $ASSISTANT_NAME will assist $USER_NAME.${NC}"

# Timezone Selection
DETECTED_TZ=$(.venv/bin/python3 -c "import tzlocal; print(tzlocal.get_localzone_name())" 2>/dev/null || echo "Asia/Kolkata")
if [ -z "$DETECTED_TZ" ]; then
    DETECTED_TZ="Asia/Kolkata"
fi

echo -e "\n${BOLD}${CYAN}--- Timezone Configuration ---${NC}"
echo -e "Detected system timezone: ${GREEN}${DETECTED_TZ}${NC}"
echo "1) Use detected timezone: ${DETECTED_TZ} (Press Enter)"
echo "2) Asia/Kolkata (IST - India +05:30)"
echo "3) America/New_York (EST/EDT - US Eastern)"
echo "4) America/Los_Angeles (PST/PDT - US Pacific)"
echo "5) America/Chicago (CST/CDT - US Central)"
echo "6) Europe/London (GMT/BST - UK)"
echo "7) Europe/Berlin (CET/CEST - Central Europe)"
echo "8) Asia/Dubai (GST - UAE +04:00)"
echo "9) Asia/Singapore (SGT - Singapore +08:00)"
echo "10) UTC"
echo "11) Custom timezone string (enter manually)"
read -rp "Select timezone [1-11] (default: 1 [${DETECTED_TZ}]): " TZ_CHOICE
TZ_CHOICE=${TZ_CHOICE:-1}

case $TZ_CHOICE in
    1) USER_TZ="$DETECTED_TZ" ;;
    2) USER_TZ="Asia/Kolkata" ;;
    3) USER_TZ="America/New_York" ;;
    4) USER_TZ="America/Los_Angeles" ;;
    5) USER_TZ="America/Chicago" ;;
    6) USER_TZ="Europe/London" ;;
    7) USER_TZ="Europe/Berlin" ;;
    8) USER_TZ="Asia/Dubai" ;;
    9) USER_TZ="Asia/Singapore" ;;
    10) USER_TZ="UTC" ;;
    11)
        read -rp "Enter timezone string (e.g. Asia/Kolkata): " USER_TZ
        ;;
    *) USER_TZ="$DETECTED_TZ" ;;
esac
echo -e "${GREEN}✓ Timezone configured: $USER_TZ${NC}"

# 4. Generate config.json
echo -e "\n${BLUE}[4/6] Generating config.json...${NC}"

TG_ALLOWED_IDS_JSON=""
if [ -n "$TG_USER_ID" ]; then
    TG_ALLOWED_IDS_JSON="$TG_USER_ID"
fi

WA_ALLOWED_NUMS_JSON=""
if [ -n "$WA_USER_PHONE" ]; then
    WA_ALLOWED_NUMS_JSON="\"$WA_USER_PHONE\""
fi

cat <<EOF > config.json
{
  "app": {
    "name": "Tracky AI",
    "assistant_name": "$ASSISTANT_NAME",
    "user_name": "$USER_NAME",
    "host": "0.0.0.0",
    "port": $CONFIG_PORT,
    "timezone": "$USER_TZ",
    "debug": true,
    "log_discussions": true,
    "llm_mode": "$LLM_MODE"
  },
  "gemini": {
    "api_key": "$GEMINI_KEY",
    "primary_model": "$PRIMARY_MODEL",
    "backup_model": "$BACKUP_MODEL",
    "temperature": 0.4,
    "max_output_tokens": 1024
  },
  "local_llm": {
    "enabled": $LOCAL_LLM_ENABLED,
    "provider": "ollama",
    "host": "$OLLAMA_HOST",
    "model": "$OLLAMA_MODEL",
    "fallback_on_error": true,
    "local_only": $LOCAL_ONLY_CONFIG,
    "timeout": 25.0
  },
  "database": {
    "path": "tracky.db"
  },
  "memory": {
    "max_history_messages": 100,
    "max_history_hours": 48,
    "memory_log_file": "memory.log",
    "log_discussions": true,
    "discussion_log_file": "logs/discussions.log"
  },
  "telegram": {
    "enabled": $TELEGRAM_ENABLED,
    "bot_token": "$TELEGRAM_TOKEN",
    "mode": "$TELEGRAM_MODE",
    "webhook_url": "",
    "allowed_user_ids": [$TG_ALLOWED_IDS_JSON]
  },
  "whatsapp": {
    "enabled": $WHATSAPP_ENABLED,
    "provider": "$WA_PROVIDER",
    "web_session_url": "http://127.0.0.1:3001",
    "web_session_auto_start": true,
    "twilio_account_sid": "$TWILIO_SID",
    "twilio_auth_token": "$TWILIO_TOKEN",
    "twilio_phone_number": "$TWILIO_PHONE",
    "meta_phone_number_id": "",
    "meta_access_token": "",
    "meta_verify_token": "tracky_webhook_verify_token",
    "allowed_phone_numbers": [$WA_ALLOWED_NUMS_JSON]
  },
  "voice": {
    "stt_enabled": true,
    "tts_enabled": false,
    "tts_voice": "en-US-ChristopherNeural"
  },
  "guardrails": {
    "rate_limit_messages_per_minute": 20,
    "max_message_chars": 2000
  }
}
EOF

echo -e "${GREEN}✓ config.json generated successfully.${NC}"

# 5. Initialize Database
echo -e "\n${BLUE}[5/6] Initializing SQLite database...${NC}"
.venv/bin/python3 -c "import asyncio; from db.database import init_db; asyncio.run(init_db())"
echo -e "${GREEN}✓ Database tracky.db initialized with all schemas and indexes.${NC}"

# 6. Optional DigitalOcean Systemd Service
if [ "$SERVER_CHOICE" == "2" ]; then
    echo -e "\n${BLUE}[6/6] Generating systemd unit file for 24/7 background service...${NC}"
    CURRENT_USER=$(whoami)
    cat <<EOF > tracky.service
[Unit]
Description=Tracky AI Personal Assistant Service
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/.venv/bin/python $SCRIPT_DIR/app.py
Restart=always
RestartSec=5
StandardOutput=append:$SCRIPT_DIR/logs/tracky.log
StandardError=append:$SCRIPT_DIR/logs/error.log

[Install]
WantedBy=multi-user.target
EOF

    echo -e "${GREEN}✓ Created tracky.service${NC}"
    echo -e "To install and enable this service on your DigitalOcean droplet, run:"
    echo -e "  ${BOLD}sudo cp tracky.service /etc/systemd/system/${NC}"
    echo -e "  ${BOLD}sudo systemctl daemon-reload${NC}"
    echo -e "  ${BOLD}sudo systemctl enable --now tracky${NC}"
fi

echo -e "\n${BOLD}${GREEN}=============================================================="
echo "          🎉 Tracky AI Setup Completed Successfully!          "
echo "=============================================================="
echo -e "${NC}"
echo "To start Tracky AI anytime, simply run:"
echo -e "  ${BOLD}./run.sh${NC}"
echo ""
echo -e "Log file: ${CYAN}logs/tracky.log${NC}"
echo -e "Memory file: ${CYAN}memory.log${NC}"
echo ""
