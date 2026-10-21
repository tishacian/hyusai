import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

/** Local-only lot 6: failed knowledge reads, callable models, exact provenance. */
const workspace = { id: 'ws-data', slug: 'data-evidence', name: 'Data evidence', role: 'admin', role_template: 'workspace_admin', settings: { features: {} } };
const user = { id: 'u-data', email: 'data@example.test', role: 'admin', is_active: true, workspaces: [workspace] };
type Answer = { status: number; body?: unknown } | { abort: 'timedout' | 'failed' };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function install(page: Page, chunks: Answer = { status: 200, body: { chunks: [] } }) {
  const base = test.info().project.use.baseURL;
  if (!base || !['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Loopback only');
  const tables: string[] = [];
  await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ slug }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-data-evidence');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', 'fr');
  }, { slug: workspace.slug });
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: user.id, email: user.email, role: user.role });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/auth/me') return json(route, user);
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (path === '/documents/chunks') return 'abort' in chunks ? route.abort(chunks.abort) : json(route, chunks.body ?? { detail: 'Unavailable' }, chunks.status);
    if (path === '/documents/collections') return json(route, { items: [{ slug: 'manual', name: 'Manual', status: 'ready', document_count: 1, chunk_count: 1 }] });
    if (path.endsWith('/inventory')) return json(route, { sources: [], source_count: 1, chunk_count: 1 });
    if (path === '/documents/stats') return json(route, { total_chunks: 1, vector_db_type: 'qdrant' });
    if (path === '/knowledge/scopes') return json(route, { scopes: [] });
    if (path === '/knowledge/guides') return json(route, { items: [] });
    if (path === '/ml-models') return json(route, { catalog: { enabled: true, algorithms: [], metrics: [], tasks: [], limits: {} }, permissions: {}, models: [
      { id: 'blocked-v1', slug: 'blocked', name: 'Selected without artifact', version: 1, task: 'classification', algo: 'linear', status: 'ready', is_champion: true, callable: false, refusal: { code: 'ML_ARTIFACT_MISSING' }, features: [] },
      { id: 'callable-v1', slug: 'callable', name: 'Callable model', version: 1, task: 'classification', algo: 'linear', status: 'ready', is_champion: true, callable: true, features: [] },
    ] });
    if (path === '/contexts') return json(route, [
      { id: 'recent', name: 'Recently maintained v7', version: 7, updated_at: new Date().toISOString(), source_dates: [], data_refs: [], memory_refs: [] },
      { id: 'old', name: 'Old source v1', version: 1, updated_at: new Date().toISOString(), source_dates: [{ ref: 'manual', updated_at: '2000-01-01T00:00:00Z' }], data_refs: ['manual'], memory_refs: [] },
    ]);
    if (path === '/connectors') return json(route, { can_configure: true, connectors: [{ id: 'postgresql', configured: true, values: { host: 'db.example.test', database: 'erp', username: 'reader', sslmode: 'verify-full' }, secrets_set: { password: true } }] });
    if (path === '/connectors/postgresql/catalog') return json(route, { tables: [{ schema: 'finance', name: 'invoices', kind: 'table' }, { schema: 'public', name: 'invoices', kind: 'table' }], checked_at: '2026-10-21T10:00:00Z', datasets_enabled: true, limits: { import_rows: 1000 } });
    if (path === '/connectors/postgresql/table') {
      tables.push(`${url.searchParams.get('schema')}.${url.searchParams.get('table')}`);
      return json(route, { schema: 'finance', table: 'invoices', fingerprint: 'fp', columns: [{ name: 'amount', kind: 'float', dtype: 'double precision', supported: true, as_text: false, primary_key: false }] });
    }
    return json(route, route.request().method() === 'GET' && (path.endsWith('s') || path.includes('items')) ? [] : {});
  });
  return { tables };
}

test.describe('Lot 6: data, knowledge and model evidence', () => {
  test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1', 'Local mocked contract only');
  test('knowledge displays returned frozen chunks', async ({ page }) => {
    await install(page, { status: 200, body: {
      chunks: [{ point_id: 'p1', content: 'Frozen source excerpt', content_length: 21, truncated: false, document_filename: 'manual.pdf', chunk_index: 0 }],
      count: 1, offset: 0, has_more: false, total: 1, total_is_exact: true,
    } });
    await page.goto('/knowledge/manual?facet=chunks');
    await expect(page.locator('app-knowledge-view')).toContainText('Frozen source excerpt');
    await expect(page.getByTestId('load-state-error')).toHaveCount(0);
  });
  test('only a confirmed empty read shows empty content', async ({ page }) => {
    await install(page);
    await page.goto('/knowledge/manual?facet=chunks');
    await expect(page.locator('app-knowledge-view')).toContainText('No chunks loaded yet');
    await expect(page.getByTestId('load-state-error')).toHaveCount(0);
  });
  for (const [label, answer] of [
    ['403', { status: 403 }], ['500', { status: 500 }], ['504', { status: 504 }],
    ['timeout', { abort: 'timedout' }], ['offline', { abort: 'failed' }],
  ] as Array<[string, Answer]>) {
    test(`knowledge ${label} never becomes an empty panel`, async ({ page }) => {
      await install(page, answer);
      await page.goto('/knowledge/manual?facet=chunks');
      await expect(page.getByTestId(label === '403' ? 'load-state-denied' : 'load-state-error')).toBeVisible();
      await expect(page.locator('app-knowledge-view')).not.toContainText('No chunks loaded yet');
    });
  }
  test('serving filter excludes selected models without a callable artifact', async ({ page }) => {
    await install(page);
    await page.goto('/models');
    await expect(page.getByTestId('model-serving-blocked')).toContainText('non appelable');
    await page.getByRole('button', { name: 'En service', exact: true }).click();
    await expect(page.getByTestId('models-list')).toContainText('Callable model');
    await expect(page.getByTestId('models-list')).not.toContainText('Selected without artifact');
  });
  test('context freshness follows dates rather than version count', async ({ page }) => {
    await install(page);
    await page.goto('/steering/contexts');
    await expect(page.locator('li').filter({ hasText: 'Recently maintained v7' }).last().getByTestId('context-freshness')).toContainText('moins de 90');
    await expect(page.locator('li').filter({ hasText: 'Old source v1' }).last().getByTestId('context-freshness')).toContainText('90');
  });
  test('PostgreSQL opens the exact schema and retains the dataset version', async ({ page }) => {
    const { tables } = await install(page);
    await page.goto('/connectors/postgresql?sourceDatabase=erp&sourceSchema=finance&sourceTable=invoices&datasetId=dataset-v3&datasetVersion=3');
    await expect(page.getByTestId('pg-selected-table')).toHaveText('finance.invoices');
    expect(tables).toEqual(['finance.invoices']);
    const backToDataset = page.getByTestId('pg-return-dataset');
    await expect(backToDataset).toContainText('version 3');
    const destination = new URL((await backToDataset.getAttribute('href'))!, page.url());
    expect(destination.pathname).toBe('/data/dataset-v3');
    expect(destination.searchParams.get('facet')).toBe('lineage');
  });
});
