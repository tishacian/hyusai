import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off' });
const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-tabular-extensions.json'), 'utf8'));
const catalog = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
const workspace = { id: 'skore-qa', slug: 'skore-qa', name: 'Skore QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };

async function setup(page: Page, locale: string, status = 'completed') {
  const writes: string[] = [];
  const dataset = { id: 'skore-data', name: 'Synthetic', slug: 'synthetic', version: 1, status: 'ready', source: 'upload', row_count: 800, schema: fixture.columns, parent_ids: [] };
  const model = { id: 'skore-model', name: 'Synthetic classifier', slug: 'synthetic-classifier', version: 1,
    task: 'classification', family: 'tabular', algo: 'linear', target: 'region', features: ['visits'],
    dataset_id: dataset.id, status: 'ready', is_champion: true, test_size: .25, cross_validation: 0,
    classes: ['North', 'South'], params: { knobs: {} }, spec: {},
    metrics: { ...fixture.classification_metrics,
      evaluation: { schema: 1, status: 'stored', role: 'final_test', fingerprint: 'a'.repeat(64), rows: { total: 800, train: 600, test: 200 }, duplicate_overlap: 1 },
      metric_semantics: { schema: 2, positive_class: 'North', averaging: 'binary' },
      diagnostics: { schema: 1, engine: 'skore', version: '0.27.0', role: 'development', scope: 'development_base_estimator', served_model: false, status,
        checks: [ { code: 'SKD001', title: 'Overfitting', section: 'issue', explanation: 'Training scores exceed development validation scores.', documentation_url: 'https://docs.skore.probabl.ai/stable/' },
          { code: 'SKD009', title: 'Baseline', section: 'skipped', explanation: null },
          { code: 'SKD013', title: 'Temporal overlap', section: 'error', explanation: 'Controlled diagnostic error.' } ] } },
    signature: { inputs: [{ name: 'visits', type: 'long' }] }, input_example: [{ visits: 8 }] };
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer synthetic-skore-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
  }, { slug: workspace.slug, locale });
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (!['GET', 'HEAD'].includes(request.method())) writes.push(path);
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/ml-models/catalog') return json(route, { catalog });
    if (path === `/ml-models/${model.id}`) return json(route, { model, dataset, provenance: null, versions: [model], challenger_id: null, catalog,
      serving: { enabled: true, callable: true, is_serving: true, serving_model_id: model.id, serving_version: 1, fields: [], keys: [], classes: model.classes, positive_label: 'North' } });
    if (path === `/ml-models/${model.id}/evaluation-review`) return json(route, { schema: 1, model_id: model.id, mode: 'proposal_only', status: 'available',
      proposals: [{ code: 'SKD001', hypothesis: 'regularization', evidence_anchor: 'evaluation-check-SKD001', requires: ['review_flow_plan', 'explicit_training', 'independent_evaluation', 'explicit_promotion'] }] });
    if (path === '/datasets') return json(route, { datasets: [dataset] });
    if (path === '/ml-models') return json(route, { models: [model], catalog });
    return json(route, {});
  });
  return writes;
}

test.describe('Skore evaluation evidence', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const locale of ['fr', 'en']) {
    test(`${locale}: navigate from a hypothesis to its evidence without starting a fit`, async ({ page }) => {
      const writes = await setup(page, locale);
      await page.goto('/models/skore-model');
      const evidence = page.getByTestId('evaluation-evidence');
      await expect(evidence).toBeVisible();
      await expect(evidence).toContainText('North');
      await expect(evidence.locator('[data-check-section="skipped"]')).toHaveCount(1);
      await expect(evidence.locator('[data-check-section="error"]')).toHaveCount(1);
      await evidence.getByRole('button', { name: locale === 'fr' ? 'Examiner les pistes d’amélioration' : 'Review improvement hypotheses' }).click();
      const proposal = evidence.locator('a[href$="#evaluation-check-SKD001"]');
      await expect(proposal).toBeVisible();
      await proposal.click();
      await expect(page).toHaveURL(/#evaluation-check-SKD001$/);
      await expect(evidence.locator('#evaluation-check-SKD001')).toContainText('Training scores');
      expect(writes.filter(path => path.startsWith('/ml-models'))).toEqual([]);
    });
  }
  test('an exhausted budget is not a completed review', async ({ page }) => {
    await setup(page, 'fr', 'timed_out');
    await page.goto('/models/skore-model');
    await expect(page.getByTestId('diagnostic-status')).toContainText('Budget');
    await expect(page.getByTestId('evaluation-evidence').getByRole('button')).toHaveCount(0);
  });
});
