"""Isometric projection — the geometry contract every later stage obeys.

Classic pixel-art "isometric" is really 2:1 dimetric. One ground cell is a
4 x 2 pixel rhombus, so every ground line runs at exactly two horizontal pixels
per one vertical pixel: the slope pixel artists can draw without anti-aliasing.

World axes, after rotation, map to screen as:

    +u (east)  ->  (+2, +1) px   right and toward the viewer
    +v (north) ->  (+2, -1) px   right and away from the viewer

so the viewer stands to the south-west. Height is a straight vertical lift, the
only screen direction that is not part of the ground plane.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Screen pixels per ground cell along each iso axis.
CELL_W = 2.0   # half-width: a cell spans 4 px
CELL_H = 1.0   # half-height: a cell spans 2 px

#: Metres per storey. Irish terraces run a little under this; it is the divisor
#: used when a building carries a `height` tag instead of `building:levels`, and
#: the unit every height in the render is quoted in.
STOREY_M = 3.2


@dataclass(frozen=True)
class Camera:
    """Maps projected world metres onto the art canvas."""

    origin_x: float          #: world easting at the canvas centre
    origin_y: float          #: world northing at the canvas centre
    rotation_deg: float
    cell_m: float
    width_px: int
    height_px: int
    storey_px: float = 3.0
    centre_shift_px: tuple[float, float] = (0.0, 0.0)

    @property
    def _rot(self) -> tuple[float, float]:
        rad = math.radians(self.rotation_deg)
        return math.cos(rad), math.sin(rad)

    def ground(self, x: float, y: float) -> tuple[float, float]:
        """Project a world point (metres, easting/northing) to canvas pixels."""
        cos_r, sin_r = self._rot
        dx, dy = x - self.origin_x, y - self.origin_y
        # Rotate the map, then convert metres to cells.
        u = (dx * cos_r - dy * sin_r) / self.cell_m
        v = (dx * sin_r + dy * cos_r) / self.cell_m
        sx = (u + v) * CELL_W
        sy = (u - v) * CELL_H
        return (
            sx + self.width_px / 2 + self.centre_shift_px[0],
            sy + self.height_px / 2 + self.centre_shift_px[1],
        )

    def world(self, sx: float, sy: float) -> tuple[float, float]:
        """Inverse of `ground` — the world point under a canvas pixel."""
        cos_r, sin_r = self._rot
        px = sx - self.width_px / 2 - self.centre_shift_px[0]
        py = sy - self.height_px / 2 - self.centre_shift_px[1]
        u = (px / CELL_W + py / CELL_H) / 2 * self.cell_m
        v = (px / CELL_W - py / CELL_H) / 2 * self.cell_m
        return (
            self.origin_x + u * cos_r + v * sin_r,
            self.origin_y - u * sin_r + v * cos_r,
        )

    def lift(self, point: tuple[float, float], levels: float) -> tuple[float, float]:
        """Raise a projected point by a number of storeys."""
        return (point[0], point[1] - levels * self.storey_px)

    def depth(self, x: float, y: float) -> float:
        """Painter's-order key: larger means nearer the viewer."""
        cos_r, sin_r = self._rot
        dx, dy = x - self.origin_x, y - self.origin_y
        u = (dx * cos_r - dy * sin_r) / self.cell_m
        v = (dx * sin_r + dy * cos_r) / self.cell_m
        return u - v

    def ground_extent_m(self) -> tuple[float, float]:
        """Ground rectangle covered by the canvas, in metres (across, deep).

        The isometric view compresses depth by two, so a landscape canvas always
        shows a deeper-than-wide patch of ground.
        """
        across = self.width_px * math.sqrt(2) * self.cell_m / (2 * CELL_W)
        deep = self.height_px * math.sqrt(2) * self.cell_m / (2 * CELL_H)
        return across, deep

    def mm_per_pixel(self, dpi: int, upscale: int) -> float:
        return 25.4 * upscale / dpi


def solve_frame(
    points: list[tuple[float, float]],
    rotation_deg: float,
    width_px: int,
    height_px: int,
    *,
    margin: float = 0.06,
    headroom_px: float = 0.0,
) -> tuple[float, float, float]:
    """Smallest cell size, and the centre, that fits every point on canvas.

    Returns (cell_m, origin_x, origin_y). Screen coordinates scale as 1/cell_m,
    so the fit is solved once in unit space and then divided through.

    `headroom_px` reserves space at the top of the canvas for building height,
    which is drawn upward from the ground plane and would otherwise overflow.
    """
    if not points:
        raise ValueError("no points to frame")

    rad = math.radians(rotation_deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)

    unit = []
    for x, y in points:
        u = x * cos_r - y * sin_r
        v = x * sin_r + y * cos_r
        unit.append(((u + v) * CELL_W, (u - v) * CELL_H))

    min_x = min(p[0] for p in unit)
    max_x = max(p[0] for p in unit)
    min_y = min(p[1] for p in unit)
    max_y = max(p[1] for p in unit)

    usable_w = width_px * (1 - 2 * margin)
    usable_h = height_px * (1 - 2 * margin) - headroom_px
    if usable_w <= 0 or usable_h <= 0:
        raise ValueError("margins leave no usable canvas")

    cell_m = max((max_x - min_x) / usable_w, (max_y - min_y) / usable_h)

    # Centre of the fitted box, biased down by half the headroom so the
    # reserved space lands above the subject.
    cx_unit = (min_x + max_x) / 2
    cy_unit = (min_y + max_y) / 2 - headroom_px * cell_m / 2

    # Invert the isometric map: sx = (u+v)*CELL_W, sy = (u-v)*CELL_H.
    su = cx_unit / CELL_W
    sv = cy_unit / CELL_H
    u = (su + sv) / 2
    v = (su - sv) / 2
    origin_x = u * cos_r + v * sin_r
    origin_y = -u * sin_r + v * cos_r
    return cell_m, origin_x, origin_y


def project_ring(camera: Camera, coords, levels: float = 0.0) -> list[tuple[float, float]]:
    points = [camera.ground(x, y) for x, y in coords]
    if levels:
        points = [camera.lift(p, levels) for p in points]
    return points
