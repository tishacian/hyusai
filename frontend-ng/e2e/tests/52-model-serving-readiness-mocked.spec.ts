import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8'));
const modelId = '4d551f64-bbb7-49cf-98bc-157b5e45b710';
const dataset = {
  id: 'forecast-history', name: 'Daily service volume', slug: 'service-volume', version: 1,
  source: 'upload', status: 'ready', row_count: 420, column_count: 2, parent_ids: [],
  schema: [{ name: 'observed_at', dtype: 'Datetime', kind: 'datetime' }, { name: 'volume', dtype: 'Float64', kind: 'float' }],
};
const model = {
  id: modelId, name: 'Service volume forecast', slug: 'service-volume-forecast', version: 1,
  task: 'forecasting', family: 'forecasting', algo: 'gradient_boosting', target: 'volume',
  features: [], status: 'ready', is_champion: true, dataset_id: dataset.id, dataset_slug: dataset.slug,
  row_count: 420, test_size: .1, cross_validation: 3, trained_at: '2026-10-09T14:00:00Z', train_duration_ms: 28000,
  primary_metric: fixture.panel.metrics.primary, metrics: fixture.panel.metrics, signature: fixture.panel.signature,
  input_example: [], classes: [], params: { knobs: {} },
  spec: { time_column: 'observed_at', shape: 'single', horizon: 28, backtest_folds: 3, interval_level: .8, frequency: 'D' },
};

async function setup(page: Page, theme: string, canTrain: boolean) {
  const workspace = { id: 'readiness-qa', slug: 'readiness-qa', name: 'Model readiness QA', role: canTrain ? 'owner' : 'viewer', role_template: canTrain ? 'workspace_owner' : 'workspace_viewer', settings: {}, mode: 'builder' };
  const writes: string[] = [];
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ slug, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-model-readiness-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', theme);
    localStorage.setItem('agentium_locale', 'en');
  }, { slug: workspace.slug, theme });
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (!['GET', 'HEAD'].includes(request.method())) writes.push(path);
    const user = { id: 'qa-user', user_id: 'qa-user', valid: true, role: canTrain ? 'admin' : 'user', email: 'qa@example.test', is_active: true, workspaces: [workspace] };
    if (['/auth/validate', '/auth/me'].includes(path)) return json(route, user);
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (path === '/ml-models/catalog') return json(route, { catalog: fixture.catalog });
    if (path === '/ml-models/' + modelId) return json(route, {
      model, dataset, provenance: null, versions: [model], challenger_id: null, catalog: fixture.catalog,
      serving: {
        enabled: true, callable: false, is_serving: true, serving_model_id: modelId, serving_version: 1,
        readiness: { training_ready: true, state: 'blocked', check: 'metadata', action: 'retrain' },
        refusal: { code: 'ML_ARTIFACT_LEGACY_UNSUPPORTED', message: 'Do not show this raw worker message.' },
        permissions: { train: canTrain, promote: canTrain, delete: false, keys: false, publish: false },
        fields: [], classes: [], keys: [], max_rows: 100, mode: 'forecast', predict_count: 0,
        endpoint: '/api/v1/ml-models/' + modelId + '/forecast', key_header: 'X-Agentium-Model-Key',
      },
    });
    if (path === '/ml-models') return json(route, { models: [model], catalog: fixture.catalog });
    if (path === '/ml-models/plan') return json(route, { dataset, columns: [], catalog: fixture.catalog, plan: null, refusal: null });
    if (path === '/datasets') return json(route, { datasets: [dataset] });
    return json(route, {});
  });
  return writes;
}

test.describe('Model serving readiness — isolated UI QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const variant of [
    { width: 1440, height: 1000, theme: 'dark', canTrain: true },
    { width: 390, height: 844, theme: 'light', canTrain: true },
    { width: 390, height: 844, theme: 'light', canTrain: false },
  ]) {
    const name = `${variant.theme}-${variant.width}-${variant.canTrain ? 'owner' : 'viewer'}`;
    test(name + ': training completion never promises callable serving', async ({ page }, info) => {
      await page.setViewportSize({ width: variant.width, height: variant.height });
      const writes = await setup(page, variant.theme, variant.canTrain);
      await page.goto('/models/' + modelId);
      const banner = page.getByTestId('serving-readiness-refusal');
      await expect(banner).toBeVisible();
      await expect(page.getByTestId('serving-readiness')).toHaveText('Calls unavailable');
      await expect(page.getByText('Training complete', { exact: true })).toBeVisible();
      await expect(page.getByText('Selected version', { exact: true }).first()).toBeVisible();
      await expect(banner).toContainText('This older artifact lacks the required contract.');
      await expect(banner).toContainText(variant.canTrain ? 'Use Retrain to create a new version.' : 'Ask an owner to retrain and evaluate a new version');
      await expect(page.locator('body')).not.toContainText('ML_ARTIFACT_LEGACY_UNSUPPORTED');
      await expect(page.locator('body')).not.toContainText('Do not show this raw worker message.');
      const headerMetrics = await page.locator('ck-object-header').evaluate(element => ({ width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }));
      const bannerMetrics = await banner.evaluate(element => ({
        height: element.getBoundingClientRect().height,
        paragraphs: [...element.querySelectorAll('p')].map(paragraph => ({
          fontSize: getComputedStyle(paragraph).fontSize,
          lineHeight: getComputedStyle(paragraph).lineHeight,
        })),
      }));
      const overflow = await page.evaluate(() => ({ viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.viewport);
      expect((await new AxeBuilder({ page }).include('[data-testid="serving-readiness-refusal"]').analyze()).violations).toEqual([]);
      await page.screenshot({ path: info.outputPath(`${name}-overview.png`) });
      await banner.screenshot({ path: info.outputPath(`${name}-banner.png`) });
      await page.getByRole('tab', { name: /Predict/i }).click();
      await expect(page.getByText('This model does not answer yet', { exact: true })).toBeVisible();
      await expect(page.getByTestId('forecast-run')).toHaveCount(0);
      await expect(page.getByTestId('forecast-playground')).toHaveCount(0);
      await page.screenshot({ path: info.outputPath(`${name}-predict.png`) });
      const retrain = page.getByRole('button', { name: 'Retrain', exact: true });
      if (variant.canTrain) {
        await expect(retrain).toBeEnabled();
        await retrain.click();
        await expect(page.getByRole('dialog')).toBeVisible();
      } else {
        await expect(retrain).toHaveCount(0);
      }
      expect(writes.filter(path => path === '/ml-models' || /\/(forecast|predict|promote)$/.test(path))).toEqual([]);
      writeFileSync(info.outputPath(`${name}.json`), JSON.stringify({ ...variant, language: 'en', localMocked: true, headerMetrics, bannerMetrics, overflow, rawErrorVisible: false, predictCallUnavailable: true, retrainOpensDialog: variant.canTrain, writes }, null, 2));
    });
  }
});
