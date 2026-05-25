/**
 * Shared utilities for SENTINEL-CI Playwright QA harnesses (S1/S2/S3).
 */
import { stat } from 'node:fs/promises';
import { join } from 'node:path';

export const HOST = (process.env.AGENTIUM_HOST || 'https://agentium.papai.ai').replace(/\/+$/, '');
export const EMAIL = process.env.AGENTIUM_EMAIL || 'thibaud.ishacian@datategy.net';
export const PASSWORD = process.env.AGENTIUM_PASSWORD || '';
export const WORKSPACE = 'sentinel-ci';
export const NAV_TIMEOUT = 45_000;
export const AYA_WAIT_MS = 18_000;

export function createHarnessState(startedAt = Date.now()) {
  return {
    startedAt,
    results: [],
    consoleErrors: [],
    windowEvents: [],
    sseChunks: [],
    probesInstalled: false,
  };
}

export function log(state, m) {
  const e = ((Date.now() - state.startedAt) / 1000).toFixed(1);
  console.log(`[${e.padStart(6, ' ')}s] ${m}`);
}

export function record(state, step, { status, observation, fix, priority = 'P1', screenshot = null, extra = {} }) {
  const r = { step, status, observation, fix, priority, screenshot, ...extra };
  state.results.push(r);
  log(state, `  [${status}] ${step}: ${observation.slice(0, 140)}`);
  return r;
}

export async function shot(page, outDir, name) {
  const file = join(outDir, `${name}.png`);
  try {
    await page.waitForTimeout(800);
    await page.screenshot({ path: file, fullPage: false });
    const st = await stat(file);
    return { file, sizeBytes: st.size, ok: st.size > 5000 };
  } catch (e) {
    return { file: null, sizeBytes: 0, ok: false, error: e.message };
  }
}

export async function installProbes(page, state) {
  if (state.probesInstalled) return;
  state.probesInstalled = true;
  await page.exposeFunction('__report_event', (e) => state.windowEvents.push(e));
  await page.exposeFunction('__report_chunk', (c) => state.sseChunks.push(c));
  await page.evaluate(() => {
    for (const n of [
      'agentium:assistant-navigate',
      'agentium:assistant-propose',
      'agentium:assistant-show-webcam',
      'agentium:assistant-draft-open',
      'agentium:map-command',
    ]) {
      window.addEventListener(n, (ev) => {
        try {
          window.__report_event({ event: n, detail: ev.detail });
        } catch {}
      });
    }
    const origFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      const isStream = url && url.includes('/chat/stream');
      const res = await origFetch(input, init);
      if (isStream && res.body) {
        const orig = res.clone();
        (async () => {
          const reader = orig.body.getReader();
          const dec = new TextDecoder();
          let buf = '';
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop() || '';
            for (const line of lines) {
              if (line.startsWith('data:')) {
                const data = line.slice(5).trim();
                if (!data) continue;
                try {
                  window.__report_chunk(JSON.parse(data));
                } catch {}
              }
            }
          }
        })();
      }
      return res;
    };
  });
}

export async function login(page, state, outDir) {
  if (!PASSWORD) {
    throw new Error('AGENTIUM_PASSWORD is required for QA login');
  }
  await installProbes(page, state);
  await page.goto(`${HOST}/`, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  await page.waitForTimeout(1500);
  const emailSel = page.locator('#signin-email, input[type=email]').first();
  await emailSel.waitFor({ state: 'visible', timeout: 15_000 });
  await emailSel.fill(EMAIL);
  await page.locator('#signin-password, input[type=password]').first().fill(PASSWORD);
  await page
    .locator('form.ck-auth-form button[type="submit"], button[type="submit"]')
    .first()
    .click();
  try {
    await page.waitForURL(/\/hypervisor(\/|$)/, { timeout: 25_000 });
  } catch {
    await shot(page, outDir, '00-login-failed');
    throw new Error(`Login failed url=${page.url()}`);
  }
  await page.evaluate((slug) => {
    try {
      localStorage.setItem('agentium_workspace_slug', slug);
    } catch {}
  }, WORKSPACE);
}

export async function openAyaPanel(page) {
  for (const sel of [
    'button.action-button:has-text("AYA")',
    '[aria-label="Ouvrir AYA"]',
    '.assistant-badge',
    'button:has-text("AYA")',
  ]) {
    try {
      const loc = page.locator(sel).first();
      if ((await loc.count()) === 0) continue;
      await loc.click({ timeout: 4000 });
      await page.waitForTimeout(1000);
      if (
        await page
          .locator('textarea[name="userInput"]')
          .first()
          .isVisible()
          .catch(() => false)
      )
        return true;
    } catch {}
  }
  await page.keyboard.press('Meta+j').catch(() => {});
  await page.waitForTimeout(800);
  if (
    await page
      .locator('textarea[name="userInput"]')
      .first()
      .isVisible()
      .catch(() => false)
  )
    return true;
  await page.keyboard.press('Control+j').catch(() => {});
  await page.waitForTimeout(800);
  return page
    .locator('textarea[name="userInput"]')
    .first()
    .isVisible()
    .catch(() => false);
}

export async function sendAya(page, state, text, waitMs = AYA_WAIT_MS) {
  const ta = page.locator('textarea[name="userInput"]').first();
  await ta.waitFor({ state: 'visible', timeout: 10_000 });
  await ta.fill(text);
  await page.waitForTimeout(200);
  const beforeChunks = state.sseChunks.length;
  await ta.press('Enter');
  await page.waitForTimeout(waitMs);
  try {
    await page.waitForFunction(
      () => {
        const t = document.querySelector('textarea[name="userInput"]');
        return t && !t.disabled;
      },
      { timeout: waitMs },
    );
  } catch {}
  await page.waitForTimeout(1500);
  return { newChunks: state.sseChunks.slice(beforeChunks) };
}

export async function drawerState(page) {
  return page.evaluate(() => {
    const drawer = document.querySelector(
      'app-assistant-draft-drawer, .draft-drawer, [data-testid="assistant-draft-drawer"]',
    );
    const open = !!drawer && (
      drawer.getAttribute('data-open') === 'true' ||
      drawer.classList.contains('is-open') ||
      drawer.querySelector('[open]') ||
      drawer.querySelector('iframe, embed, object') ||
      (drawer.textContent || '').trim().length > 40
    );
    const title = drawer?.querySelector('h2, h3, .drawer-title, [class*="title"]')?.textContent?.trim() || '';
    const body = drawer?.querySelector('.draft-body, pre, .doc-preview')?.textContent?.trim() || '';
    const kind = drawer?.querySelector('.eyebrow')?.textContent?.trim() || drawer?.getAttribute('data-kind') || '';
    const pdfVisible = !!drawer?.querySelector('iframe[src*="pdf"], iframe[src*="blob"], canvas, .pdf-viewer');
    const emailVisible = !!drawer?.querySelector('.email-draft, [class*="customs"], textarea, .draft-body');
    return { open: !!open || !!drawer, title: title.slice(0, 160), body: body.slice(0, 400), kind, pdfVisible, emailVisible };
  });
}

export async function webcamState(page) {
  return page.evaluate(() => {
    const imgs = [...document.querySelectorAll('img[src*="webcam"], img[src*="blob"], video, .webcam-preview, .webcam-tile')];
    const apm = [...document.querySelectorAll('*')].some(el => /APM Apapa|Port Vridi|Atlantic Trader/i.test(el.textContent || ''));
    const filled = imgs.filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 40 && r.height > 40;
    }).length;
    return { filled, apm, total: imgs.length };
  });
}

export async function goto(page, path) {
  const url = path.startsWith('http') ? path : `${HOST}${path}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  try {
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
  } catch {}
  await page.waitForTimeout(2000);
}

export function hasAction(chunks, actionPattern) {
  return chunks.some((c) => actionPattern.test(JSON.stringify(c)));
}

export function summarizeResults(state) {
  const pass = state.results.filter((r) => r.status === 'PASS').length;
  const partial = state.results.filter((r) => r.status === 'PARTIAL').length;
  const fail = state.results.filter((r) => r.status === 'FAIL').length;
  return { pass, partial, fail, total: state.results.length };
}

export function functionalPass(status, domOk, telemetryOk = false) {
  if (domOk) return 'PASS';
  if (status === 'FAIL' && telemetryOk) return 'PARTIAL';
  return status;
}
