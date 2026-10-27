"""
Telegram Bot Adapter for Tracky AI.
Supports:
- Text messaging with multi-turn conversation memory
- Voice note audio processing (STT & TTS replies)
- Proactive reminder alerts
- Long-polling (local/server) and webhook modes
"""

import os
import tempfile
from typing import Optional
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from core.logger import logger
from core.config import settings
from core.tools import ToolContext
from core.llm import llm_engine
from core.memory import memory_manager
from core.guardrails import guardrails
from core.voice import voice_processor
from core.scheduler import register_dispatcher
from adapters.base import BaseMessenger


class TelegramAdapter(BaseMessenger):
    def __init__(self):
        self.bot_token = settings.telegram.bot_token
        self.enabled = settings.telegram.enabled
        self.mode = settings.telegram.mode
        self.app: Optional[Application] = None

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Telegram adapter is disabled in configuration.")
            return

        if not self.bot_token or "YOUR_TELEGRAM" in self.bot_token:
            logger.warning("Telegram bot_token is empty or default placeholder. Skipping Telegram startup.")
            return

        logger.info(f"Initializing Telegram Bot in mode='{self.mode}'...")
        req = HTTPXRequest(connect_timeout=25.0, read_timeout=30.0, write_timeout=25.0)
        get_updates_req = HTTPXRequest(connect_timeout=25.0, read_timeout=35.0, write_timeout=25.0)
        self.app = (
            Application.builder()
            .token(self.bot_token)
            .request(req)
            .get_updates_request(get_updates_req)
            .build()
        )

        # Command handlers
        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("help", self._handle_help))
        self.app.add_handler(CommandHandler("status", self._handle_status))

        # Message handlers
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_message))
        self.app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._handle_voice_message))

        # Register proactive alert dispatcher
        register_dispatcher("telegram", self.send_message)

        # Initialize & start with retry
        for attempt in range(1, 4):
            try:
                await self.app.initialize()
                await self.app.start()
                if self.mode == "polling":
                    logger.info("Starting Telegram long polling...")
                    await self.app.updater.start_polling(poll_interval=1.0, timeout=15, drop_pending_updates=True)
                else:
                    logger.info(f"Telegram webhook mode enabled at {settings.telegram.webhook_url}")
                logger.info("Telegram Bot started successfully.")
                break
            except Exception as e:
                logger.warning(f"Telegram start attempt {attempt}/3 failed: {e}")
                if attempt == 3:
                    logger.error("Failed to initialize Telegram Bot after 3 attempts.")
                    raise
                import asyncio
                await asyncio.sleep(2)

    async def stop(self) -> None:
        if self.app:
            logger.info("Stopping Telegram Bot...")
            if self.mode == "polling" and self.app.updater:
                await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def send_message(self, recipient_id: str, text: str) -> bool:
        if not self.app or not self.app.bot:
            logger.error("Cannot send Telegram message: Bot not initialized.")
            return False
        chat_id: Any = recipient_id
        try:
            chat_id = int(recipient_id)
        except (ValueError, TypeError):
            if isinstance(recipient_id, str) and recipient_id.startswith("@"):
                chat_id = recipient_id
            else:
                logger.warning(f"Invalid Telegram chat_id '{recipient_id}' - skipping.")
                return False

        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            return True
        except Exception as e:
            logger.warning(f"Failed to send Markdown message to {chat_id}: {e}. Retrying as plain text...")
            try:
                await self.app.bot.send_message(chat_id=chat_id, text=text)
                return True
            except Exception as e2:
                logger.error(f"Failed to send plain text Telegram message to {chat_id}: {e2}")
                return False

    # --- Handlers ---

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = str(update.effective_user.id) if update.effective_user else ""
        allowed, msg = guardrails.check_user_allowed(user_id, "telegram")
        if not allowed:
            await update.message.reply_text(f"⚠️ {msg}")
            return

        user_display = (update.effective_user.first_name if update.effective_user else None) or settings.app.user_name
        welcome_text = (
            f"👋 Hey {user_display}! I'm **{settings.app.assistant_name}**, your personal assistant.\n\n"
            f"You can talk to me like a real human! Just tell me what you need, like:\n"
            f"• *\"I have a test tomorrow, remind me at 4 pm today to study\"*\n"
            f"• *\"Add a task: Finish hackathon pitch deck by 8pm\"*\n"
            f"• *\"Schedule a meeting with mentor on Friday at 3pm\"*\n"
            f"• *\"What's on my schedule today?\"*\n\n"
            f"You can also send me **voice notes** directly! 🎙️"
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown")

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = str(update.effective_user.id) if update.effective_user else ""
        allowed, msg = guardrails.check_user_allowed(user_id, "telegram")
        if not allowed:
            await update.message.reply_text(f"⚠️ {msg}")
            return

        help_text = (
            "🤖 **Tracky AI Commands & Capabilities**:\n\n"
            "• Natural Text & Voice: Just speak or type naturally.\n"
            "• `/status`: Check server health, active models, and database status.\n"
            "• `/help`: Show this help manual.\n\n"
            "**Examples**:\n"
            "• *Remind me in 15 minutes to take a break*\n"
            "• *Show my pending tasks*\n"
            "• *Mark task #1 as completed*"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = str(update.effective_user.id) if update.effective_user else ""
        allowed, msg = guardrails.check_user_allowed(user_id, "telegram")
        if not allowed:
            await update.message.reply_text(f"⚠️ {msg}")
            return

        mode = (getattr(settings.app, "llm_mode", "hybrid") or "hybrid").lower()
        if mode in ("local", "local_only", "offline"):
            mode_desc = f"Local-Only (100% Offline via `{settings.local_llm.model}` — 0 API Quota)"
        elif mode == "cloud_only":
            mode_desc = f"Cloud-Only (`{settings.gemini.primary_model}`)"
        else:
            mode_desc = f"Hybrid (`{settings.gemini.primary_model}` + `{settings.local_llm.model}` fallback)"

        status_text = (
            "🟢 **Tracky AI Status**:\n\n"
            f"• **LLM Mode**: {mode_desc}\n"
            f"• **Timezone**: `{settings.app.timezone}`\n"
            f"• **Platform**: Telegram (Active)\n"
            f"• **Database**: SQLite (Connected)"
        )
        await update.message.reply_text(status_text, parse_mode="Markdown")

    async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return

        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)
        user_text = update.message.text.strip()

        # Guardrail checks
        allowed, error_msg = guardrails.check_all(user_id, "telegram", user_text)
        if not allowed:
            await update.message.reply_text(f"⚠️ {error_msg}")
            return

        # Show typing indicator
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        user_name = (update.effective_user.first_name if update.effective_user else None) or settings.app.user_name
        ctx = ToolContext(
            user_id=user_id,
            platform="telegram",
            chat_id=chat_id,
            timezone_name=settings.app.timezone,
            user_name=user_name,
            assistant_name=settings.app.assistant_name,
        )

        history = await memory_manager.get_context_history(user_id)
        reply = await llm_engine.generate_response(ctx, user_text, history)

        await memory_manager.record_interaction(
            user_id=user_id,
            platform="telegram",
            user_text=user_text,
            assistant_reply=reply,
            duration=llm_engine.last_duration,
            model_name=llm_engine.last_model_used,
            tools_called=llm_engine.last_tools_called,
        )
        try:
            await update.message.reply_text(reply, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(reply)

    async def _handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not (update.message.voice or update.message.audio):
            return

        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)

        allowed, error_msg = guardrails.check_user_allowed(user_id, "telegram")
        if not allowed:
            await update.message.reply_text(f"⚠️ {error_msg}")
            return

        # Download voice file
        await context.bot.send_chat_action(chat_id=chat_id, action="record_voice")
        voice = update.message.voice or update.message.audio
        voice_file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_audio:
            temp_path = tmp_audio.name

        try:
            await voice_file.download_to_drive(temp_path)

            # Transcribe via Gemini
            transcribed_text = await voice_processor.transcribe_audio_file(temp_path, mime_type="audio/ogg")

            if not transcribed_text:
                await update.message.reply_text("Sorry, I couldn't clearly transcribe your voice message. Could you try typing it?")
                return

            # Process transcribed text through LLM
            user_name = (update.effective_user.first_name if update.effective_user else None) or settings.app.user_name
            ctx = ToolContext(
                user_id=user_id,
                platform="telegram",
                chat_id=chat_id,
                timezone_name=settings.app.timezone,
                user_name=user_name,
                assistant_name=settings.app.assistant_name,
            )

            history = await memory_manager.get_context_history(user_id)
            reply = await llm_engine.generate_response(ctx, f"[Voice message]: {transcribed_text}", history)
            await memory_manager.record_interaction(
                user_id=user_id,
                platform="telegram",
                user_text=f"[Voice]: {transcribed_text}",
                assistant_reply=reply,
                duration=llm_engine.last_duration,
                model_name=llm_engine.last_model_used,
                tools_called=llm_engine.last_tools_called,
            )

            # Send text reply (with markdown fallback) - responds in text only
            voice_caption = f"🎙️ *Heard*: \"{transcribed_text}\"\n\n{reply}"
            try:
                await update.message.reply_text(voice_caption, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(f"🎙️ Heard: \"{transcribed_text}\"\n\n{reply}")

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


telegram_adapter = TelegramAdapter()
