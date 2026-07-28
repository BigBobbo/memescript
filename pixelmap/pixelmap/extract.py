"""Stage 1 — extract.

Normalizes raw Overpass JSON into typed, metric geometry: shapely objects
projected into the city's CRS (Irish Transverse Mercator for Limerick), with
only the tags the renderer actually cares about.

Everything downstream works in metres; this is the last stage that knows about
latitude and longitude.
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

# Carriageway widths in metres by highway class — deliberately a little wider
# than reality so streets stay legible once quantized to ~3 m cells.
ROAD_WIDTH_M = {
    "motorway": 15.0,
    "trunk": 13.0,
    "primary": 12.0,
    "secondary": 10.0,
    "tertiary": 8.5,
    "unclassified": 7.0,
    "residential": 7.0,
    "living_street": 5.5,
    "pedestrian": 6.0,
    "service": 4.0,
}
for _base in ("motorway", "trunk", "primary", "secondary", "tertiary"):
    ROAD_WIDTH_M[f"{_base}_link"] = ROAD_WIDTH_M[_base] * 0.7

#: Roads at or above this class survive into the schematic street skeleton.
ROAD_IMPORTANCE = {
    "motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4,
    "unclassified": 5, "residential": 5, "living_street": 6, "pedestrian": 6,
    "service": 7,
}


@dataclass
class Road:
    osm_id: str
    geom: LineString
    highway: str
    name: str | None
    width_m: float
    bridge: bool
    tunnel: bool
    layer: int

    @property
    def importance(self) -> int:
        return ROAD_IMPORTANCE.get(self.highway, 7)


@dataclass
class Building:
    osm_id: str
    geom: Polygon
    levels: float
    levels_tagged: bool
    kind: str
    name: str | None
    #: Roof tagging is unusually good in Limerick — 30% of buildings carry a
    #: roof:shape — and the roof is the largest surface an isometric view shows.
    roof_shape: str | None = None
    roof_orientation: str | None = None
    roof_colour: str | None = None
    #: A shop or amenity means a shopfront on the ground floor.
    shop: str | None = None
    housenumber: str | None = None
    street: str | None = None


@dataclass
class Area:
    osm_id: str
    geom: Polygon
    kind: str
    name: str | None


@dataclass
class Poi:
    osm_id: str
    point: Point
    name: str | None
    tags: dict


@dataclass
class Layers:
    """Everything the renderer needs, in projected metres."""

    crs: str
    roads: list[Road] = field(default_factory=list)
    rail: list[Road] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)
    water: list[Area] = field(default_factory=list)
    waterways: list[Road] = field(default_factory=list)
    green: list[Area] = field(default_factory=list)
    urban: list[Area] = field(default_factory=list)
    pois: list[Poi] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"roads={len(self.roads)} rail={len(self.rail)} "
            f"buildings={len(self.buildings)} water={len(self.water)} "
            f"waterways={len(self.waterways)} green={len(self.green)} "
            f"urban={len(self.urban)} pois={len(self.pois)}"
        )


def _parse_levels(tags: dict) -> tuple[float, bool]:
    """Storeys from tags. Returns (levels, was_tagged).

    Ireland has effectively no `height` tags, and 83% of Limerick's tagged
    buildings are 2 storeys — so an untagged building is assumed to be 2.
    """
    raw = tags.get("building:levels")
    if raw:
        # Values like "2", "1.5", "2;3" all occur in the wild.
        token = str(raw).split(";")[0].strip().replace(",", ".")
        try:
            levels = float(token)
            if 0 < levels < 100:
                return levels, True
        except ValueError:
            pass
    height = tags.get("height")
    if height:
        try:
            metres = float(str(height).split()[0].replace(",", "."))
            if 0 < metres < 400:
                return max(1.0, metres / 3.2), True
        except ValueError:
            pass
    return 2.0, False


def _assemble_rings(segments: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Join relation member ways end-to-end into closed rings."""
    remaining = [list(seg) for seg in segments if len(seg) >= 2]
    rings: list[list[tuple[float, float]]] = []

    while remaining:
        ring = remaining.pop(0)
        extended = True
        while extended and ring[0] != ring[-1]:
            extended = False
            for i, seg in enumerate(remaining):
                if seg[0] == ring[-1]:
                    ring.extend(seg[1:])
                elif seg[-1] == ring[-1]:
                    ring.extend(reversed(seg[:-1]))
                elif seg[-1] == ring[0]:
                    ring = seg[:-1] + ring
                elif seg[0] == ring[0]:
                    ring = list(reversed(seg[1:])) + ring
                else:
                    continue
                remaining.pop(i)
                extended = True
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def _coords(element: dict) -> list[tuple[float, float]]:
    return [(pt["lon"], pt["lat"]) for pt in element.get("geometry", []) if pt]


def _polygons_from_element(element: dict) -> list[Polygon]:
    """Build valid polygons from an Overpass way or multipolygon relation."""
    polys: list[Polygon] = []

    if element["type"] == "way":
        pts = _coords(element)
        if len(pts) >= 4 and pts[0] == pts[-1]:
            polys.append(Polygon(pts))
        elif len(pts) >= 3:
            polys.append(Polygon(pts + [pts[0]]))  # tolerate unclosed areas

    elif element["type"] == "relation":
        outers, inners = [], []
        for member in element.get("members", []):
            pts = _coords(member)
            if len(pts) < 2:
                continue
            (inners if member.get("role") == "inner" else outers).append(pts)
        outer_rings = _assemble_rings(outers)
        inner_rings = _assemble_rings(inners)
        for ring in outer_rings:
            holes = []
            shell = Polygon(ring)
            if not shell.is_valid:
                shell = shell.buffer(0)
            for hole in inner_rings:
                try:
                    if shell.contains(Point(hole[0])):
                        holes.append(hole)
                except Exception:
                    continue
            try:
                polys.append(Polygon(ring, holes))
            except Exception:
                polys.append(Polygon(ring))

    cleaned = []
    for poly in polys:
        if poly.is_empty:
            continue
        if not poly.is_valid:
            fixed = poly.buffer(0)
            if fixed.is_empty:
                continue
            if isinstance(fixed, MultiPolygon):
                cleaned.extend(p for p in fixed.geoms if not p.is_empty)
                continue
            poly = fixed
        if isinstance(poly, Polygon) and poly.area > 0:
            cleaned.append(poly)
    return cleaned


def _load(path: Path) -> list[dict]:
    """Load a cached layer, gzipped or plain."""
    gz = path.with_suffix(path.suffix + ".gz") if path.suffix != ".gz" else path
    if gz.exists():
        with gzip.open(gz, "rt") as fh:
            return json.load(fh).get("elements", [])
    if path.exists():
        return json.loads(path.read_text()).get("elements", [])
    return []


def extract(raw_dir: Path, crs: str, *, log=print) -> Layers:
    """Turn cached Overpass JSON into projected, typed layers."""
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    project = lambda geom: shapely_transform(  # noqa: E731
        lambda xs, ys, zs=None: transformer.transform(xs, ys), geom
    )
    layers = Layers(crs=crs)

    for element in _load(raw_dir / "roads.json"):
        pts = _coords(element)
        if len(pts) < 2:
            continue
        tags = element.get("tags", {})
        highway = tags.get("highway", "")
        try:
            layer_val = int(float(tags.get("layer", 0)))
        except ValueError:
            layer_val = 0
        layers.roads.append(
            Road(
                osm_id=f"way/{element['id']}",
                geom=project(LineString(pts)),
                highway=highway,
                name=tags.get("name"),
                width_m=ROAD_WIDTH_M.get(highway, 6.0),
                bridge=bool(tags.get("bridge")),
                tunnel=bool(tags.get("tunnel")),
                layer=layer_val,
            )
        )

    for element in _load(raw_dir / "rail.json"):
        pts = _coords(element)
        if len(pts) < 2:
            continue
        tags = element.get("tags", {})
        layers.rail.append(
            Road(
                osm_id=f"way/{element['id']}",
                geom=project(LineString(pts)),
                highway="rail",
                name=tags.get("name"),
                width_m=5.0,
                bridge=bool(tags.get("bridge")),
                tunnel=bool(tags.get("tunnel")),
                layer=0,
            )
        )

    for element in _load(raw_dir / "buildings.json"):
        tags = element.get("tags", {})
        levels, tagged = _parse_levels(tags)
        for poly in _polygons_from_element(element):
            layers.buildings.append(
                Building(
                    osm_id=f"{element['type']}/{element['id']}",
                    geom=project(poly),
                    levels=levels,
                    levels_tagged=tagged,
                    kind=str(tags.get("building", "yes")),
                    name=tags.get("name"),
                    roof_shape=tags.get("roof:shape"),
                    roof_orientation=tags.get("roof:orientation"),
                    roof_colour=tags.get("roof:colour"),
                    shop=tags.get("shop") or tags.get("amenity"),
                    housenumber=tags.get("addr:housenumber"),
                    street=tags.get("addr:street"),
                )
            )

    for element in _load(raw_dir / "water.json"):
        tags = element.get("tags", {})
        kind = tags.get("natural") or tags.get("waterway") or "water"
        polys = _polygons_from_element(element)
        if polys:
            for poly in polys:
                layers.water.append(
                    Area(f"{element['type']}/{element['id']}", project(poly), kind, tags.get("name"))
                )
        elif element["type"] == "way":
            pts = _coords(element)
            if len(pts) >= 2:  # narrow watercourse: a line, widened later
                layers.waterways.append(
                    Road(
                        osm_id=f"way/{element['id']}",
                        geom=project(LineString(pts)),
                        highway=kind,
                        name=tags.get("name"),
                        width_m=6.0 if kind in ("river", "canal") else 3.0,
                        bridge=False,
                        tunnel=bool(tags.get("tunnel")),
                        layer=0,
                    )
                )

    for name, target in (("green.json", layers.green), ("landuse_urban.json", layers.urban)):
        for element in _load(raw_dir / name):
            tags = element.get("tags", {})
            kind = (
                tags.get("leisure")
                or tags.get("landuse")
                or tags.get("natural")
                or tags.get("amenity")
                or "area"
            )
            for poly in _polygons_from_element(element):
                target.append(
                    Area(f"{element['type']}/{element['id']}", project(poly), kind, tags.get("name"))
                )

    for element in _load(raw_dir / "poi.json"):
        tags = element.get("tags", {})
        if element["type"] == "node":
            lon, lat = element.get("lon"), element.get("lat")
        else:
            centre = element.get("center") or {}
            lon, lat = centre.get("lon"), centre.get("lat")
        if lon is None or lat is None:
            continue
        layers.pois.append(
            Poi(
                osm_id=f"{element['type']}/{element['id']}",
                point=project(Point(lon, lat)),
                name=tags.get("name"),
                tags=tags,
            )
        )

    log(f"  extracted: {layers.summary()}")
    return layers


def bounds(layers: Layers) -> tuple[float, float, float, float]:
    """Projected bounds across every layer."""
    geoms = [
        *(r.geom for r in layers.roads),
        *(b.geom for b in layers.buildings),
        *(a.geom for a in layers.water),
    ]
    if not geoms:
        raise ValueError("no geometry extracted")
    merged = unary_union([g.envelope for g in geoms])
    return merged.bounds


def tagged_levels_share(layers: Layers) -> float:
    if not layers.buildings:
        return 0.0
    return sum(1 for b in layers.buildings if b.levels_tagged) / len(layers.buildings)


def segment_bearings(roads: list[Road]) -> list[tuple[float, float]]:
    """(bearing degrees, length metres) for every road segment, in the projected CRS.

    Bearings are measured clockwise from grid north, which in Irish Transverse
    Mercator is close enough to true north across a single city.
    """
    out: list[tuple[float, float]] = []
    for road in roads:
        coords = list(road.geom.coords)
        for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            bearing = math.degrees(math.atan2(dx, dy)) % 360.0
            out.append((bearing, length))
    return out
