"""
Main application entry point for Tracky AI.
Unifies:
- FastAPI Web Server (Health, Admin endpoints, Webhooks)
- Background Scheduler (Proactive reminders & database lifecycle cleanup)
- Telegram Bot Service (Polling / Webhook)
- WhatsApp Service (Twilio / Meta Webhook)
"""

import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

from core.logger import logger, TRACKY_LOG_FILE, ERROR_LOG_FILE
from core.config import settings
from db.database import init_db
from core.scheduler import scheduler_service
from adapters.telegram_bot import telegram_adapter
from adapters.whatsapp_bot import whatsapp_adapter, whatsapp_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Tracky AI Services...")
    await init_db()
    scheduler_service.start()
    await telegram_adapter.start()
    await whatsapp_adapter.start()
    logger.info("Tracky AI is running and ready!")

    yield

    # Shutdown
    logger.info("Shutting down Tracky AI Services...")
    await telegram_adapter.stop()
    await whatsapp_adapter.stop()
    scheduler_service.stop()
    logger.info("Tracky AI shut down cleanly.")


app = FastAPI(
    title=settings.app.name,
    description="Intelligent multi-channel personal assistant for Telegram & WhatsApp",
    version="1.0.0",
    lifespan=lifespan,
)

# Attach WhatsApp router
app.include_router(whatsapp_router)


@app.get("/", response_class=JSONResponse)
async def root():
    return {
        "app": settings.app.name,
        "status": "online",
        "primary_model": settings.gemini.primary_model,
        "backup_model": settings.gemini.backup_model,
        "telegram_enabled": settings.telegram.enabled,
        "whatsapp_enabled": settings.whatsapp.enabled,
    }


@app.get("/health", response_class=JSONResponse)
async def health_check():
    return {
        "status": "healthy",
        "scheduler_running": scheduler_service.is_running,
        "timezone": settings.app.timezone,
    }


@app.get("/logs", response_class=PlainTextResponse)
async def get_logs(lines: int = 100, log_type: str = "tracky"):
    """
    Returns the latest logs for debugging and monitoring.
    log_type: 'tracky', 'error', or 'discussions'
    """
    if log_type == "discussions":
        file_path = settings.memory.absolute_discussion_log_path
    elif log_type == "error":
        file_path = ERROR_LOG_FILE
    else:
        file_path = TRACKY_LOG_FILE

    if not os.path.exists(file_path):
        return f"No log entries yet for '{log_type}'."
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:]
            return "".join(recent_lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading log file: {e}")


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=False,
    )
