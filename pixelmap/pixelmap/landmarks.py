"""Landmark models — the buildings that make it Limerick rather than a city.

Generated blocks give the fabric; a dozen named buildings give the piece its
face. Rather than hand-drawn sprites pinned to coordinates, each landmark is a
recipe that reads its own OSM footprint and returns extruded masses. Two reasons:

* the schematize stage rotates footprints bodily onto the isometric grid, so any
  sprite pinned to a lat/lon would drift off its own building;
* a recipe survives a re-fetch, a change of rotation and a change of scale,
  where a sprite has to be redrawn for each.

So a castle is "the footprint's round bulges, extruded taller than the wall
between them, all of it crenellated", and that sentence is what the code says.
Heights and the handful of judgement calls a footprint cannot supply — which end
of a church carries the tower — live in `cities/<city>/landmarks.toml`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

#: Compass directions usable as an anchor hint, as unit vectors in a projected
#: CRS where +x is east and +y is north.
COMPASS = {
    "north": (0.0, 1.0), "south": (0.0, -1.0),
    "east": (1.0, 0.0), "west": (-1.0, 0.0),
    "northeast": (0.7071, 0.7071), "northwest": (-0.7071, 0.7071),
    "southeast": (0.7071, -0.7071), "southwest": (-0.7071, -0.7071),
}


@dataclass(frozen=True)
class Mass:
    """One extruded chunk of a landmark, in world metres."""

    poly: Polygon
    base_m: float
    top_m: float
    material: str = "limestone"
    #: "flat" | "battlement" | "gabled" | "hipped" | "spire" | "cone" | "open"
    roof: str = "flat"
    #: Extra height of the roof feature above `top_m`.
    roof_m: float = 0.0
    #: "none" | "slit" | "lancet" | "arcade" | "sash" | "clerestory" | "curtain"
    openings: str = "none"
    roof_material: str | None = None


@dataclass(frozen=True)
class Model:
    """One landmark's configuration, as read from landmarks.toml."""

    osm: str
    name: str
    recipe: str
    #: Ids this model already accounts for — OSM often maps the same landmark
    #: twice (a solid footprint and a walled relation), and drawing both buries
    #: the detailed one under the crude one.
    supersedes: tuple[str, ...] = ()
    params: dict = field(default_factory=dict)

    def p(self, key: str, default=None):
        return self.params.get(key, default)


# --------------------------------------------------------------------------
# Footprint geometry


def obb_frame(poly: Polygon):
    """(centre, long-axis unit vector, long length, short length)."""
    box = poly.minimum_rotated_rectangle
    if not isinstance(box, Polygon):
        c = poly.centroid
        return (c.x, c.y), (1.0, 0.0), 1.0, 1.0
    pts = list(box.exterior.coords)[:4]
    ea = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    eb = (pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
    la, lb = math.hypot(*ea), math.hypot(*eb)
    long_v, long_m, short_m = (ea, la, lb) if la >= lb else (eb, lb, la)
    n = math.hypot(*long_v) or 1.0
    cx = sum(p[0] for p in pts) / 4
    cy = sum(p[1] for p in pts) / 4
    return (cx, cy), (long_v[0] / n, long_v[1] / n), long_m, short_m


def block_at(poly: Polygon, compass: str, side_m: float, *, cover: float = 0.8) -> Polygon:
    """A square block seated at one end of the footprint, aligned to its axis.

    The oriented box is not the building: for anything L-shaped or notched, its
    end can hang over open ground, and a tower placed there floats beside its
    own church. So the block slides in along the axis until the footprint is
    actually under it.
    """
    (cx, cy), (ux, uy), long_m, _ = obb_frame(poly)
    want = COMPASS.get(compass, (-1.0, 0.0))
    sign = 1.0 if (ux * want[0] + uy * want[1]) >= 0 else -1.0
    ax, ay = ux * sign, uy * sign
    px, py = -ay, ax                                   # the short axis
    h = side_m / 2

    def square(offset: float) -> Polygon:
        ex, ey = cx + ax * offset, cy + ay * offset
        return Polygon([
            (ex + ax * h + px * h, ey + ay * h + py * h),
            (ex + ax * h - px * h, ey + ay * h - py * h),
            (ex - ax * h - px * h, ey - ay * h - py * h),
            (ex - ax * h + px * h, ey - ay * h + py * h),
        ])

    start = max(0.0, long_m / 2 - h)
    best = square(start)
    steps = max(1, int(start / max(0.5, side_m / 4)))
    for i in range(steps + 1):
        block = square(start * (1 - i / steps))
        if block.intersection(poly).area >= cover * block.area:
            return block
        if block.intersection(poly).area > best.intersection(poly).area:
            best = block
    return best


def axis_strip(poly: Polygon, width_m: float, *, shrink_m: float = 0.0) -> Polygon:
    """A narrow band running the length of the footprint's long axis.

    What a ridge is, geometrically — used for the glazed lantern along the top
    of a train shed.
    """
    (cx, cy), (ux, uy), long_m, _ = obb_frame(poly)
    half_len = max(1.0, long_m / 2 - shrink_m)
    px, py = -uy, ux
    h = width_m / 2
    return Polygon([
        (cx + ux * half_len + px * h, cy + uy * half_len + py * h),
        (cx + ux * half_len - px * h, cy + uy * half_len - py * h),
        (cx - ux * half_len - px * h, cy - uy * half_len - py * h),
        (cx - ux * half_len + px * h, cy - uy * half_len + py * h),
    ])


def square(centre: tuple[float, float], side_m: float) -> Polygon:
    cx, cy = centre
    h = side_m / 2
    return Polygon([(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)])


def circle(centre: tuple[float, float], radius: float, sides: int = 24) -> Polygon:
    cx, cy = centre
    return Polygon([
        (cx + radius * math.cos(2 * math.pi * i / sides),
         cy + radius * math.sin(2 * math.pi * i / sides))
        for i in range(sides)
    ])


def _fit_circle(pts) -> tuple[tuple[float, float], float, float]:
    """Kasa algebraic circle fit. Returns (centre, radius, mean residual)."""
    p = np.asarray(pts, dtype=float)
    a = np.column_stack([2 * p[:, 0], 2 * p[:, 1], np.ones(len(p))])
    (cx, cy, c), *_ = np.linalg.lstsq(a, (p ** 2).sum(axis=1), rcond=None)
    r = math.sqrt(max(c + cx * cx + cy * cy, 0.0))
    resid = float(np.abs(np.hypot(p[:, 0] - cx, p[:, 1] - cy) - r).mean())
    return (float(cx), float(cy)), r, resid


def round_bulges(
    poly: Polygon,
    *,
    min_turn_deg: float = 100.0,
    max_seg_m: float = 8.0,
    radius_m: tuple[float, float] = (2.0, 12.0),
) -> list[tuple[tuple[float, float], float]]:
    """Circular bastions read off a footprint's own outline.

    A drum tower is surveyed as a run of short segments all turning the same
    way through more than a half circle. Finding them from the geometry — rather
    than listing tower coordinates — means the castle keeps its towers through a
    re-fetch, and any other round-towered building gets them for free.
    """
    ring = list(poly.exterior.coords)[:-1]
    n = len(ring)
    if n < 8:
        return []

    turn = []
    for i in range(n):
        p0, p1, p2 = ring[(i - 1) % n], ring[i], ring[(i + 1) % n]
        a = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        b = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        turn.append(math.degrees((b - a + math.pi) % (2 * math.pi) - math.pi))
    sign = 1.0 if sum(turn) > 0 else -1.0
    tight = [turn[i] * sign > 3.0 and math.dist(ring[(i - 1) % n], ring[i]) < max_seg_m
             for i in range(n)]

    found: list[tuple[tuple[float, float], float]] = []
    consumed: set[int] = set()
    for start in range(n):
        if not tight[start] or start in consumed:
            continue
        run: list[tuple[float, float]] = []
        acc = 0.0
        j = start
        while len(run) < n and tight[j % n] and (j % n) not in consumed:
            run.append(ring[j % n])
            consumed.add(j % n)
            acc += turn[j % n] * sign
            j += 1
        if acc < min_turn_deg or len(run) < 3:
            continue
        centre, radius, resid = _fit_circle(run)
        if not (radius_m[0] <= radius <= radius_m[1] and resid < 0.35 * radius):
            continue
        # The same drum can be picked up twice when a run wraps the ring start.
        if any(math.dist(centre, c) < max(r, radius) for c, r in found):
            continue
        found.append((centre, radius))
    return found


# --------------------------------------------------------------------------
# Recipes. Each takes the landmark's footprints and its config, returns masses.


def _outline(polys: list[Polygon]) -> Polygon:
    merged = unary_union(polys)
    if merged.geom_type == "MultiPolygon":
        merged = max(merged.geoms, key=lambda g: g.area)
    return merged


def castle(polys: list[Polygon], m: Model) -> list[Mass]:
    """Curtain wall and drum towers, all crenellated, no windows.

    The footprint carries both: the enclosure is the ring (its courtyard is a
    hole), and the towers are the round bulges along it.
    """
    shell = _outline(polys)
    wall_m = float(m.p("wall_m", 11.0))
    tower_m = float(m.p("tower_m", 16.0))
    masses = [Mass(shell, 0.0, wall_m, m.p("material", "limestone"),
                   roof="battlement", roof_m=float(m.p("merlon_m", 1.6)),
                   openings="slit")]
    for centre, radius in round_bulges(shell, radius_m=(2.5, 12.0)):
        masses.append(Mass(
            circle(centre, radius * 1.02), 0.0, tower_m,
            m.p("material", "limestone"),
            roof="battlement", roof_m=float(m.p("merlon_m", 1.6)), openings="slit",
        ))
    return masses


def church(polys: list[Polygon], m: Model) -> list[Mass]:
    """Nave under a steep ridge, with a tower — and maybe a spire — at one end."""
    shell = _outline(polys)
    nave_m = float(m.p("nave_m", 14.0))
    tower_side = float(m.p("tower_side_m", 9.0))
    tower_m = float(m.p("tower_m", 0.0))
    spire_m = float(m.p("spire_m", 0.0))
    material = m.p("material", "limestone")
    roof_material = m.p("roof_material", "slate")

    masses = [Mass(shell, 0.0, nave_m, material, roof="gabled",
                   roof_m=float(m.p("ridge_m", 5.0)), openings="lancet",
                   roof_material=roof_material)]
    if tower_m > 0:
        tower = block_at(shell, m.p("tower_at", "west"), tower_side)
        masses.append(Mass(
            tower, 0.0, tower_m, material,
            roof="spire" if spire_m > 0 else "battlement",
            roof_m=spire_m if spire_m > 0 else float(m.p("merlon_m", 1.4)),
            openings="lancet",
            roof_material=m.p("spire_material", material) if spire_m > 0 else None,
        ))
    return masses


def canopy(polys: list[Polygon], m: Model) -> list[Mass]:
    """A market roof on posts — the thing that is not a building.

    `building=roof` means exactly what it says, and extruding it like a shed
    turns an open market into a warehouse.
    """
    shell = max(polys, key=lambda p: p.area)
    return [Mass(shell, 0.0, float(m.p("eaves_m", 8.5)), m.p("material", "limestone"),
                 roof="open", roof_m=float(m.p("ridge_m", 3.0)), openings="none",
                 roof_material=m.p("roof_material", "canopy"))]


def trainshed(polys: list[Polygon], m: Model) -> list[Mass]:
    """A long shed with a ridge down the platforms and a glazed upper wall.

    The lantern along the ridge is what stops a hundred-metre roof reading as a
    single slab — and it is what a Victorian train shed actually has, because
    the platforms underneath need daylight and somewhere to vent the smoke.
    """
    shell = _outline(polys)
    eaves = float(m.p("eaves_m", 9.0))
    ridge = float(m.p("ridge_m", 6.0))
    lantern_m = float(m.p("lantern_m", 2.2))
    masses = [Mass(shell, 0.0, eaves, m.p("material", "brick"),
                   roof="gabled", roof_m=ridge, openings="clerestory",
                   roof_material=m.p("roof_material", "slate"))]
    if lantern_m > 0:
        masses.append(Mass(
            axis_strip(shell, float(m.p("lantern_w_m", 5.0)), shrink_m=8.0),
            eaves + ridge * 0.72, eaves + ridge + lantern_m * 0.4,
            m.p("lantern_material", "glass"),
            roof="gabled", roof_m=lantern_m, openings="clerestory",
            roof_material=m.p("roof_material", "slate"),
        ))
    return masses


def monument(polys: list[Polygon], m: Model) -> list[Mass]:
    """A stepped plinth with something on top — the Treaty Stone shape.

    Too small to model in detail at any print size we will use, so what has to
    read is the silhouette: a wide base, a narrower plinth, a block above it.
    """
    base = _outline(polys)
    (cx, cy), _, long_m, _ = obb_frame(base)
    side = float(m.p("side_m", long_m or 3.0))
    material = m.p("material", "limestone")
    steps = float(m.p("step_m", 0.45))
    plinth = float(m.p("plinth_m", 1.9))
    stone = float(m.p("stone_m", 1.1))
    return [
        Mass(square((cx, cy), side), 0.0, steps, material, roof="flat"),
        Mass(square((cx, cy), side * 0.62), steps, steps + plinth, material, roof="flat"),
        Mass(square((cx, cy), side * 0.40), steps + plinth,
             steps + plinth + stone, m.p("stone_material", "limestone_dark"),
             roof="flat"),
    ]


def palazzo(polys: list[Polygon], m: Model) -> list[Mass]:
    """A dressed-stone civic block: taller than its tagging, hipped, sash windows."""
    shell = _outline(polys)
    return [Mass(shell, 0.0, float(m.p("eaves_m", 13.0)), m.p("material", "limestone"),
                 roof="hipped", roof_m=float(m.p("ridge_m", 3.2)), openings="sash",
                 roof_material=m.p("roof_material", "slate"))]


def tower_block(polys: list[Polygon], m: Model) -> list[Mass]:
    """A modern glazed tower — banded glazing rather than punched windows."""
    shell = _outline(polys)
    return [Mass(shell, 0.0, float(m.p("eaves_m", 55.0)), m.p("material", "glass"),
                 roof="flat", openings="curtain")]


RECIPES = {
    "castle": castle,
    "church": church,
    "canopy": canopy,
    "trainshed": trainshed,
    "palazzo": palazzo,
    "tower_block": tower_block,
    "monument": monument,
}

#: Recipes that take a point rather than a footprint. A monument has no mapped
#: outline — the Treaty Stone is a single OSM node — so the renderer stands in a
#: square of `side_m` at the point and the recipe builds on that.
POINT_RECIPES = {"monument"}


def load_models(config: dict) -> tuple[dict[str, Model], set[str]]:
    """Read `[[model]]` entries. Returns (models by osm id, superseded ids)."""
    models: dict[str, Model] = {}
    superseded: set[str] = set()
    for entry in config.get("model", []):
        known = {"osm", "name", "recipe", "supersedes"}
        model = Model(
            osm=entry["osm"],
            name=entry.get("name", entry["osm"]),
            recipe=entry["recipe"],
            supersedes=tuple(entry.get("supersedes", ())),
            params={k: v for k, v in entry.items() if k not in known},
        )
        if model.recipe not in RECIPES:
            raise ValueError(f"landmark {model.name!r}: unknown recipe {model.recipe!r} "
                             f"(have {', '.join(sorted(RECIPES))})")
        models[model.osm] = model
        superseded.update(model.supersedes)
    return models, superseded


def masses_for(model: Model, polys: list[Polygon]) -> list[Mass]:
    return RECIPES[model.recipe](polys, model)
