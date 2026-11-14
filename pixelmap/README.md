# pixelmap

Turns OpenStreetMap data into a pixel-art isometric city map, built for print
and framing. Limerick first; a second city is meant to be a config folder, not a
second project.

**Status:** Stages 0-2 and 5 are built — fetch, extract, schematize, and a
painted renderer with pitched roofs, windowed facades, shopfronts, walled quays
and raised bridge decks. Streets, banks and footprints are snapped onto the
eight directions that render as crisp isometric lines (70% of road length, up
from 11%). Buildings are drawn at true isometric height with streets widened
3.5 m per side instead. Framed with the Shannon low and west on the right,
2868 × 1860 m of ground at 0.3 m per cell — 27036 × 8768 px, 9,833 buildings,
an 8 m frontage 60 px of wall — reaching from Ted Russell Dock to King John's
Castle and Colbert. Eight landmarks are modelled from their own OSM footprints
rather than drawn as sprites: the castle's crenellated curtain wall and drum
towers, St John's 90 m spire, St Mary's battlemented tower, the Milk Market
canopy, Colbert's train shed, the Hunt Museum, Riverpoint and the Treaty Stone.
Trees, boats and the compose stage are next. See [`PLAN.md`](PLAN.md) for the full design and
[`M1-FINDINGS.md`](M1-FINDINGS.md) for what M1 measured and locked.

## Setup

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python numpy shapely pyproj pillow
```

## Use

Run from this directory with `PYTHONPATH=.`:

```bash
PYTHONPATH=. ../.venv/bin/python -m pixelmap.cli <command> limerick
```

| Command | What it does |
|---|---|
| `fetch` | Download OSM layers to `cities/<city>/cache/raw/` (cached; `--force` to refresh). `--pbf FILE` builds the same cache from a local `.osm.pbf` extract (e.g. openstreetmap.fr's `ireland.osm.pbf`) when Overpass is down or refuses the connection; needs `osmium` |
| `lidar` | Download OPW lidar tiles to `cities/<city>/cache/lidar/` for building heights; `--calibrate` scores the height percentile against OSM-tagged storeys |
| `bearings` | Street-orientation analysis; writes rose figures to `analysis/` |
| `greybox --fit` | Render the locked frame, plus a landmark-annotated copy |
| `greybox --study` | Six framing variants as a contact sheet |
| `greybox --orientations` | All four quarter turns compared |
| `frame` | Render the configured frame — the composition of record. `--scale` changes how much city is in shot, `--cell` how finely it is drawn (so speed), `--grey` for grey-box, `--raw` skips snapping |
| `frontages` | Rank facades by visible wall area; writes `facades.md` |

Renders land in `cities/<city>/out/` (gitignored); evidence kept for each gate
lives in `cities/<city>/gates/`.

## How a city is configured

Everything Limerick-specific is data under `cities/limerick/`:

| File | Contents |
|---|---|
| `city.toml` | bbox, CRS, rotation, cell size, frame extents, print size, seed |
| `landmarks.toml` | `[[landmark]]` anchors for framing checks; `[[model]]` recipes, heights and materials for the named buildings |
| `cache/raw/` | the committed OSM snapshot, so a print stays reproducible |
| `cache/lidar/` | OPW lidar DSM/DTM tiles (about 70 MB, not committed; `pixelmap lidar` re-downloads them) |

The pipeline never branches on city name.

## Pipeline stages

`fetch` → `extract` → `schematize` → `discretize` → `decorate` → `render` → `compose`

Stages 0–2 and 5 are built. `discretize` and `decorate` are not yet needed —
the renderer draws from schematized vector geometry directly.

Inside `render`, three modules split by what changes them: `draw3d` is the
isometric primitives (extrude a ring, crenellate it, put a spire on it),
`landmarks` decides what a named building is made of, and `monuments` draws it.

`--grey` falls back to the grey-box renderer for judging composition; `--raw`
skips schematize to show true OSM geometry.

## Attribution

Map data © OpenStreetMap contributors, ODbL. Any print carries this credit.

Building heights: Contains Irish Public Sector Data (Geological Survey Ireland & the Office
of Public Works) licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0)
licence. Required on any print while `[heights] lidar = true`.

## Heights

OSM tags storeys on 18% of buildings. The rest take their height from OPW's 2011 2 m lidar:
surface minus terrain inside each footprint, pulled in 1 m from the walls, at the 60th
percentile of the roof returns. Against the 3,871 tagged buildings that gives a mean error of
0.20 storeys with no bias. In the Georgian core the median goes from the default 2 storeys to 3,
with 4–5 common, which matches the Google 3D Tiles comparison in `experiments/google3d/`.
Tags still win. A footprint with no roof returns, usually built after 2011, keeps the default.
