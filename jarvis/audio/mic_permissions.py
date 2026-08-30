"""Solicitud explícita de permiso de micrófono en macOS (AVFoundation)."""

from __future__ import annotations

import os
import sys
import threading

from jarvis.logger import JarvisLogger


def launched_from_app() -> bool:
    return (
        os.getenv("LIZZY_LAUNCHED_FROM_APP") == "1"
        or os.getenv("JARVIS_LAUNCHED_FROM_APP") == "1"
    )


def request_microphone_access(logger: JarvisLogger | None = None) -> bool:
    """Pide permiso de micrófono al proceso Python (necesario para sounddevice)."""
    if sys.platform != "darwin":
        return True

    try:
        import AVFoundation
    except ImportError:
        if logger:
            logger.warn("PyObjC AVFoundation no instalado")
        return False

    granted_flag = {"ok": False}
    done = threading.Event()

    def _callback(granted: bool) -> None:
        granted_flag["ok"] = bool(granted)
        done.set()

    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AVFoundation.AVMediaTypeAudio,
        _callback,
    )

    if not done.wait(timeout=30.0):
        if logger:
            logger.warn("Timeout esperando permiso de micrófono")
        return False

    if logger:
        src = "LIZZY.app" if launched_from_app() else "proceso Python"
        logger.info(
            f"Permiso micrófono ({src}): "
            f"{'concedido' if granted_flag['ok'] else 'denegado'}"
        )
    return granted_flag["ok"]


def notify_assistant_started(assistant_name: str = "Lizzy") -> None:
    """Aviso visible (solo si no arrancó desde la app, que ya notifica)."""
    if sys.platform != "darwin" or launched_from_app():
        return
    import subprocess

    wake = assistant_name.lower()
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "Escuchando «hey {wake}»" '
            f'with title "{assistant_name} activa"',
        ],
        check=False,
    )


def notify_jarvis_started() -> None:
    """Compat — usar notify_assistant_started."""
    notify_assistant_started("Lizzy")


def permission_hint(logger: JarvisLogger) -> None:
    logger.warn(
        "Micrófono bloqueado fuera de Cursor. "
        "Abre LIZZY.app desde Finder (Escritorio) y acepta el permiso de micrófono. "
        "No uses ./run.sh en la terminal de Cursor para uso 24/7."
    )
