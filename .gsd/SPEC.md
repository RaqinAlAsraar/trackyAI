# SPEC.md — Project Specification: Tracky AI

> **Status**: `FINALIZED`

## Vision
**Tracky AI** is an intelligent, conversation-driven personal assistant for Telegram and WhatsApp that manages tasks, schedules, and reminders naturally through text and voice notes. Users simply chat naturally (e.g. *"I have a test tomorrow, remind me at 4 pm today to study"*), and Tracky AI schedules, tracks, and actively notifies the user when due, with automatic lifecycle cleanup and recent conversation memory.

## Goals
1. **Multi-Channel Chat Assistant**: Support Telegram (polling and webhook modes) and WhatsApp (Twilio webhook / Meta API).
2. **Natural Language Task & Schedule Management**: Parse intents and trigger actions (reminders, tasks, calendar events) via Gemini Tool Calling.
3. **Proactive Reminders & Lifecyle Cleanup**: Background async scheduler that notifies the user at the exact target time and removes/archives expired events from SQLite.
4. **Contextual Memory**: Maintain a rolling memory buffer (`memory.log` + SQLite) of recent discussions (last 100 messages or 24-48 hours) with token conservation.
5. **Speech Support**: Voice notes to text (STT) via Gemini multimodal audio understanding, and text-to-speech (TTS) voice replies via `edge-tts`.
6. **Model Fallback**: Default to selected Google Gemini/Gemma model with automated fallback to secondary model on 429/quota/503 errors.
7. **One-Click Setup & Portability**: Interactive `setup.sh` that configures keys, models, platforms, and generates `config.json` and optional systemd service for DigitalOcean/Linux.

## Non-Goals (Out of Scope)
- Complex multi-tenant SaaS billing / user tiers (focused on hackathon & personal daily assistant).
- Heavyweight enterprise calendar sync (Google Calendar OAuth can be added as a future module; internal SQLite schedule is primary).

## Constraints
- Python 3.10+ runtime.
- Lightweight SQLite storage without requiring external database servers.
- Works offline/local for Telegram long-polling without needing public DNS/domain.

## Success Criteria
- [x] Configuration wizard (`setup.sh`) prompts for credentials, models, and platform selection, outputting `config.json`.
- [x] SQLite database schema initialized with `tasks`, `events`, `reminders`, `chat_history`.
- [x] Background scheduler (`APScheduler`) triggers proactive alerts directly to chat.
- [x] Gemini tool-calling engine handles CRUD operations on tasks/reminders/events.
- [x] Model fallback switches smoothly between primary and backup models.
- [x] Audio voice note support for STT and TTS.
- [x] Guardrails enforce message rate-limiting and conversation window capping.
- [x] System verified through test runner and integration test script.

---
*Last updated: 2026-10-26*
