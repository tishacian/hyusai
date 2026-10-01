import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off' });

// This contract runs against the local production bundle. Every API request is
// intercepted, and requests outside loopback are blocked, so it cannot change
// the demo server or use a real connector credential.
const workspace = {
  id: 'connector-honesty-workspace', slug: 'connector-honesty',
  name: 'Connector honesty', role: 'admin', role_template: 'workspace_admin',
  is_active: true, mode: 'builder', app_entitlements: [],
  settings: { features: { sap_hana_connector: true } },
  effective_features: { sap_hana_connector: true },
};

type Preview = {
  source?: string;
  row_count?: number;
};

async function prepare(page: Page, options: {
  configured?: boolean;
  preview?: Preview;
  locale?: 'fr' | 'en';
} = {}) {
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname)) {
    throw new Error('Connector honesty tests require a loopback E2E_BASE_URL');
  }
  const unexpected: string[] = [];
  await page.route('**/*', (route) => {
    const host = new URL(route.request().url()).hostname;
    return ['localhost', '127.0.0.1'].includes(host)
      ? route.fallback() : route.abort('blockedbyclient');
  });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    const json = (body: unknown, status = 200) => route.fulfill({
      status, contentType: 'application/json', body: JSON.stringify(body),
    });
    if (path === '/auth/validate' && method === 'POST') {
      return json({ valid: true, user_id: 'connector-operator', role: 'admin' });
    }
    if (path === '/auth/workspaces') return json([workspace]);
    if (path === '/auth/me') return json({
      id: 'connector-operator', username: 'operator', email: 'operator@example.test',
      role: 'admin', is_active: true, workspaces: [workspace],
    });
    if (path === `/auth/workspaces/${workspace.slug}/me/experience` && method === 'GET') {
      return json({ version: 1, persona: 'builder', journey: 'client_sources',
        completed_steps: [], dismissed: true, available: false, sources: [],
        rail_labels: 'shown', first_seen_at: '2026-09-30T09:00:00Z' });
    }
    if (path === '/settings' && method === 'GET') return json({});
    if (path === '/iam/matrix' && method === 'GET') return json({
      workspace, subject_user_id: 'connector-operator', role_template: 'workspace_admin',
      custom_labels: [], role_flags: {}, enforcement: false, permissions: [],
    });
    if (path === '/skills/runtime-health' && method === 'GET') return json({
      skills: {}, summary: { bound: 0, stub: 0, unbound: 0, catalog_only: 0 },
    });
    if (path === '/reasoning/templates' && method === 'GET') return json({ templates: [] });
    if (path === '/voice/runtimes' && method === 'GET') return json({ runtimes: [] });
    if (path === '/actions/effective' && method === 'GET') return json({ actions: [] });
    if (['/systems', '/capabilities', '/skills', '/runs', '/sessions'].includes(path) && method === 'GET') {
      return json({ [path.slice(1)]: [] });
    }
    if (path === '/connectors') return json({ can_configure: true, connectors: [{
      id: 'postgresql', configured: options.configured === true, testable: true,
      values: { host: 'postgres.example.test', database: 'demo', username: 'operator' },
      secrets_set: { password: options.configured === true },
    }] });
    if (path === '/hana/config') return json({
      host: 'hana.example.test', port: 443, user: 'OPERATOR', password_set: true,
    });
    if (path === '/hana/preview') return json({
      ok: true, tables: [{ name: 'EQUIPMENT', kind: 'table' }],
      sample_table: 'EQUIPMENT', columns: ['EQUIPMENT_ID'], rows: [],
      ...options.preview,
    });
    if (path === '/models') return json({ models: [] });
    if (path === '/help-content') return json({ version: 'local', items: [], personas: [], languages: [] });
    if (path === '/telemetry/live') return json({ throughput_rpm: null, latency_ms: null, runs_count: 0 });
    if (path === '/audit' && method === 'POST') return json({ id: 'local-navigation-audit' }, 201);
    unexpected.push(`${method} ${path}`);
    return json({ detail: `Unhandled local mock endpoint: ${method} ${path}` }, 501);
  });
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer local-connector-honesty-token');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
  }, { slug: workspace.slug, locale: options.locale ?? 'en' });
  return unexpected;
}

for (const configured of [false, true]) {
  test(`Resources does not claim PostgreSQL data access (${configured ? 'saved' : 'unset'} configuration)`, async ({ page }) => {
    const unexpected = await prepare(page, { configured });
    await page.goto('/resources?facet=connectors');
    const card = page.getByRole('button').filter({ has: page.getByRole('heading', { name: 'PostgreSQL', exact: true }) });
    await expect(card).toContainText('Explore tables, preview live data and import versioned datasets for DataOps.');
    await expect(card).not.toContainText('Data queries and imports are not available yet.');
    await expect(card.locator('app-status-pulse')).toHaveCount(0);
    expect(unexpected).toEqual([]);
  });

  test(`Connectors keeps PostgreSQL capability limits visible (${configured ? 'saved' : 'unset'} configuration)`, async ({ page }) => {
    const unexpected = await prepare(page, { configured });
    await page.goto('/connectors');
    const card = page.locator('article').filter({ has: page.getByRole('heading', { name: 'PostgreSQL', exact: true }) });
    await expect(card).toContainText('Explore tables, preview live data and import versioned datasets for DataOps.');
    await expect(card).not.toContainText('Data queries and imports are not available yet.');
    await expect(card.locator('.ck-pill')).toHaveClass(configured ? /ck-tone-ok/ : /ck-tone-info/);
    expect(unexpected).toEqual([]);
  });
}

test('HANA demonstration data has an explicit French warning above the sample', async ({ page }, info) => {
  const unexpected = await prepare(page, { locale: 'fr', preview: { source: 'demo_dataset', row_count: 0 } });
  await page.goto('/connectors/sap-hana');
  const warning = page.getByRole('status').filter({ hasText: 'Jeu de démonstration' });
  await expect(warning).toBeVisible();
  await expect(warning).toContainText('Elles ne proviennent pas de votre instance SAP HANA.');
  await expect(page.locator('app-hana-connector')).toContainText('0 lignes');
  await warning.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath('hana-demonstration-fr.png'), fullPage: true });
  expect(unexpected).toEqual([]);
});

test('live HANA is never presented as demonstration data', async ({ page }) => {
  const unexpected = await prepare(page, { preview: { source: 'hana_live', row_count: 0 } });
  await page.goto('/connectors/sap-hana');
  await expect(page.locator('app-hana-connector')).toContainText('Live HANA');
  await expect(page.getByRole('status').filter({ hasText: 'Demo dataset' })).toHaveCount(0);
  await expect(page.locator('app-hana-connector')).not.toContainText('internal demonstration data');
  expect(unexpected).toEqual([]);
});

for (const source of [undefined, 'unrecognised_source']) {
  test(`HANA does not invent provenance or a row count for ${source ?? 'missing'} source`, async ({ page }) => {
    const unexpected = await prepare(page, { preview: { source } });
    await page.goto('/connectors/sap-hana');
    await expect(page.locator('app-hana-connector')).toContainText('Unknown source');
    await expect(page.locator('app-hana-connector')).toContainText('— rows');
    await expect(page.locator('app-hana-connector')).not.toContainText('Demo dataset');
    await expect(page.locator('app-hana-connector')).not.toContainText('Live HANA');
    expect(unexpected).toEqual([]);
  });
}
