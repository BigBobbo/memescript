"""Street-bearing analysis — how the map gets rotated.

Follows Geoff Boeing's urban street network orientation method: a length-weighted
polar histogram of street bearings. On top of that we solve for the rotation that
best aligns the city's dominant grid with the isometric axes.

The trick is the fourth-harmonic circular mean. A street grid is symmetric under
90-degree rotation, so bearings are summed as unit phasors at four times their
angle; the argument of that sum, divided by four, is the grid's angle, and its
normalized magnitude is how grid-like the city is at all.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass


@dataclass
class GridFit:
    grid_angle_deg: float   #: dominant grid bearing, folded into [0, 90)
    strength: float         #: 0 = no dominant grid, 1 = perfectly gridded
    entropy: float          #: Shannon entropy of the 36-bin rose, in bits
    orderliness: float      #: 1 = perfect grid, 0 = maximally disordered
    total_length_m: float
    n_segments: int

    @property
    def rotation_deg(self) -> float:
        """Rotation to apply so the dominant grid lands on the isometric axes.

        Chosen from the four equivalent grid angles as the smallest correction,
        so the map never ends up gratuitously upside down.
        """
        candidates = [self.grid_angle_deg - k * 90.0 for k in range(4)]
        return -min(candidates, key=abs)


def rose(bearings: list[tuple[float, float]], bins: int = 36) -> list[float]:
    """Length-weighted, bidirectional histogram of bearings.

    Each segment is counted in both directions, since a street has no inherent
    direction of travel. Bins are centred on multiples of 360/bins.
    """
    counts = [0.0] * bins
    width = 360.0 / bins
    for bearing, length in bearings:
        for value in (bearing, bearing + 180.0):
            index = int(((value % 360.0) + width / 2) // width) % bins
            counts[index] += length
    return counts


def fit_grid(bearings: list[tuple[float, float]], bins: int = 36) -> GridFit:
    total = sum(length for _, length in bearings)
    if total <= 0:
        raise ValueError("no street segments to analyse")

    # Fourth harmonic: collapses the grid's 90-degree symmetry to a single phasor.
    phasor = sum(
        length * cmath.exp(4j * math.radians(bearing)) for bearing, length in bearings
    )
    strength = abs(phasor) / total
    grid_angle = (math.degrees(cmath.phase(phasor)) / 4.0) % 90.0

    counts = rose(bearings, bins)
    grand = sum(counts)
    entropy = -sum(
        (c / grand) * math.log(c / grand) for c in counts if c > 0
    ) / math.log(2)

    # Boeing's orderliness: rescaled between a perfect grid and maximum disorder.
    max_entropy = math.log2(bins)
    perfect_grid_entropy = 2.0  # four equal bins
    orderliness = 1.0 - ((entropy - perfect_grid_entropy) / (max_entropy - perfect_grid_entropy)) ** 2
    orderliness = max(0.0, min(1.0, orderliness))

    return GridFit(
        grid_angle_deg=grid_angle,
        strength=strength,
        entropy=entropy,
        orderliness=orderliness,
        total_length_m=total,
        n_segments=len(bearings),
    )


#: In 2:1 isometric, eight world directions render as clean pixel lines: the two
#: grid axes and their diagonals, which project to the screen horizontal and
#: vertical. So alignment folds at 45 degrees, not 90.
CLEAN_FOLD_DEG = 45.0


def _offset_from_clean(bearing: float, rotation: float, fold: float = CLEAN_FOLD_DEG) -> float:
    """Angle a segment must be bent through to land on a clean direction."""
    offset = (bearing + rotation) % fold
    return min(offset, fold - offset)


def alignment_profile(
    bearings: list[tuple[float, float]],
    step: float = 0.5,
    tolerance: float = 5.0,
    fold: float = CLEAN_FOLD_DEG,
) -> list[tuple[float, float]]:
    """Share of street length already near a clean direction, per candidate rotation.

    A plain-language read on how much of the city renders as crisp pixel lines
    before any snapping — and therefore how much snapping has to invent.
    """
    total = sum(length for _, length in bearings) or 1.0
    profile = []
    rotation = 0.0
    while rotation < fold:
        aligned = sum(
            length for bearing, length in bearings
            if _offset_from_clean(bearing, rotation, fold) <= tolerance
        )
        profile.append((rotation, aligned / total))
        rotation += step
    return profile


def snap_cost(
    bearings: list[tuple[float, float]],
    rotation: float,
    fold: float = CLEAN_FOLD_DEG,
) -> float:
    """Length-weighted mean bend, in degrees, needed to snap every segment.

    The honest measure of how much violence a given rotation does to the city's
    real geometry.
    """
    total = sum(length for _, length in bearings) or 1.0
    return sum(
        length * _offset_from_clean(bearing, rotation, fold)
        for bearing, length in bearings
    ) / total
