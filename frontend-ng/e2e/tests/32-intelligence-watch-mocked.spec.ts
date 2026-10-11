import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';

/**
 * Intelligence is a neutral product: a workspace without a watch sees an empty
 * state, never a list of unrelated Systems, and creates its own watch on demand.
 */
async function setup(page: Page, canCreate: boolean) {
  const workspace = {
    id: 'qa-watch', slug: 'qa-watch', name: 'Watch QA', role: 'owner', role_template: 'workspace_owner',
    mode: 'builder', settings: { family: 'generic' },
  };
  const writes: string[] = [];
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.fulfill({ status: 204, body: '' }));
  await page.addInitScript(({ slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-watch-qa');
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
    if (path === '/intelligence/watch' && request.method() === 'GET') return json(route, { systems: [], can_create: canCreate, template_id: 'intelligence' });
    if (path === '/intelligence/watch' && request.method() === 'POST') {
      writes.push(path);
      return json(route, { created: true, system: { id: 'watch-1', name: 'Veille', status: 'draft' } });
    }
    if (path === '/systems') return json(route, { systems: [{ id: 'unrelated-system', name: 'Unrelated System', status: 'active' }] });
    return json(route, request.method() === 'GET' && path.endsWith('s') ? [] : {});
  });
  return writes;
}

test.describe('Intelligence — neutral watch', () => {
  test.skip(!enabled, 'Enable E2E_CHROME_V2_MOCKED for isolated QA');

  test('a workspace without a watch is offered to create one, not a list of other Systems', async ({ page }) => {
    const writes = await setup(page, true);
    await page.goto('/intelligence');
    await expect(page.getByText('Aucune veille pour l’instant')).toBeVisible();
    await expect(page.getByText('Unrelated System')).toHaveCount(0);
    await page.getByTestId('intelligence-create-watch').click();
    await expect(page).toHaveURL(/\/systems\/watch-1/);
    expect(writes).toEqual(['/intelligence/watch']);
  });

  test('a member who cannot create Systems is told who can', async ({ page }) => {
    await setup(page, false);
    await page.goto('/intelligence');
    await expect(page.getByTestId('intelligence-create-watch')).toHaveCount(0);
    await expect(page.getByText('Seule une personne autorisée à créer des Systèmes', { exact: false })).toBeVisible();
  });
});
