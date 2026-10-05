import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const workspace = { id: 'qa-postgresql', slug: 'qa-postgresql', name: 'Showcase QA', role: 'owner', role_template: 'workspace_owner', settings: {} };
const config = { id: 'postgresql', values: { host: 'postgres.example.test', port: '5432', database: 'showcase', username: 'reader' }, secrets_set: { password: true }, configured: true, testable: true };
const columns = [
  { name: 'id', kind: 'integer', dtype: 'bigint', supported: true, as_text: false, primary_key: true },
  { name: 'amount', kind: 'string', dtype: 'numeric(12,2)', supported: true, as_text: true, primary_key: false },
  { name: 'evidence', kind: 'other', dtype: 'bytea', supported: false, as_text: false, primary_key: false },
];
const fingerprint = 'a'.repeat(64);
const description = { schema: 'showcase_ecommerce', table: 'claims', fingerprint, columns };

async function setup(page: Page, theme = 'light', locale = 'fr', options: { admin?: boolean; importError?: string; retry?: boolean; schemaChanged?: boolean; secondWorkspace?: boolean; queryFailedOnce?: boolean } = {}) {
  const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
  let importCount = 0;
  let previewCount = 0;
  const second = { ...workspace, id: 'qa-postgresql-other', slug: 'qa-postgresql-other', name: 'Other QA' };
  const workspaces = options.secondWorkspace ? [workspace, second] : [workspace];
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.fulfill({ status: 204, body: '' }));
  await page.addInitScript(({ theme, locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-postgresql-qa');
    localStorage.setItem('agentium_theme', theme); localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_workspace_slug', slug);
  }, { theme, locale, slug: workspace.slug });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa-human', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa-human', role: 'admin', email: 'qa@example.test', is_active: true, workspaces });
    if (path === '/auth/workspaces') return json(route, workspaces);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (path === '/auth/workspaces/' + second.slug) return json(route, second);
    if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON() });
    if (path === '/connectors') return json(route, { can_configure: options.admin !== false, connectors: [request.headers()['x-workspace-slug'] === second.slug ? { ...config, values: { ...config.values, database: 'other-workspace-database' } } : config] });
    if (path === '/connectors/postgresql' && request.method() === 'PUT') return json(route, { ...config, values: writes.at(-1)!.body['values'] });
    if (path === '/connectors/postgresql/test') return json(route, { status: 'connected', checked_at: '2026-10-02T12:00:00Z' });
    if (path === '/connectors/postgresql/catalog') return json(route, { tables: [{ schema: 'showcase_ecommerce', name: 'claims', kind: 'table' }, { schema: 'showcase_ecommerce', name: 'orders', kind: 'table' }, { schema: 'finance', name: 'ledger', kind: 'partitioned' }], checked_at: '2026-10-02T12:00:00Z', limits: { import_rows: 10000 }, datasets_enabled: true });
    if (path === '/connectors/postgresql/table') return json(route, description);
    if (path === '/connectors/postgresql/preview') {
      if (options.schemaChanged) return json(route, { detail: { code: 'PG_SOURCE_CHANGED' } }, 409);
      if (options.queryFailedOnce && ++previewCount === 1) return json(route, { detail: { code: 'PG_QUERY_FAILED', sqlstate: '42601' } }, 502);
      const selected = writes.at(-1)!.body['columns'] as string[];
      return json(route, { schema: columns.filter(c => selected.includes(c.name)), rows: [{ id: 1, amount: '49.90' }], row_count: 1, has_more: true, captured_at: '2026-10-02T12:01:00Z', ordered_by: ['id'] });
    }
    if (path === '/connectors/postgresql/import') {
      importCount++;
      if (options.importError && (!options.retry || importCount === 1)) return json(route, { detail: { code: options.importError } }, options.importError === 'PG_UNAVAILABLE' ? 503 : 413);
      return json(route, { replayed: false, dataset: { id: 'qa-native-pg-dataset', name: 'Réclamations', version: 2, source: 'postgresql', status: 'ready', row_count: 23, column_count: 2, schema: columns.slice(0, 2), parent_ids: [] } });
    }
    return json(route, request.method() === 'GET' && path.endsWith('s') ? [] : {});
  });
  return writes;
}

async function preview(page: Page, english = false) {
  await page.getByRole('button', { name: english ? 'Explore tables' : 'Explorer les tables', exact: true }).click();
  await page.getByRole('button', { name: /^claims/ }).click();
  await expect(page.getByTestId('pg-selected-table')).toHaveText('showcase_ecommerce.claims');
  await page.getByRole('button', { name: english ? 'Show preview' : 'Afficher l’aperçu', exact: true }).click();
  await expect(page.getByTestId('pg-preview')).toContainText('49.90');
}

test.describe('PostgreSQL — isolated end-user QA', () => {
  test.skip(!enabled, 'Enable E2E_CHROME_V2_MOCKED for isolated QA');
  for (const [theme, locale, width] of [['dark', 'fr', 1440], ['light', 'fr', 390], ['light', 'en', 1440]] as const) {
    test(`${theme}/${locale}/${width}: saved connection, real preview contract and native dataset`, async ({ page }, testInfo) => {
      const writes = await setup(page, theme, locale);
      await page.setViewportSize({ width, height: 1000 }); await page.goto('/connectors/postgresql?lens=build');
      const english = locale === 'en';
      await expect(page.getByTestId('pg-endpoint')).toContainText('showcase');
      await page.screenshot({ path: testInfo.outputPath('postgresql-setup.png'), fullPage: true });
      await page.getByRole('button', { name: english ? 'Test connection' : 'Tester la connexion', exact: true }).click();
      await expect(page.getByTestId('pg-connection-state')).toContainText(english ? 'Connection verified' : 'Connexion vérifiée');
      await preview(page, english);
      await page.getByTestId('pg-preview').scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath('postgresql-preview.png'), fullPage: true });
      await expect(page.getByRole('checkbox', { name: /evidence/ })).toBeDisabled();
      await expect(page.getByRole('checkbox', { name: /amount/ })).toBeChecked();
      await page.getByRole('textbox', { name: english ? 'Dataset name' : 'Nom du dataset', exact: true }).fill('Réclamations');
      await page.getByRole('button', { name: english ? 'Create dataset' : 'Créer le dataset', exact: true }).click();
      await expect(page.getByTestId('pg-import-success')).toContainText('23');
      await expect(page.getByTestId('pg-import-success')).toContainText('v2');
      const link = page.getByRole('link', { name: english ? 'Open dataset' : 'Ouvrir le dataset', exact: true });
      await expect(link).toHaveAttribute('href', /\/data\/qa-native-pg-dataset/);
      const imported = writes.find(w => w.path.endsWith('/import'))!.body;
      expect(imported['columns']).toEqual(['id', 'amount']); expect(imported['rows']).toBeUndefined();
      expect(imported['fingerprint']).toBe(fingerprint);
      expect((await new AxeBuilder({ page }).include('.pg-page').analyze()).violations).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath('postgresql-dataset.png'), fullPage: true });
    });
  }

  test('editing preserves the saved password and requires a fresh preview', async ({ page }) => {
    const writes = await setup(page); await page.goto('/connectors/postgresql'); await preview(page);
    await page.getByRole('checkbox', { name: /^amount/ }).uncheck();
    await expect(page.getByTestId('pg-preview')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Créer le dataset', exact: true })).toBeDisabled();
    await page.getByRole('button', { name: 'Modifier la connexion', exact: true }).click();
    await expect(page.getByLabel('Mot de passe', { exact: true })).toHaveValue('');
    await page.getByLabel('Hôte', { exact: true }).fill('new-postgres.example.test');
    await expect(page.getByRole('button', { name: 'Explorer les tables', exact: true })).toBeDisabled();
    await page.getByRole('button', { name: 'Enregistrer la connexion', exact: true }).click();
    await expect(page.getByTestId('pg-endpoint')).toContainText('new-postgres.example.test');
    const values = writes.find(w => w.path === '/connectors/postgresql')!.body['values'] as Record<string, unknown>;
    expect(values['password']).toBeUndefined();
    expect(values['username']).toBe('reader');
  });

  test('an unauthorized member cannot discover, test or import', async ({ page }) => {
    const writes = await setup(page, 'light', 'fr', { admin: false }); await page.goto('/connectors/postgresql');
    await expect(page.getByText('Un administrateur du workspace', { exact: false })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Explorer les tables', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Tester la connexion', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Créer le dataset', exact: true })).toBeDisabled();
    expect(writes.filter(w => w.path.startsWith('/connectors'))).toEqual([]);
  });

  test('an oversized source never appears as a successful partial dataset', async ({ page }) => {
    await setup(page, 'light', 'fr', { importError: 'PG_IMPORT_ROW_LIMIT' }); await page.goto('/connectors/postgresql'); await preview(page);
    await page.getByRole('button', { name: 'Créer le dataset', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Aucun dataset partiel');
    await expect(page.getByTestId('pg-import-success')).toHaveCount(0);
  });

  test('a retry after an unavailable response reuses the import request identity', async ({ page }) => {
    const writes = await setup(page, 'light', 'fr', { importError: 'PG_UNAVAILABLE', retry: true }); await page.goto('/connectors/postgresql'); await preview(page);
    await page.getByRole('button', { name: 'Créer le dataset', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('indisponible');
    await page.getByRole('button', { name: 'Créer le dataset', exact: true }).click();
    await expect(page.getByTestId('pg-import-success')).toBeVisible();
    const imports = writes.filter(w => w.path.endsWith('/import'));
    expect(imports).toHaveLength(2); expect(imports[0].body['request_id']).toBe(imports[1].body['request_id']);
  });

  test('a changed source requires renewed discovery and blocks importing', async ({ page }) => {
    await setup(page, 'light', 'fr', { schemaChanged: true }); await page.goto('/connectors/postgresql');
    await page.getByRole('button', { name: 'Explorer les tables', exact: true }).click();
    await page.getByRole('button', { name: /^claims/ }).click();
    await page.getByRole('button', { name: 'Afficher l’aperçu', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('schéma a changé');
    await expect(page.getByRole('button', { name: 'Créer le dataset', exact: true })).toBeDisabled();
  });

  test('a late read cannot show data from the previous workspace', async ({ page }) => {
    await setup(page, 'light', 'fr', { secondWorkspace: true });
    let release!: () => void;
    const gate = new Promise<void>(resolve => release = resolve);
    await page.route('**/api/v1/connectors/postgresql/preview', async route => {
      await gate;
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ schema: columns.slice(0, 2), rows: [{ id: 1, amount: 'PREVIOUS-WORKSPACE-DATA' }], row_count: 1, has_more: false, ordered_by: ['id'], captured_at: '2026-10-02T12:00:00Z' }) });
    });
    await page.goto('/connectors/postgresql?lens=build');
    await page.getByRole('button', { name: 'Explorer les tables', exact: true }).click();
    await page.getByRole('button', { name: /^claims/ }).click();
    await page.getByRole('button', { name: 'Afficher l’aperçu', exact: true }).click();
    await page.getByTestId('workspace-switcher-toggle').click();
    await page.getByTestId('workspace-switcher-popover').getByRole('button', { name: /Other QA/ }).click();
    await expect(page.getByTestId('workspace-switcher-toggle')).toContainText('Other QA');
    await page.getByRole('link', { name: 'Explorer PostgreSQL', exact: true }).click();
    await expect(page.getByTestId('pg-endpoint')).toContainText('other-workspace-database');
    const responded = page.waitForResponse('**/api/v1/connectors/postgresql/preview');
    release(); await responded;
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.getByTestId('pg-preview')).toHaveCount(0);
    await expect(page.getByText('PREVIOUS-WORKSPACE-DATA')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Créer le dataset', exact: true })).toBeDisabled();
  });

  test('the table list filters by name or schema', async ({ page }) => {
    await setup(page); await page.goto('/connectors/postgresql');
    await page.getByRole('button', { name: 'Explorer les tables', exact: true }).click();
    await expect(page.getByText('Tables : 3 / 3')).toBeVisible();
    await page.getByRole('searchbox', { name: 'Rechercher une table' }).fill('finance');
    await expect(page.getByText('Tables : 1 / 3')).toBeVisible();
    await expect(page.getByRole('button', { name: /^ledger/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /^claims/ })).toHaveCount(0);
    await page.getByRole('searchbox', { name: 'Rechercher une table' }).fill('zzz');
    await expect(page.getByText('Aucune table ne correspond', { exact: false })).toBeVisible();
  });

  test('a refused read shows its PostgreSQL code next to the preview and retries in place', async ({ page }) => {
    await setup(page, 'light', 'fr', { queryFailedOnce: true }); await page.goto('/connectors/postgresql');
    await page.getByRole('button', { name: 'Explorer les tables', exact: true }).click();
    await page.getByRole('button', { name: /^claims/ }).click();
    await page.getByRole('button', { name: 'Afficher l’aperçu', exact: true }).click();
    const alert = page.locator('section', { has: page.locator('#pg-explorer-title') }).getByRole('alert');
    await expect(alert).toContainText('PostgreSQL a refusé la lecture');
    await expect(alert).toContainText('Code PostgreSQL 42601');
    await alert.getByRole('button', { name: 'Réessayer', exact: true }).click();
    await expect(page.getByTestId('pg-preview')).toContainText('49.90');
    await expect(page.getByTestId('pg-failure')).toHaveCount(0);
    await expect(page.getByTestId('pg-dataset-state')).toContainText('Prêt à importer');
  });
});
