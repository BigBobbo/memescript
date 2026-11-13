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
