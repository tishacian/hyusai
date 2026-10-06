import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const workspace = { id: 'luma-source-qa', slug: 'luma-source-qa', name: 'Agentium Showcase QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const systemId = 'luma-source-system';
const hash = '1'.repeat(64);
const columns = [
  { name: 'claim_id', dtype: 'text', kind: 'string', supported: true, primary_key: true, as_text: false },
  { name: 'amount', dtype: 'numeric', kind: 'number', supported: true, primary_key: false, as_text: true },
];
const config = { id: 'postgresql', configured: true, values: { database: 'postgres' }, secrets_set: { password: true } };

async function setup(page: Page, options: { theme?: string; locale?: string; admin?: boolean; missing?: boolean; changed?: boolean; catalogError?: boolean } = {}) {
  let flow = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/app/resources/flows/showcase_ecommerce_claims_v1.json'), 'utf8'));
  const positions: Record<string, [number, number]> = {
    'asset.postgresql': [40, 40], 'source.request': [40, 340], 'loop.investigate': [410, 200],
    'decision.ready': [740, 200], 'hitl.review': [1070, 120], 'task.simulate': [1400, 120],
    'sink.receipt': [1730, 120], 'sink.blocked': [1070, 390],
  };
  for (const node of flow.nodes) { const [x, y] = positions[node.id]; node.position = { x, y }; }
  flow.nodes.push({ id: 'asset.documents', type: 'source.collection', kind: 'asset', label: 'luma-maison-regles', config: { collection_slug: 'luma-maison-regles', workspace_scoped: true }, outputs: [{ name: 'collection', schema: 'object' }], position: { x: 40, y: 210 } });
  flow.edges.push({ from: 'asset.documents', to: 'loop.investigate', kind: 'data', from_port: 'collection' });
  const writes: Array<{ path: string; body: any }> = [];
  let revision = 4;
  const system = () => ({ id: systemId, workspace_id: workspace.id, name: 'Luma Maison · Réclamations', status: 'active', flow_definition: flow, flow_sha256: hash, objective: 'SAV' });
  const state = () => ({ system_id: systemId, status: 'active', draft: { revision, base_published_version_id: 'luma-published-v2', flow_sha256: hash, flow_definition: flow }, published: { version_id: 'luma-published-v2', version_number: 2, flow_sha256: hash, flow_definition: flow, execution_contract_ready: true } });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ theme, locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-source-qa'); localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', theme); localStorage.setItem('agentium_locale', locale);
  }, { theme: options.theme ?? 'dark', locale: options.locale ?? 'fr', slug: workspace.slug });
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'source-qa-human', role: 'admin', email: 'source@example.test' });
    if (path === '/auth/me') return json(route, { id: 'source-qa-human', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (req.method() !== 'GET') writes.push({ path, body: req.postDataJSON() });
    if (path === '/systems') return json(route, { systems: [system()] });
    if (path === `/systems/${systemId}`) return json(route, system());
    if (path === `/systems/${systemId}/flow-state`) return json(route, state());
    if (path === `/systems/${systemId}/flow-draft` && req.method() === 'PUT') {
      flow = req.postDataJSON().flow_definition; revision++; return json(route, { ...state().draft, system_id: systemId, no_op: false });
    }
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_overlay', flow_sha256: hash });
    if (path === '/skills') return json(route, { skills: [] });
    if (path === '/documents/collections') return json(route, { collections: ['luma-maison-regles', 'luma-maison-preuves'] });
    if (path === '/connectors') return options.catalogError ? json(route, {}, 503) : json(route, { can_configure: options.admin !== false, connectors: options.missing ? [] : [config] });
    if (path === '/connectors/postgresql/catalog') return json(route, { tables: [{ schema: 'showcase_ecommerce', name: 'claims', kind: 'table' }], checked_at: '2026-10-05T12:00:00Z', datasets_enabled: true });
    if (path === '/connectors/postgresql/table') return json(route, { schema: 'showcase_ecommerce', table: 'claims', fingerprint: 'a'.repeat(64), columns });
    if (path === '/connectors/postgresql/preview') return options.changed ? json(route, { detail: { code: 'PG_SOURCE_CHANGED' } }, 409) : json(route, { schema: columns, rows: [{ claim_id: 'RC-1043', amount: '49.90' }], row_count: 1, has_more: true, captured_at: '2026-10-05T12:01:00Z', ordered_by: ['claim_id'] });
    return json(route, {});
  });
  return { writes, flow: () => flow };
}

async function openSource(page: Page) {
  await page.goto(`/systems/${systemId}/flow?lens=build`);
  await expect(page.locator('app-flow-node')).toHaveCount(9);
  await page.locator('app-flow-node').filter({ hasText: 'PostgreSQL · Luma Maison' }).click();
  const inspector = page.getByTestId('flow-data-source-inspector');
  await expect(inspector).toBeVisible();
  return inspector;
}

test.describe('Flow data sources — isolated end-user QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const [theme, locale, width] of [['dark', 'fr', 1440], ['light', 'fr', 390], ['light', 'en', 1440]] as const) {
    test(`${theme}/${locale}/${width}: Luma source drills down to live table preview`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      const { writes } = await setup(page, { theme, locale });
      const inspector = await openSource(page);
      await expect(inspector).toContainText(locale === 'en' ? 'Scope · 7 tables' : 'Périmètre · 7 tables');
      await expect(inspector.getByRole('link')).toHaveAttribute('href', /\/connectors\/postgresql/);
      await page.screenshot({ path: info.outputPath('luma-source-flow.png'), fullPage: true });
      await inspector.getByRole('button', { name: /^claims/ }).click();
      await expect(inspector.getByText('claim_id', { exact: true })).toBeVisible();
      const preview = inspector.getByRole('button', { name: locale === 'en' ? 'Preview · 25 rows' : 'Aperçu · 25 lignes', exact: true });
      const size = await preview.boundingBox(); expect(size!.height).toBeLessThanOrEqual(32);
      await preview.click();
      await expect(page.getByTestId('flow-source-preview')).toContainText('49.90');
      await page.getByTestId('flow-source-preview').locator('ck-data-table').scrollIntoViewIfNeeded();
      await expect(page.getByTestId('flow-source-preview').getByText('49.90', { exact: true })).toBeVisible();
      const request = writes.find(w => w.path.endsWith('/preview'))!;
      expect(request.body).toEqual({ schema: 'showcase_ecommerce', table: 'claims', fingerprint: 'a'.repeat(64), columns: ['claim_id', 'amount'], limit: 25 });
      expect(writes.filter(w => /flow-draft|postgresql\/import|postgresql\/test/.test(w.path))).toEqual([]);
      await page.screenshot({ path: info.outputPath('luma-source-preview.png'), fullPage: true });
      expect(await page.locator('#main-content').evaluate(e => e.scrollWidth <= e.clientWidth + 1)).toBe(true);
      const audit = await new AxeBuilder({ page }).include('app-flow-data-source-inspector').analyze();
      expect(audit.violations).toEqual([]);
      await inspector.getByRole('button', { name: 'Enquêter avec les preuves', exact: true }).click();
      await expect(page.getByTestId('flow-data-source-inspector')).toHaveCount(0);
      await expect(page.locator('app-flow-inspector')).toContainText('Enquêter avec les preuves');
    });
  }

  test('configured catalogue instantiates a reference and saves it without credentials', async ({ page }) => {
    const { writes } = await setup(page); await openSource(page);
    await page.getByRole('button', { name: 'Tout afficher', exact: true }).click();
    expect((await new AxeBuilder({ page }).include('app-flow-palette').analyze()).violations).toEqual([]);
    await page.getByTestId('flow-sources-palette').getByRole('button', { name: /^Sources du workspace/ }).click();
    await page.getByTestId('flow-sources-palette').getByRole('button', { name: /^PostgreSQL/ }).click();
    await expect(page.locator('app-flow-node')).toHaveCount(10);
    await expect.poll(() => writes.filter(w => w.path.endsWith('/flow-draft')).length).toBeGreaterThan(0);
    const saved = writes.filter(w => w.path.endsWith('/flow-draft')).at(-1)!.body.flow_definition;
    const nodes = saved.nodes.filter((node: any) => node.type === 'source.connector');
    expect(nodes).toHaveLength(2); expect(nodes.at(-1).config).toEqual({ connector_id: 'postgresql', read_mode: 'live', resources: [] });
    expect(JSON.stringify(saved)).not.toMatch(/secrets_set|password|postgres\.example/);

    const inspector = page.getByTestId('flow-data-source-inspector');
    await expect(inspector).toContainText('Périmètre · 0 tables');
    await inspector.getByRole('button', { name: 'Parcourir les tables', exact: true }).click();
    await inspector.getByRole('button', { name: /^claims/ }).click();
    await inspector.getByRole('button', { name: 'Ajouter au périmètre', exact: true }).click();
    await expect(inspector).toContainText('Périmètre · 1 table');
    await expect(inspector.getByRole('button', { name: /^claims.*Dans le périmètre/ })).toBeVisible();
    await expect(inspector.getByText('claim_id', { exact: true })).toBeVisible();
    await inspector.getByRole('combobox', { name: 'Relier une étape', exact: true }).selectOption('decision.ready');
    const sourceId = nodes.at(-1).id;
    await expect.poll(() => {
      const graph = writes.filter(w => w.path.endsWith('/flow-draft')).at(-1)!.body.flow_definition;
      return graph.edges.some((edge: any) => edge.from === sourceId && edge.to === 'decision.ready' && edge.kind === 'data');
    }).toBe(true);
    const linked = writes.filter(w => w.path.endsWith('/flow-draft')).at(-1)!.body.flow_definition;
    expect(linked.nodes.find((node: any) => node.id === sourceId).config.resources).toEqual([{ schema: 'showcase_ecommerce', table: 'claims' }]);
  });

  for (const options of [{ admin: false }, { missing: true }, { catalogError: true }]) {
    test(`unavailable/unauthorized source preserves saved references ${JSON.stringify(options)}`, async ({ page }) => {
      const { writes } = await setup(page, options); const inspector = await openSource(page);
      await expect(inspector).toContainText('Périmètre · 7 tables');
      await expect(inspector.getByRole('button', { name: 'Parcourir les tables', exact: true })).toBeDisabled();
      expect(writes.filter(w => w.path.endsWith('/flow-draft') || w.path.endsWith('/preview'))).toEqual([]);
    });
  }

  test('schema changes fail visibly without a fabricated preview', async ({ page }) => {
    await setup(page, { changed: true }); const inspector = await openSource(page);
    await inspector.getByRole('button', { name: /^claims/ }).click();
    await inspector.getByRole('button', { name: 'Aperçu · 25 lignes', exact: true }).click();
    await expect(inspector.getByRole('alert')).toContainText('schéma');
    await expect(page.getByTestId('flow-source-preview')).toHaveCount(0);
  });

  test('the objection strip stays out of the way until there is a run to object to', async ({ page }) => {
    await setup(page, { theme: 'dark', locale: 'fr' });
    await page.route('**/api/v1/systems/*/automation-review', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ runs: [], review: null }) }));
    await page.goto(`/systems/${systemId}/flow?lens=build`);
    await expect(page.locator('app-flow-node')).toHaveCount(9);
    await expect(page.locator('app-review-loop section')).toHaveCount(0);
  });

  test('a run opens a compact objection strip, then its form and steps', async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await setup(page, { theme: 'dark', locale: 'fr' });
    let review: unknown = null;
    await page.route('**/api/v1/systems/*/automation-review', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ runs: [{ id: 'run-2', status: 'completed' }, { id: 'run-1', status: 'completed' }], review }) }));
    await page.goto(`/systems/${systemId}/flow?lens=build`);
    const strip = page.locator('app-review-loop section');
    await expect(strip).toContainText('Émettre une réserve');
    expect((await strip.boundingBox())!.height).toBeLessThanOrEqual(48);
    await strip.getByRole('button', { name: 'Émettre une réserve' }).click();
    await expect(strip.getByRole('textbox')).toBeVisible();
    await expect(strip.locator('.review__steps li')).toHaveCount(4);
    await page.screenshot({ path: info.outputPath('review-open.png'), clip: { x: 0, y: 0, width: 1440, height: 520 } });
    review = { id: 'rev-1', system_id: systemId, run_id: 'run-2', note: 'Le remboursement ignore la preuve de livraison.', status: 'open', draft_hash: 'abc' };
    await page.reload();
    await expect(page.locator('app-review-loop [data-testid="review-status"]')).toContainText('Étape 3 sur 4 · Correction');
    await expect(page.locator('app-review-loop q')).toContainText('preuve de livraison');
    await page.screenshot({ path: info.outputPath('review-step3.png'), clip: { x: 0, y: 0, width: 1440, height: 420 } });
  });
});

