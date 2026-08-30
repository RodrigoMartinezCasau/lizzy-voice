"""Grabación de audio — un solo stream continuo por frase (sin perder el inicio)."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from jarvis.logger import JarvisLogger


def _rms(chunk: np.ndarray) -> float:
    if chunk.size == 0:
        return 0.0
    mono = chunk[:, 0] if chunk.ndim > 1 else chunk
    return float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if from_rate == to_rate or audio.size == 0:
        return audio
    mono = audio[:, 0] if audio.ndim > 1 else audio
    target_len = int(len(mono) * to_rate / from_rate)
    if target_len <= 0:
        return np.zeros((0,), dtype=np.float32)
    resampled = np.interp(
        np.linspace(0, len(mono), target_len, endpoint=False),
        np.arange(len(mono)),
        mono.astype(np.float64),
    )
    return resampled.astype(np.float32)


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int,
        channels: int,
        logger: JarvisLogger,
        *,
        device: int | None = None,
        capture_rate: int | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.logger = logger
        self.device = device
        self.capture_rate = capture_rate or sample_rate
        self._lock = threading.Lock()
        self._abort = threading.Event()

    def abort(self) -> None:
        self._abort.set()

    def _read_chunk(
        self,
        stream: sd.InputStream,
        block_frames: int,
        timeout_s: float,
    ) -> np.ndarray | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._abort.is_set():
                return None
            try:
                chunk, overflowed = stream.read(block_frames)
                if overflowed:
                    self.logger.warn("Mic overflow")
                return chunk.copy()
            except sd.PortAudioError as exc:
                self.logger.error(f"Mic read error: {exc}")
                return None
        return None

    def record_phrase(
        self,
        timeout_s: float = 12.0,
        speech_threshold: float = 0.008,
        silence_threshold: float = 0.006,
        silence_duration_s: float = 1.1,
        min_duration_s: float = 0.35,
        wait_for_speech_s: float = 60.0,
        max_phrase_s: float = 4.0,
        pre_roll_chunks: int = 12,
        on_speech_started: Callable[[], None] | None = None,
    ) -> np.ndarray:
        """Espera voz y graba en el MISMO stream (conserva «hey jarvis» completo)."""
        self._abort.clear()
        block_frames = max(1, int(self.capture_rate * 0.06))
        block_duration = block_frames / self.capture_rate
        chunks: list[np.ndarray] = []
        pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_chunks)
        speech_started = False
        speech_started_notified = False
        speech_started_at: float | None = None
        silent_for = 0.0
        speech_elapsed = 0.0
        last_log = time.monotonic()

        with self._lock:
            try:
                with sd.InputStream(
                    samplerate=self.capture_rate,
                    channels=self.channels,
                    dtype="float32",
                    device=self.device,
                    blocksize=block_frames,
                ) as stream:
                    speech_deadline = time.monotonic() + wait_for_speech_s
                    record_deadline = speech_deadline + timeout_s

                    while time.monotonic() < record_deadline:
                        if self._abort.is_set():
                            break

                        chunk = self._read_chunk(stream, block_frames, 0.5)
                        if chunk is None:
                            break

                        level = _rms(chunk)

                        if not speech_started:
                            pre_roll.append(chunk)
                            if level >= speech_threshold:
                                speech_started = True
                                speech_started_at = time.monotonic()
                                chunks.extend(pre_roll)
                                pre_roll.clear()
                                speech_elapsed = len(chunks) * block_duration
                                if not speech_started_notified and on_speech_started:
                                    speech_started_notified = True
                                    try:
                                        on_speech_started()
                                    except Exception as exc:
                                        self.logger.warn(f"on_speech_started: {exc}")
                            elif time.monotonic() > speech_deadline:
                                return np.zeros((0, self.channels), dtype=np.float32)
                            elif time.monotonic() - last_log >= 20.0:
                                self.logger.info(
                                    f"Esperando voz… (nivel={level:.4f}, umbral={speech_threshold})"
                                )
                                last_log = time.monotonic()
                            continue

                        chunks.append(chunk)
                        speech_elapsed += block_duration

                        if (
                            speech_started_at is not None
                            and time.monotonic() - speech_started_at >= max_phrase_s
                        ):
                            self.logger.info(
                                f"Frase completa (máx {max_phrase_s:.0f}s) — procesando"
                            )
                            break

                        if level < silence_threshold and speech_elapsed > min_duration_s:
                            silent_for += block_duration
                            if silent_for >= silence_duration_s:
                                break
                        else:
                            silent_for = 0.0

            except Exception as exc:
                self.logger.error(f"Error grabando: {exc} (dev={self.device})")
                return np.zeros((0, self.channels), dtype=np.float32)

        if not chunks:
            return np.zeros((0, self.channels), dtype=np.float32)

        audio = np.concatenate(chunks, axis=0)
        resampled = _resample(audio, self.capture_rate, self.sample_rate)
        seconds = len(resampled) / self.sample_rate if resampled.size else 0.0
        self.logger.info(
            f"Audio capturado: {seconds:.1f}s (rms={_rms(audio):.4f}, dev={self.device})"
        )
        if resampled.ndim == 1:
            return resampled.reshape(-1, 1)
        return resampled

    def record_until_silence(
        self,
        timeout_s: float,
        silence_threshold: float = 0.010,
        silence_duration_s: float = 1.1,
        min_duration_s: float = 0.5,
    ) -> np.ndarray:
        """Graba inmediatamente hasta silencio (post-activación)."""
        return self.record_phrase(
            timeout_s=timeout_s,
            speech_threshold=0.0,
            silence_threshold=silence_threshold,
            silence_duration_s=silence_duration_s,
            min_duration_s=min_duration_s,
            wait_for_speech_s=timeout_s,
            pre_roll_chunks=4,
        )
