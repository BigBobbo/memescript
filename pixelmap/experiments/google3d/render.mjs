// Usage: GOOGLE_MAPS_API_KEY=... node render.mjs [outdir]
// Renders an isometric patch of Google Photorealistic 3D Tiles as a grid of
// orthographic shots, then writes them plus a manifest for stitch.py.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { chromium } from 'playwright-core';

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(process.argv[2] || path.join(here, 'out'));
fs.mkdirSync(out, { recursive: true });

const key = process.env.GOOGLE_MAPS_API_KEY;
if (!key) { console.error('GOOGLE_MAPS_API_KEY is not set'); process.exit(1); }

// Matches pixelmap's iso.py with rotation 212.75: screen-right faces 257.75°,
// so the camera looks toward 167.75°. 30° elevation gives exact 2:1 ground lines.
const P = {
  lat: Number(process.env.LAT ?? 52.6678),      // King John's Castle, Thomond Bridge, the Shannon
  lon: Number(process.env.LON ?? -8.6255),
  bearing: Number(process.env.BEARING ?? 167.75),
  elev: 30,
  across: Number(process.env.ACROSS ?? 1000),   // metres
  deep: Number(process.env.DEEP ?? 1000),
  headroom: 95,                                 // St John's spire is 90 m
  groundH: 60,                                  // ellipsoid height guess, refined by ray cast
  mPerPx: Number(process.env.M_PER_PX ?? 0.25),
  shotPx: 1024,
  errorTarget: Number(process.env.ERROR_TARGET ?? 4),
};

const bundle = await build({
  entryPoints: [path.join(here, 'page.js')], bundle: true, write: false, format: 'esm',
});
const drac = path.join(here, 'node_modules/three/examples/jsm/libs/draco');
const server = http.createServer((req, res) => {
  if (req.url === '/') {
    res.setHeader('content-type', 'text/html');
    return res.end('<!doctype html><body style="margin:0"><script type="module" src="/page.js"></script>');
  }
  if (req.url === '/page.js') {
    res.setHeader('content-type', 'text/javascript');
    return res.end(bundle.outputFiles[0].text);
  }
  if (req.url.startsWith('/draco/')) {
    const f = path.join(drac, path.basename(req.url));
    if (fs.existsSync(f)) {
      res.setHeader('content-type', f.endsWith('.wasm') ? 'application/wasm' : 'text/javascript');
      return res.end(fs.readFileSync(f));
    }
  }
  res.statusCode = 404; res.end();
}).listen(0);
const url = `http://127.0.0.1:${server.address().port}/`;

console.log('server', url);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_BIN || undefined,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
});
console.log('browser up');
const page = await browser.newPage({ viewport: { width: P.shotPx, height: P.shotPx } });
page.on('response', r => { if (r.url().includes('googleapis') && r.status() >= 400) console.error('[http]', r.status(), r.url().split('?')[0]); });
page.on('pageerror', e => console.error('[pageerror]', String(e).replace(key, '<key>')));
page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.error('[page]', m.text().replace(key, '<key>')); });
await page.addInitScript(p => { window.__G3D = p; }, { ...P, key });
await page.goto(url);
await page.waitForFunction(() => window.g3dReady, null, { timeout: 60000 });

console.log('page ready');
const t0 = Date.now();
console.log('probe ground:', await page.evaluate(() => g3d.probeGround()));
const e = await page.evaluate(() => g3d.extent());

const span = P.shotPx * P.mPerPx;               // metres of screen per shot
const cols = Math.ceil((e.right - e.left) / span);
const rows = Math.ceil((e.top - e.bottom) / span);
console.log(`grid ${cols} x ${rows} shots of ${P.shotPx}px at ${P.mPerPx} m/px`);

const shots = [];
for (let r = 0; r < rows; r++) {
  for (let c = 0; c < cols; c++) {
    const l = e.left + c * span, t = e.top - r * span;
    const { stats, png } = await page.evaluate(a => g3d.shot(...a), [l, l + span, t - span, t]);
    const file = `shot_r${r}_c${c}.png`;
    fs.writeFileSync(path.join(out, file), Buffer.from(png.split(',')[1], 'base64'));
    shots.push({ r, c, file });
    console.log(`${file}  frames ${stats.frames}  cached ${stats.inCache}  failed ${stats.failed}${stats.timeout ? '  TIMEOUT' : ''}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
}

const attributions = await page.evaluate(() => g3d.attributions());
const crop = {
  w: Math.round((e.right - e.left) / P.mPerPx),
  h: Math.round((e.top - e.bottom) / P.mPerPx),
};
const { key: _k, ...params } = P;
fs.writeFileSync(path.join(out, 'manifest.json'),
  JSON.stringify({ params, extent: e, cols, rows, shotPx: P.shotPx, crop, shots, attributions }, null, 2));
console.log('attributions:', attributions.join('; '));
await browser.close();
server.close();
