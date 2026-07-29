"""Drawing landmark masses.

`landmarks.py` decides what a landmark is made of; this draws it. The split is
deliberate — deciding that a castle is "walls plus drum towers, crenellated" is
geometry reasoning, while crenellating a ring is pixel reasoning, and the two
change for different reasons.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .draw3d import (
    arc_positions, metre_px, prism, pyramid, ridge_roof, ring_span, shade, wall_rect,
)
from .iso import STOREY_M, Camera
from .landmarks import Mass
from .style import Style, material_for

#: Crenellation proportions. Merlons wider than the gaps between them, which is
#: what a real parapet looks like and what stops the top reading as a comb.
MERLON_M = 1.8
EMBRASURE_M = 1.1

#: Below this, detail is finer than the pixels can hold and only adds noise.
MIN_DETAIL_PX = 3.0


#: Bay spacing and opening width for each vocabulary, in metres of wall.
_OPENINGS = {
    #: A castle shows almost nothing: narrow slits, widely spaced, set high.
    "slit": dict(pitch=5.0, width=0.55, v0=0.40, v1=0.76, levels=1, head=0.0),
    #: Cathedral bays: tall, pointed, and continuous round the building.
    "lancet": dict(pitch=4.2, width=1.5, v0=0.22, v1=0.62, levels=1, head=0.09),
    "arcade": dict(pitch=4.0, width=2.4, v0=0.06, v1=0.50, levels=1, head=0.0),
    #: Georgian civic: a regular grid of sashes over four floors.
    "sash": dict(pitch=3.4, width=1.4, v0=0.26, v1=0.78, levels="storeys", head=0.0),
    #: A modern tower reads by its horizontal banding, so the "opening" is
    #: nearly the whole floor: one glazed strip per storey, wall to wall.
    "curtain": dict(pitch=2.0, width=1.8, v0=0.14, v1=0.80, levels="storeys", head=0.0),
}

def _openings(draw, a, b, height_px, length_m, sunlit, along_m, kind, glass,
              height_m: float) -> bool:
    """Whatever punctuates one wall face of a landmark.

    Landmarks get their own vocabulary rather than the domestic sash grid: a
    castle has arrow slits, a cathedral has lancets, a train shed a clerestory
    band. Reusing house windows on all three made them read as big houses with
    interesting roofs.

    Bays are spaced along the ring by arc length, not per polygon edge — the
    footprints these run on are surveyed outlines, and a drum tower is two dozen
    edges of a metre each.
    """
    width_px = math.hypot(b[0] - a[0], b[1] - a[1])
    if kind == "none" or width_px < 8 or height_px < 8 or length_m <= 0:
        return False
    if not sunlit:
        glass = shade(glass, 0.86)

    if kind == "clerestory":
        # One continuous glazed band, so nothing to space out.
        draw.polygon(wall_rect(a, b, height_px, 0.03, 0.97, 0.56, 0.90), fill=glass)
        draw.polygon(wall_rect(a, b, height_px, 0.03, 0.97, 0.10, 0.42),
                     fill=shade(glass, 0.90))
        return True

    spec = _OPENINGS.get(kind)
    if spec is None:
        return False
    px_per_m = width_px / length_m
    if spec["width"] * px_per_m < MIN_DETAIL_PX:
        return False

    half = spec["width"] / 2 / length_m          # in wall-fraction units
    levels = spec["levels"]
    if levels == "storeys":
        # Rows come from the building's real height, not from its pixels, so a
        # tower does not grow extra floors when the render is zoomed in.
        levels = max(1, min(24, int(round(height_m / STOREY_M))))
        if height_px / levels < MIN_DETAIL_PX + 1:
            return False
    fill = shade(glass, 0.66) if kind == "slit" else glass

    # Which bay centres, spaced every `pitch` metres round the whole ring, land
    # on this particular wall.
    first = math.ceil((along_m - spec["pitch"] / 2) / spec["pitch"])
    drawn = False
    for k in range(first, first + int(length_m / spec["pitch"]) + 2):
        u = (k * spec["pitch"] + spec["pitch"] / 2 - along_m) / length_m
        if not (0.0 <= u - half and u + half <= 1.0):
            continue
        for level in range(levels):
            v0 = (level + spec["v0"]) / levels
            v1 = (level + spec["v1"]) / levels
            draw.polygon(wall_rect(a, b, height_px, u - half, u + half, v0, v1),
                         fill=fill)
            if spec["head"]:
                head = wall_rect(a, b, height_px, u - half, u + half, v1, v1)
                apex = ((head[0][0] + head[1][0]) / 2,
                        (head[0][1] + head[1][1]) / 2 - height_px * spec["head"])
                draw.polygon([head[0], head[1], apex], fill=fill)
        drawn = True
    return drawn


def _battlement(draw, top_ring, ring_world, rise_px, left, right, outline) -> None:
    """Crenellate a wall head: merlons up, embrasures left open.

    Merlons are spaced by arc length round the whole ring, so a drum tower gets
    a dozen of them rather than one per surveyed vertex, and one that straddles
    a corner turns the corner with it.
    """
    pitch, phase = arc_positions(ring_world, MERLON_M + EMBRASURE_M)
    perimeter = sum(math.dist(ring_world[i], ring_world[i + 1])
                    for i in range(len(ring_world) - 1))
    if perimeter <= 0 or pitch <= 0:
        return

    faces = []
    s = phase
    while s < perimeter:
        span = ring_span(top_ring, ring_world, s - MERLON_M / 2, s + MERLON_M / 2)
        s += pitch
        if len(span) < 2 or math.dist(span[0], span[-1]) < MIN_DETAIL_PX:
            continue
        # A merlon is the strip of wall between two arc positions, raised.
        quad = span + [(x, y - rise_px) for x, y in reversed(span)]
        lit = left if (span[-1][0] - span[0][0]) < 0 else right
        faces.append((sum(p[1] for p in span) / len(span), quad, lit))
    for _, quad, colour in sorted(faces, key=lambda f: f[0]):
        draw.polygon(quad, fill=colour, outline=outline)


def _posts(draw, camera, ring_world, height_px, left, right, outline) -> None:
    """Support columns under an open canopy, every few metres of perimeter."""
    width = max(2.0, 0.55 * metre_px(camera))
    posts = []
    for i in range(len(ring_world) - 1):
        ax, ay = ring_world[i]
        bx, by = ring_world[i + 1]
        count = max(1, int(math.dist((ax, ay), (bx, by)) // 6.0))
        for k in range(count):
            t = k / count
            posts.append(camera.ground(ax + (bx - ax) * t, ay + (by - ay) * t))
    del left  # a post is a couple of pixels wide; two-tone shading is noise
    for px, py in sorted(posts, key=lambda p: p[1]):
        draw.polygon([(px - width / 2, py), (px + width / 2, py),
                      (px + width / 2, py - height_px), (px - width / 2, py - height_px)],
                     fill=right, outline=outline)


def _fill_with_holes(img, camera, poly, lift_px: float, colour) -> None:
    """Fill a polygon at a given height, honouring its holes.

    Pillow cannot fill a ring with a hole in it, so the shape is stencilled into
    a mask first. The mask is cropped to the polygon's own bounds — over a
    quarter-billion-pixel canvas, a full-size mask per landmark is not free.
    """
    pts = [(x, y - lift_px) for x, y in
           (camera.ground(cx, cy) for cx, cy in poly.exterior.coords)]
    if len(pts) < 3:
        return
    x0 = max(0, int(min(p[0] for p in pts)) - 2)
    y0 = max(0, int(min(p[1] for p in pts)) - 2)
    x1 = min(img.width, int(max(p[0] for p in pts)) + 2)
    y1 = min(img.height, int(max(p[1] for p in pts)) + 2)
    if x1 <= x0 or y1 <= y0:
        return

    mask = Image.new("1", (x1 - x0, y1 - y0), 0)
    stencil = ImageDraw.Draw(mask)
    stencil.polygon([(x - x0, y - y0) for x, y in pts], fill=1)
    for ring in poly.interiors:
        hole = [(x - x0, y - y0 - lift_px) for x, y in
                (camera.ground(cx, cy) for cx, cy in ring.coords)]
        if len(hole) >= 3:
            stencil.polygon(hole, fill=0)
    img.paste(colour, (x0, y0), mask=mask)


def _obb_px(camera: Camera, poly, lift_px: float):
    """The footprint's oriented box, projected and lifted — a roof needs four
    corners, and a surveyed outline rarely has exactly four."""
    box = poly.minimum_rotated_rectangle
    if box.geom_type != "Polygon":
        return None
    return [(x, y - lift_px)
            for x, y in (camera.ground(cx, cy) for cx, cy in list(box.exterior.coords)[:4])]


def draw_mass(draw, img, camera: Camera, mass: Mass, style: Style, stats=None) -> None:
    """Draw one extruded chunk of a landmark, roof feature included."""
    ring = list(mass.poly.exterior.coords)
    if len(ring) < 4:
        return
    mat = material_for(style, mass.material)
    roof_mat = material_for(style, mass.roof_material or mass.material)
    outline = style.outline if style.outline_px else None
    ppm = metre_px(camera)
    base_px, top_px, rise_px = mass.base_m * ppm, mass.top_m * ppm, mass.roof_m * ppm
    detailed = 0

    def face(a, b, height_px, length_m, sunlit, along_m):
        nonlocal detailed
        detailed += int(_openings(draw, a, b, height_px, length_m, sunlit,
                                  along_m, mass.openings, style.window,
                                  mass.top_m - mass.base_m))

    if mass.roof == "open":
        # A canopy has no walls: posts, then the roof floating over them. The
        # `building=roof` tag means exactly that, and extruding it like a shed
        # turns an open market into a warehouse.
        _posts(draw, camera, ring, top_px, mat.left, mat.right, outline)
        corners = _obb_px(camera, mass.poly, top_px)
        if corners:
            ridge_roof(draw, corners, rise_px, roof_mat.roof, outline)
        else:
            draw.polygon([(x, y - top_px) for x, y in
                          (camera.ground(cx, cy) for cx, cy in ring)],
                         fill=roof_mat.roof, outline=outline)
        if stats is not None:
            stats.landmark_masses += 1
        return

    # A walled enclosure is drawn from the inside out: courtyard floor, then the
    # inner faces (of which only the far ones survive), then the outer wall over
    # the top of the near ones.
    for hole in mass.poly.interiors:
        court = [camera.ground(x, y) for x, y in hole.coords]
        if len(court) >= 3:
            draw.polygon(court, fill=style.court, outline=outline)
        prism(draw, camera, list(hole.coords), base_px, top_px,
              shade(mat.right, 0.92), shade(mat.right, 0.84), outline)

    top = prism(draw, camera, ring, base_px, top_px,
                mat.left, mat.right, outline, face=face)
    if not top:
        return

    if mass.roof == "battlement":
        # Cap the wall head first — with holes, so a courtyard stays open.
        if mass.poly.interiors:
            _fill_with_holes(img, camera, mass.poly, top_px, shade(mat.roof, 0.94))
        else:
            draw.polygon(top, fill=shade(mat.roof, 0.94), outline=outline)
        _battlement(draw, top, ring, rise_px,
                    shade(mat.left, 1.02), shade(mat.right, 0.98), outline)
        for hole in mass.poly.interiors:
            _battlement(draw, [(x, y - top_px) for x, y in
                               (camera.ground(cx, cy) for cx, cy in hole.coords)],
                        list(hole.coords), rise_px,
                        shade(mat.left, 0.96), shade(mat.right, 0.92), outline)
    elif mass.roof == "spire":
        draw.polygon(top, fill=shade(roof_mat.roof, 0.9), outline=outline)
        apex = pyramid(draw, top, rise_px, roof_mat.roof, outline)
        # A finial, so the tallest thing in the frame ends in a point rather
        # than in whatever the polygon rasteriser left behind.
        draw.line([apex, (apex[0], apex[1] - max(2.0, rise_px * 0.04))],
                  fill=outline or shade(roof_mat.roof, 0.6),
                  width=max(1, int(ppm * 0.5)))
    elif mass.roof == "cone":
        pyramid(draw, top, rise_px, roof_mat.roof, outline)
    elif mass.roof in ("gabled", "hipped"):
        box = mass.poly.minimum_rotated_rectangle
        corners = _obb_px(camera, mass.poly, top_px)
        if corners and box.area > 0 and mass.poly.area / box.area > 0.6:
            ridge_roof(draw, corners, rise_px, roof_mat.roof, outline,
                       hipped=0.5 if mass.roof == "hipped" else 0.0)
        else:
            draw.polygon(top, fill=roof_mat.roof, outline=outline)
    elif mass.poly.interiors:
        _fill_with_holes(img, camera, mass.poly, top_px, roof_mat.roof)
    else:
        draw.polygon(top, fill=roof_mat.roof, outline=outline)

    if stats is not None:
        stats.landmark_masses += 1
        stats.facades_detailed += detailed


def draw_landmark(draw, img, camera, masses, style, stats=None) -> None:
    """Draw a landmark's masses back to front, so a near tower sits over the
    wall behind it."""
    for mass in sorted(masses, key=lambda m: camera.ground(m.poly.centroid.x,
                                                           m.poly.centroid.y)[1]):
        draw_mass(draw, img, camera, mass, style, stats)
    if stats is not None:
        stats.landmarks += 1
