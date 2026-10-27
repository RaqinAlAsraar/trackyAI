import pytest
import json
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from app import app
from core.config import settings
from db import database as db
from adapters.whatsapp_bot import format_for_whatsapp, whatsapp_adapter


def test_format_for_whatsapp():
    raw = "🔔 **Today's Active Reminders** (2):\n\n• **#1**: Exam — `Tomorrow at 6:00 AM`"
    formatted = format_for_whatsapp(raw)
    assert "**" not in formatted
    assert "*Today's Active Reminders*" in formatted
    assert "*#1*" in formatted


@pytest.mark.asyncio
async def test_whatsapp_web_incoming_tasks():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "sender": "919876543210@s.whatsapp.net",
            "phone": "919876543210",
            "name": "Ali Abbas",
            "text": "Create today's task list: prepare presentation, review code, test whatsapp",
        }
        res = await client.post("/webhook/whatsapp/web", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "ok"
        reply = data.get("reply", "")
        assert "prepare presentation" in reply
        assert "review code" in reply
        assert "test whatsapp" in reply

        # Verify tasks saved to db with platform="whatsapp"
        tasks = await db.get_tasks("919876543210", status="pending")
        assert any("prepare presentation" in t["title"] for t in tasks)
        assert any(t["platform"] == "whatsapp" for t in tasks)


@pytest.mark.asyncio
async def test_whatsapp_web_incoming_reminders_and_reschedule():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create reminder
        p1 = {
            "sender": "919876543210@s.whatsapp.net",
            "phone": "919876543210",
            "name": "Ali Abbas",
            "text": "I have exam on 30 October. So set a reminder for that day at 6:00 a.m. morning.",
        }
        res1 = await client.post("/webhook/whatsapp/web", json=p1)
        assert res1.status_code == 200
        d1 = res1.json()
        assert "Oct 30" in d1.get("reply", "")
        assert "6:00 AM" in d1.get("reply", "")

        # 2. Contextual Reschedule
        p2 = {
            "sender": "919876543210@s.whatsapp.net",
            "phone": "919876543210",
            "name": "Ali Abbas",
            "text": "Change it's Timing to 8 am",
        }
        res2 = await client.post("/webhook/whatsapp/web", json=p2)
        assert res2.status_code == 200
        d2 = res2.json()
        assert "Reminder Rescheduled" in d2.get("reply", "")
        assert "8:00 AM" in d2.get("reply", "")


@pytest.mark.asyncio
async def test_whatsapp_unified_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # JSON payload to root /webhook/whatsapp
        payload = {
            "sender": "919876543210@s.whatsapp.net",
            "phone": "919876543210",
            "name": "Ali Abbas",
            "text": "Show today's tasklist",
        }
        res = await client.post("/webhook/whatsapp", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "ok"
        assert "Today's Active Tasks" in data.get("reply", "")


@pytest.mark.asyncio
async def test_whatsapp_outbound_send_message():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = '{"success": true}'

        whatsapp_adapter.provider = "web_session"
        whatsapp_adapter.bridge_url = "http://127.0.0.1:3001"
        ok = await whatsapp_adapter.send_message("919876543210", "🔔 **Reminder:** Drink water")
        assert ok is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["to"] == "919876543210"
        # Bolding converted to single asterisks for WhatsApp
        assert call_kwargs["json"]["message"] == "🔔 *Reminder:* Drink water"
