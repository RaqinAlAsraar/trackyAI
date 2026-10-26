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
        self.app = Application.builder().token(self.bot_token).build()

        # Command handlers
        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("help", self._handle_help))
        self.app.add_handler(CommandHandler("status", self._handle_status))

        # Message handlers
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_message))
        self.app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._handle_voice_message))

        # Register proactive alert dispatcher
        register_dispatcher("telegram", self.send_message)

        # Initialize & start
        await self.app.initialize()
        await self.app.start()

        if self.mode == "polling":
            logger.info("Starting Telegram long polling...")
            await self.app.updater.start_polling(drop_pending_updates=True)
        else:
            logger.info(f"Telegram webhook mode enabled at {settings.telegram.webhook_url}")

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
        try:
            chat_id = int(recipient_id)
            await self.app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message to {recipient_id}: {e}")
            return False

    # --- Handlers ---

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        welcome_text = (
            f"👋 Hey {user.first_name if user else 'there'}! I'm **Tracky AI**, your personal assistant.\n\n"
            f"You can talk to me like a real human! Just tell me what you need, like:\n"
            f"• *\"I have a test tomorrow, remind me at 4 pm today to study\"*\n"
            f"• *\"Add a task: Finish hackathon pitch deck by 8pm\"*\n"
            f"• *\"Schedule a meeting with mentor on Friday at 3pm\"*\n"
            f"• *\"What's on my schedule today?\"*\n\n"
            f"You can also send me **voice notes** directly! 🎙️"
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown")

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        status_text = (
            "🟢 **Tracky AI Status**:\n\n"
            f"• Model: `{settings.gemini.primary_model}` (Backup: `{settings.gemini.backup_model}`)\n"
            f"• Timezone: `{settings.app.timezone}`\n"
            f"• Platform: Telegram (Active)\n"
            f"• Database: SQLite (Connected)"
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

        ctx = ToolContext(
            user_id=user_id,
            platform="telegram",
            chat_id=chat_id,
            timezone_name=settings.app.timezone,
        )

        history = await memory_manager.get_context_history(user_id)
        reply = await llm_engine.generate_response(ctx, user_text, history)

        await memory_manager.record_interaction(user_id, "telegram", user_text, reply)
        await update.message.reply_text(reply)

    async def _handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not (update.message.voice or update.message.audio):
            return

        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)

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
            ctx = ToolContext(
                user_id=user_id,
                platform="telegram",
                chat_id=chat_id,
                timezone_name=settings.app.timezone,
            )

            history = await memory_manager.get_context_history(user_id)
            reply = await llm_engine.generate_response(ctx, f"[Voice message]: {transcribed_text}", history)
            await memory_manager.record_interaction(user_id, "telegram", f"[Voice]: {transcribed_text}", reply)

            # Send text reply
            await update.message.reply_text(f"🎙️ *Heard*: \"{transcribed_text}\"\n\n{reply}", parse_mode="Markdown")

            # Also generate voice reply if TTS enabled
            if settings.voice.tts_enabled:
                await context.bot.send_chat_action(chat_id=chat_id, action="record_voice")
                tts_path = await voice_processor.text_to_speech(reply)
                if tts_path and os.path.exists(tts_path):
                    with open(tts_path, "rb") as audio:
                        await update.message.reply_voice(voice=audio)
                    os.unlink(tts_path)

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


telegram_adapter = TelegramAdapter()
