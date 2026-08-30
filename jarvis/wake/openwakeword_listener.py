"""Wake word con openWakeWord — local, sin API key."""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
import openwakeword
import sounddevice as sd
from openwakeword.model import Model

from jarvis.logger import JarvisLogger

FRAME_SAMPLES = 1280


class WakeWordListener:
    def __init__(
        self,
        model_name: str,
        threshold: float,
        sample_rate: int,
        logger: JarvisLogger,
        on_detected: Callable[[], None],
    ) -> None:
        if sample_rate != 16_000:
            raise ValueError("openWakeWord requiere sample_rate=16000")

        self.logger = logger
        self.on_detected = on_detected
        self.threshold = threshold
        self.model_name = model_name
        self._paused = False
        self._last_detection = 0.0
        self._cooldown_s = 2.0
        self._audio_stream: sd.InputStream | None = None

        self.logger.info("Cargando modelo wake word...")
        openwakeword.utils.download_models(model_names=[model_name])
        self._model = Model(wakeword_models=[model_name], inference_framework="onnx")
        self._score_key = next(iter(self._model.models.keys()))

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False
        self._last_detection = time.time()

    def start(self) -> None:
        mic = sd.query_devices(kind="input")
        self.logger.info(
            f"Escuchando «hey lizzy» en: {mic['name']} (umbral {self.threshold})"
        )

        def callback(indata, _frames, _time, status) -> None:
            if status:
                self.logger.warn(f"Audio status: {status}")
            if self._paused:
                return

            pcm = (indata[:, 0] * 32767).astype(np.int16)
            scores = self._model.predict(pcm)
            score = float(scores.get(self._score_key, 0.0))
            if score >= self.threshold:
                now = time.time()
                if now - self._last_detection < self._cooldown_s:
                    return
                self._last_detection = now
                self.logger.info(f"Wake word detectada (score={score:.2f})")
                self.on_detected()

        self._audio_stream = sd.InputStream(
            samplerate=16_000,
            blocksize=FRAME_SAMPLES,
            dtype="float32",
            channels=1,
            callback=callback,
        )
        self._audio_stream.start()

    def stop(self) -> None:
        if self._audio_stream:
            self._audio_stream.stop()
            self._audio_stream.close()
            self._audio_stream = None
