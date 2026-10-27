"""
Smart Local NLP & Multi-Action Intent Engine for Tracky AI.
Provides:
1. Semantic intent detection (Create, List, Delete, Complete, Clean) for Reminders, Tasks, and Calendar Events.
2. Multi-action statement splitting (e.g. "Remind me X after 2 mins AND check project at 12:47").
3. Multi-item batch processing (e.g. "Add tennis ball, namaz, and exam study in the tasks").
4. Multi-ID deletion & inactive item cleanup (e.g. "Remove 53, 52", "Remove inactive reminders now").
5. Natural conversational replies like a real personal human assistant.
"""

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

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
    handle_delete_task,
    handle_create_event,
    handle_list_events,
)
import db.database as db


def get_user_tz(tz_name: str):
    try:
        if ZoneInfo:
            return ZoneInfo(tz_name)
        elif pytz:
            return pytz.timezone(tz_name)
    except Exception:
        pass
    return timezone.utc


def format_iso_to_local(iso_str: str, tz_name: str = "UTC") -> str:
    """Formats an ISO timestamp into warm human-readable local time."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        user_tz = get_user_tz(tz_name)
        dt_local = dt.astimezone(user_tz)
        now_local = datetime.now(user_tz)

        time_part = dt_local.strftime("%I:%M %p").lstrip("0")
        
        # Check day relative to today
        if dt_local.date() == now_local.date():
            return f"Today at {time_part}"
        elif dt_local.date() == (now_local + timedelta(days=1)).date():
            return f"Tomorrow at {time_part}"
        else:
            return dt_local.strftime(f"%a, %b %d at {time_part}")
    except Exception:
        return iso_str


def parse_target_datetime(text: str, tz_name: str = "UTC") -> Optional[Tuple[datetime, str]]:
    """
    Parses natural time expressions and returns (target_datetime, cleaned_text_without_time).
    Handles relative offsets ('after 2 minutes', 'in 15 seconds', 'in 3 hours')
    and clock times ('at 12:47', 'at 12:50 PM', 'tonight at 9', 'tomorrow at 10am').
    """
    user_tz = get_user_tz(tz_name)
    now = datetime.now(user_tz)
    text_lower = text.lower()

    # 1. Relative seconds
    sec_m = re.search(r"\b(?:in|after)\s*(\d+)\s*(?:sec|second|seconds|s)\b", text_lower)
    if sec_m:
        secs = int(sec_m.group(1))
        cleaned = re.sub(r"\b(?:in|after)\s*" + re.escape(sec_m.group(1)) + r"\s*(?:sec|second|seconds|s)\b", "", text, flags=re.IGNORECASE)
        return now + timedelta(seconds=secs), cleaned

    # 2. Relative minutes
    min_m = re.search(r"\b(?:in|after)\s*(\d+)\s*(?:min|minute|minutes|m)\b", text_lower)
    if min_m:
        mins = int(min_m.group(1))
        cleaned = re.sub(r"\b(?:in|after)\s*" + re.escape(min_m.group(1)) + r"\s*(?:min|minute|minutes|m)\b", "", text, flags=re.IGNORECASE)
        return now + timedelta(minutes=mins), cleaned

    # 3. Relative hours
    hr_m = re.search(r"\b(?:in|after)\s*(\d+)\s*(?:hour|hours|hr|hrs|h)\b", text_lower)
    if hr_m:
        hrs = int(hr_m.group(1))
        cleaned = re.sub(r"\b(?:in|after)\s*" + re.escape(hr_m.group(1)) + r"\s*(?:hour|hours|hr|hrs|h)\b", "", text, flags=re.IGNORECASE)
        return now + timedelta(hours=hrs), cleaned

    # 4. Specific clock time: 'at 12:47', 'at 12:50 PM', '12:15 pm'
    clock_m = re.search(r"\b(?:at|for)?\s*(\d{1,2}):(\d{2})\s*(am|pm)?\b", text_lower)
    if clock_m:
        hour = int(clock_m.group(1))
        minute = int(clock_m.group(2))
        ampm = (clock_m.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        elif not ampm:
            # If no am/pm specified, assume PM if hour <= 7 and current hour >= 10
            if hour <= 7 and now.hour >= 10:
                hour += 12

        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # If time already passed today, assume tomorrow
        if target <= now:
            target += timedelta(days=1)
        cleaned = text[:clock_m.start()] + text[clock_m.end():]
        return target, cleaned

    # 5. Simple hour time: 'at 4 pm', 'at 9 am'
    simple_clock = re.search(r"\b(?:at|for)\s*(\d{1,2})\s*(am|pm)\b", text_lower)
    if simple_clock:
        hour = int(simple_clock.group(1))
        ampm = simple_clock.group(2).lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        cleaned = text[:simple_clock.start()] + text[simple_clock.end():]
        return target, cleaned

    return None


def clean_reminder_title(raw_text: str) -> str:
    """Strips filler words and command wrappers from reminder text."""
    t = raw_text
    # Remove voice tag
    t = re.sub(r"^\[(?:voice|voice message)\]:\s*", "", t, flags=re.IGNORECASE)
    # Remove assistant callouts
    t = re.sub(r"^(?:hello|hey|hi)\s+[a-z0-9_]+\s*[,:]?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^[a-z0-9_]+\s*[,:]\s*", "", t, flags=re.IGNORECASE)
    # Remove command prefixes
    t = re.sub(r"^(?:please\s+)?(?:set\s+(?:a\s+)?reminder(?:\s+(?:to|for))?|remind\s+(?:me)?(?:\s+(?:to|for))?)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(?:and\s+)?(?:to\s+)?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:today|tomorrow|tonight)\b", "", t, flags=re.IGNORECASE)
    t = t.strip(" ,.:;!-")
    return t or "Reminder"


def split_items_list(text: str) -> List[str]:
    """
    Parses a string containing multiple items separated by commas, 'and', bullet points, or newlines.
    e.g. 'tennis ball, namaz, and exam study' -> ['tennis ball', 'namaz', 'exam study']
    """
    # Remove command prefixes like 'Create today's task list. Add...'
    cleaned = text
    cleaned = re.sub(r"^.*?\badd\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^.*?task\s*list[:.\s]+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:in\s+(?:the\s+)?tasks?|in\s+it|to\s+(?:the\s+)?(?:task\s*list|todo|list))\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" .")
    
    # Split by comma or semicolon or newline
    parts = re.split(r"[,;\n]+", cleaned)
    items = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Split trailing 'and item'
        sub_parts = re.split(r"\s+and\s+", p, flags=re.IGNORECASE)
        for sp in sub_parts:
            sp = sp.strip(" -•*.")
            sp = re.sub(r"^(?:add|and|item|tasks?)(?:[:\s]|\s)+", "", sp, flags=re.IGNORECASE).strip(" .")
            sp = re.sub(r"\s+(?:in\s+the\s+tasks?|in\s+it)$", "", sp, flags=re.IGNORECASE).strip(" .")
            if sp and sp.lower() not in ["tasks", "task", "in the tasks", "tasklist", "in it"]:
                items.append(sp)
    return items


class SmartNLPEngine:
    async def process_user_intent(self, ctx: ToolContext, user_message: str) -> Optional[str]:
        """
        Main NLP entry point.
        Analyzes the user's message, handles compound multi-actions, executes DB operations,
        and returns a rich human assistant response. Returns None if general conversational LLM is needed.
        """
        msg = user_message.strip()
        if not msg:
            return None

        # Clean voice prefix if present
        clean_msg = re.sub(r"^\[(?:voice|voice message)\]:\s*", "", msg, flags=re.IGNORECASE).strip()
        msg_lower = clean_msg.lower()
        user_display = ctx.user_name or settings.app.user_name or "Friend"
        assistant_display = ctx.assistant_name or settings.app.assistant_name or "Tracky"

        # -------------------------------------------------------------
        # 1. ACTION: Delete Inactive / Triggered Reminders
        # e.g. "Remove the inactive reminders now", "clear inactive reminders"
        # -------------------------------------------------------------
        if any(w in msg_lower for w in ["inactive", "triggered", "past", "old"]) and any(r in msg_lower for r in ["remind", "reminder", "reminders"]):
            if any(action in msg_lower for action in ["remove", "delete", "clear", "clean", "purge"]):
                count = await db.delete_inactive_reminders(ctx.user_id)
                if count > 0:
                    return f"🧹 All done, {user_display}! Cleaned up **{count} inactive reminder{'s' if count != 1 else ''}** from your list."
                return f"✨ Your reminder list is already tidy, {user_display}! No inactive or past reminders found."

        # -------------------------------------------------------------
        # 2. ACTION: Multi-ID Deletion (e.g. "Remove 53, 52", "delete 53 and 52", "remove reminders 53, 52")
        # -------------------------------------------------------------
        id_delete_match = re.search(r"^(?:please\s+)?(?:delete|remove|cancel)\s+(?:reminders?|tasks?|items?)?\s*#?(\d+(?:[\s,]+(?:and\s+)?#?\d+)*)$", msg_lower)
        if id_delete_match or (any(w in msg_lower for w in ["remove", "delete", "cancel"]) and re.search(r"\b\d+\b", msg_lower) and len(clean_msg.split()) <= 6):
            # Extract all numbers
            raw_ids = [int(n) for n in re.findall(r"\b\d+\b", clean_msg)]
            if raw_ids:
                # Try deleting from reminders first, then tasks
                rem_deleted = await db.delete_reminders_by_ids(raw_ids, ctx.user_id)
                task_deleted = await db.delete_tasks_by_ids(raw_ids, ctx.user_id)
                total = rem_deleted + task_deleted
                if total > 0:
                    id_list_str = ", ".join(f"#{i}" for i in raw_ids)
                    return f"🗑️ Done, {user_display}! Successfully removed {id_list_str} for you."
                return f"⚠️ None of the requested IDs ({', '.join(f'#{i}' for i in raw_ids)}) were found in your active items."

        # -------------------------------------------------------------
        # 3. ACTION: Delete existing task list and create new one
        # e.g. "Delete this and create new tasklist, add exam prep, coding and hacking in it"
        # -------------------------------------------------------------
        if ("delete this" in msg_lower or "clear task" in msg_lower or "replace task" in msg_lower) and any(w in msg_lower for w in ["create", "new", "add"]):
            # Clear existing tasks
            await db.delete_all_tasks(ctx.user_id, status="pending")
            # Extract items to add
            add_part = re.sub(r"^.*?add\s+", "", clean_msg, flags=re.IGNORECASE)
            items = split_items_list(add_part)
            if items:
                created = await db.add_multiple_tasks(ctx.user_id, ctx.platform, items)
                lines = [f"📋 **Task List Updated for you, {user_display}!**", "Cleared your previous tasks and added your new priorities:"]
                for t in created:
                    lines.append(f"• **#{t['id']}**: {t['title']}")
                return "\n\n".join(lines)
            return f"🗑️ Cleared your active task list, {user_display}! What would you like to add to your fresh list?"

        # -------------------------------------------------------------
        # 4. ACTION: Create Task List with Multiple Items
        # e.g. "Create today's task list. Add tennis ball, namaz, and exam study in the tasks."
        # -------------------------------------------------------------
        is_add_or_create_tasks = any(w in msg_lower for w in ["add", "create", "make", "new", "set"]) and any(t in msg_lower for t in ["task", "tasks", "todo", "todos", "tasklist", "task list"])
        if is_add_or_create_tasks and ("add" in msg_lower or ":" in clean_msg or "," in clean_msg):
            # Extract items portion
            match_items = re.search(r"(?:add|create|tasks?[:\s]+)(.+)$", clean_msg, re.IGNORECASE)
            if match_items:
                raw_items = match_items.group(1)
                items = split_items_list(raw_items)
                if items:
                    created = await db.add_multiple_tasks(ctx.user_id, ctx.platform, items)
                    lines = [f"📋 **Task Created! Added {len(created)} Task{'s' if len(created) != 1 else ''} for you, {user_display}!**"]
                    for t in created:
                        lines.append(f"• **#{t['id']}**: {t['title']}")
                    return "\n\n".join(lines)

        # -------------------------------------------------------------
        # 5. QUERY: List Tasks / To-Do
        # e.g. "today's task list", "show tasks", "my active tasks", "tasks"
        # -------------------------------------------------------------
        is_list_tasks = (
            any(k in msg_lower for k in ["task", "tasks", "todo", "todos", "tasklist"])
            and not any(neg in msg_lower for neg in ["add", "create", "new", "delete", "cancel", "remove", "finish", "complete"])
        ) or msg_lower in ["today's task list", "todays task list", "tasks", "my tasks", "active tasks", "show tasks", "show active tasks"]
        
        if is_list_tasks:
            res = await handle_list_tasks(ctx, status="pending")
            tasks = res.get("tasks", [])
            if not tasks:
                return f"📋 You have no pending tasks right now, {user_display}! You're completely up to date! 🎉"
            lines = [f"📋 **Your Active Tasks** ({len(tasks)}):"]
            for t in tasks:
                prio = f" [{t['priority'].upper()}]" if t.get("priority") and t["priority"] != "normal" else ""
                lines.append(f"• **#{t['id']}**: {t['title']}{prio}")
            return "\n\n".join(lines)

        # -------------------------------------------------------------
        # 6. ACTION: Multi-Reminder / Sequential Reminders in One Message
        # e.g. "Remind me to drink coffee after 2 minutes \n And to check project at 12:47"
        # -------------------------------------------------------------
        if "remind" in msg_lower:
            # Check if there are multiple reminder clauses joined by newline or 'and'
            clauses = re.split(r"(?:\n+|\s+and\s+(?:to\s+)?(?=check|remind|call|meet|send|email|do|work|take))", clean_msg, flags=re.IGNORECASE)
            scheduled_results = []

            for clause in clauses:
                clause = clause.strip()
                if not clause:
                    continue
                parsed = parse_target_datetime(clause, ctx.timezone_name)
                if parsed:
                    target_dt, raw_title = parsed
                    title = clean_reminder_title(raw_title)
                    res = await handle_create_reminder(ctx, reminder_text=title, remind_at_iso=target_dt.isoformat())
                    time_str = format_iso_to_local(target_dt.isoformat(), ctx.timezone_name)
                    scheduled_results.append((res.get("reminder_id"), title, time_str))

            if scheduled_results:
                if len(scheduled_results) == 1:
                    rid, rtitle, rtime = scheduled_results[0]
                    return (
                        f"🔔 **Reminder Scheduled for you, {user_display}!**\n\n"
                        f"• **What**: {rtitle}\n"
                        f"• **When**: `{rtime}`"
                    )
                else:
                    lines = [f"🔔 **Scheduled {len(scheduled_results)} Reminders for you, {user_display}:**"]
                    for rid, rtitle, rtime in scheduled_results:
                        lines.append(f"• **#{rid}**: {rtitle} — `{rtime}`")
                    return "\n\n".join(lines)

        # -------------------------------------------------------------
        # 7. QUERY: List Reminders
        # e.g. "show active reminders", "reminders list", "my reminders"
        # -------------------------------------------------------------
        is_list_reminders = (
            ("reminder" in msg_lower or "reminders" in msg_lower)
            and any(w in msg_lower for w in ["list", "show", "view", "get", "active", "pending", "my", "what", "check", "display"])
            and not any(neg in msg_lower for neg in ["delete", "remove", "cancel", "clear", "clean", "set", "add", "create"])
        ) or msg_lower in ["reminders", "my reminders", "active reminders", "show reminders", "show active reminders", "show active reminders as list"]

        if is_list_reminders:
            res = await handle_list_reminders(ctx)
            reminders = res.get("reminders", [])
            if not reminders:
                return f"🔔 You have no pending reminders scheduled, {user_display}! Your schedule is clear."
            lines = [f"🔔 **Your Active Reminders** ({len(reminders)}):"]
            for r in reminders:
                t_str = format_iso_to_local(r.get("remind_at", ""), ctx.timezone_name)
                lines.append(f"• **#{r['id']}**: {r['reminder_text']} — `{t_str}`")
            return "\n\n".join(lines)

        # -------------------------------------------------------------
        # 8. ACTION: Complete Task by ID or name
        # e.g. "done 12", "complete task 12", "finished task #12"
        # -------------------------------------------------------------
        comp_m = re.search(r"^(?:mark\s+)?(?:done|complete|finished)\s*(?:task)?\s*#?(\d+)", msg_lower)
        if comp_m:
            t_id = int(comp_m.group(1))
            res = await handle_complete_task(ctx, task_id=t_id)
            if res.get("success"):
                return f"✅ **Awesome work, {user_display}!** Task #{t_id} marked as completed! 🚀"
            return f"⚠️ Task #{t_id} was not found in your list."

        # -------------------------------------------------------------
        # 9. ACTION: Schedule Calendar Event
        # e.g. "Schedule meeting with mentor tomorrow at 4pm"
        # -------------------------------------------------------------
        if any(w in msg_lower for w in ["schedule", "appointment", "event", "calendar", "meeting"]) and any(w in msg_lower for w in ["at", "on", "tomorrow", "friday", "monday"]):
            parsed = parse_target_datetime(clean_msg, ctx.timezone_name)
            if parsed:
                target_dt, raw_title = parsed
                event_title = re.sub(r"^(?:please\s+)?(?:schedule|add|set\s+up)\s+(?:a\s+)?(?:event|meeting|appointment)?\s*(?:for|with|about)?", "", raw_title, flags=re.IGNORECASE).strip(" ,.-") or "Event"
                res = await handle_create_event(ctx, title=event_title, start_time_iso=target_dt.isoformat())
                time_str = format_iso_to_local(target_dt.isoformat(), ctx.timezone_name)
                return (
                    f"📅 **Event Scheduled, {user_display}!**\n\n"
                    f"• **Event**: {event_title}\n"
                    f"• **When**: `{time_str}`"
                )

        # -------------------------------------------------------------
        # 10. QUERY: Calendar & Schedule
        # e.g. "What's on my schedule?", "calendar", "my events"
        # -------------------------------------------------------------
        if any(q in msg_lower for q in ["calendar", "my schedule", "what's on my schedule", "agenda", "upcoming events", "events"]) and not any(w in msg_lower for w in ["add", "schedule", "create"]):
            res = await handle_list_events(ctx, active_only=True)
            events = res.get("events", [])
            if not events:
                return f"📅 Your calendar is open and free, {user_display}! No upcoming events scheduled."
            lines = [f"📅 **Your Upcoming Schedule** ({len(events)}):"]
            for e in events:
                t_str = format_iso_to_local(e.get("start_time", ""), ctx.timezone_name)
                lines.append(f"• **#{e['id']}**: {e['title']} — `{t_str}`")
            return "\n\n".join(lines)

        # -------------------------------------------------------------
        # 11. Conversational Greeting
        # -------------------------------------------------------------
        if msg_lower in ["hi", "hello", "hey", "start", "good morning", "good evening", f"hi {assistant_display.lower()}", f"hello {assistant_display.lower()}"]:
            return (
                f"👋 Hey {user_display}! I'm **{assistant_display}**, your personal assistant.\n\n"
                f"How can I help you right now?\n"
                f"• *\"Add tasks: coding, gym, reading\"*\n"
                f"• *\"Remind me to drink coffee in 2 minutes\"*\n"
                f"• *\"Show today's task list\"*\n"
                f"• *\"What's on my schedule today?\"*"
            )

        return None


nlp_engine = SmartNLPEngine()
