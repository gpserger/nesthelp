"""Parse recognized speech into commands.

Grammar (all lowercase words, matching the Vosk vocabulary):

    fire mission bearing <bearing> [reverse] (distance|range) <km>
        [charges <one..six>] [(shell|ammo) <alias words>]
    target <digits> <field> <value> [<field> <value> ...]   # edit a target
    target <digits> reverse                                 # flip bearing 180
    target <digits> (destroyed|dead|down)
    (delete|deleted) target <digits>  /  target <digits> (delete|deleted)
    clear [the] board
    default charges <one..six>
    default shell (<alias words>|none)

Numbers are dictated exactly as read off the map, digits spoken singly
("niner" = 9, "oh" = 0):

  bearing   the last digit is tenths: "nine six six" = 96.6, so whole
            degrees carry a trailing zero ("two four five zero" = 245.0).
            With "point" the digits before it are whole degrees:
            "one two four point seven" = 124.7. Bearings >= 360 rejected.
  distance  km at the calculator's 0.01 precision — the last two digits are
            decimals: "five eight four" = "five point eight four" = 5.84 km,
            so 12.50 km is "one two five zero".

Plain numerals ("124.7", "1247" = 124.7, "5.84") are also accepted so the
same grammar works in --stdin mode.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class ParseError(ValueError):
    pass


class _Unset:
    def __repr__(self):
        return "UNSET"


UNSET = _Unset()  # distinguishes "field not mentioned" from "shell none"


@dataclass(frozen=True)
class FireMission:
    bearing_deg: float
    distance_m: int
    charges: int | None
    shell: str | None | _Unset  # UNSET = not mentioned, None = explicit "none"


@dataclass(frozen=True)
class UpdateTarget:
    target_id: int
    bearing_deg: float | None
    distance_m: int | None
    charges: int | None
    shell: str | None | _Unset
    reverse: bool = False


@dataclass(frozen=True)
class TargetDestroyed:
    target_id: int


@dataclass(frozen=True)
class DeleteTarget:
    target_id: int


@dataclass(frozen=True)
class ClearBoard:
    pass


@dataclass(frozen=True)
class SetDefaultCharges:
    charges: int


@dataclass(frozen=True)
class SetDefaultShell:
    shell: str | None  # None = clear the default


DIGIT_WORDS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "niner": 9,
}
DESTROY_WORDS = {"destroyed", "dead", "down"}
DELETE_WORDS = {"delete", "deleted"}


class _Cursor:
    def __init__(self, toks: list[str]):
        self.toks = toks
        self.i = 0

    def done(self) -> bool:
        return self.i >= len(self.toks)

    def peek(self) -> str | None:
        return None if self.done() else self.toks[self.i]

    def next(self) -> str:
        t = self.toks[self.i]
        self.i += 1
        return t


def _read_int(cur: _Cursor, what: str) -> int:
    val, got = 0, False
    while not cur.done():
        t = cur.peek()
        if t in DIGIT_WORDS:
            val = val * 10 + DIGIT_WORDS[t]
        elif t.isdigit():
            val = val * (10 ** len(t)) + int(t)
        else:
            break
        got = True
        cur.next()
    if not got:
        raise ParseError(f"expected a number for {what}")
    return val


_BEARING_NUMERAL = re.compile(r"\d{1,3}\.\d|\d{1,4}")
_KM_NUMERAL = re.compile(r"\d+\.\d{1,2}")


def _collect_digits(cur: _Cursor, limit: int) -> list[str]:
    digits: list[str] = []
    while not cur.done() and len(digits) < limit:
        t = cur.peek()
        if t in DIGIT_WORDS:
            digits.append(str(DIGIT_WORDS[t]))
        elif t.isdigit():
            digits.extend(t)
        else:
            break
        cur.next()
    return digits


def _more_digits(cur: _Cursor) -> bool:
    t = cur.peek()
    return t is not None and (t in DIGIT_WORDS or t.isdigit())


def _read_bearing(cur: _Cursor) -> float:
    """The last digit is tenths, mirroring the distance rule: "nine six six"
    = 96.6, "two four five zero" = 245.0. With "point", the digits before it
    are whole degrees: "one two four point seven" = 124.7."""
    t = cur.peek()
    if t and _BEARING_NUMERAL.fullmatch(t):  # typed: "124.7" / "1247" / "966"
        cur.next()
        val = float(t) if "." in t else int(t) / 10.0
    else:
        digits = _collect_digits(cur, 5)
        if not digits:
            raise ParseError("expected a bearing")
        if cur.peek() == "point":
            cur.next()
            frac = _collect_digits(cur, 1)
            if not frac or _more_digits(cur):
                raise ParseError("bearing takes a single decimal digit after 'point'")
            val = int("".join(digits)) + int(frac[0]) / 10.0
        else:
            val = int("".join(digits)) / 10.0
    if val >= 360.0:
        raise ParseError(f"bearing {val:g} is not on the compass")
    return val


def _read_distance_km(cur: _Cursor) -> float:
    """Distance in km at 0.01 precision. Without "point" the last two digits
    are decimals: "five eight four" = "five point eight four" = 5.84 km."""
    t = cur.peek()
    if t and _KM_NUMERAL.fullmatch(t):  # typed: "5.84"
        cur.next()
        return float(t)
    digits = _collect_digits(cur, 6)
    if not digits:
        raise ParseError("expected a distance")
    if cur.peek() == "point":
        cur.next()
        frac = _collect_digits(cur, 2)
        if not frac or _more_digits(cur):
            raise ParseError("distance takes one or two decimal digits after 'point'")
        return int("".join(digits)) + int("".join(frac)) / (10 ** len(frac))
    return int("".join(digits)) / 100.0


def build_alias_map(shells: list[dict]) -> dict[tuple[str, ...], str]:
    """Map spoken-token tuples to shell names, e.g. ('hotel','echo') -> 'HE'."""
    amap: dict[tuple[str, ...], str] = {}
    for s in shells:
        amap[(s["name"].lower(),)] = s["name"]
        for alias in s.get("aliases", []):
            amap[tuple(alias.lower().split())] = s["name"]
    return amap


def _match_shell(cur: _Cursor, alias_map: dict[tuple[str, ...], str]) -> str:
    rest = tuple(cur.toks[cur.i:])
    for alias in sorted(alias_map, key=len, reverse=True):
        if rest[:len(alias)] == alias:
            cur.i += len(alias)
            return alias_map[alias]
    raise ParseError(f"unknown shell '{' '.join(rest[:4])}'")


def _read_fields(cur: _Cursor, alias_map) -> dict:
    """Field/value pairs shared by fire missions and target edits."""
    fields: dict = {}
    while not cur.done():
        t = cur.next()
        if t == "bearing":
            fields["bearing"] = _read_bearing(cur)
        elif t in ("distance", "range"):
            fields["distance"] = round(_read_distance_km(cur) * 1000)
        elif t in ("charges", "charge"):
            n = _read_int(cur, "charges")
            if not 1 <= n <= 6:
                raise ParseError(f"charges must be 1-6, heard {n}")
            fields["charges"] = n
        elif t in ("shell", "ammo"):
            if cur.peek() == "none":
                cur.next()
                fields["shell"] = None
            else:
                fields["shell"] = _match_shell(cur, alias_map)
        elif t == "reverse":
            fields["reverse"] = True
        else:
            raise ParseError(f"unexpected word '{t}'")
    return fields


def _parse_fire(cur: _Cursor, alias_map) -> FireMission:
    f = _read_fields(cur, alias_map)
    if "bearing" not in f:
        raise ParseError("no bearing given")
    if "distance" not in f:
        raise ParseError("no distance given")
    bearing = f["bearing"]
    if f.get("reverse"):  # target->gun bearing was called; flip to gun->target
        bearing = (bearing + 180.0) % 360.0
    return FireMission(bearing, f["distance"], f.get("charges"),
                       f.get("shell", UNSET))


def parse(tokens: list[str], alias_map: dict[tuple[str, ...], str]):
    """Return a command, or None when the utterance isn't addressed to us.

    Raises ParseError when it starts like a command but is malformed.
    """
    toks = [t for t in tokens if t and t != "[unk]"]
    if not toks:
        return None
    head = toks[0]
    cur = _Cursor(toks)

    if head == "fire":
        cur.next()
        if cur.peek() != "mission":
            raise ParseError("expected 'fire mission'")
        cur.next()
        return _parse_fire(cur, alias_map)

    if head == "target":
        cur.next()
        tid = _read_int(cur, "target number")
        verb = cur.peek() or ""
        if verb in DESTROY_WORDS:
            return TargetDestroyed(tid)
        if verb in DELETE_WORDS:
            return DeleteTarget(tid)
        f = _read_fields(cur, alias_map)
        if not f:
            raise ParseError(f"target {tid}: expected 'destroyed', 'delete', "
                             f"or a field to change")
        return UpdateTarget(tid, f.get("bearing"), f.get("distance"),
                            f.get("charges"), f.get("shell", UNSET),
                            f.get("reverse", False))

    if head in DELETE_WORDS:
        cur.next()
        if cur.peek() == "target":
            cur.next()
        return DeleteTarget(_read_int(cur, "target number"))

    if head == "clear":
        cur.next()
        if cur.peek() == "the":
            cur.next()
        if cur.peek() == "board":
            return ClearBoard()
        raise ParseError("expected 'clear board'")

    if head == "default":
        cur.next()
        what = cur.next() if not cur.done() else ""
        if what in ("charges", "charge"):
            n = _read_int(cur, "default charges")
            if not 1 <= n <= 6:
                raise ParseError(f"charges must be 1-6, heard {n}")
            return SetDefaultCharges(n)
        if what in ("shell", "ammo"):
            if cur.peek() == "none":
                return SetDefaultShell(None)
            return SetDefaultShell(_match_shell(cur, alias_map))
        raise ParseError("expected 'default charges N' or 'default shell X'")

    return None


def vocabulary(alias_map: dict[tuple[str, ...], str]) -> list[str]:
    """Word list for the grammar-constrained recognizer."""
    words = {
        "fire", "mission", "bearing", "distance", "range", "charges", "charge",
        "shell", "ammo", "target", "clear", "the", "board", "default", "point",
        "none", "reverse",
    }
    words |= DIGIT_WORDS.keys() | DESTROY_WORDS | DELETE_WORDS
    for alias in alias_map:
        words |= set(alias)
    return sorted(words)
