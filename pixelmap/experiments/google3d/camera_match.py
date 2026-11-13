"""The pipeline Camera that lands pixel for pixel on a render.mjs/stitch.py output."""

from __future__ import annotations

import json
import math
from pathlib import Path

from pyproj import Transformer

from pixelmap.frame import true_storey_px
from pixelmap.iso import STOREY_M, Camera


def matched_camera(out: Path, city, *, native_height: bool = False) -> tuple[Camera, dict]:
    """Ortho at 30° puts d m across at d m and d m forward at d/2 m up — iso.py's 2:1.

    At M m/px that is a cell of M * 2 * sqrt(2). Height differs: ortho gives
    cos 30° = 0.866 m of screen per metre, iso.py's true isometric 0.707, so by
    default storeys follow Google's scale.
    """
    m = json.loads((out / "manifest.json").read_text())
    p, e = m["params"], m["extent"]
    w, h = m["crop"]["w"], m["crop"]["h"]
    mpp = p["mPerPx"]
    assert abs((city.rotation_deg - 45) % 360 - p["bearing"] % 360) < 1e-6, \
        "Google bearing must equal rotation - 45"
    cell = mpp * 2 * math.sqrt(2)
    storey = (true_storey_px(cell) if native_height
              else STOREY_M * math.cos(math.radians(p["elev"])) / mpp)
    ox, oy = Transformer.from_crs("EPSG:4326", city.crs, always_xy=True).transform(p["lon"], p["lat"])
    tx, ty = -e["left"] / mpp, e["top"] / mpp     # Google's target is screen (0, 0) m
    cam = Camera(origin_x=ox, origin_y=oy, rotation_deg=city.rotation_deg, cell_m=cell,
                 width_px=w, height_px=h, storey_px=storey,
                 centre_shift_px=(tx - w / 2, ty - h / 2))
    return cam, m
