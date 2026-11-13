"""Render the Google test patch through our own pipeline, pixel-registered.

Usage (from pixelmap/):
    PYTHONPATH=. ../.venv/bin/python experiments/google3d/compare.py experiments/google3d/out

Reads OUTDIR/manifest.json and OUTDIR/limerick_iso_full.png (from render.mjs +
stitch.py) and writes, into OUTDIR:
    pipeline_raw.png        grey-box, true OSM geometry (registration check)
    pipeline_painted.png    the painted renderer, schematized as in `frame`
    compare_side.jpg        Google | pipeline, side by side
    compare_overlay.jpg     raw OSM footprint and water outlines over Google
    crop_*.jpg              full-resolution detail pairs

Camera match: Google's ortho camera at 30° elevation puts a ground point d m
along screen-right at d m, and d m forward at d/2 m up the screen — the same
2:1 as iso.py. At M m/px that is a cell of M * 2 * sqrt(2). Height differs:
ortho gives cos 30° = 0.866 m of screen per metre of height, iso.py's true
isometric gives 0.707. Both are rendered at Google's scale here so the
silhouettes can be compared; `--native-height` uses ours.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from pyproj import Transformer

from pixelmap.cli import _extract_cached, _landmark_config
from pixelmap.config import load_city
from pixelmap.frame import true_storey_px
from pixelmap.iso import STOREY_M, Camera

out = Path(sys.argv[1])
native_height = "--native-height" in sys.argv
m = json.loads((out / "manifest.json").read_text())
p, e = m["params"], m["extent"]
W, H = m["crop"]["w"], m["crop"]["h"]
mpp = p["mPerPx"]

city = load_city("limerick")
assert abs((city.rotation_deg - 45) % 360 - (p["bearing"] % 360)) < 1e-6, \
    "Google bearing must equal rotation - 45"

cell = mpp * 2 * math.sqrt(2)
storey = (true_storey_px(cell) if native_height
          else STOREY_M * math.cos(math.radians(p["elev"])) / mpp)
ox, oy = Transformer.from_crs("EPSG:4326", city.crs, always_xy=True).transform(p["lon"], p["lat"])
# Google's target point sits at screen (0, 0) in metres: x = -left, y = top.
target_px = (-e["left"] / mpp, e["top"] / mpp)
camera = Camera(origin_x=ox, origin_y=oy, rotation_deg=city.rotation_deg, cell_m=cell,
                width_px=W, height_px=H, storey_px=storey,
                centre_shift_px=(target_px[0] - W / 2, target_px[1] - H / 2))
print(f"cell {cell:.4f} m · storey {storey:.2f} px · canvas {W}x{H}")

layers = _extract_cached(city)

# 1. Raw grey-box: true OSM geometry, the fair registration check.
from pixelmap.greybox import render as grey_render
raw, _ = grey_render(layers, camera)
raw.save(out / "pipeline_raw.png")

# 2. Painted, schematized exactly as `frame` does.
from pixelmap.landmarks import load_models
from pixelmap.paint import render as paint_render
from pixelmap.schematize import schematize
from pixelmap.style import STYLES

sc = city.config["schematize"]
sch = schematize(layers, city.rotation_deg, road_simplify_m=sc["road_simplify_m"],
                 water_simplify_m=sc["water_simplify_m"],
                 street_widen_m=sc.get("street_widen_m", 0.0))
models, superseded = load_models(_landmark_config(city))
painted, stats = paint_render(sch, camera, STYLES["limerick-day"], city.seed,
                              models=models, superseded=superseded)
painted.save(out / "pipeline_painted.png")
print(f"painted {stats.buildings} buildings, {stats.landmarks} landmarks")

google = Image.open(out / "limerick_iso_full.png").convert("RGB")


def thumb(img, w=1600):
    t = img.copy()
    t.thumbnail((w, w), Image.LANCZOS)
    return t


# Side by side.
a, b = thumb(google), thumb(painted)
side = Image.new("RGB", (a.width + b.width + 10, a.height), "white")
side.paste(a, (0, 0)); side.paste(b, (a.width + 10, 0))
side.save(out / "compare_side.jpg", quality=88)

# Overlay: raw OSM outlines (ground level) on Google.
overlay = google.copy()
d = ImageDraw.Draw(overlay)


def rings(geom):
    if geom.is_empty:
        return
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type == "Polygon":
            yield g.exterior
            yield from g.interiors


for w in layers.water:
    for r in rings(w.geom):
        d.line([camera.ground(*c) for c in r.coords], fill=(0, 200, 255), width=3)
for bld in layers.buildings:
    for r in rings(bld.geom):
        d.line([camera.ground(*c) for c in r.coords], fill=(255, 40, 40), width=1)
overlay.save(out / "compare_overlay_full.png")
thumb(overlay, 2000).save(out / "compare_overlay.jpg", quality=88)

# Full-resolution detail pairs (Google pixel boxes).
crops = {"castle": (1500, 1450, 2600, 2100), "weir": (1900, 1050, 3000, 1600),
         "georgian": (2400, 100, 3500, 750)}
for name, box in crops.items():
    g, q = google.crop(box), painted.crop(box)
    pair = Image.new("RGB", (g.width, g.height * 2 + 6), "white")
    pair.paste(g, (0, 0)); pair.paste(q, (0, g.height + 6))
    pair.save(out / f"crop_{name}.jpg", quality=90)
print("wrote", out)
