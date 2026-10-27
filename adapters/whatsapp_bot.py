"""
WhatsApp Adapter for Tracky AI.
Supports:
- WhatsApp Web Multi-Device Session (via local Baileys bridge)
- Twilio WhatsApp Sandbox / Production API
- Meta WhatsApp Cloud API
- Webhook endpoints for receiving incoming WhatsApp text
- Proactive reminder alerts via WhatsApp
"""

import os
import re
import httpx
import subprocess
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import JSONResponse

from core.logger import logger
from core.config import settings
from core.tools import ToolContext
from core.llm import llm_engine
from core.memory import memory_manager
from core.guardrails import guardrails
from core.scheduler import register_dispatcher
from adapters.base import BaseMessenger

whatsapp_router = APIRouter(prefix="/webhook/whatsapp", tags=["WhatsApp"])


def format_for_whatsapp(text: str) -> str:
    """
    Converts markdown formatting from Telegram/standard markdown style
    to WhatsApp-native formatting:
    - **bold** -> *bold*
    - ### Header -> *Header*
    """
    if not text:
        return ""
    # Headers
    formatted = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    # Double asterisks to single asterisk for bold
    formatted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", formatted)
    # Clean up bullet list spacing
    formatted = re.sub(r"^[•*]\s*", "• ", formatted, flags=re.MULTILINE)
    return formatted


class WhatsAppAdapter(BaseMessenger):
    def __init__(self):
        self.enabled = settings.whatsapp.enabled
        self.provider = settings.whatsapp.provider
        self.account_sid = settings.whatsapp.twilio_account_sid
        self.auth_token = settings.whatsapp.twilio_auth_token
        self.from_phone = settings.whatsapp.twilio_phone_number
        self.bridge_url = getattr(settings.whatsapp, "web_session_url", "http://127.0.0.1:3001").rstrip("/")
        self.bridge_process: Optional[subprocess.Popen] = None

    async def start(self) -> None:
        if not self.enabled:
            logger.info("WhatsApp adapter is disabled in configuration.")
            return

        logger.info(f"WhatsApp adapter enabled using provider='{self.provider}'")
        register_dispatcher("whatsapp", self.send_message)

        if self.provider in ["web_session", "whatsapp_web"]:
            logger.info(f"WhatsApp Web Session mode active. Bridge target: {self.bridge_url}")
            # Check if bridge is already running
            bridge_running = False
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    res = await client.get(f"{self.bridge_url}/status")
                    if res.status_code == 200:
                        bridge_running = True
                        data = res.json()
                        logger.info(f"WhatsApp Web Bridge is online (status: {data.get('status')}).")
            except Exception:
                pass

            if not bridge_running:
                logger.info("💡 To connect your WhatsApp, start the bridge in a terminal: bash whatsapp_bridge/start.sh")
                logger.info("   Scan the QR code with WhatsApp -> Linked Devices -> Link a Device.")
                if getattr(settings.whatsapp, "web_session_auto_start", False):
                    bridge_dir = os.path.join(os.path.dirname(__file__), "..", "whatsapp_bridge")
                    bridge_script = os.path.join(bridge_dir, "bridge.js")
                    node_modules = os.path.join(bridge_dir, "node_modules")

                    if os.path.exists(bridge_script) and os.path.exists(node_modules):
                        try:
                            log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
                            os.makedirs(log_dir, exist_ok=True)
                            log_file = open(os.path.join(log_dir, "whatsapp_bridge.log"), "a", encoding="utf-8")
                            self.bridge_process = subprocess.Popen(
                                ["node", "bridge.js"],
                                cwd=bridge_dir,
                                stdout=log_file,
                                stderr=log_file,
                            )
                            logger.info(f"WhatsApp Web Bridge auto-started. View QR at: {self.bridge_url}/qr")
                        except Exception as e:
                            logger.warning(f"Could not auto-start WhatsApp Web Bridge process: {e}")

    async def stop(self) -> None:
        if self.bridge_process:
            logger.info("Stopping WhatsApp Web Session Bridge process...")
            try:
                self.bridge_process.terminate()
                self.bridge_process.wait(timeout=3)
            except Exception:
                self.bridge_process.kill()
            self.bridge_process = None
        logger.info("WhatsApp adapter stopped.")

    async def send_message(self, recipient_id: str, text: str) -> bool:
        """
        Sends outbound WhatsApp message (proactive reminders or alerts).
        recipient_id: e.g. 'whatsapp:+1234567890', '+1234567890', or '1234567890@s.whatsapp.net'
        """
        formatted_text = format_for_whatsapp(text)

        # -------------------------------------------------------------
        # 1. WhatsApp Web Session Provider (Baileys / Local Bridge)
        # -------------------------------------------------------------
        if self.provider in ["web_session", "whatsapp_web"]:
            target = recipient_id.replace("whatsapp:", "").strip()
            url = f"{self.bridge_url}/send"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(url, json={"to": target, "message": formatted_text})
                    if res.status_code == 200:
                        logger.info(f"Dispatched WhatsApp Web message to {target}")
                        return True
                    else:
                        logger.error(f"WhatsApp Web Bridge send failed ({res.status_code}): {res.text}")
                        return False
            except Exception as e:
                logger.error(f"Failed to send WhatsApp Web message via bridge: {e}")
                return False

        # -------------------------------------------------------------
        # 2. Twilio WhatsApp Provider
        # -------------------------------------------------------------
        if not recipient_id.startswith("whatsapp:"):
            recipient_id = f"whatsapp:{recipient_id}"

        if not self.account_sid or not self.auth_token:
            logger.error("Cannot send WhatsApp message: Twilio credentials missing.")
            return False

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {
            "From": self.from_phone,
            "To": recipient_id,
            "Body": formatted_text,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    url, data=data, auth=(self.account_sid, self.auth_token)
                )
                if res.status_code in (200, 201):
                    logger.info(f"Dispatched Twilio WhatsApp message to {recipient_id}")
                    return True
                else:
                    logger.error(f"Twilio error ({res.status_code}): {res.text}")
                    return False
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message: {e}")
            return False


whatsapp_adapter = WhatsAppAdapter()


async def process_whatsapp_incoming(user_id: str, chat_id: str, user_name: str, user_text: str) -> str:
    """Unified handler for incoming WhatsApp messages across all providers."""
    allowed, error_msg = guardrails.check_all(user_id, "whatsapp", user_text)
    if not allowed:
        return format_for_whatsapp(error_msg)

    ctx = ToolContext(
        user_id=user_id,
        platform="whatsapp",
        chat_id=chat_id,
        timezone_name=settings.app.timezone,
        user_name=user_name,
        assistant_name=settings.app.assistant_name,
    )

    history = await memory_manager.get_context_history(user_id)
    reply = await llm_engine.generate_response(ctx, user_text, history)
    await memory_manager.record_interaction(
        user_id=user_id,
        platform="whatsapp",
        user_text=user_text,
        assistant_reply=reply,
        duration=llm_engine.last_duration,
        model_name=llm_engine.last_model_used,
        tools_called=llm_engine.last_tools_called,
    )
    return format_for_whatsapp(reply)


# -------------------------------------------------------------
# Webhook Endpoint: Dedicated Web Session Bridge (/web)
# -------------------------------------------------------------
@whatsapp_router.post("/web")
async def receive_web_session_whatsapp(request: Request):
    """
    Receives incoming WhatsApp messages from local WhatsApp Web Session Bridge.
    Payload: {"sender": "...", "phone": "...", "name": "...", "text": "..."}
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON payload"})

    sender = data.get("sender", "")
    phone = data.get("phone", "")
    name = data.get("name") or settings.app.user_name or "Friend"
    text = (data.get("text") or "").strip()

    if not text:
        return JSONResponse(content={"status": "ignored", "reason": "Empty message"})

    user_id = phone or sender.replace("@s.whatsapp.net", "").replace("@c.us", "")
    chat_id = sender or f"{user_id}@s.whatsapp.net"

    logger.info(f"Received WhatsApp Web message from {name} (+{user_id}): '{text}'")

    reply = await process_whatsapp_incoming(
        user_id=user_id,
        chat_id=chat_id,
        user_name=name,
        user_text=text,
    )

    return JSONResponse(content={"status": "ok", "reply": reply})


# -------------------------------------------------------------
# Webhook Endpoint: Unified / Dual-mode (/webhook/whatsapp)
# -------------------------------------------------------------
@whatsapp_router.post("")
async def receive_unified_whatsapp(request: Request):
    """
    Unified endpoint that automatically detects whether the incoming request is:
    1. JSON from WhatsApp Web Session Bridge, OR
    2. Form-encoded from Twilio WhatsApp Webhook.
    """
    content_type = request.headers.get("content-type", "").lower()

    # JSON -> Web Session Bridge
    if "application/json" in content_type:
        return await receive_web_session_whatsapp(request)

    # Form Data -> Twilio
    form_data = await request.form()
    from_num = form_data.get("From", "")
    body = (form_data.get("Body") or "").strip()
    profile_name = form_data.get("ProfileName")

    user_id = from_num.replace("whatsapp:", "")
    user_name = profile_name or settings.app.user_name or "Friend"

    logger.info(f"Received Twilio WhatsApp message from {from_num} ({profile_name}): '{body}'")

    reply = await process_whatsapp_incoming(
        user_id=user_id,
        chat_id=from_num,
        user_name=user_name,
        user_text=body,
    )

    twiml = f"<Response><Message>{reply}</Message></Response>"
    return Response(content=twiml, media_type="application/xml")


# -------------------------------------------------------------
# Status & Meta Endpoints
# -------------------------------------------------------------
@whatsapp_router.get("/status")
async def get_whatsapp_status():
    """Returns the current status of the WhatsApp adapter and Web Session Bridge."""
    status_info: Dict[str, Any] = {
        "enabled": settings.whatsapp.enabled,
        "provider": settings.whatsapp.provider,
        "web_session_url": getattr(settings.whatsapp, "web_session_url", "http://127.0.0.1:3001"),
        "bridge_online": False,
        "bridge_status": "disconnected",
    }

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{status_info['web_session_url']}/status")
            if res.status_code == 200:
                bridge_data = res.json()
                status_info["bridge_online"] = True
                status_info["bridge_status"] = bridge_data.get("status", "unknown")
                status_info["user"] = bridge_data.get("user")
    except Exception as e:
        status_info["error"] = str(e)

    return JSONResponse(content=status_info)


@whatsapp_router.get("")
async def verify_meta_webhook(request: Request):
    """Meta WhatsApp Cloud API verification challenge."""
    hub_mode = request.query_params.get("hub.mode")
    hub_token = request.query_params.get("hub.verify_token")
    hub_challenge = request.query_params.get("hub.challenge")

    if hub_mode == "subscribe" and hub_token == settings.whatsapp.meta_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)
