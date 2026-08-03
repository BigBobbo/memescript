"""Stage 0b — LiDAR building heights.

OSM gives Limerick 21,949 footprints and almost no heights: 6% carry
`building:levels` and none carry `height`, so the renderer has been drawing a
flat 2-storey city. Ireland publishes open LiDAR that covers the whole frame,
which turns the guess into a measurement.

The source is the OPW National Aerial Survey Contract set, 2 m grid, flown
2011, CC-BY 4.0. Each tile ships a DSM (first return — roofs and trees) and a
DTM (bare earth). Their difference is height above local ground, so a hill
under a terrace does not inflate the terrace.

**Read the roof high, then calibrate down to the eave.** The renderer lifts
walls to `levels` storeys and puts a pitched roof on top of them
(`draw3d.ridge_roof`), so the number it wants is the eave. The tempting way to
get it — a low percentile of the roof surface, since the surface spreads from
eave up to ridge — measures badly at 2 m. A terrace is three pixels across, and
a pixel on the outline averages roof with pavement, so low percentiles sample
the mixing rather than the eaves. Swept against the buildings OSM has already
tagged, the 20th percentile correlates at r=0.60 and implies an impossible
2.0 m storey; the 85th correlates at r=0.76 and implies 2.9 m.

The contamination is one-directional — mixed pixels always read low — so a high
percentile rejects it for free, and eroding the footprint first stops being
necessary. What a high percentile measures is near the ridge, which is why the
eave is recovered by a calibration rather than read off directly:

    roof_85 = storey_m * levels + pitch_m

fitted per city against the tagged buildings. The intercept is the roof's own
height above the eave, so the relation is physical rather than a curve fit;
for Limerick it comes out at 2.9 m a storey under 1.2 m of pitch. Cities get
their own fit, so a second city stays a config folder rather than a second
calibration to hand-tune.

Vintage is a feature as much as a limit: anything built after 2011 reads as
bare ground, fails the minimum-height test and is handed back to the tag or the
default rather than being flattened to nothing.

**The ridge is recorded but must not be used as a roof height.** A 2 m raster
cannot see a ridge line: it is a thin feature, few pixels land on it, and even
the 97th percentile lands well below it — the same reason St John's 90 m spire
reads as 56 m. Measured against the wall tops, it implies a median roof of
0.86 m where a real gabled terrace rises 2-3 m, so feeding it to the renderer
would flatten the whole roofscape. It does not help pick a roof shape either:
99.8% of Limerick's roof-tagged buildings are pitched, so there is nothing to
discriminate, and the spread between the 85th and 97th percentiles scores 21%
against 99.7% for the footprint-area rule already in `paint._infer_roof_shape`.
The width-scaled pitch the renderer draws is the better model. The measurement
stays here because it is honest data about big flat-roofed buildings and it
names the tallest things in the frame; it is not a roof height.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path

import numpy as np
import shapely
from PIL import Image
from shapely.geometry import Polygon

USER_AGENT = "pixelmap/0.1 (isometric pixel-art city maps; contact via repo)"
MAX_ATTEMPTS = 5
TIMEOUT_S = 180

#: GeoTIFF tags carrying the georeferencing we need. The GSI rasters are plain
#: north-up grids, so a tiepoint and a scale are the whole transform.
TAG_TIEPOINT = 33922
TAG_PIXEL_SCALE = 33550
TAG_NODATA = 42113

# Pillow reads these as mode "F" without GDAL, which keeps the dependency list
# at numpy/shapely/pyproj/pillow.
Image.MAX_IMAGE_PIXELS = None


@dataclass(frozen=True)
class Tile:
    """One 2 x 2 km LiDAR tile, as the coverage service describes it."""

    name: str
    url: str
    left: float
    bottom: float
    right: float
    top: float
    resolution: float
    captured: str


@dataclass(frozen=True)
class Height:
    """What the LiDAR says about one footprint, in metres above local ground."""

    #: High percentile of the roof surface — the calibration's input, near but
    #: not exactly the ridge.
    roof_m: float
    ridge_m: float
    pixels: int


@dataclass(frozen=True)
class Calibration:
    """`roof_m = storey_m * levels + pitch_m`, fitted on tagged buildings."""

    storey_m: float
    pitch_m: float
    samples: int
    correlation: float

    def levels(self, roof_m: float) -> float:
        return (roof_m - self.pitch_m) / self.storey_m


@dataclass(frozen=True)
class Survey:
    """A completed height survey: the readings plus the fit that reads them."""

    heights: dict[str, Height]
    calibration: Calibration | None

    def __bool__(self) -> bool:
        return bool(self.heights)


def _get(url: str, *, log=print) -> bytes:
    """GET with the same mirror-less backoff shape the Overpass fetcher uses."""
    last_error = "no attempt made"
    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return resp.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        delay = min(2 ** attempt, 30)
        log(f"    attempt {attempt + 1}/{MAX_ATTEMPTS} failed ({last_error[:80]}); "
            f"retry in {delay}s")
        time.sleep(delay)
    raise RuntimeError(f"GET failed after {MAX_ATTEMPTS} attempts: {url}: {last_error}")


def discover_tiles(config: dict, bounds: tuple[float, float, float, float], *,
                   log=print) -> list[Tile]:
    """Ask the coverage service which tiles intersect a projected bounding box.

    `bounds` is (minx, miny, maxx, maxy) in the city CRS, which for Limerick is
    the same ITM the rasters are published in.
    """
    lidar_cfg = config["lidar"]
    query = urllib.parse.urlencode({
        "geometry": ",".join(f"{v:.0f}" for v in bounds),
        "geometryType": "esriGeometryEnvelope",
        "inSR": lidar_cfg["srid"],
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "DATA_NAME,DATA_URL,RESOLUTION,DATECAPTUR,"
                     "EXT_LEFT,EXT_TOP,EXT_RIGHT,EXT_BOTTOM",
        "returnGeometry": "false",
        "f": "json",
    })
    payload = json.loads(_get(f"{lidar_cfg['service']}/query?{query}", log=log))
    if "features" not in payload:
        raise RuntimeError(f"coverage service returned no features: {str(payload)[:200]}")

    tiles = []
    for feature in payload["features"]:
        a = feature["attributes"]
        # The service publishes tile extents as attributes; without them we
        # cannot place the raster, so such a tile is unusable.
        if a.get("EXT_LEFT") is None:
            log(f"  skipping {a.get('DATA_NAME')}: no extent attributes")
            continue
        tiles.append(Tile(
            name=a["DATA_NAME"],
            url=a["DATA_URL"],
            left=float(a["EXT_LEFT"]),
            bottom=float(a["EXT_BOTTOM"]),
            right=float(a["EXT_RIGHT"]),
            top=float(a["EXT_TOP"]),
            resolution=float(a["RESOLUTION"]),
            captured=str(a["DATECAPTUR"]),
        ))
    return sorted(tiles, key=lambda t: t.name)


def _read_geotiff(data: bytes) -> tuple[np.ndarray, float, float, float, float]:
    """Array plus (left, top, scale, nodata) from a north-up GeoTIFF."""
    with Image.open(BytesIO(data)) as im:
        array = np.asarray(im, dtype=np.float32)
        tiepoint = im.tag_v2[TAG_TIEPOINT]
        scale = im.tag_v2[TAG_PIXEL_SCALE]
        nodata = float(im.tag_v2.get(TAG_NODATA, -9999))
    # Tiepoint maps raster (i,j,k) to model (x,y,z); these rasters pin pixel 0,0.
    return array, float(tiepoint[3]), float(tiepoint[4]), float(scale[0]), nodata


def download_tiles(tiles: list[Tile], cache_dir: Path, *, force: bool = False,
                   log=print) -> dict[str, Path]:
    """Fetch each tile's zip once. Returns {tile name: local zip}."""
    tile_dir = cache_dir / "lidar" / "tiles"
    tile_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for tile in tiles:
        path = tile_dir / f"{tile.name}.zip"
        if path.exists() and not force:
            log(f"  {tile.name}: cached ({path.stat().st_size / 1e6:.1f} MB)")
        else:
            log(f"  {tile.name}: downloading…")
            path.write_bytes(_get(tile.url, log=log))
            log(f"  {tile.name}: {path.stat().st_size / 1e6:.1f} MB")
        paths[tile.name] = path
    return paths


class HeightModel:
    """A normalised surface model — metres of object above bare earth.

    Tiles are mosaicked into one array on a common grid. The frame is a few
    thousand pixels a side at 2 m, so holding it in memory costs tens of MB and
    saves per-building tile lookups.
    """

    def __init__(self, ndsm: np.ndarray, left: float, top: float, scale: float):
        self.ndsm = ndsm
        self.left = left
        self.top = top
        self.scale = scale

    @classmethod
    def from_tiles(cls, tiles: list[Tile], paths: dict[str, Path], *,
                   log=print) -> "HeightModel":
        scale = min(t.resolution for t in tiles)
        left = min(t.left for t in tiles)
        right = max(t.right for t in tiles)
        bottom = min(t.bottom for t in tiles)
        top = max(t.top for t in tiles)

        width = int(round((right - left) / scale))
        height = int(round((top - bottom) / scale))
        # NaN means "no reading here", which propagates through the percentiles
        # as an excluded sample rather than as a fake zero-height roof.
        ndsm = np.full((height, width), np.nan, dtype=np.float32)
        log(f"  mosaic {width} x {height} px at {scale:g} m "
            f"({ndsm.nbytes / 1e6:.0f} MB)")

        for tile in tiles:
            with zipfile.ZipFile(paths[tile.name]) as zf:
                names = {n.upper(): n for n in zf.namelist()}
                dsm_name = next((v for k, v in names.items() if k.endswith("DSM.TIF")), None)
                dtm_name = next((v for k, v in names.items() if k.endswith("DTM.TIF")), None)
                if not dsm_name or not dtm_name:
                    log(f"  {tile.name}: no DSM/DTM pair in zip, skipped")
                    continue
                dsm, t_left, t_top, t_scale, dsm_nd = _read_geotiff(zf.read(dsm_name))
                dtm, _, _, _, dtm_nd = _read_geotiff(zf.read(dtm_name))

            if t_scale != scale or dsm.shape != dtm.shape:
                log(f"  {tile.name}: unexpected grid ({t_scale} m, {dsm.shape}), skipped")
                continue

            valid = (dsm != dsm_nd) & (dtm != dtm_nd)
            patch = np.where(valid, dsm - dtm, np.nan).astype(np.float32)

            col = int(round((t_left - left) / scale))
            row = int(round((top - t_top) / scale))
            ndsm[row:row + patch.shape[0], col:col + patch.shape[1]] = patch

        covered = float(np.isfinite(ndsm).mean())
        log(f"  {covered * 100:.1f}% of the mosaic has a reading")
        return cls(ndsm, left, top, scale)

    def sample(self, polygon: Polygon, *, erode_m: float, min_height_m: float,
               roof_pct: float, ridge_pct: float, min_pixels: int) -> Height | None:
        """Roof and ridge height inside one footprint, or None if unreadable.

        Erosion is available but defaults to off. Edge pixels do straddle wall
        and pavement, but they only ever read low, so the high percentiles used
        here already ignore them — and shrinking a three-pixel terrace costs
        more samples than the contamination does.
        """
        shape = polygon
        if erode_m > 0:
            eroded = polygon.buffer(-erode_m)
            if not eroded.is_empty and eroded.area > 0:
                shape = eroded

        minx, miny, maxx, maxy = shape.bounds
        col0 = int(np.floor((minx - self.left) / self.scale))
        col1 = int(np.ceil((maxx - self.left) / self.scale))
        row0 = int(np.floor((self.top - maxy) / self.scale))
        row1 = int(np.ceil((self.top - miny) / self.scale))

        height, width = self.ndsm.shape
        col0, col1 = max(0, col0), min(width, col1 + 1)
        row0, row1 = max(0, row0), min(height, row1 + 1)
        if col0 >= col1 or row0 >= row1:
            return None

        # Pixel centres, so a sample represents the ground it actually covers.
        xs = self.left + (np.arange(col0, col1) + 0.5) * self.scale
        ys = self.top - (np.arange(row0, row1) + 0.5) * self.scale
        grid_x, grid_y = np.meshgrid(xs, ys)

        inside = shapely.contains_xy(shape, grid_x, grid_y)
        if not inside.any():
            # Buildings smaller than a pixel still deserve an answer: take the
            # single pixel covering the centroid.
            centre = shape.representative_point()
            col = int((centre.x - self.left) / self.scale)
            row = int((self.top - centre.y) / self.scale)
            if not (0 <= row < height and 0 <= col < width):
                return None
            values = self.ndsm[row:row + 1, col:col + 1].ravel()
        else:
            values = self.ndsm[row0:row1, col0:col1][inside]

        values = values[np.isfinite(values)]
        # Pixels near the ground are pavement bleed, a demolished building, or
        # one built after the survey — none of them describe a wall.
        values = values[values >= min_height_m]
        if values.size < min_pixels:
            return None

        return Height(
            roof_m=float(np.percentile(values, roof_pct)),
            ridge_m=float(np.percentile(values, ridge_pct)),
            pixels=int(values.size),
        )


def measure(buildings, model: HeightModel, config: dict, *, log=print) -> dict[str, Height]:
    """Sample every footprint. Returns {osm_id: Height} for those that read."""
    cfg = config["lidar"]
    erode_m = float(cfg.get("erode_m", 0.0))
    min_height_m = float(cfg.get("min_height_m", 2.0))
    roof_pct = float(cfg.get("roof_percentile", 85.0))
    ridge_pct = float(cfg.get("ridge_percentile", 97.0))
    min_pixels = int(cfg.get("min_pixels", 1))

    heights: dict[str, Height] = {}
    for i, building in enumerate(buildings):
        if i and i % 5000 == 0:
            log(f"    {i}/{len(buildings)} sampled")
        result = model.sample(
            building.geom,
            erode_m=erode_m,
            min_height_m=min_height_m,
            roof_pct=roof_pct,
            ridge_pct=ridge_pct,
            min_pixels=min_pixels,
        )
        if result is not None:
            heights[building.osm_id] = result
    return heights


def calibrate(buildings, heights: dict[str, Height], config: dict, *,
              log=print) -> Calibration | None:
    """Fit `roof_m = storey_m * levels + pitch_m` on the buildings OSM tagged.

    Tagged buildings are the only ground truth there is. They are also biased —
    mappers tag the tall and the notable — so the fit is restricted to the
    ordinary range where the samples are dense, and towers are left to be
    predicted rather than allowed to lever the line.
    """
    cfg = config["lidar"]
    max_levels = float(cfg.get("calibration_max_levels", 6.0))
    min_samples = int(cfg.get("calibration_min_samples", 100))

    xs, ys = [], []
    for building in buildings:
        height = heights.get(building.osm_id)
        if height is None or not building.levels_tagged:
            continue
        if not 0 < building.levels <= max_levels:
            continue
        xs.append(float(building.levels))
        ys.append(height.roof_m)

    if len(xs) < min_samples:
        log(f"  only {len(xs)} tagged buildings read — too few to calibrate; "
            f"falling back to configured storey height")
        return None

    x = np.asarray(xs)
    y = np.asarray(ys)
    slope, intercept = np.polyfit(x, y, 1)
    correlation = float(np.corrcoef(x, y)[0, 1])

    # A negative or tiny slope would mean the fit found no relation at all;
    # inverting it would turn every building into nonsense.
    if slope < 1.0:
        log(f"  calibration slope {slope:.2f} m/storey is not credible; "
            f"falling back to configured storey height")
        return None

    return Calibration(storey_m=float(slope), pitch_m=float(intercept),
                       samples=len(xs), correlation=correlation)


def heights_path(cache_dir: Path) -> Path:
    return cache_dir / "lidar" / "heights.json.gz"


def save_heights(survey: Survey, config: dict, tiles: list[Tile],
                 cache_dir: Path) -> Path:
    """Write the derived heights, which are what the pipeline actually reads.

    The rasters themselves are 54 MB and stay out of the repo; this file is the
    reproducible artefact, in the same spirit as the committed OSM snapshot.
    The tile manifest travels with it so the rasters can be fetched again.
    """
    path = heights_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "attribution": config["lidar"]["attribution"],
        "source": config["lidar"]["service"],
        "tiles": [asdict(t) for t in tiles],
        "settings": {k: v for k, v in config["lidar"].items()
                     if k not in ("service", "attribution", "srid")},
        "calibration": asdict(survey.calibration) if survey.calibration else None,
        "heights": {k: [round(v.roof_m, 2), round(v.ridge_m, 2), v.pixels]
                    for k, v in survey.heights.items()},
    }
    with gzip.open(path, "wt") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return path


def load_survey(cache_dir: Path) -> Survey:
    """Read the cached survey, or an empty one when the stage has not run."""
    path = heights_path(cache_dir)
    if not path.exists():
        return Survey(heights={}, calibration=None)
    with gzip.open(path, "rt") as fh:
        payload = json.load(fh)
    calibration = payload.get("calibration")
    return Survey(
        heights={k: Height(roof_m=v[0], ridge_m=v[1], pixels=v[2])
                 for k, v in payload["heights"].items()},
        calibration=Calibration(**calibration) if calibration else None,
    )
