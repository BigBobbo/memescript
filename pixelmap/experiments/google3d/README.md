# Google 3D Tiles isometric test

A one-off test, not part of the pipeline: renders about 1 km² of Google Photorealistic 3D Tiles
around King John's Castle with an orthographic 2:1 camera matching `iso.py`
(rotation 212.75°, so it looks toward bearing 167.75°). It checks mesh quality and the water problem.

PLAN.md §13 rules out Google 3D Tiles derivatives in the print. Outputs stay
local (`out/` is gitignored).

```bash
npm install
GOOGLE_MAPS_API_KEY=... node render.mjs out   # Map Tiles API must be enabled on the key
python3 stitch.py out                          # -> out/limerick_iso_full.png, _preview.jpg
```

Env overrides: `LAT`, `LON`, `ACROSS`, `DEEP` (m), `M_PER_PX` (default 0.25),
`ERROR_TARGET` (default 4; lower = more detail, slower), `BEARING`.

## Comparing against our pipeline

```bash
cd pixelmap
PYTHONPATH=. ../.venv/bin/python experiments/google3d/compare.py experiments/google3d/out
```

Renders the same patch through `paint` and `greybox` with a camera matched pixel for pixel
(cell = `M_PER_PX` × 2√2 = 0.707 m; storey scaled to the ortho cos 30° so silhouettes are
comparable, `--native-height` for ours). It writes side-by-side, an OSM-outline overlay on
the Google render, and full-resolution crop pairs into `out/`.

## Findings (run 2026-11-13, defaults)

**Google render.** 4 × 3 shots, 4000 × 2329 px, about 15 min. No failed tiles. Ground probe 58 m.
- Mesh is good: the castle's drum towers, Thomond Bridge's arches, rooflines and cars are crisp.
  Trees are soft blobs. No seams at shot edges.
- Water is not usable as drawn. The texture is flat but carries patchwork tint (blue near the
  castle, silty brown upstream), tide-exposed mudflats, weir foam and sun glint.

**Registration.** Raw OSM water and footprint outlines land on the Google banks and buildings,
so `iso.py`'s rotation, 2:1 and origin agree with a true ortho camera at bearing 167.75°.

**What the comparison shows about the pipeline.**

| Area | Google (ground truth) | Pipeline today | Lead |
|---|---|---|---|
| Abbey River / King's Island | Narrow channel, wooded bank | Water fills the wooded bank too, in raw *and* painted | Water regions from `extract` over-fill; check coastline region assembly there |
| Shannon banks | Irregular, mudflats | Matches the OSM bank; `water_simplify_m = 45` smooths it acceptably | — |
| Georgian core heights | Mostly 3–5 storeys | Mostly 2: within 300 m of O'Connell St, 629 of 714 buildings are untagged and fall to `default_levels = 2` (tagged median 3) | Per-area default, e.g. 4 inside the Newtown Pery grid |
| Street width | Narrow, continuous terraces | Visibly wide, gaps between rows (`street_widen_m = 3.5`) | Expected trade-off; Google shows how far it departs |
| Thomond Bridge | Seven arches, parapets | Flat slab | Arches in the bridge model |
| Castle | — | Modelled castle lines up with the real one | — |
| Trees | Dense along the river and in gardens | None | Already next on the plan |
