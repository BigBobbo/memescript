"""Low-level isometric drawing primitives.

Everything here works in projected screen pixels and knows nothing about OSM.
It exists so the generic building renderer and the landmark models can share one
notion of what a lifted wall, a shaded face and a prism are — two implementations
of "extrude this ring" would drift apart within a week.

Screen y grows downward, so a face whose outward normal has positive y points at
the viewer, and the light comes from the left.
"""

from __future__ import annotations

import hashlib
import math

from PIL import ImageDraw

from .iso import STOREY_M, Camera


def shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in colour)


def rng(key: str, seed: int, salt: str = "") -> float:
    """A stable pseudo-random number in [0, 1) for a given key."""
    digest = hashlib.blake2b(f"{seed}:{key}:{salt}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2 ** 64


def metre_px(camera: Camera) -> float:
    """Screen pixels per metre of height."""
    return camera.storey_px / STOREY_M


def wall_point(a, b, lift, u, v):
    """Facade space to screen. u runs along the wall, v from ground to eaves."""
    return (a[0] + (b[0] - a[0]) * u,
            a[1] + (b[1] - a[1]) * u - lift * v)


def wall_rect(a, b, lift, u0, u1, v0, v1):
    return [wall_point(a, b, lift, u0, v0), wall_point(a, b, lift, u1, v0),
            wall_point(a, b, lift, u1, v1), wall_point(a, b, lift, u0, v1)]


def outward_normal_fn(ground: list[tuple[float, float]]):
    """A test for which way a wall faces, independent of vertex winding.

    OSM footprints wind both ways — two thirds of Limerick's are clockwise — so
    reading facing off the vertex order details the back of most buildings.
    Comparing each wall's normal against the footprint centroid does not care.
    """
    n = len(ground) - 1
    cx = sum(p[0] for p in ground[:n]) / n
    cy = sum(p[1] for p in ground[:n]) / n

    def outward(a, b):
        nx, ny = (b[1] - a[1]), -(b[0] - a[0])
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny
        return nx, ny

    return outward


def prism(
    draw: ImageDraw.ImageDraw,
    camera: Camera,
    ring: list[tuple[float, float]],
    base_px: float,
    top_px: float,
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    outline: tuple[int, int, int] | None,
    *,
    face: callable | None = None,
) -> list[tuple[float, float]]:
    """Extrude a world ring between two heights. Returns the projected top ring.

    `face(a, b, height_px, length_m, sunlit, along_m)` is called for each wall
    that turns toward the viewer, with `a`/`b` already lifted to the base — that
    is the hook openings hang off. `along_m` is how far round the ring the wall
    starts, so openings can be spaced by arc length rather than per edge: a drum
    tower is a 24-gon, and one window per edge gives it 24 windows.

    Walls are drawn back to front so nearer ones win.
    """
    ground = [camera.ground(x, y) for x, y in ring]
    if len(ground) < 4:
        return []
    outward = outward_normal_fn(ground)
    base = [(x, y - base_px) for x, y in ground]
    top = [(x, y - top_px) for x, y in ground]
    height_px = top_px - base_px

    along = [0.0]
    for i in range(len(ring) - 1):
        along.append(along[-1] + math.dist(ring[i], ring[i + 1]))

    for i in sorted(range(len(ring) - 1), key=lambda i: (base[i][1] + base[i + 1][1]) / 2):
        a, b = base[i], base[i + 1]
        if math.dist(a, b) < 0.6:
            continue
        nx, ny = outward(ground[i], ground[i + 1])
        sunlit = nx < 0
        draw.polygon([a, b, (b[0], b[1] - height_px), (a[0], a[1] - height_px)],
                     fill=left if sunlit else right, outline=outline)
        if face is not None and ny > 0:
            face(a, b, height_px, along[i + 1] - along[i], sunlit, along[i])
    return top


def arc_positions(ring, pitch_m: float, *, phase: float = 0.5) -> tuple[float, float]:
    """Even spacing round a closed ring: (pitch, offset of the first item).

    The pitch is nudged so a whole number of items fits the perimeter — leaving
    a ragged joint where the ring closes is the one place the eye always looks.
    """
    perimeter = sum(math.dist(ring[i], ring[i + 1]) for i in range(len(ring) - 1))
    if perimeter <= 0 or pitch_m <= 0:
        return pitch_m, 0.0
    count = max(1, round(perimeter / pitch_m))
    return perimeter / count, perimeter / count * phase


def ring_span(ring_px, ring_world, s0: float, s1: float) -> list[tuple[float, float]]:
    """The screen polyline between two arc-length positions along a ring.

    Returned as a point list so a merlon that straddles a corner bends round it
    instead of cutting it off.
    """
    pts: list[tuple[float, float]] = []
    walked = 0.0
    for i in range(len(ring_world) - 1):
        seg = math.dist(ring_world[i], ring_world[i + 1])
        if seg <= 0:
            continue
        start, end = walked, walked + seg
        walked = end
        if end < s0 or start > s1:
            continue
        ax, ay = ring_px[i]
        bx, by = ring_px[i + 1]
        t0 = max(0.0, (s0 - start) / seg)
        t1 = min(1.0, (s1 - start) / seg)
        if t1 <= t0:
            continue
        p0 = (ax + (bx - ax) * t0, ay + (by - ay) * t0)
        p1 = (ax + (bx - ax) * t1, ay + (by - ay) * t1)
        if not pts or math.dist(pts[-1], p0) > 0.01:
            pts.append(p0)
        pts.append(p1)
    return pts


def pyramid(
    draw: ImageDraw.ImageDraw,
    ring_px: list[tuple[float, float]],
    rise_px: float,
    colour: tuple[int, int, int],
    outline: tuple[int, int, int] | None,
    *,
    apex_shift: tuple[float, float] = (0.0, 0.0),
) -> tuple[float, float]:
    """A spire or conical cap over a top ring. Returns the apex.

    Faces are drawn far to near and shaded by which way they lean, so a
    many-sided cone over a round tower reads as round rather than as a fan.
    """
    n = len(ring_px) - 1
    if n < 3:
        return (0.0, 0.0)
    cx = sum(p[0] for p in ring_px[:n]) / n
    cy = sum(p[1] for p in ring_px[:n]) / n
    apex = (cx + apex_shift[0], cy - rise_px + apex_shift[1])

    faces = []
    for i in range(n):
        a, b = ring_px[i], ring_px[i + 1]
        mid_y = (a[1] + b[1]) / 2
        # A face turning left catches the light; one tipped away is darkest.
        lit = 1.10 if (b[0] - a[0]) < 0 else 0.84
        if mid_y < cy:
            lit *= 0.94                      # the far side, tipped away from us
        faces.append((mid_y, [a, b, apex], lit))
    for _, poly, lit in sorted(faces, key=lambda f: f[0]):
        draw.polygon(poly, fill=shade(colour, lit), outline=outline)
    return apex


def ridge_roof(
    draw: ImageDraw.ImageDraw,
    corners_px: list[tuple[float, float]],
    rise_px: float,
    colour: tuple[int, int, int],
    outline: tuple[int, int, int] | None,
    *,
    along_long: bool = True,
    hipped: float = 0.0,
) -> None:
    """A gabled or hipped roof over four already-projected corners."""
    if len(corners_px) != 4:
        return
    p = corners_px
    len_a = math.dist(p[0], p[1])
    len_b = math.dist(p[1], p[2])
    first = (len_a >= len_b) == along_long
    e0, e1, e2, e3 = (p[0], p[1], p[2], p[3]) if first else (p[1], p[2], p[3], p[0])

    ra = ((e0[0] + e3[0]) / 2 + (e1[0] - e0[0]) * hipped * 0.5,
          (e0[1] + e3[1]) / 2 + (e1[1] - e0[1]) * hipped * 0.5 - rise_px)
    rb = ((e1[0] + e2[0]) / 2 - (e1[0] - e0[0]) * hipped * 0.5,
          (e1[1] + e2[1]) / 2 - (e1[1] - e0[1]) * hipped * 0.5 - rise_px)

    faces = [([e0, e1, rb, ra], 1.12), ([e3, e2, rb, ra], 0.82),
             ([e0, e3, ra], 0.96), ([e1, e2, rb], 0.90)]
    for poly, lit in sorted(faces, key=lambda f: sum(q[1] for q in f[0]) / len(f[0])):
        draw.polygon(poly, fill=shade(colour, lit), outline=outline)
