"""
Voice module for Tracky AI:
- Speech-to-Text (STT) via Gemini multimodal audio transcription
- Text-to-Speech (TTS) via edge-tts (high-quality Microsoft neural voices)
"""

import os
import tempfile
import asyncio
from typing import Optional
import edge_tts
from google import genai
from google.genai import types

from core.logger import logger
from core.config import settings


class VoiceProcessor:
    def __init__(self):
        self.stt_enabled = settings.voice.stt_enabled
        self.tts_enabled = settings.voice.tts_enabled
        self.tts_voice = settings.voice.tts_voice

    async def transcribe_audio_file(self, audio_file_path: str, mime_type: str = "audio/ogg") -> Optional[str]:
        """
        Transcribes speech using Gemini's native audio understanding.
        Accepts voice notes (.ogg, .mp3, .wav, .m4a).
        """
        if not self.stt_enabled:
            logger.info("STT is disabled in configuration.")
            return None

        if not os.path.exists(audio_file_path):
            logger.error(f"Audio file not found: {audio_file_path}")
            return None

        try:
            logger.info(f"Transcribing audio file {audio_file_path} via Gemini...")
            client = genai.Client(api_key=settings.gemini.api_key)
            with open(audio_file_path, "rb") as f:
                audio_bytes = f.read()

            response = await client.aio.models.generate_content(
                model="models/gemini-3-flash-preview",
                contents=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                    "Please accurately transcribe all spoken words from this audio clip verbatim. Output ONLY the transcribed text without commentary or quotation marks.",
                ],
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            transcription = response.text.strip() if response.text else ""
            logger.info(f"Audio transcribed successfully: '{transcription}'")
            return transcription
        except Exception as e:
            logger.error(f"Failed to transcribe audio with Gemini: {e}")
            return None

    async def text_to_speech(self, text: str, output_path: Optional[str] = None) -> Optional[str]:
        """
        Generates realistic voice audio using edge-tts.
        Returns the path to the generated audio file (.mp3).
        """
        if not self.tts_enabled:
            logger.info("TTS is disabled in configuration.")
            return None

        if not output_path:
            fd, output_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)

        try:
            communicate = edge_tts.Communicate(text, self.tts_voice)
            await communicate.save(output_path)
            logger.info(f"Generated TTS audio file at {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to generate TTS audio: {e}")
            return None


voice_processor = VoiceProcessor()
