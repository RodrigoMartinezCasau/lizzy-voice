"""Wake word con Porcupine."""

from __future__ import annotations

import struct
from collections.abc import Callable

import pvporcupine
import sounddevice as sd

from jarvis.logger import JarvisLogger


class WakeWordListener:
    def __init__(
        self,
        access_key: str,
        keyword: str,
        sample_rate: int,
        logger: JarvisLogger,
        on_detected: Callable[[], None],
    ) -> None:
        if not access_key:
            raise RuntimeError(
                "PICOVOICE_ACCESS_KEY requerida. Obtén una en console.picovoice.ai"
            )
        self.logger = logger
        self.on_detected = on_detected
        self.sample_rate = sample_rate
        self._porcupine = pvporcupine.create(
            access_key=access_key,
            keywords=[keyword],
        )
        self._frame_length = self._porcupine.frame_length
        self._audio_stream: sd.RawInputStream | None = None
        self._paused = False

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def start(self) -> None:
        self.logger.info(f"Escuchando palabra clave: '{self._porcupine.keywords[0]}'")

        def callback(indata, _frames, _time, status) -> None:
            if status:
                self.logger.warn(f"Audio status: {status}")
            if self._paused:
                return
            pcm = struct.unpack_from(
                "h" * self._frame_length, indata, 0
            )
            result = self._porcupine.process(pcm)
            if result >= 0:
                self.logger.info("Wake word detectada")
                self.on_detected()

        self._audio_stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self._frame_length,
            dtype="int16",
            channels=1,
            callback=callback,
        )
        self._audio_stream.start()

    def stop(self) -> None:
        if self._audio_stream:
            self._audio_stream.stop()
            self._audio_stream.close()
            self._audio_stream = None
        self._porcupine.delete()
