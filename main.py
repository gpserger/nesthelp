"""NESTHELP — voice-controlled fire direction board for IRON NEST.

    ./run.sh                 # normal use (mic listening + board)
    ./run.sh --debug         # also print everything heard/parsed
    ./run.sh --stdin         # type commands instead of speaking (testing)
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import tomllib
import urllib.request
import zipfile

import uvicorn

from chimes import Chimes
from controller import Controller
from parser import vocabulary
from server import create_app
from speech import SpeechThread, StdinThread

HERE = pathlib.Path(__file__).parent
MODEL_URL = ("https://alphacephei.com/vosk/models/"
             "vosk-model-small-en-us-0.15.zip")


def ensure_model(model_dir: pathlib.Path) -> None:
    if model_dir.is_dir():
        return
    models = model_dir.parent
    models.mkdir(parents=True, exist_ok=True)
    print(f"Downloading speech model (~40 MB, one-time): {MODEL_URL}")
    zip_path = models / "model.zip"
    try:
        urllib.request.urlretrieve(MODEL_URL, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(models)
    finally:
        zip_path.unlink(missing_ok=True)
    if not model_dir.is_dir():
        sys.exit(f"model download did not produce {model_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(HERE / "config.toml"))
    ap.add_argument("--stdin", action="store_true",
                    help="read commands from stdin instead of the microphone")
    ap.add_argument("--debug", action="store_true",
                    help="print recognized text and parse results")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    host = args.host or cfg.get("server", {}).get("host", "127.0.0.1")
    port = args.port or cfg.get("server", {}).get("port", 8737)

    controller = Controller(cfg, Chimes(HERE / "sounds"), debug=args.debug)

    if args.stdin:
        thread = StdinThread(controller.on_text)
    else:
        model_dir = HERE / cfg.get("speech", {}).get(
            "model_dir", "models/vosk-model-small-en-us-0.15")
        ensure_model(model_dir)
        thread = SpeechThread(str(model_dir), vocabulary(controller.alias_map),
                              controller.on_text,
                              sample_rate=cfg.get("speech", {}).get("sample_rate", 16000),
                              debug=args.debug)

    app = create_app(controller, thread.start,
                     getattr(thread, "stop", lambda: None))
    print(f"NESTHELP board: http://{host}:{port}  "
          f"(open fullscreen on your second monitor)")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
