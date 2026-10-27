import pytest
import asyncio
from core.tools import ToolContext
from core.nlp_engine import nlp_engine, parse_target_datetime, split_items_list, format_iso_to_local
import db.database as db

@pytest.mark.asyncio
async def test_smart_nlp_multi_reminder():
    ctx = ToolContext(
        user_id="nlp_test_user",
        platform="telegram",
        chat_id="9999",
        timezone_name="Asia/Kolkata",
        user_name="Ali Abbas",
        assistant_name="Angel"
    )
    # Compound multi-action reminder
    msg = "Remind me to drink coffee after 2 minutes\nAnd to check project at 12:47"
    reply = await nlp_engine.process_user_intent(ctx, msg)
    assert reply is not None
    assert "Scheduled 2 Reminders" in reply or "Reminder Scheduled" in reply
    assert "drink coffee" in reply
    assert "check project" in reply

    # Verify both reminders exist in DB
    reminders = await db.get_active_reminders("nlp_test_user")
    texts = [r["reminder_text"] for r in reminders]
    assert any("drink coffee" in t for t in texts)
    assert any("check project" in t for t in texts)


@pytest.mark.asyncio
async def test_smart_nlp_multi_task_creation_and_listing():
    ctx = ToolContext(
        user_id="nlp_test_user_2",
        platform="telegram",
        chat_id="9999",
        timezone_name="Asia/Kolkata",
        user_name="Ali Abbas",
        assistant_name="Angel"
    )
    
    # 1. Multi-item task creation
    msg = "Create today's task list. Add tennis ball, namaz, and exam study in the tasks."
    reply = await nlp_engine.process_user_intent(ctx, msg)
    assert reply is not None
    assert "Task Created" in reply or "Added" in reply
    assert "tennis ball" in reply
    assert "namaz" in reply
    assert "exam study" in reply

    # 2. Query tasks
    reply_list = await nlp_engine.process_user_intent(ctx, "show active tasks")
    assert reply_list is not None
    assert "tennis ball" in reply_list
    assert "namaz" in reply_list
    assert "exam study" in reply_list

    # 3. Replace task list
    replace_msg = "Delete this and create new tasklist, add exam prep, coding and hacking in it"
    reply_replace = await nlp_engine.process_user_intent(ctx, replace_msg)
    assert reply_replace is not None
    assert "Task List Updated" in reply_replace
    assert "exam prep" in reply_replace
    assert "coding" in reply_replace
    assert "hacking" in reply_replace

    # Ensure previous tasks were cleared
    tasks = await db.get_tasks("nlp_test_user_2")
    task_titles = [t["title"] for t in tasks]
    assert "tennis ball" not in task_titles
    assert "exam prep" in task_titles


@pytest.mark.asyncio
async def test_smart_nlp_delete_by_ids_and_inactive():
    ctx = ToolContext(
        user_id="nlp_test_user_3",
        platform="telegram",
        chat_id="9999",
        timezone_name="Asia/Kolkata",
        user_name="Ali Abbas",
        assistant_name="Angel"
    )
    
    # Create tasks
    created = await db.add_multiple_tasks(ctx.user_id, ctx.platform, ["Item A", "Item B", "Item C"])
    id_a = created[0]["id"]
    id_b = created[1]["id"]

    # Delete by IDs: "Remove 53, 52" style
    reply_del = await nlp_engine.process_user_intent(ctx, f"Remove {id_a}, {id_b}")
    assert reply_del is not None
    assert "Successfully removed" in reply_del
    assert f"#{id_a}" in reply_del

    # Delete inactive reminders
    reply_clean = await nlp_engine.process_user_intent(ctx, "Remove the inactive reminders now")
    assert reply_clean is not None
    assert "All done" in reply_clean or "already tidy" in reply_clean
