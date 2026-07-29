# Limerick Pixel-Art Isometric Map — Research & Plan

*A code-first pipeline that turns OpenStreetMap data into a framed, printed isometric
pixel-art poster of Limerick city — designed so a second city is a config file, not a
second project.*

**Status:** M1 complete — see [`M1-FINDINGS.md`](M1-FINDINGS.md). Gate G1 awaiting sign-off.
**Research date:** 2026-07-27. All data probes and links below were verified live on that date.

> **M1 updated three things in this document.** The rotation is now measured, not
> estimated (−32.75°, plus a +90° compositional turn → **+57.25°**); the cell size
> and frame are solved and locked (**1.812 m**, centre 52.664928/−8.624746, showing
> 1153 × 1537 m); and §4.1's "3 px per storey" was wrong — true isometric at this
> cell size is 3.53 px, now set to **4.5 px**. §4.3's alignment maths also folded at
> 90° where it should fold at 45°. The locked values live in `cities/limerick/city.toml`.

---

## TL;DR

- **The niche is genuinely open.** Nobody has published an OSM → isometric-pixel-art
  pipeline, and no isometric or pixel-art map of Limerick exists as a product at all.
  Every existing tool stops one step short (2D-stylized, realistic-3D, or voxel), and the
  hand-made gold standard (eBoy's Pixoramas) costs ~1,000 hours per city.
- **The data is better than feared.** Limerick's OSM building coverage is effectively
  complete (~22,000 footprints in the wider city bbox) thanks to a 2019 community tracing
  campaign. Storey counts exist on ~23% of core buildings; "2 storeys" is the empirically
  correct default for the rest. Open 2 m lidar (CC-BY) covers the city if we ever want real
  heights. The city core is flat (2–15 m relief) — terrain can be ignored.
- **Limerick is unusually iso-friendly.** The Georgian core (Newtown Pery) is a true
  planned grid bearing ~32.7° east of north. Rotate the whole map by −32.7° and O'Connell
  Street and its cross-streets align exactly with the isometric axes and render as clean
  pixel lines. The medieval quarter and radial roads get snapped to 8 allowed directions;
  the Shannon and Abbey River keep their true curves (stair-stepped, which reads as charm).
- **Recommended architecture:** a deterministic Python pipeline —
  fetch → extract → schematize → discretize (classified iso cell grid + extruded building
  prisms) → decorate → render (custom pixel renderer with palette/outline rules) →
  compose (title, border, integer upscale to exact print pixels). Hand-crafted sprites for
  ~15 landmarks provide the charm. All manual fixes live in a replayable `overrides.yaml`
  edited through a small local web editor — **the bitmap is never the source of truth**,
  which is how we avoid Photoshop entirely.
- **Print target (recommendation):** 61×91 cm landscape, 300 DPI, giclée on smooth matte,
  IKEA RÖDALM frame. Art canvas ~1800×1200 px at ×6 integer upscale (~0.5 mm per art
  pixel — eBoy-density texture from afar, crisp pixels up close).

---

## 1. Goal, constraints, definition of done

**Goal.** One framed print of central Limerick in isometric pixel art that feels like a
piece of art (eBoy / SimCity 2000 lineage), not a data visualization.

**Constraints & principles.**

1. *Code over cursor.* The user is not a Photoshop person. Everything that can be
   automated is; everything that can't becomes structured config or a purpose-built
   editor, never freehand bitmap editing.
2. *Art over accuracy.* Streets may be straightened, geometry simplified, landmarks
   enlarged. eBoy call their versions "misinterpretations" — that is licence, not failure.
3. *Reproducible.* Same inputs + same config + same seed ⇒ identical PNG. The final
   print file can be regenerated from the repo forever.
4. *City-agnostic core.* Limerick knowledge lives in `cities/limerick/` (config, palette
   accents, landmark sprites, overrides). The pipeline itself never hard-codes Limerick.

**Definition of done.**

- `pixelmap build limerick --print` emits a print-master file (exact pixel dimensions for
  the chosen size, sRGB, 300 DPI metadata) plus a screen preview.
- A test print has been approved, the final print ordered, framed, and on the wall.

---

## 2. Research digest

Three research passes were run (prior art; assets/print craft; geodata/algorithms), plus
live Overpass API probes of Limerick. Full link list in the Appendix. What matters:

### 2.1 Prior art — the landscape

| Project | What it proves | Licence | Take |
|---|---|---|---|
| [eBoy Pixorama posters](https://www.eboy.com/) | The quality bar; sells as framed art (A0, offset, matte stock) | Proprietary | Hand-made: 3 people, 6–8 weeks, a shared library of 5,000+ reusable isometric elements. Not geographically accurate — landmark compressions. Borrow the *modular element library* idea and the permission to bend geography. |
| [Brett Camper's 8-Bit Cities](https://8bitnyc.com/) (2010) | Automated OSM → pixel-art works and handles non-grid streets | No code released | Architecture: per-tile spatial classification of OSM (road? park? water?) → stamp a hand-drawn tile. Stair-stepped streets read as charming. **This is our architecture, lifted from 2D to isometric.** |
| [prettymaps](https://github.com/marceloprates/prettymaps) (12.3k★) | "Code-generated OSM art as wall decor" is a proven category | AGPL-3.0 | 2D only. Borrow osmnx layer-fetch patterns (via MIT osmnx directly, not AGPL code). |
| [OSM2World](https://osm2world.org/) | Real isometric renders of OSM exist today (`--oview.angle`, `--oview.from` CLI) | MIT | Realistic textures fight the pixel aesthetic. Useful as a *reference renderer* to sanity-check Limerick's 3D data. |
| [VoxCity](https://github.com/kunifujiwara/VoxCity) (374★, peer-reviewed) | OSM/Overture → integrated voxel city model → **exports MagicaVoxel .vox** | MIT | The one real "osm2vox" bridge. Perfect for a cheap week-one morale render (see §3.3), not for the final pixel-art look. |
| [arnis](https://github.com/louis-e/arnis) (17.1k★) | OSM → Minecraft in high detail | Apache-2.0 | Its heuristics for voxelizing footprints, road widths, water are directly instructive for our discretize stage. |
| [isocity](https://github.com/victorqribeiro/isocity) (3.2k★) | Painter's-order iso tile stamping is ~200 lines of code | MIT | Model for our compositor loop. Uses Kenney CC0 tiles. |
| Aerialod + [Alasdair Rae's city renders](http://www.statsmapsnpix.com/2019/11/amazing-3d-rendering-with-aerialod.html) | Path-traced voxel city renders from lidar look gorgeous | Freeware (closed) | A plan-B aesthetic; Windows-only, not pixel art, little control. |
| "Isometric NYC" ([writeup](https://rogerwong.me/2026/02/isometric-nyc)) by Andy Coenen (2026) | Closest thing to our exact goal, done with fine-tuned image models over Google 3D Tiles | No code; restrictive data ToS | Existence proof + warnings: water and trees were the AI failure modes; heavy manual QA. His line — "when hard parts become easy, the differentiator becomes love" — is the thesis of our landmark/charm layer. |
| Etsy/Displate market | Isometric pixel city prints sell; only generic minimalist Limerick street posters exist | — | **No pixel-art or isometric Limerick map exists. The niche is open.** |

**Craft references:** [SLYNYRD Pixelblog #41 (isometric)](https://www.slynyrd.com/blog/2022/11/28/pixelblog-41-isometric-pixel-art),
[#14 cityscapes, #51 city builder](https://www.slynyrd.com/pixelblog-catalogue) — the
rulebook for 2:1 lines, cube construction, and top-bright/left-mid/right-dark shading we
will encode in the renderer.

**Honest gap confirmed by research:** no tutorial or tool anywhere covers "real city,
non-grid streets, isometric pixel art". The three observed strategies are (a) eBoy:
abandon geography; (b) 8-Bit Cities: quantize to a grid and accept stair-steps;
(c) Isometric NYC: keep true geometry, let AI absorb irregularity. **We take (b) with a
city-specific rotation that makes Limerick's Georgian grid land exactly on the iso axes,
plus (a)'s landmark liberties.**

### 2.2 Data reality for Limerick (probed live, 2026-07-27)

Overpass counts, bbox 52.645–52.685 N, −8.660–−8.600 E (~4.4 × 4.1 km around the core):

| Metric | Value | Consequence |
|---|---|---|
| Building footprints | **21,935** (21,894 ways + 41 relations) | Coverage effectively complete — render-ready |
| …with `building:levels` or `height` | 3,870 (~18%; ~23% in the tight core) | Heights mostly defaulted |
| `building:levels` distribution (core) | 83% = 2, then 1, 3, 4… one 15 (Riverpoint) | **Default = 2 storeys is empirically correct** |
| `height` tags | ~0 (13 in core) | Ignore |
| Highway ways | 5,517 | Full network present |
| Landmarks (castle, cathedrals, bridges, Thomond Park, Milk Market roof relation, Treaty Stone, People's Park, Hunt Museum, Riverpoint, Colbert) | All present | Anchor table in §7 |

Context: Ireland's buildings were traced manually by the
[OSM Ireland Buildings Project](https://wiki.openstreetmap.org/wiki/Ireland/Buildings)
(started Nov 2019; Limerick was project #7 on
[tasks.openstreetmap.ie](https://tasks.openstreetmap.ie/): **100% mapped, 31% validated**).
The 31% validation means occasional wonky outlines — our discretize stage will
orthogonalize footprints anyway (JOSM "Q" style), which pixel art demands regardless.

**Heights bonus track:** GSI/OPW **open 2 m lidar DSM + DTM tiles cover Limerick city**
(CC-BY 4.0, vintage 2006/2011, EPSG:2157, via
[data.gov.ie](https://data.gov.ie/dataset/open-topographic-lidar-data)). DSM − DTM ≈
per-building height for exactly the city where OSM heights are absent. Optional
enhancement — staleness caveat for post-2011 buildings.

**Terrain:** measured spot elevations across the core span ~2–15 m. Flat. Ignored in v1;
the only "terrain" drawn is the river, quay walls, and bridges.

**Alternatives assessed and rejected:** Microsoft GlobalMLBuildingFootprints covers
Ireland but with no heights (verified `height: -1.0` in the Ireland tiles) and adds nothing
over OSM here; Overture ≈ OSM repackaged for Ireland; Tailte Éireann/OSi footprints are
paid/closed. **OSM is simply the open building map of Ireland.**

### 2.3 Print craft facts that shape the design

- **Integer nearest-neighbour upscaling only**, and deliver a file already at the print
  shop's exact pixel dimensions so nothing downstream resamples. Order notes: *"do not
  resample, do not sharpen, print at 100%"* — print-service resampling is the #1 killer
  of crisp pixels.
- **300 DPI** is the poster norm; 150+ DPI is fine at 1–3 m viewing. Pixel art is flat
  colour, so high DPI is free quality.
- **Pixel size on paper:** dense city panoramas (eBoy prints at A0) use ~0.3–1 mm art
  pixels — texture from across the room, crisp detail up close. Chunky 1.5–3 mm pixels
  suit single sprites, not a whole city. We target **~0.5–0.9 mm** and settle it with an
  A4 test strip at 2–3 candidate scales (gate G2).
- **Colour:** work sRGB, embed the profile, export PNG + TIFF masters. Saturated neon
  palettes dull in CMYK conversion — muted palettes (Apollo, Vinik24 mid-tones) survive
  printing much better. Soft-proof, and order one small test print before the big one.
- **Paper:** smooth bright-white matte (e.g. Hahnemühle Photo Rag 308 giclée) — texture
  disturbs flat fills, gloss glares behind glass. eBoy themselves ship offset on matte
  stock. Fine dither patterns are only a moiré risk on offset presses, not inkjet/giclée.
- **Frames:** IKEA's RIBBA family is discontinued; the replacement **RÖDALM** exists in
  **61×91 cm and 50×70 cm**. The 61×91 frame ships with a mount that windows ~50×70 —
  so one frame supports both "full bleed" and "matted gallery" looks.

---

## 3. Approach decision

### 3.1 Options considered

| Option | Verdict | Why |
|---|---|---|
| **A. Custom pipeline: classified iso cell grid + extruded prisms + custom pixel renderer + hand-made landmark sprites** | **✅ Chosen** | Only path to authentic pixel-art (outlines, palette discipline, per-face shading rules); fully deterministic and city-agnostic; the 8-Bit Cities architecture proves the classify-and-stamp core; effort is real but concentrated in reusable code + ~15 landmark sprites. |
| B. VoxCity → MagicaVoxel/Aerialod render | Demoted to week-one experiment | Beautiful fast, but it's *voxel-render* aesthetics (soft path-traced toy city), not pixel art; little art direction; Aerialod is Windows-only closed freeware. |
| C. OSM2World `--oview` ortho render → downscale + palette quantize | Rejected as core; kept as reference viewer | Downscaled realistic 3D never reads as hand-made pixel art; materials/outline control would mean fighting someone else's renderer. |
| D. Blosm + Blender + pixel-art post addons | Rejected | Most moving parts, heaviest skill stack, still a "3D render pixelated". |
| E. Pure tile-stamping from Kenney CC0 packs | Rejected as final look; used for scaffolding | Loses Limerick's actual fabric — and the Shannon/Abbey River loop around King's Island *is* the composition. Kenney tiles serve as placeholders and geometry reference during development. |
| F. AI image generation (Isometric NYC style) | Rejected | Not reproducible or print-crisp at the pixel level; data ToS issues; QA burden lands exactly on the things we care about (water, trees). Fine for mood boards only. |

### 3.2 The chosen architecture in one paragraph

Rotate Limerick by −32.7° so the Georgian grid aligns with the isometric axes. Rasterize
ground truth (water, quays, roads by class, rail, parks, plazas) onto a ~2.5 m cell grid —
curves become stair-steps, which is the correct pixel-art idiom. Extrude building
footprints into voxel prisms (storeys from `building:levels`, else 2; landmark overrides).
Render back-to-front with a small custom renderer that enforces the classic rules: 2:1
pixel lines, three-face shading (top bright / left mid / right dark), constrained palette,
selective 1 px outlines, procedural facade windows, procedural roofs (gabled along the
long axis for houses, flat for commercial). Stamp hand-crafted sprites for landmarks,
bridges, boats, trees, buses. Composite title, border, legend, attribution; integer-upscale
to exact print pixels.

### 3.3 Week-one morale render (optional but recommended)

Before any renderer code: run **VoxCity** on the Limerick bbox → `.vox` → MagicaVoxel
screenshot. One evening, near-zero code. It (a) validates the data end-to-end, (b) gives
an immediate "wow, that's my city" artifact, (c) calibrates how much the custom pixel
look must beat a free voxel render to be worth it. It is explicitly *not* the product.

---

## 4. Projection & geometry spec

### 4.1 Isometric system

- Classic pixel-art "isometric" = **2:1 dimetric**. World grid axes *u, v* map to screen
  as `u → (+2, +1) px`, `v → (−2, +1) px` (y down); a ground cell is a 4×2 px rhombus.
- All slopes in ground linework are 2:1 stairs — never anti-aliased, never fractional.
- Storey height: 3 px per floor at base scale (tune at G2 against test prints).
- Light convention: sun top-left. Face shading: top = light, left (sun side) = mid,
  right = dark; water gets the light ripple dither, never buildings (SLYNYRD rules).

### 4.2 Rotation — the Limerick trick

O'Connell Street's OSM geometry bears **≈ 32.7° east of north** (computed over its 19
segments; Newtown Pery is a genuine 1769 planned grid — Christopher Colles for Edmund
Sexton Pery). Setting `rotation_deg = -32.7` in city config maps the entire Georgian
core onto the iso axes: O'Connell, Henry, Catherine, and the Georgian cross-streets all
render as perfectly clean pixel lines. At M1 we confirm the production value with a
length-weighted 36-bin bearing histogram over the whole network (OSMnx
`add_edge_bearings` / `plot_orientation` — Boeing's method) rather than one street.

### 4.3 Street schematization

1. Skeletonize: keep motorway→residential + named lanes/quays in the render window;
   drop service alleys below a length threshold.
2. Consolidate intersections (OSMnx), simplify polylines (Douglas-Peucker,
   topology-preserving).
3. In the rotated frame, snap each segment's bearing to the nearest of **8 directions**
   (the two grid axes = iso diagonals; the two 45° world diagonals = screen
   horizontal/vertical — all four render crisply), with endpoint re-solving so junctions
   stay connected. Greedy snap + relaxation is expected to suffice at 2.5 m cells because
   rasterization absorbs residual error as stair-steps (8-Bit Cities precedent).
4. Escape hatches, in order: per-way override (`force_bearing`, `straighten`), and only
   if a whole district misbehaves, borrow ideas from octilinear schematization research
   (Freiburg [LOOM/octi](https://github.com/ad-freiburg/loom), GPL C++, built for
   transit-graph scale;
   ["multilinear metro maps"](https://arxiv.org/abs/1904.03039) generalizes to
   data-detected orientation sets). Full MIP schematization is noted as overkill.
5. **Rivers are exempt.** The Shannon and Abbey River keep their true curves (simplified,
   stair-stepped). The loop around King's Island is the identity of the composition.
   Bridges are placed geometrically but drawn as crafted sprites.

### 4.4 Resolution budget (the honest arithmetic)

With cell size *g* metres and upscale factor *k* (art px → print px at 300 DPI):
`metres per horizontal px = √2·g/4`, `metres per vertical px = √2·g/2` (vertical screen
distance compresses ground 2× — an isometric map shows a *deeper-than-wide* ground
rectangle).

Shortlisted configs for **61×91 cm landscape (10800×7200 print px @300 DPI)**:

| Config | Art canvas | Pixel on paper | Visible ground (W×D) | 8 m house |
|---|---|---|---|---|
| g=2.5 m, k=6 | 1800×1200 px | 0.51 mm | ~1.59 × 2.12 km | ~13 px wide |
| **g=3.0 m, k=6** ★ | 1800×1200 px | 0.51 mm | ~1.91 × 2.55 km | ~11 px wide |
| g=2.5 m, k=8 | 1350×900 px | 0.68 mm | ~1.19 × 1.59 km | ~13 px |

★ = provisional recommendation: the only config whose ground window fits the full
wishlist extent (Thomond Park → Colbert Station, both banks) with margin. If G1
composition studies favour a tighter core crop, drop to g=2.5 for chunkier buildings.
Decided empirically at gates G1/G2 with A4 test strips — not in this document.

### 4.5 Coverage recommendation

Fetch bbox 52.645–52.685 N, −8.660–−8.600 E. Render window (post-rotation crop), aimed
to include: full King's Island + Abbey River loop; Newtown Pery grid to People's Park &
Colbert Station; both Shannon banks (Clancy/O'Callaghan strands, Treaty Stone); the three
main bridges (Thomond, Sarsfield, Shannon); Thomond Park at the NW edge; Riverpoint and
the docks to the SW. University of Limerick is 5 km east — out of scope (option: tiny
inset badge, decide at M5).

---

## 5. Pipeline architecture

Seven deterministic stages, each cached to disk, each re-runnable independently. One CLI:

```
pixelmap fetch|extract|schematize|discretize|decorate|render|compose limerick
pixelmap build limerick [--preview|--print] [--stage <name>]
pixelmap edit limerick        # launches the override editor (§8)
```

| Stage | In → Out | Contents |
|---|---|---|
| 0 `fetch` | city.toml → `cache/raw/` | Overpass (or Geofabrik `.pbf` + pyrosm for reproducibility) pulls: buildings, highways, water, landuse, leisure, rail, named POIs. Raw responses cached & committed as a data snapshot so the print is regenerable even if OSM changes. |
| 1 `extract` | raw → `layers.gpkg` | Normalize to typed layers in EPSG:2157 (Irish Transverse Mercator): water polys, road centrelines w/ class & width, rail, green/plaza polys, building footprints w/ storeys (levels → int, default 2), POI anchors. |
| 2 `schematize` | layers → `schematic.gpkg` | Rotate by `rotation_deg`; simplify; snap road bearings (§4.3); orthogonalize building footprints; widen roads to class widths; resolve overlaps (bridge decks over water, etc.). Consumes `overrides.yaml`. |
| 3 `discretize` | schematic → `scene.json` | Rasterize ground layers to the cell grid with painter's priority (water < green < plaza < road < rail); voxelize buildings to prisms (footprint cells × storeys, roof type inferred); emit the **scene graph**: `{grid, prisms[], props[], landmarks[]}` — every element carries its source OSM id. Consumes overrides. |
| 4 `decorate` | scene → scene′ | Procedural charm, seeded RNG: street trees along configured ways, cars/buses on road cells, boats & swans on river cells, chimneys on Georgian terraces, facade window patterns, quay walls. Landmark sprite placements from config. Consumes overrides. |
| 5 `render` | scene′ → `art.png` | The custom renderer: back-to-front painter's order; ground tile stamps; prism faces with palette ramps; selective outlines; dithering only where style config allows (water, parks). Pure function of scene + style config. |
| 6 `compose` | art.png → `print/` | Border, title/subtitle typography, legend, attribution line, optional inset; integer ×k upscale; emit `screen.png`, `print.png` (exact print pixels, 300 DPI metadata, sRGB embedded) + `print.tif`. |

**Determinism:** one `seed` in city config; no wall-clock anywhere; golden-image tests on
renderer primitives (a cube, a road junction, a gable roof) and a full small-scene
snapshot test.

**Repo layout (future — nothing implemented yet):**

```
pixelmap/
  PLAN.md                     ← this document
  pixelmap/                   ← the city-agnostic package (fetch…compose, renderer, editor)
  cities/limerick/
    city.toml                 ← bbox, rotation_deg, grid, palette ref, print size, seed
    palette.toml              ← the ~40-colour palette + role mapping
    landmarks.toml            ← anchors, sprite refs, footprint OSM ids, scale liberties
    overrides.yaml            ← every manual fix ever made, replayable
    sprites/                  ← .vox / .png landmark & prop art
    cache/                    ← fetched data snapshot (committed)
  tests/                      ← golden images, stage unit tests
```

Python 3.12+, uv-managed, dependencies deliberately boring: osmnx/pyrosm, shapely,
pyproj, rasterio (or numpy rasterization), numpy, Pillow, FastAPI (editor only). The
renderer is our code — that's where the art lives, and it's plain numpy.

---

## 6. Visual style spec

- **Palette:** one global constrained palette, ~32–48 colours, stored as config. Starting
  point: [Apollo (46)](https://lospec.com/palette-list/apollo) or a
  [Resurrect 64](https://lospec.com/palette-list/resurrect-64) subset — both are
  ramp-organized and CMYK-survivable; compare against
  [AAP-64](https://lospec.com/palette-list/aap-64),
  [Endesga 32](https://lospec.com/palette-list/endesga-32),
  [Vinik24](https://lospec.com/palette-list/vinik24) at gate G2. Colour roles: limestone
  grey (Limerick is the limestone city), Georgian red brick, slate roofs, painted
  shopfront accents on the main streets (seeded variation), steely Shannon blue-green,
  park greens, warm sandstone for the castle/cathedrals. One deliberate Munster-red
  accent budget (Thomond Park seats, the odd door) — tasteful, not livery.
- **Buildings:** procedural facades — window/door pixel patterns keyed to storeys and
  frontage length; Georgian terraces get fanlight doors and sash-window rhythm; gable
  roofs along the footprint's long axis for ≤3-storey residential, flat/parapet for
  commercial; chimney props on terrace party walls.
- **Water:** flat base + sparse ripple dither + 1 px quay-wall drop with highlight;
  bridges cast simple contact shadows. Weir line above Curraghgour if it survives
  composition.
- **Outlines:** selective — silhouette edges of prisms and landmarks get 1 px dark line;
  ground linework relies on colour contrast (full outlining at this density turns to mud;
  SLYNYRD guidance).
- **Typography:** title `LIMERICK` + subtitle `LUIMNEACH` + coordinates line. Fonts
  (licence-verified): [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P)
  (OFL) for title; [Silkscreen](https://fonts.google.com/specimen/Silkscreen) (OFL) or
  [m5x7](https://managore.itch.io/m5x7) (CC0) for small labels. Rendered at native pixel
  size on the art canvas *before* upscale so letter pixels = art pixels.
- **Border/legend:** thin pixel border; attribution line set in the border (§13); no
  street labels on v1 (labels fight the art; revisit at G3).
- **Variants later (cheap once pipeline exists):** dusk with lit windows, match-day
  Thomond crowds, Christmas. Each is a palette + decorate-config swap.

---

## 7. Landmarks — the charm layer

Generated buildings make it *a* city; these make it *Limerick*. Confirmed present in OSM
with probe anchor coordinates (exact polygons resolved by OSM id at build time — some
probe hits are the eponymous bike-share stations, close enough for planning):

**Tier 1 (must have):**

| Landmark | Anchor (lat, lon) | Notes |
|---|---|---|
| King John's Castle | 52.6695, −8.6249 | The hero sprite. Towers + curtain wall, oversize licence permitted |
| Thomond Bridge | 52.6701, −8.6277 | Crafted arches |
| Sarsfield Bridge | 52.6651, −8.6297 | + Shannon Rowing Club clubhouse |
| Shannon Bridge | ~52.662, −8.633 | The modern arc, confirm id at M1 |
| St Mary's Cathedral | 52.6674, −8.6237 | Tower + battlements |
| St John's Cathedral | 52.6629, −8.6179 | Tallest spire in Ireland — vertical exclamation mark of the whole piece |
| The Treaty Stone | 52.6696, −8.6281 | Tiny but obligatory; plinth on Clancy Strand |
| Thomond Park | 52.6743, −8.6428 | Stands + pitch; Munster red seats |
| Milk Market | 52.6636, −8.6220 | The white canopy roof (mapped as a roof relation!) |
| Colbert Station | 52.6591, −8.6240 | Victorian frontage + platform canopies |

**Tier 2 (wanted):** Hunt Museum (52.6663, −8.6244), People's Park bandstand + Carnegie
building (52.6581, −8.6280), Riverpoint towers (52.6613, −8.6328), Cleeves factory
chimney (O'Callaghan Strand — confirm id at M1), Mathew Bridge, Abbey/O'Dwyer bridges,
St Munchin's, the boathouses on the strands, Curraghgour boat club.

**Tier 3 (props, reusable across cities):** rowing eights & cox on the Shannon, swans,
gulls, Bus Éireann single-deckers, cars, trees (3 species), benches, lamp posts, GAA/rugby
crowd dots.

**Authoring workflow (no Photoshop):** each landmark is a small voxel model (fits ~64³)
in MagicaVoxel — free, and closer to LEGO than to Photoshop — *or* generated
parametrically in code (a castle is cylinders + battlement loops). Realistic split:
Claude drafts parametric/voxel models from photos; the user art-directs with feedback;
MagicaVoxel available for hand-tweaking by whoever enjoys it. Models live in
`cities/limerick/sprites/` and are rendered by the same pixel renderer as everything else,
so lighting/palette stay coherent. Budget: 1–2 evenings per Tier-1 landmark.

---

## 8. The editor — manual fixes without Photoshop

Purpose-built local web tool (`pixelmap edit limerick`), because some judgment calls
(a wrong roof, an ugly junction, a boat that should move 3 cells left) are faster to click
than to code.

- **Views:** rendered preview (zoom/pan) side-by-side with a plain 2D OSM map, linked
  cursors; layer toggles (ground / prisms / props / landmarks); "overridden items"
  highlight.
- **Click any pixel → resolves to the scene element → its source OSM id.** Edit
  operations: building storeys ±, roof style, colour class, delete/merge; road force
  direction / width / delete stub; prop place/remove/rotate from the sprite library;
  landmark nudge/rotate/swap; ground-cell class paint (water/green/plaza).
- **Every edit writes a line to `overrides.yaml`** — human-readable, git-diffable,
  keyed by OSM id or cell coordinate. Example shapes:

  ```yaml
  - {match: {osm: "way/123456"}, set: {levels: 4, roof: flat}}
  - {match: {osm: "way/222333"}, action: delete}          # scruffy shed
  - {match: {way: "O'Connell Street"}, set: {bearing: axis_u}}
  - {prop: rowing_eight, at: [52.6668, -8.6262], heading: 210}
  ```

- Re-render button does an incremental preview (dirty-region re-render). The pipeline
  replays overrides on every build — so a fresh OSM fetch, a palette change, or a scale
  change never loses manual work. **This is the core Photoshop-avoidance principle: the
  source of truth is data + config, never the bitmap.**
- Build order: the editor is M6 — *after* the pipeline proves itself, because overrides
  can be hand-written in YAML from day one; the editor is ergonomics, not architecture.

---

## 9. Milestones & gates

Effort in evenings (~2–3 h). Claude does the heavy code lifting in future sessions; the
user's irreplaceable role is art direction at the gates.

| # | Milestone | Contents | Est. |
|---|---|---|---|
| M0 | Decisions | Close the open questions in §14 | ½ |
| M1 | Data + grey-box | fetch/extract stages; bearing histogram → lock rotation; grey-box iso render (unstyled masses) at 2 configs; composition studies both orientations; **optional VoxCity morale render** | 2–3 |
| **G1** | *Gate: composition* — window, rotation, g/k config locked from grey-box prints | | |
| M2 | Styled ground | schematize + discretize + renderer core: water/quays/roads/parks/rail, palette v1, A4 test strip ordered | 4–6 |
| **G2** | *Gate: the look* — does the ground read as art? palette + pixel-size locked (test strip in hand) | | |
| M3 | Buildings | prisms, roofs, facades, orthogonalization, height defaults | 3–5 |
| M4 | Landmarks | Tier 1 sprites (parametric/voxel workflow), placed | 8–15, spread |
| **G3** | *Gate: is it Limerick?* — show someone who knows the city; they should grin and point | | |
| M5 | Charm + type | decorate stage (trees/boats/traffic/swans), title, border, legend | 2–3 |
| M6 | Editor | FastAPI + canvas overrides editor; cleanup pass over the whole map | 4–6 |
| M7 | Print | soft-proof, final A4 strip, order 61×91 giclée, frame | 2 + shop time |

Total ≈ 25–40 evenings at hobby pace (1–3 months). The dominant cost is M4 — exactly the
part that makes it art rather than a render, per every piece of prior art studied.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Generated output looks sterile, not charming | Gates G2/G3 fail cheap and early; landmark density + decoration pass + palette iteration are the known levers (eBoy/Isometric NYC lesson); worst case the piece leans harder on hand-crafted landmarks over generated fabric |
| Street snapping produces ugly junctions in the medieval quarter | Rasterization hides most; per-way overrides; the quarter is small — hand-tune worst 10 junctions via editor |
| Scale wrong for print (pixels too fine/coarse) | A4 test strips at candidate scales at G2, before any large spend |
| OSM footprint noise (31% validated) amplified by outlines | Orthogonalize footprints in schematize; selective outlining only |
| Renderer performance (~1–2 M voxel faces) | Plain numpy painter's algorithm is comfortably enough at 1800×1200; chunked re-render for editor |
| Print service ruins the file | Exact-pixel delivery + "no resample/sharpen/100%" notes + test print first |
| CMYK dulls the palette | Muted ramp palettes chosen for survivability; soft-proof; test strip |
| Scope creep (labels! night mode! UL inset!) | v1 scope frozen at G1; variants are post-v1 config swaps |
| MagicaVoxel is still too "arty" for the user | Parametric models drafted by Claude from photos; user only gives feedback |

## 11. Other cities later

Everything Limerick-specific is data: `city.toml` (bbox, rotation from the bearing
histogram, palette accents, title), `landmarks.toml` + sprites, `overrides.yaml`. The
pipeline never branches on city name. A second city costs: one config, one bearing check,
one palette accent pass, and its own Tier-1 landmark sprites (the real cost — days, not
weeks). Galway, Cork, Dublin (Liffey + Georgian grids) are natural candidates; so are
gift-size 30×40 cm prints of towns.

## 12. Print production checklist (v1 target)

1. Master: `print.png` + `print.tif`, exactly 10800×7200 px, sRGB embedded, 300 DPI
   metadata, integer-upscaled ×6 from 1800×1200 art canvas.
2. Giclée pigment print, smooth matte 240–310 gsm (Photo Rag 308 class), 61×91 cm,
   ~3 mm bleed or designed border per shop spec.
3. Order notes: *print at 100%, no resampling, no sharpening, no auto-enhance.*
4. A4 test strip of a detailed crop first; check palette, black density, pixel edges.
5. Frame: IKEA RÖDALM 61×91 (or 50×70 via its mount); no glass upgrade needed for matte.

## 13. Licensing & attribution

- **OSM data: ODbL** → the print carries "Map data © OpenStreetMap contributors" in the
  border (required if ever sold/shared; good manners regardless).
- If lidar heights used: add "Contains GSI/OPW data © Government of Ireland, CC-BY 4.0".
- Fonts: OFL (Press Start 2P, Silkscreen) / CC0 (m5x7, monogram) — all print-safe.
- Kenney assets (CC0) usable even commercially; ours are placeholders anyway.
- Our own code/sprites: user's choice; MIT suggested if the repo ever goes public.
- Avoid: copying prettymaps code (AGPL), F4map screenshots, Google 3D Tiles derivatives.

## 14. Open decisions (user input wanted, recommendations attached)

1. **Print size/orientation** — rec: 61×91 cm landscape (RÖDALM-compatible; landscape
   suits the 2:1 projection's deep ground window). Decide at G1 with grey-box studies.
2. **Coverage window** — rec: §4.5 extent (Thomond Park ↔ Colbert, both banks, full
   King's Island); UL omitted (optional inset badge).
3. **Style north star** — rec: crisp chunky 2:1 with selective outlines, eBoy-leaning
   density; alternative is a cleaner minimal look. A/B at G2.
4. **Mood** — rec: daylight for v1; dusk/lit-windows as a later variant.
5. **Munster-red accent easter eggs** — rec: yes, sparingly.
6. **Project name** — working name `pixelmap`; candidates: `isopolis`, `shannonpixel`.
7. **Frame route** — RÖDALM vs. custom framing budget.

---

## Appendix — key references

*Prior art:* [eBoy](https://www.eboy.com/) · [8-Bit Cities](https://8bitnyc.com/) ·
[prettymaps](https://github.com/marceloprates/prettymaps) ·
[OSM2World](https://osm2world.org/) · [VoxCity](https://github.com/kunifujiwara/VoxCity) ·
[arnis](https://github.com/louis-e/arnis) ·
[isocity](https://github.com/victorqribeiro/isocity) ·
[FileToVox](https://github.com/Zarbuz/FileToVox) ·
[Aerialod city workflow](http://www.statsmapsnpix.com/2019/11/amazing-3d-rendering-with-aerialod.html) ·
[Isometric NYC writeup](https://rogerwong.me/2026/02/isometric-nyc) ·
[osm2pov/osm-isometric-3d](https://github.com/bitsteller/osm-isometric-3d) ·
[pixijs-isotoon](https://github.com/FaisalBinAhmed/pixijs-isotoon)

*Craft:* [SLYNYRD Pixelblog catalogue](https://www.slynyrd.com/pixelblog-catalogue)
(#41 isometric, #14 cityscapes, #51 city builder, #1 palettes) ·
[Pixnote isometric guide](https://pixnote.net/en/learn/isometric/) ·
[Pixel Joint printing thread](http://pixeljoint.com/forum/forum_posts.asp?TID=8673)

*Assets:* [Kenney isometric packs](https://kenney.nl/assets/tag:isometric) (CC0) ·
Lospec palettes: [Apollo](https://lospec.com/palette-list/apollo) ·
[Resurrect 64](https://lospec.com/palette-list/resurrect-64) ·
[AAP-64](https://lospec.com/palette-list/aap-64) ·
[Endesga 32](https://lospec.com/palette-list/endesga-32) ·
[Vinik24](https://lospec.com/palette-list/vinik24) · Fonts:
[Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P) ·
[Silkscreen](https://fonts.google.com/specimen/Silkscreen) ·
[m5x7](https://managore.itch.io/m5x7) · [monogram](https://datagoblin.itch.io/monogram)

*Data & algorithms:* [OSM Ireland Buildings Project](https://wiki.openstreetmap.org/wiki/Ireland/Buildings) ·
[tasks.openstreetmap.ie](https://tasks.openstreetmap.ie/) ·
[OSMnx](https://osmnx.readthedocs.io/) ·
[Boeing, street network orientation](https://geoffboeing.com/2019/09/urban-street-network-orientation/) ·
[pyrosm](https://pyrosm.readthedocs.io/) ·
[Geofabrik Ireland extract](https://download.geofabrik.de/europe/ireland-and-northern-ireland.html) ·
[EPSG:2157 ITM](https://epsg.io/2157) ·
[GSI/OPW open lidar](https://data.gov.ie/dataset/open-topographic-lidar-data) (CC-BY 4.0) ·
[LOOM/octi octilinear schematization](https://github.com/ad-freiburg/loom) ·
[Multilinear metro maps](https://arxiv.org/abs/1904.03039) ·
[Microsoft GlobalMLBuildingFootprints](https://github.com/microsoft/GlobalMLBuildingFootprints) ·
[Overture buildings](https://docs.overturemaps.org/guides/buildings/) ·
[Newtown Pery](https://en.wikipedia.org/wiki/Newtown_Pery,_Limerick)

*Print:* [theprintspace giclée paper guide](https://www.theprintspace.co.uk/how-to-choose-the-right-giclee-paper-for-your-art-type/) ·
[Poster Print Shop DPI guide](https://posterprintshop.com/guide/how-many-dpi-for-large-format-printing/) ·
[IKEA frame size guide](https://www.ikea.com/gb/en/rooms/living-room/how-to/finding-the-right-picture-frame-pubb930a400/) ·
[RÖDALM 61×91](https://www.ikea.com/gb/en/p/roedalm-frame-black-30548932/)
