"""Drawing the charm layer — trees, boats, swans.

`decorate.py` decides where a prop stands; this draws it, in the same lighting
the buildings obey: light from the upper left, so a canopy is pale on its
left shoulder and deep on its lower right.

Props are the smallest things on the canvas, often a dozen pixels, and small
pixel art fails in a specific way — detail below a couple of pixels turns to
mush and reads as noise. So each sprite is drawn from a handful of large
shapes and simply stops drawing the parts that no longer fit: below a threshold
a tree is a canopy and a stub, and below that it is not drawn at all. That is
better than a grey smudge where a tree should be.
"""

from __future__ import annotations

import math

from PIL import ImageDraw

from .decorate import Prop
from .draw3d import metre_px, rng, shade
from .iso import CELL_H, CELL_W, Camera
from .style import Style

#: Below this canopy width in pixels a tree is noise, not a tree.
MIN_TREE_PX = 3.0
#: Height of the canopy's centre as a fraction of the tree's full height.
CANOPY_CENTRE = 0.62
#: Below this a boat cannot show a cabin, and below half of it, nothing at all.
MIN_BOAT_PX = 5.0


def ground_px_per_m(camera: Camera) -> float:
    """Screen pixels per metre measured across the ground plane.

    A ground metre is not a height metre: the isometric compresses the ground
    and leaves height alone, so the two scales differ and a prop drawn with the
    wrong one is the wrong shape.
    """
    return 2 * CELL_W / (math.sqrt(2) * camera.cell_m)


def draw_tree(draw: ImageDraw.ImageDraw, camera: Camera, prop: Prop,
              style: Style, seed: int) -> bool:
    """A trunk and a canopy, lit from the upper left."""
    ox, oy = camera.ground(prop.x, prop.y)
    lift = prop.height_m * metre_px(camera)
    ground_scale = ground_px_per_m(camera)

    # Canopy radius follows the tree's height, the way a real one does.
    radius_m = prop.height_m * (0.36 + 0.10 * rng(f"{prop.x:.1f},{prop.y:.1f}", seed, "r"))
    rx = radius_m * ground_scale
    if rx * 2 < MIN_TREE_PX:
        return False
    # Foliage is a ball, so its vertical radius is the height scale, not the
    # squashed ground one — otherwise every tree looks run over.
    ry = radius_m * metre_px(camera)

    base = style.canopy[prop.variant % len(style.canopy)]
    # The crown sits at about two thirds of the tree's height, not on top of it.
    # Hanging the canopy off the very top leaves a bare pole underneath and the
    # whole park turns into lollipops.
    crown_y = oy - lift * CANOPY_CENTRE

    trunk_w = max(1.0, rx * 0.26)
    if lift > ry:
        draw.rectangle([ox - trunk_w / 2, crown_y, ox + trunk_w / 2, oy],
                       fill=style.trunk)

    draw.ellipse([ox - rx, crown_y - ry, ox + rx, crown_y + ry * 0.75], fill=base)
    if rx >= 3.0:
        # A smaller, brighter ellipse offset up and left is all the modelling a
        # canopy this size can carry.
        hx, hy = rx * 0.55, ry * 0.55
        cx, cy = ox - rx * 0.30, crown_y - ry * 0.28
        draw.ellipse([cx - hx, cy - hy, cx + hx, cy + hy], fill=shade(base, 1.18))
    if style.outline_px and rx >= 4.0:
        draw.ellipse([ox - rx, crown_y - ry, ox + rx, crown_y + ry * 0.75],
                     outline=shade(base, 0.62))
    return True


def draw_boat(draw: ImageDraw.ImageDraw, camera: Camera, prop: Prop,
              style: Style, seed: int) -> bool:
    """A hull on the water, pointing along the channel."""
    scale = ground_px_per_m(camera)
    length_px = prop.height_m * scale
    if length_px < MIN_BOAT_PX * 0.5:
        return False

    ox, oy = camera.ground(prop.x, prop.y)
    beam_m = prop.height_m * 0.30
    angle = math.radians(prop.angle_deg)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    mpx = metre_px(camera)

    def point(lx: float, ly: float, up: float = 0.0):
        """Boat-local metres to screen, so the hull turns with the river."""
        wx = prop.x + lx * cos_a - ly * sin_a
        wy = prop.y + lx * sin_a + ly * cos_a
        sx, sy = camera.ground(wx, wy)
        return sx, sy - up * mpx

    half_l, half_b = prop.height_m / 2, beam_m / 2
    outline = [(-half_l, -half_b), (half_l * 0.72, -half_b),
               (half_l, 0.0), (half_l * 0.72, half_b), (-half_l, half_b)]

    # Waterline first, then the deck lifted a freeboard above it. The strip of
    # the darker shape still showing underneath is the hull side — the same
    # trick the buildings use, and the reason a boat reads as a boat rather
    # than as a plank floating on the river.
    freeboard = max(0.5, prop.height_m * 0.11)
    draw.polygon([point(x, y) for x, y in outline], fill=shade(style.hull, 0.72))
    draw.polygon([point(x, y, freeboard) for x, y in outline], fill=style.hull)

    if length_px >= MIN_BOAT_PX:
        # A cabin set aft of centre, small enough to leave working deck.
        cabin = [(-half_l * 0.45, -half_b * 0.55), (half_l * 0.10, -half_b * 0.55),
                 (half_l * 0.10, half_b * 0.55), (-half_l * 0.45, half_b * 0.55)]
        roof = freeboard + max(0.7, prop.height_m * 0.16)
        draw.polygon([point(x, y, freeboard) for x, y in cabin],
                     fill=shade(style.hull_light, 0.74))
        draw.polygon([point(x, y, roof) for x, y in cabin], fill=style.hull_light)
        if prop.variant == 0 and length_px >= MIN_BOAT_PX * 1.6:
            mast = prop.height_m * 0.95
            draw.line([point(half_l * 0.25, 0.0, freeboard),
                       point(half_l * 0.25, 0.0, mast)],
                      fill=style.hull_light, width=1)
    return True


def draw_swan(draw: ImageDraw.ImageDraw, camera: Camera, prop: Prop,
              style: Style, seed: int) -> bool:
    """Two pixels of white and a neck, which is all a swan needs to read."""
    scale = ground_px_per_m(camera)
    body = max(1.0, 1.5 * scale)
    if body < 1.0:
        return False
    ox, oy = camera.ground(prop.x, prop.y)
    draw.ellipse([ox - body, oy - body * 0.5, ox + body, oy + body * 0.5],
                 fill=style.swan)
    if body >= 2.0:
        neck = body * 1.5
        draw.line([(ox + body * 0.4, oy - body * 0.2),
                   (ox + body * 0.6, oy - neck)], fill=style.swan, width=1)
    return True


DRAW = {"tree": draw_tree, "boat": draw_boat, "swan": draw_swan}


def draw_prop(draw: ImageDraw.ImageDraw, camera: Camera, prop: Prop,
              style: Style, seed: int) -> bool:
    """Draw one prop. Returns whether it was big enough to be worth drawing."""
    painter = DRAW.get(prop.kind)
    if painter is None:
        return False
    return painter(draw, camera, prop, style, seed)
