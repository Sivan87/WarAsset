// Fas 5: renders static/img/favicon.svg to the raster favicon/app-icon sizes
// browsers actually request (static/img/favicon-16.png, favicon-32.png,
// apple-touch-icon.png). Not part of the Docker build/runtime (no image
// library is installed in the app's venv or the container, see CLAUDE.md) —
// this is a one-off dev-time tool, run manually and its PNG output committed
// to the repo, same spirit as the Playwright testing already used ad hoc in
// every previous phase (no run-skill exists for WarAsset yet).
//
// Usage (from a scratch directory with `npm install playwright` +
// `npx playwright install chromium` already done — see any previous phase's
// CLAUDE.md testing notes for the exact commands):
//   node render_favicons.js
//
// Re-run this after editing static/img/favicon.svg (e.g. if the accent hex
// in nocturne.css's --color-accent ever changes and favicon.svg's hardcoded
// copy is updated to match).

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');
const svgPath = path.join(REPO_ROOT, 'static/img/favicon.svg');
const svg = fs.readFileSync(svgPath, 'utf8');
const dataUri = 'data:image/svg+xml;base64,' + Buffer.from(svg).toString('base64');

const targets = [
  { file: path.join(REPO_ROOT, 'static/img/favicon-16.png'), size: 16 },
  { file: path.join(REPO_ROOT, 'static/img/favicon-32.png'), size: 32 },
  { file: path.join(REPO_ROOT, 'static/img/apple-touch-icon.png'), size: 180 },
];

(async () => {
  const browser = await chromium.launch();
  for (const t of targets) {
    const page = await browser.newPage({ viewport: { width: t.size, height: t.size }, deviceScaleFactor: 1 });
    await page.setContent(`<!doctype html><html><head><style>
      html,body{margin:0;padding:0;width:${t.size}px;height:${t.size}px;overflow:hidden;background:transparent;}
      img{display:block;width:${t.size}px;height:${t.size}px;}
    </style></head><body><img id="pic" src="${dataUri}"></body></html>`);
    await page.waitForFunction(() => document.getElementById('pic').complete && document.getElementById('pic').naturalWidth > 0);
    await page.screenshot({ path: t.file, omitBackground: true });
    await page.close();
    console.log('wrote', t.file);
  }
  await browser.close();
})();
