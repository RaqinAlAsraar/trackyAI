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

# Server Deployment Type
echo -e "\n${YELLOW}Where will you run Tracky AI?${NC}"
echo "1) Local Linux machine"
echo "2) DigitalOcean / Cloud VPS (with systemd service option)"
read -rp "Select option [1/2] (default: 1): " SERVER_CHOICE
SERVER_CHOICE=${SERVER_CHOICE:-1}

# Gemini API Key
echo -e "\n${YELLOW}Google Gemini API Key:${NC}"
echo "Get one for free at https://aistudio.google.com/"
read -rp "Enter your Gemini API Key: " GEMINI_KEY
while [ -z "$GEMINI_KEY" ]; do
    echo -e "${RED}API key cannot be empty.${NC}"
    read -rp "Enter your Gemini API Key: " GEMINI_KEY
done

# Primary Model Selection
echo -e "\n${YELLOW}Select Primary LLM Model:${NC}"
echo "1) gemma-2-27b-it (Recommended Open Weights)"
echo "2) gemini-2.0-flash (Ultra fast, state-of-the-art multimodal)"
echo "3) gemini-1.5-flash (Fast & lightweight)"
echo "4) gemini-1.5-pro (Deep reasoning)"
echo "5) Custom model name"
read -rp "Select primary model [1-5] (default: 2): " MODEL_CHOICE
MODEL_CHOICE=${MODEL_CHOICE:-2}

case $MODEL_CHOICE in
    1) PRIMARY_MODEL="gemma-2-27b-it" ;;
    2) PRIMARY_MODEL="gemini-2.0-flash" ;;
    3) PRIMARY_MODEL="gemini-1.5-flash" ;;
    4) PRIMARY_MODEL="gemini-1.5-pro" ;;
    5)
        read -rp "Enter custom primary model name: " PRIMARY_MODEL
        ;;
    *) PRIMARY_MODEL="gemini-2.0-flash" ;;
esac

# Backup Model Selection
echo -e "\n${YELLOW}Select Backup Fallback Model (used automatically if primary hits rate limits or errors):${NC}"
echo "1) gemini-1.5-flash (Highly recommended as reliable backup)"
echo "2) gemini-2.0-flash"
echo "3) gemma-2-27b-it"
echo "4) Custom model name"
read -rp "Select backup model [1-4] (default: 1): " BACKUP_CHOICE
BACKUP_CHOICE=${BACKUP_CHOICE:-1}

case $BACKUP_CHOICE in
    1) BACKUP_MODEL="gemini-1.5-flash" ;;
    2) BACKUP_MODEL="gemini-2.0-flash" ;;
    3) BACKUP_MODEL="gemma-2-27b-it" ;;
    4)
        read -rp "Enter custom backup model name: " BACKUP_MODEL
        ;;
    *) BACKUP_MODEL="gemini-1.5-flash" ;;
esac

# Messaging Platform Selection
echo -e "\n${YELLOW}Which messaging platform(s) do you want to configure?${NC}"
echo "1) Telegram only (Easiest & recommended for daily use)"
echo "2) WhatsApp only (via Twilio)"
echo "3) Both Telegram and WhatsApp"
read -rp "Select platform [1-3] (default: 1): " PLATFORM_CHOICE
PLATFORM_CHOICE=${PLATFORM_CHOICE:-1}

TELEGRAM_ENABLED=false
WHATSAPP_ENABLED=false
TELEGRAM_TOKEN=""
TELEGRAM_MODE="polling"
TWILIO_SID=""
TWILIO_TOKEN=""
TWILIO_PHONE="whatsapp:+14155238886"

if [ "$PLATFORM_CHOICE" == "1" ] || [ "$PLATFORM_CHOICE" == "3" ]; then
    TELEGRAM_ENABLED=true
    echo -e "\n${BOLD}${BLUE}--- Telegram Bot Setup ---${NC}"
    echo "Create a bot in Telegram by messaging @BotFather and copy the HTTP API Token."
    read -rp "Enter your Telegram Bot Token: " TELEGRAM_TOKEN
    
    echo "Connection mode:"
    echo "1) Polling (Works immediately locally & VPS without public domain or SSL)"
    echo "2) Webhook (Requires public HTTPS domain)"
    read -rp "Select Telegram mode [1/2] (default: 1): " TG_MODE_CHOICE
    if [ "$TG_MODE_CHOICE" == "2" ]; then
        TELEGRAM_MODE="webhook"
    else
        TELEGRAM_MODE="polling"
    fi
fi

if [ "$PLATFORM_CHOICE" == "2" ] || [ "$PLATFORM_CHOICE" == "3" ]; then
    WHATSAPP_ENABLED=true
    echo -e "\n${BOLD}${BLUE}--- WhatsApp (Twilio) Setup ---${NC}"
    echo "Get credentials at https://console.twilio.com/ -> Messaging -> Try WhatsApp Sandbox"
    read -rp "Enter Twilio Account SID: " TWILIO_SID
    read -rp "Enter Twilio Auth Token: " TWILIO_TOKEN
    read -rp "Enter Twilio WhatsApp Number (default: whatsapp:+14155238886): " INPUT_TWILIO_PHONE
    if [ -n "$INPUT_TWILIO_PHONE" ]; then
        TWILIO_PHONE="$INPUT_TWILIO_PHONE"
    fi
fi

# Timezone Selection
DEFAULT_TZ="Asia/Kolkata"
if [ -f /etc/timezone ]; then
    DEFAULT_TZ=$(cat /etc/timezone)
elif command -v timedatectl &> /dev/null; then
    DETECTED_TZ=$(timedatectl | grep "Time zone" | awk '{print $3}')
    if [ -n "$DETECTED_TZ" ]; then
        DEFAULT_TZ="$DETECTED_TZ"
    fi
fi

echo -e "\n${YELLOW}Your Timezone:${NC}"
read -rp "Enter timezone (default: $DEFAULT_TZ): " USER_TZ
USER_TZ=${USER_TZ:-$DEFAULT_TZ}

# 4. Generate config.json
echo -e "\n${BLUE}[4/6] Generating config.json...${NC}"

cat <<EOF > config.json
{
  "app": {
    "name": "Tracky AI",
    "host": "0.0.0.0",
    "port": 8000,
    "timezone": "$USER_TZ",
    "debug": true
  },
  "gemini": {
    "api_key": "$GEMINI_KEY",
    "primary_model": "$PRIMARY_MODEL",
    "backup_model": "$BACKUP_MODEL",
    "temperature": 0.4,
    "max_output_tokens": 1024
  },
  "database": {
    "path": "tracky.db"
  },
  "memory": {
    "max_history_messages": 100,
    "max_history_hours": 48,
    "memory_log_file": "memory.log"
  },
  "telegram": {
    "enabled": $TELEGRAM_ENABLED,
    "bot_token": "$TELEGRAM_TOKEN",
    "mode": "$TELEGRAM_MODE",
    "webhook_url": "",
    "allowed_user_ids": []
  },
  "whatsapp": {
    "enabled": $WHATSAPP_ENABLED,
    "provider": "twilio",
    "twilio_account_sid": "$TWILIO_SID",
    "twilio_auth_token": "$TWILIO_TOKEN",
    "twilio_phone_number": "$TWILIO_PHONE",
    "meta_phone_number_id": "",
    "meta_access_token": "",
    "meta_verify_token": "tracky_webhook_verify_token"
  },
  "voice": {
    "stt_enabled": true,
    "tts_enabled": true,
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
echo "Log file: ${CYAN}logs/tracky.log${NC}"
echo "Memory file: ${CYAN}memory.log${NC}"
echo ""
EOF

chmod +x setup.sh
