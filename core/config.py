"""
Configuration loader and validator for Tracky AI.
Reads config.json with sensible defaults and environment overrides.
"""

import os
import json
from typing import List, Optional
from pydantic import BaseModel, Field
from core.logger import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


class AppConfig(BaseModel):
    name: str = "Tracky AI"
    assistant_name: str = "Tracky"
    user_name: str = "Friend"
    host: str = "0.0.0.0"
    port: int = 8000
    timezone: str = "Asia/Kolkata"
    debug: bool = True


class GeminiConfig(BaseModel):
    api_key: str = ""
    primary_model: str = "models/gemma-4-26b-a4b-it"
    backup_model: str = "models/gemini-2.5-flash"
    temperature: float = 0.4
    max_output_tokens: int = 1024


class DatabaseConfig(BaseModel):
    path: str = "tracky.db"

    @property
    def absolute_path(self) -> str:
        if os.path.isabs(self.path):
            return self.path
        return os.path.join(BASE_DIR, self.path)


class MemoryConfig(BaseModel):
    max_history_messages: int = 100
    max_history_hours: int = 48
    memory_log_file: str = "memory.log"

    @property
    def absolute_log_path(self) -> str:
        if os.path.isabs(self.memory_log_file):
            return self.memory_log_file
        return os.path.join(BASE_DIR, self.memory_log_file)


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    mode: str = "polling"  # 'polling' or 'webhook'
    webhook_url: str = ""
    allowed_user_ids: List[int] = Field(default_factory=list)


class WhatsAppConfig(BaseModel):
    enabled: bool = False
    provider: str = "twilio"  # 'twilio' or 'meta'
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    meta_phone_number_id: str = ""
    meta_access_token: str = ""
    meta_verify_token: str = "tracky_webhook_verify_token"
    allowed_phone_numbers: List[str] = Field(default_factory=list)


class VoiceConfig(BaseModel):
    stt_enabled: bool = True
    tts_enabled: bool = True
    tts_voice: str = "en-US-ChristopherNeural"


class GuardrailsConfig(BaseModel):
    rate_limit_messages_per_minute: int = 20
    max_message_chars: int = 2000


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)


def load_settings(path: Optional[str] = None) -> Settings:
    config_file = path or CONFIG_PATH
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            settings = Settings.model_validate(data)
            logger.info(f"Loaded configuration from {config_file}")
            return settings
        except Exception as e:
            logger.warning(f"Failed to parse {config_file}: {e}. Using defaults.")

    logger.info("Using default settings (config.json not found or unreadable).")
    return Settings()


# Global settings instance
settings = load_settings()
