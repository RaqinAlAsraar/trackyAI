"""
Memory module for Tracky AI.
Manages conversation buffer (last 100 messages or 24-48 hours)
and appends formatted interaction logs to memory.log.
"""

import os
from datetime import datetime, timezone
from typing import List, Dict
import aiofiles

from core.logger import logger
from core.config import settings
from db.database import add_chat_message, get_recent_chat_history


class ConversationMemory:
    def __init__(self):
        self.memory_log_path = settings.memory.absolute_log_path
        self.max_messages = settings.memory.max_history_messages
        self.max_hours = settings.memory.max_history_hours

    async def record_interaction(
        self, user_id: str, platform: str, user_text: str, assistant_reply: str
    ) -> None:
        """Saves user message and assistant reply to DB and appends to memory.log."""
        # 1. Save to SQLite
        await add_chat_message(user_id, platform, "user", user_text)
        await add_chat_message(user_id, platform, "assistant", assistant_reply)

        # 2. Append to memory.log for fast audit & contextual tracking
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            log_entry = (
                f"[{timestamp}] [{platform.upper()}:{user_id}]\n"
                f"USER: {user_text}\n"
                f"TRACKY: {assistant_reply}\n"
                f"{'-'*50}\n"
            )
            async with aiofiles.open(self.memory_log_path, mode="a", encoding="utf-8") as f:
                await f.write(log_entry)
        except Exception as e:
            logger.error(f"Failed to append to memory.log: {e}")

    async def get_context_history(self, user_id: str) -> List[Dict[str, str]]:
        """Retrieves formatted history for LLM prompting within window limits."""
        return await get_recent_chat_history(
            user_id=user_id,
            limit=self.max_messages,
            max_hours=self.max_hours,
        )


memory_manager = ConversationMemory()
