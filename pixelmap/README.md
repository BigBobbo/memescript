# pixelmap

Turns OpenStreetMap data into a pixel-art isometric city map, built for print
and framing. Limerick first; a second city is meant to be a config folder, not a
second project.

**Status:** M2 in progress. Data pipeline, orientation analysis and the
schematize stage are built: every street, bank and footprint is snapped onto the
eight directions that render as crisp isometric lines (70% of road length, up
from 11%). Framed with the Shannon low and west on the right, at Pixorama-scale
detail (8 m frontage = 53 px). Styling is next. See [`PLAN.md`](PLAN.md) for the full design and
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
| `fetch` | Download OSM layers to `cities/<city>/cache/raw/` (cached; `--force` to refresh) |
| `bearings` | Street-orientation analysis; writes rose figures to `analysis/` |
| `greybox --fit` | Render the locked frame, plus a landmark-annotated copy |
| `greybox --study` | Six framing variants as a contact sheet |
| `greybox --orientations` | All four quarter turns compared |
| `frame` | Render the configured frame — the composition of record. `--cell` trades detail for speed, `--raw` skips snapping |

Renders land in `cities/<city>/out/` (gitignored); evidence kept for each gate
lives in `cities/<city>/gates/`.

## How a city is configured

Everything Limerick-specific is data under `cities/limerick/`:

| File | Contents |
|---|---|
| `city.toml` | bbox, CRS, rotation, cell size, frame extents, print size, seed |
| `landmarks.toml` | tier-1/2 landmarks — anchors for framing and, later, sprites |
| `cache/raw/` | the committed OSM snapshot, so a print stays reproducible |

The pipeline never branches on city name.

## Pipeline stages

`fetch` → `extract` → `schematize` → `discretize` → `decorate` → `render` → `compose`

Stages 0–2 are built. `frame` short-circuits from schematize to a throwaway
grey-box renderer so composition and geometry can be judged before the real
renderer exists; `--raw` skips schematize to show true OSM geometry.

## Attribution

Map data © OpenStreetMap contributors, ODbL. Any print carries this credit.
