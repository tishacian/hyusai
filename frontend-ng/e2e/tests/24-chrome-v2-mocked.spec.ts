import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route, type TestInfo } from '@playwright/test';

/**
 * Chrome v2 — local, fully mocked safety net for the Cockpit chrome lots.
 *
 * Opt-in, with no backend:
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://localhost:4200
 *   npx playwright test e2e/tests/24-chrome-v2-mocked.spec.ts
 *
 * Every `/api/v1/**` request is answered here. Each chrome lot adds its
 * scenario below. The L1 scenarios are local-only and block every other
 * host, so they can never touch a shared environment; the L4 scenario needs
 * the network, since its fonts come from Google Fonts.
 */

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

// --- L1 — swallowed gestures ------------------------------------------------

const WORKSPACE_SLUG = 'chrome-v2';
const WORKSPACE_ID = 'workspace-chrome-v2';
const TOKEN = 'Bearer local-chrome-v2-token';
const SYSTEM_ID = 'system-chrome-v2';
const FLOW_HASH = '1'.repeat(64);

const workspace = {
  id: WORKSPACE_ID,
  name: 'Chrome v2 workspace',
  slug: WORKSPACE_SLUG,
  role: 'admin',
  role_template: 'workspace_admin',
  member_count: 1,
  created_at: '2026-09-24T08:00:00Z',
  is_active: true,
  mode: 'builder',
  settings: {},
  effective_features: {},
  app_entitlements: [],
};

const flowDefinition = {
  source: 'flow',
  schema_version: 3,
  nodes: [
    {
      id: 'source.request',
      type: 'source',
      kind: 'source',
      label: 'Request',
      position: { x: 120, y: 180 },
      inputs: [],
      outputs: [{ name: 'payload', schema: 'object' }],
      config: { ingress: { kind: 'manual' } },
    },
    {
      id: 'sink.answer',
      type: 'sink',
      kind: 'sink',
      label: 'Answer',
      position: { x: 520, y: 180 },
      inputs: [{ name: 'result', schema: 'object' }],
      outputs: [],
      config: {},
    },
  ],
  edges: [
    { from: 'source.request', to: 'sink.answer', kind: 'data', from_port: 'payload', to_port: 'result' },
  ],
};

const system = {
  id: SYSTEM_ID,
  workspace_id: WORKSPACE_ID,
  name: 'Chrome v2 system',
  objective: 'Carry the chrome scenarios',
  status: 'draft',
  flow_definition: flowDefinition,
  flow_sha256: FLOW_HASH,
  created_at: '2026-09-24T08:00:00Z',
  updated_at: '2026-09-24T08:00:00Z',
};

/** Enough Systems for the list to scroll inside the shell `main`. */
const systems = [
  system,
  ...Array.from({ length: 59 }, (_, index) => ({
    ...system,
    id: `system-chrome-v2-${index}`,
    name: `Chrome v2 system ${index}`,
  })),
];

function localOnly(testInfo: TestInfo): boolean {
  const configured = testInfo.project.use.baseURL;
  if (typeof configured !== 'string') return false;
  try {
    const url = new URL(configured);
    return url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

async function mockCockpit(page: Page): Promise<void> {
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return route.fallback();
    return route.abort('blockedbyclient');
  });

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();

    if (path === '/auth/validate') {
      return json(route, { valid: true, user_id: 'user-chrome-v2', email: 'chrome@example.test', role: 'admin' });
    }
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/me') {
      return json(route, {
        id: 'user-chrome-v2',
        username: 'chrome',
        email: 'chrome@example.test',
        role: 'admin',
        is_active: true,
        mfa_enabled: false,
        workspaces: [workspace],
      });
    }
    if (path === '/help-content') {
      return json(route, { version: 'local', personas: [], languages: [], items: [] });
    }
    if (path === '/skills' && method === 'GET') return json(route, { skills: [] });
    if (path === '/capabilities' && method === 'GET') return json(route, { capabilities: [] });
    if (path === '/runs' && method === 'GET') return json(route, { runs: [] });
    if (path === '/systems' && method === 'GET') return json(route, { systems });
    if (path === `/systems/${SYSTEM_ID}` && method === 'GET') return json(route, system);
    if (path === `/systems/${SYSTEM_ID}` && method === 'PATCH') {
      const body = request.postDataJSON() as { flow_definition?: unknown };
      return json(route, { ...system, flow_definition: body.flow_definition, flow_sha256: '2'.repeat(64) });
    }
    // No publication route: the builder hydrates from `flow_definition`.
    if (path === `/systems/${SYSTEM_ID}/flow-state`) return json(route, { detail: 'Not Found' }, 404);
    if (path === `/systems/${SYSTEM_ID}/validate-flow` && method === 'POST') {
      return json(route, {
        flow_sha256: FLOW_HASH,
        analyzer_version: 'local-chrome-v2',
        runtime_mode: 'dag_strict',
        valid: true,
        issues: [],
      });
    }
    // The chrome loads more in the background than any scenario reads.
    if (method === 'GET') return json(route, {});
    return json(route, {}, 202);
  });

  await page.addInitScript(({ token, workspaceSlug }) => {
    localStorage.setItem('agentium_token', token);
    localStorage.setItem('agentium_workspace_slug', workspaceSlug);
    localStorage.setItem('agentium_locale', 'en');
  }, { token: TOKEN, workspaceSlug: WORKSPACE_SLUG });
}

test.describe('L1 — swallowed gestures', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1', 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked chrome net.');
    test.skip(!localOnly(testInfo), 'This mocked chrome net is local-only; set E2E_BASE_URL=http://localhost:4200.');
    await mockCockpit(page);
  });

  test('the sommaire goes from Data to Models and marks only the open one', async ({ page }) => {
    await page.goto('/data');
    const sommaire = page.getByRole('complementary', { name: 'Summary' });
    const data = sommaire.getByRole('link', { name: 'Data', exact: true });
    const models = sommaire.getByRole('link', { name: 'Models', exact: true });
    await expect(data).toHaveAttribute('aria-current', 'page');

    await models.click();
    await expect(page).toHaveURL(/\/models(\?|$)/);
    await expect(models).toHaveAttribute('aria-current', 'page');
    await expect(sommaire.locator('[aria-current="page"]')).toHaveCount(1);

    await data.click();
    await expect(page).toHaveURL(/\/data(\?|$)/);
    await expect(data).toHaveAttribute('aria-current', 'page');
  });

  test('the active item leads back to its list, then to the top of it', async ({ page }) => {
    await page.goto(`/systems/${SYSTEM_ID}`);
    const item = page.getByRole('complementary', { name: 'Summary' }).getByRole('link', { name: /^Systems(, back to the list)?$/ });
    await expect(item).toHaveAttribute('aria-current', 'page');
    await item.click();
    await expect(page).toHaveURL(/\/systems(\?|$)/);

    const main = page.locator('#main-content');
    await expect(main.getByRole('heading', { level: 1 })).toBeVisible();
    await main.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    expect(await main.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

    await item.click();
    await expect.poll(() => main.evaluate((element) => element.scrollTop)).toBe(0);
    await expect(main.getByRole('heading', { level: 1 })).toBeFocused();
    await expect(page).toHaveURL(/\/systems(\?|$)/);
  });

  test('⌘Z undoes on the canvas and zooms out from the chrome', async ({ page }) => {
    const flowUrl = new RegExp(`/systems/${SYSTEM_ID}/flow(\\?|$)`);
    await page.goto(`/systems/${SYSTEM_ID}/flow`);
    // The builder is the heaviest lazy chunk of the app.
    await expect(page.getByRole('heading', { level: 1, name: new RegExp(system.name) })).toBeVisible({
      timeout: 30_000,
    });
    const nodes = page.locator('app-flow-node');
    await expect(nodes).toHaveCount(2);

    await nodes.filter({ hasText: 'Answer' }).click();
    await page.keyboard.press('Delete');
    await expect(nodes).toHaveCount(1);
    // Undo waits while the autosave writes; let that write land first.
    await expect(page.locator('app-flow-toolbar .ck-flow-toolbar__state')).toHaveClass(/\bis-saved\b/);

    await page.keyboard.press('ControlOrMeta+z');
    await expect(nodes).toHaveCount(2);
    // A zoom-out would already be under way; give it the time to show.
    await page.waitForTimeout(500);
    await expect(page).toHaveURL(flowUrl);

    await page.getByRole('complementary', { name: 'Summary' })
      .getByRole('link', { name: /^Systems(, back to the list)?$/ })
      .focus();
    await page.keyboard.press('ControlOrMeta+z');
    await expect(page).not.toHaveURL(flowUrl);
  });
});

// --- L3 — Focus de route sur le titre ---------------------------------------

test.describe('L3 — route focus on the title', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1', 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked chrome net.');
    test.skip(!localOnly(testInfo), 'This mocked chrome net is local-only; set E2E_BASE_URL=http://localhost:4200.');
    await mockCockpit(page);
    // Impact is hidden in builder mode; L3 needs all three zones.
    const operatorWorkspace = { ...workspace, mode: 'operator' };
    await page.route('**/api/v1/auth/workspaces', async (route) => json(route, [operatorWorkspace]));
    await page.route(`**/api/v1/auth/workspaces/${WORKSPACE_SLUG}`, async (route) => json(route, operatorWorkspace));
    await page.route('**/api/v1/auth/me', async (route) => {
      return json(route, {
        id: 'user-chrome-v2',
        username: 'chrome',
        email: 'chrome@example.test',
        role: 'admin',
        is_active: true,
        mfa_enabled: false,
        workspaces: [operatorWorkspace],
      });
    });
  });

  test('Enter on a rail item focuses the h1 without a ring; Tab shows a 2px ring', async ({ page }) => {
    await page.goto('/systems');
    const title = page.locator('#main-content h1').first();
    await expect(title).toBeVisible({ timeout: 30_000 });

    const operate = page.locator('app-side-rail').getByRole('link', { name: /Monitor|Suivre|Operate/i });
    await operate.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/runs(\?|$)/);

    const h1 = page.locator('#main-content h1').first();
    await expect.poll(async () => h1.evaluate((el) => document.activeElement === el)).toBe(true);
    expect(await h1.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe('none');

    const status = page.locator('.shell-route-status');
    await expect(status).toHaveAttribute('role', 'status');
    await expect.poll(async () => (await status.textContent())?.trim() ?? '').not.toBe('');

    await page.keyboard.press('Tab');
    const ring = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return null;
      const style = getComputedStyle(el);
      return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
    });
    expect(ring?.outlineStyle).not.toBe('none');
    expect(ring?.outlineWidth).toBe('2px');
  });

  test('axe-core finds no violations on Impact, Create and Monitor', async ({ page }) => {
    const AxeBuilder = (await import('@axe-core/playwright')).default;

    for (const path of ['/hypervisor', '/systems', '/runs'] as const) {
      await page.goto(path);
      await expect(page.locator('#main-content h1').first()).toBeVisible({ timeout: 30_000 });
      // Same WCAG AA tag set as the accessibility matrix canary — not best-practice extras.
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(results.violations, `${path}: ${results.violations.map((v) => v.id).join(', ')}`).toEqual([]);
    }
  });
});

// --- L4 — Tokens v2 and fonts -----------------------------------------------

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';

const WORKSPACE = {
  id: 'ws-chrome-v2',
  name: 'Agentium Showcase',
  slug: 'chrome-v2',
  role: 'admin',
};

const USER = {
  id: 'user-chrome-v2',
  email: 'ada@example.test',
  role: 'admin',
  is_active: true,
  mfa_enabled: false,
  first_name: 'Ada',
  last_name: 'Lovelace',
  workspaces: [WORKSPACE],
};

async function installMocks(page: Page, theme: 'dark' | 'light' = 'dark'): Promise<void> {
  await page.addInitScript(({ slug, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-chrome-v2');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', theme);
    localStorage.setItem('agentium_locale', 'fr');
  }, { slug: WORKSPACE.slug, theme });

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const apiPath = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();

    if (apiPath === '/auth/validate' && method === 'POST') {
      return json(route, { valid: true, user_id: USER.id, email: USER.email, role: USER.role });
    }
    if (apiPath === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (apiPath === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (apiPath === '/auth/me') return json(route, USER);
    if (apiPath === '/iam/matrix') {
      return json(route, {
        workspace: { id: WORKSPACE.id, slug: WORKSPACE.slug, name: WORKSPACE.name },
        subject_user_id: USER.id,
        role_template: 'workspace_admin',
        custom_labels: [],
        role_flags: {},
        enforcement: true,
        permissions: [],
      });
    }
    if (apiPath === '/systems') return json(route, []);
    // An empty object makes the help tooltips throw on every change detection.
    if (apiPath === '/help-content') {
      return json(route, { version: 'local', personas: [], languages: [], items: [] });
    }

    if (method === 'GET') {
      if (apiPath.endsWith('s') || apiPath.includes('items')) return json(route, []);
      return json(route, {});
    }
    return json(route, { ok: true });
  });
}

const SHOT_DIR = process.env['E2E_SHOT_DIR'] ?? 'test-results/chrome-v2-shots';

function shot(name: string): string {
  return `${SHOT_DIR}/${name}`;
}

function daysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

function experience(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    version: 1,
    persona: 'operator',
    journey: 'northforge_sources',
    completed_steps: [],
    dismissed: true,
    example_available: false,
    ...overrides,
  };
}

/** L27 — the member experience record that drives the readable rail. */
async function mockExperience(page: Page, overrides: Record<string, unknown>): Promise<void> {
  let state = experience(overrides);
  await page.route(`**/api/v1/auth/workspaces/${WORKSPACE.slug}/me/experience`, async (route) => {
    if (route.request().method() === 'PATCH') {
      state = { ...state, ...(route.request().postDataJSON() as Record<string, unknown>) };
    }
    return json(route, state);
  });
}

/** Left edge of the first laid-out column after the rail (sommaire or main). */
async function firstContentX(page: Page): Promise<number> {
  return page.evaluate(() => {
    const rail = document.querySelector('app-side-rail');
    const candidates = [
      document.querySelector('app-mini-rail aside'),
      document.querySelector('#main-content'),
    ].filter((el): el is Element => !!el && el.getBoundingClientRect().width > 0);
    const railRight = rail ? rail.getBoundingClientRect().right : 0;
    return Math.round(Math.min(...candidates.map((el) => el.getBoundingClientRect().x), Infinity) || railRight);
  });
}

test.describe('Chrome v2 — mocked', () => {
  test.use({ locale: 'fr-FR', colorScheme: 'dark' });
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked chrome safety net');

  test('L4 — titles in Space Grotesk, text in IBM Plex Sans, no Inter nor JetBrains Mono', async ({ page }) => {
    const fontRequests: string[] = [];
    page.on('request', (request) => {
      if (/fonts\.(?:googleapis|gstatic)\.com/.test(request.url())) fontRequests.push(request.url());
    });
    await installMocks(page);
    await page.goto('/systems');

    const title = page.locator('#main-content h1').first();
    await expect(title).toBeVisible({ timeout: 30_000 });
    await expect
      .poll(() => page.evaluate(() => [...document.fonts].some(
        (face) => face.family.replace(/["']/g, '') === 'Space Grotesk' && face.status === 'loaded',
      )))
      .toBe(true);

    expect(await page.evaluate(() => document.fonts.check('600 24px "Space Grotesk"'))).toBe(true);
    expect(await title.evaluate((element) => getComputedStyle(element).fontFamily)).toMatch(/^"?Space Grotesk"?,/);
    expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toMatch(/^"?IBM Plex Sans"?,/);
    expect(
      await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--ck-cta-bg').trim()),
    ).toBe('#1fb8cc');
    expect(fontRequests.some((url) => url.includes('/s/spacegrotesk/'))).toBe(true);
    expect(fontRequests.filter((url) => /family=(?:Inter|JetBrains)|\/s\/(?:inter|intertight|jetbrainsmono)\//i.test(url))).toEqual([]);
  });

  test('L6/L27 — hidden labels: icon rail stays 56px, tooltip on Tab, Escape closes, no link-name', async ({ page }) => {
    await installMocks(page);
    await mockExperience(page, { rail_labels: 'hidden', first_seen_at: daysAgo(2) });
    await page.goto('/systems');

    const rail = page.locator('app-side-rail .ck-rail');
    await expect(rail).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('rail-labels-toggle')).toHaveAttribute('aria-pressed', 'false');

    const widthAtRest = await rail.evaluate((el) => el.getBoundingClientRect().width);
    expect(Math.round(widthAtRest)).toBe(56);

    const main = page.locator('#main-content');
    const mainXBefore = (await main.boundingBox())!.x;
    expect(await firstContentX(page)).toBe(56);

    await rail.hover({ position: { x: 28, y: 80 } });
    expect(Math.round(await rail.evaluate((el) => el.getBoundingClientRect().width))).toBe(56);
    expect((await main.boundingBox())!.x).toBe(mainXBefore);

    const firstLink = page.locator('app-side-rail a.ck-rail-item').first();
    await firstLink.focus();
    // Keyboard focus so :focus-visible opens the tooltip immediately.
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Tab');
    await expect(firstLink).toBeFocused();

    const tooltip = page.locator('app-side-rail [role="tooltip"]');
    await expect(tooltip).toBeVisible();
    const describedBy = await firstLink.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(await tooltip.getAttribute('id')).toBe(describedBy);
    await expect(firstLink).toHaveAttribute('aria-label', /.+/);

    await page.keyboard.press('Escape');
    await expect(tooltip).toHaveCount(0);
    await expect(firstLink).not.toHaveAttribute('aria-describedby');

    const axe = await new AxeBuilder({ page })
      .include('app-side-rail')
      .withRules(['link-name'])
      .analyze();
    expect(axe.violations).toEqual([]);
  });

  test('L27 — before the preference is known the rail never flashes labels', async ({ page }) => {
    await installMocks(page);
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route(`**/api/v1/auth/workspaces/${WORKSPACE.slug}/me/experience`, async (route) => {
      await held;
      return json(route, experience({ rail_labels: 'auto', first_seen_at: daysAgo(1) }));
    });
    await page.goto('/systems');
    const rail = page.locator('app-side-rail .ck-rail');
    await expect(rail).toBeVisible({ timeout: 30_000 });
    expect(Math.round(await rail.evaluate((el) => el.getBoundingClientRect().width))).toBe(56);
    await expect(page.getByTestId('rail-labels-toggle')).toHaveCount(0);
    release();
    await expect.poll(() => rail.evaluate((el) => Math.round(el.getBoundingClientRect().width))).toBe(184);
  });

  for (const theme of ['dark', 'light'] as const) {
    test(`L27 — a newcomer's labelled rail pushes the content, names = labels, axe clean (${theme})`, async ({ page }) => {
      await installMocks(page, theme);
      await mockExperience(page, { rail_labels: 'auto', first_seen_at: daysAgo(2) });
      await page.goto('/systems');

      const rail = page.locator('app-side-rail .ck-rail');
      await expect(rail).toBeVisible({ timeout: 30_000 });
      await expect.poll(() => rail.evaluate((el) => Math.round(el.getBoundingClientRect().width))).toBe(184);
      const host = await page.locator('app-side-rail').boundingBox();
      expect(Math.round(host!.width)).toBe(184);
      // Pushed, never covered: the first content column starts at the rail edge.
      expect(await firstContentX(page)).toBe(184);
      expect((await page.locator('#main-content').boundingBox())!.x).toBeGreaterThanOrEqual(184);
      // Width changes are instant: no transition on the rail.
      expect(await page.locator('app-side-rail').evaluate((el) => getComputedStyle(el).transitionDuration)).toBe('0s');

      const links = page.locator('app-side-rail nav a.ck-rail-item');
      const count = await links.count();
      expect(count).toBeGreaterThan(2);
      for (let i = 0; i < count; i += 1) {
        const link = links.nth(i);
        const text = (await link.innerText()).trim();
        expect(text.length).toBeGreaterThan(0);
        await expect(link).toHaveAccessibleName(text);
        await expect(link).not.toHaveAttribute('aria-label');
      }
      await expect(page.locator('app-side-rail nav a[aria-current="page"]')).toHaveCount(1);

      const toggle = page.getByTestId('rail-labels-toggle');
      await expect(toggle).toHaveAttribute('aria-pressed', 'true');
      await expect(toggle).toHaveAccessibleName('Libellés du rail');
      const toggleBox = await toggle.boundingBox();
      expect(toggleBox!.height).toBeGreaterThanOrEqual(24);

      await links.first().hover();
      await expect(page.locator('app-side-rail [role="tooltip"]')).toHaveCount(0);

      await page.screenshot({ path: shot(`rail-labelled-${theme}.png`) });
      // The sommaire's active item misses 4.5:1 in light (#0a7483 on #dfeaed,
      // 4.46:1) — owned by the sommaire lot, reported there, excluded here.
      const results = await new AxeBuilder({ page })
        .exclude('app-mini-rail')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(results.violations, results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`).join('\n')).toEqual([]);

      await page.getByTestId('rail-labels-toggle').click();
      await expect.poll(() => rail.evaluate((el) => Math.round(el.getBoundingClientRect().width))).toBe(56);
      await page.screenshot({ path: shot(`rail-icons-${theme}.png`) });
      const hidden = await new AxeBuilder({ page })
        .exclude('app-mini-rail')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(hidden.violations, hidden.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`).join('\n')).toEqual([]);
    });
  }

  test('L27 — the toggle saves at once, by keyboard, and a failed save reverts politely', async ({ page }) => {
    await installMocks(page);
    const writes: unknown[] = [];
    let failNext = true;
    let state = experience({ rail_labels: 'auto', first_seen_at: daysAgo(3) });
    await page.route(`**/api/v1/auth/workspaces/${WORKSPACE.slug}/me/experience`, async (route) => {
      if (route.request().method() === 'PATCH') {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        writes.push(body);
        if (failNext) {
          failNext = false;
          return json(route, { detail: 'unavailable' }, 503);
        }
        state = { ...state, ...body };
        return json(route, state);
      }
      return json(route, state);
    });
    await page.goto('/systems');
    const rail = page.locator('app-side-rail .ck-rail');
    await expect.poll(() => rail.evaluate((el) => Math.round(el.getBoundingClientRect().width)), { timeout: 30_000 }).toBe(184);

    const toggle = page.getByTestId('rail-labels-toggle');
    await toggle.focus();
    await page.keyboard.press('Space');
    // The write failed: labels come back and the status says so.
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    const status = page.locator('app-side-rail [role="status"]');
    await expect(status).toHaveText('Préférence non enregistrée. Réessayez.');
    await expect(status).toBeVisible();
    await page.screenshot({ path: shot('rail-save-failed-dark.png') });

    await page.keyboard.press('Enter');
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await expect(toggle).toBeFocused();
    expect(Math.round(await rail.evaluate((el) => el.getBoundingClientRect().width))).toBe(56);
    await expect(status).toHaveText('');
    await expect.poll(() => writes).toEqual([{ rail_labels: 'hidden' }, { rail_labels: 'hidden' }]);
  });

  for (const theme of ['dark', 'light'] as const) {
    test(`L27 — ⌘K asks the agent when nothing matches and defines lexicon terms (${theme})`, async ({ page }) => {
      // The chat overlay is a heavy lazy chunk on a cold dev server.
      test.setTimeout(120_000);
      await installMocks(page, theme);
      await mockExperience(page, { rail_labels: 'hidden', first_seen_at: daysAgo(30) });
      await page.goto('/systems');
      await expect(page.locator('#main-content h1').first()).toBeVisible({ timeout: 30_000 });

      await page.keyboard.press('ControlOrMeta+k');
      const input = page.getByRole('combobox');
      await expect(input).toBeFocused();
      await expect(input).toHaveAttribute('aria-expanded', 'true');
      const listbox = page.getByRole('listbox');
      await expect(input).toHaveAttribute('aria-controls', (await listbox.getAttribute('id'))!);

      await input.fill('quels runs ont échoué hier');
      const first = listbox.getByRole('option').first();
      await expect(first).toContainText('Demander à l’agent : “quels runs ont échoué hier”');
      await expect(first).toHaveAttribute('aria-selected', 'true');
      await expect(input).toHaveAttribute('aria-activedescendant', (await first.getAttribute('id'))!);
      await expect(page.locator('app-command-palette [role="status"]')).toHaveText('Aucune commande ne correspond. Entrée pour demander à l’agent.');
      await page.screenshot({ path: shot(`palette-agent-${theme}.png`) });
      const axePalette = await new AxeBuilder({ page })
        .include('app-command-palette')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(axePalette.violations, axePalette.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`).join('\n')).toEqual([]);

      await input.fill('brouillon');
      const define = listbox.getByRole('option', { name: /Qu’est-ce que Brouillon/ });
      await expect(define).toBeVisible();
      await expect(define).toContainText('Une version encore modifiable');
      await page.screenshot({ path: shot(`palette-definition-${theme}.png`) });

      await input.fill('quels runs ont échoué hier');
      await page.keyboard.press('Enter');
      await expect(page.locator('app-command-palette [role="dialog"]')).toHaveCount(0);
      const chatInput = page.locator('app-chat-overlay textarea[name="userInput"]');
      await expect(chatInput).toHaveValue('quels runs ont échoué hier', { timeout: 15_000 });
      await page.screenshot({ path: shot(`chat-prefilled-${theme}.png`) });
    });
  }
});

// --- L5 — Visual guardrails (cliquet) + reduced-motion orb -----------------

test.describe('L5 — chrome ratchet / reduced-motion orb', () => {
  test.use({ locale: 'fr-FR', colorScheme: 'dark' });
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked chrome safety net');

  test('reduced-motion freezes the auth thinking orb across 500 ms', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.addInitScript(() => {
      localStorage.removeItem('agentium_token');
      localStorage.removeItem('agentium_workspace_slug');
      localStorage.setItem('agentium_locale', 'en');
      localStorage.setItem('agentium_theme', 'dark');
    });
    await page.route('**/api/v1/**', async (route) => {
      const method = route.request().method();
      if (method === 'GET') return json(route, {});
      return json(route, { ok: true });
    });

    await page.goto('/auth/signin');
    const canvas = page.locator('ck-thinking-orb canvas').first();
    await expect(canvas).toBeVisible({ timeout: 30_000 });

    const first = await canvas.evaluate((node) => (node as HTMLCanvasElement).toDataURL('image/png'));
    await page.waitForTimeout(500);
    const second = await canvas.evaluate((node) => (node as HTMLCanvasElement).toDataURL('image/png'));
    expect(second).toBe(first);
  });
});

// --- L30 — Chat C2: the overlay as a sourced working thread ------------------

const THREAD_SESSION = 'session-l30';
const THREAD_WORKSPACE = {
  ...WORKSPACE,
  settings: {
    knowledge_scopes: [
      { key: 'politiques-release', label: 'Politiques de release', is_default: true, collection_slugs: ['politiques-release'] },
    ],
  },
};
const THREAD_SOURCES = [
  {
    document_id: 'doc-policy',
    collection: 'politiques-release',
    title: 'Politique d’exécution immuable v2.pdf',
    page: 3,
    score: 0.91,
    snippet: '3.1 Une exécution terminée est immuable. 3.2 La relance réutilise exactement les entrées de l’exécution d’origine et produit une nouvelle exécution, liée à la première. 3.3 Les journaux restent attachés à l’exécution d’origine.',
  },
  {
    document_id: 'doc-guide',
    collection: 'politiques-release',
    title: 'Guide de qualification release.md',
    chunk_index: 14,
    score: 0.84,
    snippet: 'Une relance se déclenche depuis la fiche de l’exécution ; elle ne modifie jamais les entrées d’origine.',
  },
  {
    document_id: 'doc-checklist',
    collection: 'politiques-release',
    title: 'Checklist mise en production.docx',
    chunk_index: 2,
    score: 0.62,
    snippet: 'Vérifier les approbations avant la mise en production.',
  },
];

function sse(frames: Record<string, unknown>[]): string {
  return frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('');
}

/** The mocked turn: real-looking step events, then sources on the first token. */
async function mockThread(page: Page): Promise<void> {
  await page.route(`**/api/v1/auth/workspaces/${WORKSPACE.slug}`, async (route) => json(route, THREAD_WORKSPACE));
  await page.route('**/api/v1/auth/workspaces', async (route) => json(route, [THREAD_WORKSPACE]));
  await page.route('**/api/v1/sessions', async (route) => {
    if (route.request().method() === 'POST') return json(route, { id: THREAD_SESSION, title: 'Relance' });
    return json(route, { sessions: [] });
  });
  await page.route('**/api/v1/chat/stream', async (route) => route.fulfill({
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
    body: sse([
      { chunk_type: 'session', session_id: THREAD_SESSION },
      { chunk_type: 'decision_step', decision_step: { id: 's1', type: 'query_analysis', title: 'Analyse de la question', status: 'completed', duration: 120 } },
      { chunk_type: 'decision_step', decision_step: { id: 's2', type: 'retrieve', title: 'Recherche dans Politiques de release', status: 'completed', duration: 640, description: 'Retrieved 3 chunks' } },
      { chunk_type: 'decision_step', decision_step: { id: 's3', type: 'context_filtering', title: 'Lecture des passages', status: 'completed', duration: 210 } },
      { chunk_type: 'decision_step', decision_step: { id: 's4', type: 'synthesis', title: 'Rédaction de la réponse', status: 'completed', duration: 930 } },
      { chunk_type: 'text', content: 'Non. Une exécution terminée reste immuable. ', sources: THREAD_SOURCES },
      { chunk_type: 'text', content: 'La relance crée une nouvelle exécution liée, avec exactement les mêmes entrées [1]. Elle se déclenche depuis la fiche de l’exécution [2].' },
      // The SSE service emits the final `done` itself when the body ends.
    ]),
  }));
}

test.describe('L30 — chat overlay: sourced thread and open proof', () => {
  test.use({ locale: 'fr-FR' });
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked chrome safety net');

  for (const theme of ['dark', 'light'] as const) {
    test(`⌘J, a streamed answer, citation [1] opened by keyboard, Escape gives focus back (${theme})`, async ({ page }) => {
      test.setTimeout(120_000);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.emulateMedia({ colorScheme: theme });
      await installMocks(page, theme);
      await mockExperience(page, { rail_labels: 'hidden', first_seen_at: daysAgo(30) });
      await mockThread(page);
      await page.goto('/systems');
      await expect(page.locator('#main-content h1').first()).toBeVisible({ timeout: 30_000 });

      await page.keyboard.press('ControlOrMeta+j');
      const overlay = page.locator('app-chat-overlay');
      const input = overlay.locator('textarea[name="userInput"]');
      await expect(input).toBeVisible({ timeout: 30_000 });
      await expect(overlay.getByTestId('chat-overlay-meta')).toHaveText('Sources : Politiques de release');
      const chips = overlay.getByTestId('chat-thread-chips');
      await expect(chips).toContainText('Politiques de release');
      // No voice runtime is mocked: the chip must not promise one.
      await expect(chips).not.toContainText('Voix disponible');
      await expect(overlay.getByTestId('chat-thread-advanced')).toHaveAttribute('aria-expanded', 'false');

      // L31 — only the toolbar sits above the question: the context picker
      // waits behind « Avancé », the session documents are a composer button.
      await expect(overlay.getByTestId('chat-thread-context')).toHaveCount(0);
      await expect(overlay.locator('.t-header, .t-sidebar')).toHaveCount(0);
      const history = overlay.getByTestId('chat-overlay-history');
      await expect(history).toHaveText('Historique');
      await expect(history).toHaveCSS('text-transform', 'none');
      const footer = overlay.getByTestId('chat-overlay-footer');
      await expect(footer).toHaveText('Enregistrée dans Suivre › Conversations');
      await expect(footer).toHaveCSS('text-transform', 'none');
      const attach = overlay.getByRole('button', { name: 'Documents de session' });
      await expect(attach).toHaveAttribute('aria-expanded', 'false');
      await attach.click();
      await expect(attach).toHaveAttribute('aria-expanded', 'true');
      await expect(overlay.getByLabel('Ajouter des documents à la session')).toHaveAttribute('type', 'file');
      await attach.click();
      await expect(overlay.getByTestId('chat-thread-attach-panel')).toHaveCount(0);

      await input.fill('Peut-on relancer une exécution terminée avec d’autres entrées ?');
      await input.press('Enter');

      await expect(overlay.getByTestId('chat-thread-question')).toContainText('Vous ·');
      const trace = overlay.getByTestId('chat-work-trace');
      await expect(trace).toContainText('Recherche');
      await expect(trace).toContainText('Lecture');
      await expect(trace).toContainText('Rédaction');
      await expect(trace).toContainText('4 étapes');
      await expect(overlay.getByTestId('chat-thread-counts')).toHaveText('3 passages · 2 cités');
      // L31 — « Exécutions · Qualité » sit in the answer's action row, not on a line of their own.
      const links = overlay.locator('.ck-thread-actions').getByTestId('chat-thread-links');
      await expect(links.getByRole('link', { name: 'Exécutions' })).toBeVisible();
      await expect(links.getByRole('link', { name: 'Qualité' })).toBeVisible();
      await expect(overlay.locator('.ck-thread-summary')).toHaveCount(0);

      const cite = overlay.locator('[data-proof-cite$=":1"]').first();
      await cite.focus();
      await page.keyboard.press('Enter');
      const rail = overlay.getByTestId('chat-proof-rail');
      await expect(rail).toBeVisible();
      await expect(rail.getByRole('heading', { name: 'Preuve ouverte' })).toBeFocused();
      await expect(rail.getByTestId('chat-proof-selected')).toContainText('Politique d’exécution immuable v2.pdf');
      await expect(rail.getByTestId('chat-proof-selected')).toContainText('Politiques de release · p. 3');
      await expect(rail.getByTestId('chat-proof-mark')).toHaveText(
        '3.2 La relance réutilise exactement les entrées de l’exécution d’origine et produit une nouvelle exécution, liée à la première.',
      );
      await expect(rail.getByRole('button', { name: /Ouvrir la preuve 2/ })).toBeVisible();
      await expect(rail.getByRole('button', { name: /lu, non cité/ })).toContainText('Lue, non citée');
      await expect(cite).toHaveAttribute('aria-current', 'true');
      // Rail and thread side by side: the panel widened instead of covering.
      const railBox = await rail.boundingBox();
      const inputBox = await input.boundingBox();
      expect(railBox && inputBox && railBox.x >= inputBox.x + inputBox.width).toBeTruthy();
      await page.screenshot({ path: shot(`l30-chat-proof-${theme}.png`) });

      const axe = await new AxeBuilder({ page })
        .include('app-chat-overlay')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(axe.violations, axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`).join('\n')).toEqual([]);

      await page.keyboard.press('Escape');
      await expect(rail).toHaveCount(0);
      await expect(cite).toBeFocused();
      await expect(input).toBeVisible();
      await page.screenshot({ path: shot(`l30-chat-thread-${theme}.png`) });

      // « Avancé » opens the model and retrieval controls above the composer.
      const advanced = overlay.getByTestId('chat-thread-advanced');
      await advanced.click();
      await expect(advanced).toHaveAttribute('aria-expanded', 'true');
      // L31 — the context picker lives here now, and the voice controls speak French.
      const advancedPanel = overlay.getByTestId('chat-thread-advanced-panel');
      await expect(advancedPanel.getByRole('combobox', { name: 'Contexte' })).toBeVisible();
      await expect(advancedPanel).toContainText('Moteur vocal');
      await expect(advancedPanel).toContainText('Contexte en direct');
      for (const english of ['Voice runtime', 'Batch', 'Live context', 'Auto-send', 'Realtime']) {
        await expect(advancedPanel).not.toContainText(english);
      }
      await page.screenshot({ path: shot(`l30-chat-advanced-${theme}.png`) });
      await attach.click();
      await expect(overlay.getByTestId('chat-thread-attach-panel')).toBeVisible();
      const axeOpen = await new AxeBuilder({ page })
        .include('app-chat-overlay')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(axeOpen.violations, axeOpen.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`).join('\n')).toEqual([]);
      await page.screenshot({ path: shot(`l31-chat-advanced-attach-${theme}.png`) });
      await attach.click();
      await advanced.click();
      await expect(advanced).toHaveAttribute('aria-expanded', 'false');

      // A phone has no room for a second column: the proof covers the thread.
      await page.setViewportSize({ width: 390, height: 844 });
      await cite.click();
      await expect(rail).toBeVisible();
      await page.screenshot({ path: shot(`l30-chat-proof-narrow-${theme}.png`) });
      await page.keyboard.press('Escape');
      await expect(rail).toHaveCount(0);
      await expect(cite).toBeFocused();
    });
  }
});

// --- L31 — finishing touches -------------------------------------------------

test.describe('L31 — sentence case, one filled button, honest bottom bar', () => {
  test.use({ locale: 'fr-FR' });
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked chrome safety net');

  for (const theme of ['dark', 'light'] as const) {
    test(`/systems reads in sentence case with a single filled button; axe (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme });
      await installMocks(page, theme);
      await mockExperience(page, { rail_labels: 'hidden', first_seen_at: daysAgo(30) });
      await page.goto('/systems');
      const main = page.locator('#main-content');
      await expect(main.locator('h1').first()).toBeVisible({ timeout: 30_000 });
      await expect(main.getByText('Créer · Systèmes', { exact: true })).toBeVisible();
      await expect(main.getByTestId('page-frame-status')).toHaveText('0 actif');
      await expect(main.getByTestId('systems-count')).toHaveText('Systèmes · 0');
      const create = main.getByTestId('systems-new');
      const first = main.getByTestId('systems-create-first');
      await expect(first).toHaveText(/Créer le premier système/);
      for (const control of [create, first, main.getByTestId('systems-compose'), main.getByRole('button', { name: 'Analyse contrats' })]) {
        await expect(control).toHaveCSS('text-transform', 'none');
        await expect(control).not.toHaveCSS('font-family', /Plex Mono|monospace/i);
      }
      // The empty state leads: its button is the only filled one.
      await expect(first).toHaveClass(/ck-cta/);
      await expect(create).not.toHaveClass(/ck-cta/);
      await expect(main.locator('.ck-cta')).toHaveCount(1);

      const bar = page.locator('app-command-bar');
      await expect(bar).toContainText('Plateforme opérationnelle');
      await expect(bar).not.toContainText('Système opérationnel');
      await expect(bar.getByTestId('command-bar-version')).toHaveText('v0.4.0 · build 1');
      await expect(bar.getByTestId('command-bar-version')).toHaveCSS('text-transform', 'none');
      await expect(bar.getByText('Plateforme opérationnelle')).toHaveCSS('text-transform', 'none');
      await page.screenshot({ path: shot(`l31-systems-${theme}.png`) });

      const axe = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(axe.violations, axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`).join('\n')).toEqual([]);
    });
  }

  test('a builder keeps a compact context control beside the scope, no « Avancé »', async ({ page }) => {
    test.setTimeout(90_000);
    await installMocks(page, 'dark');
    await mockExperience(page, { rail_labels: 'hidden', first_seen_at: daysAgo(30) });
    await mockThread(page);
    const builder = { ...THREAD_WORKSPACE, mode: 'builder' };
    await page.route(`**/api/v1/auth/workspaces/${WORKSPACE.slug}`, async (route) => json(route, builder));
    await page.route('**/api/v1/auth/workspaces', async (route) => json(route, [builder]));
    await page.goto('/systems');
    await expect(page.locator('#main-content h1').first()).toBeVisible({ timeout: 30_000 });
    await page.keyboard.press('ControlOrMeta+j');
    const overlay = page.locator('app-chat-overlay');
    await expect(overlay.locator('textarea[name="userInput"]')).toBeVisible({ timeout: 30_000 });
    const chips = overlay.getByTestId('chat-thread-chips');
    await expect(chips.getByRole('combobox', { name: 'Contexte' })).toBeVisible();
    await expect(overlay.getByTestId('chat-thread-advanced')).toHaveCount(0);
    await expect(overlay.locator('.t-header')).toHaveCount(0);
    await page.screenshot({ path: shot('l31-chat-builder-dark.png') });
  });
});
