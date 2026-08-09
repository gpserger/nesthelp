"""Board state and command handling.

All mutations run on the asyncio event loop (input threads hand text over via
call_soon_threadsafe), so no locking is needed. Every change pushes a full
snapshot to each connected websocket's queue.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from ballistics import Ballistics, OutOfRangeError
from parser import (UNSET, ClearBoard, DeleteTarget, FireMission, ParseError,
                    SetDefaultCharges, SetDefaultShell, TargetDestroyed,
                    UpdateTarget, build_alias_map, parse)


@dataclass
class Target:
    id: int
    bearing_deg: float
    distance_m: int
    charges: int
    elevation_deg: float
    tolerance_deg: float | None
    shell: str | None
    charges_bumped: bool
    status: str = "active"  # active | destroyed
    created: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "bearing_deg": round(self.bearing_deg, 1),
            "distance_m": self.distance_m,
            "charges": self.charges,
            "elevation_deg": round(self.elevation_deg, 2),
            "tolerance_deg": None if self.tolerance_deg is None
                             else round(self.tolerance_deg, 2),
            "shell": self.shell,
            "charges_bumped": self.charges_bumped,
            "status": self.status,
        }


class Controller:
    def __init__(self, cfg: dict, chimes, debug: bool = False):
        b = cfg.get("ballistics", {})
        self.ballistics = Ballistics(
            deg_per_km=b.get("deg_per_km", 12.0),
            max_elevation_deg=b.get("max_elevation_deg", 60.0),
            max_charges=b.get("max_charges", 6))
        self.shells = {s["name"]: s for s in cfg.get("shells", [])}
        self.alias_map = build_alias_map(cfg.get("shells", []))
        self.blast_margin = cfg.get("blast", {}).get("margin", 1.0)
        self.default_shell = cfg.get("blast", {}).get("default_shell") or None
        d = cfg.get("charges", {}).get("default", "max")
        self.default_charges: int | None = None if d == "max" else int(d)
        self.prefix = tuple(cfg.get("speech", {}).get("prefix", "").split())
        self.chimes = chimes
        self.debug = debug
        self.targets: dict[int, Target] = {}
        self.next_id = 1
        self.last_heard: dict | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._subs: set[asyncio.Queue] = set()

    # -- wiring ------------------------------------------------------------

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def on_text(self, text: str) -> None:
        """Entry point for input threads (speech / stdin)."""
        if self.loop:
            self.loop.call_soon_threadsafe(self._handle, text)

    # -- state -------------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "targets": [t.to_dict() for t in
                        sorted(self.targets.values(), key=lambda t: t.id)],
            "defaults": {
                "charges": self.default_charges or "max",
                "shell": self.default_shell,
            },
            "max_charges": self.ballistics.max_charges,
            "max_range_km": self.ballistics.max_range_km(),
            "last_heard": self.last_heard,
        }

    def _broadcast(self) -> None:
        snap = self.snapshot()
        for q in self._subs:
            q.put_nowait(snap)

    # -- command handling --------------------------------------------------

    def _solve(self, distance_m: int, charges: int | None, shell: str | None):
        blast = self.shells.get(shell, {}).get("blast_diameter_km") if shell else None
        return self.ballistics.solve(distance_m / 1000.0, charges=charges,
                                     blast_diameter_km=blast,
                                     blast_margin=self.blast_margin)

    def _handle(self, text: str) -> None:
        toks = text.split()
        if self.prefix:
            if tuple(toks[:len(self.prefix)]) != self.prefix:
                return
            toks = toks[len(self.prefix):]
        try:
            cmd = parse(toks, self.alias_map)
        except ParseError as e:
            self._finish(text, ok=False, msg=str(e))
            return
        if cmd is None:
            return  # not addressed to us; stay silent
        try:
            msg = self._apply(cmd)
        except (OutOfRangeError, ValueError) as e:
            self._finish(text, ok=False, msg=str(e))
            return
        self._finish(text, ok=True, msg=msg)

    def _apply(self, cmd) -> str:
        if isinstance(cmd, FireMission):
            shell = self.default_shell if cmd.shell is UNSET else cmd.shell
            sol = self._solve(
                cmd.distance_m,
                cmd.charges if cmd.charges is not None else self.default_charges,
                shell)
            t = Target(self.next_id, cmd.bearing_deg, cmd.distance_m,
                       sol.charges, sol.elevation_deg, sol.tolerance_deg,
                       shell, sol.charges_bumped)
            self.targets[t.id] = t
            self.next_id += 1
            note = " (charges raised to reach)" if sol.charges_bumped else ""
            return (f"target {t.id}: elevation {sol.elevation_deg:.2f}, "
                    f"{sol.charges} charges{note}")
        if isinstance(cmd, UpdateTarget):
            t = self.targets.get(cmd.target_id)
            if not t:
                raise ValueError(f"no target {cmd.target_id}")
            shell = t.shell if cmd.shell is UNSET else cmd.shell
            sol = self._solve(
                cmd.distance_m if cmd.distance_m is not None else t.distance_m,
                cmd.charges if cmd.charges is not None else t.charges,
                shell)
            if cmd.bearing_deg is not None:
                t.bearing_deg = cmd.bearing_deg
            if cmd.reverse:
                t.bearing_deg = (t.bearing_deg + 180.0) % 360.0
            t.distance_m, t.shell = round(sol.distance_km * 1000), shell
            t.charges, t.elevation_deg = sol.charges, sol.elevation_deg
            t.tolerance_deg, t.charges_bumped = sol.tolerance_deg, sol.charges_bumped
            note = " (charges raised to reach)" if sol.charges_bumped else ""
            return (f"target {t.id} updated: elevation {sol.elevation_deg:.2f}, "
                    f"{sol.charges} charges{note}")
        if isinstance(cmd, TargetDestroyed):
            t = self.targets.get(cmd.target_id)
            if not t:
                raise ValueError(f"no target {cmd.target_id}")
            t.status = "destroyed"
            return f"target {t.id} destroyed"
        if isinstance(cmd, DeleteTarget):
            if cmd.target_id not in self.targets:
                raise ValueError(f"no target {cmd.target_id}")
            del self.targets[cmd.target_id]
            return f"target {cmd.target_id} deleted"
        if isinstance(cmd, ClearBoard):
            self.targets.clear()
            self.next_id = 1
            return "board cleared"
        if isinstance(cmd, SetDefaultCharges):
            self.default_charges = cmd.charges
            return f"default charges {cmd.charges}"
        if isinstance(cmd, SetDefaultShell):
            self.default_shell = cmd.shell
            return f"default shell {cmd.shell or 'cleared'}"
        raise ValueError("unknown command")

    def _finish(self, text: str, ok: bool, msg: str) -> None:
        self.last_heard = {"text": text, "ok": ok, "msg": msg,
                           "ts": time.time()}
        (self.chimes.accept if ok else self.chimes.error)()
        if self.debug:
            mark = "ok " if ok else "ERR"
            print(f"[{mark}] {text} -> {msg}")
        self._broadcast()
