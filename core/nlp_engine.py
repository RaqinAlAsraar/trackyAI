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


MONTHS_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12
}


def parse_target_datetime(text: str, tz_name: str = "UTC") -> Optional[Tuple[datetime, str]]:
    """
    Parses natural time & date expressions and returns (target_datetime, cleaned_text_without_time).
    Supports:
    - Specific calendar dates: 'on 30 October', '30th Oct', 'October 30'
    - Relative days/weeks: 'after 15 days', 'in 3 days', 'in 2 weeks', 'tomorrow'
    - Clock times: 'at 6:00 a.m. morning', '1:10 p.m.', 'at 12:47', 'at 4 pm'
    - Relative hours/minutes/seconds: 'after 2 minutes', 'in 15 seconds'
    """
    user_tz = get_user_tz(tz_name)
    now = datetime.now(user_tz)
    text_lower = text.lower()
    cleaned = text

    # --- 1. Check for specific calendar dates (e.g. 'on 30 October', 'October 30') ---
    target_date = None
    date_pattern_1 = r"\b(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b"
    date_pattern_2 = r"\b(?:on\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b"

    m1 = re.search(date_pattern_1, text_lower)
    m2 = re.search(date_pattern_2, text_lower) if not m1 else None

    if m1:
        day = int(m1.group(1))
        month = MONTHS_MAP[m1.group(2).lower()]
        year = now.year
        try:
            target_date = datetime(year, month, day, tzinfo=user_tz)
            if target_date.date() < now.date():
                target_date = datetime(year + 1, month, day, tzinfo=user_tz)
        except Exception:
            target_date = None
        cleaned = re.sub(date_pattern_1, "", cleaned, flags=re.IGNORECASE)
    elif m2:
        month = MONTHS_MAP[m2.group(1).lower()]
        day = int(m2.group(2))
        year = now.year
        try:
            target_date = datetime(year, month, day, tzinfo=user_tz)
            if target_date.date() < now.date():
                target_date = datetime(year + 1, month, day, tzinfo=user_tz)
        except Exception:
            target_date = None
        cleaned = re.sub(date_pattern_2, "", cleaned, flags=re.IGNORECASE)

    # --- 2. Check for relative days/weeks (e.g. 'after 15 days', 'in 3 days', 'tomorrow') ---
    if not target_date:
        days_m = re.search(r"\b(?:after|in|for)\s*(\d+)\s*(?:days?|d)\b", text_lower)
        weeks_m = re.search(r"\b(?:after|in|for)\s*(\d+)\s*(?:weeks?|w)\b", text_lower)
        if days_m:
            num_days = int(days_m.group(1))
            target_date = now + timedelta(days=num_days)
            cleaned = re.sub(r"\b(?:after|in|for)\s*" + re.escape(days_m.group(1)) + r"\s*(?:days?|d)\b", "", cleaned, flags=re.IGNORECASE)
        elif weeks_m:
            num_weeks = int(weeks_m.group(1))
            target_date = now + timedelta(days=num_weeks * 7)
            cleaned = re.sub(r"\b(?:after|in|for)\s*" + re.escape(weeks_m.group(1)) + r"\s*(?:weeks?|w)\b", "", cleaned, flags=re.IGNORECASE)
        elif "day after tomorrow" in text_lower:
            target_date = now + timedelta(days=2)
            cleaned = re.sub(r"\bday after tomorrow\b", "", cleaned, flags=re.IGNORECASE)
        elif "tomorrow" in text_lower:
            target_date = now + timedelta(days=1)
            cleaned = re.sub(r"\btomorrow\b", "", cleaned, flags=re.IGNORECASE)

    # --- 3. Check for clock times (e.g. 'at 6:00 a.m. morning', '1:10 p.m.', 'at 12:47', 'at 4 pm') ---
    clock_pattern = r"\b(?:at|for|after)?\s*(\d{1,2}):(\d{2})(?:\s*(a\.?m\.?|p\.?m\.?|am|pm))?(?:\s*(morning|evening|night|afternoon))?\b"
    simple_clock_pattern = r"\b(?:at|for|after)\s*(\d{1,2})(?:\s*(a\.?m\.?|p\.?m\.?|am|pm))(?:\s*(morning|evening|night|afternoon))?\b"

    clock_m = re.search(clock_pattern, cleaned.lower())
    simple_m = re.search(simple_clock_pattern, cleaned.lower()) if not clock_m else None

    if clock_m:
        hour = int(clock_m.group(1))
        minute = int(clock_m.group(2))
        raw_ampm = (clock_m.group(3) or "").replace(".", "").lower()
        modifier = (clock_m.group(4) or "").lower()

        is_am = "am" in raw_ampm or modifier == "morning"
        is_pm = "pm" in raw_ampm or modifier in ["evening", "night", "afternoon"]

        if is_pm and hour < 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
        elif not is_am and not is_pm:
            # Heuristic: if <= 7 and current hour >= 10 on same day, assume PM
            if hour <= 7 and now.hour >= 10 and (not target_date or target_date.date() == now.date()):
                hour += 12

        cleaned = re.sub(clock_pattern, "", cleaned, count=1, flags=re.IGNORECASE)
        base = target_date if target_date else now
        result_dt = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if not target_date and result_dt <= now:
            result_dt += timedelta(days=1)
        return result_dt, cleaned

    elif simple_m:
        hour = int(simple_m.group(1))
        minute = 0
        raw_ampm = (simple_m.group(2) or "").replace(".", "").lower()
        modifier = (simple_m.group(3) or "").lower()

        is_am = "am" in raw_ampm or modifier == "morning"
        is_pm = "pm" in raw_ampm or modifier in ["evening", "night", "afternoon"]

        if is_pm and hour < 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0

        cleaned = re.sub(simple_clock_pattern, "", cleaned, count=1, flags=re.IGNORECASE)
        base = target_date if target_date else now
        result_dt = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if not target_date and result_dt <= now:
            result_dt += timedelta(days=1)
        return result_dt, cleaned

    # If target_date was found without a specific clock time, apply time of day default
    if target_date:
        if "morning" in text_lower:
            target_date = target_date.replace(hour=8, minute=0, second=0, microsecond=0)
        elif "evening" in text_lower:
            target_date = target_date.replace(hour=18, minute=0, second=0, microsecond=0)
        elif "night" in text_lower:
            target_date = target_date.replace(hour=21, minute=0, second=0, microsecond=0)
        elif "afternoon" in text_lower:
            target_date = target_date.replace(hour=14, minute=0, second=0, microsecond=0)
        else:
            target_date = target_date.replace(hour=9, minute=0, second=0, microsecond=0)
        cleaned = re.sub(r"\b(?:morning|evening|night|afternoon|that day)\b", "", cleaned, flags=re.IGNORECASE)
        return target_date, cleaned

    # --- 4. Relative hours / minutes / seconds ---
    sec_m = re.search(r"\b(?:in|after)\s*(\d+)\s*(?:sec|second|seconds|s)\b", text_lower)
    if sec_m:
        secs = int(sec_m.group(1))
        cleaned = re.sub(r"\b(?:in|after)\s*" + re.escape(sec_m.group(1)) + r"\s*(?:sec|second|seconds|s)\b", "", cleaned, flags=re.IGNORECASE)
        return now + timedelta(seconds=secs), cleaned

    min_m = re.search(r"\b(?:in|after)\s*(\d+)\s*(?:min|minute|minutes|m)\b", text_lower)
    if min_m:
        mins = int(min_m.group(1))
        cleaned = re.sub(r"\b(?:in|after)\s*" + re.escape(min_m.group(1)) + r"\s*(?:min|minute|minutes|m)\b", "", cleaned, flags=re.IGNORECASE)
        return now + timedelta(minutes=mins), cleaned

    hr_m = re.search(r"\b(?:in|after)\s*(\d+)\s*(?:hour|hours|hr|hrs|h)\b", text_lower)
    if hr_m:
        hrs = int(hr_m.group(1))
        cleaned = re.sub(r"\b(?:in|after)\s*" + re.escape(hr_m.group(1)) + r"\s*(?:hour|hours|hr|hrs|h)\b", "", cleaned, flags=re.IGNORECASE)
        return now + timedelta(hours=hrs), cleaned

    return None


def clean_reminder_title(raw_text: str) -> str:
    """Strips filler words and command wrappers from reminder text."""
    t = raw_text
    # Remove voice tag
    t = re.sub(r"^\[(?:voice|voice message)\]:\s*", "", t, flags=re.IGNORECASE)
    # Remove assistant callouts
    t = re.sub(r"^(?:hello|hey|hi)\s+[a-z0-9_]+\s*[,:]?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^[a-z0-9_]+\s*[,:]\s*", "", t, flags=re.IGNORECASE)

    # Handle pattern: "I have exam on 30 October. So set a reminder for that day..."
    topic_m = re.search(r"^(?:i\s+have\s+(?:an?\s+)?)(.+?)(?:\s+on\s+|\s+after\s+|\s+in\s+|\s+at\s+|\s*\.\s*|\s+so\s+)", t, flags=re.IGNORECASE)
    if topic_m:
        topic = topic_m.group(1).strip()
        if len(topic) >= 3:
            return topic.capitalize()

    # Handle pattern: "set timer for it at 6:00 pm" or "set timer for exam"
    timer_m = re.search(r"\bset\s+(?:a\s+)?timer\s+(?:for\s+)(.+?)(?:\s+at|\s+for|\s+after|$)", t, flags=re.IGNORECASE)
    if timer_m:
        topic = timer_m.group(1).strip(" .")
        if topic and topic.lower() != "it":
            return topic.capitalize()

    # Remove command prefixes
    t = re.sub(r"^(?:please\s+)?(?:set\s+(?:a\s+)?(?:reminder|timer)(?:\s+(?:to|for))?|remind\s+(?:me)?(?:\s+(?:to|for))?)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bso\s+set\s+(?:a\s+)?(?:reminder|timer)(?:\s+for\s+that\s+day)?\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(?:and\s+)?(?:to\s+)?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:today|tomorrow|tonight|that day|morning|evening|night|afternoon)\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:a\.?m\.?|p\.?m\.?)\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:for\s+\d+\s+days?|after\s+\d+\s+days?)\b", "", t, flags=re.IGNORECASE)
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
        # 2. ACTION: Compound Elimination + New Reminder in One Sentence
        # e.g. "Eliminate the reminder 62, add a new reminder to check the project after 1:15 p.m."
        # -------------------------------------------------------------
        compound_del_add = re.search(
            r"^(?:please\s+)?(?:eliminate|delete|remove|cancel)\s+(?:the\s+)?(?:reminder\s+)?#?(\d+)[,\s]+(?:and\s+)?(?:add|set|create)\s+(?:a\s+)?(?:new\s+)?(?:reminder|timer)\s+(.+)$",
            clean_msg,
            flags=re.IGNORECASE,
        )
        if compound_del_add:
            old_id = int(compound_del_add.group(1))
            new_clause = compound_del_add.group(2)
            await db.delete_reminder(old_id, ctx.user_id)
            parsed = parse_target_datetime(new_clause, ctx.timezone_name)
            if parsed:
                target_dt, raw_title = parsed
                title = clean_reminder_title(raw_title)
                res = await handle_create_reminder(ctx, reminder_text=title, remind_at_iso=target_dt.isoformat())
                time_str = format_iso_to_local(target_dt.isoformat(), ctx.timezone_name)
                new_id = res.get("reminder_id")
                return (
                    f"🗑️ Removed reminder #{old_id}.\n\n"
                    f"🔔 **Reminder Scheduled for you, {user_display}!**\n\n"
                    f"• **#{new_id}**: {title}\n"
                    f"• **When**: `{time_str}`"
                )

        # -------------------------------------------------------------
        # 3. ACTION: Reschedule / Change Existing Reminder Time
        # e.g. "Change time for #62 for today 1:15", "reschedule reminder 62 to 1:15 pm"
        # -------------------------------------------------------------
        resched_m = re.search(
            r"(?:change|update|reschedule|move)(?:\s+the)?\s+(?:time\s+for\s+)?(?:reminder\s+)?#?(\d+)\s*(?:for|to|at)\s*(.+)$",
            clean_msg,
            flags=re.IGNORECASE,
        )
        if resched_m:
            r_id = int(resched_m.group(1))
            time_part = resched_m.group(2)
            parsed = parse_target_datetime(time_part, ctx.timezone_name)
            if parsed:
                target_dt, _ = parsed
                updated = await db.update_reminder_time(r_id, ctx.user_id, target_dt.isoformat())
                if updated:
                    time_str = format_iso_to_local(target_dt.isoformat(), ctx.timezone_name)
                    return f"🕒 **Reminder Rescheduled, {user_display}!**\n\n• **#{r_id}** updated to: `{time_str}`"
                return f"⚠️ Reminder #{r_id} was not found in your schedule."

        # -------------------------------------------------------------
        # 4. ACTION: Multi-ID Deletion (e.g. "Remove 53, 52", "Delete #64", "remove 62")
        # -------------------------------------------------------------
        id_delete_match = re.search(
            r"^(?:please\s+)?(?:delete|remove|cancel|eliminate)\s+(?:the\s+)?(?:reminders?|tasks?|items?)?\s*#?(\d+(?:[\s,]+(?:and\s+)?#?\d+)*)$",
            msg_lower,
        )
        if id_delete_match or (any(w in msg_lower for w in ["remove", "delete", "cancel", "eliminate"]) and re.search(r"\b\d+\b", msg_lower) and len(clean_msg.split()) <= 6):
            raw_ids = [int(n) for n in re.findall(r"\b\d+\b", clean_msg)]
            if raw_ids:
                rem_deleted = await db.delete_reminders_by_ids(raw_ids, ctx.user_id)
                task_deleted = await db.delete_tasks_by_ids(raw_ids, ctx.user_id)
                total = rem_deleted + task_deleted
                if total > 0:
                    id_list_str = ", ".join(f"#{i}" for i in raw_ids)
                    return f"🗑️ Done, {user_display}! Successfully removed {id_list_str} for you."
                return f"⚠️ None of the requested IDs ({', '.join(f'#{i}' for i in raw_ids)}) were found in your active items."

        # -------------------------------------------------------------
        # 5. ACTION: Delete existing task list and create new one
        # e.g. "Delete this and create new tasklist, add exam prep, coding and hacking in it"
        # -------------------------------------------------------------
        if ("delete this" in msg_lower or "clear task" in msg_lower or "replace task" in msg_lower) and any(w in msg_lower for w in ["create", "new", "add"]):
            await db.delete_all_tasks(ctx.user_id, status="pending")
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
        # 6. ACTION: Fuzzy Task Completion by Keyword / Name
        # e.g. "Hacki and coding are done", "namaz is done", "coding is finished"
        # -------------------------------------------------------------
        done_m = re.search(r"^(.*?)\s+(?:are|is)\s+(?:done|finished|completed)$", clean_msg, flags=re.IGNORECASE)
        if done_m and not any(w in msg_lower for w in ["supposed", "why", "when", "how", "what"]):
            raw_kws = done_m.group(1)
            kws = [k.strip() for k in re.split(r"[,;\n]+|\s+and\s+", raw_kws, flags=re.IGNORECASE) if k.strip()]
            if kws:
                completed = await db.complete_tasks_by_keywords(ctx.user_id, kws)
                if completed:
                    lines = [f"✅ **Marked {len(completed)} Task{'s' if len(completed) != 1 else ''} as Completed, {user_display}!** 🎉"]
                    for c in completed:
                        lines.append(f"• **#{c['id']}**: {c['title']}")
                    lines.append("\n*Tip: Say 'Clear completed tasks' anytime to remove them from your list.*")
                    return "\n".join(lines)

        # -------------------------------------------------------------
        # 7. ACTION: Feedback Handling - Remove Completed Tasks
        # e.g. "You were supposed to remove these tasks when they are done", "clear completed tasks"
        # -------------------------------------------------------------
        if any(ph in msg_lower for ph in ["supposed to remove", "clear completed", "remove completed", "delete completed", "clean completed"]):
            cleared = await db.delete_completed_tasks(ctx.user_id)
            if cleared > 0:
                return f"🧹 You're completely right, {user_display}! Cleaned up **{cleared} completed task{'s' if cleared != 1 else ''}** from your list so it stays tidy."
            return f"✨ No completed tasks were pending removal, {user_display}! Your active list is up to date."

        # -------------------------------------------------------------
        # 8. ACTION: Create Task List with Multiple Items
        # e.g. "Create today's task list. Add tennis ball, namaz, and exam study in the tasks."
        # -------------------------------------------------------------
        is_add_or_create_tasks = any(w in msg_lower for w in ["add", "create", "make", "new", "set"]) and any(t in msg_lower for t in ["task", "tasks", "todo", "todos", "tasklist", "task list"])
        if is_add_or_create_tasks and ("add" in msg_lower or ":" in clean_msg or "," in clean_msg):
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
        # 9. QUERY: List Tasks / To-Do
        # e.g. "today's task list", "Any todo list for today?", "show active tasks"
        # -------------------------------------------------------------
        is_list_tasks = (
            any(k in msg_lower for k in ["task", "tasks", "todo", "todos", "tasklist"])
            and not any(neg in msg_lower for neg in ["add", "create", "new", "delete", "cancel", "remove", "finish", "complete", "done"])
        ) or msg_lower in ["today's task list", "todays task list", "tasks", "my tasks", "active tasks", "show tasks", "show active tasks", "any todo list for today?"]

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
        # 10. ACTION: Set Timer / Date Reminder
        # e.g. "I have exam after 15 days, set timer for it at 6:00 p.m. for 15 days."
        # e.g. "I have exam on 30 October. So set a reminder for that day at 6:00 a.m. morning."
        # -------------------------------------------------------------
        if any(w in msg_lower for w in ["remind", "reminder", "timer"]) or ("i have" in msg_lower and any(w in msg_lower for w in ["exam", "meeting", "class", "interview"])):
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
        # 11. QUERY: List Reminders / Timers
        # e.g. "show active reminders", "reminders list", "timers", "active timers"
        # -------------------------------------------------------------
        is_list_reminders = (
            any(w in msg_lower for w in ["reminder", "reminders", "timer", "timers"])
            and any(w in msg_lower for w in ["list", "show", "view", "get", "active", "pending", "my", "what", "check", "display"])
            and not any(neg in msg_lower for neg in ["delete", "remove", "cancel", "clear", "clean", "set", "add", "create"])
        ) or msg_lower in ["reminders", "my reminders", "active reminders", "show reminders", "show active reminders", "timers", "active timers", "show timers"]

        if is_list_reminders:
            res = await handle_list_reminders(ctx)
            reminders = res.get("reminders", [])
            if not reminders:
                noun = "timers or reminders" if "timer" in msg_lower else "reminders"
                return f"🔔 You have no pending {noun} scheduled, {user_display}! Your schedule is clear."
            title_header = "Active Timers & Reminders" if "timer" in msg_lower else "Active Reminders"
            lines = [f"🔔 **Your {title_header}** ({len(reminders)}):"]
            for r in reminders:
                t_str = format_iso_to_local(r.get("remind_at", ""), ctx.timezone_name)
                lines.append(f"• **#{r['id']}**: {r['reminder_text']} — `{t_str}`")
            return "\n\n".join(lines)

        # -------------------------------------------------------------
        # 12. FEEDBACK: Wrong reminder time
        # -------------------------------------------------------------
        if msg_lower in ["wrong reminder time", "wrong time", "wrong reminder", "incorrect time"]:
            return f"⚠️ My apologies, {user_display}! Tell me which reminder to adjust (e.g. *\"Change time for #65 to 6:00 AM on 30 October\"*) and I'll update it right away."

        # -------------------------------------------------------------
        # 13. ACTION: Complete Task by ID
        # e.g. "done 12", "complete task 12", "finished task #12"
        # -------------------------------------------------------------
        comp_m = re.search(r"^(?:mark\s+)?(?:done|complete|finished)\s*(?:task)?\s*#?(\d+)$", msg_lower)
        if comp_m:
            t_id = int(comp_m.group(1))
            res = await handle_complete_task(ctx, task_id=t_id)
            if res.get("success"):
                return f"✅ **Awesome work, {user_display}!** Task #{t_id} marked as completed! 🚀"
            return f"⚠️ Task #{t_id} was not found in your list."

        # -------------------------------------------------------------
        # 14. ACTION: Schedule Calendar Event
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
        # 15. QUERY: Calendar & Schedule
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
        # 16. Conversational Greeting
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
