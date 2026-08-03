# Could Limerick have an Isopolis? · feasibility findings

*Researched 2026-08-03, against [sf.isopolis.city](https://sf.isopolis.city/dev.html).
Coverage claims below were checked against live services, not guessed.*

Isopolis is an interactive isometric pixel-art map of San Francisco: ~121 km²
at ~22 gigapixels, served as a 9-level zoomable tile pyramid with clickable
annotations, neighbourhood boundaries, tours and shareable view state. It was
**not** drawn procedurally. The pipeline was: render Google Photorealistic 3D
Tiles orthographically in a dimetric frame → fine-tune an image model
(Qwen-Image-Edit, ~55M-param LoRA, ~101 hand-approved training pairs) to
translate those renders into pixel art → generate ~1,500 overlapping windows →
manually correct ~200 → serve as static tiles.

So the feasibility question splits into three separate questions with three
separate answers.

## 1. Does Limerick have the data Isopolis was built from? — Yes

The one irreplaceable input is Google's photogrammetric 3D mesh (the
Photorealistic 3D Tiles API serves the same mesh Google Earth shows).

- Google's Map Tiles API coverage table lists **Ireland: 2D ⬤ / 3D ⬤**.
- The community-maintained Google Earth 3D coverage list names **Limerick**
  explicitly, alongside Dublin, Cork, Galway, Athlone, Kilkenny, Dundalk and
  Tralee.

So the "SF has much better data" worry is mostly unfounded for this route.
Limerick's mesh will be coarser and older than San Francisco's (SF is one of
Google's flagship photogrammetry cities), which means the pixel-art model has
blurrier conditioning to work from — a quality tax, not a blocker. The
translation-to-pixel-art step is forgiving of mesh blur; Isopolis itself had to
hand-fix the Golden Gate Bridge because photogrammetry mangled it, and our
equivalent fixes (the castle, the spire) are exactly what `landmarks.toml`
already does.

Scale is also in our favour: Limerick's urban core is ~15 km² against
Isopolis's 121 km². At the same pixel density that is roughly **2–3 gigapixels
vs 22** — an order of magnitude less generation, review and correction work.

**The real constraint on this route is legal, not data.** Google Maps Platform
terms prohibit both bulk export of tiles as static imagery and using the
content to train ML models. Isopolis did it anyway; whether to accept that risk
for a personal project is a judgement call, but it should be made knowingly.

## 2. Does Limerick have the open data for the route this repo takes? — Yes, measured

Already confirmed in [M1-FINDINGS.md](M1-FINDINGS.md): 21,949 OSM building
footprints in the 4.4 × 4.1 km fetch window, roads, water, rail, green, 148
POIs. The known weakness is heights — few `building:levels` tags, so we default
to 2 storeys and hand-model the eight landmarks.

New finding: **open LiDAR covers Limerick city**, and it closes the height gap.
Queried the GSI download services over the city-centre envelope
(ITM 556000–559000 E, 655000–658500 N):

| Dataset | Resolution | Captured | Licence |
|---|---|---|---|
| OPW flood-study LiDAR (DSM+DTM) | 2 m | Oct 2006 | CC-BY 4.0 |
| OPW NASC LiDAR (DSM+DTM) | 2 m | 2011 | CC-BY 4.0 |
| TII route corridor LiDAR | 2 m | 2010–11 | CC-BY 4.0 |

(The newer 1 m GSI Phase 2 / DCHG surveys return **zero** tiles over the city
centre — 2 m is what exists.) Tiles are direct ZIP downloads from
`gsi.geodata.gov.ie`, e.g. `OPW_949`–`OPW_973` for the NASC set.

**This is now built and measured** — see `pixelmap lidar` and
[analysis/heights.md](cities/limerick/analysis/heights.md). 20,364 of 21,949
footprints (92.8%) got a height, and the flat skyline is gone: 51% of them are
not 2 storeys.

One prediction in the first draft of this note was wrong. Taking the *median*
of DSM−DTM per footprint, as suggested above, measures badly at 2 m — a terrace
is three pixels across and a pixel on the outline averages roof with pavement,
so low and middle statistics sample the mixing rather than the building. The
contamination is one-directional (mixed pixels always read low), so the working
method reads a *high* percentile and calibrates it back down:

    roof_85 = storey_m * levels + pitch_m

fitted per city against the buildings OSM has already tagged. Limerick fits
2.93 m a storey under 1.25 m of roof pitch — the intercept being the roof's own
height above the eave, which is why the relation is physical rather than a
curve fit. Scored on tagged buildings held out of the fit, and against the flat
default it replaces:

| | LiDAR | Flat 2-storey default |
|---|---|---|
| Within half a storey (all 1,916) | 95% | 88% |
| Within half a storey (the 225 that aren't 2-storey) | 82% | 0% |
| Mean absolute error (those 225) | 0.46 | 1.30 |

The totals understate it because most tagged buildings really are 2 storeys, so
the flat default scores well on the bulk; the second row is where a skyline is
won or lost. Vintage (2011) means post-2011 buildings read as bare ground, fail
the minimum-height test and keep their tag-or-default height rather than being
flattened.

Boundaries (electoral divisions, city boundary) are on data.gov.ie under open
licences, filling the role SF's neighbourhood polygons play for Isopolis's
clickable regions.

## 3. Is the interactive product feasible? — Yes, and it is built

Everything that makes Isopolis feel alive — the tile pyramid, deep zoom,
clickable landmarks, neighbourhood outlines, tours, URL-hash share links,
ambient sound — consumes **one big image plus small JSON**. None of it cares
whether the image came from an ML model or our renderer.

`pixelmap site` now does this: it renders the frame, cuts it into 256 px tiles
across a halving pyramid, and writes a self-contained viewer beside them. At
0.9 m per cell that is 583 tiles over 7 levels, 7.9 MB, with 14 landmark
markers placed by pushing `landmarks.toml` anchors through the same camera that
drew the frame — so a marker cannot drift off the building under it. Drag to
pan, wheel to zoom, click a landmark, and the view state lives in the URL hash
so a view can be sent to someone. The locked print frame at 0.3 m per cell is
27,036 × 8,768 px (~237 MP) and needs only a longer render; the tiling and the
viewer do not change.

## Recommendation

Two viable routes, one recommended:

- **Route A — Isopolis-style ML restyle** of Google 3D tile renders. Data
  exists (mesh confirmed), scale is 10× smaller than SF, but it needs a
  hand-built training set, GPU fine-tuning budget, a manual correction pass,
  and a knowing decision about Google's terms. It also throws away the
  schematize work: ML output is organic, not grid-crisp.

- **Route B — finish what's here, then build the viewer** (recommended, and
  now done). The procedural renderer already produces consistent pixel art at
  gigapixel-class resolution from fully open data. Both missing Isopolis
  ingredients are built: real heights (`pixelmap lidar`, CC-BY data) and the
  zoomable viewer (`pixelmap site`). Nothing about Limerick's data limited this
  route.

What is left is content rather than capability: tours, neighbourhood
boundaries from the CSO/OSi electoral divisions, per-building info on click
(OSM already carries the names and addresses), and a full-resolution render at
0.3 m per cell.

The honest gap between an eventual Limerick page and sf.isopolis.city is
texture richness at extreme zoom: an ML model hallucinates plausible detail
everywhere, a procedural renderer draws what it is told. The counterweights
are crisp geometry, reproducibility, print-safety and a clean licence.
