"""Resolución de dispositivos de audio — evita índices rotos al cambiar hardware."""

from __future__ import annotations

import sounddevice as sd

from jarvis.logger import JarvisLogger


def list_input_devices() -> list[tuple[int, str, int]]:
    """Devuelve [(índice, nombre, canales_entrada), ...]."""
    out: list[tuple[int, str, int]] = []
    for i, dev in enumerate(sd.query_devices()):
        ch = int(dev["max_input_channels"])
        if ch > 0:
            out.append((i, str(dev["name"]).strip(), ch))
    return out


def list_output_devices() -> list[tuple[int, str, int]]:
    """Devuelve [(índice, nombre, canales_salida), ...]."""
    out: list[tuple[int, str, int]] = []
    for i, dev in enumerate(sd.query_devices()):
        ch = int(dev["max_output_channels"])
        if ch > 0:
            out.append((i, str(dev["name"]).strip(), ch))
    return out


def _input_device_info(index: int | None) -> dict:
    if index is None:
        idx = int(sd.default.device[0])
    else:
        idx = index
    return dict(sd.query_devices(idx))


def _find_input_by_name(name: str) -> tuple[int, dict] | None:
    needle = name.strip().lower()
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] <= 0:
            continue
        label = str(dev["name"]).strip()
        if needle in label.lower():
            return i, dict(dev)
    return None


def resolve_input_settings(
    device_index: int | None,
    device_name: str | None,
    capture_rate: int,
    channels: int,
    logger: JarvisLogger | None = None,
) -> tuple[int | None, int, int, str]:
    """
    Resuelve micrófono para captura.

    Devuelve (device_id, channels, sample_rate, label).
    Si el micrófono elegido es el default del sistema, device_id=None (más fiable en macOS/TCC).
    """
    default_idx = int(sd.default.device[0])
    default_dev = dict(sd.query_devices(default_idx))
    picked_idx: int | None = None
    picked_dev: dict | None = None

    if device_name:
        found = _find_input_by_name(device_name)
        if found:
            picked_idx, picked_dev = found
        elif logger:
            logger.warn(
                f"No encuentro micrófono «{device_name}» — uso entrada por defecto del Mac"
            )

    if picked_idx is None and device_index is not None:
        try:
            dev = sd.query_devices(device_index)
            if dev["max_input_channels"] > 0:
                picked_idx, picked_dev = device_index, dict(dev)
            elif logger:
                logger.warn(
                    f"AUDIO_INPUT_DEVICE={device_index} ({dev['name']}) "
                    "no tiene entrada — uso default del Mac"
                )
        except Exception:
            if logger:
                logger.warn(f"AUDIO_INPUT_DEVICE={device_index} no existe — uso default")

    if picked_idx is None:
        picked_idx, picked_dev = default_idx, default_dev

    label = str(picked_dev["name"]).strip()
    use_default = picked_idx == default_idx
    device_id: int | None = None if use_default else picked_idx

    max_ch = int(picked_dev["max_input_channels"])
    resolved_channels = channels if channels > 0 else min(max_ch, 2)
    if resolved_channels > max_ch:
        resolved_channels = max_ch
    if resolved_channels < 1:
        resolved_channels = 1

    native_rate = int(float(picked_dev["default_samplerate"]))
    resolved_rate = capture_rate if capture_rate > 0 else native_rate
    if abs(resolved_rate - native_rate) > 1000:
        if logger:
            logger.info(
                f"Micrófono nativo {native_rate} Hz — captura a {resolved_rate} Hz"
            )

    if logger:
        where = "default del Mac" if device_id is None else f"índice {device_id}"
        logger.info(
            f"Entrada de audio → {label} ({where}, "
            f"{resolved_rate} Hz, {resolved_channels} ch)"
        )

    return device_id, resolved_channels, resolved_rate, label


def resolve_input_device(
    device_index: int | None,
    device_name: str | None,
    logger: JarvisLogger | None = None,
) -> int | None:
    """Compat: solo devuelve el índice (None = default del sistema)."""
    device_id, _ch, _rate, _label = resolve_input_settings(
        device_index, device_name, 48000, 1, logger
    )
    return device_id


def _resolve_device(
    *,
    device_index: int | None,
    device_name: str | None,
    channel_key: str,
    default_index: int | None,
    env_key: str,
    label: str,
    logger: JarvisLogger | None,
) -> int | None:
    devices = sd.query_devices()

    if device_name:
        needle = device_name.strip().lower()
        for i, dev in enumerate(devices):
            if dev[channel_key] <= 0:
                continue
            name = str(dev["name"]).strip()
            if needle in name.lower():
                if logger:
                    logger.info(f"{label} «{device_name}» → [{i}] {name}")
                return i
        if logger:
            logger.warn(
                f"No encuentro {label.lower()} «{device_name}» — probando índice o default"
            )

    if device_index is not None:
        try:
            dev = devices[device_index]
        except IndexError:
            if logger:
                logger.warn(f"{env_key}={device_index} no existe — usando default")
        else:
            if dev[channel_key] > 0:
                if logger:
                    logger.info(f"{label} índice {device_index} → {dev['name']}")
                return device_index
            if logger:
                logger.warn(
                    f"{env_key}={device_index} ({dev['name']}) "
                    f"no tiene salida — usando default"
                    if channel_key == "max_output_channels"
                    else f"{env_key}={device_index} ({dev['name']}) "
                    "no tiene entrada — usando default"
                )

    if default_index is not None and int(default_index) >= 0:
        dev = devices[int(default_index)]
        if dev[channel_key] > 0:
            if logger:
                logger.info(
                    f"{label} default → [{default_index}] {dev['name']}"
                )
            return int(default_index)

    if logger:
        logger.error(f"No hay ningún dispositivo de {label.lower()} disponible")
    return None


def resolve_output_device(
    device_index: int | None,
    device_name: str | None,
    logger: JarvisLogger | None = None,
) -> int | None:
    """Elige altavoz: nombre > índice válido > default del sistema."""
    return _resolve_device(
        device_index=device_index,
        device_name=device_name,
        channel_key="max_output_channels",
        default_index=sd.default.device[1],
        env_key="AUDIO_OUTPUT_DEVICE",
        label="Altavoz",
        logger=logger,
    )
