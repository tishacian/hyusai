import {expect, test, type Page, type TestInfo} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {expectOk} from '../fixtures/api';

// Production reads only, with explicit credentials and no mocked responses.
// A workspace owner is never relabelled as a System owner or platform admin.
// This canary neither changes feature flags nor stores/reuses an auth session.
// It intentionally refuses qualification after an operator has closed R2/R4.
test.use({trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block', ignoreHTTPSErrors: false, timezoneId: 'UTC'});

interface Activity {
  id: string; native_id: string; kind: string; status: string; version: number;
  created_at: string; finished_at: string | null;
  measurements: {duration_ms?: number | null; cost_known?: boolean; cost_amount?: number | null;
    cost_basis?: string | null; currency?: string | null; infrastructure_cost_usd?: number | null};
}
interface Aggregate {total: number; by_status: Record<string, number>; by_kind: Record<string, number>}
interface ActivityPage {items: Activity[]; total: number; has_more: boolean; aggregates: Aggregate}
interface Summary extends Aggregate {
  durations: Record<string, {eligible_count: number; measured_count: number; p50_ms: number | null; p95_ms: number | null}>;
  costs: Array<{basis: string; currency: string; known_amount: number; known_count: number}>;
  cost_known_count: number; cost_unknown_count: number;
}
interface Series {from: string; until: string; totals: Summary; buckets: Array<Summary & {from: string; until: string}>;
  population: {metric: string; kind: string | null; time_basis: string}}
interface Features {enabled: boolean; activity_series_enabled: boolean; execution_view_enabled: boolean; scopes: string[]}
interface Evidence {
  revision: string; workspace: string; since: string; from: string; until: string;
  role_coverage: string; completed: string[]; blocked_business_writes: string[];
  suppressed_navigation_audits: number; [key: string]: unknown;
}

const root = '/api/v1/observability';
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'timed_out', 'lost', 'unknown']);
const measured = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

async function begin(page: Page): Promise<Evidence> {
  const username = process.env['E2E_USERNAME'];
  const password = process.env['E2E_PASSWORD'];
  const revision = process.env['E2E_EXPECTED_REVISION'] || '';
  const workspace = process.env['E2E_SHOWCASE_WORKSPACE_SLUG'] || 'agentium-showcase';
  expect(Boolean(username && password), 'Explicit live credentials are required').toBe(true);
  expect(revision, 'Pin the exact deployed revision').toMatch(/^[a-f0-9]{40}$/);
  const until = new Date().toISOString();
  const from = new Date(Date.parse(until) - 30 * 86400000).toISOString();
  const evidence: Evidence = {revision, workspace, since: '30d', from, until,
    role_coverage: 'workspace owner/admin only; System owner and platform admin require separate principals',
    completed: [], blocked_business_writes: [], suppressed_navigation_audits: 0};
  await page.route('**/*', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (['GET', 'HEAD', 'OPTIONS'].includes(request.method()) ||
      (request.method() === 'POST' && ['/api/v1/auth/login', '/api/v1/auth/refresh', '/api/v1/auth/validate'].includes(path))) {
      await route.continue();
    } else {
      if (request.method() === 'POST' && path === '/api/v1/audit') evidence.suppressed_navigation_audits++;
      else evidence.blocked_business_writes.push(`${request.method()} ${path}`);
      await route.abort('blockedbyclient');
    }
  });
  await page.goto('/auth/signin');
  const login = await page.evaluate(async ({username, password, workspace}) => {
    const response = await fetch('/api/v1/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: username, password, remember_me: false})});
    const body = await response.json().catch(() => ({}));
    if (!response.ok || typeof body.token !== 'string') return {ok: false, status: response.status};
    localStorage.setItem('agentium_token', `Bearer ${body.token}`);
    if (typeof body.refresh_token === 'string') localStorage.setItem('agentium_refresh_token', body.refresh_token);
    localStorage.setItem('agentium_workspace_slug', workspace);
    localStorage.setItem('agentium_locale', 'fr');
    return {ok: true, status: response.status};
  }, {username: username!, password: password!, workspace});
  expect(login.ok, `Explicit authentication succeeds (HTTP ${login.status}); no default fallback`).toBe(true);
  const profile = await expectOk<{id: string; role: string; workspaces: Array<{id: string; slug: string; role: string}>}>(page, '/api/v1/auth/me');
  const membership = profile.workspaces.find(item => item.slug === workspace);
  expect(Boolean(membership), 'The current principal has actual Showcase membership').toBe(true);
  expect(['owner', 'admin'].includes(membership!.role), 'This canary qualifies a workspace owner/admin, not a scope switch').toBe(true);
  evidence.principal = {id: profile.id, platform_role: profile.role, workspace_role: membership!.role, workspace_id: membership!.id};
  for (const path of ['/api/v1/build-info', '/build-info.json']) {
    const build = await expectOk<{revision: string; revision_verified: boolean}>(page, path);
    expect(build.revision, `${path}: exact deployed revision`).toBe(revision);
    expect(build.revision_verified).toBe(true);
  }
  const features = await expectOk<Features>(page, `${root}/activities/features`);
  expect(features.enabled && features.activity_series_enabled && features.execution_view_enabled, 'Both options are really open for this workspace').toBe(true);
  evidence.features = features;
  evidence.completed.push('authenticated-real-workspace-role-exact-revision-and-open-options');
  return evidence;
}

async function saveEvidence(info: TestInfo, evidence: Evidence, basename: string): Promise<void> {
  const path = info.outputPath(`${basename}.json`);
  // Metadata and aggregate counts only: no credentials, tokens or document text.
  await writeFile(path, JSON.stringify({...evidence, accepted: info.errors.length === 0}, null, 2));
  await info.attach(basename, {contentType: 'application/json', path});
}

const pageScope = (evidence: Evidence) => new URLSearchParams({since: evidence.since, as_of: evidence.until});
const seriesScope = (evidence: Evidence) => new URLSearchParams({from: evidence.from, until: evidence.until, bucket: 'day', metric: 'activity', time_basis: 'created'});

test('Operations live: exhaustive tiles open the corresponding Activities filter', async ({page}, info) => {
  test.setTimeout(180_000);
  const evidence = await begin(page);
  const observations: Array<Record<string, unknown>> = [];
  evidence.tiles = observations;
  try {
    await page.setViewportSize({width: 1440, height: 1000});
    const scope = pageScope(evidence);
    const params = seriesScope(evidence); params.set('kind', 'run');
    const series = await expectOk<Series>(page, `${root}/activities/series?${params}`);
    expect(series.totals.total, 'Real Runs must exist to qualify tile drilldowns').toBeGreaterThan(0);
    evidence.run_counts = series.totals;
    const cases = [
      {tile: 'runs', status: '', expected: series.totals.total},
      {tile: 'completed', status: 'succeeded', expected: series.totals.by_status['succeeded'] || 0},
      {tile: 'failed', status: 'failed', expected: series.totals.by_status['failed'] || 0},
      {tile: 'running', status: 'pending,running,waiting', expected: ['pending', 'running', 'waiting'].reduce((sum, status) => sum + (series.totals.by_status[status] || 0), 0)},
    ];
    for (const item of cases) {
      await page.goto(`/observability?${scope}`);
      const tiles = page.getByTestId('operations-tiles');
      await expect(tiles).toHaveAttribute('data-source', 'series');
      await expect(page.getByTestId('operations-tiles-coverage')).toContainText('Tuiles exhaustives sous vos droits');
      const tile = page.getByTestId(`operations-tile-${item.tile}`);
      const count = Number((await tile.locator('.text-2xl').innerText()).replace(/\s/g, ''));
      expect.soft(count, `${item.tile}: tile agrees with exhaustive Run series`).toBe(item.expected);
      const href = await tile.getAttribute('href');
      expect(href).toBeTruthy();
      await tiles.screenshot({path: info.outputPath(`tile-${item.tile}-origin.png`)});
      await tile.focus();
      const destinationSeries = page.waitForResponse(response => new URL(response.url()).pathname === `${root}/activities/series`);
      await tile.press('Enter');
      await expect(page.getByTestId('activity-monitor')).toBeVisible();
      await expect(page.getByTestId('activity-monitor').locator('.listing')).toBeVisible();
      const query = new URL(page.url()).searchParams;
      expect.soft(query.get('facet')).toBe('activities');
      expect.soft(query.get('kind')).toBe('run');
      expect.soft(query.get('since')).toBe('30d');
      expect.soft(query.get('as_of')).toBe(evidence.until);
      const observedStatus = query.get('status') || '';
      const displayedCount = Number((await page.getByTestId('activity-monitor').locator(':scope > .stats article strong').first().innerText()).replace(/\s/g, ''));
      observations.push({tile: item.tile, displayed_tile_count: count, displayed_list_count: displayedCount,
        expected_status: item.status, actual_status: observedStatus, href});
      // The running tile represents the union of pending/running/waiting. Opening
      // every Run is a failure even when the active count happens to be zero.
      expect.soft(observedStatus.split(',').filter(Boolean).sort(), `${item.tile}: corresponding status population`).toEqual(item.status.split(',').filter(Boolean).sort());
      expect.soft(displayedCount, `${item.tile}: destination has the same population as the tile`).toBe(item.expected);
      await expect(page.locator('select[name="status"]'), 'The selected filter is visible, including a union').toHaveValue(item.status);
      const chartResponse = await destinationSeries;
      expect(chartResponse.ok(), 'The actual chart request succeeds').toBe(true);
      const chartQuery = new URL(chartResponse.url()).searchParams;
      expect.soft(chartQuery.get('status') || '').toBe(item.status);
      expect.soft(chartQuery.get('kind')).toBe('run');
      expect.soft(chartQuery.get('from')).toBe(evidence.from);
      expect.soft(chartQuery.get('until')).toBe(evidence.until);
      const chart: Series = await chartResponse.json();
      expect.soft(chart.totals.total, 'The rendered chart uses the same authorized population').toBe(item.expected);
      await page.getByTestId('activity-monitor').locator('.filters').screenshot({path: info.outputPath(`tile-${item.tile}-destination.png`)});
      await page.getByTestId('activity-monitor').locator(':scope > .stats').screenshot({path: info.outputPath(`tile-${item.tile}-destination-count.png`)});
      const reloadedSeries = page.waitForResponse(response => new URL(response.url()).pathname === `${root}/activities/series`);
      await page.reload();
      await expect(page.getByTestId('activity-monitor').locator('.listing')).toBeVisible();
      expect.soft(new URL(page.url()).searchParams.get('status') || '').toBe(observedStatus);
      await expect(page.locator('select[name="status"]')).toHaveValue(item.status);
      const reloadedResponse = await reloadedSeries;
      expect(reloadedResponse.ok()).toBe(true);
      expect.soft(new URL(reloadedResponse.url()).searchParams.get('status') || '').toBe(item.status);
      expect.soft(((await reloadedResponse.json()) as Series).totals.total).toBe(item.expected);
      evidence.completed.push(`${item.tile}-keyboard-navigation-and-reload-observed`);
    }
    expect(evidence.blocked_business_writes).toEqual([]);
  } finally {
    await saveEvidence(info, evidence, 'operations-live-tile-evidence');
  }
});

async function allActivities(page: Page, evidence: Evidence): Promise<Activity[]> {
  const items: Activity[] = [];
  let initial: Aggregate | undefined;
  // All creation dates are required: an expense can finish in this window even
  // when its activity was created earlier. Pagination is never silently cut off.
  for (let offset = 0; offset < 10000; offset += 100) {
    const params = new URLSearchParams({until: evidence.until, limit: '100', offset: String(offset)});
    const result = await expectOk<ActivityPage>(page, `${root}/activities?${params}`);
    if (!initial) initial = result.aggregates;
    expect(result.aggregates, 'Acceptance requires a stable population during pagination; a changing snapshot is inconclusive').toEqual(initial);
    items.push(...result.items);
    if (!result.has_more) {
      expect(new Set(items.map(item => item.id)).size, 'Every authorized activity appears exactly once').toBe(result.total);
      expect(items.length).toBe(result.total);
      evidence.exhaustive_list = {count: items.length, pages: offset / 100 + 1, aggregates: initial};
      return items;
    }
    expect(result.items.length, 'A paginated response must advance').toBeGreaterThan(0);
  }
  throw new Error('Acceptance incomplete: the real corpus exceeds 10000 records; no truncated comparison is accepted.');
}

function counts(items: Activity[]): Aggregate {
  const result: Aggregate = {total: items.length, by_status: {}, by_kind: {}};
  for (const item of items) {
    result.by_status[item.status] = (result.by_status[item.status] || 0) + 1;
    result.by_kind[item.kind] = (result.by_kind[item.kind] || 0) + 1;
  }
  return result;
}

function compareActivity(series: Series, items: Activity[], context: string): void {
  const aggregate = counts(items);
  expect.soft(series.totals.total, `${context}: exhaustive total`).toBe(aggregate.total);
  expect.soft(series.totals.by_status, `${context}: exhaustive status counts`).toEqual(aggregate.by_status);
  expect.soft(series.totals.by_kind, `${context}: exhaustive kind counts`).toEqual(aggregate.by_kind);
  expect.soft(series.buckets.reduce((sum, cell) => sum + cell.total, 0), `${context}: buckets cover exact population`).toBe(aggregate.total);
  const durationKinds = [...new Set(items.filter(item => terminal.has(item.status)).map(item => item.kind))];
  expect.soft(Object.keys(series.totals.durations).sort(), `${context}: only eligible duration populations`).toEqual(durationKinds.sort());
  for (const kind of durationKinds) {
    const eligible = items.filter(item => item.kind === kind && terminal.has(item.status));
    const values = eligible.map(item => item.measurements.duration_ms).filter(measured).sort((a, b) => a - b);
    expect.soft(series.totals.durations[kind], `${context}: exact measured nearest-rank durations for ${kind}`).toEqual({
      eligible_count: eligible.length, measured_count: values.length,
      p50_ms: values.length ? values[Math.ceil(values.length * .5) - 1] : null,
      p95_ms: values.length ? values[Math.ceil(values.length * .95) - 1] : null,
    });
  }
}

async function visibleChart(page: Page, name: string, info: TestInfo, filename: string): Promise<void> {
  const series = page.getByTestId('activity-series');
  // Angular defers chart creation until its placeholder enters the viewport.
  await series.scrollIntoViewIfNeeded();
  const canvas = series.getByRole('img', {name, exact: true});
  await expect(canvas).toBeVisible({timeout: 30000});
  await canvas.scrollIntoViewIfNeeded();
  expect(await canvas.evaluate(element => element instanceof HTMLCanvasElement && element.width > 0 && element.height > 0), 'Chart really has rendering dimensions').toBe(true);
  await canvas.screenshot({path: info.outputPath(filename)});
}

test('Activities live: real series equal the exhaustive list and render volume duration and expenses', async ({page}, info) => {
  test.setTimeout(360_000);
  const evidence = await begin(page);
  const comparisons: Array<Record<string, unknown>> = [];
  evidence.comparisons = comparisons;
  try {
    const all = await allActivities(page, evidence);
    const start = Date.parse(evidence.from), end = Date.parse(evidence.until);
    const created = all.filter(item => Date.parse(item.created_at) >= start && Date.parse(item.created_at) < end);
    expect(created.length, 'Real activities in this window are required').toBeGreaterThan(0);
    const params = seriesScope(evidence);
    const activity = await expectOk<Series>(page, `${root}/activities/series?${params}`);
    compareActivity(activity, created, 'all activities by creation');
    comparisons.push({population: 'activity/created', list: counts(created), series: activity.totals});
    evidence.completed.push('workspace-real-principal-exhaustive-list-vs-created-series-and-durations');

    const costTotals: Record<string, Summary> = {};
    for (const kind of ['skill_invocation', 'compute_run']) {
      const ended = all.filter(item => item.kind === kind && terminal.has(item.status) && item.finished_at
        && Date.parse(item.finished_at) >= start && Date.parse(item.finished_at) < end);
      const costs = new URLSearchParams({from: evidence.from, until: evidence.until, bucket: 'day', metric: 'cost', time_basis: 'finished', kind});
      const series = await expectOk<Series>(page, `${root}/activities/series?${costs}`);
      costTotals[kind] = series.totals;
      compareActivity(series, ended, `${kind} finished expense population`);
      expect.soft(series.totals.cost_known_count + series.totals.cost_unknown_count, `${kind}: costs have explicit coverage`).toBe(ended.length);
      expect.soft(series.totals.costs.reduce((sum, cost) => sum + cost.known_count, 0), `${kind}: no parent/child double counting`).toBe(series.totals.cost_known_count);
      for (const cost of series.totals.costs) {
        expect.soft(Number.isFinite(cost.known_amount) && cost.known_amount >= 0, 'Known expenses remain nonnegative measured amounts').toBe(true);
        expect.soft(Boolean(cost.basis && cost.currency), 'Never combine unlabelled bases or currencies').toBe(true);
      }
      comparisons.push({population: `${kind}/cost/finished`, list: counts(ended), series: series.totals,
        limitation: 'Compares authorized finished population and coverage; not a provider billing reconciliation'});
    }
    evidence.completed.push('finished-expense-populations-match-list-with-explicit-known-unknown-costs');
    expect(costTotals['skill_invocation'].total, 'At least one real invocation expense population is needed for the third chart').toBeGreaterThan(0);

    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: 1000});
      await page.goto(`/observability?facet=activities&${pageScope(evidence)}`);
      await expect(page.getByTestId('activity-monitor')).toBeVisible();
      await visibleChart(page, 'Activités par statut', info, `activities-volume-${width}.png`);
      await visibleChart(page, 'Durées p50 et p95 par type de travail', info, `activities-durations-${width}.png`);
      const series = page.getByTestId('activity-series');
      const expenseButton = series.getByRole('button', {name: 'Dépenses des invocations', exact: true});
      await expenseButton.focus(); await expenseButton.press('Enter');
      await visibleChart(page, 'Coûts par base et devise', info, `activities-expenses-${width}.png`);
      await expect(series).toContainText('Coûts inconnus');
      const blankCosts = costTotals['skill_invocation'].cost_known_count === 0;
      evidence[`expense_amount_coverage_${width}`] = blankCosts ? 'unknown amounts explicitly disclosed; no billed amount qualified' : 'known amounts present with explicit coverage';
      await series.locator('.controls').screenshot({path: info.outputPath(`activities-expense-controls-${width}.png`)});
      expect.soft(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}: no page-wide horizontal overflow`).toBe(true);
      evidence.completed.push(`real-volume-duration-expense-charts-${width}-keyboard`);
    }
    expect(evidence.blocked_business_writes).toEqual([]);
  } finally {
    await saveEvidence(info, evidence, 'activities-live-series-evidence');
  }
});
