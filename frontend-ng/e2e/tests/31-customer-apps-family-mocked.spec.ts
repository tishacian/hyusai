import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';

/**
 * A customer application stays in its own family's workspaces, whatever the
 * flags. Without entitlement flags the historical default used to list
 * ANDRITZ's Client360 and FSE reports in every workspace, Showcase included.
 */
async function setup(page: Page, family: string | null) {
  const workspace = {
    id: 'qa-family', slug: 'qa-family', name: 'Family QA', role: 'owner', role_template: 'workspace_owner',
    mode: 'builder', settings: family ? { family } : {},
  };
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.fulfill({ status: 204, body: '' }));
  await page.addInitScript(({ slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-family-qa');
    localStorage.setItem('agentium_locale', 'fr'); localStorage.setItem('agentium_workspace_slug', slug);
  }, { slug: workspace.slug });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa-human', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa-human', role: 'admin', email: 'qa@example.test', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    return json(route, request.method() === 'GET' && path.endsWith('s') ? [] : {});
  });
}

test.describe('Customer applications — family boundary', () => {
  test.skip(!enabled, 'Enable E2E_CHROME_V2_MOCKED for isolated QA');

  for (const family of ['generic', null]) {
    test(`a ${family ?? 'unstamped'} workspace never sees ANDRITZ's applications`, async ({ page }) => {
      await setup(page, family);
      await page.goto('/runs');
      await expect(page.locator('app-mini-rail, .ck-mini-rail').first()).toBeVisible();
      await expect(page.locator('a[href^="/client360"]')).toHaveCount(0);
      await expect(page.locator('a[href^="/knowledge/interventions"]')).toHaveCount(0);
      await page.goto('/client360');
      await expect(page).not.toHaveURL(/\/client360/);
      await expect(page.locator('app-client360-page')).toHaveCount(0);
      await page.goto('/knowledge/interventions');
      await expect(page).not.toHaveURL(/\/knowledge\/interventions/);
    });
  }

  test('an ANDRITZ workspace keeps Client360 in its rail', async ({ page }) => {
    await setup(page, 'andritz');
    await page.goto('/runs');
    await expect(page.locator('a[href^="/client360"]').first()).toBeVisible();
    await page.goto('/client360');
    await expect(page).toHaveURL(/\/client360/);
  });
});
