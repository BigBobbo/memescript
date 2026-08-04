# pixelmap

Turns OpenStreetMap data into a pixel-art isometric city map, built for print
and framing. Limerick first; a second city is meant to be a config folder, not a
second project.

**Status:** Stages 0-2 and 4-6 are built — fetch, LiDAR heights, extract,
schematize, decorate, a painted renderer with pitched roofs, windowed facades,
shopfronts, walled quays and raised bridge decks, and a zoomable web viewer.
Building heights are measured rather than assumed: open 2011 LiDAR gives 93% of
footprints a height, and half of them turn out not to be the 2 storeys the
pipeline used to assume. The charm layer plants 19,000
trees, floats boats and swans on the river, and puts chimneys on the terraces. Streets, banks and footprints are snapped onto the
eight directions that render as crisp isometric lines (70% of road length, up
from 11%). Buildings are drawn at true isometric height with streets widened
3.5 m per side instead. Framed with the Shannon low and west on the right,
2868 × 1860 m of ground at 0.3 m per cell — 27036 × 8768 px, 9,833 buildings,
an 8 m frontage 60 px of wall — reaching from Ted Russell Dock to King John's
Castle and Colbert. Eight landmarks are modelled from their own OSM footprints
rather than drawn as sprites: the castle's crenellated curtain wall and drum
towers, St John's 90 m spire, St Mary's battlemented tower, the Milk Market
canopy, Colbert's train shed, the Hunt Museum, Riverpoint and the Treaty Stone.
Title, border and legend are next, then the print master. See [`PLAN.md`](PLAN.md)
for the full design, [`M1-FINDINGS.md`](M1-FINDINGS.md) for what M1 measured and
locked, and [`ISOPOLIS-FEASIBILITY.md`](ISOPOLIS-FEASIBILITY.md) for how this
compares with the ML-generated route.

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
| `lidar` | Measure building heights from open LiDAR; writes `cache/lidar/heights.json.gz` and `analysis/heights.md` |
| `bearings` | Street-orientation analysis; writes rose figures to `analysis/` |
| `greybox --fit` | Render the locked frame, plus a landmark-annotated copy |
| `greybox --study` | Six framing variants as a contact sheet |
| `greybox --orientations` | All four quarter turns compared |
| `frame` | Render the configured frame — the composition of record. `--scale` changes how much city is in shot, `--cell` how finely it is drawn (so speed), `--grey` for grey-box, `--raw` skips snapping, `--bare` drops the charm layer, `--measured-ridges` takes roof height from the LiDAR instead of the width-scaled pitch (looks flatter — see `gates/g14`) |
| `frontages` | Rank facades by visible wall area; writes `facades.md` |
| `site` | Cut the frame into a tile pyramid and emit the zoomable web viewer into `out/site/` |

Renders land in `cities/<city>/out/` (gitignored); evidence kept for each gate
lives in `cities/<city>/gates/`.

## How a city is configured

Everything Limerick-specific is data under `cities/limerick/`:

| File | Contents |
|---|---|
| `city.toml` | bbox, CRS, rotation, cell size, frame extents, print size, seed |
| `landmarks.toml` | `[[landmark]]` anchors for framing checks; `[[model]]` recipes, heights and materials for the named buildings |
| `cache/raw/` | the committed OSM snapshot, so a print stays reproducible |

The pipeline never branches on city name.

## Pipeline stages

`fetch` → `lidar` → `extract` → `schematize` → `discretize` → `decorate` → `render` → `compose`

Stages 0–2 and 4–6 are built. `discretize` is not yet needed — the renderer
draws from schematized vector geometry directly.

`decorate` is the charm layer: street trees, park and woodland planting, boats
and swans on the Shannon, chimney stacks on the terraces. None of it is in OSM
— street trees are barely mapped in Ireland and swans not at all — so props are
placed procedurally from the city's seed and are identical run to run. Density
is per green kind, because most of Limerick's "green" is verge and meadow
rather than parkland. `frame --bare` renders without it.

`compose` is `pixelmap site`: it cuts the render into a pyramid of 256 px tiles
and writes a self-contained viewer beside them — deep zoom with the pixels kept
crisp, clickable landmarks placed through the same camera that drew the frame,
and the view state in the URL hash so a particular view can be sent to someone.
Levels halve exactly and reduce with a box filter, the one downscale that
cannot invent a colour the palette does not have.

```bash
PYTHONPATH=. ../.venv/bin/python -m pixelmap.cli site limerick --cell 0.9
python -m http.server -d cities/limerick/out/site 8000
```

Inside `render`, three modules split by what changes them: `draw3d` is the
isometric primitives (extrude a ring, crenellate it, put a spire on it),
`landmarks` decides what a named building is made of, and `monuments` draws it.

`--grey` falls back to the grey-box renderer for judging composition; `--raw`
skips schematize to show true OSM geometry.

## Attribution

Map data © OpenStreetMap contributors, ODbL. Any print carries this credit.

Building heights derive from open LiDAR: Contains Irish Public Sector Data
(Geological Survey Ireland & the Office of Public Works) licensed under a
Creative Commons Attribution 4.0 International (CC BY 4.0) licence. CC-BY
requires the credit, so any print carries this one too.
