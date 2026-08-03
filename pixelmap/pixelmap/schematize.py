"""Stage 2 — schematize.

Nudges the city onto the isometric grid. Every street, bank and building edge is
pushed to the nearest of the eight directions that render as a clean pixel line,
because a road two degrees off a crisp slope reads as a mistake while a road
snapped fully onto it reads as a decision.

Three different treatments, because the geometry types want different things:

* **Streets** are a connected network, so they cannot be snapped one at a time —
  junctions would pull apart. Segments declare the direction they want and node
  positions are relaxed until the network agrees.
* **Buildings** are rigid objects. Rotating each footprint bodily onto the grid
  keeps its shape intact; snapping edge by edge would shred it. A building only
  gets rotated if it has an orientation to be rotated onto — see
  `rigid_snap_polygon`.
* **Water and greens** are soft outlines. They are simplified hard first, so
  snapping produces a few long deliberate reaches instead of a jagged staircase.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import replace

from shapely.affinity import rotate as shapely_rotate
from shapely.affinity import translate
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .bearings import CLEAN_FOLD_DEG, rotated_bearing
from .extract import Area, Building, Layers, Road

#: Vertices closer than this are treated as the same junction.
NODE_TOLERANCE_M = 1.5


def _bearing(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dx, dy)) % 360.0


def _unit_for(bearing: float) -> tuple[float, float]:
    r = math.radians(bearing)
    return math.sin(r), math.cos(r)


def snap_direction(dx: float, dy: float, rotation: float,
                   fold: float = CLEAN_FOLD_DEG) -> tuple[float, float]:
    """Unit vector for the crisp direction nearest to (dx, dy)."""
    b = rotated_bearing(_bearing(dx, dy), rotation)
    return _unit_for((round(b / fold) * fold + rotation) % 360.0)


def _key(x: float, y: float) -> tuple[int, int]:
    return (round(x / NODE_TOLERANCE_M), round(y / NODE_TOLERANCE_M))


def snap_network(
    roads: list[Road],
    rotation: float,
    *,
    simplify_m: float = 6.0,
    min_length_m: float = 4.0,
    iterations: int = 60,
    anchor: float = 0.04,
) -> list[Road]:
    """Snap a road network onto the crisp directions, keeping junctions joined.

    Each segment names the direction it wants and proposes where its two ends
    should sit; every node then moves to the average of what its segments asked
    for. Repeating that converges on a network where nearly every segment runs
    along a crisp direction and the junctions still meet.

    A weak pull back toward the original position (`anchor`) stops the whole
    network drifting off the landmarks it is supposed to sit between.
    """
    nodes: dict[tuple[int, int], list[float]] = {}
    original: dict[tuple[int, int], tuple[float, float]] = {}
    chains: list[list[tuple[int, int]]] = []

    for road in roads:
        line = road.geom.simplify(simplify_m, preserve_topology=False)
        coords = list(line.coords)
        chain: list[tuple[int, int]] = []
        for x, y in coords:
            k = _key(x, y)
            if k not in nodes:
                nodes[k] = [x, y]
                original[k] = (x, y)
            if not chain or chain[-1] != k:
                chain.append(k)
        if len(chain) >= 2:
            chains.append(chain)

    # Segment list with the length each one should keep.
    segments: list[tuple[tuple[int, int], tuple[int, int], float]] = []
    for chain in chains:
        for a, b in zip(chain, chain[1:]):
            ax, ay = original[a]
            bx, by = original[b]
            length = math.hypot(bx - ax, by - ay)
            if length >= min_length_m:
                segments.append((a, b, length))

    for _ in range(iterations):
        acc: dict[tuple[int, int], list[float]] = {}
        for a, b, length in segments:
            ax, ay = nodes[a]
            bx, by = nodes[b]
            ux, uy = snap_direction(bx - ax, by - ay, rotation)
            mx, my = (ax + bx) / 2, (ay + by) / 2
            half = length / 2
            for k, tx, ty in (
                (a, mx - ux * half, my - uy * half),
                (b, mx + ux * half, my + uy * half),
            ):
                slot = acc.setdefault(k, [0.0, 0.0, 0.0])
                slot[0] += tx
                slot[1] += ty
                slot[2] += 1.0

        for k, (sx, sy, n) in acc.items():
            if n == 0:
                continue
            tx, ty = sx / n, sy / n
            ox, oy = original[k]
            nodes[k] = [
                tx * (1 - anchor) + ox * anchor,
                ty * (1 - anchor) + oy * anchor,
            ]

    # Rebuild each road from the relaxed node positions.
    out: list[Road] = []
    for road in roads:
        coords = list(road.geom.simplify(simplify_m, preserve_topology=False).coords)
        chain: list[tuple[int, int]] = []
        for x, y in coords:
            k = _key(x, y)
            if not chain or chain[-1] != k:
                chain.append(k)
        if len(chain) < 2:
            continue
        pts = [tuple(nodes[k]) for k in chain]
        deduped = [pts[0]]
        for p in pts[1:]:
            if math.dist(p, deduped[-1]) > 1e-6:
                deduped.append(p)
        if len(deduped) >= 2:
            out.append(replace(road, geom=LineString(deduped)))
    return out


#: Below this, a footprint's walls disagree too much to be pointing anywhere.
#: Ordinary buildings are rectangular and score 1.000; the exceptions are round
#: or curved — King John's Castle scores 0.36, the Riverpoint tower 0.08.
MIN_ORIENTATION_COHERENCE = 0.5


def polygon_orientation(poly: Polygon, rotation: float,
                        fold: float = CLEAN_FOLD_DEG) -> tuple[float, float] | None:
    """(rotation onto the nearest crisp direction, coherence) for a footprint.

    Orientation is the length-weighted circular mean of the edge bearings, taken
    at the harmonic that collapses the fold's symmetry — the same trick
    `bearings.fit_grid` uses on the street network, at 45 degrees instead of 90.
    Long walls therefore outvote short ones, and a building speaks with one
    voice rather than through whichever single edge happens to be longest.

    Coherence is that mean's normalised magnitude: 1 when every edge agrees on
    the same direction (any rectangle, whatever its angle), 0 when they point
    everywhere. It is what tells a terrace from a drum tower.
    """
    coords = list(poly.exterior.coords)
    if len(coords) < 3:
        return None

    harmonic = 360.0 / fold
    total = 0.0
    phasor = 0j
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            continue
        bearing = rotated_bearing(_bearing(dx, dy), rotation)
        total += length
        phasor += length * cmath.exp(1j * harmonic * math.radians(bearing))

    if total <= 0 or phasor == 0:
        return None

    coherence = abs(phasor) / total
    dominant = (math.degrees(cmath.phase(phasor)) / harmonic) % fold
    # Turn the short way onto the crisp direction, never more than half a fold.
    delta = -dominant if dominant <= fold / 2 else fold - dominant
    return delta, coherence


def rigid_snap_polygon(poly: Polygon, rotation: float,
                       fold: float = CLEAN_FOLD_DEG,
                       min_coherence: float = MIN_ORIENTATION_COHERENCE) -> Polygon:
    """Rotate a footprint bodily so its walls land on a crisp direction.

    Rotating rather than snapping edge by edge keeps the building's own shape —
    right angles stay right angles, and a terrace stays a terrace.

    A round or irregular footprint is left exactly where it is. It has no
    dominant wall direction, so any rotation chosen for it is arbitrary, and the
    arbitrary rotation is not free: King John's Castle was being swung 19
    degrees off true and left jutting into the Shannon instead of sitting flush
    along the bank. Rotating a building is a licence worth taking when it buys
    crisp walls; on a drum tower it buys nothing and costs the river.
    """
    result = polygon_orientation(poly, rotation, fold)
    if result is None:
        return poly
    delta, coherence = result
    if coherence < min_coherence or abs(delta) < 1e-9:
        return poly
    # Shapely rotates counter-clockwise; bearings run clockwise.
    return shapely_rotate(poly, -delta, origin="centroid", use_radians=False)


def _densify(coords: list[tuple[float, float]], max_edge_m: float) -> list[tuple[float, float]]:
    """Split long edges so no single edge can swing far when snapped."""
    out: list[tuple[float, float]] = []
    n = len(coords)
    for i in range(n):
        ax, ay = coords[i]
        bx, by = coords[(i + 1) % n]
        out.append((ax, ay))
        length = math.hypot(bx - ax, by - ay)
        if length > max_edge_m:
            steps = int(length // max_edge_m)
            for s in range(1, steps + 1):
                f = s / (steps + 1)
                out.append((ax + (bx - ax) * f, ay + (by - ay) * f))
    return out


def snap_ring(
    poly: Polygon,
    rotation: float,
    *,
    simplify_m: float = 25.0,
    max_edge_m: float = 120.0,
    iterations: int = 60,
    anchor: float = 0.12,
) -> Polygon:
    """Snap an outline onto crisp directions while keeping it where it was.

    Three things have to hold at once, and each guards against a specific way
    this goes wrong:

    * **Simplify first**, or snapping turns every surveyed wiggle into a
      staircase instead of a few deliberate reaches.
    * **Cap edge length**, or a single multi-kilometre edge — the Shannon is
      mapped as one polygon running 18 km — swings its far end hundreds of
      metres when rotated up to 22.5 degrees onto a crisp direction.
    * **Anchor to the original position**, or the ring relaxes into spikes:
      every edge pulls on its neighbours with nothing holding the shape in
      place.

    Consecutive edges along a straight reach snap to the same direction and
    merge, so a gentle curve becomes a handful of long clean runs rather than a
    sawtooth.
    """
    simple = poly.simplify(simplify_m, preserve_topology=True)
    if simple.is_empty or not isinstance(simple, Polygon):
        return poly
    coords = _densify(list(simple.exterior.coords)[:-1], max_edge_m)
    n = len(coords)
    if n < 4:
        return simple

    pts = [list(c) for c in coords]
    lengths = [math.dist(coords[i], coords[(i + 1) % n]) for i in range(n)]

    for _ in range(iterations):
        acc = [[0.0, 0.0, 0.0] for _ in range(n)]
        for i in range(n):
            j = (i + 1) % n
            ax, ay = pts[i]
            bx, by = pts[j]
            if lengths[i] < 1e-9:
                continue
            ux, uy = snap_direction(bx - ax, by - ay, rotation)
            mx, my = (ax + bx) / 2, (ay + by) / 2
            half = lengths[i] / 2
            for k, tx, ty in ((i, mx - ux * half, my - uy * half),
                              (j, mx + ux * half, my + uy * half)):
                acc[k][0] += tx
                acc[k][1] += ty
                acc[k][2] += 1.0
        for i in range(n):
            sx, sy, c = acc[i]
            if not c:
                continue
            ox, oy = coords[i]
            pts[i] = [
                (sx / c) * (1 - anchor) + ox * anchor,
                (sy / c) * (1 - anchor) + oy * anchor,
            ]

    try:
        out = Polygon([tuple(p) for p in pts])
        if not out.is_valid:
            out = out.buffer(0)
        if isinstance(out, Polygon) and not out.is_empty and out.area > 0:
            return out
    except Exception:
        pass
    return simple


def widen_streets(
    buildings: list[Building],
    roads: list[Road],
    rotation: float,
    amount_m: float,
    *,
    max_distance_m: float = 30.0,
) -> list[Building]:
    """Push buildings back from the street they front.

    In an isometric view a row of buildings hides the feet of whatever stands
    behind it, and the cure most renderers reach for — stretching everything
    vertically — distorts the buildings themselves. Widening the street instead
    buys the same clearance and leaves the architecture honest, which is what
    isometric city art has always quietly done.

    The displacement is snapped to a crisp direction so buildings stay on the
    grid the schematize stage just put them on. Perpendiculars of crisp
    directions are themselves crisp, so fronting geometry stays square.
    """
    if amount_m <= 0:
        return buildings

    streets = [r for r in roads if r.importance <= 6]
    if not streets:
        return buildings
    tree = STRtree([r.geom for r in streets])

    out: list[Building] = []
    for b in buildings:
        centroid = b.geom.centroid
        line = streets[tree.nearest(centroid)].geom
        distance = line.distance(centroid)
        if distance > max_distance_m or distance < 1e-6:
            out.append(b)
            continue
        foot = line.interpolate(line.project(centroid))
        dx, dy = centroid.x - foot.x, centroid.y - foot.y
        if math.hypot(dx, dy) < 1e-6:
            out.append(b)
            continue
        ux, uy = snap_direction(dx, dy, rotation)
        out.append(replace(b, geom=translate(b.geom, ux * amount_m, uy * amount_m)))
    return out


def schematize(
    layers: Layers,
    rotation: float,
    *,
    road_simplify_m: float = 6.0,
    water_simplify_m: float = 30.0,
    street_widen_m: float = 0.0,
    min_coherence: float = MIN_ORIENTATION_COHERENCE,
    log=print,
) -> Layers:
    """Push every layer onto the isometric grid."""
    out = Layers(crs=layers.crs)

    out.roads = snap_network(layers.roads, rotation, simplify_m=road_simplify_m)
    out.rail = snap_network(layers.rail, rotation, simplify_m=road_simplify_m)
    out.waterways = snap_network(layers.waterways, rotation, simplify_m=12.0)

    snapped, round_ones = [], 0
    for b in layers.buildings:
        oriented = polygon_orientation(b.geom, rotation)
        if oriented is None:
            geom = b.geom
        elif oriented[1] < min_coherence:
            # Round or irregular: no wall direction to snap onto, so leave it
            # exactly where it stands rather than swinging it somewhere untrue.
            geom = b.geom
            round_ones += 1
        else:
            geom = shapely_rotate(b.geom, -oriented[0], origin="centroid")
        snapped.append(replace(b, geom=geom))
    if round_ones:
        log(f"  {round_ones} buildings left unrotated (no dominant wall direction)")
    out.buildings = widen_streets(snapped, out.roads, rotation, street_widen_m)
    out.water = [
        Area(a.osm_id,
             snap_ring(a.geom, rotation,
                       # Scale the tolerance down for small ponds so they are
                       # simplified, not erased.
                       simplify_m=water_simplify_m if a.geom.area > 20000 else 8.0),
             a.kind, a.name)
        for a in layers.water
    ]
    out.water = _keep_dry_land(out.water, layers.water, out.buildings, log=log)
    out.green = [
        Area(a.osm_id, snap_ring(a.geom, rotation, simplify_m=15.0), a.kind, a.name)
        for a in layers.green
    ]
    out.urban = [
        Area(a.osm_id, snap_ring(a.geom, rotation, simplify_m=15.0), a.kind, a.name)
        for a in layers.urban
    ]
    out.pois = list(layers.pois)

    log(f"  schematized: {out.summary()}")
    return out


#: A building overlapping raw water by more than this really does stand over it
#: — a boathouse, a jetty, a quay shed — and the river is allowed to keep it.
WET_BUILDING_SHARE = 0.15


def _keep_dry_land(water: list[Area], raw_water: list[Area],
                   buildings: list[Building], *, log=print) -> list[Area]:
    """Stop a stylised bank from flooding buildings that stand on dry land.

    Water is simplified far harder than anything else — 45 m for the Shannon —
    so that the river reads as a few long deliberate reaches instead of a
    snapped staircase. That is a deliberate liberty, but a 45 m liberty taken
    along a bank lined with buildings will swallow some of them: King John's
    Castle sits entirely on land in OSM and ended up 19% under the river.

    Rather than weaken the simplification everywhere for the sake of a few
    metres of bank, the bank keeps its bold line and gives way where a building
    was standing on dry land to begin with. Dryness is judged against the raw
    water, before simplification, so the test cannot be corrupted by the very
    liberty it is checking.
    """
    if not water or not buildings:
        return water

    raw = unary_union([a.geom for a in raw_water if not a.geom.is_empty])
    if raw.is_empty:
        return water

    # Only buildings the simplified water actually reaches can be flooded by it,
    # and that is a waterfront handful out of twenty thousand — so let the index
    # find them rather than intersecting the whole city against the river.
    shapes = [a.geom for a in water]
    tree = STRtree(shapes)
    dry = []
    for b in buildings:
        if b.geom.is_empty or b.geom.area <= 0:
            continue
        if not any(shapes[i].intersects(b.geom) for i in tree.query(b.geom)):
            continue
        if b.geom.intersection(raw).area / b.geom.area <= WET_BUILDING_SHARE:
            dry.append(b.geom)
    if not dry:
        return water

    dry_union = unary_union(dry)
    out, rescued = [], 0.0
    for area in water:
        flooded = area.geom.intersection(dry_union).area
        if flooded <= 0:
            out.append(area)
            continue
        rescued += flooded
        trimmed = area.geom.difference(dry_union)
        if trimmed.is_empty:
            continue
        # A difference can shatter one bank into slivers; keep the polygons.
        if trimmed.geom_type == "Polygon":
            out.append(Area(area.osm_id, trimmed, area.kind, area.name))
        else:
            for part in trimmed.geoms:
                if part.geom_type == "Polygon" and part.area > 1.0:
                    out.append(Area(area.osm_id, part, area.kind, area.name))
    if rescued > 0:
        log(f"  water pulled back off {rescued:.0f} m² of dry land")
    return out


def crisp_share(roads: list[Road], rotation: float, tolerance_deg: float = 2.0) -> float:
    """Share of road length running along a crisp direction. 1.0 after snapping."""
    total = aligned = 0.0
    for road in roads:
        coords = list(road.geom.coords)
        for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            b = rotated_bearing(_bearing(dx, dy), rotation) % CLEAN_FOLD_DEG
            total += length
            if min(b, CLEAN_FOLD_DEG - b) <= tolerance_deg:
                aligned += length
    return aligned / total if total else 0.0
