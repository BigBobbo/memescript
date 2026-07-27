"""Stage 0 — fetch.

Pulls raw OSM layers from the Overpass API into the city's cache directory.

Public Overpass instances are frequently overloaded, so every query rotates
through a list of mirrors with exponential backoff, and each layer is cached
independently: a failure only costs the layer that failed. Cached responses are
committed to the repo so a print stays reproducible even as OSM changes.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Descriptive UA is required: overpass-api.de answers 406 to blank agents.
USER_AGENT = "pixelmap/0.1 (isometric pixel-art city maps; contact via repo)"

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

MAX_ATTEMPTS = 8
TIMEOUT_S = 180


@dataclass(frozen=True)
class Layer:
    """One Overpass query, cached as one JSON file."""

    name: str
    selectors: tuple[str, ...]
    #: `geom` inlines coordinates on ways/relation members — no node resolution
    #: needed downstream. `center` is enough for point-like anchors.
    out: str = "geom"

    def query(self, bbox: tuple[float, float, float, float]) -> str:
        s, w, n, e = bbox
        box = f"{s},{w},{n},{e}"
        body = "\n".join(f"  {sel}({box});" for sel in self.selectors)
        return f"[out:json][timeout:{TIMEOUT_S}];\n(\n{body}\n);\nout {self.out};"


# Layers are deliberately narrow: each one maps to a render concern, so a
# retry, a schema tweak, or a re-fetch stays scoped to that concern.
LAYERS: tuple[Layer, ...] = (
    Layer(
        "water",
        (
            'way["natural"="water"]',
            'relation["natural"="water"]',
            'way["waterway"~"^(river|riverbank|stream|canal|dock)$"]',
            'relation["waterway"="riverbank"]',
        ),
    ),
    Layer(
        "roads",
        (
            'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|'
            'unclassified|residential|living_street|pedestrian|service|'
            'motorway_link|trunk_link|primary_link|secondary_link|tertiary_link)$"]',
        ),
    ),
    Layer("rail", ('way["railway"~"^(rail|light_rail|tram|disused)$"]',)),
    Layer(
        "green",
        (
            'way["leisure"~"^(park|garden|pitch|golf_course|recreation_ground|common)$"]',
            'relation["leisure"~"^(park|garden|pitch|recreation_ground)$"]',
            'way["landuse"~"^(grass|forest|meadow|cemetery|allotments|village_green|recreation_ground)$"]',
            'relation["landuse"~"^(grass|forest|meadow|cemetery)$"]',
            'way["natural"~"^(wood|scrub|grassland|wetland|sand|beach)$"]',
        ),
    ),
    Layer(
        "buildings",
        ('way["building"]', 'relation["building"]'),
    ),
    Layer(
        "landuse_urban",
        (
            'way["landuse"~"^(residential|commercial|industrial|retail|railway|'
            'construction|brownfield|education)$"]',
            'way["amenity"="parking"]',
        ),
    ),
    Layer(
        "poi",
        (
            'nwr["historic"~"^(castle|memorial|monument|ruins|city_gate)$"]',
            'nwr["amenity"~"^(place_of_worship|university|hospital|townhall|theatre)$"]',
            'nwr["tourism"~"^(museum|attraction|artwork)$"]',
            'nwr["leisure"="sports_centre"]',
            'nwr["man_made"~"^(bridge|chimney|tower|water_tower)$"]',
            'nwr["railway"="station"]',
        ),
        out="tags center",
    ),
)


def _post(url: str, query: str) -> bytes:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S + 30) as resp:
        return resp.read()


def run_query(query: str, *, log=print) -> dict:
    """Run one Overpass query, rotating mirrors until one answers with JSON."""
    last_error = "no attempt made"
    for attempt in range(MAX_ATTEMPTS):
        url = MIRRORS[attempt % len(MIRRORS)]
        host = urllib.parse.urlparse(url).netloc
        try:
            raw = _post(url, query)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            # Overpass reports runtime errors as HTML with a 200 status.
            if raw[:1] == b"{":
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    last_error = f"bad JSON from {host}: {exc}"
            else:
                snippet = raw[:160].decode("utf-8", "replace").replace("\n", " ")
                last_error = f"non-JSON from {host}: {snippet}"

        delay = min(2 ** attempt, 60)
        log(f"    attempt {attempt + 1}/{MAX_ATTEMPTS} failed ({last_error[:90]}); "
            f"retry in {delay}s")
        time.sleep(delay)

    raise RuntimeError(f"Overpass query failed after {MAX_ATTEMPTS} attempts: {last_error}")


def fetch_city(config: dict, cache_dir: Path, *, force: bool = False, log=print) -> dict[str, Path]:
    """Fetch every layer for a city. Returns {layer name: cached path}."""
    bbox = (
        config["bbox"]["south"],
        config["bbox"]["west"],
        config["bbox"]["north"],
        config["bbox"]["east"],
    )
    raw_dir = cache_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for layer in LAYERS:
        path = raw_dir / f"{layer.name}.json.gz"
        if path.exists() and not force:
            with gzip.open(path, "rt") as fh:
                n = len(json.load(fh).get("elements", []))
            log(f"  {layer.name}: cached ({n} elements)")
            paths[layer.name] = path
            continue

        log(f"  {layer.name}: fetching…")
        result = run_query(layer.query(bbox), log=log)
        with gzip.open(path, "wt") as fh:
            json.dump(result, fh, separators=(",", ":"))
        size_mb = path.stat().st_size / 1e6
        log(f"  {layer.name}: {len(result.get('elements', []))} elements "
            f"({size_mb:.1f} MB)")
        paths[layer.name] = path
        time.sleep(2)  # be a good Overpass citizen between layers

    return paths
