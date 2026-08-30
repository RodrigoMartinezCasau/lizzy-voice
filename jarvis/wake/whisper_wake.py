"""Activación por voz — escucha continua + Whisper detecta «Lizzy»."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from jarvis.audio.recorder import AudioRecorder, _rms
from jarvis.audio.stt import SpeechToText
from jarvis.lights.commands import parse_light_command, preprocess_command_text
from jarvis.logger import JarvisLogger
from jarvis.wake.wake_match import looks_like_wake

MIN_AUDIO_RMS = 0.002
MIN_CONVERSATION_CHARS = 3


class WhisperWakeListener:
    """Espera voz, transcribe, activa si oye «Lizzy» (o suena parecido)."""

    def __init__(
        self,
        recorder: AudioRecorder,
        stt: SpeechToText,
        logger: JarvisLogger,
        on_command: Callable[[str], None],
        listen_timeout_s: float = 60.0,
        wake_stt: SpeechToText | None = None,
        on_phrase_captured: Callable[[], None] | None = None,
        on_speech_started: Callable[[], None] | None = None,
        is_conversation_active: Callable[[], bool] | None = None,
        on_wake_detected: Callable[[], None] | None = None,
        is_armed: Callable[[], bool] | None = None,
        silence_duration_s: float = 0.9,
        max_phrase_s: float = 4.0,
        wake_name: str = "Lizzy",
    ) -> None:
        self.recorder = recorder
        self.stt = stt
        self.wake_stt = wake_stt or stt
        self.logger = logger
        self.on_command = on_command
        self.on_phrase_captured = on_phrase_captured
        self.on_speech_started = on_speech_started
        self.is_conversation_active = is_conversation_active
        self.on_wake_detected = on_wake_detected
        self.is_armed = is_armed
        self.silence_duration_s = silence_duration_s
        self.max_phrase_s = max_phrase_s
        self.wake_name = wake_name
        self.listen_timeout_s = listen_timeout_s
        self._paused = True
        self._running = False
        self._thread: threading.Thread | None = None
        self._speech_ack_sent = False
        self._record_errors = 0

    def pause(self) -> None:
        self._paused = True
        self.recorder.abort()

    def resume(self) -> None:
        self._paused = False
        self._speech_ack_sent = False

    def start(self) -> None:
        self._running = True
        self._paused = False
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="whisper-wake"
        )
        self._thread.start()
        self.logger.info(
            f"Escuchando continuamente — di «hey {self.wake_name.lower()}» + tu pregunta "
            "(15 s de conversación tras activar)"
        )

    def stop(self) -> None:
        self._running = False
        self.recorder.abort()

    @staticmethod
    def _is_direct_light_command(text: str) -> bool:
        normalized = preprocess_command_text(text)
        return parse_light_command(normalized) is not None

    def _fire_speech_started(self) -> None:
        if self.is_armed and not self.is_armed():
            return
        if self._speech_ack_sent or not self.on_speech_started:
            return
        if self.is_conversation_active and self.is_conversation_active():
            return
        self._speech_ack_sent = True
        try:
            self.on_speech_started()
        except Exception as exc:
            self.logger.warn(f"on_speech_started: {exc}")

    def _loop(self) -> None:
        while self._running:
            if self._paused:
                time.sleep(0.05)
                continue

            self._speech_ack_sent = False
            armed = self.is_armed() if self.is_armed else True
            in_conversation = armed and (
                self.is_conversation_active() if self.is_conversation_active else False
            )

            try:
                audio = self.recorder.record_phrase(
                    timeout_s=14.0 if in_conversation else 12.0,
                    wait_for_speech_s=self.listen_timeout_s,
                    max_phrase_s=self.max_phrase_s,
                    speech_threshold=0.004,
                    silence_threshold=0.006,
                    silence_duration_s=self.silence_duration_s,
                    min_duration_s=0.3,
                    on_speech_started=self._fire_speech_started,
                )
            except Exception as exc:
                self._record_errors += 1
                self.logger.error(f"Error grabando: {exc}")
                delay = min(30.0, 0.5 * (2 ** min(self._record_errors, 6)))
                if self._record_errors in (1, 5, 20) or self._record_errors % 60 == 0:
                    self.logger.warn(
                        f"Micrófono sin captura ({self._record_errors} fallos) — "
                        f"reintento en {delay:.0f}s"
                    )
                time.sleep(delay)
                continue

            if not self._running or self._paused:
                continue

            if audio.size == 0:
                self._record_errors += 1
                delay = min(30.0, 0.5 * (2 ** min(self._record_errors, 6)))
                if self._record_errors in (1, 5, 20) or self._record_errors % 60 == 0:
                    self.logger.warn(
                        f"Sin captura de micrófono ({self._record_errors} intentos) — "
                        f"reintento en {delay:.0f}s"
                    )
                time.sleep(delay)
                continue

            self._record_errors = 0

            rms = _rms(audio)
            if rms < MIN_AUDIO_RMS:
                self.logger.info(f"Audio muy bajo (rms={rms:.4f}) — intentando STT igualmente")

            if self.on_phrase_captured:
                try:
                    self.on_phrase_captured()
                except Exception as exc:
                    self.logger.warn(f"on_phrase_captured: {exc}")

            try:
                text = self.wake_stt.transcribe(
                    audio, self.recorder.sample_rate, fast=not in_conversation
                )
            except Exception as exc:
                self.logger.error(f"Error STT wake: {exc}")
                continue

            if not text or len(text.strip()) < MIN_CONVERSATION_CHARS:
                if in_conversation:
                    self.logger.info("Modo conversación — STT vacío, sigo escuchando")
                else:
                    self.logger.info("STT vacío — repita más cerca del micrófono")
                continue

            if in_conversation:
                wake = looks_like_wake(text)
                if not wake:
                    self.logger.info(
                        f"Conversación ({self.silence_duration_s}s silencio): {text[:100]}"
                    )
                    self.on_command(text)
                    continue

            wake = looks_like_wake(text)

            if not armed:
                if not wake:
                    self.logger.info(f"Reposo (ignorado): {text[:80]}")
                    continue
                self.logger.info(f"Reactivación: {text[:100]}")
                if self.on_wake_detected:
                    try:
                        self.on_wake_detected()
                    except Exception as exc:
                        self.logger.warn(f"on_wake_detected: {exc}")
                self.on_command(text)
                continue

            light = self._is_direct_light_command(text)

            if not wake and not light:
                self.logger.info(f"Oído (ignorado): {text[:80]}")
                continue

            if wake:
                self.logger.info(f"Activación: {text[:100]}")
                if self.on_wake_detected:
                    try:
                        self.on_wake_detected()
                    except Exception as exc:
                        self.logger.warn(f"on_wake_detected: {exc}")
            else:
                self.logger.info(f"Comando luces directo: {text[:100]}")

            self.on_command(text)
