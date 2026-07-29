"""Analysis figures for the composition gate.

These are diagnostic charts, not artwork, so unlike everything else in this
project they are drawn anti-aliased: rendered at 3x and downsampled.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SS = 3  # supersample factor
INK = (28, 32, 36)
MUTED = (120, 128, 132)
GRID = (214, 216, 210)
ACCENT = (46, 125, 131)
ACCENT_SOFT = (46, 125, 131, 70)
BRICK = (166, 64, 45)
PAPER = (250, 250, 246)

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    path = _FONT_PATHS[1] if bold else _FONT_PATHS[0]
    try:
        return ImageFont.truetype(path, size * SS)
    except OSError:
        return ImageFont.load_default()


def rose_figure(
    counts: list[float],
    fit,
    profile: list[tuple[float, float]],
    *,
    title: str,
    subtitle: str,
    path: Path,
) -> Path:
    """Polar bearing histogram beside the axis-alignment profile."""
    W, H = 1180, 620
    img = Image.new("RGB", (W * SS, H * SS), PAPER)
    draw = ImageDraw.Draw(img, "RGBA")

    draw.text((40 * SS, 26 * SS), title, font=_font(20, bold=True), fill=INK)
    draw.text((40 * SS, 54 * SS), subtitle, font=_font(12), fill=MUTED)

    # ---- rose ------------------------------------------------------------
    cx, cy, radius = 300 * SS, 350 * SS, 210 * SS
    peak = max(counts) or 1.0

    for frac in (0.25, 0.5, 0.75, 1.0):
        r = radius * frac
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GRID, width=1 * SS)

    bins = len(counts)
    width_deg = 360.0 / bins
    for i, count in enumerate(counts):
        if count <= 0:
            continue
        r = radius * (count / peak)
        # Bearings are clockwise from north; pieslice angles are clockwise from
        # east, hence the -90 turn.
        start = i * width_deg - width_deg / 2 - 90
        draw.pieslice(
            [cx - r, cy - r, cx + r, cy + r],
            start, start + width_deg,
            fill=ACCENT_SOFT, outline=ACCENT, width=1 * SS,
        )

    for label, angle in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
        rad = math.radians(angle - 90)
        lx = cx + (radius + 22 * SS) * math.cos(rad)
        ly = cy + (radius + 22 * SS) * math.sin(rad)
        draw.text((lx, ly), label, font=_font(12, bold=True), fill=MUTED, anchor="mm")

    # The fitted grid: four spokes at the dominant angle.
    for k in range(4):
        rad = math.radians(fit.grid_angle_deg + 90 * k - 90)
        draw.line(
            [cx, cy, cx + radius * 1.04 * math.cos(rad), cy + radius * 1.04 * math.sin(rad)],
            fill=BRICK, width=2 * SS,
        )
    draw.text(
        (cx, cy + radius + 46 * SS),
        f"dominant grid  {fit.grid_angle_deg:.1f}°   ·   strength {fit.strength:.2f}"
        f"   ·   entropy {fit.entropy:.2f} bits",
        font=_font(11), fill=INK, anchor="mm",
    )

    # ---- alignment profile ----------------------------------------------
    px0, py0 = 640 * SS, 130 * SS
    pw, ph = 480 * SS, 380 * SS
    draw.rectangle([px0, py0, px0 + pw, py0 + ph], outline=GRID, width=1 * SS)
    draw.text((px0, py0 - 30 * SS), "Street length rendering as clean pixel lines",
              font=_font(13, bold=True), fill=INK)
    draw.text((px0, py0 - 12 * SS), "share within 5° of an isometric axis, by map rotation",
              font=_font(10), fill=MUTED)

    best_rot, best_share = max(profile, key=lambda p: p[1])
    top = max(0.6, min(1.0, best_share * 1.25))

    for frac in (0.25, 0.5, 0.75, 1.0):
        y = py0 + ph - ph * frac
        draw.line([px0, y, px0 + pw, y], fill=GRID, width=1 * SS)
        draw.text((px0 - 8 * SS, y), f"{top * frac * 100:.0f}%", font=_font(9),
                  fill=MUTED, anchor="rm")

    points = [
        (px0 + pw * (rot / 90.0), py0 + ph - ph * min(share / top, 1.0))
        for rot, share in profile
    ]
    draw.line(points, fill=ACCENT, width=2 * SS, joint="curve")

    bx = px0 + pw * (best_rot / 90.0)
    draw.line([bx, py0, bx, py0 + ph], fill=BRICK, width=2 * SS)
    draw.text((bx + 6 * SS, py0 + 8 * SS),
              f"best +{best_rot:.1f}°  ({best_share * 100:.0f}%)",
              font=_font(11, bold=True), fill=BRICK)

    for tick in (0, 15, 30, 45, 60, 75, 90):
        x = px0 + pw * (tick / 90.0)
        draw.line([x, py0 + ph, x, py0 + ph + 6 * SS], fill=MUTED, width=1 * SS)
        draw.text((x, py0 + ph + 20 * SS), f"{tick}°", font=_font(9), fill=MUTED, anchor="mm")
    draw.text((px0 + pw / 2, py0 + ph + 46 * SS), "map rotation applied",
              font=_font(10), fill=MUTED, anchor="mm")

    path.parent.mkdir(parents=True, exist_ok=True)
    img.resize((W, H), Image.LANCZOS).save(path)
    return path


def contact_sheet(entries: list[tuple[str, Path]], path: Path, *, columns: int = 2) -> Path:
    """Label and tile candidate renders so configs can be compared side by side."""
    if not entries:
        raise ValueError("nothing to contact-sheet")

    thumbs = [(label, Image.open(p).convert("RGB")) for label, p in entries]
    tw = 900
    scaled = [
        (label, im.resize((tw, max(1, round(im.height * tw / im.width))), Image.LANCZOS))
        for label, im in thumbs
    ]
    cell_h = max(im.height for _, im in scaled)
    pad, header = 24, 34
    rows = math.ceil(len(scaled) / columns)
    W = columns * tw + (columns + 1) * pad
    H = rows * (cell_h + header) + (rows + 1) * pad

    sheet = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(_FONT_PATHS[1], 20) if Path(_FONT_PATHS[1]).exists() else ImageFont.load_default()

    for i, (label, im) in enumerate(scaled):
        col, row = i % columns, i // columns
        x = pad + col * (tw + pad)
        y = pad + row * (cell_h + header + pad)
        draw.text((x, y), label, font=font, fill=INK)
        sheet.paste(im, (x, y + header))

    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path
