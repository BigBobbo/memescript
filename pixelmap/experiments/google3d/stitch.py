"""Stitch render.mjs shots into one image. Usage: python3 stitch.py OUTDIR"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1])
m = json.loads((out / "manifest.json").read_text())
n = m["shotPx"]
canvas = Image.new("RGB", (m["cols"] * n, m["rows"] * n), "white")
for s in m["shots"]:
    canvas.paste(Image.open(out / s["file"]).convert("RGB"), (s["c"] * n, s["r"] * n))
canvas = canvas.crop((0, 0, m["crop"]["w"], m["crop"]["h"]))

credit = "Google 3D Tiles: " + "; ".join(m["attributions"])
ImageDraw.Draw(canvas).text((8, canvas.height - 16), credit, fill=(0, 0, 0))
canvas.save(out / "limerick_iso_full.png")

# A preview small enough to view at a glance.
preview = canvas.copy()
preview.thumbnail((2000, 2000), Image.LANCZOS)
preview.save(out / "limerick_iso_preview.jpg", quality=88)
print(canvas.size, "->", out / "limerick_iso_full.png")
