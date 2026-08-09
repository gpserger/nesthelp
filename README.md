# NESTHELP

A voice-controlled fire direction board for **[IRON NEST: Heavy Turret
Simulator](https://store.steampowered.com/app/2950790/)**.

Call out fire missions by voice while you play. NESTHELP listens on your
microphone, does the ballistics, and keeps a target board on your second
monitor — bearing, distance, charges, and the elevation to dial into the gun.
No more spinning the calculator wheel for every shot.

```
"fire mission — bearing nine six six — distance five eight four"
```

…and the board shows target 1: **096.6°, 5.84 km, 6 charges, elevation 11.68°**.

- **Fully offline.** Speech recognition is local ([Vosk](https://alphacephei.com/vosk/)),
  constrained to a ~60-word grammar so digits are recognized reliably and
  normal talking is ignored. Nothing leaves your machine.
- **Charge-aware.** Automatically picks the most charges that reach, keeping
  elevation low so the gun gets back to horizontal (and reloaded) faster.
  Override per target or per session by voice.
- **Elevation windows.** Tell it the shell type and it shows the elevation
  interval that still lands the blast on the aim point — eyeball the wheel
  into the window instead of fine-tuning to two decimals.
- **Fixable.** Mishears and updates are edited by voice: change any field of
  an existing target, flip a bearing 180°, strike out destroyed targets.

The board shows a phrase reference whenever you have room, so you never have
to memorize the grammar.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
git clone https://github.com/gpserger/nesthelp
cd nesthelp
uv run main.py
```

That's it — uv creates the environment, and the first run downloads the
~40 MB speech model. Open the printed URL (default `http://127.0.0.1:8737`)
fullscreen on your second monitor.

Prefer pip? `python -m venv .venv`, activate it,
`pip install -r requirements.txt`, `python main.py`. Linux users can also
just run `./run.sh` (uses uv when available, falls back to venv + pip).

Useful flags: `--debug` prints everything heard and how it parsed;
`--stdin` lets you type commands instead of speaking (great for trying the
grammar without a mic).

### Platform notes

| | Mic capture | Chimes |
| --- | --- | --- |
| **Linux** | PipeWire `pw-record` or PulseAudio `parec` (stock on Fedora/Ubuntu) | `paplay`/`pw-play`/`aplay` |
| **Windows** | PortAudio via the `sounddevice` package (installed automatically) | `winsound` (built in) |
| **macOS** | `sounddevice` (may prompt for mic permission) | `afplay` |

Python 3.11+ is required (uv handles this for you).

## Speaking to it

Speak digits singly; `niner` = 9, `oh` = 0.

- **Bearing** — the last digit is tenths: `nine six six` = 96.6°,
  `one two four seven` = 124.7°. Whole degrees carry a trailing zero:
  `two four five zero` = 245.0°. You can also say
  `one two four point seven`. Bearings ≥ 360° are rejected.
- **Distance** — kilometers, last two digits are decimals:
  `five eight four` = 5.84 km, `one two five zero` = 12.50 km. Explicit
  form works too: `five point eight four`.

| Say | Effect |
| --- | --- |
| `fire mission bearing nine six six distance five eight four` | New target at 96.6°, 5.84 km, auto-max charges |
| `… charges three` | Override the charge count for this mission |
| `… shell hotel echo` | Attach a shell type → elevation tolerance window |
| `… bearing nine six six reverse …` | You measured target→gun; flips 180° (→ 276.6°) |
| `target three charges four` | Edit target 3; elevation recomputes |
| `target three bearing one two four seven distance one two zero zero` | Edit any fields at once |
| `target three shell hotel echo` / `target three shell none` | Change or remove its shell |
| `target three reverse` | Flip target 3's bearing 180° |
| `target three destroyed` (or `dead` / `down`) | Strike it through |
| `delete target three` | Remove it entirely (e.g. a mishear) |
| `clear the board` | Wipe everything; numbering restarts at 1 |
| `default charges four` | Session default charge count |
| `default shell earthquake` / `default shell none` | Session default shell |

Every command is confirmed with an accept chime (or an error buzz), and the
board shows exactly what was heard and how it parsed — glance over before
you commit a long-range shot.

Shell names are spoken in NATO alphabet or by alias: LE `lima echo` ·
AP `alpha papa` · HE `hotel echo` · APHE `alpha papa hotel echo` ·
HCHE `hotel charlie hotel echo` / `high capacity` · EQKE `earthquake` ·
FLCH `fletcher`. Add your own aliases in `config.toml` — but stick to real
English words, since the speech model can't hear words it doesn't know
(that's why FLCH is "fletcher", not "flechette").

## Ballistics

The in-game calculator implements (verified against it, August 2026):

```
elevation° = 12 × distance_km ÷ charges        (max 60°)
```

so each powder charge adds exactly 5 km of range, and more charges mean a
flatter shot — which matters, because the gun must return to horizontal to
reload. NESTHELP therefore defaults to the most charges that reach.

**Elevation windows:** with blast diameter `B` km at `c` charges, any
elevation within `±12·(B/2)/c` degrees of the exact solution still lands the
blast on the aim point. The board shows this as `±0.61 → 18.99–20.21`.
Blast diameters in `config.toml` are rough by-eye measurements — corrections
welcome. The `margin` setting scales the window down if edge-of-blast hits
don't reliably kill your targets.

If a game patch rebalances the ballistics, the formula's constants
(`deg_per_km`, `max_elevation_deg`, `max_charges`) are all in `config.toml`.

## Configuration

Everything lives in [`config.toml`](config.toml): server port, ballistics
constants, default charges/shell, shell list with blast diameters and spoken
aliases. Two worth knowing about:

- `prefix` — set to e.g. `"computer"` to require a wake word before every
  command, if playing with squad voice chat causes false triggers.
- `default = "max"` under `[charges]` — set a number to prefer a fixed
  charge count instead of auto-max.

## Development

```sh
uv run test_core.py     # ballistics + grammar tests, no mic or model needed
```

The pieces: `ballistics.py` (the math), `parser.py` (command grammar),
`speech.py` (mic → Vosk), `controller.py` (board state), `server.py` +
`static/index.html` (FastAPI + WebSocket board), `chimes.py` (audio
feedback), `main.py` (wiring).

NESTHELP is a fan-made helper and is not affiliated with the developers of
IRON NEST. It reads no game files and touches no game memory — it's a
calculator with a microphone.
