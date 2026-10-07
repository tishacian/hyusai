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
  metrics: { primary: { key: 'r2', value: 0.8 }, scores: [{ key: 'r2', value: 0.8 }] },
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
  catalog.families.find((family: any) => family.key === 'tabular').spec_fields = options.fields === false ? [] : fixture.fields;
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

async function editOptions(host: Locator, locale: string) {
  const options = host.getByTestId('tabular-options');
  await expect(options).not.toHaveAttribute('open');
  await options.locator('summary').click();
  await expect(options).toContainText(locale === 'fr' ? 'Options avancées' : 'Advanced options');
  await expect(options.locator('[data-spec-field="probe_count"]')).toHaveCount(0);
  await options.locator('#tabular-probe_mode').selectOption('on');
  await expect(options.locator('#tabular-probe_count')).toHaveValue('3');
  await options.locator('#tabular-probe_count').fill('5');
  await options.locator('#tabular-probe_count').press('Tab');
  await options.getByLabel('region', { exact: true }).check();
  await expect(options.getByLabel('segment', { exact: true })).toBeDisabled();
  await expect(options.locator('[data-spec-field="probe_enabled"]')).toHaveCount(0);
}

test.describe('Models · tabular foundation — mocked QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const [theme, locale] of [['dark', 'fr'], ['light', 'en']] as const) {
    test(`${theme}/${locale}: studio options follow the resolved task and train request`, async ({ page }, info) => {
      await page.setViewportSize({ width: 1440, height: 1000 });
      const api = await setup(page, { theme, locale });
      await page.goto('/models');
      await page.getByRole('button', { name: locale === 'fr' ? /Entraîner/ : /Train/ }).first().click();
      const studio = page.getByRole('dialog');
      await studio.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
      await editOptions(studio, locale);
      await expect.poll(() => api.plans.at(-1)?.spec).toMatchObject({ probe_mode: 'on', probe_count: 5, probe_columns: ['region'] });
      await studio.getByRole('button', { name: 'Classification', exact: true }).click();
      await expect(studio.locator('#tabular-probe_mode')).toHaveCount(0);
      await expect(studio.locator('#tabular-probe_enabled')).toBeVisible();
      await expect.poll(() => api.plans.at(-1)?.spec).toEqual({ probe_enabled: false });
      await studio.getByRole('button', { name: locale === 'fr' ? 'Régression' : 'Regression', exact: true }).click();
      await expect(studio.locator('#tabular-probe_count')).toHaveValue('5');
      await expect(studio.locator('.ck-submit')).toBeEnabled();
      await studio.getByTestId('tabular-options').screenshot({ path: info.outputPath(`options-${theme}-${locale}.png`) });
      await studio.locator('.ck-submit').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0].spec).toEqual({ probe_mode: 'on', probe_count: 5, probe_columns: ['region'] });
      expect(api.trains[0].test_size).toBe(0.25);
    });

    test(`${theme}/${locale}: Flow options persist and reach its plan`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 1000 });
      const api = await setup(page, { theme, locale });
      await page.goto(`/systems/${systemId}/flow?lens=build`);
      await page.locator('app-flow-node').filter({ hasText: 'Train sales' }).click();
      await page.getByTestId('open-train-workshop').click();
      const workshop = page.locator('app-flow-train-workshop');
      await workshop.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
      await editOptions(workshop, locale);
      await expect.poll(() => api.params()).toMatchObject({ target: 'amount', spec: { probe_mode: 'on', probe_count: 5, probe_columns: ['region'] } });
      await expect.poll(() => api.plans.at(-1)?.spec).toMatchObject({ probe_mode: 'on', probe_count: 5, probe_columns: ['region'] });
      await workshop.getByTestId('run-train-test').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0].spec).toEqual({ probe_mode: 'on', probe_count: 5, probe_columns: ['region'] });
    });

    test(`${theme}/${locale}: regression feedback explains invalid numbers`, async ({ page }) => {
      const api = await setup(page, { theme, locale, fields: false });
      await page.goto(`/models/${model.id}`);
      await page.getByRole('tab', { name: locale === 'fr' ? 'Suivi' : 'Monitoring', exact: true }).click();
      await page.getByLabel(locale === 'fr' ? 'Prédiction' : 'Prediction', { exact: true }).fill('prediction-1');
      await page.getByLabel(locale === 'fr' ? 'Issue' : 'Outcome', { exact: true }).fill('invalid');
      await page.getByRole('button', { name: locale === 'fr' ? 'Enregistrer' : 'Save', exact: true }).click();
      await expect(page.getByText(locale === 'fr' ? 'L’issue réelle doit être un nombre fini pour un modèle de régression.' : 'Ground truth must be a finite number for a regression model.', { exact: true })).toBeVisible();
      await page.getByLabel(locale === 'fr' ? 'Issue' : 'Outcome', { exact: true }).fill('12.5');
      await page.getByRole('button', { name: locale === 'fr' ? 'Enregistrer' : 'Save', exact: true }).click();
      await expect.poll(() => api.feedback.at(-1)?.label).toBe('12.5');
      await expect(page.getByText(locale === 'fr' ? 'Issue enregistrée' : 'Outcome saved', { exact: true })).toBeVisible();
    });
  }

  test('the real empty catalog offers no premature options', async ({ page }) => {
    await setup(page, { theme: 'dark', locale: 'fr', fields: false });
    await page.goto('/models');
    await page.getByRole('button', { name: /Entraîner/ }).first().click();
    await page.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
    await expect(page.getByTestId('tabular-options')).toHaveCount(0);
    await expect(page.locator('.ck-submit')).toBeEnabled();
  });
});
