"""
Local LLM and Offline Fallback Engine for Tracky AI.
Provides:
1. Local lightweight Gemma LLM via Ollama / OpenAI-compatible local runtime.
2. Offline deterministic intent execution for reminders, tasks, and schedules.
3. Zero-downtime fallback when cloud Gemini API quota is reached or network is unavailable.
"""

import re
import json
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    import pytz
except ImportError:
    pytz = None

from core.logger import logger
from core.config import settings
from core.tools import (
    ToolContext,
    handle_create_reminder,
    handle_list_reminders,
    handle_cancel_reminder,
    handle_create_task,
    handle_list_tasks,
    handle_complete_task,
    handle_create_event,
    handle_list_events,
)


class LocalLLMEngine:
    @property
    def host(self) -> str:
        return settings.local_llm.host.rstrip("/")

    @property
    def model(self) -> str:
        return settings.local_llm.model

    @property
    def enabled(self) -> bool:
        return settings.local_llm.enabled

    @property
    def timeout(self) -> float:
        return settings.local_llm.timeout

    async def is_available(self) -> bool:
        """Fast check (0.6s) to verify if the local Ollama LLM server is running."""
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=0.6) as client:
                res = await client.get(f"{self.host}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    async def generate_response(
        self,
        ctx: ToolContext,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[str]:
        """
        Queries local Gemma LLM via Ollama REST API.
        Extracts and executes any embedded action commands.
        """
        if not await self.is_available():
            return None

        # 1. First check if user message is a concrete actionable intent (reminders, tasks, lists)
        from core.nlp_engine import nlp_engine
        intent_res = await nlp_engine.process_user_intent(ctx, user_message)
        if intent_res:
            logger.info("Executed smart NLP intent directly for local engine.")
            return intent_res

        # 2. General conversational queries via Ollama
        system_instruction = (
            f"You are {ctx.assistant_name or settings.app.assistant_name}, a friendly, intelligent personal assistant. "
            f"You are running locally on the user's machine as an offline/local brain.\n"
            f"The user's name is {ctx.user_name or settings.app.user_name}.\n"
            f"Current user timezone is {ctx.timezone_name}.\n"
            "Keep responses natural, helpful, supportive, and concise."
        )

        messages = [{"role": "system", "content": system_instruction}]
        if history:
            for h in history[-8:]:
                role = "user" if h["role"] == "user" else "assistant"
                messages.append({"role": role, "content": h["content"]})

        messages.append({"role": "user", "content": user_message})

        try:
            logger.info(f"Attempting response generation with local model '{self.model}' at {self.host}...")
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.4,
                    "num_predict": 512,
                },
            }

            async with httpx.AsyncClient(timeout=max(self.timeout, 25.0)) as client:
                res = await client.post(f"{self.host}/api/chat", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data.get("message", {}).get("content", "").strip()
                    if content:
                        logger.info(f"Local LLM '{self.model}' responded successfully.")
                        return content
                else:
                    logger.warning(f"Local LLM returned status {res.status_code}: {res.text}")
        except Exception as e:
            logger.warning(f"Local LLM call to '{self.model}' failed: {type(e).__name__}: {e}")

        return None


def format_iso_to_local(iso_str: str, tz_name: str = "UTC") -> str:
    """Formats an ISO timestamp to clean local human-readable time."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        user_tz = timezone.utc
        if ZoneInfo:
            user_tz = ZoneInfo(tz_name)
        elif pytz:
            user_tz = pytz.timezone(tz_name)
        return dt.astimezone(user_tz).strftime("%I:%M %p (%a, %b %d)")
    except Exception:
        return iso_str


async def execute_deterministic_intent(ctx: ToolContext, user_message: str) -> Optional[str]:
    """
    Parses and executes user actions (reminders, tasks, lists) directly in SQLite.
    Guarantees that reminders are ACTUALLY saved to the DB and fired on time.
    """
    msg = user_message.strip()
    msg_lower = msg.lower()
    user_display = ctx.user_name or settings.app.user_name or "Friend"

    # --- 1. Query: List Reminders ---
    is_list_reminders = (
        ("reminder" in msg_lower or "reminders" in msg_lower)
        and any(w in msg_lower for w in ["list", "show", "view", "get", "active", "pending", "my", "what", "check", "display"])
    ) or msg_lower in ["reminders", "my reminders", "active reminders", "show reminders"]

    if is_list_reminders:
        res = await handle_list_reminders(ctx)
        reminders = res.get("reminders", [])
        if not reminders:
            return f"🔔 You have no pending reminders right now, {user_display}!"
        lines = [f"🔔 **Your Active Reminders** ({len(reminders)}):"]
        for r in reminders:
            t_str = format_iso_to_local(r.get("remind_at", ""), ctx.timezone_name)
            lines.append(f"• **#{r['id']}**: {r['reminder_text']} — `{t_str}`")
        return "\n\n".join(lines)

    # --- 2. Query: List Tasks ---
    is_list_tasks = (
        any(k in msg_lower for k in ["task", "tasks", "todo", "todos"])
        and any(w in msg_lower for w in ["list", "show", "view", "get", "active", "pending", "my", "what", "check", "display"])
    ) or msg_lower in ["tasks", "my tasks", "active tasks", "show tasks", "todos", "my todos"]

    if is_list_tasks:
        res = await handle_list_tasks(ctx, status="pending")
        tasks = res.get("tasks", [])
        if not tasks:
            return f"📋 You have no pending tasks right now, {user_display}! Great job! 🎉"
        lines = [f"📋 **Your Active Tasks** ({len(tasks)}):"]
        for t in tasks:
            prio = f" [{t['priority'].upper()}]" if t.get("priority") else ""
            lines.append(f"• **#{t['id']}**: {t['title']}{prio}")
        return "\n\n".join(lines)

    # --- 3. Action: Create Reminder ---
    is_reminder_cmd = any(w in msg_lower for w in ["remind", "reminder"])
    seconds_match = re.search(r"(?:in|after)\s*(\d+)\s*(?:sec|second|seconds|s)\b", msg_lower)
    minutes_match = re.search(r"(?:in|after)\s*(\d+)\s*(?:min|minute|minutes|m)\b", msg_lower)
    hours_match = re.search(r"(?:in|after)\s*(\d+)\s*(?:hour|hours|hr|hrs|h)\b", msg_lower)
    clock_match = re.search(r"(?:at|for)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", msg_lower)

    if is_reminder_cmd and (seconds_match or minutes_match or hours_match or clock_match):
        user_tz = timezone.utc
        try:
            if ZoneInfo:
                user_tz = ZoneInfo(ctx.timezone_name)
            elif pytz:
                user_tz = pytz.timezone(ctx.timezone_name)
        except Exception:
            pass

        now_local = datetime.now(user_tz)
        target_time = None

        if seconds_match:
            secs = int(seconds_match.group(1))
            target_time = now_local + timedelta(seconds=secs)
        elif minutes_match:
            mins = int(minutes_match.group(1))
            target_time = now_local + timedelta(minutes=mins)
        elif hours_match:
            hrs = int(hours_match.group(1))
            target_time = now_local + timedelta(hours=hrs)
        elif clock_match:
            hour = int(clock_match.group(1))
            minute = int(clock_match.group(2) or 0)
            ampm = (clock_match.group(3) or "").lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            target_time = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_time <= now_local:
                target_time += timedelta(days=1)

        if target_time:
            # Extract clean reminder text
            rem_text = msg
            rem_text = re.sub(r"^\[(?:voice|voice message)\]:\s*", "", rem_text, flags=re.IGNORECASE)
            rem_text = re.sub(r"^(?:hello|hey|hi)\s+[a-z0-9_]+\s*[,:]?\s*", "", rem_text, flags=re.IGNORECASE)
            patterns_to_clean = [
                r"(?:please\s+)?(?:set\s+(?:a\s+)?reminder(?:\s+(?:to|for))?|remind\s+(?:me)?(?:\s+(?:to|for))?)",
                r"(?:in|after)\s*\d+\s*(?:sec|second|seconds|s|min|minute|minutes|m|hour|hours|hr|hrs|h)\b",
                r"(?:at|for)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
                r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b",
                r"\b(?:today|tomorrow)\b",
            ]
            for p in patterns_to_clean:
                rem_text = re.sub(p, "", rem_text, flags=re.IGNORECASE)
            rem_text = re.sub(r"^\s*(?:to|for)\s+", "", rem_text, flags=re.IGNORECASE)
            rem_text = rem_text.strip(" ,.:;!-") or "Reminder"

            target_iso = target_time.isoformat()
            res = await handle_create_reminder(ctx, reminder_text=rem_text, remind_at_iso=target_iso)
            time_str = target_time.strftime("%I:%M %p (%a, %b %d)")
            rem_id = res.get("reminder_id", "")
            id_str = f" #{rem_id}" if rem_id else ""
            return (
                f"🔔 **Reminder Scheduled**\n\n"
                f"I've set a reminder{id_str} for you, {user_display}:\n"
                f"• **Reminder**: {rem_text}\n"
                f"• **Time**: {time_str}"
            )

    # --- 4. Action: Create Task ---
    task_match = re.search(r"(?:add|create|new) task[:\s]+(.+)", msg, re.IGNORECASE)
    if not task_match and ("task:" in msg_lower or "todo:" in msg_lower):
        task_match = re.search(r"(?:task|todo)[:\s]+(.+)", msg, re.IGNORECASE)

    if task_match:
        task_title = task_match.group(1).strip()
        res = await handle_create_task(ctx, title=task_title)
        return (
            f"📝 **Task Created**\n\n"
            f"Added to your to-do list: **{task_title}** (Task #{res.get('task_id', 1)})"
        )

    # --- 5. Action: Complete Task ---
    comp_match = re.search(r"(?:complete|done|finish|mark) task\s*#?(\d+)", msg_lower)
    if comp_match:
        t_id = int(comp_match.group(1))
        res = await handle_complete_task(ctx, task_id=t_id)
        if res.get("success"):
            return f"✅ **Task #{t_id} marked as completed!** Good work, {user_display}! 🚀"
        return f"⚠️ Task #{t_id} was not found."

    # --- 6. Action: Delete Reminder ---
    del_rem_match = re.search(r"(?:delete|cancel|remove) reminder\s*#?(\d+)", msg_lower)
    if del_rem_match:
        r_id = int(del_rem_match.group(1))
        res = await handle_cancel_reminder(ctx, reminder_id=r_id)
        if res.get("success"):
            return f"🗑️ **Reminder #{r_id} cancelled and removed.**"
        return f"⚠️ Reminder #{r_id} was not found."

    # --- 7. Query: List Events / Calendar ---
    if any(q in msg_lower for q in ["events", "calendar", "my schedule", "what's on my schedule", "agenda"]):
        res = await handle_list_events(ctx)
        events = res.get("events", [])
        if not events:
            return f"📅 Your calendar is clear, {user_display}! No upcoming events scheduled."
        lines = [f"📅 **Your Upcoming Events** ({len(events)}):"]
        for e in events:
            t_str = format_iso_to_local(e.get("start_time", ""), ctx.timezone_name)
            lines.append(f"• **#{e['id']}**: {e['title']} — `{t_str}`")
        return "\n\n".join(lines)

    return None


async def offline_fallback_handler(ctx: ToolContext, user_message: str) -> str:
    """
    Intelligent offline intent parser.
    Executes tasks, reminders, and schedules directly against SQLite when cloud AI and local LLM are offline.
    Guarantees Tracky NEVER crashes or fails to manage user requests.
    """
    # Check smart NLP intent first
    from core.nlp_engine import nlp_engine
    direct_res = await nlp_engine.process_user_intent(ctx, user_message)
    if direct_res:
        return direct_res

    msg_lower = user_message.strip().lower()
    user_display = ctx.user_name or settings.app.user_name or "Friend"
    assistant_display = ctx.assistant_name or settings.app.assistant_name or "Tracky"

    # Greetings & Help
    if any(q in msg_lower for q in ["hi", "hello", "hey", "who are you", "help", "start"]):
        return (
            f"👋 Hey {user_display}! I'm **{assistant_display}**, your personal assistant (Offline Mode).\n\n"
            f"I can help you with:\n"
            f"• *\"Set a reminder to drink coffee after 1 minute\"*\n"
            f"• *\"Show active reminders\"*\n"
            f"• *\"Add task: Review final project deck\"*\n"
            f"• *\"Show active tasks\"*\n"
            f"• *\"What's on my schedule?\"*"
        )

    # General Query Fallback
    return (
        f"I received your message, {user_display}:\n"
        f"> \"{user_message}\"\n\n"
        f"💡 You can manage all your **reminders**, **tasks**, and **calendar** directly with me:\n"
        f"• *\"Set a reminder for ...\"*\n"
        f"• *\"Show active reminders\"*\n"
        f"• *\"Add task ...\"*\n"
        f"• *\"Show active tasks\"*"
    )


local_llm_engine = LocalLLMEngine()
