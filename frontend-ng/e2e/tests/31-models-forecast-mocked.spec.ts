import { readFileSync } from 'node:fs';
import { addFoundationCatalog } from '../fixtures/ml-foundation';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Forecasting on the Models surface, against a mocked API.
 *
 * The card reads a real harness result (`e2e/fixtures/ml-forecast.json`: four
 * Nawa cells, hourly PRB, a 24-step backtest) and the catalog the backend
 * serves when an ml-ts worker is listening, so what is on screen is what a
 * trained forecast looks like — not a hand-written approximation of it.
 */

test.use({ serviceWorkers: 'block', video: 'off' });

const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8'));
fixture.catalog.families.find((family: any) => family.key === 'forecasting').spec_fields.push(
  {key:'tuning',kind:'enum',required:false,default:'off',choices:['off','budget']},
  {key:'tuning_trials',kind:'int',required:false,default:30,min:5,max:100},
  {key:'tuning_budget_s',kind:'int',required:false,default:60,min:30,max:60},
  {key:'tuning_folds',kind:'int',required:false,default:3,min:2,max:5},
);
fixture.panel.metrics.tuning = {
  metric:'mae',direction:'min',trials_run:5,trials_pruned:0,trials_failed:0,stopped_by:'trials',budget_s:60,elapsed_s:9,folds:3,
  start:{knobs:{alpha:1},score:4,std:.3},best:{knobs:{alpha:.1},score:3,std:.2,trial:1},
  trials:[{n:0,score:4,state:'complete',duration_ms:500},{n:1,score:3,state:'complete',duration_ms:600}],
  baseline:{key:'seasonal_naive',mae:5},
  validation:{method:'expanding_window',metric:'mae',aggregation:'mean_per_series',train_start:'2026-08-01',train_end:'2026-08-21',holdout_start:'2026-08-22',holdout_rows:72,initial_train_size:432,rows:504,horizon:24,folds:3},
};
addFoundationCatalog(fixture.catalog);
const workspace = { id: 'forecast-qa', slug: 'forecast-qa', name: 'Nawa QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const datasetId = 'ds-cells';
const modelId = 'fc-cells-1';

const schema = [
  { name: 'cell_id', dtype: 'String', kind: 'string' },
  { name: 'technology', dtype: 'String', kind: 'string' },
  { name: 'ts', dtype: 'Datetime', kind: 'datetime' },
  { name: 'prb_utilization_pct', dtype: 'Float64', kind: 'float' },
  { name: 'active_users', dtype: 'Int64', kind: 'integer' },
];
const dataset = {
  id: datasetId, name: 'Cellules Nawa · horaire', slug: 'nawa-cells', version: 1, source: 'upload', status: 'ready',
  row_count: 2688, column_count: schema.length, schema, parent_ids: [], created_at: '2026-10-07T09:00:00Z',
};
const columns = schema.map((column) => ({
  name: column.name, kind: column.kind, distinct: column.name === 'cell_id' ? 4 : 600, nulls: 0,
  suggested_task: column.kind === 'float' || column.kind === 'integer' ? 'regression' : 'classification',
}));
const model = {
  id: modelId, name: 'Cellules Nawa · prb_utilization_pct +24', slug: 'nawa-cells-prb', version: 1,
  task: 'forecasting', family: 'forecasting', algo: 'gradient_boosting', target: 'prb_utilization_pct',
  features: ['technology'], status: 'ready', is_champion: true, dataset_id: datasetId, dataset_slug: 'nawa-cells',
  row_count: 2688, test_size: 0.11, cross_validation: 3, trained_at: '2026-10-07T09:12:00Z', train_duration_ms: 28100,
  primary_metric: fixture.panel.metrics.primary, metrics: fixture.panel.metrics, signature: fixture.panel.signature,
  input_example: [], classes: [], params: { knobs: {} },
  spec: { time_column: 'ts', shape: 'panel', series_columns: ['cell_id'], horizon: 24, exog: { technology: 'static' }, backtest_folds: 3, interval_level: 0.8, fill: 'refuse', calendar: true, frequency: 'auto' },
};
const serving = {
  enabled: true, callable: true, serving_version: 1, serving_model_id: modelId, is_serving: true, max_rows: 100,
  fields: [], classes: [], positive_label: null, predict_count: 0, last_predict_at: null, published_skill: null,
  keys: [], endpoint: `/api/v1/ml-models/${modelId}/forecast`, key_header: 'X-Agentium-Model-Key', mode: 'forecast',
};

/** What the ml-ts worker would answer: a daily wave after the last date seen. */
function forecastAnswer(body: any) {
  const horizon = body.params?.horizon ?? 24;
  const level = body.params?.interval_level ?? 0.8;
  const levels: string[] = fixture.panel.signature.output.levels;
  const asked = (body.inputs ?? []).map((row: any) => row.series).filter(Boolean);
  const series = asked.length ? [...new Set(asked)] : levels;
  const last = new Date(fixture.panel.metrics.forecast.last_timestamp.replace(' ', 'T') + 'Z');
  const forecast = series.flatMap((name: any) =>
    Array.from({ length: horizon }, (_, index) => {
      const at = new Date(last.getTime() + (index + 1) * 3_600_000);
      const pred = 45 + 20 * Math.sin(((at.getUTCHours() - 6) / 24) * 2 * Math.PI);
      return { series: name, timestamp: at.toISOString().replace('T', ' ').slice(0, 19), pred, lower_bound: pred - 6, upper_bound: pred + 6 };
    }),
  );
  const first = forecast.filter((row: any) => row.series === series[0]);
  const top = first.reduce((best: any, row: any) => (row.pred > best.pred ? row : best), first[0]);
  const explanation = body.params?.explain
    ? {
        series: series[0],
        method: 'shap',
        steps: first.map((row: any, index: number) => ({ step: index + 1, timestamp: row.timestamp, pred: row.pred, base: 40, groups: { lags: row.pred - 42, calendar: 2 } })),
        peak: {
          step: first.indexOf(top) + 1, timestamp: top.timestamp, pred: top.pred, base: 40, groups: { lags: top.pred - 42, calendar: 2 },
          features: [
            { feature: 'lag_168', group: 'lags', contribution: top.pred - 45, value: top.pred },
            { feature: 'lag_24', group: 'lags', contribution: 3, value: top.pred - 2 },
            { feature: 'hour_sin', group: 'calendar', contribution: 2, value: 0.5 },
          ],
        },
      }
    : null;
  return { served: { model_id: modelId, version: 1, is_champion: true }, horizon, interval_level: level, frequency: 'h', series, forecast, explanation, rows: forecast.length, duration_ms: 84, load_ms: 0, cached: true, prediction_id: 'p-1' };
}

async function setup(page: Page, options: { theme: string; locale: string }) {
  const plans: any[] = [];
  const trains: any[] = [];
  const forecasts: any[] = [];
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', (route) =>
    ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort(),
  );
  await page.addInitScript(({ theme, locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer forecast-qa');
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
    if (path === '/ml-models/catalog') return json(route, { catalog: fixture.catalog });
    if (path === '/ml-models' && request.method() === 'GET') return json(route, { models: [model], catalog: fixture.catalog });
    if (path === '/ml-models' && request.method() === 'POST') {
      trains.push(request.postDataJSON());
      return json(route, { model: { ...model, id: 'fc-cells-2', version: 2, status: 'pending', metrics: {} } });
    }
    if (path === '/ml-models/plan') {
      const body = request.postDataJSON();
      plans.push(body);
      const base = { dataset, columns, catalog: fixture.catalog, plan: null, refusal: null };
      if (!body.target) return json(route, base);
      if (body.task !== 'forecasting') {
        return json(route, { ...base, plan: { task: 'regression', target: body.target, features: ['active_users'], algo: 'gradient_boosting', estimator: 'sklearn.ensemble.HistGradientBoostingRegressor', knobs: {}, test_size: 0.25, cross_validation: 0, name: 'x', warnings: [], rows: 2688 } });
      }
      const spec = body.spec ?? {};
      if (spec.shape !== 'panel') {
        // Four cells share every date: the server says it is a panel.
        return json(route, { ...base, refusal: { code: 'ML_TS_DUPLICATE_TIMESTAMPS', message: 'dates repeat', field: 'series_columns' } });
      }
      return json(route, { ...base, plan: { task: 'forecasting', family: 'forecasting', spec, target: body.target, features: Object.keys(spec.exog ?? {}), algo: body.algo ?? 'gradient_boosting', estimator: 'sklearn.ensemble.HistGradientBoostingRegressor', knobs: {}, test_size: 0.11, cross_validation: 3, name: 'Cellules Nawa · prb_utilization_pct +48', warnings: [], rows: 2688 } });
    }
    if (path === `/ml-models/${modelId}`) {
      return json(route, { model, dataset, provenance: null, versions: [model], challenger_id: null, catalog: fixture.catalog, serving });
    }
    if (path === `/ml-models/${modelId}/monitoring`) return json(route, { monitoring: null });
    if (path === `/ml-models/${modelId}/forecast`) {
      const body = request.postDataJSON();
      forecasts.push(body);
      return json(route, forecastAnswer(body));
    }
    if (path === '/datasets') return json(route, { datasets: [dataset], feature: { enabled: true, upload_max_bytes: 1 << 26 } });
    if (path === `/datasets/${datasetId}/preview`) return json(route, { dataset_id: datasetId, schema, rows: [{ cell_id: 'CAS-400-L04', technology: '4G', ts: '2026-08-01T00:00:00', prb_utilization_pct: 41.2, active_users: 120 }], offset: 0, limit: 50, total: 2688 });
    return json(route, {});
  });
  return { plans, trains, forecasts };
}

test.describe('Models · forecasting — isolated end-user QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(
      process.env['E2E_CHROME_V2_MOCKED'] !== '1' ||
        !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname),
      'Local mocked QA only.',
    );
  });

  for (const [theme, locale, width] of [['dark', 'fr', 1440], ['light', 'en', 1440], ['light', 'fr', 390]] as const) {
    test(`${theme}/${locale}/${width}: the card reads a backtest, the studio asks a panel forecast`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      const api = await setup(page, { theme, locale });

      // ── The card ──────────────────────────────────────────────────────────
      await page.goto(`/models/${modelId}`);
      const evidence = page.getByTestId('forecast-evidence');
      await expect(evidence).toBeVisible();
      await expect(evidence.locator('canvas')).toBeVisible();
      const tuningEvidence = page.getByTestId('tuning-temporal-validation');
      await expect(tuningEvidence).toContainText(locale === 'fr' ? 'plis temporels croissants' : 'expanding temporal folds');
      await expect(tuningEvidence).toContainText('2026-08-22');
      await expect(tuningEvidence).toContainText(locale === 'fr' ? 'MAE du naïf saisonnier' : 'Seasonal naive MAE');
      // Three of the four cells are plotted, one at a time.
      const pick = evidence.locator('select');
      await expect(pick.locator('option')).toHaveCount(3);
      await pick.selectOption({ index: 1 });
      await expect(evidence).toContainText(locale === 'fr' ? 'répéter la dernière saison' : 'repeating the last season');
      await expect(evidence).toContainText(locale === 'fr' ? 'Couverture' : 'Coverage');
      await expect(page.getByText(locale === 'fr' ? 'Erreur par série' : 'Error per series')).toBeVisible();
      // What it leans on, from the real fit: the series' own past, by far.
      const explained = page.getByTestId('forecast-explanation');
      await expect(explained).toContainText(locale === 'fr' ? 'Passé récent de la série' : 'The series’ recent past');
      await expect(explained).toContainText(locale === 'fr' ? 't−168 (7 j)' : 't−168 (7 d)');
      await expect(page.getByTestId('forecast-excursions').locator('li')).toHaveCount(5);
      await explained.scrollIntoViewIfNeeded();
      await explained.screenshot({ path: info.outputPath(`explain-${theme}-${locale}-${width}.png`) });
      await page.getByTestId('forecast-excursions').screenshot({ path: info.outputPath(`excursions-${theme}-${locale}-${width}.png`) });
      // The series' anatomy and the regressor's one-step diagnostic (skore).
      const anatomy = page.getByTestId('forecast-analysis');
      await expect(anatomy).toContainText(locale === 'fr' ? 'Saisonnalité forte' : 'Strong seasonality');
      await expect(anatomy).toContainText(locale === 'fr' ? 'Revient à son niveau' : 'Returns to its level');
      await anatomy.scrollIntoViewIfNeeded();
      await anatomy.screenshot({ path: info.outputPath(`anatomy-${theme}-${locale}-${width}.png`) });
      const diagnostic = page.getByTestId('forecast-diagnostic');
      await expect(diagnostic).toContainText('skore');
      await expect(diagnostic.locator('canvas')).toBeVisible();
      await diagnostic.screenshot({ path: info.outputPath(`diagnostic-${theme}-${locale}-${width}.png`) });
      await page.screenshot({ path: info.outputPath(`card-${theme}-${locale}-${width}.png`), fullPage: true });

      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(1);

      // ── Asking it now ─────────────────────────────────────────────────────
      await page.getByRole('tab', { name: locale === 'fr' ? /Prédire/i : /Predict/i }).click();
      const play = page.getByTestId('forecast-playground');
      await expect(play).toBeVisible();
      await expect(play.getByTestId('forecast-horizon')).toHaveValue('24');
      await play.getByTestId('forecast-horizon').fill('12');
      await play.getByTestId('forecast-series').selectOption({ index: 2 });
      await play.getByTestId('forecast-run').click();
      await expect(play.getByTestId('forecast-peak')).toBeVisible();
      await expect(play.locator('canvas')).toBeVisible();
      expect(api.forecasts.at(-1)).toMatchObject({ params: { horizon: 12, interval_level: 0.8 } });
      expect(api.forecasts.at(-1).inputs).toHaveLength(1);
      expect(api.forecasts.at(-1).params.explain).toBe(true);
      const why = play.getByTestId('forecast-why');
      await expect(why).toBeVisible();
      await expect(why).toContainText(locale === 'fr' ? 'Partant d’une base de 40' : 'From a base of 40');
      await expect(why).toContainText(locale === 'fr' ? 't−168 (7 j)' : 't−168 (7 d)');
      await why.scrollIntoViewIfNeeded();
      await why.screenshot({ path: info.outputPath(`why-${theme}-${locale}-${width}.png`) });
      // The cURL is this exact call.
      await expect(page.locator('pre.ck-code')).toContainText('/forecast');
      await expect(page.locator('pre.ck-code')).toContainText('"horizon":12');
      await page.screenshot({ path: info.outputPath(`play-${theme}-${locale}-${width}.png`), fullPage: true });

      // ── The studio ────────────────────────────────────────────────────────
      await page.goto('/models');
      await page.getByRole('button', { name: locale === 'fr' ? /Entraîner/ : /Train/ }).first().click();
      await page.getByTestId('train-target').locator('[data-testid="column-select"][data-name="prb_utilization_pct"]').click();
      const studio = page.getByRole('dialog');
      await studio.getByRole('button', { name: locale === 'fr' ? 'Prévision' : 'Forecasting', exact: true }).click();
      const forecast = page.getByTestId('train-forecast');
      await expect(forecast.locator('select')).toHaveValue('ts');
      // One series assumed, four cells found: the refusal sits on the spec.
      await expect(page.getByTestId('train-forecast-refusal')).toBeVisible();
      await studio.getByRole('button', { name: locale === 'fr' ? 'Panel de séries' : 'Panel of series' }).click();
      await studio.getByRole('button', { name: 'cell_id', exact: true }).click();
      await studio.getByRole('combobox', { name: 'technology' }).selectOption('static');
      await page.locator('#train-horizon').fill('48');
      // Committed when the field is left: one plan per decision, not per keystroke.
      await page.locator('#train-horizon').press('Tab');
      await expect(page.getByTestId('train-forecast-refusal')).toHaveCount(0);
      await page.locator('#forecast-tuning-mode').selectOption('budget');
      await expect(page.locator('#forecast-tuning_budget_s')).toHaveValue('60');
      await expect(page.locator('#forecast-tuning_budget_s')).toHaveAttribute('max','60');
      await page.locator('#forecast-tuning_trials').fill('8');
      await page.locator('#forecast-tuning_trials').press('Tab');
      await page.locator('#forecast-tuning_folds').fill('2');
      await page.locator('#forecast-tuning_folds').press('Tab');
      await page.locator('#forecast-tuning_budget_s').fill('40');
      await page.locator('#forecast-tuning_budget_s').press('Tab');
      await page.locator('#train-fill').selectOption('interpolate');
      await expect(page.getByTestId('forecast-tuning-refusal')).toContainText(locale === 'fr' ? 'lire le futur' : 'read future values');
      await expect(page.locator('.ck-submit')).toBeDisabled();
      await page.locator('#train-fill').selectOption('refuse');
      await expect(page.locator('.ck-submit')).toBeEnabled();
      await page.screenshot({ path: info.outputPath(`studio-${theme}-${locale}-${width}.png`), fullPage: true });

      const lastPlan = api.plans.at(-1);
      expect(lastPlan.task).toBe('forecasting');
      expect(lastPlan.spec).toMatchObject({ time_column: 'ts', shape: 'panel', series_columns: ['cell_id'], horizon: 48, exog: { technology: 'static' } });
      expect(lastPlan.spec.strategy).toBeUndefined();

      await page.locator('.ck-submit').click();
      await expect.poll(() => api.trains.length).toBe(1);
      expect(api.trains[0].spec).toMatchObject({ shape: 'panel', horizon: 48, tuning:'budget', tuning_trials:8, tuning_folds:2, tuning_budget_s:40 });
      // A forecast is judged by its backtest: no random split is sent.
      expect(api.trains[0].test_size).toBeUndefined();
    });
  }
});


test.describe('Models · zero-shot forecast — mocked QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost','127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const locale of ['fr','en']) test(`zero-shot ${locale}: only supported fields reach training`, async ({page}) => {
    const api = await setup(page,{theme:'dark',locale});
    await page.goto('/models');
    await page.getByRole('button',{name:locale==='fr'?/Entraîner/:/Train/}).first().click();
    const studio = page.getByRole('dialog');
    await studio.getByTestId('train-target').locator('[data-testid="column-select"][data-name="prb_utilization_pct"]').click();
    await studio.getByRole('button',{name:locale==='fr'?'Prévision':'Forecasting',exact:true}).click();
    await studio.getByRole('button',{name:locale==='fr'?'Panel de séries':'Panel of series',exact:true}).click();
    await studio.getByRole('button',{name:'cell_id',exact:true}).click();
    await studio.getByRole('combobox',{name:'technology',exact:true}).selectOption('static');
    await studio.getByRole('button',{name:locale==='fr'?/Prévision zéro-shot/:/Zero-shot forecast/}).click();
    await expect(studio.locator('#train-horizon')).toHaveAttribute('max','64');
    await expect(studio.locator('#train-lags')).toHaveCount(0);
    await expect(studio.getByRole('combobox',{name:'technology',exact:true})).toHaveCount(0);
    await expect(studio.locator('#forecast-tuning-mode')).toHaveCount(0);
    await expect(studio.locator('#train-fill option')).toHaveCount(2);
    await expect(studio.locator('#train-folds option')).toHaveCount(5);
    await expect(studio.locator('.ck-submit')).toBeEnabled();
    await studio.locator('.ck-submit').click();
    await expect.poll(() => api.trains.length).toBe(1);
    expect(api.trains[0].algo).toBe('chronos_zero_shot');
    expect(api.trains[0].spec).toEqual({time_column:'ts',shape:'panel',series_columns:['cell_id'],horizon:24,
      frequency:'auto',interval_level:.8,backtest_folds:3,fill:'refuse'});
  });
});
