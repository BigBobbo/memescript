"""Which facades are actually worth attention.

A frame holds thousands of buildings, but visible wall area is heavily skewed:
a few hundred frontages on the main streets carry most of what the eye reads,
and the rest are back walls, sheds and roofs seen from above. Ranking by the
screen area a building's walls actually occupy turns "detail four thousand
buildings" into a worklist you can finish in an evening.

Output is a worksheet keyed by OSM id, so anything filled in survives a re-fetch
and lands in `overrides.yaml` rather than in the bitmap.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

from .extract import Building
from .iso import Camera


@dataclass
class Frontage:
    building: Building
    visible_px: float
    lat: float
    lon: float
    tags: dict

    @property
    def label(self) -> str:
        t = self.tags
        name = t.get("name")
        if name:
            return name
        number, street = t.get("addr:housenumber"), t.get("addr:street")
        if number and street:
            return f"{number} {street}"
        if street:
            return street
        return t.get("shop") or t.get("amenity") or t.get("building") or "building"

    @property
    def street(self) -> str:
        return self.tags.get("addr:street") or ""

    @property
    def streetview_url(self) -> str:
        """Link for looking the building up by eye."""
        return (
            "https://www.google.com/maps/@?api=1&map_action=pano"
            f"&viewpoint={self.lat:.6f},{self.lon:.6f}"
        )


def _polygon_area(points: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def visible_wall_area(building: Building, camera: Camera) -> float:
    """Screen-space area of the walls this building actually shows the viewer.

    Only walls turned toward the camera count: in the isometric projection those
    are the ones whose ground edge runs left-to-right on screen.
    """
    ring = list(building.geom.exterior.coords)
    if len(ring) < 4:
        return 0.0
    ground = [camera.ground(x, y) for x, y in ring]
    lift = building.levels * camera.storey_px

    total = 0.0
    for i in range(len(ring) - 1):
        a, b = ground[i], ground[i + 1]
        if b[0] < a[0]:
            continue  # facing away from the viewer
        quad = [a, b, (b[0], b[1] - lift), (a[0], a[1] - lift)]
        total += _polygon_area(quad)
    return total


def _load_tags(raw_dir: Path) -> dict[str, dict]:
    path = raw_dir / "buildings.json.gz"
    if not path.exists():
        return {}
    with gzip.open(path, "rt") as fh:
        elements = json.load(fh).get("elements", [])
    return {f"{e['type']}/{e['id']}": e.get("tags", {}) for e in elements}


def rank_frontages(
    buildings: list[Building],
    camera: Camera,
    raw_dir: Path,
    inv_transformer,
    *,
    min_px: float = 200.0,
) -> list[Frontage]:
    """Every on-canvas building, ranked by how much wall it shows."""
    tags = _load_tags(raw_dir)
    out: list[Frontage] = []
    for b in buildings:
        centroid = b.geom.centroid
        sx, sy = camera.ground(centroid.x, centroid.y)
        if not (0 <= sx <= camera.width_px and -200 <= sy <= camera.height_px):
            continue
        area = visible_wall_area(b, camera)
        if area < min_px:
            continue
        lon, lat = inv_transformer.transform(centroid.x, centroid.y)
        out.append(Frontage(b, area, lat, lon, tags.get(b.osm_id, {})))
    out.sort(key=lambda f: -f.visible_px)
    return out


def concentration(frontages: list[Frontage], shares=(0.5, 0.8, 0.9)) -> dict[float, int]:
    """How many buildings account for each share of total visible wall area."""
    total = sum(f.visible_px for f in frontages) or 1.0
    result: dict[float, int] = {}
    running = 0.0
    targets = sorted(shares)
    idx = 0
    for i, f in enumerate(frontages, start=1):
        running += f.visible_px
        while idx < len(targets) and running / total >= targets[idx]:
            result[targets[idx]] = i
            idx += 1
    for t in targets[idx:]:
        result[t] = len(frontages)
    return result


def write_worksheet(frontages: list[Frontage], path: Path, limit: int = 200) -> Path:
    """A fill-in-the-blanks list, ordered by how much each facade matters."""
    total = sum(f.visible_px for f in frontages) or 1.0
    lines = [
        "# Facade worksheet",
        "",
        "Ranked by the wall area each building actually shows in the render, so",
        "the top of this list is where detail pays. Fill in what you can see —",
        "by eye, from a photo, from anywhere — and it becomes `overrides.yaml`.",
        "",
        "`wall` and `trim` take any CSS-style hex. `windows` is the number of",
        "window columns across the frontage; leave blank to let the renderer",
        "infer it from the frontage width.",
        "",
        "| # | building | street | levels | visible px | share | look |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, f in enumerate(frontages[:limit], start=1):
        lines.append(
            f"| {i} | {f.label} | {f.street} | {f.building.levels:g} | "
            f"{f.visible_px:,.0f} | {f.visible_px / total * 100:.2f}% | "
            f"[street view]({f.streetview_url}) |"
        )
    lines += ["", "## Fill these in", "", "```yaml", "facades:"]
    for f in frontages[:limit]:
        lines.append(
            f"  - {{ osm: \"{f.building.osm_id}\", wall: \"\", trim: \"\", windows: }}"
            f"   # {f.label}"
        )
    lines += ["```", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return path
