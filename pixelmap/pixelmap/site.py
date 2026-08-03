"""Stage 6 — compose to a zoomable web map.

A 26-megapixel PNG is not something a browser will open, and a 237-megapixel
one is not something it will survive. The fix is the same one every slippy map
uses: cut the render into a pyramid of small tiles, and let the viewer fetch
only the handful covering the screen at the zoom being looked at.

The pyramid is plain pixel space, not Web Mercator. The render is already an
isometric projection of the ground, so re-projecting it into a geographic tile
scheme would only add a second projection on top of the one that gives the
picture its character. Levels halve: the deepest is native resolution, each one
above it is a clean 2x box-filter reduction, and level 0 fits in a single tile.

Halving exactly matters. A box filter over an exact 2x2 block is the one
downscale that cannot introduce colours absent from the original, which keeps
a limited pixel-art palette intact all the way down the pyramid.

Landmark markers are placed by pushing their anchors through the same camera
that drew the frame, so a marker cannot drift from the building under it.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

TILE_PX = 256


@dataclass(frozen=True)
class Pyramid:
    """What the viewer needs to know about the tile set."""

    width: int
    height: int
    tile_px: int
    max_level: int
    tiles: int


def build_pyramid(image: Image.Image, out_dir: Path, *, tile_px: int = TILE_PX,
                  log=print) -> Pyramid:
    """Cut `image` into `out_dir/tiles/{z}/{x}_{y}.png`. Returns the manifest.

    Level `max_level` is native resolution; each level below is half the size,
    down to level 0, which fits inside one tile.
    """
    width, height = image.size
    # Number of halvings before the long edge fits a single tile.
    max_level = max(0, math.ceil(math.log2(max(width, height) / tile_px)))

    tiles_dir = out_dir / "tiles"
    if tiles_dir.exists():
        shutil.rmtree(tiles_dir)

    written = 0
    level_image = image
    for level in range(max_level, -1, -1):
        level_dir = tiles_dir / str(level)
        level_dir.mkdir(parents=True, exist_ok=True)
        w, h = level_image.size
        cols = math.ceil(w / tile_px)
        rows = math.ceil(h / tile_px)

        for row in range(rows):
            for col in range(cols):
                box = (col * tile_px, row * tile_px,
                       min((col + 1) * tile_px, w), min((row + 1) * tile_px, h))
                tile = level_image.crop(box)
                # Edge tiles are short; padding them keeps every tile the same
                # size so the viewer can place them by arithmetic alone.
                if tile.size != (tile_px, tile_px):
                    padded = Image.new("RGB", (tile_px, tile_px), (0, 0, 0))
                    padded.paste(tile, (0, 0))
                    tile = padded
                tile.save(level_dir / f"{col}_{row}.png", optimize=True)
                written += 1

        log(f"    z{level}: {cols}x{rows} tiles ({w}x{h} px)")
        if level:
            # Exact halving, rounded up so nothing is cropped away entirely.
            level_image = level_image.resize(
                (max(1, (w + 1) // 2), max(1, (h + 1) // 2)), Image.BOX)

    return Pyramid(width=width, height=height, tile_px=tile_px,
                   max_level=max_level, tiles=written)


def landmark_markers(city, camera, *, to_crs) -> list[dict]:
    """Landmark anchors as native-resolution pixel positions.

    Anchors outside the canvas are dropped rather than clamped: a marker pinned
    to the frame edge would claim a building that is not in shot.
    """
    import tomllib

    path = city.dir / "landmarks.toml"
    if not path.exists():
        return []
    with path.open("rb") as fh:
        config = tomllib.load(fh)

    excluded = set(city.config["frame"].get("exclude", []))
    markers = []
    for entry in config.get("landmark", []):
        if entry.get("name") in excluded or entry.get("short") in excluded:
            continue
        x, y = to_crs.transform(entry["lon"], entry["lat"])
        px, py = camera.ground(x, y)
        if not (0 <= px < camera.width_px and 0 <= py < camera.height_px):
            continue
        markers.append({
            "name": entry["name"],
            "short": entry.get("short", entry["name"]),
            "tier": int(entry.get("tier", 2)),
            "x": round(px, 1),
            "y": round(py, 1),
            "lat": entry["lat"],
            "lon": entry["lon"],
        })
    return sorted(markers, key=lambda m: (m["tier"], m["name"]))


def write_site(out_dir: Path, pyramid: Pyramid, markers: list[dict], *,
               city_name: str, subtitle: str, attribution: list[str],
               stats: list[tuple[str, str]]) -> Path:
    """Write data.json and the viewer itself."""
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "city": city_name,
        "subtitle": subtitle,
        "width": pyramid.width,
        "height": pyramid.height,
        "tile": pyramid.tile_px,
        "maxLevel": pyramid.max_level,
        "markers": markers,
        "attribution": attribution,
        "stats": [{"label": k, "value": v} for k, v in stats],
    }
    (out_dir / "data.json").write_text(json.dumps(data, indent=1))
    index = out_dir / "index.html"
    index.write_text(VIEWER_HTML.replace("__TITLE__", f"{city_name} — pixelmap"))
    return index


VIEWER_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>__TITLE__</title>
<!-- Inline so the page stays self-contained and the browser's automatic
     /favicon.ico request does not 404 against the tile server. -->
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' fill='%230d0f12'/%3E%3Cpath d='M2 9l6-3 6 3-6 3z' fill='%23f0c060'/%3E%3Cpath d='M2 9v2l6 3v-2z' fill='%23b8863a'/%3E%3Cpath d='M14 9v2l-6 3v-2z' fill='%238a6229'/%3E%3C/svg%3E">
<style>
  :root {
    --ink: #e8e6e1;
    --dim: #9a978f;
    --panel: rgba(18, 20, 24, 0.92);
    --edge: rgba(255, 255, 255, 0.14);
    --accent: #f0c060;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; height: 100%; overflow: hidden;
    background: #0d0f12; color: var(--ink);
    font: 13px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    -webkit-font-smoothing: antialiased;
  }
  #stage { position: fixed; inset: 0; cursor: grab; touch-action: none; }
  #stage.dragging { cursor: grabbing; }
  canvas { display: block; width: 100%; height: 100%; image-rendering: pixelated; }

  .panel {
    position: fixed; background: var(--panel); border: 1px solid var(--edge);
    border-radius: 8px; backdrop-filter: blur(8px); padding: 12px 14px;
  }
  #title { top: 14px; left: 14px; max-width: min(340px, calc(100vw - 28px)); }
  #title h1 { margin: 0; font-size: 15px; letter-spacing: 0.02em; }
  #title p { margin: 4px 0 0; color: var(--dim); font-size: 11px; }
  #stats { margin: 9px 0 0; padding: 9px 0 0; border-top: 1px solid var(--edge);
           display: grid; grid-template-columns: auto auto; gap: 2px 12px; font-size: 11px; }
  #stats dt { color: var(--dim); }
  #stats dd { margin: 0; text-align: right; }

  #controls { top: 14px; right: 14px; display: flex; gap: 6px; padding: 8px; }
  button {
    font: inherit; font-size: 12px; color: var(--ink); background: rgba(255,255,255,0.06);
    border: 1px solid var(--edge); border-radius: 5px; padding: 5px 10px; cursor: pointer;
  }
  button:hover { background: rgba(255,255,255,0.13); }
  button:active { transform: translateY(1px); }
  button[aria-pressed="true"] { background: var(--accent); color: #17140c; border-color: var(--accent); }

  #legend { bottom: 14px; left: 14px; max-width: min(420px, calc(100vw - 28px)); }
  #legend p { margin: 0; color: var(--dim); font-size: 10px; line-height: 1.6; }
  #legend .keys { color: var(--ink); }

  #readout { bottom: 14px; right: 14px; color: var(--dim); font-size: 10px; padding: 8px 11px; }

  .marker {
    position: fixed; transform: translate(-50%, -100%); pointer-events: auto;
    cursor: pointer; user-select: none; white-space: nowrap;
  }
  .marker .dot {
    width: 9px; height: 9px; margin: 0 auto; background: var(--accent);
    border: 1.5px solid #17140c; border-radius: 50%;
    box-shadow: 0 0 0 1.5px var(--accent), 0 2px 6px rgba(0,0,0,0.6);
  }
  .marker .label {
    margin-bottom: 4px; font-size: 10.5px; padding: 2px 6px; border-radius: 4px;
    background: var(--panel); border: 1px solid var(--edge);
  }
  .marker.tier2 .label { opacity: 0.75; }
  .marker.selected .label { background: var(--accent); color: #17140c; border-color: var(--accent); }
  .marker .stem { width: 1px; height: 8px; margin: 0 auto; background: var(--accent); opacity: 0.8; }

  #card { bottom: 14px; left: 50%; transform: translateX(-50%); min-width: 240px;
          max-width: min(380px, calc(100vw - 28px)); display: none; }
  #card.open { display: block; }
  #card h2 { margin: 0 0 3px; font-size: 14px; }
  #card p { margin: 0; color: var(--dim); font-size: 11px; }
  #card .close { position: absolute; top: 8px; right: 10px; color: var(--dim);
                 cursor: pointer; font-size: 15px; line-height: 1; }
  #card .close:hover { color: var(--ink); }

  @media (max-width: 620px) {
    #stats, #legend { display: none; }
    #title { max-width: calc(100vw - 120px); }
  }
</style>
</head>
<body>
<div id="stage"><canvas id="map"></canvas></div>
<div id="markers"></div>

<div class="panel" id="title">
  <h1 id="cityName">—</h1>
  <p id="citySub"></p>
  <dl id="stats"></dl>
</div>

<div class="panel" id="controls">
  <button id="zoomOut" title="Zoom out">−</button>
  <button id="zoomIn" title="Zoom in">+</button>
  <button id="fit" title="Fit the whole city">Fit</button>
  <button id="pins" aria-pressed="true" title="Toggle landmarks">Pins</button>
  <button id="share" title="Copy a link to this view">Share</button>
</div>

<div class="panel" id="legend">
  <p><span class="keys">drag</span> pan · <span class="keys">wheel</span> zoom ·
     <span class="keys">double-click</span> zoom in ·
     <span class="keys">arrows</span> pan · <span class="keys">+ −</span> zoom ·
     <span class="keys">0</span> fit</p>
  <p id="attribution" style="margin-top:6px"></p>
</div>

<div class="panel" id="readout">—</div>

<div class="panel" id="card">
  <span class="close" id="cardClose">×</span>
  <h2 id="cardName"></h2>
  <p id="cardMeta"></p>
</div>

<script>
(function () {
  "use strict";

  var canvas = document.getElementById("map");
  var ctx = canvas.getContext("2d", { alpha: false });
  var stage = document.getElementById("stage");
  var markerLayer = document.getElementById("markers");

  var D = null;                 // manifest from data.json
  var view = { x: 0, y: 0, scale: 1 };   // x,y = native-pixel point at canvas centre
  var cache = new Map();        // "z/x_y" -> Image
  var pending = new Map();
  var showPins = true;
  var selected = null;
  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  var minScale = 0.05, maxScale = 8;

  function resize() {
    var w = stage.clientWidth, h = stage.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false;
    draw();
  }

  function fitScale() {
    if (!D) return 1;
    return Math.min(stage.clientWidth / D.width, stage.clientHeight / D.height);
  }

  function fit() {
    view.scale = fitScale();
    view.x = D.width / 2;
    view.y = D.height / 2;
    clamp();
    draw();
  }

  function clamp() {
    // Keep at least a little of the map on screen at all times, and never let
    // the whole thing shrink below the fit scale — there is nothing out there.
    minScale = Math.min(fitScale(), 1) * 0.85;
    view.scale = Math.max(minScale, Math.min(maxScale, view.scale));
    var halfW = stage.clientWidth / (2 * view.scale);
    var halfH = stage.clientHeight / (2 * view.scale);
    if (D.width * view.scale <= stage.clientWidth) view.x = D.width / 2;
    else view.x = Math.max(halfW, Math.min(D.width - halfW, view.x));
    if (D.height * view.scale <= stage.clientHeight) view.y = D.height / 2;
    else view.y = Math.max(halfH, Math.min(D.height - halfH, view.y));
  }

  // Which pyramid level renders closest to 1 screen pixel per tile pixel.
  function levelFor(scale) {
    var z = D.maxLevel + Math.ceil(Math.log2(Math.max(scale, 1e-6)));
    return Math.max(0, Math.min(D.maxLevel, z));
  }

  function tileUrl(z, x, y) { return "tiles/" + z + "/" + x + "_" + y + ".png"; }

  function getTile(z, x, y) {
    var key = z + "/" + x + "_" + y;
    if (cache.has(key)) return cache.get(key);
    if (pending.has(key)) return null;
    var img = new Image();
    pending.set(key, img);
    img.onload = function () { cache.set(key, img); pending.delete(key); draw(); };
    img.onerror = function () { pending.delete(key); };
    img.src = tileUrl(z, x, y);
    return null;
  }

  function draw() {
    if (!D) return;
    var w = stage.clientWidth, h = stage.clientHeight;
    ctx.fillStyle = "#0d0f12";
    ctx.fillRect(0, 0, w, h);

    var z = levelFor(view.scale);
    var levelScale = Math.pow(2, z - D.maxLevel);   // native px -> level px
    var s = view.scale / levelScale;                // level px -> screen px
    var levelW = D.width * levelScale, levelH = D.height * levelScale;

    // Top-left of the viewport in level pixels.
    var originX = view.x * levelScale - w / (2 * s);
    var originY = view.y * levelScale - h / (2 * s);

    var cols = Math.ceil(levelW / D.tile), rows = Math.ceil(levelH / D.tile);
    var x0 = Math.max(0, Math.floor(originX / D.tile));
    var x1 = Math.min(cols - 1, Math.floor((originX + w / s) / D.tile));
    var y0 = Math.max(0, Math.floor(originY / D.tile));
    var y1 = Math.min(rows - 1, Math.floor((originY + h / s) / D.tile));

    for (var ty = y0; ty <= y1; ty++) {
      for (var tx = x0; tx <= x1; tx++) {
        var dx = (tx * D.tile - originX) * s;
        var dy = (ty * D.tile - originY) * s;
        var size = D.tile * s;
        var img = getTile(z, tx, ty);
        if (img) {
          ctx.drawImage(img, dx, dy, size, size);
        } else {
          // Nothing sharp yet — stretch the parent tile so panning never
          // exposes bare background.
          var pz = z - 1, drawn = false;
          while (pz >= 0 && !drawn) {
            var f = Math.pow(2, z - pz);
            var px = Math.floor(tx / f), py = Math.floor(ty / f);
            var parent = cache.get(pz + "/" + px + "_" + py);
            if (parent) {
              var sub = D.tile / f;
              ctx.drawImage(parent, (tx % f) * sub, (ty % f) * sub, sub, sub,
                            dx, dy, size, size);
              drawn = true;
            }
            pz--;
          }
        }
      }
    }
    placeMarkers();
    updateReadout();
  }

  function toScreen(nx, ny) {
    return {
      x: (nx - view.x) * view.scale + stage.clientWidth / 2,
      y: (ny - view.y) * view.scale + stage.clientHeight / 2
    };
  }

  var markerEls = [];
  function buildMarkers() {
    markerLayer.innerHTML = "";
    markerEls = D.markers.map(function (m) {
      var el = document.createElement("div");
      el.className = "marker" + (m.tier === 2 ? " tier2" : "");
      el.innerHTML = '<div class="label"></div><div class="stem"></div><div class="dot"></div>';
      el.querySelector(".label").textContent = m.short;
      el.addEventListener("click", function (e) { e.stopPropagation(); select(m); });
      markerLayer.appendChild(el);
      return el;
    });
  }

  function placeMarkers() {
    var pad = 60;
    for (var i = 0; i < D.markers.length; i++) {
      var m = D.markers[i], el = markerEls[i];
      if (!showPins) { el.style.display = "none"; continue; }
      var p = toScreen(m.x, m.y);
      var on = p.x > -pad && p.x < stage.clientWidth + pad &&
               p.y > -pad && p.y < stage.clientHeight + pad;
      // Tier 2 is detail: it earns its space only once zoomed in.
      if (m.tier === 2 && view.scale < 0.35) on = false;
      el.style.display = on ? "block" : "none";
      if (on) { el.style.left = p.x + "px"; el.style.top = p.y + "px"; }
      el.classList.toggle("selected", selected === m);
    }
  }

  function select(m) {
    selected = m;
    document.getElementById("cardName").textContent = m.name;
    document.getElementById("cardMeta").textContent =
      m.lat.toFixed(5) + ", " + m.lon.toFixed(5);
    document.getElementById("card").classList.add("open");
    placeMarkers();
    writeHash();
  }

  function deselect() {
    selected = null;
    document.getElementById("card").classList.remove("open");
    placeMarkers();
    writeHash();
  }

  function updateReadout() {
    document.getElementById("readout").textContent =
      "z" + levelFor(view.scale) + "/" + D.maxLevel +
      " · " + Math.round(view.scale * 100) + "%" +
      " · " + Math.round(view.x) + "," + Math.round(view.y);
  }

  // --- view state in the URL, so a view can be sent to someone -------------
  var hashLock = false;
  function writeHash() {
    hashLock = true;
    var parts = [Math.round(view.x), Math.round(view.y), view.scale.toFixed(4)];
    if (selected) parts.push(encodeURIComponent(selected.short));
    location.replace("#" + parts.join("/"));
    setTimeout(function () { hashLock = false; }, 0);
  }

  function readHash() {
    var raw = location.hash.replace(/^#/, "");
    if (!raw) return false;
    var p = raw.split("/");
    if (p.length < 3) return false;
    var x = parseFloat(p[0]), y = parseFloat(p[1]), s = parseFloat(p[2]);
    if (!isFinite(x) || !isFinite(y) || !isFinite(s)) return false;
    view.x = x; view.y = y; view.scale = s;
    clamp();
    if (p[3]) {
      var want = decodeURIComponent(p[3]);
      var found = D.markers.filter(function (m) { return m.short === want; })[0];
      if (found) select(found);
    }
    return true;
  }

  // --- interaction ---------------------------------------------------------
  var drag = null;
  stage.addEventListener("pointerdown", function (e) {
    drag = { x: e.clientX, y: e.clientY, moved: false };
    stage.setPointerCapture(e.pointerId);
    stage.classList.add("dragging");
  });
  stage.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    view.x -= dx / view.scale;
    view.y -= dy / view.scale;
    drag.x = e.clientX; drag.y = e.clientY;
    clamp(); draw();
  });
  stage.addEventListener("pointerup", function (e) {
    if (drag && !drag.moved) deselect();
    drag = null;
    stage.classList.remove("dragging");
    writeHash();
  });
  stage.addEventListener("pointercancel", function () { drag = null; });

  function zoomAt(factor, cx, cy) {
    // Keep the point under the cursor fixed while the scale changes.
    var before = { x: view.x + (cx - stage.clientWidth / 2) / view.scale,
                   y: view.y + (cy - stage.clientHeight / 2) / view.scale };
    view.scale *= factor;
    clamp();
    var after = { x: view.x + (cx - stage.clientWidth / 2) / view.scale,
                  y: view.y + (cy - stage.clientHeight / 2) / view.scale };
    view.x += before.x - after.x;
    view.y += before.y - after.y;
    clamp(); draw(); writeHash();
  }

  stage.addEventListener("wheel", function (e) {
    e.preventDefault();
    var factor = Math.pow(2, -e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.002));
    zoomAt(factor, e.clientX, e.clientY);
  }, { passive: false });

  stage.addEventListener("dblclick", function (e) { zoomAt(2, e.clientX, e.clientY); });

  document.addEventListener("keydown", function (e) {
    var step = 80 / view.scale;
    if (e.key === "ArrowLeft") view.x -= step;
    else if (e.key === "ArrowRight") view.x += step;
    else if (e.key === "ArrowUp") view.y -= step;
    else if (e.key === "ArrowDown") view.y += step;
    else if (e.key === "+" || e.key === "=") return zoomAt(2, stage.clientWidth / 2, stage.clientHeight / 2);
    else if (e.key === "-" || e.key === "_") return zoomAt(0.5, stage.clientWidth / 2, stage.clientHeight / 2);
    else if (e.key === "0") { fit(); writeHash(); return; }
    else if (e.key === "Escape") { deselect(); return; }
    else return;
    e.preventDefault(); clamp(); draw(); writeHash();
  });

  document.getElementById("zoomIn").onclick = function () {
    zoomAt(2, stage.clientWidth / 2, stage.clientHeight / 2); };
  document.getElementById("zoomOut").onclick = function () {
    zoomAt(0.5, stage.clientWidth / 2, stage.clientHeight / 2); };
  document.getElementById("fit").onclick = function () { fit(); writeHash(); };
  document.getElementById("cardClose").onclick = deselect;
  document.getElementById("pins").onclick = function () {
    showPins = !showPins;
    this.setAttribute("aria-pressed", showPins ? "true" : "false");
    placeMarkers();
  };
  document.getElementById("share").onclick = function () {
    var btn = this;
    var done = function (ok) {
      btn.textContent = ok ? "Copied" : "Copy failed";
      setTimeout(function () { btn.textContent = "Share"; }, 1400);
    };
    writeHash();
    if (navigator.clipboard) {
      navigator.clipboard.writeText(location.href).then(function () { done(true); },
                                                        function () { done(false); });
    } else { done(false); }
  };

  window.addEventListener("resize", function () { clamp(); resize(); });
  window.addEventListener("hashchange", function () { if (!hashLock) { readHash(); draw(); } });

  // --- boot ----------------------------------------------------------------
  fetch("data.json").then(function (r) { return r.json(); }).then(function (data) {
    D = data;
    document.getElementById("cityName").textContent = data.city;
    document.getElementById("citySub").textContent = data.subtitle || "";
    document.getElementById("attribution").innerHTML =
      (data.attribution || []).join("<br>");
    var dl = document.getElementById("stats");
    (data.stats || []).forEach(function (s) {
      var dt = document.createElement("dt"); dt.textContent = s.label;
      var dd = document.createElement("dd"); dd.textContent = s.value;
      dl.appendChild(dt); dl.appendChild(dd);
    });
    buildMarkers();
    resize();
    if (!readHash()) fit();
    draw();
  }).catch(function (err) {
    document.getElementById("citySub").textContent =
      "Could not load data.json — serve this directory over HTTP, not file://";
    console.error(err);
  });
})();
</script>
</body>
</html>
"""
