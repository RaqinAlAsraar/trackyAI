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
    await asyncio.sleep(0.05)
    assert len(received_messages) >= 1
    assert "Important scheduler test alert" in received_messages[0]["message"]


@pytest.mark.asyncio
async def test_voice_tts_disabled():
    # Verify TTS is disabled and Tracky responds in text only
    output_audio = await voice_processor.text_to_speech("Tracky AI is online and ready!")
    assert output_audio is None


@pytest.mark.asyncio
async def test_local_llm_and_offline_fallback():
    from core.local_llm import local_llm_engine, offline_fallback_handler
    from core.llm import llm_engine

    ctx = ToolContext(
        user_id="test_offline_user",
        platform="telegram",
        chat_id="12345",
        timezone_name="UTC",
        user_name="OfflineTester",
        assistant_name="Tracky",
    )

    # 1. Test offline reminder creation
    reply_reminder = await offline_fallback_handler(ctx, "remind me in 15 minutes to take a break")
    assert "Reminder Scheduled" in reply_reminder
    assert "take a break" in reply_reminder

    # Verify reminder exists in database
    reminders = await db.get_active_reminders("test_offline_user")
    assert any("take a break" in r["reminder_text"] for r in reminders)

    # 2. Test offline task creation
    reply_task = await offline_fallback_handler(ctx, "add task: study offline backup")
    assert "Task Created" in reply_task
    assert "study offline backup" in reply_task

    # 3. Test offline task listing
    reply_list = await offline_fallback_handler(ctx, "list my tasks")
    assert "study offline backup" in reply_list

    # 4. Test offline help
    reply_help = await offline_fallback_handler(ctx, "who are you")
    assert "Offline Mode" in reply_help

    # 5. Test local_llm_engine availability check (does not raise exception)
    is_avail = await local_llm_engine.is_available()
    assert isinstance(is_avail, bool)


@pytest.mark.asyncio
async def test_llm_engine_cascade_and_metrics():
    from core.llm import llm_engine

    ctx = ToolContext(
        user_id="test_cascade_user",
        platform="telegram",
        chat_id="55555",
        timezone_name="UTC",
        user_name="CascadeTester",
        assistant_name="Tracky",
    )

    # Calling generate_response in offline/test environment should seamlessly produce a response
    reply = await llm_engine.generate_response(ctx, "remind me in 30 minutes to drink water")
    assert reply is not None
    assert len(reply) > 5
    assert llm_engine.last_duration is not None
    assert llm_engine.last_model_used is not None


@pytest.mark.asyncio
async def test_llm_engine_local_only_mode():
    from core.llm import llm_engine
    from core.config import settings

    ctx = ToolContext(
        user_id="test_local_mode_user",
        platform="telegram",
        chat_id="77777",
        timezone_name="UTC",
        user_name="LocalTester",
        assistant_name="Tracky",
    )

    original_mode = settings.app.llm_mode
    try:
        settings.app.llm_mode = "local_only"
        reply = await llm_engine.generate_response(ctx, "show active reminders")
        assert reply is not None
        assert "Active Reminders" in reply or "pending reminders" in reply
        # Verify it did not attempt cloud models
        assert any(llm_engine.last_model_used.startswith(p) for p in ["local:", "offline:", "nlp:"])
    finally:
        settings.app.llm_mode = original_mode


@pytest.mark.asyncio
async def test_smart_nlp_engine_multi_actions():
    from core.nlp_engine import nlp_engine

    ctx = ToolContext(
        user_id="test_nlp_user_999",
        platform="telegram",
        chat_id="99999",
        timezone_name="Asia/Kolkata",
        user_name="Test User",
        assistant_name="Angel",
    )

    # 1. Multi-task addition
    r1 = await nlp_engine.process_user_intent(ctx, "Create today's task list. Add tennis ball, namaz, and exam study in the tasks.")
    assert r1 is not None
    assert "Added 3 Tasks" in r1
    assert "tennis ball" in r1
    assert "namaz" in r1
    assert "exam study" in r1

    # 2. Query active tasks
    r2 = await nlp_engine.process_user_intent(ctx, "Today's task list")
    assert r2 is not None
    assert "Active Tasks" in r2

    # 3. Replace task list
    r3 = await nlp_engine.process_user_intent(ctx, "Delete this and create new tasklist, add exam prep, coding and hacking in it")
    assert r3 is not None
    assert "Task List Updated" in r3
    assert "exam prep" in r3
    assert "coding" in r3
    assert "hacking" in r3

    # 4. Multi-reminder creation
    r4 = await nlp_engine.process_user_intent(ctx, "Remind me to drink coffee after 2 minutes \n And to check project at 12:47")
    assert r4 is not None
    assert "Scheduled 2 Reminders" in r4 or "Reminder Scheduled" in r4
    assert "drink coffee" in r4
    assert "check project" in r4

    # 5. Clean inactive reminders
    r5 = await nlp_engine.process_user_intent(ctx, "Remove the inactive reminders now")
    assert r5 is not None
    assert "inactive reminder" in r5 or "tidy" in r5

