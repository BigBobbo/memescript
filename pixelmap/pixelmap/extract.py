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
from shapely.ops import polygonize
from shapely.strtree import STRtree
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

#: A derived water region holding more buildings than this is land that the
#: shore test got backwards, not an estuary with a lot of boathouses.
MAX_BUILDINGS_IN_WATER = 12

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
    #: Where `levels` came from: "tag", "lidar" or "default". Tags win over
    #: LiDAR — a surveyed storey count beats a 2 m raster inferring one.
    levels_source: str = "default"
    #: Metres from ground to the LiDAR's highest reading, where it managed one.
    #: Off by default as a roof height — see `paint._roof_rise` and `lidar.py`.
    ridge_m: float | None = None


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


def extract(raw_dir: Path, crs: str, *, bbox=None, log=print) -> Layers:
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

    # Tidal water: derive the area the coastline implies, clipped to the data
    # extent, and treat it as ordinary water from here on.
    coast_lines = []
    for element in _load(raw_dir / "coastline.json"):
        pts = _coords(element)
        if len(pts) >= 2:
            coast_lines.append(project(LineString(pts)))
    if coast_lines and bbox is not None:
        south, west, north, east = bbox
        (x0, y0), (x1, y1) = (
            transformer.transform(west, south), transformer.transform(east, north)
        )
        extent = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        derived = water_from_coastline(
            coast_lines, extent, [a.geom for a in layers.water],
            [b.geom for b in layers.buildings], log=log,
        )
        for poly in derived:
            layers.water.append(Area("coastline", poly, "coastline", None))

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


def water_from_coastline(
    coastline: list[LineString],
    extent: Polygon,
    existing: list[Polygon] | None = None,
    buildings: list[Polygon] | None = None,
    *,
    log=print,
) -> list[Polygon]:
    """Turn coastline ways into the water area they imply.

    Tidal water carries no polygon in OSM. Instead the shore is drawn as
    `natural=coastline` ways with **land on the left and water on the right** of
    the way's direction, and every renderer is expected to work the area out for
    itself. Below Limerick the Shannon is an estuary, so without this the river
    stops dead partway down the frame.

    The coastline is closed against the data extent, the result cut into
    regions, and each region tested against the nearest shore segment to see
    which side it lies on.
    """
    if not coastline:
        return []

    clipped = []
    for line in coastline:
        piece = line.intersection(extent)
        for geom in getattr(piece, "geoms", [piece]):
            if isinstance(geom, LineString) and geom.length > 0:
                clipped.append(geom)
    if not clipped:
        return []

    # Coastline stops where the river stops being tidal — at Limerick that is
    # just above Sarsfield Bridge — so it has a loose end inside the data and
    # cannot enclose anything on its own. Closing it against the already-mapped
    # river polygons gives the estuary a boundary at both ends.
    edges = [*clipped, extent.boundary]
    for poly in existing or []:
        piece = poly.intersection(extent)
        if not piece.is_empty:
            edges.append(piece.boundary)

    regions = list(polygonize(unary_union(edges)))
    if not regions:
        return []
    index = STRtree(regions)

    # Probe outward from the shore rather than inward from each region. Asking
    # "which side of the nearest shore segment is this region's centre on?" fails
    # whenever that centre lies far from the shore — the nearest segment can
    # belong to a completely different stretch of coast, which is what put
    # King's Island under water. Stepping a few metres to the right of the
    # coastline lands unambiguously in the water, whatever shape the region is.
    wet: set[int] = set()
    for line in clipped:
        length = line.length
        if length <= 0:
            continue
        samples = max(2, int(length // 20))
        for i in range(samples + 1):
            along = length * i / samples
            a = line.interpolate(max(0.0, along - 1.0))
            b = line.interpolate(min(length, along + 1.0))
            dx, dy = b.x - a.x, b.y - a.y
            norm = math.hypot(dx, dy)
            if norm < 1e-9:
                continue
            # Right of travel is (dy, -dx); by the coastline convention, water.
            probe = Point(a.x + dy / norm * 4.0, a.y - dx / norm * 4.0)
            for idx in index.query(probe):
                if regions[idx].contains(probe):
                    wet.add(int(idx))
                    break

    water = [regions[i] for i in sorted(wet)]

    # A stretch of estuary holds no houses. If a region does, the shore test has
    # picked the landward side and the whole neighbourhood would be drawn
    # submerged, so drop it rather than trust the geometry.
    if buildings:
        homes = STRtree([b.centroid for b in buildings])
        kept = []
        for region in water:
            inside = sum(1 for i in homes.query(region)
                         if region.contains(Point(buildings[int(i)].centroid)))
            if inside > MAX_BUILDINGS_IN_WATER:
                log(f"  coastline: rejected a {region.area / 1e4:.0f} ha region "
                    f"holding {inside} buildings — it is land, not water")
                continue
            kept.append(region)
        water = kept

    total = sum(p.area for p in water)
    log(f"  coastline: {len(clipped)} ways -> {len(water)} water regions "
        f"({total / 1e4:.0f} ha)")
    return water


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


def apply_lidar_heights(layers: Layers, survey, *, storey_m: float = 3.2,
                        max_levels: float = 60.0) -> dict[str, int]:
    """Replace guessed storey counts with measured ones. Returns a tally by source.

    Precedence is tag > LiDAR > default. A mapper who counted storeys from the
    pavement is more reliable than a 2 m raster, and overriding them would also
    throw away the hand-checked landmark heights.

    A building the LiDAR could not read — built after the survey, or too small
    to catch a return above the minimum height — keeps whatever it had.
    """
    calibration = survey.calibration

    def to_levels(height) -> float:
        if calibration is not None:
            return calibration.levels(height.roof_m)
        # Without a fit there is nothing to subtract the roof pitch with, so
        # this is the cruder reading the calibration exists to improve on.
        return height.roof_m / storey_m

    tally = {"tag": 0, "lidar": 0, "default": 0}
    for building in layers.buildings:
        measured = survey.heights.get(building.osm_id)
        # Recorded whenever it was measured, even where a tag wins on storeys:
        # the tag says how tall the walls are and nothing about the roof.
        if measured is not None:
            building.ridge_m = measured.ridge_m

        if building.levels_tagged:
            building.levels_source = "tag"
        elif measured is not None:
            levels = max(1.0, min(max_levels, to_levels(measured)))
            # Half a storey is the finest step 2 m data can justify, and it
            # keeps a bungalow from rounding up into a two-storey house.
            building.levels = round(levels * 2) / 2
            building.levels_source = "lidar"
        tally[building.levels_source] += 1
    return tally


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
