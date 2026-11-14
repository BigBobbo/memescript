"""Stage 0, offline — build the Overpass layer cache from an OSM .pbf extract.

Public Overpass mirrors are often overloaded or refuse cloud addresses. This
reads a regional extract instead (e.g. openstreetmap.fr's ireland.osm.pbf) and
writes the same `cache/raw/<layer>.json.gz` files `fetch` would, shaped like
Overpass `out geom` / `out tags center` output, so `extract` runs unchanged.

The selectors mirror fetch.LAYERS; keep the two in step. As with Overpass, a
way is included when any of its nodes falls in the bbox, with its full
geometry, and a relation when any member way does.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path


def _re(pattern: str):
    rx = re.compile(pattern)
    return lambda v: v is not None and bool(rx.search(v))


def _eq(value: str):
    return lambda v: v == value


def _any(v):
    return v is not None


# (layer, element kinds, tag key, value test) — one row per Overpass selector.
SELECTORS = [
    ("water", "w", "natural", _eq("water")),
    ("water", "r", "natural", _eq("water")),
    ("water", "w", "waterway", _re(r"^(river|riverbank|stream|canal|dock)$")),
    ("water", "r", "waterway", _eq("riverbank")),
    ("coastline", "w", "natural", _eq("coastline")),
    ("roads", "w", "highway", _re(r"^(motorway|trunk|primary|secondary|tertiary|unclassified|"
                                  r"residential|living_street|pedestrian|service|motorway_link|"
                                  r"trunk_link|primary_link|secondary_link|tertiary_link)$")),
    ("rail", "w", "railway", _re(r"^(rail|light_rail|tram|disused)$")),
    ("green", "w", "leisure", _re(r"^(park|garden|pitch|golf_course|recreation_ground|common)$")),
    ("green", "r", "leisure", _re(r"^(park|garden|pitch|recreation_ground)$")),
    ("green", "w", "landuse", _re(r"^(grass|forest|meadow|cemetery|allotments|village_green|"
                                  r"recreation_ground)$")),
    ("green", "r", "landuse", _re(r"^(grass|forest|meadow|cemetery)$")),
    ("green", "w", "natural", _re(r"^(wood|scrub|grassland|wetland|sand|beach)$")),
    ("buildings", "w", "building", _any),
    ("buildings", "r", "building", _any),
    ("landuse_urban", "w", "landuse", _re(r"^(residential|commercial|industrial|retail|railway|"
                                          r"construction|brownfield|education)$")),
    ("landuse_urban", "w", "amenity", _eq("parking")),
    ("poi", "nwr", "historic", _re(r"^(castle|memorial|monument|ruins|city_gate)$")),
    ("poi", "nwr", "amenity", _re(r"^(place_of_worship|university|hospital|townhall|theatre)$")),
    ("poi", "nwr", "tourism", _re(r"^(museum|attraction|artwork)$")),
    ("poi", "nwr", "leisure", _eq("sports_centre")),
    ("poi", "nwr", "man_made", _re(r"^(bridge|chimney|tower|water_tower)$")),
    ("poi", "nwr", "railway", _eq("station")),
]
LAYER_NAMES = list(dict.fromkeys(s[0] for s in SELECTORS))
KEYS = sorted({s[2] for s in SELECTORS})


def _layers_for(kind: str, tags) -> list[str]:
    hit = []
    for layer, kinds, key, test in SELECTORS:
        if kind in kinds and layer not in hit and test(tags.get(key)):
            hit.append(layer)
    return hit


def fetch_from_pbf(config: dict, cache_dir: Path, pbf: Path, *, log=print) -> dict[str, Path]:
    import osmium

    b = config["bbox"]
    s, w, n, e = b["south"], b["west"], b["north"], b["east"]
    inside = lambda lat, lon: s <= lat <= n and w <= lon <= e  # noqa: E731

    # Pass 1: relations we might want, and the ways they are built from.
    rels: dict[int, tuple[dict, list, list[str]]] = {}
    member_ways: set[int] = set()
    for r in osmium.FileProcessor(str(pbf), osmium.osm.RELATION).with_filter(
            osmium.filter.KeyFilter(*KEYS)):
        tags = dict(r.tags)
        layers = _layers_for("r", tags)
        if not layers:
            continue
        members = [(m.type, m.ref, m.role) for m in r.members]
        rels[r.id] = (tags, members, layers)
        member_ways.update(ref for t, ref, _ in members if t == "w")
    log(f"  pbf: {len(rels)} candidate relations")

    # Pass 2: ways with locations, plus tagged nodes.
    out: dict[str, list] = {name: [] for name in LAYER_NAMES}
    way_geom: dict[int, list[dict]] = {}
    way_in: set[int] = set()
    fp = osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for obj in fp:
        if obj.is_node():
            if not obj.tags or not obj.location.valid():
                continue
            lat, lon = obj.location.lat, obj.location.lon
            if not inside(lat, lon):
                continue
            tags = dict(obj.tags)
            for layer in _layers_for("n", tags):
                out[layer].append({"type": "node", "id": obj.id, "lat": lat, "lon": lon,
                                   "tags": tags})
            continue
        want = obj.id in member_ways
        tags = dict(obj.tags) if obj.tags else {}
        layers = _layers_for("w", tags) if tags else []
        if not want and not layers:
            continue
        geom, hit = [], False
        for nd in obj.nodes:
            if nd.location.valid():
                lat, lon = nd.location.lat, nd.location.lon
                geom.append({"lat": lat, "lon": lon})
                hit = hit or inside(lat, lon)
        if want:
            way_geom[obj.id] = geom
            if hit:
                way_in.add(obj.id)
        if not hit:
            continue
        for layer in layers:
            if layer == "poi":
                lats = [p["lat"] for p in geom]
                lons = [p["lon"] for p in geom]
                out[layer].append({"type": "way", "id": obj.id, "tags": tags,
                                   "center": {"lat": (min(lats) + max(lats)) / 2,
                                              "lon": (min(lons) + max(lons)) / 2}})
            else:
                out[layer].append({"type": "way", "id": obj.id, "tags": tags,
                                   "geometry": geom})

    for rid, (tags, members, layers) in rels.items():
        if not any(t == "w" and ref in way_in for t, ref, _ in members):
            continue
        mem = [{"type": "way", "ref": ref, "role": role, "geometry": way_geom.get(ref, [])}
               for t, ref, role in members if t == "w"]
        for layer in layers:
            if layer == "poi":
                pts = [p for m in mem for p in m["geometry"]]
                if pts:
                    lats = [p["lat"] for p in pts]
                    lons = [p["lon"] for p in pts]
                    out[layer].append({"type": "relation", "id": rid, "tags": tags,
                                       "center": {"lat": (min(lats) + max(lats)) / 2,
                                                  "lon": (min(lons) + max(lons)) / 2}})
            else:
                out[layer].append({"type": "relation", "id": rid, "tags": tags,
                                   "members": mem})

    raw = cache_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    paths = {}
    for layer, elements in out.items():
        path = raw / f"{layer}.json.gz"
        with gzip.open(path, "wt") as fh:
            json.dump({"version": 0.6, "generator": f"pixelmap fetch_pbf ({pbf.name})",
                       "elements": elements}, fh, separators=(",", ":"))
        log(f"  {layer}: {len(elements)} elements ({path.stat().st_size / 1e6:.1f} MB)")
        paths[layer] = path
    return paths
