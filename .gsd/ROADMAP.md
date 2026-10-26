# ROADMAP.md — Tracky AI Execution Roadmap

> **Single Source of Truth** for Tracky AI project implementation.

## Phase Overview

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 1** | Project Scaffolding, Configuration & Logging | Completed |
| **Phase 2** | SQLite Database Layer, Models & Lifecycle Cleanup | Completed |
| **Phase 3** | Gemini LLM Engine, Tool Calling & Model Fallback | Completed |
| **Phase 4** | Proactive Background Scheduler & Voice (STT/TTS) | Completed |
| **Phase 5** | Messaging Adapters (Telegram & WhatsApp) & FastAPI Entrypoint | Completed |
| **Phase 6** | Interactive `setup.sh` Wizard, Systemd Service & Empirical Verification | Completed |

---

### Phase 1: Scaffolding, Configuration & Logging
- [x] Create project directory structure (`core/`, `db/`, `adapters/`, `logs/`).
- [x] Implement `core/config.py` with Pydantic validation for `config.json`.
- [x] Create `config.json.example`.
- [x] Implement rotating logger in `core/logger.py` writing to `logs/tracky.log` and `logs/error.log`.
- [x] Define dependencies in `requirements.txt`.

### Phase 2: Database Layer & Models
- [x] Implement `db/database.py` with async SQLite (`aiosqlite`).
- [x] Create tables: `tasks`, `events`, `reminders`, `chat_history`.
- [x] Implement CRUD functions: create/read/update/delete for tasks, events, reminders.
- [x] Implement auto-cleanup for finished events and fired reminders.

### Phase 3: LLM Engine, Tools & Memory
- [x] Implement `core/memory.py` for rolling memory (last 100 messages or 24-48h) + `memory.log`.
- [x] Implement `core/guardrails.py` for rate-limiting, message size limits, and safety.
- [x] Implement `core/tools.py` with schema for LLM function calling (tasks, reminders, events).
- [x] Implement `core/llm.py` with primary model (e.g., `gemma-2-27b-it` or `gemini-2.0-flash`) and backup fallback on 429/errors.

### Phase 4: Scheduler & Voice
- [x] Implement `core/scheduler.py` with `APScheduler` async loop.
- [x] Implement proactive reminder trigger that notifies user via the originating chat adapter.
- [x] Implement `core/voice.py` for STT (audio transcription via Gemini multimodal) and TTS via `edge-tts`.

### Phase 5: Messaging Adapters & App Orchestraction
- [x] Implement `adapters/base.py` defining standard interface.
- [x] Implement `adapters/telegram_bot.py` with polling/webhook support, text & voice note handling.
- [x] Implement `adapters/whatsapp_bot.py` for Twilio / Meta webhook processing.
- [x] Implement `app.py` unifying FastAPI HTTP server, bot runners, and scheduler lifecycle.

### Phase 6: Setup Wizard, Service & Verification
- [x] Create interactive `setup.sh` that checks Python, dependencies, prompts user, tests keys, generates `config.json` and systemd file.
- [x] Write integration test harness `tests/test_tracky.py` verifying database, scheduler, memory, and LLM tool calling.
- [x] Create user guide `README.md` and verify end-to-end functionality.
