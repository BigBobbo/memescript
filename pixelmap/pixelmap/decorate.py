"""Stage 4 — decorate.

Everything so far is the city as it is recorded: footprints, banks, kerbs. This
stage adds what nobody surveys — the trees down O'Connell Street, the boats on
the Shannon, the swans under Sarsfield Bridge. It is the difference between a
very good data render and a picture of Limerick.

None of it comes from OSM. Street trees are barely mapped in Ireland and swans
are not mapped at all, so props are placed procedurally from a seed. That keeps
the pipeline's reproducibility promise intact: same inputs, same seed, same
PNG, forever.

Placement is the whole job here, and it is mostly a matter of saying no. A tree
is welcome on a verge and absurd through a roof, so every candidate is tested
against the buildings, the carriageway and the water before it is kept. The
tests run against a spatial index rather than the whole city, because a park
scattered at 9 m intervals asks the question a few thousand times.

Drawing the props is `props.py`; this module only decides where they stand.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Point, Polygon
from shapely.prepared import prep
from shapely.strtree import STRtree

from .draw3d import rng
from .extract import Layers

#: How densely each kind of green is planted, in metres between trees.
#:
#: Not every green is a park. OSM's greens for Limerick are 134 ha of `grass`,
#: 173 ha of `meadow` and 75 ha of `grassland` against 62 ha of actual park, and
#: planting verges and meadows at park density buries the city under canopy.
#: Woodland gets a thicket, parks get an avenue, open ground gets the occasional
#: tree standing on its own, which is what open ground actually looks like.
SPACING_BY_KIND = {
    "wood": 8.0, "forest": 8.0, "scrub": 11.0,
    "park": 14.0, "garden": 12.0, "cemetery": 15.0,
    "village_green": 16.0, "common": 18.0,
    "grass": 34.0, "grassland": 34.0, "meadow": 40.0, "recreation_ground": 30.0,
}

#: Greens that must stay clear. A pitch with trees down the middle of it is not
#: a pitch, and these are usually drawn *inside* a park polygon, so it is not
#: enough to skip them — they have to be subtracted from whatever contains them.
BARE = {"pitch", "golf_course", "sports_centre", "wetland"}


@dataclass(frozen=True)
class Prop:
    """One piece of charm, in projected world metres."""

    x: float
    y: float
    kind: str            #: "tree" | "boat" | "swan"
    height_m: float      #: how tall it stands, or how long a boat is
    variant: int         #: which of the kind's looks to draw
    angle_deg: float = 0.0


def _jittered_grid(poly: Polygon, spacing: float, seed: int, salt: str):
    """Candidate points on a jittered lattice covering a polygon's bounds.

    A plain lattice reads as an orchard and pure random scatter clumps; jitter
    inside each cell gives the loose, even spread that looks like planting.
    """
    minx, miny, maxx, maxy = poly.bounds
    nx = max(1, int((maxx - minx) / spacing))
    ny = max(1, int((maxy - miny) / spacing))
    for i in range(nx + 1):
        for j in range(ny + 1):
            key = f"{salt}:{i}:{j}"
            x = minx + (i + rng(key, seed, "x")) * spacing
            y = miny + (j + rng(key, seed, "y")) * spacing
            yield x, y


class _Ground:
    """What a prop is not allowed to stand on."""

    def __init__(self, layers: Layers, *, road_clearance_m: float):
        self.buildings = [b.geom for b in layers.buildings]
        self.building_tree = STRtree(self.buildings) if self.buildings else None

        # Carriageways as polygons, so a tree can sit on the verge but never in
        # the road. Pavement width is deliberately not added: the pavement is
        # exactly where a street tree belongs.
        bands = []
        for road in layers.roads:
            if road.tunnel:
                continue
            band = road.geom.buffer(road.width_m / 2 + road_clearance_m, cap_style=2)
            bands.extend(g for g in getattr(band, "geoms", [band])
                         if isinstance(g, Polygon) and not g.is_empty)
        self.roads = bands
        self.road_tree = STRtree(bands) if bands else None

        waters = [a.geom for a in layers.water]
        self.waters = waters
        self.water_tree = STRtree(waters) if waters else None

    def _hits(self, tree, shapes, point: Point) -> bool:
        if tree is None:
            return False
        return any(shapes[i].contains(point) for i in tree.query(point))

    def on_building(self, point: Point) -> bool:
        return self._hits(self.building_tree, self.buildings, point)

    def on_road(self, point: Point) -> bool:
        return self._hits(self.road_tree, self.roads, point)

    def on_water(self, point: Point) -> bool:
        return self._hits(self.water_tree, self.waters, point)

    def is_plantable_land(self, point: Point) -> bool:
        return not (self.on_building(point) or self.on_road(point)
                    or self.on_water(point))


def plant_greens(layers: Layers, ground: _Ground, seed: int, cfg: dict) -> list[Prop]:
    """Trees through the woods, the parks and — sparsely — the open ground."""
    spacings = {**SPACING_BY_KIND, **(cfg.get("spacing_by_kind") or {})}
    default_spacing = float(cfg.get("default_spacing_m", 26.0))
    min_area = float(cfg.get("min_green_area_m2", 150.0))

    # Pitches are drawn inside the parks that contain them, so keeping them
    # clear means subtracting them, not skipping them.
    bare = [a.geom for a in layers.green if a.kind in BARE]
    bare_tree = STRtree(bare) if bare else None

    def on_bare(point: Point) -> bool:
        if bare_tree is None:
            return False
        return any(bare[i].contains(point) for i in bare_tree.query(point))

    props: list[Prop] = []
    for area in layers.green:
        if area.kind in BARE or area.geom.area < min_area:
            continue
        spacing = float(spacings.get(area.kind, default_spacing))
        # Keep trunks off the very edge of a park, where they would overhang
        # the footpath outside it.
        inner = area.geom.buffer(-spacing * 0.35)
        if inner.is_empty:
            inner = area.geom
        test = prep(inner)

        for x, y in _jittered_grid(area.geom, spacing, seed, area.osm_id):
            point = Point(x, y)
            if not test.contains(point) or on_bare(point):
                continue
            if not ground.is_plantable_land(point):
                continue
            key = f"{area.osm_id}:{x:.1f}:{y:.1f}"
            props.append(Prop(
                x=x, y=y, kind="tree",
                height_m=5.0 + 5.0 * rng(key, seed, "h"),
                variant=int(rng(key, seed, "v") * 3),
            ))
    return props


def plant_streets(layers: Layers, ground: _Ground, seed: int, cfg: dict) -> list[Prop]:
    """Trees down the streets that would really be planted.

    Only the streets worth lining: a tree on every service road and car-park
    aisle would bury the city under canopy. Spacing is measured along the
    centreline and the trunk is offset onto the pavement.
    """
    spacing = float(cfg.get("street_spacing_m", 20.0))
    classes = set(cfg.get("street_classes",
                          ["primary", "secondary", "tertiary", "residential"]))
    share = float(cfg.get("street_share", 0.55))

    props: list[Prop] = []
    for road in layers.roads:
        if road.highway not in classes or road.tunnel or road.bridge:
            continue
        # Not every qualifying street is lined; a deterministic coin per street
        # keeps whole streets consistent rather than dotting trees at random.
        if rng(road.osm_id, seed, "lined") > share:
            continue

        line = road.geom
        if line.length < spacing:
            continue
        offset = road.width_m / 2 + float(cfg.get("street_offset_m", 2.2))

        steps = int(line.length // spacing)
        for step in range(1, steps + 1):
            along = step * spacing
            here = line.interpolate(along)
            ahead = line.interpolate(min(along + 1.0, line.length))
            dx, dy = ahead.x - here.x, ahead.y - here.y
            norm = math.hypot(dx, dy)
            if norm < 1e-6:
                continue
            # Perpendicular, both kerbs.
            px, py = -dy / norm, dx / norm
            for side in (1, -1):
                x = here.x + px * offset * side
                y = here.y + py * offset * side
                point = Point(x, y)
                if not ground.is_plantable_land(point):
                    continue
                key = f"{road.osm_id}:{step}:{side}"
                if rng(key, seed, "gap") < 0.18:
                    continue      # gaps for junctions, gates and driveways
                props.append(Prop(
                    x=x, y=y, kind="tree",
                    height_m=6.0 + 3.5 * rng(key, seed, "h"),
                    variant=int(rng(key, seed, "v") * 3),
                ))
    return props


def float_river(layers: Layers, seed: int, cfg: dict) -> list[Prop]:
    """Boats out in the channel, swans in close to the bank.

    Both are placed off the water's own geometry: boats inside a deep inward
    buffer so they sit in navigable water, swans in the ring between that
    buffer and the bank, which is where they actually are.
    """
    boat_spacing = float(cfg.get("boat_spacing_m", 220.0))
    swan_spacing = float(cfg.get("swan_spacing_m", 90.0))
    min_water = float(cfg.get("min_water_area_m2", 8000.0))
    deep_m = float(cfg.get("boat_clearance_m", 26.0))

    props: list[Prop] = []
    for area in layers.water:
        if area.geom.area < min_water:
            continue
        deep = area.geom.buffer(-deep_m)
        if deep.is_empty:
            continue
        shallow = area.geom.buffer(-6.0).difference(deep)
        deep_test, shallow_test = prep(deep), prep(shallow)

        # The channel's own direction, so hulls point along the river rather
        # than across it.
        minx, miny, maxx, maxy = area.geom.bounds
        river_angle = math.degrees(math.atan2(maxy - miny, maxx - minx))

        for x, y in _jittered_grid(area.geom, boat_spacing, seed, f"boat:{area.osm_id}"):
            point = Point(x, y)
            if not deep_test.contains(point):
                continue
            key = f"boat:{area.osm_id}:{x:.0f}:{y:.0f}"
            if rng(key, seed, "keep") < 0.45:
                continue
            props.append(Prop(
                x=x, y=y, kind="boat",
                height_m=7.0 + 5.0 * rng(key, seed, "len"),
                variant=int(rng(key, seed, "v") * 2),
                angle_deg=river_angle + (rng(key, seed, "yaw") - 0.5) * 24.0,
            ))

        for x, y in _jittered_grid(area.geom, swan_spacing, seed, f"swan:{area.osm_id}"):
            point = Point(x, y)
            if not shallow_test.contains(point):
                continue
            key = f"swan:{area.osm_id}:{x:.0f}:{y:.0f}"
            if rng(key, seed, "keep") < 0.72:
                continue
            props.append(Prop(
                x=x, y=y, kind="swan",
                height_m=1.1,
                variant=0,
                angle_deg=rng(key, seed, "yaw") * 360.0,
            ))
    return props


def decorate(layers: Layers, *, seed: int, config: dict | None = None,
             log=print) -> list[Prop]:
    """Place every prop. Returns them in no particular order.

    The renderer sorts props into its own painter's queue alongside buildings,
    so a tree in front of a terrace is drawn after it and one behind is drawn
    before it.
    """
    cfg = dict(config or {})
    ground = _Ground(layers, road_clearance_m=float(cfg.get("road_clearance_m", 0.8)))

    greens = plant_greens(layers, ground, seed, cfg)
    streets = plant_streets(layers, ground, seed, cfg)
    river = float_river(layers, seed, cfg)

    trees = len(greens) + len(streets)
    boats = sum(1 for p in river if p.kind == "boat")
    swans = sum(1 for p in river if p.kind == "swan")
    log(f"  decorated: {trees} trees ({len(streets)} lining streets), "
        f"{boats} boats, {swans} swans")
    return [*greens, *streets, *river]
