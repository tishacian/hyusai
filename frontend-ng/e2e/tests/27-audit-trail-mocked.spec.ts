import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const shots = process.env['E2E_SHOT_DIR'] ?? '../docs/reports/l37-audit/captures';
test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 1000 } });
const workspace = { id: 'ws-l37', name: 'Audit demo', slug: 'audit-demo', role: 'admin', role_template: 'workspace_admin', settings: {} };
const user = { id: 'user-l37', email: 'ada@example.test', role: 'admin', is_active: true, mfa_enabled: false, first_name: 'Ada', last_name: 'Lovelace', workspaces: [workspace] };
const rows = [
  { id: 'event-3', timestamp: '2026-09-30T09:00:00', event_type: 'run.completed', actor: 'Ada', severity: 'info', trace_id: 'run-l37', run_id: 'run-l37', details: { run_id: 'run-l37' } },
  { id: 'event-2', timestamp: '2026-09-30T08:00:00', event_type: 'knowledge.collection.access_changed', actor: 'Bob', severity: 'warning', details: { collection_id: 'collection-1' } },
  { id: 'event-1', timestamp: '2026-09-30T07:00:00', event_type: 'experience.released', actor: 'Ada', severity: 'info', details: { release_id: 'release-1' } },
];
const nav = { id: 'nav', timestamp: '2026-09-30T10:00:00', event_type: 'navigation.resolved', actor: 'authenticated_user', severity: 'info', details: {} };
const json = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) });

async function install(page: Page, theme: string): Promise<URL[]> {
  const requests: URL[] = [];
  await page.addInitScript(({ theme, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-l37');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', theme);
    localStorage.setItem('agentium_locale', 'fr');
  }, { theme, slug: workspace.slug });
  await page.route('**/api/v1/**', async route => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: user.id, email: user.email, role: user.role });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/auth/me') return json(route, user);
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (path === '/audit' && req.method() === 'GET') {
      requests.push(url);
      const q = url.searchParams;
      let filtered = q.get('exclude_navigation') === 'true' ? [...rows] : [nav, ...rows];
      filtered = filtered.filter(row => (!q.get('actor') || row.actor === q.get('actor'))
        && (!q.get('event_type') || row.event_type === q.get('event_type'))
        && (!q.get('trace_id') || ('trace_id' in row && row.trace_id === q.get('trace_id')))
        && (!q.get('since') || new Date(row.timestamp + 'Z') >= new Date(q.get('since')!))
        && (!q.get('until') || new Date(row.timestamp + 'Z') <= new Date(q.get('until')!)));
      const total = filtered.length;
      const before = q.get('before');
      if (before) {
        const id = before.split(',').at(-1);
        filtered = filtered.slice(filtered.findIndex(row => row.id === id) + 1);
      }
      const logs = filtered.slice(0, 2);
      const has_more = filtered.length > 2;
      return json(route, { logs, total, has_more, next_cursor: has_more ? `${logs.at(-1)!.timestamp},${logs.at(-1)!.id}` : null });
    }
    if (path === '/runs/run-l37') return json(route, { id: 'run-l37', system_id: null, status: 'completed', started_at: rows[0].timestamp, completed_at: rows[0].timestamp, input_ref: {}, output_ref: {}, invocations: [], checkpoints: [] });
    if (req.method() === 'GET') return json(route, path.endsWith('s') ? [] : {});
    return json(route, { ok: true });
  });
  return requests;
}

async function axe(page: Page) {
  const result = await new AxeBuilder({ page }).include('app-audit-logs')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  expect(result.violations, JSON.stringify(result.violations)).toEqual([]);
}

test.describe('L37 — complete audit trail', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1');
  for (const theme of ['light', 'dark']) {
    test(`server pages, navigation toggle, run links and accessibility (${theme})`, async ({ page }) => {
      const requests = await install(page, theme);
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('/governance/audit');
      const audit = page.locator('app-audit-logs');
      await expect(audit.getByRole('heading', { level: 1 })).toHaveText("Journal d'audit");
      await expect(audit.getByText('Exécution terminée', { exact: true })).toBeVisible();
      await expect(audit.locator('tbody tr')).toHaveCount(2);
      expect(requests.at(-1)!.searchParams.get('exclude_navigation')).toBe('true');
      await expect(audit.getByText('navigation.resolved', { exact: true })).toHaveCount(0);
      await axe(page);
      await page.screenshot({ path: `${shots}/audit-${theme}.png`, fullPage: true });
      await audit.getByRole('button', { name: 'Charger plus', exact: true }).click();
      await expect(audit.locator('tbody tr')).toHaveCount(3);
      expect(requests.at(-1)!.searchParams.get('before')).toBe(`${rows[1].timestamp},${rows[1].id}`);
      await audit.getByRole('switch', { name: 'Afficher les navigations' }).focus();
      await page.keyboard.press('Space');
      await expect(audit.getByText('navigation.resolved', { exact: true })).toBeVisible();
      expect(requests.at(-1)!.searchParams.get('exclude_navigation')).toBe('false');
      await axe(page);
      await page.screenshot({ path: `${shots}/audit-navigation-${theme}.png`, fullPage: true });
      await audit.getByRole('link', { name: 'Voir l’exécution' }).click();
      await expect(page).toHaveURL(/\/runs\/run-l37/);
      await page.getByRole('link', { name: 'Journal d’audit de cette exécution' }).click();
      await expect(page).toHaveURL(/\/governance\/audit\?trace_id=run-l37/);
      await expect(page.locator('app-audit-logs tbody tr')).toHaveCount(1);
      expect(requests.at(-1)!.searchParams.get('trace_id')).toBe('run-l37');
      expect(errors).toEqual([]);
    });
  }

  test('CSV exports every filtered server page and actor/period filters reach the server', async ({ page }) => {
    const requests = await install(page, 'light');
    await page.goto('/governance/audit');
    const audit = page.locator('app-audit-logs');
    await expect(audit.locator('tbody tr')).toHaveCount(2);
    const downloadPromise = page.waitForEvent('download');
    await audit.getByRole('button', { name: 'Exporter en CSV' }).click();
    const download = await downloadPromise;
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
    const csv = Buffer.concat(chunks).toString('utf8');
    expect(csv).toContain('experience.released');
    expect(csv).not.toContain('navigation.resolved');
    expect(requests.filter(url => url.searchParams.get('limit') === '500')).toHaveLength(2);
    await audit.getByLabel('Filtrer par acteur', { exact: true }).fill('Ada');
    await audit.getByLabel('Depuis', { exact: true }).fill('2026-09-30T00:00');
    await audit.getByLabel('Jusqu’au', { exact: true }).fill('2026-10-01T00:00');
    await audit.getByRole('button', { name: 'Appliquer les filtres' }).click();
    await expect(audit.locator('tbody tr')).toHaveCount(2);
    await expect.poll(() => requests.at(-1)!.searchParams.get('actor')).toBe('Ada');
    expect(requests.at(-1)!.searchParams.has('since')).toBe(true);
    expect(requests.at(-1)!.searchParams.has('until')).toBe(true);
  });
});
