# NESTHELP

Voice-controlled fire direction board for the game IRON NEST: Heavy Turret
Simulator. Local speech recognition (Vosk) → command parser → ballistics →
WebSocket target board on a second monitor.

## Commands

```sh
uv run main.py              # run (first run downloads the ~40 MB Vosk model)
uv run main.py --stdin      # type commands instead of speaking — use this for testing
uv run main.py --debug      # print everything heard and how it parsed
uv run test_core.py         # ballistics + parser tests; no mic, model, or server needed
```

Dependencies live in `pyproject.toml`; keep `requirements.txt` in sync (pip
fallback). `[tool.uv] package = false` — flat modules, nothing is installed.

## Architecture

Single process, three threads: an input thread (`speech.py` mic → Vosk, or
stdin) calls `Controller.on_text`, which hops onto the asyncio event loop via
`call_soon_threadsafe` — **all state mutation happens on the loop, there are
no locks; keep it that way**. `controller.py` holds board state and pushes
full snapshots to per-websocket queues; `static/index.html` renders them.
`parser.py` turns token lists into command dataclasses; `ballistics.py` is
pure math.

## Domain rules (deliberate, verified in-game — don't "fix")

- Elevation formula: `elevation° = 12 × distance_km ÷ charges`, max 60°,
  charges 1–6, so max range = 5 km × charges. Constants in `config.toml`.
- Dictation packs decimals into the last digits: bearing `nine six six`
  = 96.6° (digits ÷ 10), distance `five eight four` = 5.84 km (digits ÷ 100).
  Distance is dictated in km but stored in **meters** (`distance_m`).
- Bearings ≥ 360° are **rejected, never wrapped** — a mod-360 wrap once
  laundered a misheard 966 into a plausible-looking 246° shot.
- Auto charge selection picks the **most** charges that reach: lower
  elevation = faster return to horizontal = faster reload.
- `reverse` flips a bearing 180° (map line drawn target→gun). It is an
  action, not a stored property: applying it twice restores the original.
- `UNSET` sentinel in `parser.py` distinguishes "shell not mentioned" (keep
  current/default) from explicit `shell none` (clear it).

## Gotchas

- The Vosk grammar is closed: any new spoken alias in `config.toml` must be
  a word the small-en model knows, or it is silently unrecognizable. That is
  why FLCH's alias is "fletcher", not "flechette". Verify with a
  `KaldiRecognizer(model, rate, json.dumps(vocab))` smoke test — it logs
  "Ignoring word missing in vocabulary" warnings.
- `test_core.py` is plain asserts run as a script (no pytest).
- Mic capture: Linux uses a `pw-record`/`parec` subprocess; Windows/macOS use
  `sounddevice` (conditional dependency). The Windows path is untested on
  real hardware.
- Elevation tolerance window = `±12·(blast_diameter/2)·margin/charges`
  degrees; blast diameters in `config.toml` are rough by-eye measurements.
