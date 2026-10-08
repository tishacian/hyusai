import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Locator, type Page, type Route } from '@playwright/test';

// The 2a catalog has no enabled extensions. Synthetic descriptors exercise the
// shared renderer without advertising a later lot's training capabilities.
test.use({ serviceWorkers: 'block', video: 'off' });
const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-tabular-extensions.json'), 'utf8'));
const baseline = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
const workspace = { id: 'tabular-qa', slug: 'tabular-qa', name: 'Tabular QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const schema = fixture.columns.map((column: any) => ({ name: column.name, kind: column.kind, dtype: column.kind }));
const dataset = { id: 'ds-tabular', name: 'Sales', slug: 'sales', version: 1, source: 'upload', status: 'ready', row_count: 800, column_count: schema.length, schema, parent_ids: [], created_at: '2026-10-07T09:00:00Z' };
const model = {
  id: 'regression-1', name: 'Sales amount', slug: 'sales-amount', version: 1, task: 'regression', family: 'tabular',
  algo: 'gradient_boosting', target: 'amount', features: ['visits'], status: 'ready', is_champion: true,
  dataset_id: dataset.id, dataset_slug: dataset.slug, row_count: 800, test_size: 0.25, cross_validation: 0,
  trained_at: '2026-10-07T09:12:00Z', primary_metric: { key: 'r2', value: 0.8 },
  metrics: { tuning: fixture.tuning, primary: { key: 'r2', value: 0.8 }, scores: [{ key: 'r2', value: 0.8 }] },
  signature: { inputs: [{ name: 'visits', type: 'long' }], outputs: [{ name: 'prediction', type: 'double' }] },
  input_example: [], classes: [], params: { knobs: {} }, spec: {},
};
const monitoring = {
  badge: null, window: { predictions: 1, labeled: 0, limit: 1000 }, data_drift: { status: 'insufficient', features: [] },
  score_drift: { status: 'insufficient', value: null, served_mean: null, reference_mean: null, n: 1 },
  concept_drift: { status: 'insufficient', rolling_auc: null, train_auc: null, delta: null, labeled: 0 },
};
const systemId = 'tabular-system';
function flow() {
  const graph = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/app/resources/flows/showcase_ecommerce_claims_v1.json'), 'utf8'));
  graph.nodes.forEach((node: any, index: number) => { node.position = { x: 40 + (index % 4) * 330, y: 40 + Math.floor(index / 4) * 250 }; });
  graph.nodes.push({ id: 'train.sales', type: 'skill', kind: 'task', label: 'Train sales', position: { x: 40, y: 560 }, config: { skill_slug: 'ml_train_sklearn_v1', params: { task: null, target: '', features: null, algo: '', knobs: {}, test_size: 0.25, cross_validation: 0, model_name: '', spec: null, sources: [{ dataset_slug: dataset.slug }] } } });
  return graph;
}

async function setup(page: Page, options: { theme: string; locale: string; fields?: boolean }) {
  const catalog = structuredClone(baseline);
  catalog.families.find((family: any) => family.key === 'tabular').spec_fields = options.fields === false ? [] : fixture.tuning_fields;
  const plans: any[] = [], trains: any[] = [], drafts: any[] = [], feedback: any[] = [];
  let graph = flow(), revision = 1;
  const hash = '3'.repeat(64);
  const system = () => ({ id: systemId, workspace_id: workspace.id, name: 'Sales', status: 'active', flow_definition: graph, flow_sha256: hash, objective: 'Sales' });
  const state = () => ({ system_id: systemId, status: 'active', draft: { revision, base_published_version_id: 'published-v1', flow_sha256: hash, flow_definition: graph }, published: { version_id: 'published-v1', version_number: 1, flow_sha256: hash, flow_definition: graph, execution_contract_ready: true } });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', (route) => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ theme, locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer tabular-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', theme);
    localStorage.setItem('agentium_locale', locale);
  }, { ...options, slug: workspace.slug });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/ml-models/catalog') return json(route, { catalog });
    if (path === '/ml-models' && request.method() === 'POST') {
      trains.push(request.postDataJSON());
      return json(route, { model: { ...model, id: 'regression-2', version: 2, status: 'pending', metrics: {} } });
    }
    if (path === '/ml-models') return json(route, { models: [model], catalog });
    if (path === '/ml-models/plan') {
      const body = request.postDataJSON(); plans.push(body);
      const base = { dataset, columns: fixture.columns, catalog, plan: null, refusal: null };
      if (!body.target) return json(route, base);
      return json(route, { ...base, plan: { task: body.task ?? fixture.columns.find((column: any) => column.name === body.target)?.suggested_task, family: 'tabular', spec: body.spec ?? {}, target: body.target, features: ['visits'], algo: body.algo || 'gradient_boosting', estimator: 'sklearn.ensemble.HistGradientBoostingRegressor', knobs: {}, test_size: 0.25, cross_validation: 0, name: 'Sales amount', warnings: [], rows: 800 } });
    }
    if (path === `/ml-models/${model.id}`) return json(route, { model, dataset, provenance: null, versions: [model], challenger_id: null, catalog, serving: { enabled: true, callable: true, serving_version: 1, serving_model_id: model.id, is_serving: true, max_rows: 100, fields: [{ name: 'visits', kind: 'integer', required: true }], classes: [], positive_label: null, predict_count: 1, last_predict_at: null, published_skill: null, keys: [], endpoint: `/api/v1/ml-models/${model.id}/predict`, key_header: 'X-Agentium-Model-Key' } });
    if (path === `/ml-models/${model.id}/monitoring`) return json(route, { monitoring });
    if (path === `/ml-models/${model.id}/feedback`) {
      const body = request.postDataJSON(); feedback.push(body);
      if (!Number.isFinite(Number(body.label))) return json(route, { detail: { code: 'ML_FEEDBACK_NOT_NUMERIC', message: 'Numeric label required' } }, 422);
      return json(route, { prediction: { id: body.prediction_id, label: body.label }, monitoring: { ...monitoring, window: { ...monitoring.window, labeled: 1 } } });
    }
    if (path === '/datasets') return json(route, { datasets: [dataset], feature: { enabled: true, upload_max_bytes: 1 << 26 } });
    if (path === `/datasets/${dataset.id}/preview`) return json(route, { dataset_id: dataset.id, schema, rows: [], offset: 0, limit: 50, total: 800 });
    if (path === '/systems') return json(route, { systems: [system()] });
    if (path === `/systems/${systemId}`) return json(route, system());
    if (path === `/systems/${systemId}/flow-state`) return json(route, state());
    if (path === `/systems/${systemId}/flow-draft` && request.method() === 'PUT') {
      graph = request.postDataJSON().flow_definition; drafts.push(graph); revision++;
      return json(route, { ...state().draft, system_id: systemId, no_op: false });
    }
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_overlay', flow_sha256: hash });
    if (path === '/skills') return json(route, { skills: [] });
    if (path === '/documents/collections') return json(route, { collections: [] });
    if (path === '/connectors') return json(route, { can_configure: true, connectors: [] });
    return json(route, {});
  });
  return { plans, trains, feedback, params: () => drafts.at(-1)?.nodes.find((node: any) => node.id === 'train.sales')?.config?.params ?? {} };
}

async function tune(host: Locator) {
  await host.getByTestId('tabular-options').locator('summary').click();
  await host.locator('#tabular-tuning').selectOption('budget');
  await host.locator('#tabular-tuning_trials').fill('5');
  await host.locator('#tabular-tuning_budget_s').fill('30');
  await host.locator('#tabular-tuning_budget_s').press('Tab');
}

test.describe('Models · budgeted tuning — mocked QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const [theme, locale] of [['dark', 'fr'], ['light', 'en']] as const) {
    test(`${theme}/${locale}: tuning form reaches train and Evidence`, async ({ page }, info) => {
      const api = await setup(page, { theme, locale });
      await page.goto('/models');
      await page.getByRole('button', { name: locale === 'fr' ? /Entraîner/ : /Train/ }).first().click();
      const studio = page.getByRole('dialog');
      await studio.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
      await tune(studio);
      await expect.poll(() => api.plans.at(-1)?.spec).toEqual({ tuning: 'budget', tuning_trials: 5, tuning_budget_s: 30 });
      await studio.locator('.ck-submit').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0].spec).toEqual({ tuning: 'budget', tuning_trials: 5, tuning_budget_s: 30 });
      await page.goto(`/models/${model.id}`);
      await page.getByRole('tab', { name: locale === 'fr' ? 'Résultats' : 'Results', exact: true }).click();
      const evidence = page.getByTestId('tuning-evidence');
      await expect(evidence).toContainText(locale === 'fr' ? 'Nombre d’essais atteint' : 'Trial limit reached');
      await expect(evidence.locator('circle')).toHaveCount(4);
      await expect(evidence.getByRole('row')).toHaveCount(4);
      await evidence.screenshot({ path: info.outputPath(`tuning-${theme}-${locale}.png`) });
      await page.getByRole('tab', { name: locale === 'fr' ? 'Prédire' : 'Predict', exact: true }).click();
      await expect(page.getByTestId('tuning-evidence')).not.toBeVisible();
    });
    test(`${theme}/${locale}: Flow persists and submits the same options`, async ({ page }) => {
      const api = await setup(page, { theme, locale });
      await page.goto(`/systems/${systemId}/flow?lens=build`);
      await page.locator('app-flow-node').filter({ hasText: 'Train sales' }).click();
      await page.getByTestId('open-train-workshop').click();
      const workshop = page.locator('app-flow-train-workshop');
      await workshop.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
      await tune(workshop);
      await expect.poll(() => api.params()).toMatchObject({ spec: { tuning: 'budget', tuning_trials: 5, tuning_budget_s: 30 } });
      await workshop.getByTestId('run-train-test').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0].spec).toEqual({ tuning: 'budget', tuning_trials: 5, tuning_budget_s: 30 });
    });
  }
});
