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
    #: Footpath band drawn either side of the carriageway. With the streets
    #: widened, this is what makes the extra ground read as pavement.
    pavement: tuple[int, int, int] = (222, 219, 208)
    pavement_m: float = 3.0
    #: The Shannon is tidal and walled through the city. `quay` is the wall face
    #: seen across the water, `coping` its lit top course.
    quay: tuple[int, int, int] = (132, 128, 118)
    coping: tuple[int, int, int] = (196, 191, 178)
    quay_m: float = 2.6
    ripple: tuple[int, int, int] = (104, 158, 178)
    #: Bridge decks are drawn as solid prisms rather than painted stripes.
    bridge_deck: tuple[int, int, int] = (198, 192, 178)
    bridge_side: tuple[int, int, int] = (150, 144, 132)
    bridge_shadow: tuple[int, int, int] = (52, 96, 116)
    bridge_rise_m: float = 4.5
    #: Glazing, and the fascia board above a shopfront.
    window: tuple[int, int, int] = (86, 104, 118)
    window_lit: tuple[int, int, int] = (236, 206, 138)
    fascia: tuple[int, int, int] = (78, 72, 82)
    facades: tuple[Facade, ...] = field(default=())
    #: Roof colour is drawn independently of wall colour: in a real city the two
    #: barely correlate, and tying them made every red building grow a red roof.
    roofs: tuple[tuple[int, int, int], ...] = field(default=())
    landmark: Facade | None = None
    #: Named materials for landmark models. Generated buildings draw from the
    #: random `facades` pool; a landmark asks for limestone or copper by name,
    #: because "the cathedral is whatever colour its id hashed to" is exactly
    #: the wrong answer for the buildings people will look at first.
    materials: dict[str, Facade] = field(default_factory=dict)
    #: The ground inside a walled enclosure — cobbles, not roof.
    court: tuple[int, int, int] = (176, 172, 158)
    #: Weight of the outline in pixels. 0 disables it.
    outline_px: int = 1


# Limerick in its own colours, pushed toward poster saturation: limestone grey,
# Georgian red brick, painted shopfronts, slate roofs, a steely tidal Shannon.
LIMERICK_DAY = Style(
    name="limerick-day",
    sky=(206, 222, 230),
    land=(202, 204, 190),
    urban=(186, 188, 176),
    green=(126, 166, 98),
    green_dark=(96, 136, 74),
    water=(74, 130, 152),
    water_light=(96, 154, 174),
    road=(196, 192, 182),
    road_major=(206, 202, 190),
    pavement=(224, 221, 210),
    pavement_m=3.2,
    quay=(126, 122, 112),
    coping=(200, 195, 182),
    quay_m=2.8,
    ripple=(102, 156, 176),
    bridge_deck=(202, 196, 182),
    bridge_side=(154, 148, 136),
    bridge_shadow=(50, 94, 114),
    bridge_rise_m=4.5,
    rail=(150, 146, 138),
    outline=(46, 44, 52),
    window=(92, 112, 126),
    window_lit=(238, 208, 140),
    fascia=(74, 68, 78),
    # Seen from above, the roof is the biggest surface a building shows, so roof
    # colour carries the render. Keeping every roof the same slate turned the
    # whole city monotone; these vary across slate, weathered lead, warm grey
    # and clay tile while staying a believable Irish roofscape.
    facades=(
        # Limestone and painted render — the everyday city.
        Facade(roof=(126, 134, 150), left=(232, 228, 216), right=(172, 170, 162)),
        Facade(roof=(112, 122, 136), left=(242, 236, 220), right=(184, 178, 164)),
        # Georgian red brick under slate.
        Facade(roof=(120, 126, 140), left=(198, 110, 86), right=(148, 78, 62)),
        Facade(roof=(146, 96, 78),   left=(182, 100, 78), right=(136, 72, 56)),
        # Painted shopfronts — the Irish main-street colours.
        Facade(roof=(134, 140, 148), left=(218, 172, 94),  right=(164, 126, 68)),
        Facade(roof=(116, 130, 126), left=(126, 156, 136), right=(92, 116, 100)),
        Facade(roof=(140, 146, 158), left=(182, 194, 202), right=(136, 146, 154)),
        # Warm cream, common on the quays.
        Facade(roof=(150, 142, 132), left=(236, 218, 184), right=(180, 164, 136)),
        # Clay tile, the newer estates.
        Facade(roof=(158, 104, 82),  left=(226, 214, 196), right=(170, 162, 148)),
    ),
    roofs=(
        (118, 128, 144),   # blue slate, the Georgian default
        (108, 118, 132),
        (128, 136, 148),
        (96, 106, 120),    # weathered lead
        (146, 150, 156),   # light grey slate
        (150, 100, 80),    # clay tile
        (134, 88, 70),
        (112, 124, 118),   # mossy slate
        (140, 134, 124),   # warm grey
    ),
    landmark=Facade(roof=(120, 116, 108), left=(224, 214, 190), right=(170, 160, 140)),
    # King John's bailey is grass over the excavations. It also has to differ
    # clearly from the limestone wall head above it, or the enclosure reads as a
    # solid slab rather than as walls round a space.
    court=(132, 152, 104),
    # Limerick builds in its own grey limestone; the cathedrals, the castle and
    # the Custom House are all the same stone, so they are all the same colour
    # here, and the eye reads them as a set.
    materials={
        "limestone": Facade(roof=(150, 148, 138), left=(214, 210, 194),
                            right=(158, 154, 140)),
        "limestone_dark": Facade(roof=(128, 126, 118), left=(184, 180, 166),
                                 right=(134, 130, 118)),
        "brick": Facade(roof=(140, 132, 124), left=(178, 104, 80),
                        right=(132, 74, 56)),
        "render": Facade(roof=(148, 144, 136), left=(238, 230, 212),
                         right=(182, 174, 158)),
        "slate": Facade(roof=(96, 108, 126), left=(120, 130, 146),
                        right=(86, 96, 112)),
        "lead": Facade(roof=(122, 130, 134), left=(146, 152, 156),
                       right=(108, 114, 120)),
        "copper": Facade(roof=(112, 164, 148), left=(134, 182, 166),
                         right=(90, 136, 122)),
        # A market canopy is a bright lid, not a roof: it has to read as light
        # coming through rather than slate sitting on top.
        "canopy": Facade(roof=(238, 234, 222), left=(246, 242, 232),
                         right=(206, 200, 186)),
        "glass": Facade(roof=(118, 138, 152), left=(150, 176, 190),
                        right=(104, 128, 144)),
    },
)

#: OSM roof:colour values seen in Limerick, plus the usual CSS names.
_NAMED = {
    "black": (58, 58, 62), "grey": (128, 128, 130), "gray": (128, 128, 130),
    "darkgrey": (86, 86, 90), "dark_grey": (86, 86, 90), "lightgrey": (168, 168, 170),
    "white": (232, 232, 228), "brown": (132, 92, 68), "red": (156, 78, 62),
    "darkred": (124, 60, 48), "green": (96, 122, 88), "darkgreen": (74, 96, 68),
    "blue": (92, 112, 148), "slate": (112, 122, 136), "silver": (176, 178, 180),
    "beige": (208, 194, 168), "orange": (188, 118, 66), "terracotta": (170, 100, 74),
}


def parse_colour(value: str | None) -> tuple[int, int, int] | None:
    """Read an OSM colour tag, muted toward the palette so it still fits in."""
    if not value:
        return None
    text = value.strip().lower()
    if text.startswith("#"):
        hexpart = text[1:]
        if len(hexpart) == 3:
            hexpart = "".join(c * 2 for c in hexpart)
        if len(hexpart) == 6:
            try:
                raw = tuple(int(hexpart[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return None
        else:
            return None
    elif text in _NAMED:
        raw = _NAMED[text]
    else:
        return None
    # Pull tagged colours a little toward mid grey so one loud roof cannot
    # break the palette the rest of the render is built on.
    return tuple(int(c * 0.82 + 128 * 0.18) for c in raw)


def roof_for(style: Style, osm_id: str, seed: int) -> tuple[int, int, int]:
    if not style.roofs:
        raise ValueError(f"style {style.name!r} has no roof colours")
    digest = hashlib.blake2b(f"roof:{seed}:{osm_id}".encode(), digest_size=4).digest()
    return style.roofs[int.from_bytes(digest, "big") % len(style.roofs)]


def material_for(style: Style, name: str) -> Facade:
    """A landmark's named material. Unknown names are a config typo, not a
    licence to silently draw the wrong thing."""
    try:
        return style.materials[name]
    except KeyError:
        raise KeyError(
            f"style {style.name!r} has no material {name!r} "
            f"(have {', '.join(sorted(style.materials))})"
        ) from None


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
