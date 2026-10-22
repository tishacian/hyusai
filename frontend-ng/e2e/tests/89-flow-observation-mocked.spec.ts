import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

// This suite is deliberately restricted to disposable local API fixtures. It never
// executes a Skill, previews a transformation, trains a model or writes a Flow.
test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const systemId = 'flow-observation-qa';
const hash = 'a'.repeat(64);
const workspace = { id: 'flow-observation-qa', slug: 'flow-observation-qa', name: 'Flow results QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const ids = { latest: 'latest-forecast-run', old: 'older-forecast-run', different: 'different-version-run', unknown: 'unknown-version-run', held: 'held-result-run', forbidden: 'forbidden-result-run' };
const forecastRows = [
  { ds: '2026-10-20', actual: 9, forecast: null, lower: null, upper: null },
  { ds: '2026-10-21', actual: 12, forecast: 11, lower: 8, upper: 14 },
  { ds: '2026-10-22', actual: null, forecast: 17, lower: 13, upper: 23 },
  { ds: '2026-10-23', actual: null, forecast: 19, lower: 15, upper: 25 },
];
function call(id: string, node: string, output: unknown, minute = 1, extra: any = {}) {
  return { id, skill_slug: node === 'forecast' ? 'ml_forecast_v1' : 'sql_transform_v1', status: 'completed',
    started_at: `2026-10-22T09:${String(minute).padStart(2, '0')}:00Z`, completed_at: `2026-10-22T09:${String(minute).padStart(2, '0')}:02Z`, latency_ms: 2000,
    input_ref: { scope: 'retained input only' }, output_ref: output, trace: { node_id: node, passage_id: 'passage-1', membrane_attempt_index: minute }, ...extra };
}
function recordedRun(id: string, day: number, calls: any[], extra: any = {}) {
  return { id, system_id: systemId, status: 'completed', started_at: `2026-10-${day}T09:00:00Z`, completed_at: `2026-10-${day}T09:02:00Z`, duration_ms: 120000,
    flow_version_id: 'flow-v10', flow_sha256: hash, execution_surface: 'published_manual', input_ref: { execution: { ingress_id: 'source.capacity' } }, skill_invocations: calls.map(invocation => ({ ...invocation, started_at: invocation.started_at?.replace('2026-10-22', `2026-10-${day}`), completed_at: invocation.completed_at?.replace('2026-10-22', `2026-10-${day}`) })), ...extra };
}
async function fixture(page: Page, locale: 'fr' | 'en' = 'fr') {
  const graph: any = { version: 3, runtime_mode: 'dag_overlay', nodes: [
    { id: 'source', kind: 'source', type: 'source', label: 'Incoming claims', position: { x: 20, y: 40 }, config: {}, outputs: [{ name: 'out', schema: 'object' }] },
    { id: 'prep', kind: 'task', type: 'skill', label: 'Prepared claims', position: { x: 330, y: 40 }, config: { skill_slug: 'sql_transform_v1', params: {} }, inputs: [{ name: 'in', schema: 'object' }], outputs: [{ name: 'out', schema: 'object' }] },
    { id: 'forecast', kind: 'task', type: 'skill', label: 'Capacity forecast', position: { x: 650, y: 40 }, config: { skill_slug: 'ml_forecast_v1', params: {} }, inputs: [{ name: 'in', schema: 'object' }], outputs: [{ name: 'out', schema: 'object' }] },
    { id: 'agent', kind: 'agent_loop', type: 'agent_loop', label: 'Investigate the claim', position: { x: 330, y: 290 }, config: { goal: { objective: 'Propose a resolution', status: 'active' }, skill_allowlist: ['read_order'], budget: { max_turns: 4 } }, inputs: [{ name: 'in', schema: 'object' }], outputs: [{ name: 'out', schema: 'object' }] },
    { id: 'user-draft', kind: 'task', type: 'skill', label: 'Unfinished user preparation', position: { x: 650, y: 290 }, config: { skill_slug: 'sql_transform_v1', params: { sql: '-- keep my unfinished draft', untouched: true } }, inputs: [], outputs: [] },
  ], edges: [
    { from: 'source', from_port: 'out', to: 'prep', to_port: 'in', kind: 'data' },
    { from: 'prep', from_port: 'out', to: 'forecast', to_port: 'in', kind: 'data' },
    { from: 'prep', from_port: 'out', to: 'agent', to_port: 'in', kind: 'data' },
  ] };
  const original = structuredClone(graph);
  const decision = call('agent-decision', 'agent', { next_skill: 'read_order', rationale: 'Read the order facts before proposing a refund.' }, 3, {
    skill_slug: 'decide_next_v1', input_ref: { visible_skills: [{ slug: 'read_order', purpose: 'Read the order facts' }] },
    trace: { node_id: 'agent', passage_id: 'passage-agent', membrane_attempt_kind: 'agent_loop_decide', membrane_attempt_index: 1,
      agent_loop_decision: { effective: { next_skill: 'read_order', exit: null }, normalization_reasons: [] },
      model_execution: { provider: 'openai', model: 'gpt-5-mini', returned_model: 'gpt-5-mini', model_source: 'node' } },
  });
  const runs: Record<string, any> = {
    [ids.latest]: recordedRun(ids.latest, 22, [
      call('forecast-first-attempt', 'forecast', { summary: 'Earlier retained attempt' }, 1, { status: 'failed' }),
      call('forecast-final-attempt', 'forecast', { rows: [
        ...forecastRows.map(row => ({ ...row, series: 'Claims' })),
        ...forecastRows.map(row => ({ ...row, series: 'Returns', actual: row.actual === null ? null : row.actual + 3, forecast: row.forecast === null ? null : row.forecast + 3, lower: row.lower === null ? null : row.lower + 3, upper: row.upper === null ? null : row.upper + 3 })),
      ], frequency: 'D' }, 2),
      call('prepared-dataset-attempt', 'prep', { dataset_id: 'prepared-v7', dataset_version: 7, rows_out: 2 }),
      decision,
      call('agent-action', 'agent', { answer: 'Order paid; delivery late.' }, 4, { skill_slug: 'read_order', trace: { node_id: 'agent', passage_id: 'passage-agent', membrane_attempt_kind: 'agent_loop_act', membrane_attempt_index: 1 } }),
      { ...structuredClone(decision), id: 'other-agent-decision', trace: { ...decision.trace, node_id: 'other-agent' }, output_ref: { next_skill: 'read_order', rationale: 'MUST_NOT_BORROW_ADJACENT_AGENT' } },
    ]),
    'newer-node-preview': recordedRun('newer-node-preview', 23, [call('preview-forecast', 'forecast', { summary: 'PREVIEW_IS_NOT_THE_LATEST_BUSINESS_RUN' })], { execution_surface: 'node_preview' }),
    [ids.old]: recordedRun(ids.old, 21, [call('older-forecast-attempt', 'forecast', { summary: 'OLDER_FORECAST_EVIDENCE' })]),
    [ids.different]: recordedRun(ids.different, 20, [call('different-forecast-attempt', 'forecast', { summary: 'DIFFERENT_VERSION_EVIDENCE' })], { flow_sha256: 'b'.repeat(64), flow_version_id: 'flow-v9' }),
    [ids.unknown]: recordedRun(ids.unknown, 19, [call('unknown-forecast-attempt', 'forecast', { summary: 'UNKNOWN_VERSION_EVIDENCE' })], { flow_sha256: null, flow_version_id: null }),
    [ids.held]: recordedRun(ids.held, 18, [call('held-forecast-attempt', 'forecast', { summary: 'HELD_PAYLOAD_MUST_NOT_RENDER', dataset_id: 'held-secret' })], { result_held: true }),
    [ids.forbidden]: recordedRun(ids.forbidden, 17, [call('recovered-forecast-attempt', 'forecast', { summary: 'RECOVERED_AUTHORIZED_EVIDENCE' })]),
  };
  let denyRun = true;
  let denyDataset = false;
  let slowRun: string | null = null;
  let releaseSlow: (() => void) | undefined;
  let slowSettled = false;
  const requests: Array<{ method: string; path: string; query: string; body: any }> = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && /^(ERROR|Error:|TypeError:)|NG0\d+/.test(message.text())) errors.push(message.text());
  });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-flow-observation-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light');
  }, { locale, slug: workspace.slug });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa-human', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'qa-human', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    requests.push({ method: request.method(), path, query: url.search, body: request.postData() ? request.postDataJSON() : null });
    const system = { id: systemId, workspace_id: workspace.id, name: 'Claims assistant', status: 'active', flow_definition: graph, flow_sha256: hash };
    if (path === '/systems') return json(route, { systems: [system] });
    if (path === `/systems/${systemId}`) return json(route, system);
    if (path === `/systems/${systemId}/flow-state`) return json(route, { system_id: systemId, status: 'active', draft: { revision: 42, base_published_version_id: 'flow-v10', flow_sha256: hash, flow_definition: graph }, published: { version_id: 'flow-v10', version_number: 10, flow_sha256: hash, flow_definition: graph, execution_contract_ready: true } });
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_overlay', flow_sha256: hash });
    if (path === '/skills') return json(route, { skills: ['ml_forecast_v1', 'sql_transform_v1', 'read_order'].map(slug => ({ id: slug, slug, name: slug, version: '1', type: 'workflow', category: 'Data', runtime_status: 'bound', input_schema: { type: 'object', properties: {} }, output_schema: { type: 'object', properties: {} }, visibility: { visible: true, reason: 'visible', capabilities: [] } })) });
    if (path === '/models') return json(route, { models: [] });
    if (path === '/connectors') return json(route, { can_configure: true, connectors: [] });
    if (path === '/documents/collections') return json(route, { collections: [] });
    if (path === '/runs') return json(route, { runs: Object.values(runs).map(({ skill_invocations, ...run }) => run) });
    if (path.startsWith('/runs/') && runs[path.slice(6)]) {
      const id = path.slice(6);
      if (id === ids.forbidden && denyRun) return json(route, { detail: 'Not authorized for this retained Run.' }, 403);
      if (id === slowRun) { await new Promise<void>(resolve => { releaseSlow = resolve; }); }
      try { return await json(route, runs[id]); } finally { if (id === slowRun) slowSettled = true; }
    }
    if (path === '/datasets/prepared-v7') return json(route, denyDataset ? { detail: 'No dataset permission.' } : { dataset: { id: 'prepared-v7', version: 7, status: 'ready', name: 'Prepared claims v7', run_id: ids.latest, node_id: 'prep' } }, denyDataset ? 403 : 200);
    if (path === '/datasets/prepared-v7/preview') return json(route, { dataset_id: 'prepared-v7', offset: 0, limit: 50, total: 2, schema: [{ name: 'case_id', dtype: 'Utf8', kind: 'string' }, { name: 'priority', dtype: 'Float64', kind: 'float' }], rows: [{ case_id: 'CASE-001', priority: 0 }, { case_id: 'CASE-002', priority: 0.8 }] });
    return json(route, {});
  });
  return { requests, errors, graph, original, allowRun: () => { denyRun = false; }, denyDataset: (value: boolean) => { denyDataset = value; },
    delayRun: (id: string) => { slowRun = id; }, releaseRun: () => releaseSlow?.(), hasPendingRun: () => !!releaseSlow, hasSettledRun: () => slowSettled };
}
const panel = (page: Page) => page.getByTestId('flow-observation-panel');
const runSelect = (page: Page) => page.getByTestId('flow-observation-run-select');
const node = (page: Page, title: string) => page.locator('app-flow-node').filter({ hasText: title });
async function open(page: Page, title = 'Capacity forecast') {
  await page.goto(`/systems/${systemId}/flow?lens=build`);
  await node(page, title).getByTestId('flow-node-observe').click();
  await expect(panel(page)).toBeVisible();
  await expect(runSelect(page)).toHaveValue(ids.latest);
  await expect(page.locator('.fo-bar__context')).toHaveAttribute('data-match', 'same');
}
function expectReadOnly(api: Awaited<ReturnType<typeof fixture>>) {
  expect(api.requests.filter(request => request.method !== 'GET' && !request.path.endsWith('/validate-flow')
    && !(request.path === '/audit' && request.body?.event_type === 'navigation.resolved'))).toEqual([]);
  expect(api.requests.filter(request => /\/flow-draft$|\/publish$|\/node-runs$|\/executions$|\/execute$|\/rerun$|\/model-calls$|\/train$/.test(request.path))).toEqual([]);
  expect(api.graph).toEqual(api.original);
  expect(api.errors).toEqual([]);
}

test.describe('Flow observation — authorized read-only execution windows', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });

  test('FR dark: actual forecast, attempts, pin/drag/enlarge and original user draft survive reading', async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const api = await fixture(page);
    await page.goto(`/systems/${systemId}/flow?lens=build`);
    await page.getByRole('button', { name: /Modifier le brouillon/ }).click();
    await node(page, 'Capacity forecast').locator('.ck-flow-node__title').dblclick();
    await expect(panel(page)).toBeVisible();
    await expect(panel(page).getByTestId('flow-observation-attempt-select')).toHaveValue('forecast-final-attempt');
    await expect(panel(page).locator('ck-forecast-chart canvas')).toBeVisible();
    expect(await panel(page).locator('ck-forecast-chart canvas').evaluate(canvas => {
      const bounds = canvas.getBoundingClientRect(), container = canvas.closest('[data-testid=flow-observation-panel]')!.getBoundingClientRect();
      return bounds.left >= container.left && bounds.right <= container.right + 1;
    })).toBe(true);
    await expect(node(page, 'Capacity forecast').getByTestId('flow-node-observed-status')).toHaveAttribute('data-status', 'completed');
    await panel(page).locator('details').filter({ hasText: /Valeurs|Values/i }).locator('summary').click();
    const table = panel(page).locator('ck-data-table');
    await expect(table).toContainText('2026-10-23');
    for (const value of ['actual', 'forecast', 'lower', 'upper', '19', '15', '25']) await expect(table).toContainText(value);
    await panel(page).getByTestId('flow-observation-attempt-select').selectOption('forecast-first-attempt');
    await expect(panel(page)).toContainText('Earlier retained attempt');
    await expect(panel(page).locator('ck-forecast-chart')).toHaveCount(0);
    await panel(page).getByTestId('flow-observation-attempt-select').selectOption('forecast-final-attempt');
    await panel(page).getByRole('button', { name: 'Entrée', exact: true }).click();
    await expect(panel(page)).toContainText('retained input only');
    await expect(panel(page).locator('ck-forecast-chart')).toHaveCount(0);
    await panel(page).getByRole('button', { name: 'Sortie', exact: true }).click();
    await panel(page).locator('.flow-result__chart-head select').selectOption('Returns');
    await expect(panel(page).locator('ck-forecast-chart canvas')).toHaveAttribute('aria-label', 'Capacity forecast · Returns');
    await panel(page).getByTestId('flow-observation-pin-action').click();
    const pin = page.locator('.ck-flow-observation-node');
    await expect(pin).toHaveCount(1);
    await expect(pin).toContainText('Capacity forecast');
    await expect(pin).toContainText(ids.latest.slice(0, 8));
    await expect(pin.locator('.flow-result__chart-head select')).toHaveValue('Returns');
    await expect(pin.locator('ck-forecast-chart canvas')).toHaveAttribute('aria-label', 'Capacity forecast · Returns');
    const header = pin.locator('.fo-card__header');
    await header.hover();
    const before = await header.boundingBox();
    expect(before).not.toBeNull();
    await page.mouse.move(before!.x + 70, before!.y + 20);
    await page.mouse.down(); await page.mouse.move(before!.x + 20, before!.y + 110, { steps: 10 }); await page.mouse.up();
    await expect.poll(async () => (await header.boundingBox())?.y).not.toBe(before!.y);
    await header.click({ position: { x: 70, y: 20 } });
    await page.keyboard.press('Delete');
    await page.keyboard.press('Control+z');
    await page.keyboard.press('Control+s');
    await expect(page.locator('app-flow-node')).toHaveCount(5);
    expectReadOnly(api);
    expect((await new AxeBuilder({ page }).include('[data-testid=flow-observation-bar]').include('[data-testid=flow-observation-panel]').withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
    await panel(page).getByTestId('flow-observation-expand-action').click();
    const dialog = page.getByRole('dialog', { name: 'Capacity forecast' });
    await expect(dialog.locator('ck-forecast-chart canvas')).toBeVisible();
    await expect(dialog.locator('.flow-result__chart-head select')).toHaveValue('Returns');
    expect((await new AxeBuilder({ page }).include('[data-testid="flow-observation-modal"]').withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
    await dialog.screenshot({ path: info.outputPath('forecast-enlarged-fr-dark.png') });
    await page.keyboard.press('Escape'); await expect(dialog).toHaveCount(0);
    await runSelect(page).selectOption(ids.old);
    await expect(panel(page)).toContainText('OLDER_FORECAST_EVIDENCE');
    await expect(panel(page).locator('ck-forecast-chart')).toHaveCount(0);
    await expect(pin.locator('ck-forecast-chart canvas')).toBeVisible();
    await expect(pin).toContainText(ids.latest.slice(0, 8));
    await page.screenshot({ path: info.outputPath('flow-forecast-pinned-fr-dark.png') });
    await pin.getByRole('button', { name: /Retirer/ }).click(); await expect(pin).toHaveCount(0);
    await page.getByTestId('flow-observation-toggle').click();
    await expect(panel(page)).toHaveCount(0);
    await expect(node(page, 'Unfinished user preparation')).toBeVisible();
    expectReadOnly(api);
    await page.reload();
    await page.getByRole('button', { name: /Modifier le brouillon/ }).click();
    await expect(node(page, 'Unfinished user preparation')).toBeVisible();
    expectReadOnly(api);
  });

  test('EN light 390: table preview uses immutable dataset GET, readable modal and no page overflow', async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const api = await fixture(page, 'en');
    await open(page, 'Prepared claims');
    await expect(panel(page).locator('ck-data-table')).toContainText('CASE-001');
    await expect(panel(page).locator('ck-data-table')).toContainText('CASE-002');
    await expect(panel(page).locator('ck-data-table')).toContainText('0.8');
    expect(api.requests.filter(request => request.path.startsWith('/datasets/')).map(({ method, path, query }) => ({ method, path, query }))).toEqual([
      { method: 'GET', path: '/datasets/prepared-v7', query: '' },
      { method: 'GET', path: '/datasets/prepared-v7/preview', query: '?offset=0&limit=50' },
    ]);
    await panel(page).getByTestId('flow-observation-expand-action').click();
    const dialog = page.getByRole('dialog', { name: 'Prepared claims' });
    await expect(dialog.locator('ck-data-table')).toContainText('CASE-002');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(await dialog.evaluate(el => el.getBoundingClientRect().right <= innerWidth + 1 && el.getBoundingClientRect().left >= 0)).toBe(true);
    expect((await new AxeBuilder({ page }).include('[data-testid="flow-observation-modal"]').withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
    await page.screenshot({ path: info.outputPath('dataset-modal-en-light-390.png'), fullPage: true });
    await page.keyboard.press('Escape'); await expect(dialog).toHaveCount(0);
    expect((await new AxeBuilder({ page }).include('[data-testid=flow-observation-panel]').withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
    await page.screenshot({ path: info.outputPath('dataset-panel-en-light-390.png'), fullPage: true });
    expectReadOnly(api);
  });

  test('Run/version provenance, unknown and held evidence stay truthful', async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const api = await fixture(page);
    await open(page);
    await runSelect(page).selectOption(ids.different);
    await expect(page.locator('.fo-bar__context')).toHaveAttribute('data-match', 'different');
    await expect(panel(page)).toContainText('DIFFERENT_VERSION_EVIDENCE');
    await runSelect(page).selectOption(ids.unknown);
    await expect(page.locator('.fo-bar__context')).toHaveAttribute('data-match', 'unknown');
    await expect(panel(page)).toContainText('UNKNOWN_VERSION_EVIDENCE');
    await runSelect(page).selectOption(ids.held);
    await expect(panel(page).getByTestId('flow-result-viewer')).toHaveCount(0);
    await expect(panel(page).getByTestId('flow-observation-pin-action')).toHaveCount(0);
    await expect(page.getByText('HELD_PAYLOAD_MUST_NOT_RENDER')).toHaveCount(0);
    await expect(panel(page)).toContainText(/retenu|retenue|masqu|bloqu|rétention/i);
    expect(api.requests.some(request => request.path.includes('held-secret'))).toBe(false);
    await page.screenshot({ path: info.outputPath('held-result-fr-dark.png') });
    await runSelect(page).selectOption(ids.old);
    await node(page, 'Prepared claims').getByTestId('flow-node-observe').click();
    await expect(panel(page)).toContainText('Aucun résultat accessible pour cette étape');
    await expect(panel(page).getByTestId('flow-result-viewer')).toHaveCount(0);
    await panel(page).getByRole('button', { name: 'Chercher un résultat récent' }).click();
    await expect(runSelect(page)).toHaveValue(ids.latest);
    await expect(panel(page).getByTestId('flow-observation-dataset-preview')).toBeVisible();
    expectReadOnly(api);
  });

  test('A denied Run and dataset are explicit failures, retry reads and never executes', async ({ page }) => {
    const api = await fixture(page, 'en');
    await open(page);
    await runSelect(page).selectOption(ids.forbidden);
    await expect(panel(page).getByRole('alert')).toBeVisible();
    await expect(panel(page).getByTestId('flow-result-viewer')).toHaveCount(0);
    api.allowRun();
    await panel(page).getByRole('button', { name: /Retry/ }).click();
    await expect(panel(page)).toContainText('RECOVERED_AUTHORIZED_EVIDENCE');
    await runSelect(page).selectOption(ids.latest);
    api.denyDataset(true);
    await node(page, 'Prepared claims').getByTestId('flow-node-observe').click();
    await expect(panel(page).getByRole('alert')).toBeVisible();
    expect(api.requests.filter(request => request.path === '/datasets/prepared-v7/preview')).toEqual([]);
    api.denyDataset(false);
    await panel(page).getByTestId('flow-observation-dataset-preview').click();
    await expect(panel(page).locator('ck-data-table')).toContainText('CASE-001');
    expectReadOnly(api);
  });

  test('Switching Run immediately clears former results and fences late responses', async ({ page }) => {
    const api = await fixture(page, 'en');
    await open(page);
    await expect(panel(page).locator('ck-forecast-chart')).toBeVisible();
    api.delayRun(ids.old);
    await runSelect(page).selectOption(ids.old);
    await expect.poll(api.hasPendingRun).toBe(true);
    await expect(panel(page).locator('ck-forecast-chart')).toHaveCount(0);
    await runSelect(page).selectOption(ids.different);
    await expect(panel(page)).toContainText('DIFFERENT_VERSION_EVIDENCE');
    api.releaseRun();
    await expect.poll(api.hasSettledRun).toBe(true);
    await expect(runSelect(page)).toHaveValue(ids.different);
    await expect(panel(page)).not.toContainText('OLDER_FORECAST_EVIDENCE');
    await expect(panel(page)).toContainText('DIFFERENT_VERSION_EVIDENCE');
    expectReadOnly(api);
  });

  test('Agent decisions are retained evidence scoped to the selected node', async ({ page }, info) => {
    const api = await fixture(page, 'en');
    await open(page, 'Investigate the claim');
    await expect(panel(page)).toContainText('Order paid; delivery late.');
    await expect(panel(page).getByTestId('agent-decision-trail')).toHaveCount(0);
    await panel(page).getByTestId('flow-observation-attempt-select').selectOption('agent-decision');
    const decisions = panel(page).getByTestId('agent-decision-trail');
    await expect(decisions).toContainText('Read the order facts before proposing a refund.');
    await expect(decisions.locator('.agent-choice')).toHaveCount(1);
    await expect(panel(page)).not.toContainText('MUST_NOT_BORROW_ADJACENT_AGENT');
    await decisions.locator('summary').click();
    await expect(decisions).toContainText('gpt-5-mini');
    await panel(page).getByTestId('flow-observation-presentation-select').selectOption('decisions');
    await expect(decisions).toBeVisible();
    await panel(page).screenshot({ path: info.outputPath('agent-recorded-choices-en-light.png') });
    expectReadOnly(api);
  });
});
