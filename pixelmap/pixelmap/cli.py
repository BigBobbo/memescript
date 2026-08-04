"""pixelmap command line.

    pixelmap fetch limerick
    pixelmap bearings limerick
    pixelmap greybox limerick [--study]
    pixelmap frame limerick [--cell 1.4] [--annotate]
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

from .config import City, load_city


def _apply_heights(city: City, layers) -> None:
    """Fold measured LiDAR heights in, if the stage has been run.

    Kept out of `extract` so the OSM snapshot and the height survey stay
    separable: re-running one must not invalidate the other. Applying is
    idempotent — it recomputes from the heights file rather than accumulating.
    """
    from .extract import apply_lidar_heights
    from .iso import STOREY_M
    from .lidar import load_survey

    survey = load_survey(city.cache)
    if not survey:
        return
    tally = apply_lidar_heights(layers, survey, storey_m=STOREY_M)
    print(f"  heights: {tally['lidar']} from LiDAR, {tally['tag']} tagged, "
          f"{tally['default']} default")


def _extract_cached(city: City, *, force: bool = False):
    """Extract layers, caching the projected result between runs."""
    from .extract import extract

    cache_path = city.cache / "layers.pickle"
    raw_dir = city.cache / "raw"
    # The pickle holds the OSM extract as fetched; heights are folded in after
    # loading, so a re-run of the survey needs no cache invalidation.
    if cache_path.exists() and not force:
        newest_raw = max((p.stat().st_mtime for p in raw_dir.glob("*.json*")), default=0)
        if cache_path.stat().st_mtime >= newest_raw:
            with cache_path.open("rb") as fh:
                layers = pickle.load(fh)
            print(f"  layers: cached ({layers.summary()})")
            _apply_heights(city, layers)
            return layers

    layers = extract(raw_dir, city.crs, bbox=city.bbox)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("wb") as fh:
        pickle.dump(layers, fh, protocol=pickle.HIGHEST_PROTOCOL)
    _apply_heights(city, layers)
    return layers


def cmd_fetch(args) -> int:
    from .fetch import fetch_city

    city = load_city(args.city)
    print(f"fetch: {city.config['city']['name']}  bbox={city.bbox}")
    fetch_city(city.config, city.cache, force=args.force)
    return 0


def cmd_lidar(args) -> int:
    from .lidar import (HeightModel, Survey, calibrate, discover_tiles,
                        download_tiles, measure, save_heights)

    city = load_city(args.city)
    if "lidar" not in city.config:
        print(f"error: {args.city} has no [lidar] section in city.toml", file=sys.stderr)
        return 2

    print(f"lidar: {city.config['city']['name']}")
    layers = _extract_cached(city)
    if not layers.buildings:
        print("error: no buildings to measure", file=sys.stderr)
        return 1

    # Footprints only, and deliberately not `extract.bounds`: Overpass returns
    # the Shannon as whole polygons spanning 18 km, so the all-layer bounds
    # would drag in 16 tiles and a mostly empty 440 MB mosaic to sample a city
    # that fits in seven.
    boxes = [b.geom.bounds for b in layers.buildings]
    pad = 200.0
    window = (min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad,
              max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)
    print(f"  window {window[2] - window[0]:.0f} x {window[3] - window[1]:.0f} m")

    print("  discovering tiles…")
    tiles = discover_tiles(city.config, window)
    if not tiles:
        print("error: no LiDAR tiles cover this city", file=sys.stderr)
        return 1
    captured = sorted({t.captured for t in tiles})
    print(f"  {len(tiles)} tiles at {min(t.resolution for t in tiles):g} m, "
          f"captured {', '.join(captured)}")

    paths = download_tiles(tiles, city.cache, force=args.force)
    model = HeightModel.from_tiles(tiles, paths)

    print(f"  sampling {len(layers.buildings)} footprints…")
    heights = measure(layers.buildings, model, city.config)
    got = len(heights) / max(1, len(layers.buildings))
    print(f"  {len(heights)} of {len(layers.buildings)} read ({got * 100:.1f}%)")

    calibration = calibrate(layers.buildings, heights, city.config)
    if calibration is not None:
        print(f"  calibration: {calibration.storey_m:.2f} m per storey under "
              f"{calibration.pitch_m:.2f} m of roof "
              f"(r={calibration.correlation:.2f}, n={calibration.samples})")

    survey = Survey(heights=heights, calibration=calibration)
    path = save_heights(survey, city.config, tiles, city.cache)
    print(f"  wrote {path.relative_to(city.dir)} "
          f"({path.stat().st_size / 1e3:.0f} kB)")

    _report_heights(city, layers, survey)
    return 0


def _report_heights(city: City, layers, survey) -> None:
    """Check the survey against the buildings whose storeys OSM already knows.

    Tagged buildings are the only ground truth available, and the calibration
    was fitted on them, so quoting the fit's own residuals as accuracy would be
    marking its own homework. The split below is therefore held out: the fit is
    re-run on half the tagged buildings and scored on the half it never saw.
    """
    import statistics

    from .lidar import calibrate

    tagged = [b for b in layers.buildings
              if b.levels_tagged and b.osm_id in survey.heights]
    if not tagged:
        print("  no tagged buildings to validate against")
        return

    # Split by parity of a hash rather than of position, so neighbouring
    # terraces do not all land on the same side. crc32, not hash(): Python
    # salts string hashing per process, which would reshuffle the split on
    # every run and make the number below unreproducible.
    import zlib

    def side(osm_id: str) -> int:
        return zlib.crc32(osm_id.encode()) % 2

    train = [b for b in tagged if side(b.osm_id) == 0]
    test = [b for b in tagged if side(b.osm_id) == 1]
    held_out = calibrate(train, survey.heights, city.config, log=lambda *_: None)

    default_levels = float(city.config["render"].get("default_levels", 2))
    errors, baseline_errors = [], []
    if held_out is not None:
        for building in test:
            predicted = held_out.levels(survey.heights[building.osm_id].roof_m)
            # Round as the pipeline does, so the score measures what is drawn.
            predicted = round(max(1.0, predicted) * 2) / 2
            errors.append(predicted - building.levels)
            baseline_errors.append(default_levels - building.levels)

    lines = [
        "# LiDAR heights — validation",
        "",
        f"Source: {city.config['lidar']['attribution']}",
        "",
        f"- Footprints sampled: **{len(layers.buildings)}**",
        f"- Read by LiDAR: **{len(survey.heights)}** "
        f"({len(survey.heights) / max(1, len(layers.buildings)) * 100:.1f}%)",
        f"- Tagged and read, usable as ground truth: **{len(tagged)}**",
        "",
    ]

    if survey.calibration is not None:
        c = survey.calibration
        lines += [
            "## Calibration",
            "",
            "Fitted on tagged buildings as `roof_85 = storey_m * levels + pitch_m`.",
            "",
            "| Term | Value |",
            "|---|---|",
            f"| Metres per storey | {c.storey_m:.2f} |",
            f"| Roof pitch above eave | {c.pitch_m:.2f} m |",
            f"| Correlation | {c.correlation:.3f} |",
            f"| Buildings fitted | {c.samples} |",
            "",
        ]

    if errors:
        def stats(values: list[float]) -> tuple[float, float, float]:
            absolute = sorted(abs(v) for v in values)
            return (sum(1 for a in absolute if a <= 0.5) / len(absolute),
                    sum(1 for a in absolute if a <= 1.0) / len(absolute),
                    statistics.fmean(absolute))

        within_half, within_one, mae = stats(errors)
        base_half, base_one, base_mae = stats(baseline_errors)

        # The comparison that matters is against the flat default this stage
        # replaces, not against nothing: most tagged buildings are 2 storeys,
        # so "always 2" already scores well and a bare accuracy figure flatters.
        odd = [e for e, b in zip(errors, baseline_errors) if b != 0]
        odd_base = [b for b in baseline_errors if b != 0]

        print(f"  held-out validation on {len(errors)} buildings: "
              f"median error {statistics.median(errors):+.2f} storeys, "
              f"{within_half * 100:.0f}% within half a storey "
              f"(flat default: {base_half * 100:.0f}%)")
        lines += [
            "## Held-out accuracy",
            "",
            f"The calibration was re-fitted on {len(train)} tagged buildings and",
            f"scored on the {len(errors)} it never saw, rounded to half storeys as",
            "the renderer draws them. Error is predicted minus tagged storeys.",
            "",
            f"| Statistic | LiDAR | Flat default of {default_levels:g} |",
            "|---|---|---|",
            f"| Median error | {statistics.median(errors):+.2f} "
            f"| {statistics.median(baseline_errors):+.2f} |",
            f"| Mean absolute error | {mae:.2f} | {base_mae:.2f} |",
            f"| Within half a storey | {within_half * 100:.0f}% "
            f"| {base_half * 100:.0f}% |",
            f"| Within one storey | {within_one * 100:.0f}% | {base_one * 100:.0f}% |",
            "",
        ]
        if odd:
            odd_half, _, odd_mae = stats(odd)
            odd_base_half, _, odd_base_mae = stats(odd_base)
            lines += [
                f"Most tagged buildings really are {default_levels:g} storeys, so the flat",
                "default scores well on the bulk and the totals above understate the",
                f"difference. On the {len(odd)} test buildings that are *not*",
                f"{default_levels:g} storeys — exactly the ones a flat default gets wrong:",
                "",
                f"| Statistic | LiDAR | Flat default |",
                "|---|---|---|",
                f"| Mean absolute error | {odd_mae:.2f} | {odd_base_mae:.2f} |",
                f"| Within half a storey | {odd_half * 100:.0f}% "
                f"| {odd_base_half * 100:.0f}% |",
                "",
            ]
        lines += [
            "Tagged buildings are a biased sample — mappers tag the tall and the",
            "notable — so this flatters the anonymous terraces slightly.",
            "",
        ]

    by_id = {b.osm_id: b for b in layers.buildings}
    lines += [
        "## Tallest ridges found",
        "",
        "These name the tallest things in the frame. They are *not* used as roof",
        "heights — at 2 m a ridge line is too thin to land pixels on, so this",
        "column reads low for anything pitched. See the note in `lidar.py`.",
        "",
        "| Building | Roof m | Ridge m | Pixels |",
        "|---|---|---|---|",
    ]
    for osm_id, height in sorted(survey.heights.items(),
                                 key=lambda kv: -kv[1].ridge_m)[:12]:
        building = by_id.get(osm_id)
        label = building.name if building and building.name else osm_id
        lines.append(f"| {label} | {height.roof_m:.1f} | {height.ridge_m:.1f} "
                     f"| {height.pixels} |")

    city.analysis.mkdir(parents=True, exist_ok=True)
    out = city.analysis / "heights.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"  wrote {out.relative_to(city.dir)}")


def cmd_bearings(args) -> int:
    from .bearings import _offset_from_clean as _offset
    from .bearings import alignment_profile, fit_grid, rose, snap_cost
    from .extract import segment_bearings
    from .plots import rose_figure
    from shapely.geometry import Point
    from pyproj import Transformer

    city = load_city(args.city)
    layers = _extract_cached(city, force=args.force)

    # Streets only: driveways and car-park aisles are noise for grid detection.
    streets = [r for r in layers.roads if r.importance <= 6]
    all_bearings = segment_bearings(streets)
    fit_all = fit_grid(all_bearings)

    # The Georgian core on its own: the planned grid we actually want aligned.
    transformer = Transformer.from_crs("EPSG:4326", city.crs, always_xy=True)
    core_lon, core_lat = -8.6265, 52.6605          # mid O'Connell Street
    cx, cy = transformer.transform(core_lon, core_lat)
    core_centre = Point(cx, cy)
    core_streets = [
        r for r in streets if r.geom.distance(core_centre) <= args.core_radius
    ]
    core_bearings = segment_bearings(core_streets)
    fit_core = fit_grid(core_bearings)

    named = {r.name for r in core_streets if r.name}
    print(f"\nwhole area : {len(streets)} streets, "
          f"{fit_all.total_length_m / 1000:.1f} km")
    print(f"  grid angle {fit_all.grid_angle_deg:.2f}°   strength {fit_all.strength:.3f}"
          f"   entropy {fit_all.entropy:.2f} bits   orderliness {fit_all.orderliness:.3f}")
    print(f"  -> rotation {fit_all.rotation_deg:+.2f}°")

    print(f"\nGeorgian core ({args.core_radius:.0f} m radius): {len(core_streets)} streets, "
          f"{fit_core.total_length_m / 1000:.1f} km")
    print(f"  grid angle {fit_core.grid_angle_deg:.2f}°   strength {fit_core.strength:.3f}"
          f"   entropy {fit_core.entropy:.2f} bits   orderliness {fit_core.orderliness:.3f}")
    print(f"  -> rotation {fit_core.rotation_deg:+.2f}°")
    print(f"  streets included: {', '.join(sorted(n for n in named if n)[:12])}")

    profile_all = alignment_profile(all_bearings)
    profile_core = alignment_profile(core_bearings)
    best_all = max(profile_all, key=lambda p: p[1])
    best_core = max(profile_core, key=lambda p: p[1])
    print(f"\nclean-line share (within 5° of one of the 8 crisp directions):")
    print(f"  whole area best +{best_all[0]:.1f}° -> {best_all[1] * 100:.1f}% of street length")
    print(f"  core       best +{best_core[0]:.1f}° -> {best_core[1] * 100:.1f}%")

    # Compare the candidate rotations on both the core and the whole city.
    candidates = {
        "fitted core grid": fit_core.rotation_deg,
        "fitted whole area": fit_all.rotation_deg,
        "configured": city.rotation_deg,
        "none": 0.0,
    }
    print("\nrotation candidates      core clean   city clean   core bend   city bend")
    for label, rotation in candidates.items():
        core_share = sum(
            length for bearing, length in core_bearings
            if _offset(bearing, rotation) <= 5.0
        ) / (sum(l for _, l in core_bearings) or 1.0)
        all_share = sum(
            length for bearing, length in all_bearings
            if _offset(bearing, rotation) <= 5.0
        ) / (sum(l for _, l in all_bearings) or 1.0)
        print(f"  {label:<22} {rotation:+7.2f}° "
              f"{core_share * 100:8.1f}% {all_share * 100:10.1f}% "
              f"{snap_cost(core_bearings, rotation):9.2f}° {snap_cost(all_bearings, rotation):9.2f}°")

    out = city.analysis
    rose_figure(
        rose(all_bearings), fit_all, profile_all,
        title=f"{city.config['city']['name']} — street bearings, whole fetch area",
        subtitle=f"{len(streets)} streets · {fit_all.total_length_m / 1000:.0f} km of "
                 f"centreline · length-weighted · 36 bins",
        path=out / "bearings-all.png",
    )
    rose_figure(
        rose(core_bearings), fit_core, profile_core,
        title=f"{city.config['city']['name']} — street bearings, Georgian core",
        subtitle=f"{len(core_streets)} streets within {args.core_radius:.0f} m of "
                 f"O'Connell Street · length-weighted · 36 bins",
        path=out / "bearings-core.png",
    )
    print(f"\nwrote {out / 'bearings-all.png'}")
    print(f"wrote {out / 'bearings-core.png'}")
    return 0


def _decorate(city: City, layers):
    """Place the charm layer, if the city asks for one."""
    from .decorate import decorate

    cfg = city.config.get("decorate")
    if cfg is not None and not cfg.get("enabled", True):
        return []
    return decorate(layers, seed=city.seed, config=cfg or {})


def _landmark_config(city: City) -> dict:
    """The city's landmarks.toml — anchors under `landmark`, models under `model`."""
    import tomllib

    path = city.dir / "landmarks.toml"
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _load_landmarks(city: City) -> list[dict]:
    return _landmark_config(city).get("landmark", [])


def cmd_frontages(args) -> int:
    """Rank facades by the wall area they actually show."""
    from pyproj import Transformer

    from .frame import camera_for
    from .frontages import concentration, rank_frontages, write_worksheet
    from .schematize import schematize

    city = load_city(args.city)
    layers = _extract_cached(city, force=args.force)
    layers = schematize(layers, city.rotation_deg,
                        road_simplify_m=city.config["schematize"]["road_simplify_m"],
                        water_simplify_m=city.config["schematize"]["water_simplify_m"])
    camera = camera_for(city, cell_m=args.cell or city.cell_m)
    inv = Transformer.from_crs(city.crs, "EPSG:4326", always_xy=True)

    ranked = rank_frontages(layers.buildings, camera, city.cache / "raw", inv)
    total = sum(f.visible_px for f in ranked) or 1.0
    print(f"\n{len(ranked)} buildings show visible wall in this frame")
    for share, count in sorted(concentration(ranked).items()):
        print(f"  {share*100:.0f}% of visible wall area comes from the top "
              f"{count} buildings ({count/len(ranked)*100:.1f}%)")

    named = sum(1 for f in ranked if f.tags.get("name") or f.tags.get("addr:street"))
    print(f"  {named} of them ({named/len(ranked)*100:.0f}%) carry a name or address in OSM")

    print("\ntop frontages by visible wall:")
    for i, f in enumerate(ranked[:12], start=1):
        print(f"  {i:2}. {f.label[:38]:<40} {f.visible_px:8,.0f} px  "
              f"{f.visible_px/total*100:5.2f}%")

    path = write_worksheet(ranked, city.dir / "facades.md", limit=args.limit)
    print(f"\nwrote {path}")
    return 0


def cmd_frame(args) -> int:
    """Render the configured frame — the composition of record."""
    import math

    from PIL import Image
    from pyproj import Transformer

    from .frame import camera_for, true_storey_px, wgs84_bounds
    from .iso import CELL_H, CELL_W
    from .greybox import annotate_landmarks, render, save_preview

    city = load_city(args.city)
    layers = _extract_cached(city, force=args.force)
    cell_m = args.cell or city.cell_m
    camera = camera_for(city, cell_m=cell_m, scale=args.scale)

    # A widened frame can reach past the OSM snapshot behind it, which shows up
    # as a clean empty band rather than an error. Say so before spending the
    # render rather than after.
    south, west, north, east = wgs84_bounds(camera, city.crs)
    b = city.config["bbox"]
    if (south < b["south"] or west < b["west"]
            or north > b["north"] or east > b["east"]):
        print(f"  WARNING: frame reaches outside the fetched bbox — "
              f"needs S{south:.4f} W{west:.4f} N{north:.4f} E{east:.4f}, "
              f"have S{b['south']} W{b['west']} N{b['north']} E{b['east']}. "
              f"Widen [bbox] and re-run fetch --force.")

    if not args.raw:
        from .schematize import crisp_share, schematize

        before = crisp_share(layers.roads, city.rotation_deg)
        layers = schematize(layers, city.rotation_deg,
                            road_simplify_m=city.config["schematize"]["road_simplify_m"],
                            water_simplify_m=city.config["schematize"]["water_simplify_m"],
                            street_widen_m=city.config["schematize"].get("street_widen_m", 0.0))
        after = crisp_share(layers.roads, city.rotation_deg)
        print(f"  road length on a crisp direction: {before*100:.1f}% -> {after*100:.1f}%")

    if args.grey:
        img, grey_stats = render(layers, camera)
        drawn = grey_stats.buildings_drawn
    else:
        from .landmarks import load_models
        from .paint import render as paint_render
        from .style import STYLES

        models, superseded = load_models(_landmark_config(city))
        props = [] if args.bare else _decorate(city, layers)
        img, stats = paint_render(layers, camera, STYLES[args.style], city.seed,
                                  models=models, superseded=superseded,
                                  props=props,
                                  measured_ridges=args.measured_ridges)
        drawn = stats.buildings
        print(f"  painted {stats.buildings} buildings · "
              f"{stats.roofs_tagged} pitched roofs · "
              f"{stats.facades_detailed} detailed facades · "
              f"{stats.shopfronts} shopfronts · "
              f"{stats.quay_walls} quay walls · {stats.bridges} bridges")
        missing = sorted(set(models) - stats.landmarks_drawn)
        print(f"  {stats.landmarks} landmarks modelled "
              f"({stats.landmark_masses} masses)"
              + (f" · not on canvas: {', '.join(missing)}" if missing else ""))
    path = save_preview(img, city.out / f"{args.slug}.png")

    preview = img.copy()
    preview.thumbnail((1900, 1900), Image.LANCZOS)
    preview.save(city.out / f"{args.slug}-preview.png")

    if args.annotate:
        to_crs = Transformer.from_crs("EPSG:4326", city.crs, always_xy=True)
        marks = [m for m in _load_landmarks(city)
                 if m.get("short") not in set(city.config["frame"].get("exclude", []))]
        annotated, placement = annotate_landmarks(img, camera, marks, to_crs)
        small = annotated.copy()
        small.thumbnail((1900, 1900), Image.LANCZOS)
        small.save(city.out / f"{args.slug}-annotated.png")
        missing = [n for (n, ok) in placement if not ok]
        if missing:
            print(f"  off canvas: {', '.join(missing)}")

    across, deep = camera.ground_extent_m()
    mpx = camera.width_px * camera.height_px / 1e6
    print(f"{camera.width_px}x{camera.height_px} px ({camera.width_px/camera.height_px:.2f}:1, "
          f"{mpx:.0f} Mpx) · rot {camera.rotation_deg:.2f} · cell {cell_m} m")
    print(f"  ground {across:.0f} x {deep:.0f} m · {drawn} buildings")
    # A ground edge along an iso axis is sqrt(CELL_W^2 + CELL_H^2) px per cell,
    # not CELL_W: the wall runs diagonally across the rhombus, not along it.
    print(f"  8 m frontage {8 / cell_m * math.hypot(CELL_W, CELL_H):.0f} px · "
          f"storey {camera.storey_px:.1f} px "
          f"(true isometric {true_storey_px(cell_m):.1f})")
    print(f"  wrote {path}")
    return 0


def cmd_site(args) -> int:
    """Cut the frame into a tile pyramid and emit the zoomable viewer."""
    from pyproj import Transformer

    from .frame import camera_for
    from .landmarks import load_models
    from .paint import render as paint_render
    from .schematize import schematize
    from .site import build_pyramid, landmark_markers, write_site
    from .style import STYLES

    city = load_city(args.city)
    layers = _extract_cached(city, force=args.force)
    cell_m = args.cell or city.cell_m
    camera = camera_for(city, cell_m=cell_m, scale=args.scale)
    print(f"site: {city.config['city']['name']} · "
          f"{camera.width_px}x{camera.height_px} px · cell {cell_m} m")

    layers = schematize(layers, city.rotation_deg,
                        road_simplify_m=city.config["schematize"]["road_simplify_m"],
                        water_simplify_m=city.config["schematize"]["water_simplify_m"],
                        street_widen_m=city.config["schematize"].get("street_widen_m", 0.0))

    models, superseded = load_models(_landmark_config(city))
    props = _decorate(city, layers)
    print("  rendering…")
    image, stats = paint_render(layers, camera, STYLES[args.style], city.seed,
                                models=models, superseded=superseded, props=props)

    out_dir = city.out / "site"
    print("  tiling…")
    pyramid = build_pyramid(image, out_dir, tile_px=args.tile)

    to_crs = Transformer.from_crs("EPSG:4326", city.crs, always_xy=True)
    markers = landmark_markers(city, camera, to_crs=to_crs)

    across, deep = camera.ground_extent_m()
    attribution = ["Map data © OpenStreetMap contributors, ODbL."]
    if "lidar" in city.config:
        attribution.append(city.config["lidar"]["attribution"])

    # Count over the buildings actually in shot, so this share and the drawn
    # building count in the same panel describe the same set.
    in_frame = [b for b in layers.buildings
                if 0 <= camera.ground(*b.geom.centroid.coords[0])[0] < camera.width_px
                and 0 <= camera.ground(*b.geom.centroid.coords[0])[1] < camera.height_px]
    measured = sum(1 for b in in_frame if b.levels_source == "lidar")
    lidar_share = (f"{measured / len(in_frame) * 100:.0f}% LiDAR-measured"
                   if in_frame and measured else "")

    index = write_site(
        out_dir, pyramid, markers,
        city_name=city.config["city"]["name"],
        subtitle=f"{across / 1000:.1f} × {deep / 1000:.1f} km at {cell_m:g} m per cell",
        attribution=attribution,
        stats=[
            ("Buildings", f"{stats.buildings:,}"),
            ("Heights", lidar_share or "tagged/default"),
            ("Pitched roofs", f"{stats.roofs_tagged:,}"),
            ("Resolution", f"{pyramid.width:,} × {pyramid.height:,}"),
            ("Zoom levels", f"{pyramid.max_level + 1}"),
        ],
    )

    size_mb = sum(p.stat().st_size for p in (out_dir / "tiles").rglob("*.png")) / 1e6
    print(f"  {pyramid.tiles} tiles across {pyramid.max_level + 1} levels ({size_mb:.1f} MB)")
    print(f"  {len(markers)} landmark markers")
    print(f"  wrote {index}")
    print(f"\n  serve it:  python -m http.server -d {out_dir} 8000")
    return 0


#: Long edge of a composition study, in pixels. These renders exist to judge
#: what is in shot, not detail, so they are sized for the eye and the clock
#: rather than for the printer — the print canvas is 10,800 px wide and six of
#: those in a contact sheet is minutes of rendering to answer a framing question.
STUDY_WIDTH_PX = 2400


def cmd_greybox(args) -> int:
    from .greybox import annotate_landmarks, render, save_preview
    from .frame import true_storey_px
    from .iso import Camera, solve_frame
    from .plots import contact_sheet
    from pyproj import Transformer

    city = load_city(args.city)
    layers = _extract_cached(city, force=args.force)

    transformer = Transformer.from_crs("EPSG:4326", city.crs, always_xy=True)
    landmarks = _load_landmarks(city)
    # Fallback centre for a city with no tier-1 landmarks; the frame anchor is
    # the same point the real composition is built around.
    anchor = city.config["frame"]["anchor"]
    default_x, default_y = transformer.transform(anchor["lon"], anchor["lat"])

    aspect = city.config["print"]["height_cm"] / city.config["print"]["width_cm"]
    base_w = STUDY_WIDTH_PX
    base_h = round(STUDY_WIDTH_PX * aspect)
    # Height in pixels per storey follows the cell size, so it can only be known
    # once a variant has solved for one. The configured cell gives the nominal
    # value the headroom reservation is scaled from.
    storey_px = true_storey_px(city.cell_m) * city.config["render"]["height_exaggeration"]
    rotation = args.rotation if args.rotation is not None else city.rotation_deg

    def fitted(width: int, height: int, rot: float, *, exclude: set[str] = frozenset(),
               storey: float = None):
        """Cell size and centre that fit the tier-1 landmarks, minus exclusions."""
        pts = [
            transformer.transform(m["lon"], m["lat"])
            for m in landmarks
            if m.get("tier", 1) == 1 and m.get("short") not in exclude
        ]
        if not pts:
            return city.cell_m, default_x, default_y
        # Reserve headroom proportional to how tall buildings will be drawn.
        return solve_frame(
            pts, rot, width, height, margin=0.07,
            headroom_px=20 * (storey or storey_px),
        )

    # Thomond Park sits 1.5 km north-west of everything else, so including it
    # forces the frame wide and fills half the canvas with suburb. The study
    # exists to make that trade-off visible.
    OUTLIER = {"Thomond Park"}

    if args.orientations:
        # A rotation of +/-90 degrees maps the eight clean directions onto
        # themselves, so all four orientations bend the streets identically.
        # The choice is purely compositional — hence looking at all of them.
        variants = []
        for quarter in (0, 90, 180, 270):
            rot = rotation + quarter
            cell_m, ox, oy = fitted(base_w, base_h, rot, exclude={"Thomond Park"})
            variants.append((
                f"{'NESW'[quarter // 90]}  turned {quarter} degrees  (rot {rot:+.2f})",
                cell_m, rot, base_w, base_h, ox, oy, storey_px,
            ))
    elif args.study:
        wide = fitted(base_w, base_h, rotation)
        tight = fitted(base_w, base_h, rotation, exclude=OUTLIER)
        turned = fitted(base_w, base_h, rotation + 90, exclude=OUTLIER)
        portrait = fitted(base_h, base_w, rotation, exclude=OUTLIER)
        tall = fitted(base_w, base_h, rotation, exclude=OUTLIER, storey=4.5)
        variants = [
            ("A  all tier-1 incl. Thomond Park · landscape",
             *wide[:1], rotation, base_w, base_h, *wide[1:], storey_px),
            ("B  tier-1 minus Thomond Park · landscape",
             *tight[:1], rotation, base_w, base_h, *tight[1:], storey_px),
            ("C  tier-1 minus Thomond Park · turned 90 degrees",
             *turned[:1], rotation + 90, base_w, base_h, *turned[1:], storey_px),
            ("D  tier-1 minus Thomond Park · portrait",
             *portrait[:1], rotation, base_h, base_w, *portrait[1:], storey_px),
            ("E  as B, storeys drawn 50 percent taller (4.5 px)",
             *tall[:1], rotation, base_w, base_h, *tall[1:], 4.5),
            ("F  tight core, castle to Colbert only",
             *fitted(base_w, base_h, rotation,
                     exclude=OUTLIER | {"Shannon Br", "St John's"})[:1],
             rotation, base_w, base_h,
             *fitted(base_w, base_h, rotation,
                     exclude=OUTLIER | {"Shannon Br", "St John's"})[1:], storey_px),
        ]
    else:
        if args.fit:
            cell_m, ox, oy = fitted(base_w, base_h, rotation,
                                    exclude=OUTLIER if args.tight else frozenset())
        else:
            cell_m, ox, oy = (args.cell or city.cell_m), default_x, default_y
        variants = [(
            f"cell {cell_m:.2f} m · rot {rotation:+.2f}°",
            cell_m, rotation, base_w, base_h, ox, oy, storey_px,
        )]

    entries = []
    for label, cell_m, rot, width, height, ox, oy, storeys in variants:
        if ox is None:
            ox, oy = default_x, default_y
        if args.lat is not None and args.lon is not None:
            ox, oy = transformer.transform(args.lon, args.lat)

        camera = Camera(
            origin_x=ox, origin_y=oy,
            rotation_deg=rot, cell_m=cell_m,
            width_px=width, height_px=height,
            storey_px=storeys,
        )
        img, stats = render(layers, camera, draw_frame=True)
        slug = label.split()[0].strip().lower() if (args.study or args.orientations) else "greybox"
        path = save_preview(img, city.out / f"greybox-{slug}.png")

        across, deep = stats.ground_extent_m
        print(f"{label}\n    {width}x{height} px · cell {cell_m:.2f} m · "
              f"{stats.buildings_drawn} buildings · ground {across / 1000:.2f} x "
              f"{deep / 1000:.2f} km · -> {path.name}")

        if landmarks:
            annotated, placement = annotate_landmarks(img, camera, landmarks, transformer)
            save_preview(annotated, city.out / f"greybox-{slug}-annotated.png")
            missing = [
                name for (name, ok), m in zip(placement, landmarks)
                if not ok and m.get("tier", 1) == 1
            ]
            if missing:
                print(f"    tier-1 off canvas: {', '.join(missing)}")
            else:
                print("    all tier-1 landmarks on canvas")
        entries.append((label, path))

    if len(entries) > 1:
        sheet = contact_sheet(entries, city.out / "greybox-study.png")
        print(f"\nwrote contact sheet {sheet}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pixelmap", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="download raw OSM layers")
    p_fetch.add_argument("city")
    p_fetch.add_argument("--force", action="store_true", help="re-fetch cached layers")
    p_fetch.set_defaults(func=cmd_fetch)

    p_lidar = sub.add_parser("lidar", help="measure building heights from open LiDAR")
    p_lidar.add_argument("city")
    p_lidar.add_argument("--force", action="store_true",
                         help="re-download the rasters instead of using the cache")
    p_lidar.set_defaults(func=cmd_lidar)

    p_bear = sub.add_parser("bearings", help="street orientation analysis")
    p_bear.add_argument("city")
    p_bear.add_argument("--core-radius", type=float, default=450.0)
    p_bear.add_argument("--force", action="store_true", help="re-run extract")
    p_bear.set_defaults(func=cmd_bearings)

    p_grey = sub.add_parser("greybox", help="unstyled composition render")
    p_grey.add_argument("city")
    p_grey.add_argument("--study", action="store_true", help="render the config comparison set")
    p_grey.add_argument("--fit", action="store_true", help="solve cell size to fit tier-1 landmarks")
    p_grey.add_argument("--tight", action="store_true", help="drop outlying landmarks when fitting")
    p_grey.add_argument("--orientations", action="store_true", help="compare all four turns")
    p_grey.add_argument("--cell", type=float, default=None)
    p_grey.add_argument("--rotation", type=float, default=None)
    p_grey.add_argument("--lat", type=float, default=None)
    p_grey.add_argument("--lon", type=float, default=None)
    p_grey.add_argument("--force", action="store_true", help="re-run extract")
    p_grey.set_defaults(func=cmd_greybox)

    p_frame = sub.add_parser("frame", help="render the configured frame")
    p_frame.add_argument("city")
    p_frame.add_argument("--cell", type=float, default=None,
                         help="override cell size in metres (smaller = more detail)")
    p_frame.add_argument("--scale", type=float, default=None,
                         help="widen the frame by this factor at the same pixels "
                              "per metre and the same aspect (bigger = more city)")
    p_frame.add_argument("--slug", default="frame")
    p_frame.add_argument("--grey", action="store_true",
                         help="grey-box instead of the painted style")
    p_frame.add_argument("--style", default="limerick-day")
    p_frame.add_argument("--raw", action="store_true",
                         help="skip schematize and draw true OSM geometry")
    p_frame.add_argument("--annotate", action="store_true")
    p_frame.add_argument("--bare", action="store_true",
                         help="skip the charm layer (no trees, boats or swans)")
    p_frame.add_argument("--measured-ridges", action="store_true",
                         help="take roof height from the LiDAR instead of the "
                              "width-scaled pitch")
    p_frame.add_argument("--force", action="store_true", help="re-run extract")
    p_frame.set_defaults(func=cmd_frame)

    p_site = sub.add_parser("site", help="cut a tile pyramid and emit the web viewer")
    p_site.add_argument("city")
    p_site.add_argument("--cell", type=float, default=None,
                        help="override cell size in metres (smaller = more detail)")
    p_site.add_argument("--scale", type=float, default=None,
                        help="widen the frame at the same pixels per metre")
    p_site.add_argument("--tile", type=int, default=256, help="tile size in pixels")
    p_site.add_argument("--style", default="limerick-day")
    p_site.add_argument("--force", action="store_true", help="re-run extract")
    p_site.set_defaults(func=cmd_site)

    p_front = sub.add_parser("frontages", help="rank facades by visible wall area")
    p_front.add_argument("city")
    p_front.add_argument("--cell", type=float, default=None)
    p_front.add_argument("--limit", type=int, default=200)
    p_front.add_argument("--force", action="store_true")
    p_front.set_defaults(func=cmd_frontages)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
