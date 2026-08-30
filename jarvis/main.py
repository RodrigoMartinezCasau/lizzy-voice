#!/usr/bin/env python3
"""Lizzy — punto de entrada principal."""

from __future__ import annotations

import asyncio
import faulthandler
import re
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

from jarvis.audio.mic_guard import probe_microphone, validate_input_device
from jarvis.audio.devices import resolve_input_settings, resolve_output_device
from jarvis.audio.mic_permissions import (
    launched_from_app,
    notify_assistant_started,
    permission_hint,
    request_microphone_access,
)
from jarvis.audio.phrases import count_speech_cycles
from jarvis.tools.live_data import answer_time_query, build_live_context
from jarvis.audio.player import AudioPlayer
from jarvis.audio.recorder import AudioRecorder
from jarvis.audio.stt import SpeechToText
from jarvis.audio.tts import TextToSpeech
from jarvis.brain.agent import Brain
from jarvis.brain.capabilities import build_capabilities
from jarvis.brain.context_loader import load_context
from jarvis.commands.rituals import answer_daily_conclusion, is_daily_conclusion_query
from jarvis.commands.system import is_shutdown_command
from jarvis.config import load_config
from jarvis.lights.commands import parse_light_command, preprocess_command_text
from jarvis.lights.lepro import LedState, LeproMqttController, create_led_controller
from jarvis.logger import JarvisLogger
from jarvis.tools.dev_commands import try_handle_dev_command
from jarvis.wake import create_wake_listener
from jarvis.wake.wake_match import build_wake_prefix_pattern

def _install_crash_handlers(logger: JarvisLogger) -> None:
    faulthandler.enable()

    def _log_exc(exc_type, exc, tb) -> None:
        logger.error("".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _log_exc

    if hasattr(threading, "excepthook"):

        def _thread_exc(args) -> None:
            logger.error(
                "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                )
            )

        threading.excepthook = _thread_exc


class Lizzy:
    def __init__(self) -> None:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        self.cfg = load_config()
        self.logger = JarvisLogger(self.cfg.log_file)
        self._wake_prefix = build_wake_prefix_pattern(self.cfg.wake_word)
        _install_crash_handlers(self.logger)
        resolve_input_settings(
            self.cfg.audio_input_device,
            self.cfg.audio_input_device_name or None,
            self.cfg.capture_rate,
            self.cfg.channels,
            self.logger,
        )
        resolve_output_device(
            self.cfg.audio_output_device,
            self.cfg.audio_output_device_name or None,
            self.logger,
        )

        leds_backend = self.cfg.leds_backend
        if leds_backend == "lepro_cloud" and not (
            self.cfg.light_account and self.cfg.light_token
        ):
            self.logger.warn("Lepro sin credenciales — LEDs en modo mock")
            leds_backend = "mock"

        self.leds = create_led_controller(
            leds_backend,
            self.logger,
            wled_host=self.cfg.wled_host,
            light_account=self.cfg.light_account,
            light_token=self.cfg.light_token,
            lepro_region=self.cfg.lepro_region,
            light_device=self.cfg.light_device,
        )
        self.recorder = AudioRecorder(
            self.cfg.sample_rate,
            self.cfg.channels,
            self.logger,
            device=self.cfg.audio_input_device,
            capture_rate=self.cfg.capture_rate,
        )
        self.stt = SpeechToText(
            self.cfg.whisper_model,
            self.cfg.whisper_language,
            self.logger,
            wake_name=self.cfg.assistant_name,
            user_name=self.cfg.user_name,
        )
        self.wake_stt = SpeechToText(
            self.cfg.wake_whisper_model,
            self.cfg.whisper_language,
            self.logger,
            wake_name=self.cfg.assistant_name,
            user_name=self.cfg.user_name,
        )
        self.tts = TextToSpeech(
            self.cfg.tts_voice,
            self.cfg.tts_rate,
            self.logger,
            pitch=self.cfg.tts_pitch,
            volume=self.cfg.tts_volume,
        )
        self.player = AudioPlayer(
            self.logger,
            output_device=self.cfg.audio_output_device,
        )
        self.brain = Brain(
            api_key=self.cfg.anthropic_api_key,
            model=self.cfg.llm_model,
            user_name=self.cfg.user_name,
            assistant_name=self.cfg.assistant_name,
            max_tokens=self.cfg.max_response_tokens,
            logger=self.logger,
        )
        self._lock = threading.Lock()
        self._running = True
        self._wake_listener = None
        self._conversation_until = 0.0
        self._armed = True
        self._capabilities = build_capabilities(
            self.cfg.user_name,
            str(self.cfg.dev_workspace),
            assistant_name=self.cfg.assistant_name,
        )
        self.logger.info("Cargando contexto de empresa…")
        self._context_cache = load_context(
            self.cfg.context_dir, max_chars=self.cfg.context_max_chars
        )
        self.logger.info(
            f"Contexto cargado: {len(self._context_cache):,} caracteres"
        )

        threading.Thread(target=self.stt._get_model, daemon=True).start()
        threading.Thread(target=self.wake_stt._get_model, daemon=True).start()

    def _in_conversation(self) -> bool:
        return time.monotonic() < self._conversation_until

    def _extend_conversation(self) -> None:
        self._conversation_until = time.monotonic() + self.cfg.conversation_window_s
        self.logger.info(
            f"Modo conversación activo {self.cfg.conversation_window_s:.0f}s"
        )

    def _on_wake_detected(self) -> None:
        self._armed = True
        self._extend_conversation()

    def _set_leds(self, state: LedState) -> None:
        asyncio.run(self.leds.set_state(state))

    def _set_color(self, rgb: tuple[int, int, int], brightness: int = 45) -> None:
        asyncio.run(self.leds.set_custom_color(rgb, brightness))

    def _idle_leds(self) -> None:
        if self._armed:
            self._set_leds(LedState.STANDBY)
        else:
            self._set_leds(LedState.SLEEP)

    def _speak(self, text: str, *, dramatic: bool = False) -> None:
        num_cycles = count_speech_cycles(text)

        async def _blink_and_play() -> None:
            synth = (
                (lambda t: self.tts.speak_dramatic(t))
                if dramatic
                else (lambda t: self.tts.speak(t))
            )
            mp3 = await asyncio.to_thread(synth, text)
            duration = self.player.get_duration(mp3)
            if duration <= 0:
                duration = max(1.5, len(text) * (0.085 if dramatic else 0.065))
            await self.leds.start_speaking_blink(
                duration_s=duration, num_cycles=num_cycles
            )
            try:
                await asyncio.to_thread(self.player.play, mp3)
            finally:
                await self.leds.stop_speaking_blink()
                mp3.unlink(missing_ok=True)

        try:
            asyncio.run(_blink_and_play())
        finally:
            self._idle_leds()

    def _immediate_ack(self) -> None:
        """Tonito de confirmación — afplay para no interferir con el micrófono."""
        try:
            self._set_leds(LedState.ACTIVATED)
            path = self.cfg.activate_sound
            if path.exists():
                import subprocess

                subprocess.run(["afplay", str(path)], check=False)
            else:
                self.logger.warn("activate.mp3 no encontrado — omitiendo tono")
        except Exception as exc:
            self.logger.warn(f"Ack inmediato: {exc}")

    def _on_speech_started(self) -> None:
        """Feedback instantáneo solo si está armado y no en conversación."""
        if not self._armed or self._in_conversation():
            return
        threading.Thread(target=self._immediate_ack, daemon=True).start()

    def _on_phrase_captured(self) -> None:
        pass  # ack ya en _on_speech_started

    def _dispatch(self, fn, *args) -> None:
        def _run() -> None:
            if not self._lock.acquire(blocking=False):
                self.logger.warn("Ocupado — repita en un momento")
                return
            try:
                fn(*args)
            finally:
                self._lock.release()

        threading.Thread(target=_run, daemon=True).start()

    def _on_wake_word(self) -> None:
        self._dispatch(self._handle_activation)

    def _on_voice_command(self, user_text: str) -> None:
        if self._wake_listener:
            self._wake_listener.pause()

        def _run() -> None:
            if not self._lock.acquire(blocking=False):
                self.logger.warn("Ocupado — repita en un momento")
                return
            try:
                self._process_command(user_text)
            finally:
                self._lock.release()
                if self._wake_listener:
                    self._wake_listener.resume()

        threading.Thread(target=_run, daemon=True).start()

    def _clean_command(self, user_text: str) -> str:
        normalized = preprocess_command_text(user_text)
        cleaned = self._wake_prefix.sub("", normalized.strip())
        return cleaned.strip()

    def _try_light_command(self, cleaned: str) -> tuple[str, tuple[int, int, int]] | None:
        return parse_light_command(cleaned)

    def _execute_light(self, color_name: str, light_color: tuple[int, int, int]) -> None:
        threading.Thread(
            target=self._set_color,
            args=(light_color,),
            daemon=True,
        ).start()
        self._speak(f"Luces en {color_name}.")

    def _enter_sleep_mode(self, farewell: str | None = None) -> None:
        """Reposo — solo «hey lizzy» reactiva (no cierra la app)."""
        self._armed = False
        self._conversation_until = 0.0
        name = self.cfg.assistant_name
        self.logger.info(f"Modo reposo — solo «hey {name.lower()}» reactiva")
        msg = farewell or f"En reposo. Diga hey {name} cuando me necesite, señor."
        self._speak(msg)
        self._set_leds(LedState.SLEEP)

    def _process_command(self, user_text: str) -> None:
        try:
            cleaned = self._clean_command(user_text)
            self.logger.info(f"Comando: {cleaned or user_text[:80]}")

            if is_shutdown_command(cleaned or user_text):
                self._enter_sleep_mode(
                    f"Entendido. Dejo de escuchar. Diga hey {self.cfg.assistant_name} cuando me necesite."
                )
                return

            self._extend_conversation()

            if not cleaned:
                self._speak("Proceda, señor.")
                return

            light = self._try_light_command(cleaned)
            if light:
                color_name, light_color = light
                self._execute_light(color_name, light_color)
                return

            time_reply = answer_time_query(cleaned, self.cfg.user_name)
            if time_reply:
                self._speak(time_reply)
                return

            if is_daily_conclusion_query(cleaned):
                self._speak(answer_daily_conclusion(), dramatic=True)
                return

            self._set_leds(LedState.PROCESSING)

            if self.cfg.cursor_agent_enabled:
                dev_reply = try_handle_dev_command(
                    cleaned,
                    self.cfg.dev_workspace,
                    self.logger,
                    user_name=self.cfg.user_name,
                )
                if dev_reply:
                    self._speak(dev_reply)
                    return

            reply = self.brain.think(
                cleaned,
                self._context_cache,
                capabilities=self._capabilities,
                dev_workspace=str(self.cfg.dev_workspace),
                live_context=build_live_context(),
            )

            # Si el LLM confirma un color, ejecutarlo en las Lepro
            light_after = self._try_light_command(preprocess_command_text(reply))
            if light_after:
                color_name, light_color = light_after
                threading.Thread(
                    target=self._set_color,
                    args=(light_color,),
                    daemon=True,
                ).start()

            self._speak(reply)

        except Exception as exc:
            self.logger.error(f"Error en ciclo de activación: {exc}")
            self._set_leds(LedState.ERROR)
            self._speak("Algo ha fallado. Consulte el registro del sistema.")
        finally:
            self._idle_leds()

    def _handle_activation(self) -> None:
        try:
            self.logger.info("Activación detectada")
            if self._wake_listener:
                self._wake_listener.pause()
            self._set_leds(LedState.ACTIVATED)
            self.player.play_activation(self.cfg.activate_sound)

            audio = self.recorder.record_until_silence(self.cfg.listen_timeout_s)
            user_text = self.stt.transcribe(audio, self.cfg.sample_rate)
            if not user_text:
                self._set_leds(LedState.ERROR)
                self._speak("No he captado su voz. Repita cuando desee.")
                return
            self._process_command(user_text)
        except Exception as exc:
            self.logger.error(f"Error en activación: {exc}")
            self._set_leds(LedState.ERROR)
            self._speak("Algo ha fallado. Consulte el registro del sistema.")
        finally:
            if self._wake_listener:
                self._wake_listener.resume()

    def _check_microphone(self) -> bool:
        """Detecta micrófono bloqueado por macOS (silencio total)."""
        _ok, peak, _rms = probe_microphone(
            device=self.cfg.audio_input_device,
            capture_rate=self.cfg.capture_rate,
            channels=self.cfg.channels,
            logger=self.logger,
            seconds=1.0,
            min_peak=0.001,
            prompt=False,
        )
        if peak >= 0.001:
            return True
        permission_hint(self.logger)
        self._speak(
            "Señor, el micrófono no responde. "
            "Abra LIZZY punto app desde el Escritorio, no desde Cursor, "
            "y conceda el permiso en Privacidad."
        )
        return False

    def _startup_greeting(self) -> None:
        msg = (
            f"Buenas, señor {self.cfg.user_name}. "
            f"Soy {self.cfg.assistant_name}. Sistemas en línea. A sus órdenes."
        )
        self._speak(msg)

    def _require_app_launch(self) -> None:
        """En macOS, el mic solo funciona si arrancas LIZZY.app (no Cursor)."""
        import os
        import subprocess

        if sys.platform != "darwin":
            return
        if launched_from_app():
            self.logger.info("Arrancado desde LIZZY.app")
            return
        if os.getenv("LIZZY_ALLOW_CURSOR") == "1" or os.getenv("JARVIS_ALLOW_CURSOR") == "1":
            self.logger.warn("Modo dev — micrófono depende de Cursor (no recomendado)")
            return

        msg = (
            f"{self.cfg.assistant_name} no puede usar el micrófono desde Cursor. "
            "Cierra esto y abre LIZZY.app desde el Escritorio (doble clic)."
        )
        self.logger.error(msg)
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display dialog "{msg}" buttons {{"OK"}} default button 1 '
                f'with title "{self.cfg.assistant_name} — micrófono"',
            ],
            check=False,
        )
        sys.exit(1)

    def run(self) -> None:
        self._require_app_launch()
        self.logger.info(f"{self.cfg.assistant_name} iniciada")
        notify_assistant_started(self.cfg.assistant_name)
        request_microphone_access(self.logger)

        if isinstance(self.leds, LeproMqttController):
            if not self.leds.connect():
                self.logger.warn("Lepro no disponible — LEDs en modo local/mock")
        self._set_leds(LedState.STANDBY)

        use_whisper = self.cfg.wake_backend == "whisper"
        self._wake_listener = create_wake_listener(
            self.cfg.wake_backend,
            sample_rate=self.cfg.sample_rate,
            logger=self.logger,
            on_detected=self._on_wake_word,
            on_command=self._on_voice_command if use_whisper else None,
            on_phrase_captured=self._on_phrase_captured if use_whisper else None,
            on_speech_started=self._on_speech_started if use_whisper else None,
            is_conversation_active=self._in_conversation if use_whisper else None,
            on_wake_detected=self._on_wake_detected if use_whisper else None,
            is_armed=lambda: self._armed if use_whisper else True,
            silence_duration_s=self.cfg.silence_duration_s,
            max_phrase_s=self.cfg.max_phrase_s,
            wake_name=self.cfg.assistant_name,
            recorder=self.recorder if use_whisper else None,
            stt=self.stt if use_whisper else None,
            wake_stt=self.wake_stt if use_whisper else None,
            listen_timeout_s=60.0,
            picovoice_access_key=self.cfg.picovoice_access_key,
            wake_word=self.cfg.wake_word,
            oww_model=self.cfg.oww_model,
            oww_threshold=self.cfg.oww_threshold,
        )

        self._startup_greeting()

        if not validate_input_device(
            device=self.cfg.audio_input_device,
            capture_rate=self.cfg.capture_rate,
            channels=self.cfg.channels,
            logger=self.logger,
        ):
            self._speak(
                f"Señor, no puedo abrir el micrófono. "
                f"Compruebe la entrada de audio y reinicie {self.cfg.assistant_name}."
            )
            self.logger.error(f"{self.cfg.assistant_name} sin escucha — micrófono inaccesible")
            return

        if not self._check_microphone():
            self.logger.warn("Micrófono abierto pero sin señal — compruebe permisos TCC")
        self._wake_listener.start()

        def shutdown(_signum, _frame) -> None:
            self.logger.info("Apagando Lizzy")
            self._running = False
            if self._wake_listener:
                self._wake_listener.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        self.logger.info("En standby.")
        try:
            while self._running:
                signal.pause()
        except (AttributeError, OSError):
            import time

            while self._running:
                time.sleep(1)


def main() -> None:
    Lizzy().run()


if __name__ == "__main__":
    main()
