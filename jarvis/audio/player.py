"""Reproducción de audio en el altavoz configurado."""

from __future__ import annotations

import re
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from jarvis.logger import JarvisLogger


class AudioPlayer:
    def __init__(
        self,
        logger: JarvisLogger,
        *,
        output_device: int | None = None,
    ) -> None:
        self.logger = logger
        self.output_device = output_device

    @staticmethod
    def get_duration(path: Path) -> float:
        if not path.exists():
            return 0.0
        try:
            out = subprocess.run(
                ["afinfo", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            match = re.search(r"estimated duration:\s*([\d.]+)\s*sec", out.stdout)
            if match:
                return float(match.group(1))
        except OSError:
            pass
        return 0.0

    def _play_to_device(self, path: Path) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            result = subprocess.run(
                [
                    "afconvert",
                    "-f",
                    "WAVE",
                    "-d",
                    "LEI16@44100",
                    str(path),
                    str(wav_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "afconvert falló")

            with wave.open(str(wav_path)) as handle:
                sample_rate = handle.getframerate()
                channels = handle.getnchannels()
                frames = handle.readframes(handle.getnframes())

            data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            if channels > 1:
                data = data.reshape(-1, channels)

            sd.play(data, sample_rate, device=self.output_device)
            sd.wait()
        finally:
            wav_path.unlink(missing_ok=True)

    def play(self, path: Path) -> None:
        if not path.exists():
            self.logger.warn(f"Archivo de audio no encontrado: {path}")
            return
        self.logger.info(
            f"Reproduciendo: {path.name} (dev={self.output_device})"
        )
        try:
            if self.output_device is not None:
                self._play_to_device(path)
            else:
                subprocess.run(["afplay", str(path)], check=False)
        except Exception as exc:
            self.logger.error(f"Error reproduciendo audio: {exc}")
            subprocess.run(["afplay", str(path)], check=False)

    def play_activation(self, path: Path) -> None:
        """Tonito corto — afplay no bloquea la captura del micrófono."""
        if not path.exists():
            self.logger.warn("activate.mp3 no encontrado — omitiendo tono")
            return
        self.logger.info(f"Reproduciendo: {path.name} (afplay)")
        subprocess.run(["afplay", str(path)], check=False)
