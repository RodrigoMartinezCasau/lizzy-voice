"""Configuración central de Lizzy."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from jarvis.audio.devices import (
    resolve_input_settings,
    resolve_output_device,
)

ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _project_root() -> Path:
    """Carpeta que Lizzy puede leer como contexto y usar de workspace.

    Se resuelve en cada instanciación porque el .env se carga después de
    importar este módulo. Sin JARVIS_CONTEXT_DIR caería en el home del
    usuario, así que la variable es obligatoria fuera de un repo.
    """
    raw = _env("JARVIS_CONTEXT_DIR")
    return Path(raw).expanduser().resolve() if raw else ROOT.parent


def _optional_int(key: str) -> int | None:
    raw = _env(key).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Config:
    root: Path = ROOT
    project_root: Path = field(default_factory=_project_root)
    context_dir: Path = field(default_factory=_project_root)
    logs_dir: Path = field(default_factory=lambda: ROOT / "logs")
    assets_dir: Path = field(default_factory=lambda: ROOT / "assets")
    log_file: Path = field(default_factory=lambda: ROOT / "logs" / "jarvis_log.txt")
    activate_sound: Path = field(default_factory=lambda: ROOT / "assets" / "activate.mp3")

    # Wake word — whisper (default, fiable) | openwakeword | porcupine
    wake_backend: str = field(default_factory=lambda: _env("WAKE_BACKEND", "whisper"))
    picovoice_access_key: str = field(default_factory=lambda: _env("PICOVOICE_ACCESS_KEY"))
    wake_word: str = field(default_factory=lambda: _env("WAKE_WORD", "lizzy"))
    assistant_name: str = field(default_factory=lambda: _env("ASSISTANT_NAME", "Lizzy"))
    oww_model: str = field(default_factory=lambda: _env("OWW_MODEL", "hey_lizzy"))
    oww_threshold: float = field(default_factory=lambda: float(_env("OWW_THRESHOLD", "0.5")))
    listen_timeout_s: float = 10.0
    silence_duration_s: float = field(
        default_factory=lambda: float(_env("JARVIS_SILENCE_DURATION_S", "0.9"))
    )
    max_phrase_s: float = field(
        default_factory=lambda: float(_env("JARVIS_MAX_PHRASE_S", "4.0"))
    )
    conversation_window_s: float = field(
        default_factory=lambda: float(_env("JARVIS_CONVERSATION_WINDOW_S", "15"))
    )
    context_max_chars: int = field(
        default_factory=lambda: int(_env("JARVIS_CONTEXT_MAX_CHARS", "96000"))
    )

    # Audio
    sample_rate: int = 16_000
    capture_rate: int = field(default_factory=lambda: int(_env("AUDIO_CAPTURE_RATE", "0")))
    channels: int = field(default_factory=lambda: int(_env("AUDIO_INPUT_CHANNELS", "0")))
    audio_input_device: int | None = field(
        default_factory=lambda: _optional_int("AUDIO_INPUT_DEVICE")
    )
    audio_input_device_name: str = field(
        default_factory=lambda: _env("AUDIO_INPUT_DEVICE_NAME")
    )
    audio_output_device: int | None = field(
        default_factory=lambda: _optional_int("AUDIO_OUTPUT_DEVICE")
    )
    audio_output_device_name: str = field(
        default_factory=lambda: _env("AUDIO_OUTPUT_DEVICE_NAME", "Pebble V3")
    )
    record_seconds_max: float = 12.0

    # STT
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    wake_whisper_model: str = field(default_factory=lambda: _env("WAKE_WHISPER_MODEL", "tiny"))
    whisper_language: str = "es"

    # Cursor Agent (auto-edición / repos)
    cursor_agent_enabled: bool = field(
        default_factory=lambda: _env("CURSOR_AGENT_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    dev_workspace: Path = field(
        default_factory=lambda: Path(
            _env("JARVIS_DEV_WORKSPACE") or str(_project_root())
        ).expanduser()
    )

    # TTS — voz femenina española
    tts_voice: str = field(
        default_factory=lambda: _env("TTS_VOICE", "es-ES-ElviraNeural")
    )
    tts_rate: str = field(default_factory=lambda: _env("TTS_RATE", "-8%"))
    tts_pitch: str = field(default_factory=lambda: _env("TTS_PITCH", "+2Hz"))
    tts_volume: str = field(default_factory=lambda: _env("TTS_VOLUME", "-6%"))

    # LLM
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("JARVIS_LLM_MODEL", "claude-sonnet-4-6"))
    max_response_tokens: int = 300

    # LEDs — mock (sin hardware) | lepro_cloud | wled
    leds_backend: str = field(default_factory=lambda: _env("LEDS_BACKEND", "mock"))
    wled_host: str = field(default_factory=lambda: _env("WLED_HOST", "YOUR_LAN_HOST"))
    light_account: str = field(default_factory=lambda: _env("LIGHT_ACCOUNT"))
    light_token: str = field(default_factory=lambda: _env("LIGHT_TOKEN"))
    lepro_region: str = field(default_factory=lambda: _env("LEPRO_REGION", "eu"))
    light_device: str = field(default_factory=lambda: _env("LIGHT_DEVICE"))

    user_name: str = field(default_factory=lambda: _env("JARVIS_USER_NAME", "Evo"))


def load_config() -> Config:
    cfg = Config()
    in_dev, in_ch, in_rate, _label = resolve_input_settings(
        cfg.audio_input_device,
        cfg.audio_input_device_name or None,
        cfg.capture_rate,
        cfg.channels,
    )
    cfg = replace(
        cfg,
        audio_input_device=in_dev,
        channels=in_ch,
        capture_rate=in_rate,
    )
    resolved_out = resolve_output_device(
        cfg.audio_output_device,
        cfg.audio_output_device_name or None,
    )
    if resolved_out != cfg.audio_output_device:
        cfg = replace(cfg, audio_output_device=resolved_out)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    return cfg
