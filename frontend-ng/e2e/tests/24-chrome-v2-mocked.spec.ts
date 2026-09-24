import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Chrome v2 — mocked local safety net, one scenario per chrome lot.
 *
 * No local backend. Opt-in:
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://localhost:4200
 *   npx playwright test e2e/tests/24-chrome-v2-mocked.spec.ts
 *
 * The fonts come from Google Fonts, so the L4 scenario needs the network.
 */

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

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

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

test.use({
  viewport: { width: 1440, height: 900 },
  locale: 'fr-FR',
  colorScheme: 'dark',
});

test.describe('Chrome v2 — mocked', () => {
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
});
