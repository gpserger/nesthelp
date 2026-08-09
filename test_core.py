"""Core math + parser tests: .venv/bin/python test_core.py"""
import tomllib

from ballistics import Ballistics, OutOfRangeError
from parser import (UNSET, ClearBoard, DeleteTarget, FireMission, ParseError,
                    SetDefaultCharges, SetDefaultShell, TargetDestroyed,
                    UpdateTarget, build_alias_map, parse, vocabulary)

with open("config.toml", "rb") as f:
    CFG = tomllib.load(f)
AMAP = build_alias_map(CFG["shells"])
B = Ballistics()


def close(a, b, eps=1e-9):
    assert abs(a - b) < eps, f"{a} != {b}"


def p(text):
    return parse(text.split(), AMAP)


# --- ballistics: the in-game verification checklist ---
close(B.solve(3.75, 1).elevation_deg, 45.0)
close(B.solve(5.0, 1).elevation_deg, 60.0)
close(B.solve(30.0, 6).elevation_deg, 60.0)
close(B.solve(1.0, 6).elevation_deg, 2.0)
close(B.solve(7.3, 3).elevation_deg, 29.2)
close(B.solve(12.34, 4).elevation_deg, 37.02)
close(B.solve(10.0, 2).elevation_deg, 60.0)
close(B.solve(13.9, 5).elevation_deg, 33.36)

# auto-max charges; bump when dictated charges can't reach
assert B.solve(12.0).charges == 6
s = B.solve(12.0, charges=2)
assert s.charges == 3 and s.charges_bumped
try:
    B.solve(30.01)
    raise AssertionError("expected OutOfRangeError")
except OutOfRangeError:
    pass

# blast tolerance: +/- 12 * (B/2) * margin / charges
close(B.solve(20.0, 6, blast_diameter_km=0.61).tolerance_deg, 0.61)
close(B.solve(4.0, 1, blast_diameter_km=0.23).tolerance_deg, 1.38)
close(B.solve(4.0, 1, blast_diameter_km=0.23, blast_margin=0.5).tolerance_deg, 0.69)

# --- parser: bearings and distances as read off the map ---
# bearing: last digit is tenths; distance: last two digits are decimals
c = p("fire mission bearing nine six six distance five eight four")
assert c == FireMission(96.6, 5840, None, UNSET)  # 96.6 deg, 5.84 km
c = p("fire mission bearing one oh seven zero distance five eight four")
assert c.bearing_deg == 107.0
c = p("fire mission bearing two four five zero distance five eight four")
assert c.bearing_deg == 245.0
c = p("fire mission bearing one two four seven distance five eight four")
assert c.bearing_deg == 124.7
c = p("fire mission bearing one two four point seven distance five eight four")
assert c.bearing_deg == 124.7  # "point" form: whole degrees before it
c = p("fire mission bearing niner point five range one two five "
      "zero charges five shell hotel charlie hotel echo")
assert c == FireMission(9.5, 12500, 5, "HCHE")  # 12.50 km
c = p("fire mission bearing two four five zero distance one two point five")
assert c.distance_m == 12500  # explicit point, one decimal digit
c = p("fire mission bearing two four five zero distance five point eight four")
assert c.distance_m == 5840
c = p("fire mission bearing 1247 distance 5.84 charges 4 ammo he")
assert c == FireMission(124.7, 5840, 4, "HE")  # typed numerals
c = p("fire mission bearing 124.7 distance 12.5")
assert c == FireMission(124.7, 12500, None, UNSET)
c = p("fire mission bearing 966 distance 5.84")
assert c.bearing_deg == 96.6  # typed digits follow the same tenths rule

# --- reverse (back-bearing) ---
c = p("fire mission bearing nine six six reverse distance five eight four")
assert c.bearing_deg == 276.6  # called target->gun, flipped to gun->target
c = p("fire mission bearing two seven six six reverse distance five eight four")
assert abs(c.bearing_deg - 96.6) < 1e-9  # flip wraps past 360
assert p("target three reverse") == UpdateTarget(3, None, None, None, UNSET, True)
c = p("target three reverse charges four")
assert c == UpdateTarget(3, None, None, 4, UNSET, True)
c = p("target three bearing nine six six reverse")
assert c == UpdateTarget(3, 96.6, None, None, UNSET, True)

# --- target edits ---
assert p("target three charges four") == UpdateTarget(3, None, None, 4, UNSET)
assert p("target three shell hotel echo") == UpdateTarget(3, None, None, None, "HE")
assert p("target three shell none") == UpdateTarget(3, None, None, None, None)
c = p("target three bearing nine six six distance five eight four charges two")
assert c == UpdateTarget(3, 96.6, 5840, 2, UNSET)

assert p("target three destroyed") == TargetDestroyed(3)
assert p("target one two dead") == TargetDestroyed(12)
assert p("delete target four") == DeleteTarget(4)
assert p("target four delete") == DeleteTarget(4)
assert p("clear the board") == ClearBoard()
assert p("clear board") == ClearBoard()
assert p("default charges four") == SetDefaultCharges(4)
assert p("default shell earthquake") == SetDefaultShell("EQKE")
assert p("default shell none") == SetDefaultShell(None)

# non-commands are silently ignored; malformed commands raise
assert p("well that was a big explosion") is None
assert p("[unk] [unk]") is None
for bad in ("fire mission distance five eight four",     # no bearing
            "fire mission bearing two four five",        # no distance
            "fire mission bearing three six five zero "
            "distance five eight four",                  # 365.0: off the compass
            "fire mission bearing three seven five point five "
            "distance five eight four",                  # 375.5: off the compass
            "fire mission bearing one two four point five five "
            "distance five eight four",                  # 2 decimal digits
            "fire mission bearing two four five zero distance five "
            "eight four charges nine",                   # charges out of range
            "target destroyed",                          # no number
            "target three",                              # edit with no fields
            "target three charges",                      # field with no value
            "fire mission bearing two four five zero distance five "
            "eight four shell banana"):                  # unknown shell
    try:
        p(bad)
        raise AssertionError(f"expected ParseError: {bad}")
    except ParseError:
        pass

# vocabulary covers everything the grammar needs
v = set(vocabulary(AMAP))
for w in ("fire", "mission", "bearing", "niner", "oh", "point", "hotel",
          "echo", "fletcher", "destroyed", "board", "none"):
    assert w in v, w

print(f"all tests passed ({len(v)} words in recognizer vocabulary)")
