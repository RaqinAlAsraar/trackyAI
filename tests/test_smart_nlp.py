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
        user_name="Test User",
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
        user_name="Test User",
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
        user_name="Test User",
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


@pytest.mark.asyncio
async def test_chat_issues_full_workflow():
    ctx = ToolContext(
        user_id="nlp_test_user_4",
        platform="telegram",
        chat_id="9999",
        timezone_name="Asia/Kolkata",
        user_name="Test User",
        assistant_name="Angel"
    )

    # 1. Date & Morning parsing (Issue #3)
    # "[Voice]: I have exam on 30 October. So set a reminder for that day at 6:00 a.m. morning."
    msg_exam = "I have exam on 30 October. So set a reminder for that day at 6:00 a.m. morning."
    reply_exam = await nlp_engine.process_user_intent(ctx, msg_exam)
    assert reply_exam is not None
    assert "Reminder Scheduled" in reply_exam
    assert "Exam" in reply_exam
    assert "6:00 AM" in reply_exam
    assert "Oct 30" in reply_exam

    # 2. Rescheduling (Issue #5)
    # Add an initial reminder
    res_init = await db.add_reminder(ctx.user_id, ctx.platform, ctx.chat_id, "check project", "2026-10-28T07:17:00+00:00")
    # "Change time for #<id> for today 1:15"
    reply_resched = await nlp_engine.process_user_intent(ctx, f"Change time for #{res_init} for today 1:15")
    assert reply_resched is not None
    assert "Reminder Rescheduled" in reply_resched
    assert "1:15 PM" in reply_resched

    # 3. Compound Eliminate + Add (Issue #1)
    # "Eliminate the reminder <id>, add a new reminder to check the project after 1:15 p.m."
    compound_msg = f"Eliminate the reminder {res_init}, add a new reminder to check the project after 1:15 p.m."
    reply_compound = await nlp_engine.process_user_intent(ctx, compound_msg)
    assert reply_compound is not None
    assert f"Removed reminder #{res_init}" in reply_compound
    assert "check the project" in reply_compound
    assert "1:15 PM" in reply_compound

    # 4. Fuzzy Task Completion (Issue #2)
    await db.add_multiple_tasks(ctx.user_id, ctx.platform, ["hacking in it", "coding", "exam prep"])
    reply_done = await nlp_engine.process_user_intent(ctx, "Hacki and coding are done")
    assert reply_done is not None
    assert "Marked 2 Tasks as Completed" in reply_done
    assert "coding" in reply_done
    assert "hacking in it" in reply_done

    # 5. User Feedback: "You were supposed to remove these tasks when they are done"
    reply_supposed = await nlp_engine.process_user_intent(ctx, "You were supposed to remove these tasks when they are done")
    assert reply_supposed is not None
    assert "Cleaned up" in reply_supposed or "completed task" in reply_supposed

    # 6. Timers mapping (Issue #4)
    reply_timers = await nlp_engine.process_user_intent(ctx, "Timers")
    assert reply_timers is not None
    assert "Active Timers & Reminders" in reply_timers

    # 7. Feedback: "Wrong reminder time"
    reply_wrong = await nlp_engine.process_user_intent(ctx, "Wrong reminder time")
    assert reply_wrong is not None
    assert "My apologies" in reply_wrong


@pytest.mark.asyncio
async def test_recent_chat_edge_cases():
    ctx = ToolContext(
        user_id="nlp_edge_user",
        platform="telegram",
        chat_id="8888",
        timezone_name="Asia/Kolkata",
        user_name="Test User",
        assistant_name="Angel"
    )

    # 1. Clean Title: "Add reminder for 5:00 pm today to write the diary notes."
    res1 = await nlp_engine.process_user_intent(ctx, "Add reminder for 5:00 pm today to write the diary notes.")
    assert res1 is not None
    assert "write the diary notes" in res1
    assert "Add reminder" not in res1.split("• **What**:")[1].split("\n")[0]

    # 2. Clean Title: "Set reminder for 1:25 today for drinking tea and eating snacks."
    res2 = await nlp_engine.process_user_intent(ctx, "Set reminder for 1:25 today for drinking tea and eating snacks.")
    assert res2 is not None
    assert "drinking tea and eating snacks" in res2
    assert "day for drinking" not in res2

    # 3. Contextual Rescheduling: "I have event on 29 October. So set reminder for that." then "Change it's Timing to 6 am"
    res3 = await nlp_engine.process_user_intent(ctx, "I have event on 29 October. So set reminder for that.")
    assert "Oct 29" in res3
    res_change = await nlp_engine.process_user_intent(ctx, "Change it's Timing to 6 am")
    assert res_change is not None
    assert "Reminder Rescheduled" in res_change
    assert "Oct 29 at 6:00 AM" in res_change

    # 4. Date-Filtered Reminders: "Show only today reminders"
    res_today_rems = await nlp_engine.process_user_intent(ctx, "Show only today reminders")
    assert res_today_rems is not None
    assert "Today's Active Reminders" in res_today_rems
    # Oct 29 event must NOT be in today's reminders!
    assert "Oct 29" not in res_today_rems

    # 5. Date-Associated Tasks: "Create tasklist for 28 october, add coding, shopping"
    res_create_tasks = await nlp_engine.process_user_intent(ctx, "Create tasklist for 28 october, add coding, shopping")
    assert res_create_tasks is not None
    assert "Added 2 Tasks for Oct 28" in res_create_tasks or "Added 2 Tasks" in res_create_tasks

    # "Show today's tasklist" - Oct 28 tasks must not pollute today's active tasks
    res_today_tasks = await nlp_engine.process_user_intent(ctx, "Show today's tasklist")
    assert res_today_tasks is not None
    assert "coding" not in res_today_tasks
    assert "shopping" not in res_today_tasks


@pytest.mark.asyncio
async def test_scope_and_crud_features():
    ctx = ToolContext(
        user_id="nlp_scope_user",
        platform="telegram",
        chat_id="7777",
        timezone_name="Asia/Kolkata",
        user_name="Test User",
        assistant_name="Angel"
    )

    # 1. Create dated tasks for tomorrow
    create_tom = await nlp_engine.process_user_intent(ctx, "Create tasklist for tomorrow, add review pr, write documentation")
    assert create_tom is not None
    assert "Added 2 Tasks" in create_tom

    # 2. Query weekly task list (should show grouped dates)
    week_tasks = await nlp_engine.process_user_intent(ctx, "Show weekly tasklist")
    assert week_tasks is not None
    assert "Weekly Task List" in week_tasks
    assert "review pr" in week_tasks
    assert "write documentation" in week_tasks

    # 3. Rename Task
    # Find the task id
    tasks = await db.get_tasks(ctx.user_id, status="pending")
    pr_task = next(t for t in tasks if "review pr" in t["title"])
    rename_res = await nlp_engine.process_user_intent(ctx, f"Rename task #{pr_task['id']} to review pull requests and merge")
    assert rename_res is not None
    assert "Task #" in rename_res and "review pull requests and merge" in rename_res

    # 4. Rename Reminder
    rem_id = await db.add_reminder(ctx.user_id, ctx.platform, ctx.chat_id, "quick call", "2026-10-29T10:00:00+00:00")
    rename_rem_res = await nlp_engine.process_user_intent(ctx, f"Rename reminder #{rem_id} to Sync with architecture team")
    assert rename_rem_res is not None
    assert "Reminder #" in rename_rem_res and "Sync with architecture team" in rename_rem_res

    # 5. Pure scope follow-up
    # Save a chat indicating user asked about reminders
    await db.add_chat_message(ctx.user_id, ctx.platform, "user", "Show me active reminders for today")
    await db.add_chat_message(ctx.user_id, ctx.platform, "assistant", "You have no reminders for today")
    followup_week = await nlp_engine.process_user_intent(ctx, "for the week")
    assert followup_week is not None
    assert "Reminders" in followup_week
    assert "Sync with architecture team" in followup_week

    # 6. Delete tasklist for a specific date
    delete_date = await nlp_engine.process_user_intent(ctx, "delete tasks for tomorrow")
    assert delete_date is not None
    assert "Deleted" in delete_date

    # Verify tasks for tomorrow are gone
    remaining = await db.get_tasks(ctx.user_id, status="pending")
    assert not any("write documentation" in t["title"] for t in remaining)

    # 7. Delete previous tasklists
    # Insert an outdated task from yesterday
    async with db.get_db() as conn:
        await conn.execute(
            "INSERT INTO tasks (user_id, platform, title, due_date, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.user_id, ctx.platform, "old obsolete task", "2026-10-20", "2026-10-20T10:00:00+00:00")
        )
        await conn.commit()
    del_past = await nlp_engine.process_user_intent(ctx, "delete previous tasklists as well which has no use now")
    assert del_past is not None
    assert "Cleaned up" in del_past
    # Confirm it was removed from db
    all_user_tasks = await db.get_tasks(ctx.user_id)
    assert not any(t["title"] == "old obsolete task" for t in all_user_tasks)



