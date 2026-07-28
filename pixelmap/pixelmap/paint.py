"""Stage 5 — render.

Draws the scene in the project's own style rather than as grey masses: pitched
roofs, windowed facades, shopfronts, outlines.

Two things carry most of the character. The first is **roofs** — in an isometric
view the roof is the largest surface on every building, and Limerick happens to
have `roof:shape` on 30% of its buildings, so a real pitched roofline is
available for free rather than inferred. The second is **facade rhythm**: at
roughly 30 x 47 px of wall, what reads is not texture but the count and spacing
of windows, the position of the door, and whether the ground floor is a
shopfront. Those come from frontage length, storey count and the `shop` tag.

Everything is drawn as flat polygons with no anti-aliasing, so the output stays
crisp when it is nearest-neighbour upscaled for print.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from PIL import Image, ImageDraw
from shapely.geometry import Polygon

from .extract import Building, Layers
from .iso import Camera
from .style import Facade, Style, facade_for, parse_colour, roof_for

#: A wall narrower or shorter than this has no room for openings; drawing them
#: anyway produces noise rather than detail.
MIN_WALL_W_PX = 11.0
MIN_WALL_H_PX = 9.0

#: Typical spacing between window centres on an Irish terrace, in metres.
WINDOW_PITCH_M = 2.9


@dataclass
class PaintStats:
    buildings: int = 0
    roofs_tagged: int = 0
    facades_detailed: int = 0
    shopfronts: int = 0


def _rng(osm_id: str, seed: int, salt: str = "") -> float:
    digest = hashlib.blake2b(f"{seed}:{osm_id}:{salt}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2 ** 64


def _shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in colour)


def _wall_point(a, b, lift, u, v):
    """Facade space to screen. u runs along the wall, v from ground to eaves."""
    return (a[0] + (b[0] - a[0]) * u,
            a[1] + (b[1] - a[1]) * u - lift * v)


def _wall_rect(a, b, lift, u0, u1, v0, v1):
    return [_wall_point(a, b, lift, u0, v0), _wall_point(a, b, lift, u1, v0),
            _wall_point(a, b, lift, u1, v1), _wall_point(a, b, lift, u0, v1)]


def _draw_facade(
    draw: ImageDraw.ImageDraw,
    a, b, lift: float,
    length_m: float,
    building: Building,
    facade: Facade,
    style: Style,
    seed: int,
    *,
    sunlit: bool,
) -> tuple[bool, bool]:
    """Windows, door and shopfront on one wall. Returns (detailed, shopfront)."""
    width_px = math.hypot(b[0] - a[0], b[1] - a[1])
    if width_px < MIN_WALL_W_PX or lift < MIN_WALL_H_PX:
        return False, False

    levels = max(1, int(round(building.levels)))
    # Window count comes from the wall's real length on the ground, not from how
    # many pixels it happens to occupy — otherwise zooming in would grow extra
    # windows on a house that has not changed.
    columns = max(1, min(12, int(round(length_m / WINDOW_PITCH_M))))
    # ...but never more openings than the pixels can separate.
    columns = min(columns, max(1, int(width_px // 4)))

    glass = style.window_lit if _rng(building.osm_id, seed, "lit") < 0.12 else style.window
    glass = glass if sunlit else _shade(glass, 0.86)
    trim = _shade(facade.left if sunlit else facade.right, 1.12)

    has_shop = bool(building.shop) and levels >= 1
    storey_v = 1.0 / levels
    inset = 0.16 / columns

    for level in range(levels):
        v0 = level * storey_v + storey_v * 0.22
        v1 = (level + 1) * storey_v - storey_v * 0.24
        if v1 <= v0:
            continue
        ground_floor = level == 0

        if ground_floor and has_shop:
            # One continuous glazed band with a fascia above it.
            draw.polygon(_wall_rect(a, b, lift, 0.06, 0.94, 0.06, storey_v * 0.62),
                         fill=glass)
            draw.polygon(_wall_rect(a, b, lift, 0.04, 0.96,
                                    storey_v * 0.62, storey_v * 0.80),
                         fill=style.fascia)
            continue

        for c in range(columns):
            u_mid = (c + 0.5) / columns
            u0, u1 = u_mid - (0.5 / columns) + inset, u_mid + (0.5 / columns) - inset
            if ground_floor and c == columns // 2 and not has_shop:
                # Door: taller, reaching the pavement.
                draw.polygon(_wall_rect(a, b, lift, u0, u1, 0.04, v1), fill=trim)
                continue
            draw.polygon(_wall_rect(a, b, lift, u0, u1, v0, v1), fill=glass)

    return True, has_shop


def _obb_corners(poly: Polygon) -> list[tuple[float, float]] | None:
    """Four corners of the footprint's oriented box, if it is boxy enough."""
    try:
        obb = poly.minimum_rotated_rectangle
    except Exception:
        return None
    if not isinstance(obb, Polygon) or obb.is_empty or obb.area <= 0:
        return None
    if poly.area / obb.area < 0.72:
        return None  # too irregular for a believable pitched roof
    return list(obb.exterior.coords)[:4]


#: Building types that are pitched by default in an Irish town.
_PITCHED_KINDS = {
    "house", "residential", "terrace", "semidetached_house", "detached",
    "bungalow", "cottage", "apartments", "church", "chapel", "school", "yes",
}
#: Above this footprint area, a flat or parapet roof is the safer assumption —
#: shopping centres, sheds and blocks rarely carry a single ridge.
_PITCHED_MAX_AREA_M2 = 500.0


def _infer_roof_shape(building: Building) -> str:
    """What roof to draw when OSM does not say.

    Only 30% of Limerick's buildings carry a `roof:shape`, and leaving the rest
    flat reads as a city of slabs. Almost every small Irish building is pitched,
    so small residential footprints get a ridge and larger or industrial ones
    stay flat — an assumption, and one the render is better for.
    """
    if building.geom.area > _PITCHED_MAX_AREA_M2:
        return "flat"
    return "gabled" if building.kind in _PITCHED_KINDS else "flat"


def _draw_roof(
    draw: ImageDraw.ImageDraw,
    camera: Camera,
    building: Building,
    facade: Facade,
    style: Style,
    seed: int,
    lift: float,
    top: list[tuple[float, float]],
) -> bool:
    """A pitched roof where the shape is known or safely inferable."""
    shape = (building.roof_shape or "").lower() or _infer_roof_shape(building)
    # Prefer what the mapper recorded, then the palette; never the wall colour.
    roof_colour = parse_colour(building.roof_colour) or roof_for(style, building.osm_id, seed)
    outline = style.outline if style.outline_px else None

    if shape not in ("gabled", "hipped", "half-hipped", "pyramidal"):
        if len(top) >= 3:
            draw.polygon(top, fill=roof_colour, outline=outline)
        return False

    corners = _obb_corners(building.geom)
    if corners is None or len(corners) != 4:
        if len(top) >= 3:
            draw.polygon(top, fill=roof_colour, outline=outline)
        return False

    p = [camera.ground(x, y) for x, y in corners]
    p = [(x, y - lift) for x, y in p]           # lift the eaves to wall top
    len_a = math.dist(corners[0], corners[1])
    len_b = math.dist(corners[1], corners[2])

    # Ridge runs along the longer side unless the tagging says otherwise.
    along_first = len_a >= len_b
    if (building.roof_orientation or "").lower() == "across":
        along_first = not along_first
    if along_first:
        e0, e1, e2, e3 = p[0], p[1], p[2], p[3]
        span = len_b
    else:
        e0, e1, e2, e3 = p[1], p[2], p[3], p[0]
        span = len_a

    # Pitch scaled to the building's own width, capped so terraces do not grow
    # cathedral roofs.
    ridge_h = min(span / camera.cell_m * 0.55, camera.storey_px * 1.35)
    if shape == "pyramidal":
        cx = sum(q[0] for q in p) / 4
        cy = sum(q[1] for q in p) / 4
        apex = (cx, cy - ridge_h)
        faces = [(e0, e1, apex), (e1, e2, apex), (e2, e3, apex), (e3, e0, apex)]
        for face in sorted(faces, key=lambda f: sum(q[1] for q in f) / len(f)):
            lit = 1.06 if (face[1][0] - face[0][0]) < 0 else 0.88
            draw.polygon(list(face), fill=_shade(roof_colour, lit), outline=outline)
        return True

    inset = 0.5 if shape in ("hipped", "half-hipped") else 0.0
    ra = ((e0[0] + e3[0]) / 2 + (e1[0] - e0[0]) * inset * 0.5,
          (e0[1] + e3[1]) / 2 + (e1[1] - e0[1]) * inset * 0.5 - ridge_h)
    rb = ((e1[0] + e2[0]) / 2 - (e1[0] - e0[0]) * inset * 0.5,
          (e1[1] + e2[1]) / 2 - (e1[1] - e0[1]) * inset * 0.5 - ridge_h)

    slope_near = [e0, e1, rb, ra]
    slope_far = [e3, e2, rb, ra]
    gable_a = [e0, e3, ra]
    gable_b = [e1, e2, rb]

    faces = [
        (slope_near, 1.12), (slope_far, 0.82),
        (gable_a, 0.96), (gable_b, 0.90),
    ]
    for face, lit in sorted(faces, key=lambda f: sum(q[1] for q in f[0]) / len(f[0])):
        draw.polygon(face, fill=_shade(roof_colour, lit), outline=outline)
    return True


def draw_building(
    draw: ImageDraw.ImageDraw,
    camera: Camera,
    building: Building,
    style: Style,
    seed: int,
    stats: PaintStats,
) -> None:
    ring = list(building.geom.exterior.coords)
    if len(ring) < 4:
        return
    facade = facade_for(style, building.osm_id, seed)
    ground = [camera.ground(x, y) for x, y in ring]
    lift = building.levels * camera.storey_px
    top = [(x, y - lift) for x, y in ground]
    outline = style.outline if style.outline_px else None

    # Which walls face the viewer cannot be read off the vertex order: OSM
    # footprints wind both ways (two thirds of Limerick's are clockwise), so a
    # winding-based test details the back of most buildings. Instead compare each
    # wall's outward normal — the one pointing away from the centroid — against
    # the view direction. Screen y grows downward, so a normal with positive y
    # points at the viewer.
    centre_x = sum(p[0] for p in ground[:-1]) / (len(ground) - 1)
    centre_y = sum(p[1] for p in ground[:-1]) / (len(ground) - 1)

    def outward_normal(a, b):
        nx, ny = (b[1] - a[1]), -(b[0] - a[0])
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if (mx - centre_x) * nx + (my - centre_y) * ny < 0:
            nx, ny = -nx, -ny
        return nx, ny

    # Walls back to front, so nearer ones overwrite what they hide.
    order = sorted(range(len(ring) - 1),
                   key=lambda i: (ground[i][1] + ground[i + 1][1]) / 2)
    for i in order:
        a, b = ground[i], ground[i + 1]
        if math.dist(a, b) < 0.6:
            continue
        nx, ny = outward_normal(a, b)
        visible = ny > 0                 # normal points down-screen, at the viewer
        sunlit = nx < 0                  # and left, into the light
        colour = facade.left if sunlit else facade.right
        draw.polygon([a, b, (b[0], b[1] - lift), (a[0], a[1] - lift)],
                     fill=colour, outline=outline)
        if visible:
            length_m = math.dist(ring[i], ring[i + 1])
            detailed, shop = _draw_facade(draw, a, b, lift, length_m, building,
                                          facade, style, seed, sunlit=sunlit)
            stats.facades_detailed += int(detailed)
            stats.shopfronts += int(shop)

    stats.roofs_tagged += int(_draw_roof(draw, camera, building, facade, style,
                                         seed, lift, top))
    stats.buildings += 1


def render(layers: Layers, camera: Camera, style: Style, seed: int,
           *, min_area_m2: float = 10.0) -> tuple[Image.Image, PaintStats]:
    """Paint the whole scene."""
    img = Image.new("RGB", (camera.width_px, camera.height_px), style.sky)
    draw = ImageDraw.Draw(img)
    stats = PaintStats()

    margin = max(camera.width_px, camera.height_px) * camera.cell_m
    draw.polygon(
        [camera.ground(x, y) for x, y in (
            (camera.origin_x - margin, camera.origin_y - margin),
            (camera.origin_x + margin, camera.origin_y - margin),
            (camera.origin_x + margin, camera.origin_y + margin),
            (camera.origin_x - margin, camera.origin_y + margin))],
        fill=style.land,
    )

    def area(poly: Polygon, colour):
        pts = [camera.ground(x, y) for x, y in poly.exterior.coords]
        if len(pts) >= 3:
            draw.polygon(pts, fill=colour)

    for a in layers.urban:
        area(a.geom, style.urban)
    for a in layers.green:
        area(a.geom, style.green_dark if a.kind in ("wood", "forest") else style.green)
    for a in layers.water:
        area(a.geom, style.water)
    for w in layers.waterways:
        band = w.geom.buffer(w.width_m / 2, cap_style=2)
        for g in getattr(band, "geoms", [band]):
            area(g, style.water)

    # Pavements first, then carriageways on top, so every street gets a kerb.
    for road in sorted(layers.roads, key=lambda r: -r.width_m):
        if road.tunnel or road.importance > 6:
            continue
        band = road.geom.buffer(road.width_m / 2 + style.pavement_m,
                                cap_style=2, join_style=1)
        for g in getattr(band, "geoms", [band]):
            area(g, style.pavement)
    for road in sorted(layers.roads, key=lambda r: -r.width_m):
        if road.tunnel:
            continue
        band = road.geom.buffer(road.width_m / 2, cap_style=2, join_style=1)
        colour = style.road_major if road.importance <= 4 else style.road
        for g in getattr(band, "geoms", [band]):
            area(g, colour)
    for track in layers.rail:
        if track.tunnel:
            continue
        band = track.geom.buffer(track.width_m / 2, cap_style=2)
        for g in getattr(band, "geoms", [band]):
            area(g, style.rail)

    renderable = []
    for b in layers.buildings:
        if b.geom.area < min_area_m2:
            continue
        c = b.geom.centroid
        sx, sy = camera.ground(c.x, c.y)
        if -400 <= sx <= camera.width_px + 400 and -1200 <= sy <= camera.height_px + 400:
            renderable.append((sy, b))

    for _, b in sorted(renderable, key=lambda t: t[0]):
        draw_building(draw, camera, b, style, seed, stats)

    return img, stats
