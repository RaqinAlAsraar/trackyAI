"""
LLM Engine for Tracky AI using Google GenAI SDK.
Features:
- Cascading model fallback with Gemma 4 and fast Gemini 2.5 Flash
- Disables thinking mode to eliminate latency and useless thinking delay
- Automatic tool calling and execution loop
- Current time & timezone grounding
- Chat history injection for multi-turn conversational memory
"""

import json
import time
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    import pytz
except ImportError:
    pytz = None

from google import genai
from google.genai import types

from core.logger import logger
from core.config import settings
from core.tools import ToolContext, execute_tool_call
from core.local_llm import local_llm_engine, offline_fallback_handler, format_iso_to_local


DEFAULT_MODELS_TO_TRY = [
    "models/gemma-4-26b-a4b-it",
    "models/gemini-3.1-flash-lite",
]


def get_system_instruction(
    user_timezone: str = "UTC",
    user_name: str = "",
    assistant_name: str = "Tracky",
) -> str:
    current_time_str = ""
    try:
        if ZoneInfo:
            tz = ZoneInfo(user_timezone)
            current_time_str = datetime.now(tz).strftime("%A, %Y-%m-%d %H:%M:%S %Z (UTC%z)")
        elif pytz:
            tz = pytz.timezone(user_timezone)
            current_time_str = datetime.now(tz).strftime("%A, %Y-%m-%d %H:%M:%S %Z (UTC%z)")
    except Exception:
        pass

    if not current_time_str:
        current_time_str = datetime.utcnow().strftime("%A, %Y-%m-%d %H:%M:%S UTC")

    display_user = user_name if user_name else "User"

    return f"""You are {assistant_name}, a friendly, intelligent, and highly capable personal AI assistant.
You work exclusively for {display_user}. You know {display_user}'s name and address them warmly by their name when appropriate.

CURRENT REFERENCE TIME:
{current_time_str}
User's Timezone: {user_timezone}

CORE RESPONSIBILITIES:
1. PERSONAL IDENTITY: Your name is {assistant_name}. You assist {display_user}.
2. REMINDERS: When {display_user} asks e.g. "I have a test tomorrow, remind me at 4 pm today to study", parse the target time accurately relative to the CURRENT REFERENCE TIME, call `create_reminder(reminder_text, remind_at_iso)` with ISO 8601 formatted datetime including timezone offset or UTC, and reply warmly confirming the reminder.
3. TASKS: Track to-do items using `create_task`, `list_tasks`, `complete_task`, and `delete_task`.
4. EVENTS: Schedule appointments or agenda items using `create_event`, `list_events`, and `delete_event`.
5. LISTING & QUERYING: When {display_user} asks "what do I have today?", "show my reminders", or "what's pending?", call the relevant list tools and present a clean, concise, human-readable summary.
6. CONVERSATION: Remember past context from the conversation history. Reply warmly, concisely, and naturally like a smart personal assistant.
7. CLARITY: If the requested time is ambiguous, politely ask for clarification. Otherwise, deduce the most sensible interpretation and confirm it.
"""


def get_genai_tools() -> List[Dict[str, Any]]:
    return [
        {
            "name": "create_reminder",
            "description": "Schedule a proactive reminder for the user at an ISO 8601 datetime.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "reminder_text": {"type": "STRING", "description": "What to remind the user about."},
                    "remind_at_iso": {"type": "STRING", "description": "ISO 8601 datetime string (e.g. '2026-10-27T16:00:00+05:30')."},
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
            "description": "List user's tasks. Filter by status: 'pending', 'completed', or empty for all.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "status": {"type": "STRING", "description": "'pending', 'completed', or empty."},
                },
            },
        },
        {
            "name": "complete_task",
            "description": "Mark a task as completed by its numeric ID.",
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
            "description": "Delete a task by its numeric ID.",
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
            "description": "Remove or cancel an event by its numeric ID.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "event_id": {"type": "INTEGER", "description": "ID of event to delete."},
                },
                "required": ["event_id"],
            },
        },
    ]


class LLMEngine:
    def __init__(self):
        self.api_key = settings.gemini.api_key
        self.client: Optional[genai.Client] = None
        self.last_model_used: Optional[str] = None
        self.last_duration: Optional[float] = None
        self.last_tools_called: List[str] = []
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
            logger.info("Initialized Google GenAI Client.")
        else:
            logger.warning("No Gemini API key configured! Please run setup.sh or update config.json.")

    def _get_models_chain(self) -> List[str]:
        chain = []
        # Add configured primary model first if set
        if settings.gemini.primary_model:
            model = settings.gemini.primary_model
            if not model.startswith("models/"):
                model = f"models/{model}"
            chain.append(model)

        # Add default models chain
        for m in DEFAULT_MODELS_TO_TRY:
            if m not in chain:
                chain.append(m)

        # Add configured backup model if set
        if settings.gemini.backup_model:
            bm = settings.gemini.backup_model
            if not bm.startswith("models/"):
                bm = f"models/{bm}"
            if bm not in chain:
                chain.append(bm)

        return chain

    async def generate_response(
        self,
        ctx: ToolContext,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Processes user message through optimized hierarchy:
        1. Cloud Gemma 4 (primary: models/gemma-4-26b-a4b-it)
        2. Immediate Local Ollama Gemma fallback on error (e.g. gemma2:2b)
        3. Cloud Backup (models/gemini-3.1-flash-lite)
        4. Deterministic Offline Rule Engine (zero-downtime)
        """
        start_time = time.time()
        self.last_tools_called = []
        self.last_model_used = None
        self.last_duration = None

        primary_model = settings.gemini.primary_model or "models/gemma-4-26b-a4b-it"
        if not primary_model.startswith("models/"):
            primary_model = f"models/{primary_model}"

        backup_model = settings.gemini.backup_model or "models/gemini-3.1-flash-lite"
        if not backup_model.startswith("models/"):
            backup_model = f"models/{backup_model}"

        # Check smart local NLP engine first for instant, accurate actions
        from core.nlp_engine import nlp_engine
        nlp_res = await nlp_engine.process_user_intent(ctx, user_message)
        if nlp_res:
            self.last_model_used = "nlp:smart_engine"
            self.last_duration = round(time.time() - start_time, 2)
            logger.info("Processed via smart local NLP engine.")
            return nlp_res

        mode = (getattr(settings.app, "llm_mode", "hybrid") or "hybrid").lower()
        if getattr(settings.local_llm, "local_only", False):
            mode = "local_only"

        # =====================================================================
        # 0. LOCAL-ONLY MODE: Never call Cloud APIs (fast local testing, 0 quota)
        # =====================================================================
        if mode in ("local", "local_only", "offline"):
            logger.info("Local-Only LLM mode active. Skipping cloud APIs completely...")
            if settings.local_llm.enabled:
                try:
                    if await local_llm_engine.is_available():
                        logger.info(f"Generating response with local model '{settings.local_llm.model}'...")
                        local_response = await local_llm_engine.generate_response(ctx, user_message, history)
                        if local_response:
                            self.last_model_used = f"local:{settings.local_llm.model}"
                            self.last_duration = round(time.time() - start_time, 2)
                            return local_response
                    else:
                        logger.warning("Local-Only mode active, but Ollama server is not running!")
                except Exception as e:
                    logger.warning(f"Local LLM failed in local_only mode: {type(e).__name__}: {e}")

            # Deterministic Offline Rule Engine (SQLite operations)
            fallback_response = await offline_fallback_handler(ctx, user_message)
            self.last_model_used = "offline:rule_engine"
            self.last_duration = round(time.time() - start_time, 2)
            return fallback_response

        # =====================================================================
        # 1. HYBRID / CLOUD PRIMARY: Cloud Gemma 4
        # =====================================================================
        if self.client:
            try:
                logger.info(f"Attempting response generation with primary model '{primary_model}'...")
                response_text = await asyncio.wait_for(
                    self._call_model(primary_model, ctx, user_message, history),
                    timeout=18.0,
                )
                self.last_model_used = primary_model
                self.last_duration = round(time.time() - start_time, 2)
                return response_text
            except Exception as e:
                logger.warning(
                    f"Primary model '{primary_model}' failed or timed out: {type(e).__name__}: {e}. "
                    f"Switching immediately to local Ollama fallback..."
                )

        # 2. Immediate Local Ollama Gemma Fallback
        if mode != "cloud_only" and settings.local_llm.enabled and settings.local_llm.fallback_on_error:
            try:
                if await local_llm_engine.is_available():
                    logger.info(f"Attempting immediate Local Gemma LLM fallback with '{settings.local_llm.model}'...")
                    local_response = await local_llm_engine.generate_response(ctx, user_message, history)
                    if local_response:
                        self.last_model_used = f"local:{settings.local_llm.model}"
                        self.last_duration = round(time.time() - start_time, 2)
                        return local_response
                else:
                    logger.info("Local Ollama server is not running (circuit breaker checked in <0.6s).")
            except Exception as e:
                logger.warning(f"Local LLM fallback failed: {type(e).__name__}: {e}")

        # 3. Secondary Cloud Backup Model (e.g. gemini-3.1-flash-lite)
        if self.client and backup_model != primary_model:
            try:
                logger.info(f"Attempting cloud backup model '{backup_model}'...")
                response_text = await asyncio.wait_for(
                    self._call_model(backup_model, ctx, user_message, history),
                    timeout=10.0,
                )
                self.last_model_used = backup_model
                self.last_duration = round(time.time() - start_time, 2)
                return response_text
            except Exception as e:
                logger.warning(f"Backup cloud model '{backup_model}' failed: {type(e).__name__}: {e}")

        # 4. Deterministic Offline Fallback Handler (tasks, reminders, calendar via SQLite)
        try:
            logger.info("Activating intelligent offline fallback handler...")
            fallback_response = await offline_fallback_handler(ctx, user_message)
            self.last_model_used = "offline:rule_engine"
            self.last_duration = round(time.time() - start_time, 2)
            return fallback_response
        except Exception as e:
            logger.error(f"Offline fallback handler encountered an error: {e}")

        self.last_duration = round(time.time() - start_time, 2)
        return (
            "⚠️ I'm having trouble connecting to AI services right now. "
            "Please check your internet connection or run 'ollama run gemma2:2b' for offline AI."
        )

    async def _call_model(
        self,
        model_name: str,
        ctx: ToolContext,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        system_instruction = get_system_instruction(
            user_timezone=ctx.timezone_name,
            user_name=ctx.user_name or settings.app.user_name,
            assistant_name=ctx.assistant_name or settings.app.assistant_name,
        )

        cfg_kwargs: Dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": settings.gemini.temperature,
            "max_output_tokens": settings.gemini.max_output_tokens,
            "tools": [{"function_declarations": get_genai_tools()}],
        }

        # Avoid thinking mode on Gemini models to eliminate latency
        if "gemini" in model_name.lower():
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

        # Prepare chat history
        initial_history = []
        if history:
            for item in history[-10:]:
                role = "user" if item["role"] == "user" else "model"
                initial_history.append(types.Content(role=role, parts=[types.Part.from_text(text=item["content"])]))

        chat = self.client.aio.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(**cfg_kwargs),
            history=initial_history,
        )

        step_timeout = 15.0 if "gemma" in model_name.lower() else 8.0
        response = await asyncio.wait_for(chat.send_message(user_message), timeout=step_timeout)

        tool_confirmations: List[str] = []

        # Handle tool calling loops (up to 5 turns)
        for _ in range(5):
            function_calls = response.function_calls
            if not function_calls:
                return response.text or "I've handled that for you!"

            # Execute all returned tool calls
            tool_responses = []
            for fn in function_calls:
                fn_name = fn.name
                fn_args = dict(fn.args)
                if fn_name not in self.last_tools_called:
                    self.last_tools_called.append(fn_name)
                logger.info(f"Executing LLM tool: {fn_name}({fn_args})")
                result = await execute_tool_call(ctx, fn_name, fn_args)
                logger.info(f"Tool {fn_name} returned: {result}")

                # Format human confirmation message (including listings)
                summary = format_tool_result_summary(fn_name, result, ctx.timezone_name, ctx.user_name or settings.app.user_name)
                tool_confirmations.append(summary)

                tool_responses.append(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": result},
                    )
                )

            # Send tool execution results back to LLM for final natural phrasing
            try:
                step2_timeout = 14.0 if "gemma" in model_name.lower() else 8.0
                response = await asyncio.wait_for(chat.send_message(tool_responses), timeout=step2_timeout)
            except Exception as e:
                logger.warning(f"Failed to get follow-up confirmation from '{model_name}' after tool execution: {type(e).__name__}: {e}")
                # Tools already completed in DB; return rich formatted tool summary directly
                if tool_confirmations:
                    return "\n\n".join(tool_confirmations)
                return "✅ Request processed successfully."

        final_text = response.text.strip() if response.text else ""
        listing_tools = {"list_reminders", "list_tasks", "list_events"}
        if any(t in self.last_tools_called for t in listing_tools):
            # If the model didn't actually list the items (e.g. gave a generic acknowledgment without items)
            if not any(marker in final_text for marker in ["#", "•", "-", "*", "1.", "2."]):
                return "\n\n".join(tool_confirmations)

        return final_text or ("\n\n".join(tool_confirmations) if tool_confirmations else "I've handled that for you!")


def format_tool_result_summary(fn_name: str, result: Any, tz_name: str = "UTC", user_name: str = "") -> str:
    """Formats raw tool results into clean, beautiful human-readable text."""
    user_disp = user_name if user_name else "Friend"
    if not isinstance(result, dict):
        return str(result)

    if fn_name == "list_reminders":
        reminders = result.get("reminders", [])
        if not reminders:
            return f"🔔 You have no pending reminders right now, {user_disp}!"
        lines = [f"🔔 **Your Active Reminders** ({len(reminders)}):"]
        for r in reminders:
            t_str = format_iso_to_local(r.get("remind_at", ""), tz_name)
            lines.append(f"• **#{r['id']}**: {r['reminder_text']} — `{t_str}`")
        return "\n\n".join(lines)

    if fn_name == "list_tasks":
        tasks = result.get("tasks", [])
        if not tasks:
            return f"📋 You have no pending tasks right now, {user_disp}! Great job! 🎉"
        lines = [f"📋 **Your Active Tasks** ({len(tasks)}):"]
        for t in tasks:
            prio = f" [{t['priority'].upper()}]" if t.get("priority") else ""
            lines.append(f"• **#{t['id']}**: {t['title']}{prio}")
        return "\n\n".join(lines)

    if fn_name == "list_events":
        events = result.get("events", [])
        if not events:
            return f"📅 Your calendar is clear, {user_disp}! No upcoming events scheduled."
        lines = [f"📅 **Your Upcoming Events** ({len(events)}):"]
        for e in events:
            t_str = format_iso_to_local(e.get("start_time", ""), tz_name)
            lines.append(f"• **#{e['id']}**: {e['title']} — `{t_str}`")
        return "\n\n".join(lines)

    if result.get("message"):
        return result["message"]

    return "✅ Request processed successfully."


llm_engine = LLMEngine()
