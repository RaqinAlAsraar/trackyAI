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

# Callback registry for outbound message dispatchers: platform -> callback(chat_id, message_text)
_dispatchers: Dict[str, Callable] = {}


def register_dispatcher(platform: str, callback: Callable) -> None:
    _dispatchers[platform] = callback
    logger.info(f"Registered outbound notification dispatcher for platform '{platform}'")


class BackgroundScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

    def start(self) -> None:
        if self.is_running:
            return

        # Check due reminders every 5 seconds
        self.scheduler.add_job(
            self.check_and_dispatch_reminders,
            "interval",
            seconds=5,
            id="reminder_checker",
            replace_existing=True,
        )

        # Run database lifecycle cleanup every 10 minutes
        self.scheduler.add_job(
            self.run_lifecycle_cleanup,
            "interval",
            minutes=10,
            id="lifecycle_cleanup",
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

    async def check_and_dispatch_reminders(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            due_reminders = await db.get_due_reminders(now_iso)
            for r in due_reminders:
                reminder_id = r["id"]
                platform = r["platform"]
                chat_id = r["chat_id"]
                text = r["reminder_text"]

                logger.info(f"Firing reminder #{reminder_id} for user {r['user_id']} on {platform}:{chat_id}")
                
                alert_message = (
                    f"🔔 **Reminder from {settings.app.assistant_name}**\n\n"
                    f"{text}\n\n"
                    f"⏰ Scheduled for: {r['remind_at']}"
                )

                dispatcher = _dispatchers.get(platform)
                dispatched = False
                if dispatcher:
                    try:
                        await dispatcher(chat_id, alert_message)
                        dispatched = True
                    except Exception as ex:
                        logger.error(f"Failed to dispatch reminder #{reminder_id} via {platform}: {ex}")
                else:
                    logger.warning(f"No dispatcher registered for platform '{platform}'.")

                # Mark as triggered in database
                await db.mark_reminder_triggered(reminder_id)

        except Exception as e:
            logger.error(f"Error in check_and_dispatch_reminders: {e}")

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
