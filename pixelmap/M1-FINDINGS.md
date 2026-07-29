# M1 — Data and grey-box · findings

*Run 2026-07-27. Everything below is measured from real data, not estimated.*

M1's job was to turn the plan's assumptions into locked numbers and put a real
picture of Limerick on screen cheaply enough that a wrong turn costs an evening.
All of it is now measured. **Gate G1 is ready for your call.**

---

## 1. What was built

A working pipeline skeleton — stages 0 and 1 complete, plus the analysis and
grey-box tooling that the composition gate needs:

```
pixelmap fetch limerick                    # stage 0: OSM -> cache/raw/*.json.gz
pixelmap bearings limerick                 # street orientation analysis + rose figures
pixelmap greybox limerick --fit            # locked-frame composition render
pixelmap greybox limerick --study          # six-variant framing comparison
pixelmap greybox limerick --orientations   # all four quarter turns
```

| Module | Role |
|---|---|
| `fetch.py` | Overpass with mirror rotation + exponential backoff; per-layer caching (gzipped, committed) |
| `extract.py` | Overpass JSON → shapely geometry in EPSG:2157, multipolygon ring assembly, storey parsing |
| `bearings.py` | Boeing-style length-weighted bearing rose; 4th-harmonic grid fit; snap-cost optimiser |
| `iso.py` | The 2:1 projection contract, plus the frame solver that fits landmarks to canvas |
| `greybox.py` | Unstyled painter's-order renderer + landmark annotation |
| `plots.py` | Rose diagrams and contact sheets |

Overpass was heavily rate-limited during the run (429s, 504s, dispatcher
errors). The mirror rotation handled every failure without intervention — worth
keeping.

## 2. Data reality — confirmed, and better than the plan assumed

Fetched bbox 52.645–52.685 N, −8.660–−8.600 E (~4.4 × 4.1 km), 2.2 MB gzipped:

| Layer | Count |
|---|---|
| Buildings (after multipolygon assembly) | **21,949** |
| Roads | 4,110 |
| Water bodies / waterways | 70 / 12 |
| Green areas | 792 |
| Urban landuse | 517 |
| Rail | 90 |
| POIs | 148 |

Storey tags behave exactly as the plan predicted, so **`default_levels = 2`
stands**. The tallest tagged building in frame is 15 levels (Riverpoint).

## 3. Rotation — LOCKED at −32.75°, then turned +90°

The plan's provisional −32.7°, estimated from O'Connell Street alone, is
confirmed by the full analysis. Measured over the 179 streets (14.5 km) of the
Georgian core:

- **Grid angle 31.61°, strength 0.657, orderliness 0.519** — a genuine planned grid.
- **Whole fetch area: strength 0.030, orderliness 0.018** — essentially *no*
  dominant grid. Limerick outside Newtown Pery is organic, which confirms the
  plan's snap-everything-else approach is doing real work, not decoration.

Optimising directly for the metric we actually pay — the length-weighted mean
bend needed to snap segments onto a clean direction — gives **−32.75°**:

| Rotation | Core crisp share | Core mean bend | City crisp | City bend |
|---|---|---|---|---|
| none (0°) | 12.0% | 11.95° | 17.5% | 12.15° |
| **−32.75° (locked)** | **58.1%** | **6.18°** | 26.2% | 10.61° |
| −31.61° (4-fold fit) | 56.8% | 6.37° | 27.1% | 10.49° |
| −25.90° (city optimum) | 19.4% | 8.77° | 27.9% | 10.19° |

Rotation takes the Georgian core from 12% to 58% of street length already
rendering as crisp pixel lines, and roughly halves the bending. The city-wide
"optimum" is a shallow noise minimum — it buys 1.7 points city-wide while
destroying the core, so the core wins outright.

**One correction to the plan's own maths:** it described snapping to 8 directions
but measured alignment against 4. In 2:1 isometric, eight world directions render
cleanly — the two grid axes *and* their diagonals, which project to the screen
horizontal and vertical. The alignment measure now folds at 45°, not 90°. This
also means **all four quarter turns bend the streets identically**, so
orientation is a free compositional choice.

## 4. Framing — LOCKED

A solver now computes the tightest crop that still fits the tier-1 landmarks
(`iso.solve_frame`). The decisive finding:

> **Thomond Park is the single most expensive landmark in the composition.**
> It sits 1.5 km north-west of everything else. Including it forces cell size
> from 1.81 m to 2.77 m, adds 4,100 buildings, and fills half the canvas with
> suburb.

Locked configuration:

| Parameter | Value |
|---|---|
| Rotation | **+57.25°** (−32.75 core fit, turned +90 for composition) |
| Cell size | **1.812 m** (a cell is a 4 × 2 px rhombus) |
| Centre | **52.664928, −8.624746** |
| Ground shown | **1153 × 1537 m**, 4,992 buildings |
| Art canvas | 1800 × 1200 px → 10800 × 7200 px at ×6 |
| Pixel on paper | 0.51 mm · an 8 m house frontage is 18 px wide |

All tier-1 landmarks except Thomond Park are on canvas.

**Why +90° of the four turns:** water at the top reads as distance in isometric,
so the Shannon becomes the horizon, the dense Georgian grid becomes foreground,
and King John's Castle lands top-centre framed inside the river bend. At +270°
(the mirror) the castle falls out of the bottom edge; at 0°/180° the landmark
spread runs corner-to-corner and pushes the castle to the very edge. See
`cities/limerick/gates/g1-orientation-study.png`.

## 5. Building height — a real bug found and fixed

The plan specified 3 px per storey. At the locked 1.81 m cell size, **true
isometric height is 3.53 px per storey**, so the planned value was *shorter* than
correct and buildings rendered as flat slabs.

Set to **4.5 px** (27% exaggeration): terraces read as rows of houses rather than
kerbs, without the toy-skyscraper look of 6 px, which starts to occlude the
street network. Evidence: `gates/g1-height-study.png`. Revisit at M3 once roofs
and facades exist.

## 6. Gate G1 — what needs your call

Everything is locked to a defensible default and rendering; these are the
judgement calls the data cannot make.

1. **Thomond Park — in or out?** *(the big one)* Recommendation: **out**, as
   locked — the 23% detail gain across the whole core is worth more than one
   stadium. Options if you want it: bring it back as a small inset badge (M5),
   or accept 2.77 m cells and a suburb-heavy frame.
2. **Orientation.** Recommendation: **+90° as locked**. Compare
   `g1-orientation-study.png` — 270° is the credible alternative if you prefer
   the river in the foreground.
3. **Crop tightness.** The locked frame keeps Colbert and St John's near the
   lower edge. Tightening further on the castle and Georgian core would gain
   detail but lose them.
4. **Print size.** Still 61 × 91 cm landscape. Nothing found at M1 argues
   against it; the isometric view's deeper-than-wide ground rectangle suits
   landscape well.

## 6b. M1b — reframed to the river brief

After reviewing G1 the brief changed: **Shannon low and horizontal, old city
above it, west on the right-hand side, and Pixorama-scale detail.** Re-measuring
against that:

| Feature | Axis | Reading |
|---|---|---|
| Shannon, in-frame reach | **51.1°** | measured by PCA over the water mass actually in shot |
| Dock Road | **58.7°** | only 7.6° off the river — they can be level together |
| Georgian grid | 31.6° | ~19.5° off the river |

Two data corrections worth recording. Overpass returns **whole** river polygons,
so the water layer spans 18 km and its centroid sits far outside any frame —
the river's vertical placement is now anchored on a named mid-channel point at
Sarsfield Bridge instead. And the earlier 110.8° figure was the estuary reach
well west of the city, not the reach in frame.

**Locked for M1b:** rotation **192.25°** (screen-right = WSW, 237°), which puts
the river 6.1° and Dock Road 1.4° off horizontal — both effectively level, with
west to the right exactly as briefed. Cell size **0.6 m**, giving an 8 m frontage
53 px wide and a 2-storey house 27 px tall, on an 8250 × 2594 px canvas
(3.2:1 panorama) covering 1750 × 1100 m.

### The trade-off this forces

Crisp directions in 2:1 isometric repeat every 45°, alternating between two
families:

- **even multiples** of 45° off the grid fit — footprints land on the iso
  diagonals, so buildings show two walls: the classic isometric silhouette;
- **odd multiples** — footprints land on the screen axes, so buildings read
  flatter and more plan-like.

Because the river runs ~19.5° off the Georgian grid, **a level river forces the
odd family.** Bend cost is untouched (still 6.18°) — only the silhouettes change.
Compare `gates/g1b-river-level.png` against `gates/g1b-iso-preserved.png`.

**The way to get both** is to straighten the Shannon in the schematize stage and
return to the 237.25° family. The plan already sanctions straightening geometry,
and the river is the one feature where a liberty buys the whole composition. That
is now the most valuable single item in M2.

### Still open at this frame

- Thomond Bridge and the Treaty Stone fall just off the lower-left edge; the
  castle and King's Island are in. Widening to catch them pulls in more of the
  north bank, which is dull.
- The Shannon narrows toward the right of frame — that is real geometry (the
  channel past the docks), not a data gap, but straightening would even it out.
- 3.2:1 is a panorama, not a standard frame size. The `[print]` block is
  deliberately non-binding until the composition settles.

## 6c. M2 — snapping, and a correction to sections 3 and 6b

### Correction: the rotation sign was inverted

Building the snapping forced a re-derivation of the projection, which exposed a
sign error in the M1 analysis. The camera rotates world coordinates by
`rotation`, so a direction's bearing in the camera's frame is
**`bearing - rotation`**. The alignment metric used `bearing + rotation`, so every
rotation reported in sections 3 and 6b was the negation of the one that actually
aligns the grid.

Verified by measuring rendered screen angles directly, rather than by algebra —
the share of core street length landing on a crisp screen slope:

| Rotation | Crisp share |
|---|---|
| −32.75° (claimed "locked" at M1) | **14.4%** |
| 57.25° (M1's frame) | 13.7% |
| 192.25° (M1b's frame) | 11.6% |
| 31.61° / 29.5° (corrected family) | **62–63%** |

So the Georgian grid was never actually aligned in any earlier render; the 58.1%
crisp figure in section 3 is wrong. The bend cost of 6.18° was right — that
metric folds at 45° and is sign-symmetric — which is why the error survived.
`rotated_bearing()` now exists so the convention lives in exactly one place.

### Rotation, re-derived

The bend-optimal family is **32.75 + 45k**, and the sub-family that also puts
footprints on the 2:1 diagonals rather than the screen axes is **32.75 + 90k**.
Locked at **212.75°** — the member with west on the right-hand side, preserving
the M1b composition.

This also dissolves the M1b trade-off. The two families are no longer a choice
between a level river and isometric buildings, because the river is now bent
onto the grid rather than the grid onto the river.

### The schematize stage

Every layer is pushed onto the eight crisp directions, with a different
treatment per geometry type — each one guarding against a specific failure:

- **Streets** relax as a connected network. Snapping ways independently pulls
  junctions apart, so segments declare a direction and node positions are
  averaged until the network agrees, with a weak anchor to original positions
  so the network cannot drift off its landmarks.
- **Buildings** rotate bodily onto the grid. Snapping edge by edge shreds a
  footprint; a rigid rotation keeps right angles right and terraces intact.
- **Water and greens** are simplified hard, then relaxed with an anchor. Three
  guards proved necessary: simplify first or a surveyed wiggle becomes a
  staircase; cap edge length or a single multi-kilometre edge (the Shannon is
  one polygon spanning 18 km) swings its far end hundreds of metres when
  rotated up to 22.5°; anchor to the original position or the ring grows
  spikes. All three failures were observed before being fixed.

**Result: road length on a crisp direction goes from 11.5% to 70.2%.** The
remainder is mostly short service stubs whose snapped direction fights a
neighbour's.

## 7. Known gaps, carried into M2

- Grey-box projects geometry straight to canvas pixels; the **cell-grid
  discretization (stage 3) is not built yet** and is where stair-stepping,
  road snapping and quantization actually happen.
- **No schematization yet** — streets are still drawn at their true bearings.
  The 6.18° mean bend is the budget M2/M3 has to spend.
- Painter's ordering sorts buildings by centroid depth; fine for grey-box,
  needs the proper cell-based order once buildings carry detail.
- Building footprints are not yet orthogonalized (OSM Limerick is 100% mapped
  but only 31% validated, so some outlines are visibly unsquare).
- The Milk Market's roof relation, bridges over water, and the quay walls all
  need explicit handling once styling starts.

---

## 8. Frame scale — coverage and detail split apart (2026-07-29)

The frame was covering the Georgian core and the bridges but stopping short of
the docks, Colbert and, at the bottom edge, King John's Castle. Widening it
without losing detail meant separating two things that had been tangled
together in `[frame]`:

| Knob | Changes | Leaves alone |
|---|---|---|
| `scale` | how much ground is in shot | pixels per metre, canvas aspect |
| `cell_m` | pixels per metre | what is in shot |

`camera_for(city, scale=…)` multiplies both ground extents, so the canvas grows
around the same subject at the same density and the aspect stays at 3.08:1.

### Choosing the value

Each subject implies a minimum scale — the factor at which it first lands on
canvas. Measured against the locked frame:

| Subject | Needs scale |
|---|---|
| Limerick Docks landuse, full western tail | 1.90 |
| Ted Russell Dock (the wet dock itself) | 1.52 |
| People's Park | 1.17 |
| Colbert Station | 1.09 |
| Thomond Bridge | 0.97 |
| King John's Castle | 0.86 |

**Locked at 1.55** — the wet dock with a little air around it, and everything
else comfortably inside. 1.90 was rejected on data, not taste: the ground
rectangle at that scale runs past the fetched bbox at lon −8.6563 (fetch west
edge −8.660 is met, but the south edge 52.6543 is not), so the western tail of
the docks landuse would render as empty land. Taking it in means re-fetching a
wider bbox, and it is 700 m of yard and hardstanding.

| Scale | Ground | Canvas at 0.3 m/cell | Buildings |
|---|---|---|---|
| 1.00 | 1850 × 1200 m | 17442 × 5656 px, 99 Mpx | 4,699 |
| 1.55 | 2868 × 1860 m | 27036 × 8768 px, 237 Mpx | 9,843 |

Render cost at 1.55: **70 s wall, 1.4 GB peak RSS, 16 MB PNG**. Not the
constraint anyone expected it to be.

### Two fixes the enlargement exposed

- **The off-canvas cull was measured in pixels**, so a coarse preview quietly
  dragged in thousands of buildings that could never touch the canvas — 15,337
  at 1.2 m/cell against 9,600 at 0.3 m. Restated in ground metres and storeys
  (`OFF_CANVAS_REACH_M`, `OFF_CANVAS_STOREYS`); both cell sizes now select the
  same 9,843 buildings, of which 7,813 sit strictly on canvas.
- **The reported frontage size was wrong**, quoting `8 / cell × CELL_W`. A wall
  runs diagonally across the ground rhombus, not along it, so the divisor is
  `hypot(CELL_W, CELL_H)`. An 8 m frontage at 0.3 m/cell is 60 px, not 107.
  Only the printed figure was affected; nothing rendered differently.
