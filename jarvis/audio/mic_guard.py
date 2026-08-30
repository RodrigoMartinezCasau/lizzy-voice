"""Comprueba que el micrófono captura señal real (permisos macOS)."""

from __future__ import annotations

import time

import numpy as np
import sounddevice as sd

from jarvis.logger import JarvisLogger


def validate_input_device(
    *,
    device: int | None,
    capture_rate: int,
    channels: int,
    logger: JarvisLogger,
) -> bool:
    """Comprueba que el stream de entrada se puede abrir (dispositivo correcto)."""
    try:
        with sd.InputStream(
            samplerate=capture_rate,
            channels=channels,
            dtype="float32",
            device=device,
            blocksize=max(1, int(capture_rate * 0.08)),
        ):
            pass
    except Exception as exc:
        label = device
        try:
            if device is not None:
                label = f"[{device}] {sd.query_devices(device)['name']}"
        except Exception:
            pass
        logger.error(f"No puedo abrir el micrófono {label}: {exc}")
        return False

    name = (
        sd.query_devices(device)["name"]
        if device is not None
        else sd.query_devices(kind="input")["name"]
    )
    logger.info(f"Micrófono listo → [{device}] {name}")
    return True


def probe_microphone(
    *,
    device: int | None,
    capture_rate: int,
    channels: int,
    logger: JarvisLogger,
    seconds: float = 2.5,
    min_peak: float = 0.025,
    prompt: bool = True,
) -> tuple[bool, float, float]:
    """Graba unos segundos y mide pico/RMS. Devuelve (ok, peak, rms)."""
    block = max(1, int(capture_rate * 0.08))
    chunks: list[np.ndarray] = []
    deadline = time.monotonic() + seconds

    try:
        with sd.InputStream(
            samplerate=capture_rate,
            channels=channels,
            dtype="float32",
            device=device,
            blocksize=block,
        ) as stream:
            logger.info(
                f"Calibrando micrófono ({seconds:.0f}s) — habla ahora..."
                if prompt
                else f"Comprobando micrófono ({seconds:.0f}s)…"
            )
            while time.monotonic() < deadline:
                data, _overflowed = stream.read(block)
                chunks.append(data.copy())
    except Exception as exc:
        logger.error(f"Micrófono inaccesible: {exc}")
        return False, 0.0, 0.0

    if not chunks:
        return False, 0.0, 0.0

    audio = np.concatenate(chunks, axis=0)
    mono = audio[:, 0] if audio.ndim > 1 else audio
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    ok = peak >= min_peak
    logger.info(f"Micrófono peak={peak:.4f} rms={rms:.4f} device={device}")
    return ok, peak, rms
