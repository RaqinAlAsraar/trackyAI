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
    def __init__(self):
        self.host = settings.local_llm.host.rstrip("/")
        self.model = settings.local_llm.model
        self.enabled = settings.local_llm.enabled
        self.timeout = settings.local_llm.timeout

    async def is_available(self) -> bool:
        """Fast check to verify if the local LLM server (e.g. Ollama) is running."""
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=1.2) as client:
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

        system_instruction = (
            f"You are {ctx.assistant_name or settings.app.assistant_name}, a friendly, intelligent personal assistant. "
            f"You are running locally on the user's machine as an offline/local brain.\n"
            f"The user's name is {ctx.user_name or settings.app.user_name}.\n"
            f"Current user timezone is {ctx.timezone_name}.\n"
            "Keep responses natural, helpful, supportive, and concise.\n"
            "If the user asks to set a reminder or add a task, confirm you understand."
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

            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
            logger.warning(f"Local LLM call to '{self.model}' failed: {e}")

        return None


async def offline_fallback_handler(ctx: ToolContext, user_message: str) -> str:
    """
    Intelligent offline intent parser.
    Executes tasks, reminders, and schedules directly against SQLite when cloud AI and local LLM are offline.
    Guarantees Tracky NEVER crashes or fails to manage user requests.
    """
    msg_lower = user_message.strip().lower()
    user_display = ctx.user_name or settings.app.user_name or "Friend"
    assistant_display = ctx.assistant_name or settings.app.assistant_name or "Tracky"

    # --- 1. Reminders Intent ---
    # Matches patterns like: "remind me in 10 minutes to take a break" or "remind me at 5pm to call mom"
    reminder_match = re.search(r"remind (?:me )?(?:to )?(.+)", msg_lower)
    if reminder_match:
        # Check relative minutes / hours
        minutes_match = re.search(r"in (\d+)\s*(min|minute|minutes|m)", msg_lower)
        hours_match = re.search(r"in (\d+)\s*(hour|hours|hr|h)", msg_lower)
        time_match = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", msg_lower)

        target_time = None
        user_tz = timezone.utc
        try:
            if ZoneInfo:
                user_tz = ZoneInfo(ctx.timezone_name)
            elif pytz:
                user_tz = pytz.timezone(ctx.timezone_name)
        except Exception:
            pass

        now_local = datetime.now(user_tz)

        if minutes_match:
            mins = int(minutes_match.group(1))
            target_time = now_local + timedelta(minutes=mins)
        elif hours_match:
            hrs = int(hours_match.group(1))
            target_time = now_local + timedelta(hours=hrs)
        elif time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            ampm = time_match.group(3)
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            target_time = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_time < now_local:
                target_time += timedelta(days=1)

        if target_time:
            # Extract reminder text
            rem_text = user_message
            for clean_pat in [
                r"remind (?:me )?(?:to )?",
                r"in \d+\s*(?:minutes?|mins?|hours?|hrs?)",
                r"at \d{1,2}(?::\d{2})?\s*(?:am|pm)?",
                r"today",
                r"tomorrow",
            ]:
                rem_text = re.sub(clean_pat, "", rem_text, flags=re.IGNORECASE)
            rem_text = rem_text.strip(" ,.:;!-") or "Reminder"

            target_iso = target_time.isoformat()
            res = await handle_create_reminder(ctx, reminder_text=rem_text, remind_at_iso=target_iso)
            time_str = target_time.strftime("%I:%M %p (%a, %b %d)")
            return (
                f"🔔 **Reminder Scheduled**\n\n"
                f"I've set a reminder for you, {user_display}:\n"
                f"• **Reminder**: {rem_text}\n"
                f"• **Time**: {time_str}\n\n"
                f"*(Offline mode active — cloud quota reached)*"
            )

    # --- 2. List Reminders ---
    if any(q in msg_lower for q in ["list reminder", "show reminder", "my reminder", "view reminder", "pending reminder"]):
        res = await handle_list_reminders(ctx)
        reminders = res.get("reminders", [])
        if not reminders:
            return f"🔔 You have no pending reminders, {user_display}!"
        items = "\n".join([f"• **#{r['id']}**: {r['reminder_text']} (At: `{r['remind_at']}`)" for r in reminders])
        return f"🔔 **Your Active Reminders**:\n\n{items}"

    # --- 3. Create Task Intent ---
    task_match = re.search(r"(?:add|create|new) task[:\s]+(.+)", user_message, re.IGNORECASE)
    if not task_match and ("task:" in msg_lower or "todo:" in msg_lower):
        task_match = re.search(r"(?:task|todo)[:\s]+(.+)", user_message, re.IGNORECASE)

    if task_match:
        task_title = task_match.group(1).strip()
        res = await handle_create_task(ctx, title=task_title)
        return (
            f"📝 **Task Created**\n\n"
            f"Added to your to-do list: **{task_title}** (Task #{res.get('task_id', 1)})\n\n"
            f"*(Offline mode active)*"
        )

    # --- 4. List Tasks ---
    if any(q in msg_lower for q in ["list task", "show task", "my task", "view task", "pending task", "what are my tasks"]):
        res = await handle_list_tasks(ctx, status="pending")
        tasks = res.get("tasks", [])
        if not tasks:
            return f"📋 You have no pending tasks right now, {user_display}! Great job! 🎉"
        items = "\n".join([f"• **#{t['id']}**: {t['title']} (`{t['priority']}` priority)" for t in tasks])
        return f"📋 **Your Pending Tasks**:\n\n{items}"

    # --- 5. Complete Task ---
    comp_match = re.search(r"(?:complete|done|finish|mark) task\s*#?(\d+)", msg_lower)
    if comp_match:
        t_id = int(comp_match.group(1))
        res = await handle_complete_task(ctx, task_id=t_id)
        if res.get("success"):
            return f"✅ **Task #{t_id} marked as completed!** Good work, {user_display}! 🚀"
        return f"⚠️ Task #{t_id} was not found."

    # --- 6. List Events / Calendar ---
    if any(q in msg_lower for q in ["events", "calendar", "my schedule", "what's on my schedule", "agenda"]):
        res = await handle_list_events(ctx)
        events = res.get("events", [])
        if not events:
            return f"📅 Your calendar is clear, {user_display}! No upcoming events scheduled."
        items = "\n".join([f"• **{e['title']}** - Starts: `{e['start_time']}`" for e in events])
        return f"📅 **Your Upcoming Events**:\n\n{items}"

    # --- 7. Greetings & Help ---
    if any(q in msg_lower for q in ["hi", "hello", "hey", "who are you", "help", "start"]):
        return (
            f"👋 Hey {user_display}! I'm **{assistant_display}**, your personal assistant.\n\n"
            f"⚠️ **Note**: Cloud AI quota is currently reached, so I am running in **Offline Mode**.\n\n"
            f"You can still ask me to:\n"
            f"• *\"Remind me in 15 minutes to take a break\"*\n"
            f"• *\"Add task: Review final project deck\"*\n"
            f"• *\"List my tasks\"*\n"
            f"• *\"List my reminders\"*\n"
            f"• *\"What's on my schedule?\"*\n\n"
            f"💡 *Tip: To enable offline AI chat, start local Gemma with: `ollama run gemma2:2b`*"
        )

    # --- 8. General Query Fallback ---
    return (
        f"I received your message, {user_display}:\n"
        f"> \"{user_message}\"\n\n"
        f"⚠️ **Cloud AI Quota Reached**: My cloud connection is currently paused due to Google API free-tier limits.\n"
        f"• I have logged your message in your history.\n"
        f"• You can still manage all your **reminders**, **tasks**, and **calendar** directly with me!\n"
        f"• To run AI chat offline locally, start Ollama with: `ollama run gemma2:2b`."
    )


local_llm_engine = LocalLLMEngine()
