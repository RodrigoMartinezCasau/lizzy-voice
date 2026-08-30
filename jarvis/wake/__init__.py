"""Factory de wake word."""

from __future__ import annotations

from collections.abc import Callable

from jarvis.audio.recorder import AudioRecorder
from jarvis.audio.stt import SpeechToText
from jarvis.logger import JarvisLogger
from jarvis.wake.openwakeword_listener import WakeWordListener as OpenWakeWordListener
from jarvis.wake.porcupine_listener import WakeWordListener as PorcupineListener
from jarvis.wake.whisper_wake import WhisperWakeListener


def create_wake_listener(
    backend: str,
    *,
    sample_rate: int,
    logger: JarvisLogger,
    on_detected: Callable[[], None],
    on_command: Callable[[str], None] | None = None,
    on_phrase_captured: Callable[[], None] | None = None,
    on_speech_started: Callable[[], None] | None = None,
    is_conversation_active: Callable[[], bool] | None = None,
    on_wake_detected: Callable[[], None] | None = None,
    is_armed: Callable[[], bool] | None = None,
    silence_duration_s: float = 0.9,
    max_phrase_s: float = 4.0,
    wake_name: str = "Lizzy",
    recorder: AudioRecorder | None = None,
    stt: SpeechToText | None = None,
    wake_stt: SpeechToText | None = None,
    listen_timeout_s: float = 60.0,
    picovoice_access_key: str = "",
    wake_word: str = "lizzy",
    oww_model: str = "hey_lizzy",
    oww_threshold: float = 0.5,
):
    if backend == "whisper":
        if not recorder or not stt or not on_command:
            raise RuntimeError("whisper wake requiere recorder, stt y on_command")
        return WhisperWakeListener(
            recorder,
            stt,
            logger,
            on_command,
            listen_timeout_s,
            wake_stt=wake_stt,
            on_phrase_captured=on_phrase_captured,
            on_speech_started=on_speech_started,
            is_conversation_active=is_conversation_active,
            on_wake_detected=on_wake_detected,
            is_armed=is_armed,
            silence_duration_s=silence_duration_s,
            max_phrase_s=max_phrase_s,
            wake_name=wake_name,
        )
    if backend == "porcupine":
        return PorcupineListener(
            access_key=picovoice_access_key,
            keyword=wake_word,
            sample_rate=sample_rate,
            logger=logger,
            on_detected=on_detected,
        )
    return OpenWakeWordListener(
        model_name=oww_model,
        threshold=oww_threshold,
        sample_rate=sample_rate,
        logger=logger,
        on_detected=on_detected,
    )
