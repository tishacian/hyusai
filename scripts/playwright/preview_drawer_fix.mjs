/**
 * Render the post-fix assistant-draft-drawer markup with the same CSS variables
 * used by the production cockpit, then capture two screenshots that mirror
 * the on-prod look once `fix(drawer): show cited passages` is deployed.
 *
 * Usage: node scripts/playwright/preview_drawer_fix.mjs
 */
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR =
  process.env.OUT_DIR ||
  join(__dirname, '..', '..', 'docs', 'status-screenshots', '2026-05-25-qa-trame');

const cases = [
  {
    name: 'S1-03-pv-douanes',
    eyebrow: 'DOCUMENT_PREVIEW',
    title: 'PV douanes - non conformite declarative',
    passages: [
      {
        page: 2,
        label: 'Cargo non conforme distinct du cargo MV Atlantic Trader',
        text: 'Page 2 du PV douanes du 18 mai 2026 - cargo non conforme distinct.',
      },
    ],
  },
  {
    name: 'S2-12-rapport-strategique',
    eyebrow: 'DOCUMENT_PREVIEW',
    title: 'Rapport strategique - cacao_diversification',
    passages: [
      {
        page: 1,
        label: null,
        text: 'Synthèse des préconisations cacao – diversification anacarde, base rapport Préfet Nawa.',
      },
    ],
  },
];

const html = (item) => `<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<title>${item.title}</title>
<style>
  :root {
    --mission-text-primary: #e8edf3;
    --mission-text-secondary: #aab4c2;
    --mission-text-tertiary: #6b7785;
    --mission-border: rgba(72, 88, 110, 0.45);
    --mission-inset: #0d1218;
    --mission-surface-1: #11161e;
    --mission-warning: #f1b45a;
    --mission-warning-soft: rgba(241, 180, 90, 0.10);
    --sentinel-accent: #65d66e;
    --sentinel-accent-strong: #92e69a;
    --sentinel-accent-soft: rgba(101, 214, 110, 0.12);
    --sentinel-accent-muted: rgba(101, 214, 110, 0.35);
    --mission-radius-sm: 6px;
    --mission-radius-md: 10px;
    --mission-shadow-floating: 0 24px 48px rgba(0, 0, 0, 0.45);
    --mission-space-1: 4px;
    --mission-space-2: 8px;
    --mission-space-3: 12px;
    --mission-space-4: 16px;
    --mission-space-5: 24px;
    --mission-text-xs: 12px;
    --mission-text-sm: 13px;
    --mission-text-md: 16px;
    --mission-lh-tight: 1.2;
    --mission-lh-body: 1.55;
    --mission-tracking-tight: -0.005em;
    --mission-tracking-micro: 0.14em;
    --mission-font-body: "Inter", system-ui, -apple-system, sans-serif;
    --mission-font-mono: "JetBrains Mono", ui-monospace, monospace;
    --mission-dur-fast: 120ms;
    --mission-dur-base: 200ms;
    --mission-dur-slow: 320ms;
    --mission-ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  }
  html, body {
    margin: 0;
    padding: 0;
    height: 100%;
    background: radial-gradient(ellipse at top, #0c1218 0%, #05080c 60%, #02050a 100%);
    color: var(--mission-text-primary);
    font-family: var(--mission-font-body);
  }
  .draft-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1200;
    background: rgba(2, 6, 10, 0.55);
    backdrop-filter: blur(6px);
  }
  .draft-drawer {
    position: fixed;
    top: 0;
    right: 0;
    z-index: 1201;
    width: min(720px, 100vw);
    height: 100vh;
    display: grid;
    grid-template-rows: auto 1fr auto;
    gap: var(--mission-space-3);
    padding: var(--mission-space-5) var(--mission-space-4);
    border-left: 1px solid var(--sentinel-accent-muted);
    background: rgba(5, 8, 12, 0.98);
    box-shadow: var(--mission-shadow-floating);
  }
  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--mission-space-3);
  }
  .eyebrow {
    display: block;
    color: var(--sentinel-accent);
    font-family: var(--mission-font-mono);
    font-size: 10px;
    letter-spacing: var(--mission-tracking-micro);
    text-transform: uppercase;
  }
  h2 {
    margin: var(--mission-space-1) 0 0;
    font-size: var(--mission-text-md);
    font-weight: 600;
    letter-spacing: var(--mission-tracking-tight);
    line-height: var(--mission-lh-tight);
  }
  .icon-button {
    border: 1px solid var(--mission-border);
    border-radius: var(--mission-radius-sm);
    background: var(--mission-inset);
    color: var(--mission-text-secondary);
    padding: 6px 10px;
    cursor: pointer;
    font-size: 14px;
  }
  .doc-preview {
    position: relative;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: var(--mission-space-3);
    overflow: hidden;
  }
  .doc-citation-preview {
    flex: 1 1 auto;
    min-height: 360px;
    padding: var(--mission-space-4);
    border: 1px solid rgba(241, 180, 90, 0.28);
    border-radius: var(--mission-radius-md);
    background: var(--mission-warning-soft);
    overflow: auto;
  }
  .doc-citation-preview > .eyebrow {
    color: var(--mission-warning);
  }
  .citation-page {
    margin-top: var(--mission-space-3);
    padding: var(--mission-space-3);
    border-left: 3px solid rgba(241, 180, 90, 0.55);
    background: rgba(241, 180, 90, 0.06);
    border-radius: var(--mission-radius-sm);
  }
  .citation-page strong {
    display: block;
    margin-bottom: var(--mission-space-1);
    font-family: var(--mission-font-mono);
    font-size: 11px;
    color: var(--mission-warning);
  }
  .citation-page em {
    display: block;
    margin-bottom: var(--mission-space-2);
    font-style: normal;
    color: var(--mission-text-secondary);
    font-size: var(--mission-text-xs);
  }
  .citation-page p {
    margin: 0;
    font-size: var(--mission-text-sm);
    line-height: var(--mission-lh-body);
    color: var(--mission-text-primary);
  }
  .doc-citation-hint {
    margin: var(--mission-space-3) 0 0;
    font-size: var(--mission-text-xs);
    color: var(--mission-text-tertiary);
    font-style: italic;
  }
  footer {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: var(--mission-space-3);
  }
  .action-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 36px;
    padding: 8px 16px;
    border: 1px solid var(--mission-border);
    border-radius: var(--mission-radius-sm);
    background: var(--mission-inset);
    color: inherit;
    font: inherit;
    font-size: var(--mission-text-sm);
    text-decoration: none;
  }
  .action-button.primary {
    border-color: rgba(101, 214, 110, 0.42);
    background: var(--sentinel-accent-soft);
    color: var(--sentinel-accent-strong);
    font-weight: 600;
  }
  .action-button.ghost { background: transparent; }
</style>
</head>
<body>
  <div class="draft-backdrop" aria-hidden="true"></div>
  <aside class="draft-drawer" role="dialog" aria-label="Brouillon advisory">
    <header>
      <div>
        <span class="eyebrow">${item.eyebrow}</span>
        <h2>${item.title}</h2>
      </div>
      <button type="button" class="icon-button" aria-label="Fermer">✕</button>
    </header>
    <section class="doc-preview" aria-label="Aperçu document">
      <section class="doc-citation-preview" aria-label="Extraits cités par AYA">
        <span class="eyebrow">Aperçu document · extraits cités par AYA</span>
        ${item.passages
          .map(
            (p) => `
        <article class="citation-page">
          ${p.page ? `<strong>Page ${p.page}</strong>` : ''}
          ${p.label ? `<em>${p.label}</em>` : ''}
          ${p.text ? `<p>« ${p.text} »</p>` : ''}
        </article>`,
          )
          .join('')}
        <p class="doc-citation-hint">PDF complet disponible via « Télécharger ».</p>
      </section>
    </section>
    <footer>
      <a class="action-button primary" href="#">Télécharger</a>
      <button type="button" class="action-button ghost">Fermer</button>
    </footer>
  </aside>
</body>
</html>`;

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1024, height: 576 },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  for (const item of cases) {
    await page.setContent(html(item), { waitUntil: 'load' });
    await page.waitForTimeout(200);
    const out = join(OUT_DIR, `${item.name}.png`);
    await page.screenshot({ path: out, fullPage: false });
    console.log(`[ok] ${out}`);
  }
  await ctx.close();
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
