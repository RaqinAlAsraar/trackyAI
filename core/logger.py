"""
Logger module for Tracky AI.
Provides console and rotating file logging to logs/tracky.log and logs/error.log.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

TRACKY_LOG_FILE = os.path.join(LOG_DIR, "tracky.log")
ERROR_LOG_FILE = os.path.join(LOG_DIR, "error.log")

_initialized = False

class ColoredConsoleFormatter(logging.Formatter):
    COLOR_RESET = "\033[0m"
    COLOR_DIM = "\033[90m"
    COLOR_CYAN = "\033[36m"
    COLOR_GREEN = "\033[32m"
    COLOR_YELLOW = "\033[33m"
    COLOR_RED = "\033[31m"
    COLOR_BOLD_RED = "\033[1;31m"
    COLOR_MAGENTA = "\033[35m"
    COLOR_BOLD = "\033[1m"

    LEVEL_MAP = {
        logging.DEBUG: ("\033[35mDEBUG\033[0m", "🟣"),
        logging.INFO: ("\033[32mINFO \033[0m", "🟢"),
        logging.WARNING: ("\033[33mWARN \033[0m", "🟡"),
        logging.ERROR: ("\033[1;31mERROR\033[0m", "🔴"),
        logging.CRITICAL: ("\033[1;41mCRIT \033[0m", "🚨"),
    }

    def format(self, record: logging.LogRecord) -> str:
        time_str = self.formatTime(record, "%H:%M:%S")
        lvl_str, icon = self.LEVEL_MAP.get(record.levelno, (record.levelname, "⚪"))
        msg = record.getMessage()

        # Context-based styling for Tracky events
        if "💬 [DISCUSSION]" in msg:
            msg = msg.replace("💬 [DISCUSSION]", f"{self.COLOR_BOLD}{self.COLOR_CYAN}💬 [DISCUSSION]{self.COLOR_RESET}")
        elif "Firing reminder" in msg:
            msg = f"{self.COLOR_BOLD}{self.COLOR_YELLOW}🔔 {msg}{self.COLOR_RESET}"
        elif any(w in msg for w in ["Created reminder", "Created task", "Created event"]):
            msg = f"{self.COLOR_BOLD}{self.COLOR_GREEN}✨ {msg}{self.COLOR_RESET}"
        elif "Local-Only LLM mode active" in msg:
            msg = f"{self.COLOR_BOLD}{self.COLOR_MAGENTA}⚡ {msg}{self.COLOR_RESET}"
        elif "Attempting response generation" in msg:
            msg = f"{self.COLOR_CYAN}🧠 {msg}{self.COLOR_RESET}"

        return f"{self.COLOR_DIM}[{time_str}]{self.COLOR_RESET} {icon} [{lvl_str}] {msg}"


def setup_logger(debug: bool = True) -> logging.Logger:
    global _initialized
    logger = logging.getLogger("tracky")
    
    if _initialized:
        return logger
        
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    file_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_formatter = ColoredConsoleFormatter()

    # Console Handler (clean & colorful)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Main Rotating File Handler (10MB max per file, keeps 5 backups)
    file_handler = RotatingFileHandler(
        TRACKY_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Error Rotating File Handler (Errors & Criticals only)
    error_file_handler = RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(file_formatter)
    logger.addHandler(error_file_handler)

    _initialized = True
    logger.info("Tracky AI Logger initialized.")
    return logger

logger = setup_logger()
