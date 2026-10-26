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


DEFAULT_MODELS_TO_TRY = [
    "models/gemini-3-flash-preview",  # Lightning fast (1.8s) with thinking_budget=0 and full tool calling
    "models/gemini-3.6-flash",        # Ultra-fast (1.5s) robust backup
    "models/gemini-3.5-flash",        # Secondary backup
    "models/gemma-4-26b-a4b-it",
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
        Processes user message through cascading model fallback with zero thinking delay.
        """
        if not self.client:
            return "Gemini API key is not configured. Please run ./setup.sh to set up your key."

        models_to_try = self._get_models_chain()
        last_error = None

        for model_name in models_to_try:
            try:
                logger.info(f"Attempting response generation with model '{model_name}'...")
                response_text = await asyncio.wait_for(
                    self._call_model(model_name, ctx, user_message, history),
                    timeout=5.0,
                )
                return response_text
            except asyncio.TimeoutError:
                last_error = f"Model '{model_name}' timed out after 5.0 seconds"
                logger.warning(f"{last_error}. Switching immediately to fallback...")
            except Exception as e:
                last_error = e
                logger.warning(f"Model '{model_name}' failed with error: {e}. Switching to fallback...")

        logger.error(f"All models failed. Last error: {last_error}")
        return f"I ran into an issue connecting to my AI brain. Error: {last_error}"

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
        }

        # Avoid thinking mode to eliminate latency and delays on models that support it
        if "gemini" in model_name.lower():
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            cfg_kwargs["tools"] = [{"function_declarations": get_genai_tools()}]

        # Prepare chat history
        initial_history = []
        if history:
            for item in history:
                role = "user" if item["role"] == "user" else "model"
                initial_history.append(types.Content(role=role, parts=[types.Part.from_text(text=item["content"])]))

        chat = self.client.aio.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(**cfg_kwargs),
            history=initial_history,
        )

        response = await chat.send_message(user_message)

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
                logger.info(f"Executing LLM tool: {fn_name}({fn_args})")
                result = await execute_tool_call(ctx, fn_name, fn_args)
                logger.info(f"Tool {fn_name} returned: {result}")

                tool_responses.append(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": result},
                    )
                )

            # Send tool execution results back to LLM
            response = await chat.send_message(tool_responses)

        return response.text or "I've handled that for you!"


llm_engine = LLMEngine()
