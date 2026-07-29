"""Grey-box renderer — M1's composition instrument.

Deliberately unstyled: flat greys, no palette, no sprites, no charm. Its only
job is to answer the gate-one questions — what rotation, what window, what cell
size, what orientation — while those answers are still cheap to change.

Geometry is projected straight to art-canvas pixels rather than going through
the cell grid. That keeps stage-three discretization decisions unmade, and since
nothing here is anti-aliased, the output already shows the true pixel scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw
from shapely.geometry import LineString, Polygon

from .extract import Layers
from .iso import Camera

# A near-neutral grey ramp with a slight cool bias, so masses read as volumes
# without implying any final palette.
GREY = {
    "sky": (238, 239, 236),
    # Ground reads darkest-to-lightest as water, green, built-up, land, road, so
    # the street network stands out against the blocks it divides.
    "land": (194, 196, 191),
    "green": (172, 183, 166),
    "water": (152, 168, 177),
    "urban": (184, 186, 181),
    "road": (226, 227, 222),
    "rail": (146, 148, 146),
    "roof": (246, 246, 243),
    "wall_left": (200, 201, 197),
    "wall_right": (150, 152, 150),
    "outline": (108, 111, 110),
    "landmark_roof": (252, 246, 232),
    "landmark_left": (214, 206, 190),
    "landmark_right": (172, 165, 150),
    "frame": (150, 152, 150),
}


@dataclass
class RenderStats:
    buildings_drawn: int
    ground_shapes: int
    tallest_levels: float
    ground_extent_m: tuple[float, float]


def _poly_to_screen(camera: Camera, poly: Polygon, levels: float = 0.0):
    ring = list(poly.exterior.coords)
    pts = [camera.ground(x, y) for x, y in ring]
    if levels:
        pts = [(x, y - levels * camera.storey_px) for x, y in pts]
    return pts


def _draw_area(draw: ImageDraw.ImageDraw, camera: Camera, poly: Polygon, colour) -> None:
    if poly.is_empty:
        return
    pts = _poly_to_screen(camera, poly)
    if len(pts) >= 3:
        draw.polygon(pts, fill=colour)
    for interior in poly.interiors:
        hole = [camera.ground(x, y) for x, y in interior.coords]
        if len(hole) >= 3:
            draw.polygon(hole, fill=GREY["land"])


def _draw_line_band(draw, camera: Camera, line: LineString, width_m: float, colour) -> None:
    """Draw a road as its buffered carriageway, projected."""
    band = line.buffer(width_m / 2.0, cap_style=2, join_style=1)
    geoms = getattr(band, "geoms", [band])
    for geom in geoms:
        if isinstance(geom, Polygon) and not geom.is_empty:
            pts = _poly_to_screen(camera, geom)
            if len(pts) >= 3:
                draw.polygon(pts, fill=colour)


def _draw_prism(draw, camera: Camera, poly: Polygon, levels: float, palette: dict) -> None:
    """Extrude a footprint: walls back-to-front, then the roof."""
    ring = list(poly.exterior.coords)
    if len(ring) < 4:
        return
    ground = [camera.ground(x, y) for x, y in ring]
    lift = levels * camera.storey_px
    top = [(x, y - lift) for x, y in ground]

    walls = []
    for i in range(len(ring) - 1):
        a, b = ground[i], ground[i + 1]
        # Screen-space cross product: which way does this wall face?
        facing = (b[0] - a[0])
        mid_y = (a[1] + b[1]) / 2
        walls.append((mid_y, facing, i))

    # Nearer walls (larger screen y) are painted last.
    for mid_y, facing, i in sorted(walls, key=lambda w: w[0]):
        a, b = ground[i], ground[i + 1]
        ta, tb = top[i], top[i + 1]
        colour = palette["left"] if facing >= 0 else palette["right"]
        draw.polygon([a, b, tb, ta], fill=colour)

    if len(top) >= 3:
        draw.polygon(top, fill=palette["roof"], outline=GREY["outline"])


def render(
    layers: Layers,
    camera: Camera,
    *,
    landmark_ids: set[str] | None = None,
    min_building_area_m2: float = 12.0,
    draw_frame: bool = False,
) -> tuple[Image.Image, RenderStats]:
    """Render the grey-box view."""
    landmark_ids = landmark_ids or set()
    img = Image.new("RGB", (camera.width_px, camera.height_px), GREY["sky"])
    draw = ImageDraw.Draw(img)

    # --- ground, painter's order by layer -------------------------------
    ground_shapes = 0

    # A land base so the sky colour only shows past the city edge.
    margin = max(camera.width_px, camera.height_px) * camera.cell_m
    corners = [
        (camera.origin_x - margin, camera.origin_y - margin),
        (camera.origin_x + margin, camera.origin_y - margin),
        (camera.origin_x + margin, camera.origin_y + margin),
        (camera.origin_x - margin, camera.origin_y + margin),
    ]
    draw.polygon([camera.ground(x, y) for x, y in corners], fill=GREY["land"])

    for area in layers.urban:
        _draw_area(draw, camera, area.geom, GREY["urban"])
        ground_shapes += 1
    for area in layers.green:
        _draw_area(draw, camera, area.geom, GREY["green"])
        ground_shapes += 1
    for area in layers.water:
        _draw_area(draw, camera, area.geom, GREY["water"])
        ground_shapes += 1
    for way in layers.waterways:
        _draw_line_band(draw, camera, way.geom, way.width_m, GREY["water"])
        ground_shapes += 1

    # Roads: widest first so junctions resolve toward the more important street.
    for road in sorted(layers.roads, key=lambda r: -r.width_m):
        if road.tunnel:
            continue
        _draw_line_band(draw, camera, road.geom, road.width_m, GREY["road"])
        ground_shapes += 1
    for track in layers.rail:
        if track.tunnel:
            continue
        _draw_line_band(draw, camera, track.geom, track.width_m, GREY["rail"])
        ground_shapes += 1

    # --- buildings, back to front ---------------------------------------
    drawn = 0
    tallest = 0.0
    default_palette = {
        "roof": GREY["roof"], "left": GREY["wall_left"], "right": GREY["wall_right"]
    }
    landmark_palette = {
        "roof": GREY["landmark_roof"],
        "left": GREY["landmark_left"],
        "right": GREY["landmark_right"],
    }

    renderable = []
    for building in layers.buildings:
        if building.geom.area < min_building_area_m2:
            continue
        centroid = building.geom.centroid
        screen = camera.ground(centroid.x, centroid.y)
        # Cheap frustum cull with room for tall towers leaning up the canvas.
        if not (-200 <= screen[0] <= camera.width_px + 200):
            continue
        if not (-400 <= screen[1] <= camera.height_px + 200):
            continue
        renderable.append((screen[1], building))

    for _, building in sorted(renderable, key=lambda item: item[0]):
        palette = landmark_palette if building.osm_id in landmark_ids else default_palette
        _draw_prism(draw, camera, building.geom, building.levels, palette)
        tallest = max(tallest, building.levels)
        drawn += 1

    if draw_frame:
        draw.rectangle(
            [0, 0, camera.width_px - 1, camera.height_px - 1],
            outline=GREY["frame"], width=1,
        )

    return img, RenderStats(
        buildings_drawn=drawn,
        ground_shapes=ground_shapes,
        tallest_levels=tallest,
        ground_extent_m=camera.ground_extent_m(),
    )


def annotate_landmarks(
    img: Image.Image,
    camera: Camera,
    landmarks: list[dict],
    transformer,
) -> tuple[Image.Image, list[tuple[str, bool]]]:
    """Overlay landmark pins so a crop can be judged against the wishlist.

    Returns the annotated image and, per landmark, whether it landed on canvas.
    """
    from PIL import ImageFont

    out = img.convert("RGB").copy()
    draw = ImageDraw.Draw(out, "RGBA")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    except OSError:
        font = ImageFont.load_default()

    pin_tier1 = (166, 64, 45)
    pin_tier2 = (46, 125, 131)
    placement: list[tuple[str, bool]] = []

    for mark in landmarks:
        wx, wy = transformer.transform(mark["lon"], mark["lat"])
        x, y = camera.ground(wx, wy)
        on_canvas = 0 <= x < camera.width_px and 0 <= y < camera.height_px
        placement.append((mark["name"], on_canvas))
        if not on_canvas:
            continue

        colour = pin_tier1 if mark.get("tier", 1) == 1 else pin_tier2
        r = 5 if mark.get("tier", 1) == 1 else 4
        draw.line([x, y - 22, x, y], fill=colour + (220,), width=2)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=colour, outline=(255, 255, 255), width=1)

        label = mark.get("short", mark["name"])
        box = draw.textbbox((0, 0), label, font=font)
        w, h = box[2] - box[0], box[3] - box[1]
        lx, ly = x + 9, y - 30
        lx = min(lx, camera.width_px - w - 8)
        draw.rectangle([lx - 4, ly - 3, lx + w + 4, ly + h + 5], fill=(255, 255, 255, 225))
        draw.text((lx, ly), label, font=font, fill=colour)

    return out, placement


def save_preview(img: Image.Image, path: Path, *, scale: int = 1) -> Path:
    """Write a render, optionally nearest-neighbour upscaled for on-screen viewing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = img
    if scale > 1:
        out = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    out.save(path)
    return path
