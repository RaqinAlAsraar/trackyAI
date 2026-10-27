"""
SQLite Database Layer for Tracky AI.
Provides asynchronous connection and CRUD operations for:
- Tasks
- Events / Schedules
- Reminders
- Chat History
Includes automatic lifecycle cleanup for finished events and fired reminders.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
import aiosqlite

from core.logger import logger
from core.config import settings


@asynccontextmanager
async def get_db():
    """Async context manager for SQLite database connections."""
    db_path = settings.database.absolute_path
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    async with aiosqlite.connect(db_path, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL;")
        yield db


async def init_db() -> None:
    """Initializes the database schema if tables do not exist."""
    async with get_db() as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                due_date TEXT,
                priority TEXT DEFAULT 'normal',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                location TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                reminder_text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                triggered_at TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status, remind_at);
            CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id, created_at);
            """
        )
        await db.commit()
    logger.info("Database schema initialized successfully.")


# -------------------------------------------------------------
# Tasks CRUD
# -------------------------------------------------------------

async def add_task(
    user_id: str,
    platform: str,
    title: str,
    description: str = "",
    due_date: Optional[str] = None,
    priority: str = "normal",
) -> int:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO tasks (user_id, platform, title, description, due_date, priority, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, platform, title, description, due_date, priority, now_iso),
        )
        await db.commit()
        return cursor.lastrowid or 0


async def get_tasks(
    user_id: str, status: Optional[str] = "pending", due_date: Optional[str] = None
) -> List[Dict[str, Any]]:
    async with get_db() as db:
        query = "SELECT * FROM tasks WHERE user_id = ?"
        params = [user_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        if due_date:
            query += " AND (due_date = ? OR due_date IS NULL)"
            params.append(due_date)
        query += " ORDER BY id DESC"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_task_status(task_id: int, user_id: str, status: str) -> bool:
    now_iso = datetime.now(timezone.utc).isoformat() if status == "completed" else None
    async with get_db() as db:
        cursor = await db.execute(
            """
            UPDATE tasks SET status = ?, completed_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (status, now_iso, task_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_task(task_id: int, user_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_tasks_by_ids(task_ids: List[int], user_id: str) -> int:
    """Deletes multiple tasks by their IDs in a single query."""
    if not task_ids:
        return 0
    placeholders = ",".join("?" for _ in task_ids)
    async with get_db() as db:
        cursor = await db.execute(
            f"DELETE FROM tasks WHERE user_id = ? AND id IN ({placeholders})",
            [user_id, *task_ids],
        )
        await db.commit()
        return cursor.rowcount


async def delete_all_tasks(user_id: str, status: Optional[str] = "pending") -> int:
    """Clears tasks for user, optionally filtered by status (default 'pending')."""
    async with get_db() as db:
        if status:
            cursor = await db.execute(
                "DELETE FROM tasks WHERE user_id = ? AND status = ?",
                (user_id, status),
            )
        else:
            cursor = await db.execute(
                "DELETE FROM tasks WHERE user_id = ?",
                (user_id,),
            )
        await db.commit()
        return cursor.rowcount


async def add_multiple_tasks(
    user_id: str, platform: str, titles: List[str], priority: str = "normal", due_date: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Inserts multiple tasks in a single transaction, optionally with due_date."""
    now_iso = datetime.now(timezone.utc).isoformat()
    created = []
    async with get_db() as db:
        for t in titles:
            clean_title = t.strip()
            if not clean_title:
                continue
            cursor = await db.execute(
                """
                INSERT INTO tasks (user_id, platform, title, priority, due_date, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (user_id, platform, clean_title, priority, due_date, now_iso),
            )
            created.append({"id": cursor.lastrowid, "title": clean_title, "priority": priority, "due_date": due_date})
        await db.commit()
    return created


# -------------------------------------------------------------
# Events & Schedules CRUD
# -------------------------------------------------------------

async def add_event(
    user_id: str,
    platform: str,
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    location: str = "",
) -> int:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO events (user_id, platform, title, start_time, end_time, location, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, platform, title, start_time, end_time, location, now_iso),
        )
        await db.commit()
        return cursor.lastrowid or 0


async def get_events(
    user_id: str, active_only: bool = True
) -> List[Dict[str, Any]]:
    async with get_db() as db:
        if active_only:
            cursor = await db.execute(
                "SELECT * FROM events WHERE user_id = ? AND status = 'active' ORDER BY start_time ASC",
                (user_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM events WHERE user_id = ? ORDER BY start_time ASC",
                (user_id,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_event(event_id: int, user_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM events WHERE id = ? AND user_id = ?",
            (event_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def cleanup_expired_events() -> int:
    """Removes events whose end_time or start_time is in the past."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            DELETE FROM events
            WHERE (end_time IS NOT NULL AND end_time < ?)
               OR (end_time IS NULL AND datetime(start_time, '+2 hours') < ?)
            """,
            (now_iso, now_iso),
        )
        await db.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info(f"Cleaned up {count} expired events from database.")
        return count


# -------------------------------------------------------------
# Reminders CRUD
# -------------------------------------------------------------

async def add_reminder(
    user_id: str,
    platform: str,
    chat_id: str,
    reminder_text: str,
    remind_at: str,
) -> int:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO reminders (user_id, platform, chat_id, reminder_text, remind_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, platform, chat_id, reminder_text, remind_at, now_iso),
        )
        await db.commit()
        return cursor.lastrowid or 0


async def get_due_reminders(target_iso: str) -> List[Dict[str, Any]]:
    """Returns pending reminders scheduled on or before target_iso, accounting for timezones."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT * FROM reminders
            WHERE status = 'pending'
            ORDER BY remind_at ASC
            """
        )
        rows = await cursor.fetchall()
        try:
            target_dt = datetime.fromisoformat(target_iso.replace("Z", "+00:00"))
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=timezone.utc)
        except Exception:
            target_dt = datetime.now(timezone.utc)

        due_list = []
        for row in rows:
            r = dict(row)
            remind_str = r.get("remind_at", "")
            try:
                dt = datetime.fromisoformat(remind_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt <= target_dt:
                    due_list.append(r)
            except Exception:
                # If parsing fails, fall back to string comparison
                if remind_str <= target_iso:
                    due_list.append(r)
        return due_list


async def get_active_reminders(user_id: str) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT * FROM reminders
            WHERE user_id = ? AND status = 'pending'
            ORDER BY remind_at ASC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def mark_reminder_triggered(reminder_id: int) -> bool:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE reminders SET status = 'triggered', triggered_at = ? WHERE id = ?",
            (now_iso, reminder_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_reminder(reminder_id: int, user_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_reminders_by_ids(reminder_ids: List[int], user_id: str) -> int:
    """Deletes multiple reminders by their IDs."""
    if not reminder_ids:
        return 0
    placeholders = ",".join("?" for _ in reminder_ids)
    async with get_db() as db:
        cursor = await db.execute(
            f"DELETE FROM reminders WHERE user_id = ? AND id IN ({placeholders})",
            [user_id, *reminder_ids],
        )
        await db.commit()
        return cursor.rowcount


async def update_reminder_time(reminder_id: int, user_id: str, new_remind_at: str) -> bool:
    """Updates the scheduled time for an existing reminder."""
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE reminders SET remind_at = ?, status = 'pending' WHERE id = ? AND user_id = ?",
            (new_remind_at, reminder_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_reminder_text(reminder_id: int, user_id: str, new_text: str) -> bool:
    """Updates the text/title of an existing reminder."""
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE reminders SET reminder_text = ? WHERE id = ? AND user_id = ?",
            (new_text, reminder_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_task_title(task_id: int, user_id: str, new_title: str) -> bool:
    """Updates the title of an existing task."""
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE tasks SET title = ? WHERE id = ? AND user_id = ?",
            (new_title, task_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_tasks_by_date(user_id: str, date_str: str) -> int:
    """Deletes all tasks for a specific due_date."""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM tasks WHERE user_id = ? AND due_date = ?",
            (user_id, date_str),
        )
        await db.commit()
        return cursor.rowcount


async def delete_past_tasks(user_id: str, current_date_str: str) -> int:
    """Deletes past/outdated tasks where due_date < current_date_str, created_at < current_date_str, or status = 'completed'."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            DELETE FROM tasks
            WHERE user_id = ? AND (
                (due_date IS NOT NULL AND due_date < ?)
                OR (due_date IS NULL AND substr(created_at, 1, 10) < ?)
                OR status = 'completed'
            )
            """,
            (user_id, current_date_str, current_date_str),
        )
        await db.commit()
        return cursor.rowcount


async def get_all_reminders(user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves reminders for a user, optionally filtered by status."""
    async with get_db() as db:
        if status:
            cursor = await db.execute(
                "SELECT * FROM reminders WHERE user_id = ? AND status = ? ORDER BY remind_at ASC",
                (user_id, status),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM reminders WHERE user_id = ? ORDER BY remind_at ASC",
                (user_id,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def complete_tasks_by_keywords(user_id: str, keywords: List[str]) -> List[Dict[str, Any]]:
    """Finds pending tasks matching given keywords and marks them completed."""
    active_tasks = await get_tasks(user_id, status="pending")
    completed = []
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        for task in active_tasks:
            t_title = task["title"].lower()
            for kw in keywords:
                clean_kw = kw.strip().lower()
                # Match if prefix or substring matches
                if len(clean_kw) >= 3 and (clean_kw in t_title or t_title.startswith(clean_kw) or clean_kw.startswith(t_title[:4])):
                    await db.execute(
                        "UPDATE tasks SET status = 'completed', completed_at = ? WHERE id = ? AND user_id = ?",
                        (now_iso, task["id"], user_id),
                    )
                    completed.append(task)
                    break
        await db.commit()
    return completed


async def delete_completed_tasks(user_id: str) -> int:
    """Deletes all completed tasks for a user."""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM tasks WHERE user_id = ? AND status = 'completed'",
            (user_id,),
        )
        await db.commit()
        return cursor.rowcount


async def delete_inactive_reminders(user_id: str) -> int:
    """Removes all triggered, cancelled, or past-due reminders for user."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            DELETE FROM reminders
            WHERE user_id = ? AND (status IN ('triggered', 'cancelled') OR (status = 'pending' AND remind_at < ?))
            """,
            (user_id, now_iso),
        )
        await db.commit()
        return cursor.rowcount


async def cleanup_old_reminders() -> int:
    """Removes triggered or cancelled reminders older than 24 hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            DELETE FROM reminders
            WHERE status IN ('triggered', 'cancelled')
              AND (triggered_at IS NOT NULL AND triggered_at < ?)
            """,
            (cutoff,),
        )
        await db.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info(f"Cleaned up {count} old reminders from database.")
        return count


# -------------------------------------------------------------
# Chat History CRUD & Memory
# -------------------------------------------------------------

async def add_chat_message(
    user_id: str, platform: str, role: str, content: str
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO chat_history (user_id, platform, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, platform, role, content, now_iso),
        )
        await db.commit()


async def get_recent_chat_history(
    user_id: str, limit: int = 100, max_hours: int = 48
) -> List[Dict[str, str]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_hours)).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT role, content FROM (
                SELECT role, content, id FROM chat_history
                WHERE user_id = ? AND created_at >= ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (user_id, cutoff, limit),
        )
        rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]
