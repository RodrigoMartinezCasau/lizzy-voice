"""Text-to-speech con edge-tts — voz grave y pausada estilo JARVIS."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import edge_tts

from jarvis.logger import JarvisLogger


class TextToSpeech:
    def __init__(
        self,
        voice: str,
        rate: str,
        logger: JarvisLogger,
        *,
        pitch: str = "-12Hz",
        volume: str = "-5%",
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        self.logger = logger

    async def synthesize_to_file(
        self,
        text: str,
        output_path: Path,
        *,
        rate: str | None = None,
        pitch: str | None = None,
        volume: str | None = None,
    ) -> Path:
        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=rate or self.rate,
            pitch=pitch or self.pitch,
            volume=volume or self.volume,
        )
        await communicate.save(str(output_path))
        self.logger.info(f"TTS generado: {output_path.name} ({self.voice})")
        return output_path

    def speak(self, text: str) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = Path(tmp.name)
        asyncio.run(self.synthesize_to_file(text, path))
        return path

    def speak_dramatic(self, text: str) -> Path:
        """Locución lenta, grave, con pausas marcadas."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = Path(tmp.name)
        asyncio.run(
            self.synthesize_to_file(
                text,
                path,
                rate="-22%",
                pitch="-16Hz",
                volume="-4%",
            )
        )
        return path
