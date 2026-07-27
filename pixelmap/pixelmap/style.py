"""Palettes and per-building colour assignment.

The cartoon look does not come from the geometry — that is already correct — it
comes from four things this module supplies: flat saturated fills, a dark
outline on every facet, strong separation between the three faces of a prism,
and enough building-to-building colour variety that 4,000 generated blocks stop
reading as one material.

Colours are assigned deterministically from the OSM id, so a building keeps its
colour across runs and the whole render stays reproducible from the seed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Facade:
    """One building material: roof, sunlit wall, shaded wall."""

    roof: tuple[int, int, int]
    left: tuple[int, int, int]
    right: tuple[int, int, int]


@dataclass(frozen=True)
class Style:
    name: str
    sky: tuple[int, int, int]
    land: tuple[int, int, int]
    urban: tuple[int, int, int]
    green: tuple[int, int, int]
    green_dark: tuple[int, int, int]
    water: tuple[int, int, int]
    water_light: tuple[int, int, int]
    road: tuple[int, int, int]
    road_major: tuple[int, int, int]
    rail: tuple[int, int, int]
    outline: tuple[int, int, int]
    facades: tuple[Facade, ...] = field(default=())
    landmark: Facade | None = None
    #: Weight of the outline in pixels. 0 disables it.
    outline_px: int = 1


# Limerick in its own colours, pushed toward poster saturation: limestone grey,
# Georgian red brick, painted shopfronts, slate roofs, a steely tidal Shannon.
LIMERICK_DAY = Style(
    name="limerick-day",
    sky=(214, 226, 231),
    land=(196, 198, 186),
    urban=(186, 188, 176),
    green=(126, 166, 98),
    green_dark=(96, 136, 74),
    water=(74, 130, 152),
    water_light=(96, 154, 174),
    road=(214, 210, 196),
    road_major=(228, 222, 204),
    rail=(150, 146, 138),
    outline=(46, 44, 52),
    facades=(
        # Limestone and painted render — the everyday city.
        Facade(roof=(108, 112, 124), left=(226, 222, 210), right=(168, 166, 158)),
        Facade(roof=(102, 106, 118), left=(238, 232, 214), right=(180, 174, 160)),
        # Georgian red brick.
        Facade(roof=(96, 100, 112), left=(196, 108, 84), right=(146, 76, 60)),
        Facade(roof=(92, 96, 108), left=(178, 96, 74), right=(132, 68, 54)),
        # Painted shopfronts — the Irish main-street colours.
        Facade(roof=(104, 108, 120), left=(214, 168, 92), right=(160, 122, 66)),
        Facade(roof=(100, 104, 116), left=(122, 152, 132), right=(88, 112, 96)),
        Facade(roof=(104, 108, 120), left=(178, 190, 198), right=(132, 142, 150)),
        # Warm cream, common on the quays.
        Facade(roof=(98, 102, 114), left=(232, 214, 180), right=(176, 160, 132)),
    ),
    landmark=Facade(roof=(120, 116, 108), left=(224, 214, 190), right=(170, 160, 140)),
)


def facade_for(style: Style, osm_id: str, seed: int = 0) -> Facade:
    """Pick a stable facade for a building.

    Hashing the id rather than counting keeps a building's colour fixed even if
    the extract order changes, which matters once manual overrides start
    referring to specific buildings.
    """
    if not style.facades:
        raise ValueError(f"style {style.name!r} has no facades")
    digest = hashlib.blake2b(f"{seed}:{osm_id}".encode(), digest_size=4).digest()
    return style.facades[int.from_bytes(digest, "big") % len(style.facades)]


STYLES = {s.name: s for s in (LIMERICK_DAY,)}
