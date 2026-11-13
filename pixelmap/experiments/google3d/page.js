// Orthographic 2:1 isometric render of Google Photorealistic 3D Tiles.
// Driven by render.mjs through window.g3d.*
import * as THREE from 'three';
import { TilesRenderer } from '3d-tiles-renderer';
import { GoogleCloudAuthPlugin, GLTFExtensionsPlugin, TileCompressionPlugin } from '3d-tiles-renderer/plugins';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';

const DEG = Math.PI / 180;
const P = window.__G3D;            // { key, lat, lon, bearing, elev, across, deep, headroom, shotPx, errorTarget }

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(P.shotPx, P.shotPx);
renderer.setClearColor(0xffffff, 1);
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.add(new THREE.AmbientLight(0xffffff, 3));

const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 20000);

const tiles = new TilesRenderer();
tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: P.key, autoRefreshToken: true }));
const draco = new DRACOLoader().setDecoderPath('/draco/');
tiles.registerPlugin(new GLTFExtensionsPlugin({ dracoLoader: draco }));
tiles.registerPlugin(new TileCompressionPlugin());
tiles.errorTarget = P.errorTarget;
tiles.lruCache.minSize = 6000;
tiles.lruCache.maxSize = 12000;
tiles.lruCache.minBytesSize = 2e9;
tiles.lruCache.maxBytesSize = 3e9;
scene.add(tiles.group);
tiles.setCamera(camera);
tiles.setResolutionFromRenderer(camera, renderer);

// Local frame at the target, in world (ECEF, since the group is untransformed).
const ell = tiles.ellipsoid;
const pos = (lat, lon, h) => ell.getCartographicToPosition(lat * DEG, lon * DEG, h, new THREE.Vector3());
let groundH = P.groundH;
let T, up, fwd, right;

function frame() {
  T = pos(P.lat, P.lon, groundH);
  up = ell.getCartographicToNormal(P.lat * DEG, P.lon * DEG, new THREE.Vector3());
  const east = new THREE.Vector3(0, 0, 1).cross(up).normalize();   // ECEF z is the pole
  const north = up.clone().cross(east).normalize();
  const b = P.bearing * DEG;                                        // view direction, clockwise from north
  fwd = north.clone().multiplyScalar(Math.cos(b)).add(east.clone().multiplyScalar(Math.sin(b)));
  right = fwd.clone().cross(up).normalize();
  const e = P.elev * DEG;
  const dir = fwd.clone().multiplyScalar(Math.cos(e)).add(up.clone().multiplyScalar(-Math.sin(e)));
  camera.position.copy(T).addScaledVector(dir, -8000);
  camera.up.copy(up);
  camera.lookAt(T);
  camera.updateMatrixWorld();
}
frame();

// Screen extent of the requested ground rectangle, plus headroom for height.
function extent() {
  const s = Math.sin(P.elev * DEG), c = Math.cos(P.elev * DEG);
  return {
    left: -P.across / 2, right: P.across / 2,
    bottom: -P.deep / 2 * s, top: P.deep / 2 * s + P.headroom * c,
  };
}

function setShot(l, r, b, t) {
  Object.assign(camera, { left: l, right: r, bottom: b, top: t });
  camera.updateProjectionMatrix();
  tiles.setResolutionFromRenderer(camera, renderer);
}

const tick = () => new Promise(res => requestAnimationFrame(res));

async function settle(maxFrames = 6000) {
  let quiet = 0;
  for (let f = 0; f < maxFrames; f++) {
    camera.updateMatrixWorld();
    tiles.update();
    renderer.render(scene, camera);
    await tick();
    const s = tiles.stats;
    const busy = s.queued + s.downloading + s.parsing;
    quiet = busy === 0 && tiles.root ? quiet + 1 : 0;
    if (quiet > 20) return { frames: f, ...s };
    if (tiles.rootLoadingState === -1 /* FAILED */ || (s.failed && !tiles.root)) throw new Error('root tileset failed to load');
  }
  return { frames: maxFrames, timeout: true, ...tiles.stats };
}

window.g3d = {
  extent,
  async probeGround() {
    // Coarse view of the whole frame, then cast a ray down at the target.
    const e = extent();
    setShot(e.left, e.right, e.bottom, e.top);
    await settle();
    const ray = new THREE.Raycaster(pos(P.lat, P.lon, 1000), up.clone().negate());
    const hits = ray.intersectObject(tiles.group, true);
    if (hits.length) {
      const d = hits[0].point.clone().sub(pos(P.lat, P.lon, 0)).dot(up);
      groundH = d;
      frame();
    }
    return { groundH, hits: hits.length };
  },
  async shot(l, r, b, t) {
    setShot(l, r, b, t);
    const s = await settle();
    renderer.render(scene, camera);
    return { stats: s, png: renderer.domElement.toDataURL('image/png') };
  },
  attributions() {
    return tiles.getAttributions().map(a => a.value);
  },
};
window.g3dReady = true;
