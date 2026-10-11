import { chromium } from 'playwright-core';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(__dirname, '../..');
const deck = `file://${path.join(repo, 'docs/sentinel-ci-demo-deck-2026-05-25.html')}`;
const outDir = path.join(repo, 'docs/status-screenshots/2026-05-25-deck-redesign');

const targets = [
  { hash: '#/0', file: 'html-01-title.png' },
  { hash: '#/3', file: 'html-02-section-bloc1.png' },
  { hash: '#/5', file: 'html-03-content-state-du-jour.png' },
  { hash: '#/16', file: 'html-04-recap-s1-table.png' },
  { hash: '#/24', file: 'html-05-bloc4-section.png' },
  { hash: '#/26', file: 'html-06-content-pic-pv-douanes.png' },
];

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
const page = await ctx.newPage();
await fs.mkdir(outDir, { recursive: true });

for (const t of targets) {
  await page.goto(deck + t.hash, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const out = path.join(outDir, t.file);
  await page.screenshot({ path: out, fullPage: false });
  console.log(`saved ${out}`);
}

await browser.close();
