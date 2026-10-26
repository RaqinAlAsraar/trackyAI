"""
Tool declarations and executors for Tracky AI.
Provides callable functions for Gemini LLM Function Calling:
- Reminders management
- Tasks / To-Do management
- Events / Calendar management
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from core.logger import logger
import db.database as db


class ToolContext:
    """Carries session context for the currently executing user and platform."""
    def __init__(self, user_id: str, platform: str, chat_id: str, timezone_name: str = "UTC"):
        self.user_id = user_id
        self.platform = platform
        self.chat_id = chat_id
        self.timezone_name = timezone_name


async def handle_create_reminder(
    ctx: ToolContext, reminder_text: str, remind_at_iso: str
) -> Dict[str, Any]:
    """
    Schedules a new reminder for the user at a specified ISO 8601 datetime.
    Example remind_at_iso: '2026-10-27T16:00:00+05:30'
    """
    try:
        reminder_id = await db.add_reminder(
            user_id=ctx.user_id,
            platform=ctx.platform,
            chat_id=ctx.chat_id,
            reminder_text=reminder_text,
            remind_at=remind_at_iso,
        )
        logger.info(f"Created reminder #{reminder_id} for user {ctx.user_id} at {remind_at_iso}")
        return {
            "success": True,
            "reminder_id": reminder_id,
            "reminder_text": reminder_text,
            "remind_at": remind_at_iso,
            "message": f"Reminder #{reminder_id} scheduled for {remind_at_iso}: '{reminder_text}'.",
        }
    except Exception as e:
        logger.error(f"Failed to create reminder: {e}")
        return {"success": False, "error": str(e)}


async def handle_list_reminders(ctx: ToolContext) -> Dict[str, Any]:
    """Lists all active and pending reminders for the current user."""
    try:
        reminders = await db.get_active_reminders(user_id=ctx.user_id)
        return {
            "success": True,
            "count": len(reminders),
            "reminders": reminders,
        }
    except Exception as e:
        logger.error(f"Failed to list reminders: {e}")
        return {"success": False, "error": str(e)}


async def handle_cancel_reminder(ctx: ToolContext, reminder_id: int) -> Dict[str, Any]:
    """Cancels/deletes a pending reminder by ID."""
    try:
        success = await db.delete_reminder(reminder_id=reminder_id, user_id=ctx.user_id)
        return {
            "success": success,
            "reminder_id": reminder_id,
            "message": f"Reminder #{reminder_id} cancelled." if success else "Reminder not found.",
        }
    except Exception as e:
        logger.error(f"Failed to cancel reminder: {e}")
        return {"success": False, "error": str(e)}


async def handle_create_task(
    ctx: ToolContext,
    title: str,
    description: str = "",
    due_date_iso: Optional[str] = None,
    priority: str = "normal",
) -> Dict[str, Any]:
    """
    Creates a new task/to-do item.
    priority can be: 'low', 'normal', or 'high'.
    """
    try:
        task_id = await db.add_task(
            user_id=ctx.user_id,
            platform=ctx.platform,
            title=title,
            description=description,
            due_date=due_date_iso,
            priority=priority,
        )
        logger.info(f"Created task #{task_id} for user {ctx.user_id}")
        return {
            "success": True,
            "task_id": task_id,
            "title": title,
            "priority": priority,
            "due_date": due_date_iso,
            "message": f"Task #{task_id} '{title}' created successfully.",
        }
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        return {"success": False, "error": str(e)}


async def handle_list_tasks(
    ctx: ToolContext, status: Optional[str] = "pending"
) -> Dict[str, Any]:
    """Lists tasks. status can be 'pending', 'completed', or empty for all tasks."""
    try:
        tasks = await db.get_tasks(user_id=ctx.user_id, status=status if status else None)
        return {
            "success": True,
            "count": len(tasks),
            "tasks": tasks,
        }
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        return {"success": False, "error": str(e)}


async def handle_complete_task(ctx: ToolContext, task_id: int) -> Dict[str, Any]:
    """Marks a task as completed."""
    try:
        success = await db.update_task_status(
            task_id=task_id, user_id=ctx.user_id, status="completed"
        )
        return {
            "success": success,
            "task_id": task_id,
            "message": f"Task #{task_id} marked as completed!" if success else "Task not found.",
        }
    except Exception as e:
        logger.error(f"Failed to complete task: {e}")
        return {"success": False, "error": str(e)}


async def handle_delete_task(ctx: ToolContext, task_id: int) -> Dict[str, Any]:
    """Deletes a task by ID."""
    try:
        success = await db.delete_task(task_id=task_id, user_id=ctx.user_id)
        return {
            "success": success,
            "task_id": task_id,
            "message": f"Task #{task_id} deleted." if success else "Task not found.",
        }
    except Exception as e:
        logger.error(f"Failed to delete task: {e}")
        return {"success": False, "error": str(e)}


async def handle_create_event(
    ctx: ToolContext,
    title: str,
    start_time_iso: str,
    end_time_iso: Optional[str] = None,
    location: str = "",
) -> Dict[str, Any]:
    """
    Schedules a calendar event or appointment with start and optional end time.
    """
    try:
        event_id = await db.add_event(
            user_id=ctx.user_id,
            platform=ctx.platform,
            title=title,
            start_time=start_time_iso,
            end_time=end_time_iso,
            location=location,
        )
        logger.info(f"Created event #{event_id} for user {ctx.user_id}")
        return {
            "success": True,
            "event_id": event_id,
            "title": title,
            "start_time": start_time_iso,
            "end_time": end_time_iso,
            "message": f"Event #{event_id} '{title}' scheduled for {start_time_iso}.",
        }
    except Exception as e:
        logger.error(f"Failed to create event: {e}")
        return {"success": False, "error": str(e)}


async def handle_list_events(
    ctx: ToolContext, active_only: bool = True
) -> Dict[str, Any]:
    """Lists scheduled calendar events."""
    try:
        events = await db.get_events(user_id=ctx.user_id, active_only=active_only)
        return {
            "success": True,
            "count": len(events),
            "events": events,
        }
    except Exception as e:
        logger.error(f"Failed to list events: {e}")
        return {"success": False, "error": str(e)}


async def handle_delete_event(ctx: ToolContext, event_id: int) -> Dict[str, Any]:
    """Deletes an event by ID."""
    try:
        success = await db.delete_event(event_id=event_id, user_id=ctx.user_id)
        return {
            "success": success,
            "event_id": event_id,
            "message": f"Event #{event_id} removed." if success else "Event not found.",
        }
    except Exception as e:
        logger.error(f"Failed to delete event: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions metadata for Gemini
AVAILABLE_TOOLS = [
    {
        "name": "create_reminder",
        "description": "Schedule a proactive reminder for the user at an ISO 8601 datetime.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "reminder_text": {"type": "STRING", "description": "What to remind the user about."},
                "remind_at_iso": {"type": "STRING", "description": "ISO 8601 formatted datetime (e.g. 2026-10-27T16:00:00+05:30). Calculate based on current user time."},
            },
            "required": ["reminder_text", "remind_at_iso"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List all active/pending reminders for the user.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel or delete a reminder by its numeric ID.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "reminder_id": {"type": "INTEGER", "description": "ID of reminder to cancel."},
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "create_task",
        "description": "Add a new task or to-do item for the user.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Title or short description of the task."},
                "description": {"type": "STRING", "description": "Extra details (optional)."},
                "due_date_iso": {"type": "STRING", "description": "Optional ISO 8601 due date."},
                "priority": {"type": "STRING", "description": "Priority: low, normal, high."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List user's tasks. Filter by status: 'pending', 'completed', or null for all.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "status": {"type": "STRING", "description": "'pending', 'completed', or empty."},
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task as completed by its ID.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task_id": {"type": "INTEGER", "description": "ID of task to complete."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": "Delete a task by its ID.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task_id": {"type": "INTEGER", "description": "ID of task to delete."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "create_event",
        "description": "Schedule a calendar event, appointment, or schedule entry.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Name or title of the event."},
                "start_time_iso": {"type": "STRING", "description": "ISO 8601 start time."},
                "end_time_iso": {"type": "STRING", "description": "Optional ISO 8601 end time."},
                "location": {"type": "STRING", "description": "Optional location or link."},
            },
            "required": ["title", "start_time_iso"],
        },
    },
    {
        "name": "list_events",
        "description": "List scheduled calendar events.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "active_only": {"type": "BOOLEAN", "description": "Show only upcoming/active events."},
            },
        },
    },
    {
        "name": "delete_event",
        "description": "Remove or cancel an event by its ID.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "event_id": {"type": "INTEGER", "description": "ID of event to delete."},
            },
            "required": ["event_id"],
        },
    },
]


TOOL_ROUTERS = {
    "create_reminder": handle_create_reminder,
    "list_reminders": handle_list_reminders,
    "cancel_reminder": handle_cancel_reminder,
    "create_task": handle_create_task,
    "list_tasks": handle_list_tasks,
    "complete_task": handle_complete_task,
    "delete_task": handle_delete_task,
    "create_event": handle_create_event,
    "list_events": handle_list_events,
    "delete_event": handle_delete_event,
}


async def execute_tool_call(ctx: ToolContext, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    handler = TOOL_ROUTERS.get(tool_name)
    if not handler:
        return {"success": False, "error": f"Unknown tool '{tool_name}'"}
    try:
        return await handler(ctx, **args)
    except Exception as e:
        logger.error(f"Error executing tool {tool_name} with args {args}: {e}")
        return {"success": False, "error": str(e)}
