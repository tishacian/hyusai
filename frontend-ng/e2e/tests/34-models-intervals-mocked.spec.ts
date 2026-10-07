import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off' });
const intervals = { method: 'cv_conformal_abs', folds: 5, residual_rows: 600, default_level: .9,
  levels: [{ level: .8, q: 3, coverage: .81, width: 6 }, { level: .9, q: 5, coverage: .91, width: 10 }, { level: .95, q: 8, coverage: .94, width: 16 }] };
async function setup(page: Page, locale: string, theme: string) {
  const workspace = { id: 'interval-qa', slug: 'interval-qa', name: 'Intervals', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
  const catalog = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
  catalog.families.find((family: any) => family.key === 'tabular').spec_fields = [{ key: 'intervals', kind: 'enum', default: 'off', choices: ['off', 'conformal'], when: { task: ['regression'] } }];
  const columns = [{ name: 'amount', kind: 'float', distinct: 800, suggested_task: 'regression' }, { name: 'visits', kind: 'integer', distinct: 40, suggested_task: 'regression' }];
  const dataset = { id: 'sales', slug: 'sales', name: 'Sales', version: 1, status: 'ready', source: 'upload', row_count: 800, column_count: 2, schema: columns, parent_ids: [] };
  const model = { id: 'interval-1', name: 'Sales amount', slug: 'amount', version: 1, family: 'tabular', task: 'regression', algo: 'linear', target: 'amount', features: ['visits'], status: 'ready', is_champion: true, dataset_id: 'sales', dataset_slug: 'sales', row_count: 800, test_size: .25, cross_validation: 0, primary_metric: { key: 'r2', value: .8 }, metrics: { primary: { key: 'r2', value: .8 }, scores: [{ key: 'r2', value: .8 }], intervals }, input_example: [{ visits: 5 }], classes: [], params: { knobs: {} }, spec: { intervals: 'conformal' } };
  const serving = { enabled: true, callable: true, serving_version: 1, serving_model_id: model.id, is_serving: true, max_rows: 100, fields: [{ name: 'visits', kind: 'number', required: true, default: 5, min: 0, max: 50 }], classes: [], positive_label: null, predict_count: 0, last_predict_at: null, published_skill: null, keys: [], endpoint: `/api/v1/ml-models/${model.id}/predict`, key_header: 'X-API-Key' };
  const predictions: any[] = [], trains: any[] = [];
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ locale, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer qa'); localStorage.setItem('agentium_workspace_slug', 'interval-qa');
    localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_theme', theme);
  }, { locale, theme });
  await page.route('**/api/v1/**', route => {
    const req = route.request(), path = new URL(req.url()).pathname.replace(/^\/api\/v1/, '');
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/auth/validate') return json({ valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json({ id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json([workspace]);
    if (path.startsWith('/auth/workspaces/')) return json(workspace);
    if (path === '/ml-models/catalog') return json({ catalog });
    if (path === '/ml-models' && req.method() === 'POST') { trains.push(req.postDataJSON()); return json({ model }); }
    if (path === '/ml-models') return json({ models: [model], catalog });
    if (path === '/ml-models/plan') {
      const body = req.postDataJSON();
      return json({ dataset, columns, catalog, refusal: null, plan: body.target ? { task: body.task ?? 'regression', family: 'tabular', target: body.target, features: ['visits'], algo: 'linear', knobs: {}, spec: body.spec ?? {}, test_size: .25, cross_validation: 0, name: 'Sales amount', warnings: [], rows: 800 } : null });
    }
    if (path === '/ml-models/interval-1') return json({ model, dataset, catalog, serving, versions: [model], provenance: null, challenger_id: null });
    if (path === '/ml-models/interval-1/predict') {
      const body = req.postDataJSON(); predictions.push(body);
      const level = body.interval_level ?? .9, q = intervals.levels.find(row => row.level === level)!.q;
      return json({ served: { model_id: model.id, version: 1 }, task: 'regression', target: 'amount', classes: [], positive_label: null, rows: 1, duration_ms: 2, predictions: [{ prediction: 42, lower: 42-q, upper: 42+q, level }] });
    }
    if (path === '/datasets') return json({ datasets: [dataset], feature: { enabled: true } });
    return json({});
  });
  return { predictions, trains };
}
for (const [locale, theme] of [['fr', 'dark'], ['en', 'light']] as const) {
  test(`${theme}/${locale}: intervals reach training, Evidence and Play`, async ({ page }) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1', 'Mocked QA only');
    const calls = await setup(page, locale, theme);
    await page.goto('/models');
    await page.getByRole('button', { name: locale === 'fr' ? /Entraîner/ : /Train/ }).first().click();
    const studio = page.getByRole('dialog');
    await studio.getByTestId('train-target').locator('[data-testid="column-select"][data-name="amount"]').click();
    await studio.getByTestId('tabular-options').locator('summary').click();
    await studio.locator('#tabular-intervals').selectOption('conformal');
    await studio.locator('.ck-submit').click();
    await expect.poll(() => calls.trains.at(-1)?.spec).toEqual({ intervals: 'conformal' });
    await page.goto('/models/interval-1');
    await expect(page.getByTestId('interval-evidence')).toBeVisible();
    await page.getByRole('tab', { name: locale === 'fr' ? 'Prédire' : 'Predict', exact: true }).click();
    await page.locator('#predict-interval-level').selectOption('0.95');
    await page.getByRole('button', { name: locale === 'fr' ? 'Prédire' : 'Predict', exact: true }).click();
    await expect.poll(() => calls.predictions.at(-1)?.interval_level).toBe(.95);
    await expect(page.getByTestId('prediction-interval')).toContainText('34');
    await expect(page.getByTestId('prediction-interval')).toContainText('50');
    await expect(page.locator('pre').filter({ hasText: 'curl -X POST' })).toContainText('"interval_level":0.95');
  });
}
