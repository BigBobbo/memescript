"""City configuration loading and path conventions."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# pixelmap/pixelmap/config.py -> pixelmap/
ROOT = Path(__file__).resolve().parent.parent
CITIES = ROOT / "cities"


@dataclass(frozen=True)
class City:
    slug: str
    config: dict
    dir: Path

    @property
    def cache(self) -> Path:
        return self.dir / "cache"

    @property
    def out(self) -> Path:
        return self.dir / "out"

    @property
    def analysis(self) -> Path:
        return self.dir / "analysis"

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(south, west, north, east) in WGS84."""
        b = self.config["bbox"]
        return (b["south"], b["west"], b["north"], b["east"])

    @property
    def crs(self) -> str:
        return self.config["city"]["crs"]

    @property
    def rotation_deg(self) -> float:
        return float(self.config["projection"]["rotation_deg"])

    @property
    def cell_m(self) -> float:
        return float(self.config["grid"]["cell_m"])

    @property
    def seed(self) -> int:
        return int(self.config["city"]["seed"])


def load_city(slug: str) -> City:
    city_dir = CITIES / slug
    config_path = city_dir / "city.toml"
    if not config_path.exists():
        available = sorted(p.name for p in CITIES.iterdir() if p.is_dir()) if CITIES.exists() else []
        raise FileNotFoundError(
            f"No city config at {config_path}. Available: {', '.join(available) or 'none'}"
        )
    with config_path.open("rb") as fh:
        config = tomllib.load(fh)
    return City(slug=slug, config=config, dir=city_dir)
