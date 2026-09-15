import { expect, test, type Page, type Route } from '@playwright/test';

// Local fixture only: no provider keys, no network outside loopback, no shared writes.
test.use({ serviceWorkers: 'block', video: 'off' });
test.beforeEach(async ({ baseURL }) => {
  test.skip(!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname), 'Model Portal contract runs only against a local frontend.');
});
const model = (provider: string, name: string) => ({ provider, model: name, name, id: `${provider}:${name}`, status: 'active', configured: true, discovered: true, runtime_available: true, compatibility: 'text_generation', credential_source: 'workspace' });
const MODELS = [model('openai', 'gpt-mini'), model('ollama', 'llama'), model('azure_openai', 'summary-deployment'), { ...model('openai', 'embed-only'), compatibility: 'other' }];
const TARGET = { system_id: 'system-portal', system_name: 'Document review', node_id: 'summary', node_label: 'Summarise document', skill_slug: 'ws.portal.summary', skill_name: 'Summary', provider: 'openai', model: 'gpt-mini', input_schema: { type: 'object', properties: { document_text: { type: 'string', description: 'Supplied text' } }, required: ['document_text'] }, input_defaults: { document_text: 'S1: a synthetic inspection excerpt.' }, expected_flow_sha256: 'a'.repeat(64) };
const RUN = { id: 'run-portal', system_id: 'system-portal', status: 'completed', execution_surface: 'workbench_node', source_flow_sha256: 'a'.repeat(64), duration_ms: 2814, output_ref: {}, skill_invocations: [{ id: 'inv-portal', run_id: 'run-portal', status: 'completed', cost: 0, cost_measured: true, output_ref: { completion: 'The synthetic inspection was reviewed. [S1]', model: 'do-not-trust-output-model' }, trace: { model_execution: { provider: 'openai', model: 'gpt-mini', returned_model: 'gpt-mini-2026', credential_source: 'workspace', model_source: 'executor', fallback: false } }, metrics: { total_tokens: 232, token_evidence: { measurement_coverage: 'complete' }, cost_evidence: { method: 'catalog_unit_price', currency: 'USD', state: 'calculated' } } }] };
async function setup(page: Page, options: { admin?: boolean; routingError?: boolean; modelError?: boolean; enabled?: boolean; targets?: boolean } = {}) {
  const admin = options.admin !== false;
  const enabled = options.enabled !== false;
  const calls: Array<{ method: string; path: string; body: any }> = [];
  const unexpected: string[] = [];
  const workspace = { id: 'workspace-portal', name: 'Portal contract', slug: 'portal-contract', role: admin ? 'admin' : 'viewer', role_template: admin ? 'workspace_admin' : 'workspace_viewer', member_count: 1, created_at: '2026-09-15T09:00:00Z', is_active: true, mode: 'builder', settings: { features: { model_portal_beta: enabled, flow_publication_v1: true, flow_builder_workbench: true } }, effective_features: { model_portal_beta: enabled, skill_invocation_360_projection_v1: true }, app_entitlements: [] };
  let metadata = { endpoint: 'https://azure.example.test', deployment: 'summary-deployment', api_version: '2024-10-21' };
  const provider = (key: string) => ({ key, label: key === 'azure_openai' ? 'Azure OpenAI' : key === 'openai' ? 'OpenAI' : 'Ollama', kind: key === 'ollama' ? 'local' : 'cloud', status: 'active', configured: true, runtime_available: true, api_key_set: key !== 'ollama', credential_source: 'workspace', models: MODELS.filter((m) => m.provider === key).map((m) => m.model), ...(key === 'azure_openai' ? metadata : {}) });
  const json = (route: Route, data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  await page.route('**/*', (route) => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort('blockedbyclient'));
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.replace(/^\/api\/v1/, ''), method = req.method();
    const body = req.postData() ? req.postDataJSON() : null;
    calls.push({ method, path, body });
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'user-portal', email: 'portal@example.test', role: admin ? 'admin' : 'viewer' });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/me') return json(route, { id: 'user-portal', username: 'portal', email: 'portal@example.test', role: admin ? 'admin' : 'viewer', is_active: true, mfa_enabled: false, workspaces: [workspace] });
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (path === '/audit' && method === 'POST') return json(route, { id: 'local-audit' }, 201);
    if (path === '/telemetry/live') return json(route, { throughput_rpm: null, latency_ms: null, yield_pct: null, runs_count: 0 });
    if (path === '/models') return options.modelError ? json(route, { detail: { message: 'Catalog unavailable' } }, 503) : json(route, { models: MODELS });
    if (path === '/models/providers') return json(route, { providers: ['openai', 'azure_openai', 'ollama'].map(provider), can_configure: admin });
    if (path === '/models/config') return json(route, { can_configure: admin, runtime_providers: ['openai', 'azure_openai', 'ollama'], cloud_credentials: [{ key: 'openai', api_key_set: true }, { key: 'azure_openai', api_key_set: true, ...metadata }] });
    if (path === '/models/routing') return options.routingError ? json(route, { detail: { message: 'Routing unavailable' } }, 503) : json(route, { default_provider: 'openai', default_model: 'gpt-mini', fallback_chain: [], model_usage: [{ system_id: 'system-portal', system_name: 'Document review', node_id: 'summary', provider: 'openai', model: 'gpt-mini', source: 'current_flow' }] });
    if (path === '/models/distribution') return json(route, { by_model: [{ provider: 'openai', model: 'gpt-mini', invocations: 2, cost: 0, currency: 'USD', cost_source: 'skill_catalog', cost_state: 'partial', evidence: [{ run_id: 'run-portal', invocation_id: 'inv-portal' }] }] });
    if (path === '/models/nodes') return json(route, { nodes: [] });
    if (path === '/models/test-targets') {
      expect(url.searchParams.get('provider')).toBe('openai'); expect(url.searchParams.get('model')).toBe('gpt-mini');
      return json(route, { can_test: admin, targets: options.targets === false ? [] : [TARGET], blockers: [] });
    }
    if (path === '/models/test' && method === 'POST') return json(route, { id: RUN.id, system_id: RUN.system_id, status: 'pending' }, 201);
    if (path === '/runs/run-portal') return json(route, RUN);
    if (/^\/models\/providers\/[^/]+\/test$/.test(path)) return json(route, { provider: provider(path.split('/')[3]), test_kind: 'connection', generation_verified: false });
    if (path === '/models/credentials/azure_openai' && method === 'PUT') { metadata = { ...metadata, ...body }; return json(route, { saved: true }); }
    if (['/capabilities', '/systems', '/runs', '/skills'].includes(path) && method === 'GET') return json(route, { [path.slice(1)]: [] });
    unexpected.push(`${method} ${path}`); return json(route, { detail: `Unhandled fixture ${method} ${path}` }, 501);
  });
  await page.addInitScript(() => { localStorage.setItem('agentium_token', 'Bearer local-portal'); localStorage.setItem('agentium_workspace_slug', 'portal-contract'); localStorage.setItem('agentium_locale', 'en'); });
  return { calls, unexpected };
}

test('provider-aware catalogue, saved Azure metadata, explicit connection check and Skill link', async ({ page }, info) => {
  const h = await setup(page); await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/resources');
  const app = page.locator('app-resources-page'); await expect(app.getByText('gpt-mini', { exact: true }).first()).toBeVisible();
  await expect(app.getByText('embed-only', { exact: true })).toHaveCount(0);
  await expect(app.getByText('Configured in Systems:')).toBeVisible();
  await expect(app.getByRole('link', { name: 'Document review · summary' })).toHaveAttribute('href', /\/systems\/system-portal\/flow/);
  const row = app.locator('li').filter({ hasText: 'gpt-mini' }).first();
  const skill = row.getByRole('link', { name: 'Use in a Skill', exact: true });
  await expect(skill).toHaveAttribute('href', /provider=openai/); await expect(skill).toHaveAttribute('href', /model=gpt-mini/); await expect(skill).toHaveAttribute('href', /modelWorkspace=workspace-portal/);
  await page.screenshot({ path: info.outputPath('catalog-desktop.png'), fullPage: true });
  await row.getByRole('button', { name: 'Test in a System', exact: true }).click();
  const routing = app.locator('section').filter({ has: page.getByRole('heading', { name: 'Workspace routing', exact: true }) });
  const selects = routing.getByRole('combobox'); await expect(selects.nth(0)).toHaveValue('openai'); await expect(selects.nth(1)).toHaveValue('gpt-mini');
  await selects.nth(0).selectOption('ollama'); await expect(selects.nth(1)).toHaveValue('');
  await expect(selects.nth(1).locator('option')).toHaveText(['Choose a model', 'llama']);
  await expect(routing.getByRole('button', { name: 'Save routing' })).toBeDisabled();
  const azure = app.locator('section').filter({ has: page.getByRole('heading', { name: 'Azure OpenAI', exact: true }) });
  await expect(azure.getByRole('textbox', { name: 'Endpoint', exact: true })).toHaveValue('https://azure.example.test');
  await expect(azure.locator('input[type=password]')).toHaveValue('');
  await azure.getByRole('textbox', { name: 'Deployment', exact: true }).fill('reloaded-deployment');
  await azure.getByRole('button', { name: 'Save connection', exact: true }).click();
  await page.reload(); await expect(azure.getByRole('textbox', { name: 'Deployment', exact: true })).toHaveValue('reloaded-deployment');
  await azure.getByRole('button', { name: 'Verify connection', exact: true }).click();
  await expect.poll(() => h.calls.filter((c) => c.path === '/models/providers/azure_openai/test').length).toBe(1);
  await azure.screenshot({ path: info.outputPath('provider-azure-desktop.png') });
  expect(h.calls.some((c) => c.path === '/models/test')).toBe(false); expect(h.unexpected).toEqual([]);
});

test('routing read failure cannot save invented defaults; read-only users cannot configure', async ({ page }) => {
  const h = await setup(page, { routingError: true, admin: false }); await page.goto('/resources?facet=providers');
  const app = page.locator('app-resources-page'); await expect(app.getByText('Routing unavailable', { exact: true })).toBeVisible();
  await expect(app.getByRole('button', { name: 'Save routing' })).toBeDisabled();
  await expect(app).toContainText('Partial subtotal');
  await expect(app.getByRole('button', { name: 'Save connection' })).toHaveCount(0);
  for (const button of await app.getByRole('button', { name: 'Verify connection' }).all()) await expect(button).toBeDisabled();
  expect(h.calls.some((c) => ['POST', 'PUT', 'DELETE'].includes(c.method) && c.path.startsWith('/models'))).toBe(false); expect(h.unexpected).toEqual([]);
});

test('contract fields execute a canonical test and expose Run provenance at narrow width', async ({ page }, info) => {
  const h = await setup(page); await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/resources');
  const app = page.locator('app-resources-page'); const row = app.locator('li').filter({ hasText: 'gpt-mini' }).first();
  await row.getByRole('button', { name: 'Test in a System', exact: true }).click();
  const panel = app.locator('#model-system-test'); await expect(panel).toBeFocused(); await panel.getByRole('combobox', { name: 'System and node', exact: true }).selectOption('system-portal:summary');
  await expect(panel.getByRole('textbox', { name: /^document_text/ })).toHaveValue(TARGET.input_defaults.document_text);
  await panel.getByRole('textbox', { name: /^document_text/ }).fill('S1: checked by the technician.');
  await expect(panel.getByRole('button', { name: 'Run test', exact: true })).toBeDisabled();
  await panel.getByRole('checkbox').check(); await panel.getByRole('button', { name: 'Run test', exact: true }).click();
  await expect(panel.getByText('The synthetic inspection was reviewed. [S1]', { exact: true })).toBeVisible();
  await expect(panel.getByRole('link', { name: 'Open Run', exact: true })).toHaveAttribute('href', /\/runs\/run-portal/);
  await expect(panel).toContainText('gpt-mini-2026'); await expect(panel).toContainText('232'); await expect(panel).toContainText('2814'); await expect(panel).toContainText('Catalog tariff calculation');
  await expect(panel.locator('app-model-execution')).toContainText('Workspace'); await expect(panel).not.toContainText('do-not-trust-output-model');
  const request = h.calls.find((c) => c.path === '/models/test'); expect(request?.body).toEqual({ ...Object.fromEntries(['system_id', 'node_id', 'provider', 'model', 'expected_flow_sha256'].map((key) => [key, TARGET[key as keyof typeof TARGET]])), input_ref: { document_text: 'S1: checked by the technician.' }, acknowledge_real_side_effects: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
  await panel.getByRole('heading', { name: 'Result and evidence' }).locator('..').screenshot({ path: info.outputPath('test-result-mobile.png') }); expect(h.unexpected).toEqual([]);
});

test('no matching test node offers a Skill entry without privileged generation', async ({ page }) => {
  const h = await setup(page, { targets: false }); await page.goto('/resources');
  await page.locator('app-resources-page li').filter({ hasText: 'gpt-mini' }).first().getByRole('button', { name: 'Test in a System' }).click();
  const panel = page.locator('#model-system-test'); await expect(panel.getByText(/No compatible node/)).toBeVisible();
  await expect(panel.getByRole('link', { name: 'Use in a Skill' })).toHaveAttribute('href', /create=llm/);
  await expect(panel.getByRole('button', { name: 'Run test' })).toHaveCount(0); expect(h.calls.some((c) => c.path === '/models/test')).toBe(false);
});

test('catalogue read failure is distinct from empty and disabled portal links explain the gate', async ({ page }) => {
  await setup(page, { modelError: true, enabled: false }); await page.goto('/resources?facet=providers');
  const app = page.locator('app-resources-page'); await expect(app.getByRole('alert').filter({ hasText: 'Catalog unavailable' })).toBeVisible();
  await expect(app.getByText(/LLM Portal is not enabled in this workspace/)).toBeVisible();
  await expect(app.getByRole('heading', { name: 'No models available' })).toHaveCount(0);
  await expect(app.getByRole('button', { name: 'Save routing' })).toHaveCount(0);
});
