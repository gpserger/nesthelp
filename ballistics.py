"""Firing solution math for IRON NEST.

Verified in-game 2026-08-08 against the mechanical ballistic calculator:

    elevation_deg = DEG_PER_KM * distance_km / charges

Max elevation is 60 deg, which makes the max range exactly 5 km per powder
charge (the game's own "each charge adds 5 km" text). Calculator accepts
distances down to 0.01 km and reads out elevation down to 0.01 deg.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


class OutOfRangeError(ValueError):
    pass


@dataclass(frozen=True)
class Solution:
    distance_km: float
    charges: int
    elevation_deg: float
    # +/- elevation window that still puts the blast on the aim point,
    # None when no shell/blast diameter is known.
    tolerance_deg: float | None
    # True when the dictated charge count could not reach and was raised.
    charges_bumped: bool


class Ballistics:
    def __init__(self, deg_per_km: float = 12.0, max_elevation_deg: float = 60.0,
                 max_charges: int = 6):
        self.deg_per_km = deg_per_km
        self.max_elevation_deg = max_elevation_deg
        self.max_charges = max_charges
        self.km_per_charge = max_elevation_deg / deg_per_km

    def max_range_km(self, charges: int | None = None) -> float:
        return self.km_per_charge * (charges or self.max_charges)

    def min_charges(self, distance_km: float) -> int:
        return max(1, math.ceil(distance_km / self.km_per_charge - 1e-9))

    def solve(self, distance_km: float, charges: int | None = None,
              blast_diameter_km: float | None = None,
              blast_margin: float = 1.0) -> Solution:
        if distance_km <= 0:
            raise ValueError("distance must be positive")
        need = self.min_charges(distance_km)
        if need > self.max_charges:
            raise OutOfRangeError(
                f"{distance_km:.2f} km is beyond max range "
                f"{self.max_range_km():.0f} km")
        bumped = False
        if charges is None:
            charges = self.max_charges
        elif charges < need:
            charges, bumped = need, True
        charges = min(charges, self.max_charges)
        elevation = self.deg_per_km * distance_km / charges
        tolerance = None
        if blast_diameter_km:
            tolerance = self.deg_per_km * (blast_diameter_km / 2.0) * blast_margin / charges
        return Solution(distance_km, charges, elevation, tolerance, bumped)
