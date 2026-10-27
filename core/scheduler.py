"""
Scheduler and background worker for Tracky AI.
Handles:
- Checking pending reminders and dispatching proactive notifications to Telegram / WhatsApp
- Lifecycle database cleanup for finished events and old reminders
"""

import asyncio
from datetime import datetime, timezone
from typing import Callable, Dict, Any, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.logger import logger
from core.config import settings
import db.database as db

from core.nlp_engine import format_iso_to_local


def get_reminder_emoji(text: str) -> str:
    tl = text.lower()
    if any(w in tl for w in ["coffee", "tea", "espresso", "latte"]):
        return "☕"
    if any(w in tl for w in ["call", "phone", "ring"]):
        return "📞"
    if any(w in tl for w in ["namaz", "prayer", "fajr", "maghrib", "isha", "dhuhr", "asr"]):
        return "🕌"
    if any(w in tl for w in ["exam", "study", "read", "book", "test", "notes"]):
        return "📚"
    if any(w in tl for w in ["gym", "workout", "exercise", "run", "walk", "tennis"]):
        return "💪"
    if any(w in tl for w in ["code", "coding", "hack", "project", "dev", "program"]):
        return "💻"
    if any(w in tl for w in ["pill", "medicine", "medication", "doctor"]):
        return "💊"
    if any(w in tl for w in ["eat", "lunch", "dinner", "breakfast", "meal", "food"]):
        return "🍽️"
    if any(w in tl for w in ["sleep", "bed", "rest"]):
        return "🌙"
    if any(w in tl for w in ["meeting", "interview", "appointment"]):
        return "📅"
    return "🔔"


# Callback registry for outbound message dispatchers: platform -> callback(chat_id, message_text)
_dispatchers: Dict[str, Callable] = {}


def register_dispatcher(platform: str, callback: Callable) -> None:
    _dispatchers[platform] = callback
    logger.info(f"Registered outbound notification dispatcher for platform '{platform}'")


class BackgroundScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self._is_checking = False

    def start(self) -> None:
        if self.is_running:
            return

        # Check due reminders every 5 seconds (non-blocking with concurrency headroom)
        self.scheduler.add_job(
            self.check_and_dispatch_reminders,
            "interval",
            seconds=5,
            id="reminder_checker",
            max_instances=5,
            misfire_grace_time=30,
            coalesce=True,
            replace_existing=True,
        )

        # Run database lifecycle cleanup every 10 minutes
        self.scheduler.add_job(
            self.run_lifecycle_cleanup,
            "interval",
            minutes=10,
            id="lifecycle_cleanup",
            max_instances=2,
            misfire_grace_time=60,
            coalesce=True,
            replace_existing=True,
        )

        self.scheduler.start()
        self.is_running = True
        logger.info("BackgroundScheduler started successfully.")

    def stop(self) -> None:
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("BackgroundScheduler stopped.")

    async def _dispatch_single_reminder(self, r: Dict[str, Any]) -> None:
        reminder_id = r["id"]
        platform = r["platform"]
        chat_id = r["chat_id"]
        text = r["reminder_text"]
        user_id = r["user_id"]

        logger.info(f"Firing reminder #{reminder_id} for user {user_id} on {platform}:{chat_id}")

        user_name = settings.app.user_name or "Friend"
        icon = get_reminder_emoji(text)
        time_display = format_iso_to_local(r.get("remind_at", ""), settings.app.timezone)

        alert_message = (
            f"🔔 **Hey {user_name}! Time for your reminder:**\n\n"
            f"{icon} **{text}**\n\n"
            f"⏰ *Scheduled for: {time_display}*"
        )

        dispatcher = _dispatchers.get(platform)
        if dispatcher:
            try:
                await dispatcher(chat_id, alert_message)
            except Exception as ex:
                logger.error(f"Failed to dispatch reminder #{reminder_id} via {platform}: {ex}")
        else:
            logger.warning(f"No dispatcher registered for platform '{platform}'.")

    async def check_and_dispatch_reminders(self) -> None:
        if self._is_checking:
            return
        self._is_checking = True
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            due_reminders = await db.get_due_reminders(now_iso)
            for r in due_reminders:
                reminder_id = r["id"]
                # Mark as triggered in database immediately to prevent duplicate dispatches
                await db.mark_reminder_triggered(reminder_id)
                # Dispatch in background task so scheduler tick finishes in milliseconds
                asyncio.create_task(self._dispatch_single_reminder(r))
        except Exception as e:
            logger.error(f"Error in check_and_dispatch_reminders: {e}")
        finally:
            self._is_checking = False

    async def run_lifecycle_cleanup(self) -> None:
        """Removes expired events and old reminders to keep database clean."""
        try:
            events_cleaned = await db.cleanup_expired_events()
            reminders_cleaned = await db.cleanup_old_reminders()
            if events_cleaned or reminders_cleaned:
                logger.info(f"Lifecycle cleanup completed: {events_cleaned} events, {reminders_cleaned} reminders cleaned.")
        except Exception as e:
            logger.error(f"Error during lifecycle cleanup: {e}")


scheduler_service = BackgroundScheduler()
