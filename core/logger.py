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

def setup_logger(debug: bool = True) -> logging.Logger:
    global _initialized
    logger = logging.getLogger("tracky")
    
    if _initialized:
        return logger
        
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Main Rotating File Handler (10MB max per file, keeps 5 backups)
    file_handler = RotatingFileHandler(
        TRACKY_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Error Rotating File Handler (Errors & Criticals only)
    error_file_handler = RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)
    logger.addHandler(error_file_handler)

    _initialized = True
    logger.info("Tracky AI Logger initialized.")
    return logger

logger = setup_logger()
