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
    const item = page.getByRole('complementary', { name: 'Summary' }).getByRole('link', { name: 'Systems', exact: true });
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
      .getByRole('link', { name: 'Systems', exact: true })
      .focus();
    await page.keyboard.press('ControlOrMeta+z');
    await expect(page).not.toHaveURL(flowUrl);
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

async function installMocks(page: Page): Promise<void> {
  await page.addInitScript((slug) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-chrome-v2');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', 'dark');
    localStorage.setItem('agentium_locale', 'fr');
  }, WORKSPACE.slug);

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

    if (method === 'GET') {
      if (apiPath.endsWith('s') || apiPath.includes('items')) return json(route, []);
      return json(route, {});
    }
    return json(route, { ok: true });
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

  test('L6 — icon rail stays 56px, tooltip on Tab, Escape closes, no link-name', async ({ page }) => {
    await installMocks(page);
    await page.goto('/systems');

    const rail = page.locator('app-side-rail .ck-rail');
    await expect(rail).toBeVisible({ timeout: 30_000 });

    const widthAtRest = await rail.evaluate((el) => el.getBoundingClientRect().width);
    expect(Math.round(widthAtRest)).toBe(56);

    const main = page.locator('#main-content');
    const mainXBefore = (await main.boundingBox())!.x;

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
});
