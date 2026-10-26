"""
Comprehensive test suite for Tracky AI components:
- Database CRUD & lifecycle auto-cleanup
- Memory management & memory.log logging
- Guardrails & rate limiting
- Tools execution
- Background scheduler reminder dispatching
- Voice TTS synthesis
"""

import os
import asyncio
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta

# Ensure settings loads test environment
os.environ["SETTINGS_TEST"] = "1"

import db.database as db
from core.tools import ToolContext, execute_tool_call
from core.memory import memory_manager
from core.guardrails import guardrails
from core.scheduler import scheduler_service, register_dispatcher
from core.voice import voice_processor


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    await db.init_db()
    yield


@pytest.mark.asyncio
async def test_database_tasks_crud():
    user_id = "test_user_123"
    task_id = await db.add_task(
        user_id=user_id,
        platform="telegram",
        title="Study for Hackathon test",
        description="Study neural networks chapter",
        due_date="2026-10-27T16:00:00Z",
        priority="high",
    )
    assert task_id > 0

    tasks = await db.get_tasks(user_id=user_id, status="pending")
    assert any(t["id"] == task_id and t["title"] == "Study for Hackathon test" for t in tasks)

    # Complete task
    updated = await db.update_task_status(task_id, user_id, "completed")
    assert updated is True

    completed_tasks = await db.get_tasks(user_id=user_id, status="completed")
    assert any(t["id"] == task_id for t in completed_tasks)

    # Delete task
    deleted = await db.delete_task(task_id, user_id)
    assert deleted is True


@pytest.mark.asyncio
async def test_database_events_and_cleanup():
    user_id = "test_user_123"
    # Create an expired event in the past
    past_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    past_end = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    event_id = await db.add_event(
        user_id=user_id,
        platform="telegram",
        title="Old Presentation",
        start_time=past_time,
        end_time=past_end,
    )
    assert event_id > 0

    # Run cleanup
    cleaned = await db.cleanup_expired_events()
    assert cleaned >= 1

    events = await db.get_events(user_id=user_id, active_only=True)
    assert not any(e["id"] == event_id for e in events)


@pytest.mark.asyncio
async def test_database_reminders_and_due():
    user_id = "test_user_123"
    past_target = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    rem_id = await db.add_reminder(
        user_id=user_id,
        platform="telegram",
        chat_id="chat_999",
        reminder_text="Time to take a medicine break",
        remind_at=past_target,
    )
    assert rem_id > 0

    now_iso = datetime.now(timezone.utc).isoformat()
    due = await db.get_due_reminders(now_iso)
    assert any(r["id"] == rem_id for r in due)

    # Mark triggered
    assert await db.mark_reminder_triggered(rem_id) is True

    due_after = await db.get_due_reminders(now_iso)
    assert not any(r["id"] == rem_id for r in due_after)


@pytest.mark.asyncio
async def test_tools_execution():
    ctx = ToolContext(
        user_id="user_test_tool",
        platform="telegram",
        chat_id="chat_tool",
        timezone_name="UTC",
    )

    # Test create_reminder tool
    target_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result = await execute_tool_call(
        ctx,
        "create_reminder",
        {"reminder_text": "Submit hackathon project", "remind_at_iso": target_time},
    )
    assert result["success"] is True
    assert "reminder_id" in result

    # Test list_reminders tool
    reminders_list = await execute_tool_call(ctx, "list_reminders", {})
    assert reminders_list["success"] is True
    assert reminders_list["count"] >= 1


@pytest.mark.asyncio
async def test_memory_and_logging():
    user_id = "user_memory_test"
    user_text = "I love hacking on AI projects"
    assistant_reply = "That's awesome! Tracky AI is here to help you stay organized."

    await memory_manager.record_interaction(user_id, "telegram", user_text, assistant_reply)
    history = await memory_manager.get_context_history(user_id)
    assert len(history) >= 2
    assert history[-2]["content"] == user_text
    assert history[-1]["content"] == assistant_reply

    # Verify memory.log was created and written to
    log_path = memory_manager.memory_log_path
    assert os.path.exists(log_path)
    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert user_text in content
        assert assistant_reply in content


def test_guardrails():
    user_id = "test_guardrail_user"
    # Empty message should fail
    allowed, msg = guardrails.validate_message("")
    assert allowed is False

    # Valid message should pass
    allowed, msg = guardrails.validate_message("Hello Tracky!")
    assert allowed is True

    # Check rate limiter: 25 rapid messages should trigger rate limit (limit is 20)
    limit_hit = False
    for _ in range(25):
        ok, err = guardrails.check_rate_limit(user_id)
        if not ok:
            limit_hit = True
            break
    assert limit_hit is True


@pytest.mark.asyncio
async def test_scheduler_dispatch():
    received_messages = []

    async def mock_dispatcher(chat_id: str, message: str):
        received_messages.append({"chat_id": chat_id, "message": message})

    register_dispatcher("mock_platform", mock_dispatcher)

    # Create due reminder
    past_target = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    await db.add_reminder(
        user_id="user_sched",
        platform="mock_platform",
        chat_id="chat_sched_123",
        reminder_text="Important scheduler test alert",
        remind_at=past_target,
    )

    # Manually invoke scheduler check
    await scheduler_service.check_and_dispatch_reminders()
    assert len(received_messages) >= 1
    assert "Important scheduler test alert" in received_messages[0]["message"]


@pytest.mark.asyncio
async def test_voice_tts():
    # Test Edge-TTS voice generation
    output_audio = await voice_processor.text_to_speech("Tracky AI is online and ready!")
    if output_audio is None:
        pytest.skip("External TTS endpoint unreachable in current test environment")
    assert os.path.exists(output_audio)
    assert os.path.getsize(output_audio) > 100
    os.unlink(output_audio)
