"""Speech-to-text con Whisper local."""

from __future__ import annotations

import numpy as np
import whisper

from jarvis.logger import JarvisLogger


class SpeechToText:
    def __init__(
        self,
        model_name: str,
        language: str,
        logger: JarvisLogger,
        *,
        wake_name: str = "Lizzy",
        user_name: str = "Evo",
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.logger = logger
        self.wake_name = wake_name
        self.user_name = user_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            self.logger.info(f"Cargando Whisper '{self.model_name}'...")
            self._model = whisper.load_model(self.model_name)
        return self._model

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, *, fast: bool = False
    ) -> str:
        if audio.size == 0:
            return ""

        if audio.ndim > 1:
            audio = audio[:, 0]

        if sample_rate != 16_000:
            duration = len(audio) / sample_rate
            target_len = int(duration * 16_000)
            audio = np.interp(
                np.linspace(0, len(audio), target_len),
                np.arange(len(audio)),
                audio,
            )

        audio = audio.astype(np.float32)
        wake = self.wake_name
        transcribe_kw: dict = {
            "language": self.language,
            "fp16": False,
            "condition_on_previous_text": False,
            "initial_prompt": (
                f"Hey {wake}. {wake}. Lizzie. Lisi. Licy. {self.user_name} habla en español. "
                f"Comandos: hey {wake.lower()}, pon las luces azul, rojo, verde, naranja."
            ),
        }
        if fast:
            transcribe_kw.update(beam_size=1, best_of=1, temperature=0.0)

        result = self._get_model().transcribe(audio, **transcribe_kw)
        text = (result.get("text") or "").strip()
        self.logger.info(f"STT: {text[:120]}")
        return text
