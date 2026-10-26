"""
Memory module for Tracky AI.
Manages conversation buffer (last 100 messages or 24-48 hours)
and appends formatted interaction logs to memory.log.
"""

import os
from datetime import datetime, timezone
from typing import List, Dict, Optional
import aiofiles

from core.logger import logger
from core.config import settings
from db.database import add_chat_message, get_recent_chat_history


try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    import pytz
except ImportError:
    pytz = None


class ConversationMemory:
    def __init__(self):
        self.memory_log_path = settings.memory.absolute_log_path
        self.max_messages = settings.memory.max_history_messages
        self.max_hours = settings.memory.max_history_hours

    async def record_interaction(
        self,
        user_id: str,
        platform: str,
        user_text: str,
        assistant_reply: str,
        duration: Optional[float] = None,
        model_name: Optional[str] = None,
        tools_called: Optional[List[str]] = None,
    ) -> None:
        """
        Saves user message and assistant reply to DB.
        If log_discussions is enabled, logs discussion and timing metrics to discussions.log & memory.log.
        Can be toggled off anytime by setting "log_discussions": false in config.json.
        """
        # 1. Always save to SQLite for conversation context
        await add_chat_message(user_id, platform, "user", user_text)
        await add_chat_message(user_id, platform, "assistant", assistant_reply)

        # 2. Check if discussion logging is enabled
        is_logging_enabled = getattr(settings.app, "log_discussions", True) and getattr(
            settings.memory, "log_discussions", True
        )
        if not is_logging_enabled:
            return

        # 3. Append formatted discussion entry with execution time
        try:
            time_now_utc = datetime.now(timezone.utc)
            local_time_str = ""
            try:
                if ZoneInfo:
                    tz = ZoneInfo(settings.app.timezone)
                    local_time_str = time_now_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
                elif pytz:
                    tz = pytz.timezone(settings.app.timezone)
                    local_time_str = time_now_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception:
                pass
            if not local_time_str:
                local_time_str = time_now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

            timing_str = f"Time: {duration:.2f}s" if duration is not None else "Time: N/A"
            model_str = f"Model: {model_name}" if model_name else "Model: N/A"
            tools_str = f"Tools: {', '.join(tools_called)}" if tools_called else "Tools: None"

            log_entry = (
                f"{'='*70}\n"
                f"[{local_time_str}] [{platform.upper()}:{user_id}]\n"
                f"METRICS: {timing_str} | {model_str} | {tools_str}\n"
                f"USER: {user_text}\n"
                f"{settings.app.assistant_name.upper()}: {assistant_reply}\n"
                f"{'='*70}\n\n"
            )

            disc_path = settings.memory.absolute_discussion_log_path
            os.makedirs(os.path.dirname(os.path.abspath(disc_path)), exist_ok=True)
            async with aiofiles.open(disc_path, mode="a", encoding="utf-8") as f:
                await f.write(log_entry)

            async with aiofiles.open(self.memory_log_path, mode="a", encoding="utf-8") as f:
                await f.write(log_entry)

            logger.info(
                f"💬 [DISCUSSION] [{platform}:{user_id}] {timing_str} | {model_str} | "
                f"USER: '{user_text[:35]}' -> AI: '{assistant_reply[:35]}'"
            )
        except Exception as e:
            logger.error(f"Failed to append discussion log: {e}")

    async def get_context_history(self, user_id: str) -> List[Dict[str, str]]:
        """Retrieves formatted history for LLM prompting within window limits."""
        return await get_recent_chat_history(
            user_id=user_id,
            limit=self.max_messages,
            max_hours=self.max_hours,
        )


memory_manager = ConversationMemory()
