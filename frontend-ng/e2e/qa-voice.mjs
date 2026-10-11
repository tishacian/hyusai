/**
 * Close-up on the voice controls bar (the regression that started the polish
 * work: near-white text on a light surface). Crops the bar at 2x and computes
 * the real rendered contrast ratio of every text node inside it against the
 * nearest painted background.
 */
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = 'e2e/qa-visual';
mkdirSync(OUT, { recursive: true });

const ME = { id: 'u-qa', email: 'qa@local.test', name: 'QA Local', roles: ['admin', 'owner'] };
const WS = {
  id: 'ws-qa',
  slug: 'nawa',
  name: 'NAWA',
  settings: {
    features: { voice: true, voice_realtime: true },
    voice: { enabled: true, provider: 'openai', transport: 'livekit' },
    voice_loop: { enabled: true },
    voice_output: { enabled: true },
  },
};
const payload = (p) =>
  /\/auth\/me|\/users\/me|\/me$/.test(p)
    ? ME
    : /\/workspaces\/?$/.test(p)
      ? [WS]
      : /\/workspaces\/[^/]+\/?$/.test(p)
        ? WS
        : /\/(skills|systems|capabilities|runs|collections|apps|presets|sessions)(\/)?$/.test(p)
          ? []
          : { items: [], results: [], total: 0 };

const CONTRAST = `(() => {
  const lum = (rgb) => {
    const c = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const parse = (s) => {
    const m = (s || '').match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x.trim()));
    return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 };
  };
  const over = (fg, bg) => fg.rgb.map((v, i) => v * fg.a + bg[i] * (1 - fg.a));
  const bgOf = (el) => {
    let n = el;
    let acc = null;
    while (n && n.nodeType === 1) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) {
        acc = acc ? acc : null;
        if (c.a >= 1) return c.rgb;
        // approximate: blend translucent layer onto white/black page later
        return c.rgb;
      }
      n = n.parentElement;
    }
    return [255, 255, 255];
  };
  const bar = document.querySelector('app-voice-controls');
  if (!bar) return { error: 'no app-voice-controls in DOM' };
  const out = [];
  const walk = document.createTreeWalker(bar, NodeFilter.SHOW_TEXT);
  let t;
  while ((t = walk.nextNode())) {
    const txt = (t.textContent || '').trim();
    if (!txt) continue;
    const el = t.parentElement;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const fg = parse(cs.color);
    const bg = bgOf(el);
    if (!fg) continue;
    const fgFlat = over(fg, bg);
    const l1 = lum(fgFlat);
    const l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    out.push({
      text: txt.slice(0, 48),
      color: cs.color,
      bg: 'rgb(' + bg.join(',') + ')',
      size: cs.fontSize,
      weight: cs.fontWeight,
      opacity: cs.opacity,
      ratio: Math.round(ratio * 100) / 100,
    });
  }
  const r = bar.getBoundingClientRect();
  return { box: { x: r.x, y: r.y, width: r.width, height: r.height }, rows: out };
})()`;

const browser = await chromium.launch();
const log = [];

for (const theme of ['light', 'dark']) {
  for (const locale of ['en', 'fr']) {
    const ctx = await browser.newContext({
      viewport: { width: 1600, height: 1000 },
      deviceScaleFactor: 2,
    });
    await ctx.addInitScript(
      ({ theme, locale }) => {
        localStorage.setItem('agentium_token', 'Bearer qa-local-token');
        localStorage.setItem('agentium_workspace_slug', 'nawa');
        localStorage.setItem('agentium_theme', theme);
        localStorage.setItem('agentium_locale', locale);
      },
      { theme, locale },
    );
    const page = await ctx.newPage();
    await page.route('**/api/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload(new URL(route.request().url()).pathname)),
      }),
    );
    await page.route(/https:\/\/fonts\./, (route) => route.abort());
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);

    const res = await page.evaluate(CONTRAST);
    log.push(`\n===== voice-bar ${theme}-${locale} =====\n${JSON.stringify(res, null, 1)}`);
    if (res.box) {
      const b = res.box;
      await page.screenshot({
        path: `${OUT}/voicebar-${theme}-${locale}.png`,
        clip: { x: Math.max(0, b.x - 8), y: Math.max(0, b.y - 8), width: b.width + 16, height: b.height + 16 },
      });
      const bad = res.rows.filter((r) => r.ratio < 4.5);
      console.log(
        `voicebar ${theme}-${locale}: ${res.rows.length} text nodes, ${bad.length} under 4.5:1`,
      );
      for (const r of bad) console.log(`   ${r.ratio}  "${r.text}"  ${r.color} on ${r.bg} ${r.size}`);
    } else {
      console.log(`voicebar ${theme}-${locale}: ${JSON.stringify(res)}`);
    }
    await ctx.close();
  }
}

writeFileSync(`${OUT}/voicebar.json`, log.join('\n'));
await browser.close();
