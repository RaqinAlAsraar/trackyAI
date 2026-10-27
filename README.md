# 🤖 Tracky AI

> **Your personal AI assistant for Telegram & WhatsApp.**  
> Manages your daily task lists, timers, calendar events, and proactive reminders naturally through chat and voice.

---

## 📌 What is Tracky AI?

Tracky AI understands plain, conversational language just like a human:
- *"Create today's task list: prep demo slides, review pull requests, send email"*
- *"I have an exam on 30 October. Set a reminder for that day at 6:00 am"*
- *"Change it's timing to 7 am"* (instant contextual rescheduling)
- *"Show weekly tasklist"* (grouped by day)
- *"Delete previous tasklists as well which has no use now"* (cleans up outdated lists)

Tracky runs **100% locally** on lightweight smart NLP (<10ms response time, zero API quota usage), with optional support for local Ollama (`gemma2:2b`) or Google Gemini cloud models.

---

## 🚀 Quick Setup (3 Minutes)

### 1. Requirements
- Linux or macOS
- Python 3.10+
- Node.js 18+ (only needed for WhatsApp Web QR linking)

### 2. Run the Setup Wizard
```bash
./setup.sh
```
The wizard will guide you through:
1. Creating the virtual environment (`.venv`) and installing dependencies.
2. Choosing your AI engine:
   - **Local Only (Recommended)**: Runs completely offline with smart NLP + Ollama.
   - **Cloud (Gemini)**: Enter a free Gemini API key.
3. Choosing your messaging platform:
   - **Telegram**: Paste your bot token from [@BotFather](https://t.me/botfather).
   - **WhatsApp Web Session**: Link your personal WhatsApp via QR code (no Twilio account or fees required).
   - **Both**: Run on Telegram and WhatsApp simultaneously.

---

## 📱 Connecting Messaging Apps

### Option A: Telegram
Just paste your bot token during `./setup.sh`. It connects instantly via long-polling (no public domain or webhook needed).

### Option B: WhatsApp (Web Session QR)
1. In a terminal, run:
   ```bash
   bash whatsapp_bridge/start.sh
   ```
2. Scan the QR code shown in the terminal (or open `http://localhost:3001/qr`) using **WhatsApp > Linked Devices > Link a Device**.
3. Credentials are saved locally in `whatsapp_bridge/auth_info/` so you stay logged in permanently.

---

## 🏃 Running Tracky AI

Start the assistant:
```bash
./run.sh
```
Tracky is now live and listening for messages on your connected platforms!

---

## 💬 How to Use (Sample Commands)

| Action | What you say |
|---|---|
| **Add Daily Tasks** | `"Create today's task list: buy groceries, finish assignment, gym"` |
| **Add Tasks with Date** | `"Create tasklist for tomorrow: deploy backend, run test suite"` |
| **Set Reminder** | `"Remind me to call mom at 7:30 pm"` |
| **Set Date Reminder** | `"I have an exam on 30 October. Set a reminder for that day at 6 am"` |
| **Reschedule without ID** | `"Change it's timing to 8 am"` *(updates the reminder you just created)* |
| **View by Scope** | `"Show active reminders for today"`, `"weekly tasklist"`, `"for the week"` |
| **Fuzzy Task Completion** | `"Gym and assignment are done"` |
| **Clean Outdated Lists** | `"Delete previous tasklists as well which has no use now"` |
| **Delete Specific List** | `"Delete tasklist for tomorrow"` |
| **Rename Reminder / Task**| `"Rename reminder #12 to Team Standup"` |

---

## ⚙️ Useful Scripts

- **Switch AI Mode**: `./switch_mode.sh` (toggle between Local-Only, Cloud Gemini, or Hybrid).
- **Run Tests**: `.venv/bin/pytest tests/` (runs all 23 unit and integration tests).
- **View Live Logs**: `tail -f logs/tracky.log`.

---

## 🔒 Privacy & Configuration
- All personal tokens, numbers, and settings are saved in `config.json`.
- `config.json`, databases (`*.db`), and session credentials are in `.gitignore` and **never** pushed to GitHub.
