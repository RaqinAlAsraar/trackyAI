"""
LLM Engine for Tracky AI using Google Gemini / Gemma.
Features:
- Primary and backup model fallback handling
- Automatic tool calling and execution loop
- Current time & timezone grounding
- Chat history injection for multi-turn conversational memory
"""

import json
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional
import pytz
with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=FutureWarning)
    import google.generativeai as genai

from core.logger import logger
from core.config import settings
from core.tools import ToolContext, execute_tool_call


def get_system_instruction(user_timezone: str = "UTC") -> str:
    try:
        tz = pytz.timezone(user_timezone)
        current_time_str = datetime.now(tz).strftime("%A, %Y-%m-%d %H:%M:%S %Z (UTC%z)")
    except Exception:
        current_time_str = datetime.utcnow().strftime("%A, %Y-%m-%d %H:%M:%S UTC")

    return f"""You are Tracky, an ultra-helpful, friendly, and reliable personal AI assistant.
You help the user manage their tasks, reminders, schedules, and daily routines through natural conversation.

CURRENT REFERENCE TIME:
{current_time_str}
User's Timezone: {user_timezone}

CORE RESPONSIBILITIES:
1. REMINDERS: When the user says e.g. "I have a test tomorrow, remind me at 4 pm today to study", parse the time accurately relative to the CURRENT REFERENCE TIME, call `create_reminder(reminder_text, remind_at_iso)` with ISO 8601 formatted datetime including offset or UTC, and reply warmly confirming the reminder.
2. TASKS: Track to-do items using `create_task`, `list_tasks`, `complete_task`, and `delete_task`.
3. EVENTS: Schedule appointments or agenda items using `create_event`, `list_events`, and `delete_event`.
4. LISTING & QUERYING: When the user asks "what do I have today?", "show my reminders", or "what's pending?", call the relevant list tools and present a clean, concise, human-readable summary.
5. CONVERSATION: Remember past context from the conversation history. Reply warmly, concisely, and naturally like a smart personal assistant.
6. CLARITY: If the user's requested time is completely ambiguous, politely ask for clarification. Otherwise, deduce the most sensible interpretation and confirm it.
"""


# Function declarations compatible with google.generativeai
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
        self.primary_model_name = settings.gemini.primary_model
        self.backup_model_name = settings.gemini.backup_model
        self.temperature = settings.gemini.temperature
        self.max_tokens = settings.gemini.max_output_tokens

        if self.api_key:
            genai.configure(api_key=self.api_key)
            logger.info("Configured Google Gemini API with configured key.")
        else:
            logger.warning("No Gemini API key configured! Please run setup.sh or update config.json.")

    async def generate_response(
        self,
        ctx: ToolContext,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Processes user message through Gemini with tool calling and automatic backup model fallback.
        """
        # Try primary model first, fallback to backup model if error occurs
        models_to_try = [self.primary_model_name]
        if self.backup_model_name and self.backup_model_name != self.primary_model_name:
            models_to_try.append(self.backup_model_name)

        last_error = None
        for model_name in models_to_try:
            try:
                logger.info(f"Attempting response generation with model '{model_name}'...")
                response_text = await self._call_model(model_name, ctx, user_message, history)
                return response_text
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
        system_instruction = get_system_instruction(ctx.timezone_name)
        tools = [{"function_declarations": get_genai_tools()}]

        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction,
            tools=tools,
            generation_config=genai.types.GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ),
        )

        # Build message history for multi-turn context
        chat_contents = []
        if history:
            for item in history:
                role = "user" if item["role"] == "user" else "model"
                chat_contents.append({"role": role, "parts": [item["content"]]})

        # Append current user prompt
        chat_contents.append({"role": "user", "parts": [user_message]})

        chat = model.start_chat(history=chat_contents[:-1])
        response = await chat.send_message_async(user_message)

        # Handle tool calling loops (up to 5 turns)
        for _ in range(5):
            candidate = response.candidates[0]
            function_calls = []
            for part in candidate.content.parts:
                if fn := getattr(part, "function_call", None):
                    function_calls.append(fn)

            if not function_calls:
                # No more tools called, return the text response
                return response.text or "I've processed your request!"

            # Execute tool calls
            tool_responses = []
            for fn in function_calls:
                fn_name = fn.name
                fn_args = dict(fn.args)
                logger.info(f"Executing LLM tool: {fn_name}({fn_args})")
                result = await execute_tool_call(ctx, fn_name, fn_args)
                logger.info(f"Tool {fn_name} returned: {result}")

                tool_responses.append(
                    genai.types.Part.from_function_response(
                        name=fn_name,
                        response={"result": result},
                    )
                )

            # Send tool responses back to the model
            response = await chat.send_message_async(tool_responses)

        return response.text or "I've handled that for you!"


llm_engine = LLMEngine()
