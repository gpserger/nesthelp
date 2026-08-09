"""Always-on microphone listener feeding Vosk.

Capture backend is chosen per platform: on Linux a pw-record/parec subprocess
(no audio C libraries needed), elsewhere the sounddevice (PortAudio) library.
Recognition is grammar-constrained to the command vocabulary plus [unk],
which keeps digit accuracy high and absorbs ordinary speech; utterances that
don't start with a command word are ignored upstream.
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import threading


def _subprocess_command(rate: int) -> list[str] | None:
    if shutil.which("pw-record"):
        return ["pw-record", "--rate", str(rate), "--channels", "1",
                "--format", "s16", "-"]
    if shutil.which("parec"):
        return ["parec", f"--rate={rate}", "--channels=1", "--format=s16le"]
    return None


class SpeechThread(threading.Thread):
    def __init__(self, model_dir: str, vocab: list[str], on_text,
                 sample_rate: int = 16000, debug: bool = False):
        super().__init__(daemon=True, name="speech")
        self.model_dir = model_dir
        self.vocab = vocab
        self.on_text = on_text
        self.rate = sample_rate
        self.debug = debug
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None

    def _make_recognizer(self):
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        return KaldiRecognizer(Model(self.model_dir), self.rate,
                               json.dumps(self.vocab + ["[unk]"]))

    def _feed(self, rec, data: bytes) -> None:
        if rec.AcceptWaveform(data):
            text = json.loads(rec.Result()).get("text", "").strip()
            if text:
                if self.debug:
                    print(f"[heard] {text}", file=sys.stderr)
                self.on_text(text)

    def run(self) -> None:
        rec = self._make_recognizer()
        cmd = _subprocess_command(self.rate)
        print("listening on the default microphone", file=sys.stderr)
        if cmd:
            self._run_subprocess(rec, cmd)
        else:
            self._run_sounddevice(rec)

    def _run_subprocess(self, rec, cmd: list[str]) -> None:
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL)
        while not self._stop.is_set():
            data = self._proc.stdout.read(4000)
            if not data:
                break
            self._feed(rec, data)

    def _run_sounddevice(self, rec) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            print("no pw-record/parec found and sounddevice is not installed;"
                  " cannot capture the microphone", file=sys.stderr)
            return
        buf: queue.Queue[bytes] = queue.Queue()

        def callback(indata, frames, time_info, status):
            buf.put(bytes(indata))

        with sd.RawInputStream(samplerate=self.rate, blocksize=4000,
                               dtype="int16", channels=1, callback=callback):
            while not self._stop.is_set():
                try:
                    self._feed(rec, buf.get(timeout=0.5))
                except queue.Empty:
                    continue

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()


class StdinThread(threading.Thread):
    """Test mode: type commands instead of speaking them."""

    def __init__(self, on_text):
        super().__init__(daemon=True, name="stdin")
        self.on_text = on_text

    def run(self) -> None:
        for line in sys.stdin:
            line = line.strip().lower()
            if line:
                self.on_text(line)
