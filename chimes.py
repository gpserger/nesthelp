"""Accept/error chimes, generated once and played fire-and-forget.

Uses paplay/pw-play/aplay on Linux, winsound on Windows, afplay on macOS, so
there is no audio library dependency; playback failures are silent (the board
still shows the result).
"""
from __future__ import annotations

import math
import pathlib
import shutil
import struct
import subprocess
import sys
import wave

_RATE = 44100


def _tone(freq: float, ms: int, vol: float = 0.35) -> bytes:
    n = int(_RATE * ms / 1000)
    attack, release = int(_RATE * 0.005), int(_RATE * 0.025)
    out = bytearray()
    for i in range(n):
        env = min(1.0, i / attack, (n - i) / release)
        v = vol * env * math.sin(2 * math.pi * freq * i / _RATE)
        out += struct.pack("<h", int(v * 32767))
    return bytes(out)


def _silence(ms: int) -> bytes:
    return b"\x00\x00" * int(_RATE * ms / 1000)


class Chimes:
    def __init__(self, sound_dir: str | pathlib.Path = "sounds"):
        self.dir = pathlib.Path(sound_dir)
        self.dir.mkdir(exist_ok=True)
        self._write("accept.wav", _tone(660, 90) + _tone(990, 130))
        self._write("error.wav", _tone(220, 160) + _silence(50) + _tone(220, 160))
        self.player = next(
            (p for p in (["paplay"], ["pw-play"], ["aplay", "-q"], ["afplay"])
             if shutil.which(p[0])), None)

    def _write(self, name: str, pcm: bytes) -> None:
        path = self.dir / name
        if path.exists():
            return
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(_RATE)
            w.writeframes(pcm)

    def _play(self, name: str) -> None:
        path = str(self.dir / name)
        if sys.platform == "win32":
            import winsound
            try:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except RuntimeError:
                pass
            return
        if not self.player:
            return
        try:
            subprocess.Popen(self.player + [path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def accept(self) -> None:
        self._play("accept.wav")

    def error(self) -> None:
        self._play("error.wav")
