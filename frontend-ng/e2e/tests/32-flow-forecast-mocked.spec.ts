import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Forecasting on the Flow canvas, against a mocked API.
 *
 * Two nodes: a training node pinned to Nawa's hourly cells, and a forecast
 * node. What is checked is what the canvas writes into the graph — the forecast
 * node's model, horizon and level, and the training node's `spec` — because
 * that is what the walker projects into `_forecast` and `_train` at run time.
 */

test.use({ serviceWorkers: 'block', video: 'off' });

const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8'));
const workspace = { id: 'flow-forecast-qa', slug: 'flow-forecast-qa', name: 'Nawa QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const systemId = 'nawa-capacity';
const hash = '2'.repeat(64);
const schema = [
  { name: 'cell_id', dtype: 'String', kind: 'string' },
  { name: 'technology', dtype: 'String', kind: 'string' },
  { name: 'ts', dtype: 'Datetime', kind: 'datetime' },
  { name: 'prb_utilization_pct', dtype: 'Float64', kind: 'float' },
];
const dataset = {
  id: 'ds-cells', name: 'Cellules Nawa · horaire', slug: 'nawa-cells', version: 1, source: 'upload', status: 'ready',
  row_count: 2688, column_count: schema.length, schema, parent_ids: [], created_at: '2026-10-07T09:00:00Z',
};
const columns = schema.map((column) => ({
  name: column.name, kind: column.kind, distinct: column.name === 'cell_id' ? 4 : 600, nulls: 0,
  suggested_task: column.kind === 'float' ? 'regression' : 'classification',
}));
const models = [
  { id: 'fc-1', slug: 'nawa-cells-prb', name: 'Cellules Nawa · PRB +24', version: 1, status: 'ready', task: 'forecasting', family: 'forecasting', algo: 'gradient_boosting', target: 'prb_utilization_pct', features: [], is_champion: true, spec: { horizon: 24 } },
  { id: 'churn-1', slug: 'churn', name: 'Churn', version: 3, status: 'ready', task: 'classification', algo: 'gradient_boosting', target: 'churn', features: [], is_champion: true },
];

/** The showcase Flow, as the canvas really receives one, plus the two model nodes. */
function flow() {
  const graph = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/app/resources/flows/showcase_ecommerce_claims_v1.json'), 'utf8'));
  const positions: Record<string, [number, number]> = {
    'asset.postgresql': [40, 40], 'source.request': [40, 340], 'loop.investigate': [410, 200],
    'decision.ready': [740, 200], 'hitl.review': [1070, 120], 'task.simulate': [1400, 120],
    'sink.receipt': [1730, 120], 'sink.blocked': [1070, 390],
  };
  for (const node of graph.nodes) {
    const [x, y] = positions[node.id];
    node.position = { x, y };
  }
  graph.nodes.push(
    { id: 'train.prb', type: 'skill', kind: 'task', label: 'Apprendre la charge des cellules', position: { x: 40, y: 560 },
      config: { skill_slug: 'ml_train_sklearn_v1', params: { task: null, target: '', features: null, algo: '', knobs: {}, test_size: 0.25, cross_validation: 0, model_name: '', spec: null, sources: [{ dataset_slug: 'nawa-cells' }] } } },
    { id: 'forecast.prb', type: 'skill', kind: 'task', label: 'Prévoir la charge des cellules', position: { x: 410, y: 560 },
      config: { skill_slug: 'ml_forecast_v1', params: { model_id: '', model_slug: '', pinned_version: null, output_name: '', horizon: null, interval_level: null, sources: [] } } },
  );
  graph.edges.push({ from: 'train.prb', to: 'forecast.prb', kind: 'data' });
  return graph;
}

async function setup(page: Page, options: { theme: string; locale: string }) {
  let graph = flow();
  let revision = 1;
  const writes: Array<{ path: string; body: any }> = [];
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  const system = () => ({ id: systemId, workspace_id: workspace.id, name: 'Nawa · capacité radio', status: 'active', flow_definition: graph, flow_sha256: hash, objective: 'Capacité' });
  const state = () => ({ system_id: systemId, status: 'active', draft: { revision, base_published_version_id: 'nawa-published-v1', flow_sha256: hash, flow_definition: graph }, published: { version_id: 'nawa-published-v1', version_number: 1, flow_sha256: hash, flow_definition: graph, execution_contract_ready: true } });
  await page.route('**/*', (route) =>
    ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort(),
  );
  await page.addInitScript(({ theme, locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer flow-forecast-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', theme);
    localStorage.setItem('agentium_locale', locale);
  }, { ...options, slug: workspace.slug });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON() });
    if (path === '/systems') return json(route, { systems: [system()] });
    if (path === `/systems/${systemId}`) return json(route, system());
    if (path === `/systems/${systemId}/flow-state`) return json(route, state());
    if (path === `/systems/${systemId}/flow-draft` && request.method() === 'PUT') {
      graph = request.postDataJSON().flow_definition;
      revision++;
      return json(route, { ...state().draft, system_id: systemId, no_op: false });
    }
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_overlay', flow_sha256: hash });
    if (path === '/skills') return json(route, { skills: [] });
    if (path === '/documents/collections') return json(route, { collections: [] });
    if (path === '/connectors') return json(route, { can_configure: true, connectors: [] });
    if (path === '/ml-models/catalog') return json(route, { catalog: fixture.catalog });
    if (path === '/ml-models') return json(route, { models, catalog: fixture.catalog });
    if (path === '/datasets') return json(route, { datasets: [dataset], feature: { enabled: true, upload_max_bytes: 1 << 26 } });
    if (path === `/datasets/${dataset.id}/preview`) return json(route, { dataset_id: dataset.id, schema, rows: [], offset: 0, limit: 50, total: 2688 });
    if (path === '/ml-models/plan') {
      const body = request.postDataJSON();
      const base = { dataset, columns, catalog: fixture.catalog, plan: null, refusal: null };
      if (!body.target) return json(route, base);
      return json(route, { ...base, plan: { task: body.task ?? 'regression', family: body.task === 'forecasting' ? 'forecasting' : 'tabular', spec: body.spec ?? {}, target: body.target, features: [], algo: body.algo || 'gradient_boosting', estimator: 'sklearn.ensemble.HistGradientBoostingRegressor', knobs: {}, test_size: 0.11, cross_validation: 3, name: 'Cellules Nawa · prb +24', warnings: [], rows: 2688 } });
    }
    return json(route, {});
  });
  const drafts = () => writes.filter((write) => write.path.endsWith('/flow-draft')).map((write) => write.body.flow_definition);
  const params = (nodeId: string) => drafts().at(-1)?.nodes.find((node: any) => node.id === nodeId)?.config?.params ?? {};
  return { writes, params };
}

test.describe('Flow · forecasting — isolated end-user QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(
      process.env['E2E_CHROME_V2_MOCKED'] !== '1' ||
        !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname),
      'Local mocked QA only.',
    );
  });

  for (const [theme, locale] of [['dark', 'fr'], ['light', 'en']] as const) {
    test(`${theme}/${locale}: a forecast node and a forecasting fit are written into the graph`, async ({ page }, info) => {
      await page.setViewportSize({ width: 1440, height: 1000 });
      const api = await setup(page, { theme, locale });
      await page.goto(`/systems/${systemId}/flow?lens=build`);
      await expect(page.locator('app-flow-node')).toHaveCount(10);

      // ── The forecast node ─────────────────────────────────────────────────
      await page.locator('app-flow-node').filter({ hasText: 'Prévoir la charge' }).click();
      const section = page.getByTestId('serving-summary');
      await expect(section).toBeVisible();
      // Only forecasts are offered: the churn classifier cannot answer a horizon.
      await expect(page.getByTestId('serving-model').locator('option')).toHaveCount(2);
      await page.getByTestId('serving-model').selectOption('nawa-cells-prb');
      await expect(page.getByTestId('forecast-node-horizon')).toHaveAttribute('placeholder', '24');
      await page.getByTestId('forecast-node-horizon').fill('48');
      await page.getByTestId('forecast-node-horizon').press('Tab');
      await page.getByTestId('forecast-node-level').selectOption('0.9');
      await expect.poll(() => api.params('forecast.prb')).toMatchObject({ model_slug: 'nawa-cells-prb', horizon: 48, interval_level: 0.9 });
      await page.screenshot({ path: info.outputPath(`forecast-node-${theme}-${locale}.png`), fullPage: true });

      // ── The fit, as a forecast ────────────────────────────────────────────
      await page.locator('app-flow-node').filter({ hasText: 'Apprendre la charge' }).click();
      await page.getByTestId('open-train-workshop').click();
      const workshop = page.locator('app-flow-train-workshop');
      await workshop.getByTestId('train-target').locator('[data-testid="column-select"][data-name="prb_utilization_pct"]').click();
      await workshop.getByRole('button', { name: locale === 'fr' ? 'Prévision' : 'Forecasting', exact: true }).click();
      await expect(workshop.getByTestId('train-forecast')).toBeVisible();
      // No random split for a forecast: the backtest judges it.
      await expect(workshop.getByTestId('train-split')).toHaveCount(0);
      await workshop.getByRole('button', { name: locale === 'fr' ? 'Panel de séries' : 'Panel of series' }).click();
      await workshop.getByRole('button', { name: 'cell_id', exact: true }).click();
      await workshop.getByRole('combobox', { name: 'technology' }).selectOption('static');
      await expect.poll(() => api.params('train.prb')).toMatchObject({
        task: 'forecasting',
        target: 'prb_utilization_pct',
        spec: { time_column: 'ts', shape: 'panel', series_columns: ['cell_id'], exog: { technology: 'static' }, horizon: 24 },
      });
      await page.screenshot({ path: info.outputPath(`train-workshop-${theme}-${locale}.png`), fullPage: true });
    });
  }
});
