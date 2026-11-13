"""Building heights from open lidar: normalised DSM (surface minus terrain).

Source: OPW national lidar (2011, 2 m, CC-BY 4.0), served by Geological Survey
Ireland as 2 km DSM + DTM GeoTIFF tiles. The coverage index is an ArcGIS
feature service; each tile row carries its download URL.

OSM storey tags stay authoritative. Lidar only replaces the untagged default,
and only where the footprint holds enough returns that look like a roof — a
building put up after 2011 reads as bare ground and keeps the default.
"""

from __future__ import annotations

import io
import json
import math
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from pyproj import Transformer

from .extract import Building, Layers
from .iso import STOREY_M

COVERAGE = ("https://gsi.geodata.gov.ie/server/rest/services/Lidar/"
            "IE_GSI_LiDAR_Coverage_OPW_NASC_IE26_ITM/FeatureServer/3/query")
ATTRIBUTION = ("Contains Irish Public Sector Data (Geological Survey Ireland & the Office "
               "of Public Works) licensed under CC BY 4.0")
NODATA = -9999.0


def fetch(city, *, force: bool = False) -> list[Path]:
    """Download the DSM/DTM tiles covering the city's fetch bbox."""
    tiles_dir = city.cache / "lidar"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    b = city.config["bbox"]
    to_itm = Transformer.from_crs("EPSG:4326", "EPSG:2157", always_xy=True)
    xs, ys = zip(*(to_itm.transform(lon, lat)
                   for lon in (b["west"], b["east"]) for lat in (b["south"], b["north"])))
    q = urllib.parse.urlencode({
        "geometry": f"{min(xs)},{min(ys)},{max(xs)},{max(ys)}",
        "geometryType": "esriGeometryEnvelope", "inSR": 2157,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "DATA_URL,DATA_NAME",
        "returnGeometry": "false", "f": "json",
    })
    with urllib.request.urlopen(f"{COVERAGE}?{q}", timeout=60) as r:
        rows = [f["attributes"] for f in json.load(r)["features"]]
    got = []
    for row in rows:
        name = row["DATA_NAME"]
        wanted = [tiles_dir / f"{name}_{kind}.tif" for kind in ("DSM", "DTM")]
        if force or not all(p.exists() for p in wanted):
            print(f"  lidar: downloading {name}")
            with urllib.request.urlopen(row["DATA_URL"], timeout=300) as r:
                zf = zipfile.ZipFile(io.BytesIO(r.read()))
            for p in wanted:
                p.write_bytes(zf.read(p.name))
        got += wanted
    print(f"  lidar: {len(rows)} tiles in {tiles_dir}")
    return got


@dataclass
class Raster:
    """A north-up grid in ITM metres."""

    data: np.ndarray
    x0: float      #: west edge
    y0: float      #: north edge
    px: float      #: cell size

    def sample_mask(self, poly) -> np.ndarray:
        """Values whose cell centres fall inside a polygon."""
        from shapely import contains_xy

        minx, miny, maxx, maxy = poly.bounds
        c0 = max(0, int((minx - self.x0) / self.px))
        c1 = min(self.data.shape[1], int(math.ceil((maxx - self.x0) / self.px)))
        r0 = max(0, int((self.y0 - maxy) / self.px))
        r1 = min(self.data.shape[0], int(math.ceil((self.y0 - miny) / self.px)))
        if c1 <= c0 or r1 <= r0:
            return np.empty(0, np.float32)
        cx = self.x0 + (np.arange(c0, c1) + 0.5) * self.px
        cy = self.y0 - (np.arange(r0, r1) + 0.5) * self.px
        gx, gy = np.meshgrid(cx, cy)
        inside = contains_xy(poly, gx, gy)
        return self.data[r0:r1, c0:c1][inside]


def ndsm(city) -> Raster | None:
    """Mosaic surface minus terrain over every cached tile; None if there are none."""
    import tifffile

    tiles_dir = city.cache / "lidar"
    dsms = sorted(tiles_dir.glob("*_DSM.tif"))
    if not dsms:
        return None
    tiles = []
    for dsm_path in dsms:
        dtm_path = dsm_path.with_name(dsm_path.name.replace("_DSM", "_DTM"))
        with tifffile.TiffFile(dsm_path) as t:
            page = t.pages[0]
            sx, sy, _ = page.tags[33550].value
            _, _, _, x0, y0, _ = page.tags[33922].value
            dsm = page.asarray().astype(np.float32)
        dtm = tifffile.imread(dtm_path).astype(np.float32)
        h = dsm - dtm
        h[(dsm <= NODATA + 1) | (dtm <= NODATA + 1)] = np.nan
        tiles.append((round(x0), round(y0), sx, h))
    px = tiles[0][2]
    west = min(t[0] for t in tiles)
    north = max(t[1] for t in tiles)
    east = max(t[0] + t[3].shape[1] * px for t in tiles)
    south = min(t[1] - t[3].shape[0] * px for t in tiles)
    grid = np.full((round((north - south) / px), round((east - west) / px)), np.nan, np.float32)
    for x0, y0, _, h in tiles:
        r, c = round((north - y0) / px), round((x0 - west) / px)
        grid[r:r + h.shape[0], c:c + h.shape[1]] = h
    return Raster(grid, west, north, px)


@dataclass
class HeightStats:
    sampled: int = 0
    replaced: int = 0
    kept_default: int = 0      #: too few roof returns (new since 2011, or tiny)
    tagged_kept: int = 0


def eave_height(values: np.ndarray, percentile: float) -> float | None:
    """Wall height from the roof returns inside a footprint, or None if not a roof."""
    v = values[np.isfinite(values)]
    roof = v[v > 2.0]                       # under 2 m is ground, cars, walls
    if len(roof) < 3 or len(roof) < 0.5 * len(v):
        return None
    return float(np.percentile(roof, percentile))


def apply(layers: Layers, city, raster: Raster, *, layers_crs_to_itm=None,
          percentile: float = 35.0, inset_m: float = 1.0) -> tuple[Layers, HeightStats]:
    """Replace untagged default storeys with lidar-derived ones."""
    from shapely.ops import transform as shp_transform

    stats = HeightStats()
    to_itm = None
    if layers.crs.upper() not in ("EPSG:2157",):
        t = Transformer.from_crs(layers.crs, "EPSG:2157", always_xy=True)
        to_itm = lambda g: shp_transform(t.transform, g)  # noqa: E731
    out: list[Building] = []
    for b in layers.buildings:
        if b.levels_tagged:
            stats.tagged_kept += 1
            out.append(b)
            continue
        geom = to_itm(b.geom) if to_itm else b.geom
        core = geom.buffer(-inset_m)        # keep clear of walls and eaves overhang
        if core.is_empty:
            core = geom
        stats.sampled += 1
        h = eave_height(raster.sample_mask(core), percentile)
        if h is None:
            stats.kept_default += 1
            out.append(b)
            continue
        levels = max(1.0, round(h / STOREY_M * 2) / 2)
        stats.replaced += 1
        out.append(replace(b, levels=levels))
    return replace(layers, buildings=out), stats


def calibrate(layers: Layers, raster: Raster, percentiles=range(10, 95, 5),
              inset_m: float = 1.0) -> list[tuple[float, float, float, int]]:
    """Score each percentile against OSM-tagged storeys: (pct, mean abs err, bias, n)."""
    tagged = [b for b in layers.buildings if b.levels_tagged and b.levels <= 30]
    samples = []
    for b in tagged:
        core = b.geom.buffer(-inset_m)
        v = raster.sample_mask(core if not core.is_empty else b.geom)
        samples.append((b.levels, v))
    rows = []
    for p in percentiles:
        errs = []
        for levels, v in samples:
            h = eave_height(v, p)
            if h is not None:
                errs.append(max(1.0, round(h / STOREY_M * 2) / 2) - levels)
        e = np.array(errs)
        rows.append((p, float(np.abs(e).mean()), float(e.mean()), len(e)))
    return rows
