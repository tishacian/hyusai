import { expect, test, type Locator, type Page, type Route } from '@playwright/test';
import { runAccessibilityMatrix } from '../fixtures/accessibility-matrix';

/**
 * Measured finish (UI/UX plan, lot 1): the geometry defects measured on
 * 20 October, re-measured on the shared components that caused them.
 *
 * Opt-in, with no backend (same flag as the other mocked specs):
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4238
 *   npx playwright test e2e/tests/72-finish-geometry-mocked.spec.ts --trace=off
 *
 * `E2E_SHOT_DIR` keeps one capture per screen and theme for the review.
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const SHOT_DIR = process.env['E2E_SHOT_DIR'] ?? '';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1470, height: 776 } });

type Theme = 'dark' | 'light';
type Locale = 'fr' | 'en';

const WORKSPACE = {
  id: 'ws-finish',
  name: 'NAWA',
  slug: 'nawa-finish',
  role: 'owner',
  role_template: 'workspace_owner',
  mode: 'builder',
  settings: { features: { experience_v1: true, adoption_experience_v1: true, service_contracts: true } },
};

const USER = {
  id: 'user-finish',
  email: 'ada@example.test',
  role: 'admin',
  is_active: true,
  mfa_enabled: false,
  first_name: 'Ada',
  last_name: 'Lovelace',
  workspaces: [WORKSPACE],
};

const LONG_GROUPS = [
  'Purchasing department, Middle East region',
  'Plant maintenance supervisors',
  'Finance controllers',
];

const APPS = [
  {
    id: 'app-draft',
    slug: 'pr-to-po',
    name: 'Purchase requisition to purchase order',
    pattern: 'workbench',
    status: 'draft',
    deployments: [],
    access_policy: { groups: LONG_GROUPS },
  },
  {
    id: 'app-live',
    slug: 'claims',
    name: 'Claims review',
    pattern: 'workbench',
    status: 'published',
    deployments: [{ channel: 'live', version: 3, audience: { groups: LONG_GROUPS } }],
  },
];

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function install(page: Page, theme: Theme, locale: Locale): Promise<void> {
  await page.route('**/*', (route) => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ slug, theme, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-finish');
    localStorage.setItem('agentium_workspace_slug', slug);
    // Only the first visit: the accessibility matrix switches both afterwards.
    if (!localStorage.getItem('agentium_theme')) localStorage.setItem('agentium_theme', theme);
    if (!localStorage.getItem('agentium_locale')) localStorage.setItem('agentium_locale', locale);
  }, { slug: WORKSPACE.slug, theme, locale });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const apiPath = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (apiPath === '/auth/validate') {
      return json(route, { valid: true, user_id: USER.id, email: USER.email, role: USER.role });
    }
    if (apiPath === '/auth/me') return json(route, USER);
    if (apiPath === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (apiPath === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (apiPath === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (apiPath === '/experiences') return json(route, { experiences: APPS });
    if (apiPath === '/work') return json(route, { apps: [] });
    if (apiPath === '/work/_home') return json(route, { items: [], jobs: [], receipts: [], counts: {} });
    if (request.method() === 'GET') {
      if (apiPath.endsWith('s') || apiPath.includes('items')) return json(route, []);
      return json(route, {});
    }
    return json(route, { ok: true });
  });
}

async function box(locator: Locator) {
  await expect(locator).toBeVisible();
  const value = await locator.boundingBox();
  if (!value) throw new Error('element has no box');
  return value;
}

async function lineCount(locator: Locator): Promise<number> {
  return locator.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const tops = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top)));
    return tops.size;
  });
}

async function shot(page: Page, name: string): Promise<void> {
  if (!SHOT_DIR) return;
  await page.screenshot({ path: `${SHOT_DIR}/${name}.png`, fullPage: false });
}

test.describe('Measured finish — shared geometry', () => {
  test.skip(!enabled, 'Enable E2E_CHROME_V2_MOCKED for isolated QA');

  for (const theme of ['dark', 'light'] as const) {
    test(`Work anchors are buttons at least 32 px high (${theme})`, async ({ page }) => {
      await install(page, theme, 'en');
      await page.goto('/work');
      const services = page.getByRole('link', { name: 'Services and deliveries' });
      expect((await box(services)).height).toBeGreaterThanOrEqual(32);
      const creator = page.locator('.xp-work-creator');
      const creatorBox = await box(creator);
      expect(creatorBox.height).toBeGreaterThanOrEqual(32);
      const label = await box(creator.locator('.xp-work-creator-label'));
      expect(Math.abs((label.y + label.height / 2) - (creatorBox.y + creatorBox.height / 2))).toBeLessThanOrEqual(0.5);
      await shot(page, `work-${theme}`);
    });

    test(`the title-bar glyph is centred on its label (${theme})`, async ({ page }) => {
      await install(page, theme, 'en');
      await page.goto('/connectors/connections');
      const toggle = page.locator('.tb-workspace-toggle');
      const label = await box(toggle.locator('.tb-workspace-name'));
      const glyph = await box(toggle.locator('ck-glyph.tb-workspace-arrow svg'));
      expect(Math.abs((glyph.y + glyph.height / 2) - (label.y + label.height / 2))).toBeLessThanOrEqual(0.5);
    });

    test(`Connections sits in the page frame, with one main landmark (${theme})`, async ({ page }) => {
      await install(page, theme, 'en');
      await page.goto('/connectors/connections');
      const main = await box(page.locator('main#main-content'));
      const h1 = await box(page.getByRole('heading', { level: 1 }).first());
      expect(h1.x - main.x).toBeGreaterThanOrEqual(24);
      expect(h1.y - main.y).toBeGreaterThanOrEqual(24);
      await expect(page.locator('main')).toHaveCount(1);
      await shot(page, `connections-${theme}`);
    });

    test(`wizard groups are 20 px apart and keep their 6 px inner gap (${theme})`, async ({ page }) => {
      await install(page, theme, 'en');
      await page.goto('/create/apps/new');
      const fields = page.locator('.xp-wizard-body > .xp-field');
      await expect(fields.nth(1)).toBeVisible();
      const first = await box(fields.nth(0));
      const second = await box(fields.nth(1));
      expect(Math.round(second.y - (first.y + first.height))).toBe(20);
      const label = await box(fields.nth(0).locator('span').first());
      const input = await box(fields.nth(0).locator('input'));
      expect(Math.round(input.y - (label.y + label.height))).toBe(6);
      await shot(page, `wizard-${theme}`);
    });
  }

  for (const locale of ['en', 'fr'] as const) {
    test(`the applications table keeps actions on one line and the audience on two (${locale})`, async ({ page }) => {
      await install(page, 'dark', locale);
      await page.goto('/create/apps');
      const continueLabel = locale === 'en' ? 'Continue editing' : 'Continuer l’édition';
      const action = page.getByRole('link', { name: continueLabel });
      expect((await box(action)).height).toBeGreaterThanOrEqual(24);
      expect(await lineCount(action)).toBe(1);
      for (const cell of await page.locator('td.xp-audience').all()) {
        expect(await lineCount(cell)).toBeLessThanOrEqual(2);
      }
      await shot(page, `apps-${locale}`);
    });
  }

  // `knownIssue`: a serious axe finding that predates this lot and lives in a
  // file another lot owns. `test.fail` keeps it visible and turns red the day
  // it is fixed, so the marker gets removed instead of forgotten.
  const MATRIX = [
    { path: '/work', readySelector: '#work-launcher-title', surface: 'work', knownIssue: '' },
    {
      path: '/connectors/connections', readySelector: 'ck-page-frame h1', surface: 'connectors',
      knownIssue: 'scrollable-region-focusable on the shell command-bar footer under 768 px',
    },
    {
      path: '/create/apps', readySelector: '.xp-table', surface: 'studio',
      knownIssue: 'scrollable-region-focusable on the shell command-bar footer under 768 px',
    },
    {
      path: '/create/apps/new', readySelector: '.xp-wizard-body', surface: 'studio',
      knownIssue: 'scrollable-region-focusable on the command-bar footer and the wizard steps under 768 px',
    },
  ] as const;
  for (const screen of MATRIX) {
    test(`${screen.path} passes the accessibility matrix, 320 px included`, async ({ page }, testInfo) => {
      test.fail(!!screen.knownIssue, screen.knownIssue);
      test.setTimeout(240_000);
      await install(page, 'dark', 'en');
      await page.goto(screen.path);
      await runAccessibilityMatrix({ page, testInfo, path: screen.path, readySelector: screen.readySelector, surface: screen.surface });
    });
  }
});
