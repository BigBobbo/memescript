"""Cartoon passes over the Google 3D Tiles render. Local experiment only (PLAN.md §13).

Usage (from pixelmap/):
    PYTHONPATH=. ../.venv/bin/python experiments/google3d/cartoon.py experiments/google3d/out

Needs opencv-python-headless and scikit-learn in the venv. Writes into OUTDIR:
    cartoon_toon.png     smoothed flat colour, fixed palette, ink outlines
    cartoon_pixel.png    the same at 2x2 pixel blocks, the pixel-art look
    cartoon_*.jpg        previews and crop sheet

Water: the photo water is patchy (tide, tint, glint), so it is replaced by a
flat fill. OSM water, registered through camera_match, says where to look; low
local texture decides, since water is smooth and the woods OSM over-fills at
King's Island are not. Bridge decks are cut out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from sklearn.cluster import MiniBatchKMeans

sys.path.insert(0, str(Path(__file__).parent))
from camera_match import matched_camera  # noqa: E402
from pixelmap.cli import _extract_cached  # noqa: E402
from pixelmap.config import load_city  # noqa: E402

out = Path(sys.argv[1])
city = load_city("limerick")
camera, _ = matched_camera(out, city)
layers = _extract_cached(city)
src = cv2.cvtColor(cv2.imread(str(out / "limerick_iso_full.png")), cv2.COLOR_BGR2RGB)
H, W = src.shape[:2]


def correct(img):
    """Grey-world white balance, lifted shadows, local contrast — undo the aerial haze."""
    f = img.astype(np.float32)
    means = f.reshape(-1, 3).mean(0)
    f *= means.mean() / means
    lab = cv2.cvtColor(np.clip(f, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB)
    L = lab[..., 0].astype(np.float32) / 255
    L = np.power(L, 0.72)                           # open the baked shadows
    lab[..., 0] = np.clip(L * 255, 0, 255).astype(np.uint8)
    lab[..., 0] = cv2.createCLAHE(2.0, (16, 16)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


photo = src
src = correct(src)

WATER = (78, 132, 160)
INK = (34, 30, 40)
N_COLOURS = 28


def poly_mask(polys, lift_m=0.0):
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    lift = lift_m / 3.2 * camera.storey_px
    for poly in polys:
        for g in getattr(poly, "geoms", [poly]):
            if g.geom_type != "Polygon" or g.is_empty:
                continue
            d.polygon([(x, y - lift) for x, y in map(lambda c: camera.ground(*c), g.exterior.coords)], fill=255)
            for hole in g.interiors:
                d.polygon([(x, y - lift) for x, y in map(lambda c: camera.ground(*c), hole.coords)], fill=0)
    return np.array(img) > 0


# --- water mask -------------------------------------------------------------
water = poly_mask([a.geom for a in layers.water])
bridges = [r.geom.buffer(r.width_m / 2 + 3, cap_style=2) for r in layers.roads if r.bridge]
deck = np.zeros_like(water)
for lift in range(0, 11, 2):                       # sweep the deck up through its pier height
    deck |= poly_mask(bridges, lift)
# Water in the photo is smooth; woods, mudflats, roofs and foam are textured. OSM says
# roughly where to look; texture decides. Colour alone cannot split water from woods.
Lp = cv2.cvtColor(photo, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
mu = cv2.blur(Lp, (15, 15))
flat = np.sqrt(np.maximum(cv2.blur(Lp * Lp, (15, 15)) - mu * mu, 0)) < 6
band = cv2.dilate(water.astype(np.uint8), np.ones((61, 61), np.uint8)) > 0
core = cv2.erode((water & flat).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
cand = band & flat & ~deck
n, lbl = cv2.connectedComponents(cand.astype(np.uint8))
keep = np.zeros(n, bool); keep[np.unique(lbl[core])] = True; keep[0] = False
water = cv2.morphologyEx(keep[lbl].astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)) > 0
# Fill specks (boats, glints) but leave islands, the weir foam and the tidal banks.
n, lbl, st, _ = cv2.connectedComponentsWithStats((~water).astype(np.uint8), connectivity=4)
small = st[:, cv2.CC_STAT_AREA] < 3000
water |= small[lbl] & (lbl > 0)
water &= ~deck
water = cv2.morphologyEx(water.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0
print(f"water {water.mean()*100:.1f}% of canvas, bridge decks {deck.mean()*100:.1f}%")

# --- toon pass --------------------------------------------------------------
smooth = src.copy()
for _ in range(4):                                  # flatten texture, keep edges
    smooth = cv2.bilateralFilter(smooth, 9, 40, 7)
smooth = cv2.pyrMeanShiftFiltering(smooth, 8, 26)

# Lift the flat, hazy aerial look: more saturation and a touch of brightness.
hsv = cv2.cvtColor(smooth, cv2.COLOR_RGB2HSV).astype(np.float32)
hsv[..., 1] = np.clip(hsv[..., 1] * 1.3, 0, 255)
hsv[..., 2] = np.clip(hsv[..., 2] * 1.04 + 6, 0, 255)
smooth = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

# Shared palette fitted on land only, so the water fill stays its own colour.
land = smooth[~water]
km = MiniBatchKMeans(N_COLOURS, random_state=2157, batch_size=8192, n_init=3)
km.fit(land[np.random.default_rng(2157).choice(len(land), 200_000, replace=False)])
palette = km.cluster_centers_.astype(np.uint8)
# Cartoon palette: push each entry's saturation and value, warm the greys a touch.
ph = cv2.cvtColor(palette[None], cv2.COLOR_RGB2HSV).astype(np.float32)[0]
ph[:, 1] = np.clip(ph[:, 1] * 1.3 + 6, 0, 200)
ph[:, 2] = np.clip(ph[:, 2] * 1.08 + 10, 0, 250)
palette = cv2.cvtColor(ph[None].astype(np.uint8), cv2.COLOR_HSV2RGB)[0]


def quantise(img):
    flat = img.reshape(-1, 3)
    return palette[km.predict(flat)].reshape(img.shape)


toon = quantise(smooth)

# Water: one flat fill.
toon[water] = WATER


def ink(img, thick):
    grey = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    grey = cv2.medianBlur(grey, 5)
    edges = cv2.Canny(grey, 50, 130)
    edges[cv2.dilate(water.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0] = 0
    n, lbl, st, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    edges = (st[lbl, cv2.CC_STAT_AREA] >= 25) & (lbl > 0)    # drop speckle
    edges = edges.astype(np.uint8) * 255
    edges |= cv2.Canny(water.astype(np.uint8) * 255, 50, 150)
    if thick > 1:
        edges = cv2.dilate(edges, np.ones((thick, thick), np.uint8))
    return edges > 0


toon_ink = toon.copy()
toon_ink[ink(smooth, 2)] = INK
Image.fromarray(toon_ink).save(out / "cartoon_toon.png")

# --- pixel pass: 2x2 blocks, nearest, 1-px ink at block scale ---------------
B = 2
small = cv2.resize(smooth, (W // B, H // B), interpolation=cv2.INTER_AREA)
small_water = cv2.resize(water.astype(np.uint8), (W // B, H // B), interpolation=cv2.INTER_NEAREST) > 0
px = quantise(small)
px[small_water] = WATER
edges = cv2.resize(ink(smooth, 1).astype(np.uint8), (W // B, H // B), interpolation=cv2.INTER_AREA) > 0
px[edges] = INK
pixel = cv2.resize(px, (W // B * B, H // B * B), interpolation=cv2.INTER_NEAREST)
Image.fromarray(pixel).save(out / "cartoon_pixel.png")

# --- previews -----------------------------------------------------------------
for name, img in (("toon", toon_ink), ("pixel", pixel)):
    t = Image.fromarray(img)
    t.thumbnail((2000, 2000), Image.LANCZOS)
    t.save(out / f"cartoon_{name}_preview.jpg", quality=90)

boxes = {"castle": (1500, 1450, 2600, 2100), "georgian": (2400, 100, 3500, 750)}
for name, (x0, y0, x1, y1) in boxes.items():
    tiles = [photo[y0:y1, x0:x1], toon_ink[y0:y1, x0:x1], pixel[y0:y1, x0:x1]]
    sheet = np.full((y1 - y0, (x1 - x0) * 3 + 20, 3), 255, np.uint8)
    for i, t in enumerate(tiles):
        sheet[:, i * (x1 - x0 + 10):i * (x1 - x0 + 10) + (x1 - x0)] = t
    Image.fromarray(sheet).save(out / f"cartoon_crop_{name}.jpg", quality=90)
print("wrote", out)
