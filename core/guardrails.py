"""
Guardrails and validation for Tracky AI.
Enforces:
- Per-user rate limiting (sliding window per minute)
- Maximum input size restrictions
- Chat/User authorization checks
"""

import time
from typing import Dict, List, Tuple
from core.config import settings
from core.logger import logger


class Guardrails:
    def __init__(self):
        self.user_message_timestamps: Dict[str, List[float]] = {}
        self.rate_limit = settings.guardrails.rate_limit_messages_per_minute
        self.max_chars = settings.guardrails.max_message_chars

    def check_user_allowed(self, user_id: str, platform: str) -> Tuple[bool, str]:
        """Checks if user is authorized if an allowlist is configured."""
        if platform == "telegram" and settings.telegram.allowed_user_ids:
            try:
                numeric_id = int(user_id)
                if numeric_id not in settings.telegram.allowed_user_ids:
                    logger.warning(f"Unauthorized access attempt by Telegram user {user_id}")
                    return False, "Access restricted. You are not on the authorized user list."
            except ValueError:
                pass
        return True, ""

    def check_rate_limit(self, user_id: str) -> Tuple[bool, str]:
        """Sliding window rate limit check."""
        now = time.time()
        window_start = now - 60.0

        timestamps = self.user_message_timestamps.get(user_id, [])
        # Keep only timestamps within the last 60 seconds
        valid_timestamps = [ts for ts in timestamps if ts > window_start]
        self.user_message_timestamps[user_id] = valid_timestamps

        if len(valid_timestamps) >= self.rate_limit:
            logger.warning(f"Rate limit exceeded for user {user_id}")
            return False, "You're sending messages too fast! Please wait a moment."

        valid_timestamps.append(now)
        return True, ""

    def validate_message(self, text: str) -> Tuple[bool, str]:
        """Validates incoming message payload."""
        if not text or not text.strip():
            return False, "Message cannot be empty."
        if len(text) > self.max_chars:
            return False, f"Message is too long (max {self.max_chars} characters)."
        return True, ""

    def check_all(self, user_id: str, platform: str, text: str) -> Tuple[bool, str]:
        allowed, msg = self.check_user_allowed(user_id, platform)
        if not allowed:
            return False, msg

        allowed, msg = self.check_rate_limit(user_id)
        if not allowed:
            return False, msg

        allowed, msg = self.validate_message(text)
        if not allowed:
            return False, msg

        return True, ""


guardrails = Guardrails()
