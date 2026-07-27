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
  keeps its shape intact; snapping edge by edge would shred it.
* **Water and greens** are soft outlines. They are simplified hard first, so
  snapping produces a few long deliberate reaches instead of a jagged staircase.
"""

from __future__ import annotations

import math
from dataclasses import replace

from shapely.affinity import rotate as shapely_rotate
from shapely.geometry import LineString, Polygon

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


def rigid_snap_polygon(poly: Polygon, rotation: float,
                       fold: float = CLEAN_FOLD_DEG) -> Polygon:
    """Rotate a footprint bodily so its dominant edge lands on a crisp direction.

    Rotating rather than snapping edge by edge keeps the building's own shape —
    right angles stay right angles, and a terrace stays a terrace.
    """
    coords = list(poly.exterior.coords)
    if len(coords) < 3:
        return poly

    # The longest edge decides the building's orientation.
    best_len, best_b = 0.0, None
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length > best_len:
            best_len, best_b = length, _bearing(dx, dy)
    if best_b is None or best_len <= 0:
        return poly

    b = rotated_bearing(best_b, rotation)
    delta = (round(b / fold) * fold) - b
    if abs(delta) < 1e-9:
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


def schematize(
    layers: Layers,
    rotation: float,
    *,
    road_simplify_m: float = 6.0,
    water_simplify_m: float = 30.0,
    log=print,
) -> Layers:
    """Push every layer onto the isometric grid."""
    out = Layers(crs=layers.crs)

    out.roads = snap_network(layers.roads, rotation, simplify_m=road_simplify_m)
    out.rail = snap_network(layers.rail, rotation, simplify_m=road_simplify_m)
    out.waterways = snap_network(layers.waterways, rotation, simplify_m=12.0)

    out.buildings = [
        replace(b, geom=rigid_snap_polygon(b.geom, rotation))
        for b in layers.buildings
    ]
    out.water = [
        Area(a.osm_id,
             snap_ring(a.geom, rotation,
                       # Scale the tolerance down for small ponds so they are
                       # simplified, not erased.
                       simplify_m=water_simplify_m if a.geom.area > 20000 else 8.0),
             a.kind, a.name)
        for a in layers.water
    ]
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
