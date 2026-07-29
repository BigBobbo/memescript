"""Camera construction from a city's frame configuration.

The frame is specified the way the composition is actually reasoned about —
a ground rectangle, plus where the river should sit vertically — rather than
as a canvas size. Canvas pixels fall out of the cell size, so changing detail
level never changes what is in shot.
"""

from __future__ import annotations

import math

from pyproj import Transformer

from .iso import CELL_H, CELL_W, Camera

#: Metres per storey. Irish terraces run a little under this; it is the divisor
#: used when a building carries a `height` tag instead of `building:levels`.
STOREY_M = 3.2


def true_storey_px(cell_m: float) -> float:
    """Storey height in pixels for a geometrically true isometric.

    A cell renders as a 4 x 2 px rhombus, so a cube of one cell has a vertical
    edge of 2 px — hence 2 px per cell of height.
    """
    return 2.0 * STOREY_M / cell_m


def canvas_for(across_m: float, deep_m: float, cell_m: float) -> tuple[int, int]:
    """Canvas size covering a ground rectangle at a given cell size.

    Isometric compresses depth by two relative to width, so a canvas is always
    wider than the ground rectangle's aspect suggests.
    """
    w = across_m * 2 * CELL_W / (math.sqrt(2) * cell_m)
    h = deep_m * 2 * CELL_H / (math.sqrt(2) * cell_m)
    return int(w) + int(w) % 2, int(h) + int(h) % 2


def wgs84_bounds(camera: Camera, crs: str) -> tuple[float, float, float, float]:
    """(south, west, north, east) of the ground the canvas actually shows.

    The canvas maps to a rotated rectangle on the ground, so its four corners
    bound the visible region. Comparing this against the fetch bbox is what
    catches a frame that has been widened past the data behind it.
    """
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    corners = [
        to_wgs.transform(*camera.world(sx, sy))
        for sx, sy in ((0, 0), (camera.width_px, 0),
                       (camera.width_px, camera.height_px), (0, camera.height_px))
    ]
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    return min(lats), min(lons), max(lats), max(lons)


def camera_for(city, *, cell_m: float | None = None, scale: float | None = None) -> Camera:
    """Build the configured camera, anchoring the river at its target depth.

    `scale` widens the frame without touching detail: it multiplies both ground
    extents, so pixels per metre and the canvas aspect both stay put and the
    canvas simply grows around the same subject. `cell_m` is the opposite knob —
    same coverage, different detail. Keeping them separate is what lets the
    composition and the resolution be argued about one at a time.
    """
    frame = city.config["frame"]
    render = city.config["render"]
    cell_m = cell_m or city.cell_m
    scale = scale if scale is not None else float(frame.get("scale", 1.0))
    to_crs = Transformer.from_crs("EPSG:4326", city.crs, always_xy=True)

    width, height = canvas_for(frame["across_m"] * scale, frame["deep_m"] * scale, cell_m)
    storey_px = true_storey_px(cell_m) * render["height_exaggeration"]

    anchor = frame["anchor"]
    ox, oy = to_crs.transform(anchor["lon"], anchor["lat"])

    def build(shift):
        return Camera(
            origin_x=ox, origin_y=oy,
            rotation_deg=city.rotation_deg, cell_m=cell_m,
            width_px=width, height_px=height,
            storey_px=storey_px, centre_shift_px=shift,
        )

    # Slide vertically so a named point on the water lands at its target depth.
    # Using a real mid-channel point keeps this stable — the river's own extent
    # runs far past the frame, so its centroid is not a usable reference.
    ref = frame["river_ref"]
    rx, ry = to_crs.transform(ref["lon"], ref["lat"])
    current = build((0.0, 0.0)).ground(rx, ry)[1]
    return build((0.0, frame["river_depth"] * height - current))
