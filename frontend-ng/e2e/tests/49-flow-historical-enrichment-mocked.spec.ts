import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const workspace = { id: 'history-qa', slug: 'history-qa', name: 'Historical features QA',
  role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const systemId = 'historical-orders', nodeId = 'features.historical', hash = '9'.repeat(64);
const baseHash = 'a'.repeat(64), historyHash = 'b'.repeat(64);
const staleSql = 'SELECT misleading_old_sql FROM stale_reference';
const contract = {
  version: 1, operation: 'historical_aggregates',
  base: { dataset_id: 'orders-qa', version: 2 }, history: { dataset_id: 'payments-qa', version: 3 },
  base_row_id: 'order_id', history_row_id: 'event_id', base_key: 'customer_id', history_key: 'customer_id',
  decision_time: 'ordered_at', available_time: 'available_at', base_features: ['basket'],
  target_columns: ['late'], unavailable_columns: ['future_status'],
  aggregates: [{ operation: 'count', output: 'prior_events' }], cardinality: 'many_to_one',
  max_base_rows: 1000, max_history_rows: 2000, max_input_bytes: 1000000,
  max_unmatched_fraction: 0.5, timeout_s: 15,
};
const qualified = { ...contract, base: { ...contract.base, sha256: baseHash },
  history: { ...contract.history, sha256: historyHash } };
const columns = [
  { name: 'order_id', dtype: 'Int64', kind: 'integer' },
  { name: 'customer_id', dtype: 'String', kind: 'string' },
  { name: 'ordered_at', dtype: 'String', kind: 'string' },
  { name: 'basket', dtype: 'Float64', kind: 'float' },
  { name: 'late', dtype: 'Int64', kind: 'integer' },
];
const outputColumns = [...columns, { name: 'prior_events', dtype: 'Int64', kind: 'integer' }];
const datasets = [
  { id: 'orders-qa', name: 'Orders', slug: 'orders', version: 2, row_count: 2, schema: columns },
  { id: 'payments-qa', name: 'Historical payments', slug: 'payments', version: 3, row_count: 5,
    schema: [{ name: 'event_id', dtype: 'Int64', kind: 'integer' },
      { name: 'customer_id', dtype: 'String', kind: 'string' },
      { name: 'available_at', dtype: 'String', kind: 'string' }] },
].map(dataset => ({ ...dataset, status: 'ready', source: 'upload', column_count: dataset.schema.length,
  parent_ids: [], created_at: '2026-10-11T10:00:00Z' }));

async function setup(page: Page, locale: 'fr' | 'en') {
  // Reuse the real showcase graph and mocked Flow-state harness from suites 30/32.
  let graph = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/app/resources/flows/showcase_ecommerce_claims_v1.json'), 'utf8'));
  const positions: Record<string, [number, number]> = {
    'asset.postgresql': [40, 40], 'source.request': [40, 340], 'loop.investigate': [410, 200],
    'decision.ready': [740, 200], 'hitl.review': [1070, 120], 'task.simulate': [1400, 120],
    'sink.receipt': [1730, 120], 'sink.blocked': [1070, 390],
  };
  for (const node of graph.nodes) { const [x, y] = positions[node.id]; node.position = { x, y }; }
  graph.nodes.push({ id: nodeId, type: 'skill', kind: 'task', label: 'Historical order features',
    position: { x: 40, y: 560 }, config: { skill_slug: 'sql_transform_v1', params: {
      sql: staleSql, enrichment: structuredClone(contract), output_name: 'Orders with history',
      sources: [{ dataset_id: 'stale-sql-input', view: 'stale_reference' }],
    } } });
  const published = structuredClone(graph);
  let revision = 3;
  const writes: Array<{ path: string; body: any }> = [];
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status,
    contentType: 'application/json', body: JSON.stringify(body) });
  const system = () => ({ id: systemId, workspace_id: workspace.id, name: 'Order history', status: 'active',
    objective: 'Qualify historical features', flow_definition: published, flow_sha256: hash });
  const state = () => ({ system_id: systemId, status: 'active',
    draft: { revision, base_published_version_id: 'history-published-v1', flow_sha256: hash, flow_definition: graph },
    published: { version_id: 'history-published-v1', version_number: 1, flow_sha256: hash,
      flow_definition: published, execution_contract_ready: true } });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.fallback() : route.abort());
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-history-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light');
    localStorage.setItem('agentium_locale', locale);
  }, { slug: workspace.slug, locale });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'history-human', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'history-human', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON() });
    if (path === '/systems') return json(route, { systems: [system()] });
    if (path === `/systems/${systemId}`) return json(route, system());
    if (path === `/systems/${systemId}/flow-state`) return json(route, state());
    if (path === `/systems/${systemId}/flow-draft` && request.method() === 'PUT') {
      graph = request.postDataJSON().flow_definition; revision++;
      return json(route, { ...state().draft, system_id: systemId, no_op: false });
    }
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_overlay', flow_sha256: hash });
    if (path === '/skills') return json(route, { skills: [] });
    if (path === '/documents/collections') return json(route, { collections: [] });
    if (path === '/connectors') return json(route, { can_configure: true, connectors: [] });
    if (path === '/ml-models') return json(route, { models: [] });
    if (path === '/datasets') return json(route, { datasets, feature: { enabled: true, upload_max_bytes: 1 << 26 } });
    if (path === '/datasets/sql-preview') return json(route, { detail: { code: 'SQL_PREVIEW_MUST_NOT_RUN' } }, 409);
    if (path === '/datasets/enrichment-preview') return json(route, {
      row_count: 2, column_count: outputColumns.length, schema: outputColumns, stats: {}, duration_ms: 12,
      preview: [{ order_id: 1, customer_id: 'A', ordered_at: '2026-03-01', basket: 40, late: 0, prior_events: 3 },
        { order_id: 2, customer_id: 'B', ordered_at: '2026-03-01', basket: 20, late: 1, prior_events: 0 }],
      sources: datasets.map((dataset, index) => ({ view: index === 0 ? 'base' : 'history', aliases: [],
        dataset_id: dataset.id, name: dataset.name, rows: dataset.row_count, columns: dataset.schema })),
      enrichment: { contract: structuredClone(qualified), output_rows: 2, unmatched_rows: 1,
        unmatched_fraction: 0.5, feature_columns: ['basket', 'prior_events'] },
    });
    return json(route, {});
  });
  return { writes, params: () => graph.nodes.find((node: any) => node.id === nodeId).config.params };
}

async function openWorkshop(page: Page, locale: 'fr' | 'en') {
  await page.goto(`/systems/${systemId}/flow?lens=build`);await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
  await expect(page.locator('app-flow-node')).toHaveCount(9);
  await page.locator('app-flow-node').filter({ hasText: 'Historical order features' }).click();
  await expect(page.getByTestId('transform-summary')).toContainText(locale === 'fr' ? 'Agrégats historiques' : 'Historical aggregates');
  await page.getByTestId('open-transform-workshop').click();
  const workshop = page.locator('app-flow-transform-workshop'), editor = workshop.locator('.cm-content');
  await expect(workshop.getByTestId('transform-sql-mode')).toHaveValue('historical');
  await expect(editor).toContainText('historical_aggregates');
  await expect(editor).not.toContainText('misleading_old_sql');
  await expect(workshop.getByTestId('pin-dataset')).toHaveCount(0);
  return { workshop, editor };
}

test.describe('Historical enrichment in the Flow workshop — isolated mocked QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' ||
      !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const locale of ['fr', 'en'] as const) {
    test(`${locale}: preview historical features and persist qualified source pins`, async ({ page }, info) => {
      await page.setViewportSize({ width: 1440, height: 1000 });
      const api = await setup(page, locale);
      const { workshop, editor } = await openWorkshop(page, locale);
      await expect(workshop.getByTestId('run-transform-preview')).toHaveText(locale === 'fr'
        ? /Tester les variables historiques/ : /Preview historical features/);
      await workshop.getByTestId('run-transform-preview').click();
      await expect(workshop.getByTestId('enrichment-evidence')).toContainText(locale === 'fr'
        ? '2 décisions · 1 sans historique antérieur' : '2 decisions · 1 without earlier history');
      const requests = api.writes.filter(write => write.path === '/datasets/enrichment-preview');
      expect(requests).toHaveLength(1);
      expect(requests[0].body).toEqual({ enrichment: contract, row_limit: 50 });
      expect(api.writes.filter(write => write.path === '/datasets/sql-preview')).toEqual([]);
      expect(api.params().enrichment).toEqual(contract);
      await expect(workshop.getByTestId('pin-enrichment-proof')).toBeEnabled();
      await workshop.getByTestId('pin-enrichment-proof').click();
      await expect.poll(() => api.params().enrichment).toEqual(qualified);
      expect(api.params().sql).toBe(staleSql);
      await expect(editor).toContainText(baseHash);
      await expect(editor).toContainText(historyHash);
      await page.screenshot({ path: info.outputPath(`historical-features-${locale}.png`), fullPage: true });

      // A real page reload reads the saved draft, including versions, hashes,
      // feature policy and resource budgets. No training/publication is implied.
      await page.reload();
      const reopened = await openWorkshop(page, locale);
      await expect(reopened.editor).toContainText(baseHash);
      await expect(reopened.editor).toContainText(historyHash);
      expect(api.params().enrichment).toEqual(qualified);
      expect(api.writes.filter(write => /\/runs$|\/publish$|\/ml-models\/train$/.test(write.path))).toEqual([]);

      // A malformed JSON draft is visibly refused, never replaced by stale SQL.
      const countBefore = api.writes.filter(write => write.path.endsWith('-preview')).length;
      await reopened.editor.fill('{unfinished');
      await reopened.workshop.getByTestId('run-transform-preview').click();
      await expect(reopened.workshop.getByTestId('transform-failure')).toContainText(locale === 'fr'
        ? 'Le contrat historique doit être un objet JSON valide' : 'The historical contract must be a valid JSON object');
      expect(api.writes.filter(write => write.path.endsWith('-preview'))).toHaveLength(countBefore);
      expect(api.writes.filter(write => write.path === '/datasets/sql-preview')).toEqual([]);
    });
  }
});
