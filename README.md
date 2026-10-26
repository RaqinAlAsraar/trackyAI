# 🤖 Tracky AI — Your Personal Voice & Chat Assistant

> **Tracky AI** is an intelligent, multi-channel personal assistant designed for **Telegram** and **WhatsApp**. It manages your daily tasks, calendar schedules, and proactive reminders naturally through text and voice notes.
>
> Simply talk to Tracky like a real person:  
> *"Hey, I have a test tomorrow, remind me at 4 pm today to study"*  
> Tracky understands, confirms like a human, schedules the event, and actively alerts you right when it's time!

---

## ✨ Features

- 📱 **Multi-Channel Adapters**:
  - **Telegram**: Supports polling mode (zero configuration, works locally and on VPS without public domain) and webhook mode.
  - **WhatsApp**: Built-in webhook receiver for Twilio Sandbox & Production or Meta WhatsApp Cloud API.
- 🧠 **Google Gemini & Gemma with Auto-Fallback**:
  - Uses state-of-the-art models (`gemini-2.0-flash`, `gemma-2-27b-it`, `gemini-1.5-flash`).
  - Automatic failover: if your primary model hits rate limits (429) or quota errors, Tracky automatically fails over to your backup model seamlessly.
- ⏰ **Proactive Background Scheduler**:
  - Powered by `APScheduler` (AsyncIO).
  - Outbound alerts: Tracky actively pings you on Telegram or WhatsApp the exact moment your reminder is due.
- 🗄️ **Smart SQLite DB with Lifecycle Auto-Cleanup**:
  - Tracks tasks, calendar events, active reminders, and chat history.
  - Automatic cleanup: expired events and completed reminders are automatically pruned from the database.
- 📝 **Rolling Conversation Memory (`memory.log`)**:
  - Keeps a rolling memory of the last 100 messages / 48 hours for contextual, natural multi-turn conversations.
  - Formatted audit trail saved to `memory.log`.
- 🎙️ **Voice First (STT & TTS)**:
  - **Speech-to-Text (STT)**: Send voice notes on Telegram; Tracky transcribes and processes them via Gemini multimodal audio understanding.
  - **Text-to-Speech (TTS)**: Tracky replies with lifelike neural voice notes using `edge-tts` (Microsoft Neural voices).
- 🛡️ **Built-in Guardrails**:
  - Sliding-window rate limiting per user (prevents spam and runaway token usage).
  - Maximum character size enforcement.
  - Optional user ID allowlists for security.
- 🚀 **1-Command Interactive Setup (`setup.sh`)**:
  - Guides you through API keys, model selection, platform toggles, and timezone.
  - Generates `config.json` and systemd service file for DigitalOcean.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Linux / macOS (Ubuntu, Debian, Zorin OS, Arch, etc.)
- Python 3.10+
- `ffmpeg` (for voice note processing):
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```

### 2. Run Setup Wizard
Run the interactive setup script:
```bash
./setup.sh
```

The wizard will:
1. Create a Python virtual environment (`.venv`) and install dependencies.
2. Prompt for your **Gemini API Key** (get one free at [aistudio.google.com](https://aistudio.google.com/)).
3. Let you pick your **Primary Model** (e.g. `gemini-2.0-flash` or `gemma-2-27b-it`) and **Backup Fallback Model**.
4. Configure your chosen messaging app:
   - **Telegram**: Simply paste your bot token from [@BotFather](https://t.me/botfather).
   - **WhatsApp**: Enter your Twilio credentials or Meta webhook tokens.
5. Set your local timezone (e.g., `Asia/Kolkata`).
6. Initialize the SQLite database and create `config.json`.

---

## 🏃 Starting Tracky AI

To launch Tracky AI:
```bash
./run.sh
```
Or directly with:
```bash
.venv/bin/python app.py
```

The app will start:
- Telegram Bot polling
- Background proactive reminder scheduler
- FastAPI server on `http://0.0.0.0:8000`

---

## 🌐 Deploying to DigitalOcean / VPS (24/7 Service)

During `./setup.sh`, if you select **DigitalOcean / Cloud VPS**, a systemd service file `tracky.service` is automatically generated for you.

To install it as a continuous 24/7 background service:
```bash
sudo cp tracky.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tracky
```

### Useful Management Commands:
- Check service status: `sudo systemctl status tracky`
- Restart service: `sudo systemctl restart tracky`
- View live logs: `tail -f logs/tracky.log`

---

## 💬 Example Conversations

```
You: "Hey Tracky! I have an AI hackathon demo tomorrow, remind me at 4 pm today to polish the slides"
Tracky: "Got it! I've scheduled a reminder for today at 4:00 PM: 'Polish hackathon demo slides'. Good luck preparing!"

... at 4:00 PM sharp ...
Tracky (Notification):
🔔 Reminder from Tracky AI
Polish hackathon demo slides
⏰ Scheduled for: 2026-10-26T16:00:00+05:30

You: "What's on my schedule today?"
Tracky: "Here is what you have today:
1. 🔔 Reminder: Polish hackathon demo slides (4:00 PM)
2. 📌 Task: Finish pitch deck (High priority)"
```

---

## 🧪 Testing

Run the test suite to verify database CRUD, scheduler, tools, and memory:
```bash
.venv/bin/pytest tests/test_tracky.py -v
```

---

## 📁 Project Structure

```
trackyAi/
├── config.json.example   # Configuration template
├── setup.sh              # Interactive setup wizard
├── run.sh                # Launcher script
├── app.py                # FastAPI & multi-adapter orchestrator
├── requirements.txt      # Python dependencies
├── core/
│   ├── config.py         # Pydantic configuration loader
│   ├── guardrails.py     # Per-user rate limiting & input validation
│   ├── llm.py            # Gemini engine with tool loop & backup model fallback
│   ├── logger.py         # Rotating file loggers (logs/tracky.log & logs/error.log)
│   ├── memory.py         # Rolling conversation memory (memory.log)
│   ├── scheduler.py      # APScheduler proactive alerts & auto-cleanup
│   ├── tools.py          # LLM function declarations & CRUD handlers
│   └── voice.py          # Gemini STT & edge-tts TTS
├── db/
│   └── database.py       # SQLite connection, tables, and CRUD
├── adapters/
│   ├── base.py           # BaseMessenger abstract class
│   ├── telegram_bot.py   # Telegram polling/webhook, text & voice notes
│   └── whatsapp_bot.py   # WhatsApp Twilio/Meta webhook router
├── logs/                 # Runtime application logs
└── tests/
    └── test_tracky.py    # Pytest integration tests
```
