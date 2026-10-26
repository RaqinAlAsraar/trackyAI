"""
WhatsApp Adapter for Tracky AI.
Supports:
- Twilio WhatsApp Sandbox / Production API
- Webhook endpoints for receiving incoming WhatsApp text
- Proactive reminder alerts via WhatsApp
"""

import httpx
from typing import Optional
from fastapi import APIRouter, Request, Form, Response

from core.logger import logger
from core.config import settings
from core.tools import ToolContext
from core.llm import llm_engine
from core.memory import memory_manager
from core.guardrails import guardrails
from core.scheduler import register_dispatcher
from adapters.base import BaseMessenger

whatsapp_router = APIRouter(prefix="/webhook/whatsapp", tags=["WhatsApp"])


class WhatsAppAdapter(BaseMessenger):
    def __init__(self):
        self.enabled = settings.whatsapp.enabled
        self.provider = settings.whatsapp.provider
        self.account_sid = settings.whatsapp.twilio_account_sid
        self.auth_token = settings.whatsapp.twilio_auth_token
        self.from_phone = settings.whatsapp.twilio_phone_number

    async def start(self) -> None:
        if not self.enabled:
            logger.info("WhatsApp adapter is disabled in configuration.")
            return

        logger.info(f"WhatsApp adapter enabled using provider='{self.provider}'")
        register_dispatcher("whatsapp", self.send_message)

    async def stop(self) -> None:
        logger.info("WhatsApp adapter stopped.")

    async def send_message(self, recipient_id: str, text: str) -> bool:
        """
        Sends outbound WhatsApp message.
        recipient_id: e.g. 'whatsapp:+1234567890' or '+1234567890'
        """
        if not recipient_id.startswith("whatsapp:"):
            recipient_id = f"whatsapp:{recipient_id}"

        if not self.account_sid or not self.auth_token:
            logger.error("Cannot send WhatsApp message: Twilio credentials missing.")
            return False

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {
            "From": self.from_phone,
            "To": recipient_id,
            "Body": text,
        }

        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    url, data=data, auth=(self.account_sid, self.auth_token), timeout=10.0
                )
                if res.status_code in (200, 201):
                    logger.info(f"Dispatched WhatsApp message to {recipient_id}")
                    return True
                else:
                    logger.error(f"Twilio error ({res.status_code}): {res.text}")
                    return False
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message: {e}")
            return False


whatsapp_adapter = WhatsAppAdapter()


@whatsapp_router.post("")
async def receive_twilio_whatsapp(
    From: str = Form(...),
    Body: str = Form(...),
    ProfileName: Optional[str] = Form(None),
):
    """
    Twilio WhatsApp Webhook endpoint.
    Receives incoming WhatsApp messages from Twilio.
    """
    user_id = From.replace("whatsapp:", "")
    user_text = Body.strip()

    logger.info(f"Received WhatsApp message from {From} ({ProfileName}): '{user_text}'")

    allowed, error_msg = guardrails.check_all(user_id, "whatsapp", user_text)
    if not allowed:
        # Return TwiML response with warning
        twiml = f"<Response><Message>{error_msg}</Message></Response>"
        return Response(content=twiml, media_type="application/xml")

    user_name = ProfileName or settings.app.user_name or "Friend"
    ctx = ToolContext(
        user_id=user_id,
        platform="whatsapp",
        chat_id=From,
        timezone_name=settings.app.timezone,
        user_name=user_name,
        assistant_name=settings.app.assistant_name,
    )

    history = await memory_manager.get_context_history(user_id)
    reply = await llm_engine.generate_response(ctx, user_text, history)
    await memory_manager.record_interaction(user_id, "whatsapp", user_text, reply)

    # Return reply in Twilio TwiML format
    twiml = f"<Response><Message>{reply}</Message></Response>"
    return Response(content=twiml, media_type="application/xml")


@whatsapp_router.get("")
async def verify_meta_webhook(request: Request):
    """Meta WhatsApp Cloud API verification challenge."""
    hub_mode = request.query_params.get("hub.mode")
    hub_token = request.query_params.get("hub.verify_token")
    hub_challenge = request.query_params.get("hub.challenge")

    if hub_mode == "subscribe" and hub_token == settings.whatsapp.meta_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)
