import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Locator, type Page, type Route } from '@playwright/test';

// The 2a catalog has no enabled extensions. Synthetic descriptors exercise the
// shared renderer without advertising a later lot's training capabilities.
test.use({ serviceWorkers: 'block', video: 'off' });
const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-tabular-extensions.json'), 'utf8'));
fixture.columns.push({ name: 'message', kind: 'string', distinct: 800, nulls: 0, suggested_task: 'classification', role: 'text' });
const baseline = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
const workspace = { id: 'tabular-qa', slug: 'tabular-qa', name: 'Tabular QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const schema = fixture.columns.map((column: any) => ({ name: column.name, kind: column.kind, dtype: column.kind }));
const dataset = { id: 'ds-tabular', name: 'Sales', slug: 'sales', version: 1, source: 'upload', status: 'ready', row_count: 800, column_count: schema.length, schema, parent_ids: [], created_at: '2026-10-07T09:00:00Z' };
const model = {
  id: 'regression-1', name: 'Sales amount', slug: 'sales-amount', version: 1, task: 'regression', family: 'tabular',
  algo: 'gradient_boosting', target: 'amount', features: ['message'], status: 'ready', is_champion: true,
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

async function setup(page: Page, options: { theme: string; locale: string; fields?: boolean; deep?: boolean; available?: boolean; workerDown?: boolean; savedSpec?: Record<string,unknown> }) {
  const catalog = structuredClone(baseline);
  catalog.families.find((family: any) => family.key === 'tabular').spec_fields = options.fields === false ? [] : fixture.text_fields;
  if (options.deep) catalog.families.push({key:'tabular_deep',tasks:['classification','regression'],runtime:'ml-deep',serving:'remote',available:options.available!==false,spec_fields:[
    {key:'text_encoder',kind:'enum',default:'embedding',choices:['embedding']},
    {key:'embedding_columns',kind:'columns',required:true,max_items:1,column_kinds:['string','text','categorical']},
    {key:'embedding_components',kind:'int',default:30,min:2,max:128},
    {key:'tuning',kind:'enum',default:'off',choices:['off','budget']},
  ]});
  const plans: any[] = [], trains: any[] = [], drafts: any[] = [], feedback: any[] = [];
  let graph = flow(), revision = 1;
  if (options.savedSpec) Object.assign(graph.nodes.find((node:any) => node.id === 'train.sales').config.params,
    {target:'amount',task:'regression',algo:'gradient_boosting',spec:options.savedSpec});
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
      return json(route, { ...base, plan: { task: body.task ?? fixture.columns.find((column: any) => column.name === body.target)?.suggested_task, family: 'tabular', spec: body.spec ?? {}, target: body.target, features: ['message'], algo: body.algo || 'gradient_boosting', estimator: 'sklearn.ensemble.HistGradientBoostingRegressor', knobs: {}, test_size: 0.25, cross_validation: 0, name: 'Sales amount', warnings: [], rows: 800 } });
    }
    if (path === `/ml-models/${model.id}`) return json(route, { model: {...model, family: options.deep ? 'tabular_deep' : model.family}, dataset, provenance: null, versions: [model], challenger_id: null, catalog, serving: { enabled: true, callable: !options.workerDown, mode: 'rows', serving_version: 1, serving_model_id: model.id, is_serving: true, max_rows: 100, fields: [{ name: 'visits', kind: 'integer', required: true }], classes: [], positive_label: null, predict_count: 1, last_predict_at: null, published_skill: null, keys: [], endpoint: `/api/v1/ml-models/${model.id}/predict`, key_header: 'X-Agentium-Model-Key' } });
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

test.describe('Models · text encoder — mocked QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const [theme, locale] of [['dark', 'fr'], ['light', 'en']] as const) {
    test(`${theme}/${locale}: studio exposes text role and encoder`, async ({ page }, info) => {
      const api = await setup(page, { theme, locale });
      await page.goto('/models');
      await page.getByRole('button', { name: locale === 'fr' ? /Entraîner/ : /Train/ }).first().click();
      const studio = page.getByRole('dialog');
      await studio.getByTestId('train-target').locator('[data-testid="column-select"][data-name="region"]').click();
      const options = studio.getByTestId('tabular-options');
      await options.locator('summary').click();
      await expect(options.getByTestId('tabular-text-columns')).toContainText('message');
      await expect(options.locator('#tabular-text_encoder')).toHaveValue('auto');
      await options.locator('#tabular-text_encoder').selectOption('minhash');
      await expect.poll(() => api.plans.at(-1)?.spec).toEqual({ text_encoder: 'minhash' });
      await options.screenshot({ path: info.outputPath(`text-${theme}-${locale}.png`) });
      await studio.locator('.ck-submit').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0].spec).toEqual({ text_encoder: 'minhash' });
      expect(api.trains[0].task).toBe('classification');
      expect(api.trains[0].features).toContain('message');
    });
    test(`${theme}/${locale}: Flow keeps its text settings`, async ({ page }) => {
      const api = await setup(page, { theme, locale });
      await page.goto(`/systems/${systemId}/flow?lens=build`);
      await page.locator('app-flow-node').filter({ hasText: 'Train sales' }).click();
      await page.getByTestId('open-train-workshop').click();
      const workshop = page.locator('app-flow-train-workshop');
      await workshop.getByTestId('train-target').locator('[data-testid="column-select"][data-name="region"]').click();
      await workshop.getByTestId('tabular-options').locator('summary').click();
      await expect(workshop.getByTestId('tabular-text-columns')).toContainText('message');
      await workshop.locator('#tabular-text_encoder').selectOption('string');
      await expect.poll(() => api.params()).toMatchObject({ spec: { text_encoder: 'string' } });
      await workshop.getByTestId('run-train-test').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0].spec).toEqual({ text_encoder: 'string' });
    });
  }
});


test.describe('Models · local embeddings — mocked QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const locale of ['fr','en']) {
    test(`embeddings ${locale}: explicit column, frozen encoder and one train/test split`, async ({page}) => {
      const api = await setup(page,{theme:'dark',locale,deep:true});
      await page.goto('/models');
      await page.getByRole('button',{name:locale==='fr'?/Entraîner/:/Train/}).first().click();
      const studio = page.getByRole('dialog');
      await studio.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
      await studio.locator('#train-cv').selectOption({index:1});
      await studio.getByTestId('tabular-options').locator('summary').click();
      await studio.locator('#tabular-text_encoder').selectOption('embedding');
      await expect(studio.getByTestId('embedding-scope')).toBeVisible();
      await expect(studio.locator('.ck-submit')).toBeDisabled();
      await studio.locator('#train-cv').selectOption({index:0});
      await expect(studio.locator('.ck-submit')).toBeDisabled();
      await studio.locator('[data-spec-field="embedding_columns"]').getByRole('checkbox',{name:'message',exact:true}).check();
      await studio.locator('#tabular-embedding_components').fill('12');
      await studio.locator('#tabular-embedding_components').press('Tab');
      await expect(studio.locator('#tabular-tuning option')).toHaveCount(1);
      await expect(studio.locator('.ck-submit')).toBeEnabled();
      await studio.locator('.ck-submit').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0]).toMatchObject({cross_validation:0,spec:{text_encoder:'embedding',embedding_columns:['message'],embedding_components:12,tuning:'off'}});
    });
    test(`embeddings ${locale}: Flow round-trip retains the selected text feature`, async ({page}) => {
      const api = await setup(page,{theme:'light',locale,deep:true});
      await page.goto(`/systems/${systemId}/flow?lens=build`);
      await page.locator('app-flow-node').filter({hasText:'Train sales'}).click();
      await page.getByTestId('open-train-workshop').click();
      const workshop = page.locator('app-flow-train-workshop');
      await workshop.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
      await workshop.getByTestId('tabular-options').locator('summary').click();
      await workshop.locator('#tabular-text_encoder').selectOption('embedding');
      await expect(workshop.getByTestId('run-train-test')).toBeDisabled();
      await workshop.locator('[data-spec-field="embedding_columns"]').getByRole('checkbox',{name:'message',exact:true}).check();
      await workshop.locator('#tabular-embedding_components').fill('12');
      await workshop.locator('#tabular-embedding_components').press('Tab');
      await expect.poll(() => api.params().spec).toMatchObject({text_encoder:'embedding',embedding_columns:['message'],embedding_components:12});
      await workshop.getByRole('button',{name:locale==='fr'?'Fermer l’atelier d’entraînement':'Close the training studio',exact:true}).click();
      await page.getByTestId('open-train-workshop').click();
      await workshop.getByTestId('tabular-options').locator('summary').click();
      await expect(workshop.locator('#tabular-text_encoder')).toHaveValue('embedding');
      await expect(workshop.locator('#tabular-embedding_components')).toHaveValue('12');
      await workshop.getByTestId('run-train-test').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0]).toMatchObject({cross_validation:0,spec:{text_encoder:'embedding',embedding_columns:['message'],embedding_components:12,tuning:'off'}});
    });
  }
  test('unavailable local encoder leaves classic text encoders usable', async ({page}) => {
    await setup(page,{theme:'dark',locale:'fr',deep:true,available:false});
    await page.goto('/models');
    await page.getByRole('button',{name:/Entraîner/}).first().click();
    const studio = page.getByRole('dialog');
    await studio.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
    await studio.getByTestId('tabular-options').locator('summary').click();
    await expect(studio.locator('#tabular-text_encoder option[value="embedding"]')).toHaveCount(0);
    await studio.locator('#tabular-text_encoder').selectOption('minhash');
    await expect(studio.locator('.ck-submit')).toBeEnabled();
  });
});


test('embeddings: a removed saved text column can be explicitly replaced in Flow', async ({page}, info) => {
  test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  const api = await setup(page,{theme:'dark',locale:'en',deep:true,savedSpec:{text_encoder:'embedding',embedding_columns:['deleted_message'],embedding_components:12}});
  await page.goto(`/systems/${systemId}/flow?lens=build`);
  await page.locator('app-flow-node').filter({hasText:'Train sales'}).click();
  await page.getByTestId('open-train-workshop').click();
  const workshop = page.locator('app-flow-train-workshop');
  await workshop.getByTestId('tabular-options').locator('summary').click();
  const message = workshop.locator('[data-spec-field="embedding_columns"]').getByRole('checkbox',{name:'message',exact:true});
  await expect(message).toBeDisabled();
  await expect(workshop.getByTestId('run-train-test')).toBeDisabled();
  await workshop.getByRole('button',{name:'Remove “deleted_message”',exact:true}).click();
  await expect(message).toBeEnabled();
  await message.check();
  await expect.poll(() => api.params().spec?.embedding_columns).toEqual(['message']);
  await expect(workshop.getByTestId('run-train-test')).toBeEnabled();
});


test('embeddings: a ready model with an absent worker keeps its trained status in Play', async ({page}, info) => {
  test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  await setup(page,{theme:'light',locale:'en',deep:true,workerDown:true});
  await page.goto(`/models/${model.id}`);
  await page.getByRole('tab',{name:'Predict',exact:true}).click();
  await expect(page.locator('app-model-playground')).toContainText('The model is ready, but its prediction service is temporarily unavailable.');
});
