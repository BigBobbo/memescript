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

New finding: **open LiDAR covers Limerick city**, which can close the height
gap. Queried the GSI download services over the city-centre envelope
(ITM 556000–559000 E, 655000–658500 N):

| Dataset | Resolution | Captured | Licence |
|---|---|---|---|
| OPW flood-study LiDAR (DSM+DTM) | 2 m | Oct 2006 | CC-BY 4.0 |
| OPW NASC LiDAR (DSM+DTM) | 2 m | 2011 | CC-BY 4.0 |
| TII route corridor LiDAR | 2 m | 2010–11 | CC-BY 4.0 |

(The newer 1 m GSI Phase 2 / DCHG surveys return **zero** tiles over the city
centre — 2 m is what exists.) Tiles are direct ZIP downloads from
`gsi.geodata.gov.ie`, e.g. `OPW_949`–`OPW_973` for the NASC set.

2 m DSM−DTM medians per footprint give per-building height estimates good to
roughly a storey — coarse for architecture, fine for pixel-art massing, and it
would replace the flat `default_levels = 2` skyline with the real one. Vintage
(2006–2011) means post-2011 buildings keep their tag-or-default height.

Boundaries (electoral divisions, city boundary) are on data.gov.ie under open
licences, filling the role SF's neighbourhood polygons play for Isopolis's
clickable regions.

## 3. Is the interactive product feasible? — Yes, and it is data-independent

Everything that makes Isopolis feel alive — the tile pyramid, deep zoom,
clickable landmarks, neighbourhood outlines, tours, URL-hash share links,
ambient sound — consumes **one big image plus small JSON**. None of it cares
whether the image came from an ML model or our renderer. The current locked
frame is already 27,036 × 8,768 px (~237 MP); cut into a tile pyramid that is a
static site, hostable anywhere, with landmark anchors already in
`landmarks.toml` to drive annotations.

## Recommendation

Two viable routes, one recommended:

- **Route A — Isopolis-style ML restyle** of Google 3D tile renders. Data
  exists (mesh confirmed), scale is 10× smaller than SF, but it needs a
  hand-built training set, GPU fine-tuning budget, a manual correction pass,
  and a knowing decision about Google's terms. It also throws away the
  schematize work: ML output is organic, not grid-crisp.

- **Route B — finish what's here, then build the viewer** (recommended). The
  procedural renderer already produces consistent pixel art at gigapixel-class
  resolution from fully open data. The missing Isopolis ingredients are (1)
  real heights — solvable with the CC-BY LiDAR above, one new pipeline stage —
  and (2) the web viewer — a compose/serve stage, no new data at all. Nothing
  about Limerick's data limits this route; it is strictly an engineering
  backlog.

The honest gap between an eventual Limerick page and sf.isopolis.city is
texture richness at extreme zoom: an ML model hallucinates plausible detail
everywhere, a procedural renderer draws what it is told. The counterweights
are crisp geometry, reproducibility, print-safety and a clean licence.
