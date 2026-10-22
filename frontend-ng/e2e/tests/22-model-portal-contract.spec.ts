import { expect, test, type Page, type Route } from '@playwright/test';

// Local fixture only: no provider keys, no network outside loopback, no shared writes.
test.use({ serviceWorkers: 'block', video: 'off' });
test.beforeEach(async ({ baseURL }) => {
  test.skip(!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname), 'Model Portal contract runs only against a local frontend.');
});
const model = (provider: string, name: string) => ({ provider, model: name, name, id: `${provider}:${name}`, status: 'active', configured: true, discovered: true, runtime_available: true, compatibility: 'text_generation', credential_source: 'workspace' });
const JEV = {...model('typesafe', 'jev-1.13.0'), runtime_available: false, typed_decisions_available: true, capabilities: ['typed_decisions'], compatibility: 'typed_decisions'};
const MODELS = [JEV, model('openai', 'gpt-mini'), model('ollama', 'llama'), model('azure_openai', 'summary-deployment'), { ...model('openai', 'embed-only'), compatibility: 'other' }];
const TARGET = { system_id: 'system-portal', system_name: 'Document review', node_id: 'summary', node_label: 'Summarise document', skill_slug: 'ws.portal.summary', skill_name: 'Summary', provider: 'openai', model: 'gpt-mini', input_schema: { type: 'object', properties: { document_text: { type: 'string', description: 'Supplied text' } }, required: ['document_text'] }, input_defaults: { document_text: 'S1: a synthetic inspection excerpt.' }, expected_flow_sha256: 'a'.repeat(64) };
const RUN = { id: 'run-portal', system_id: 'system-portal', status: 'completed', execution_surface: 'workbench_node', source_flow_sha256: 'a'.repeat(64), duration_ms: 2814, output_ref: {}, skill_invocations: [{ id: 'inv-portal', run_id: 'run-portal', status: 'completed', cost: 0, cost_measured: true, output_ref: { completion: 'The synthetic inspection was reviewed. [S1]', model: 'do-not-trust-output-model' }, trace: { model_execution: { provider: 'openai', model: 'gpt-mini', returned_model: 'gpt-mini-2026', credential_source: 'workspace', model_source: 'executor', fallback: false } }, metrics: { total_tokens: 232, token_evidence: { measurement_coverage: 'complete' }, cost_evidence: { method: 'catalog_unit_price', currency: 'USD', state: 'calculated' } } }] };
async function setup(page: Page, options: { admin?: boolean; routingError?: boolean; modelError?: boolean; enabled?: boolean; targets?: boolean; comparisonUnknown?: boolean; restoreUnknown?: boolean; locale?: 'en' | 'fr'; dark?: boolean } = {}) {
  const admin = options.admin !== false;
  const enabled = options.enabled !== false;
  const calls: Array<{ method: string; path: string; body: any }> = [];
  const unexpected: string[] = [];
  const workspace = { id: 'workspace-portal', name: 'Portal contract', slug: 'portal-contract', role: admin ? 'admin' : 'viewer', role_template: admin ? 'workspace_admin' : 'workspace_viewer', member_count: 1, created_at: '2026-09-15T09:00:00Z', is_active: true, mode: 'builder', settings: { features: { model_portal_beta: enabled, flow_publication_v1: true, flow_builder_workbench: true } }, effective_features: { model_portal_beta: enabled, skill_invocation_360_projection_v1: true }, app_entitlements: [] };
  let metadata = { endpoint: 'https://azure.example.test', deployment: 'summary-deployment', api_version: '2024-10-21' };
  let comparisonAttempts = 0, restoreAttempts = 0, restored = false;
  const promptSkill = () => ({id: 'prompt-skill', slug: 'ws.portal.reply', name: 'Draft a customer response', description: 'Compose from supplied evidence.', workspace_scope: 'workspace', version: '1', category: 'LLM', input_schema: {type: 'object', properties: {details: {type: 'string'}}}, output_schema: {type: 'object'}, executor: {kind: 'prompt_template', params: {provider: 'openai', model: 'gpt-mini', template: restored ? 'Published: {details}' : 'Current: {details}'}}, metrics: {}});
  const sample = {invocation_id: 'decision-reference', run_id: 'run-reference', system_id: 'system-portal', system_name: 'Document review', started_at: '2026-10-22T10:35:00Z', objective: 'Check the delivery before proposing a resolution.', observations_count: 3, input_sha256: 'c'.repeat(64), instruction_sha256: 'd'.repeat(64), model: {provider: 'openai', model: 'gpt-mini'}};
  const comparisonRuns = ['first', 'second'].map((id, index) => ({id: `compare-${id}`, system_id: 'system-portal', status: 'completed', execution_surface: 'node_preview', skill_invocations: [{id: `inv-${id}`, skill_slug: 'decide_next_v1', status: 'completed', latency_ms: 800 + index * 100, cost_measured: index === 0, cost: index === 0 ? .003 : null, input_ref: {visible_skills: [{slug: 'read_delivery_v1', purpose: 'Read the delivery receipt'}]}, output_ref: {next_skill: index === 0 ? 'read_delivery_v1' : null, done: index === 1, exit: index === 1 ? 'complete' : null, rationale: index === 0 ? 'The delivery evidence needs checking.' : 'The supplied observations answer the question.'}, trace: {model_execution: {provider: index === 0 ? 'openai' : 'ollama', model: index === 0 ? 'gpt-mini' : 'llama', model_source: 'input', credential_source: 'workspace', fallback: false}}, metrics: index === 0 ? {total_tokens: 120, token_evidence: {measurement_coverage: 'complete'}, cost_evidence: {state: 'measured', currency: 'USD', method: 'provider_measurement'}} : {}}]}));
  const provider = (key: string) => ({ key, label: key === 'azure_openai' ? 'Azure OpenAI' : key === 'openai' ? 'OpenAI' : key === 'typesafe' ? 'TypeSafe' : 'Ollama', kind: key === 'ollama' ? 'local' : 'cloud', status: 'active', configured: true, runtime_available: key !== 'typesafe', typed_decisions_available: key === 'typesafe', capabilities: key === 'typesafe' ? ['typed_decisions'] : ['text_generation'], api_key_set: key !== 'ollama', credential_source: 'workspace', models: MODELS.filter((m) => m.provider === key).map((m) => m.model), ...(key === 'azure_openai' ? metadata : {}) });
  const json = (route: Route, data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  await page.route('**/*', (route) => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort('blockedbyclient'));
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.replace(/^\/api\/v1/, ''), method = req.method();
    const body = req.postData() ? req.postDataJSON() : null;
    calls.push({ method, path, body });
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'user-portal', email: 'portal@example.test', role: admin ? 'admin' : 'viewer' });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/me') return json(route, { id: 'user-portal', username: 'portal', email: 'portal@example.test', role: admin ? 'admin' : 'viewer', is_active: true, mfa_enabled: false, workspaces: [workspace] });
    if (path === '/auth/workspaces/portal-contract/me/experience') return json(route, {version: 1, persona: 'builder', completed_steps: [], dismissed: true, rail_labels: 'shown'});
    if (path === '/settings') return json(route, {});
    if (path === '/iam/matrix') return json(route, {workspace, subject_user_id: 'user-portal', role_template: admin ? 'workspace_admin' : 'workspace_viewer', custom_labels: [], role_flags: {}, enforcement: false, permissions: []});
    if (path === '/skills/runtime-health') return json(route, {skills: {}, summary: {bound: 0, stub: 0, unbound: 0, catalog_only: 0}});
    if (path === '/reasoning/templates') return json(route, {templates: []});
    if (path === '/voice/runtimes') return json(route, {runtimes: []});
    if (path === '/actions/effective') return json(route, {actions: []});
    if (path === '/sessions') return json(route, {sessions: []});
    if (path === '/connectors') return json(route, {connectors: [], can_configure: admin});
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (path === '/audit' && method === 'POST') return json(route, { id: 'local-audit' }, 201);
    if (path === '/telemetry/live') return json(route, { throughput_rpm: null, latency_ms: null, yield_pct: null, runs_count: 0 });
    if (path === '/models') return options.modelError ? json(route, { detail: { message: 'Catalog unavailable' } }, 503) : json(route, { models: MODELS });
    if (path === '/models/providers') return json(route, { providers: ['openai', 'azure_openai', 'ollama', 'typesafe'].map(provider), can_configure: admin });
    if (path === '/models/config') return json(route, { can_configure: admin, runtime_providers: ['openai', 'azure_openai', 'ollama'], cloud_credentials: [{ key: 'typesafe', api_key_set: true }, { key: 'openai', api_key_set: true }, { key: 'azure_openai', api_key_set: true, ...metadata }] });
    if (path === '/models/routing') return options.routingError ? json(route, { detail: { message: 'Routing unavailable' } }, 503) : json(route, { default_provider: 'openai', default_model: 'gpt-mini', fallback_chain: [], model_usage: [{ system_id: 'system-portal', system_name: 'Document review', node_id: 'summary', provider: 'openai', model: 'gpt-mini', source: 'current_flow' }] });
    if (path === '/models/distribution') return json(route, { by_model: [{ provider: 'openai', model: 'gpt-mini', invocations: 2, cost: 0, currency: 'USD', cost_source: 'skill_catalog', cost_state: 'partial', evidence: [{ run_id: 'run-portal', invocation_id: 'inv-portal' }] }] });
    if (path === '/models/nodes') return json(route, { nodes: [] });
    if (path === '/models/decision-samples') return json(route, {can_compare: admin, blockers: [], samples: admin ? [sample] : []});
    if (path === '/models/decision-comparisons' && method === 'POST') {
      comparisonAttempts += 1;
      if (options.comparisonUnknown && comparisonAttempts === 1) return json(route, {detail: 'Response lost after acceptance'}, 503);
      return json(route, {runs: comparisonRuns.map(run => ({id: run.id, system_id: run.system_id, status: 'pending'}))}, 201);
    }
    if (path.startsWith('/runs/compare-')) return json(route, comparisonRuns.find(run => path === `/runs/${run.id}`));
    if (path === '/skills/ws.portal.reply') return json(route, promptSkill());
    if (path === '/skills/executors') return json(route, {editable: admin, categories: ['LLM'], executors: []});
    if (path === '/models/resolve') return json(route, {provider: 'openai', model: 'gpt-mini', model_source: 'executor', credential_source: 'workspace', fallback: false});
    if (path === '/skills/ws.portal.reply/prompt-history') return json(route, {current_template: promptSkill().executor.params.template, current_sha256: (restored ? 'b' : 'a').repeat(64), entries: [{version_id: 'prompt-v3', version_number: 3, system_id: 'system-portal', system_name: 'Document review', node_id: 'reply', created_at: '2026-10-21T14:45:00Z', created_by: 'Author', template: 'Published: {details}', template_sha256: 'b'.repeat(64), matches_current: restored}]});
    if (path === '/skills/ws.portal.reply/prompt-history/restore' && method === 'POST') {
      restored = true; restoreAttempts += 1;
      if (options.restoreUnknown && restoreAttempts === 1) return json(route, {detail: 'Response lost after acceptance'}, 503);
      return json(route, {...promptSkill(), published_contracts_unchanged: true});
    }
    if (path === '/models/test-targets') {
      expect(url.searchParams.get('provider')).toBe('openai'); expect(url.searchParams.get('model')).toBe('gpt-mini');
      return json(route, { can_test: admin, targets: options.targets === false ? [] : [TARGET], blockers: [] });
    }
    if (path === '/models/test' && method === 'POST') return json(route, { id: RUN.id, system_id: RUN.system_id, status: 'pending' }, 201);
    if (path === '/runs/run-portal') return json(route, RUN);
    if (/^\/models\/providers\/[^/]+\/test$/.test(path)) return json(route, { provider: provider(path.split('/')[3]), test_kind: 'connection', generation_verified: false });
    if (path === '/models/credentials/typesafe' && method === 'PUT') return json(route, { saved: true });
    if (path === '/models/credentials/azure_openai' && method === 'PUT') { metadata = { ...metadata, ...body }; return json(route, { saved: true }); }
    if (['/capabilities', '/systems', '/runs', '/skills'].includes(path) && method === 'GET') return json(route, { [path.slice(1)]: [] });
    unexpected.push(`${method} ${path}`); return json(route, { detail: `Unhandled fixture ${method} ${path}` }, 501);
  });
  await page.addInitScript(({locale, dark}) => { localStorage.setItem('agentium_token', 'Bearer local-portal'); localStorage.setItem('agentium_workspace_slug', 'portal-contract'); localStorage.setItem('agentium_locale', locale); if (dark) localStorage.setItem('agentium_theme', 'dark'); }, {locale: options.locale ?? 'en', dark: options.dark ?? false});
  return { calls, unexpected };
}

test('provider-aware catalogue, saved Azure metadata, explicit connection check and Skill link', async ({ page }, info) => {
  const h = await setup(page); await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/resources?lens=govern');
  const app = page.locator('app-resources-page'); await expect(app.getByText('gpt-mini', { exact: true }).first()).toBeVisible();
  await expect(app.getByText('embed-only', { exact: true })).toHaveCount(0);
  await expect(app.getByText('Configured in Systems:')).toBeVisible();
  await expect(app.getByRole('link', { name: 'Document review · summary' })).toHaveAttribute('href', /\/systems\/system-portal\/flow/);
  const row = app.locator('li').filter({ hasText: 'gpt-mini' }).first();
  const skill = row.getByRole('link', { name: 'Use in a Skill', exact: true });
  await expect(skill).toHaveAttribute('href', /provider=openai/); await expect(skill).toHaveAttribute('href', /model=gpt-mini/); await expect(skill).toHaveAttribute('href', /modelWorkspace=workspace-portal/);
  const skillUrl = new URL((await skill.getAttribute('href'))!, page.url());
  expect(skillUrl.pathname).toBe('/skills'); expect(skillUrl.searchParams.get('lens')).toBe('govern');
  await page.screenshot({ path: info.outputPath('catalog-desktop.png'), fullPage: true });
  await row.getByRole('button', { name: 'Test in a System', exact: true }).click();
  const invocationUrl = new URL((await app.getByRole('link', { name: 'Open invocation inv-port' }).getAttribute('href'))!, page.url());
  expect(invocationUrl.pathname).toBe('/runs/run-portal/invocations/inv-portal'); expect(invocationUrl.searchParams.get('lens')).toBe('govern');
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
  expect(new URL((await panel.getByRole('link', { name: 'Use in a Skill' }).getAttribute('href'))!, page.url()).pathname).toBe('/skills');
  await expect(panel.getByRole('button', { name: 'Run test' })).toHaveCount(0); expect(h.calls.some((c) => c.path === '/models/test')).toBe(false);
});

test('catalogue read failure is distinct from empty and disabled portal links explain the gate', async ({ page }) => {
  await setup(page, { modelError: true, enabled: false }); await page.goto('/resources?facet=providers');
  const app = page.locator('app-resources-page'); await expect(app.getByRole('alert').filter({ hasText: 'Catalog unavailable' })).toBeVisible();
  await expect(app.getByText(/LLM Portal is not enabled in this workspace/)).toBeVisible();
  await expect(app.getByRole('heading', { name: 'No models available' })).toHaveCount(0);
  await expect(app.getByRole('button', { name: 'Save routing' })).toHaveCount(0);
});

async function selectComparison(page: Page) {
  const panel = page.locator('app-decision-comparison');
  await panel.getByRole('button', {name: 'Choose a decision', exact: true}).click();
  await panel.getByRole('combobox', {name: 'Reference decision'}).selectOption('decision-reference');
  await expect(panel.getByRole('combobox', {name: 'Candidate 1'})).toHaveValue('openai:gpt-mini');
  await panel.getByRole('combobox', {name: 'Candidate 2'}).selectOption('ollama:llama');
  await panel.getByRole('checkbox').check();
  return panel;
}

test('agent comparison shows frozen context, measured evidence and no tool execution at desktop and mobile widths', async ({page}, info) => {
  const h = await setup(page); await page.setViewportSize({width: 1440, height: 1000}); await page.goto('/resources');
  const panel = await selectComparison(page);
  await panel.getByRole('button', {name: 'Compare decisions', exact: true}).click();
  await expect(panel.getByText('Read the delivery receipt', {exact: true})).toBeVisible();
  await expect(panel).toContainText('business quality has not been qualified');
  await expect(panel).toContainText('3 retained observations');
  await expect(panel.locator('article')).toHaveCount(2);
  await expect(panel.locator('article').first()).toContainText('$0.0030');
  await expect(panel.locator('article').last()).not.toContainText('$0');
  const post = h.calls.find(call => call.path === '/models/decision-comparisons');
  expect(post?.body.invocation_id).toBe('decision-reference'); expect(post?.body.expected_input_sha256).toBe('c'.repeat(64));
  expect(post?.body).not.toHaveProperty('input_ref'); expect(post?.body).not.toHaveProperty('visible_skills');
  expect(h.calls.filter(call => call.method === 'POST' && !['/audit', '/auth/validate'].includes(call.path)).map(call => call.path)).toEqual(['/models/decision-comparisons']);
  await panel.screenshot({path: info.outputPath('agent-comparison-desktop.png')});
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
  await panel.screenshot({path: info.outputPath('agent-comparison-mobile.png')}); expect(h.unexpected).toEqual([]);
});

test('unknown comparison response retries the same idempotency claim', async ({page}) => {
  const h = await setup(page, {comparisonUnknown: true}); await page.goto('/resources');
  const panel = await selectComparison(page);
  await panel.getByRole('button', {name: 'Compare decisions', exact: true}).click();
  await expect(panel.getByRole('alert')).toContainText('Retry with the same selection');
  await panel.getByRole('button', {name: 'Compare decisions', exact: true}).click();
  await expect(panel.getByText('Read the delivery receipt', {exact: true})).toBeVisible();
  const requests = h.calls.filter(call => call.path === '/models/decision-comparisons');
  expect(requests).toHaveLength(2); expect(requests[0].body).toEqual(requests[1].body);
});

test('published instructions show before and after, safely retry a lost restore response and preserve model', async ({page}, info) => {
  const h = await setup(page, {restoreUnknown: true}); await page.goto('/skills/ws.portal.reply');
  const panel = page.locator('app-skill-prompt-history');
  await panel.getByRole('button', {name: 'View versions'}).click();
  await expect(panel.getByText('Current: {details}', {exact: true})).toBeVisible();
  await expect(panel.getByText('Published: {details}', {exact: true})).toBeVisible();
  await expect(panel).toContainText('The model stays unchanged');
  await panel.screenshot({path: info.outputPath('prompt-history-desktop.png')});
  await panel.getByRole('button', {name: 'Restore these instructions'}).click();
  await expect(panel.getByRole('alert')).toContainText('Could not load or restore');
  await panel.getByRole('button', {name: 'Restore these instructions'}).click();
  await expect(panel.getByText('Matches current instructions', {exact: true})).toBeVisible();
  await expect(panel.getByRole('button', {name: 'Restore these instructions'})).toHaveCount(0);
  await expect(page.locator('app-skill-execution')).toContainText('gpt-mini');
  const requests = h.calls.filter(call => call.path.endsWith('/prompt-history/restore'));
  expect(requests).toHaveLength(2); expect(requests[0].body).toEqual(requests[1].body);
  expect(h.calls.some(call => call.method === 'PATCH' || call.path.includes('/publish'))).toBe(false);
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
  await panel.screenshot({path: info.outputPath('prompt-history-mobile.png')}); expect(h.unexpected).toEqual([]);
});

test('agent comparison and instruction history keep French labels and localized dates in dark chrome', async ({page}, info) => {
  await setup(page, {locale: 'fr', dark: true}); await page.goto('/resources');
  const panel = page.locator('app-decision-comparison');
  await panel.getByRole('button', {name: 'Choisir une décision', exact: true}).click();
  await panel.getByRole('combobox', {name: 'Décision de référence'}).selectOption('decision-reference');
  await expect(panel.getByRole('combobox', {name: 'Décision de référence'})).toContainText('22/10/2026');
  await panel.getByRole('combobox', {name: 'Candidat 2'}).selectOption('ollama:llama');
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button', {name: 'Comparer les décisions', exact: true}).click();
  await expect(panel).toContainText('qualité métier n’est pas encore qualifiée');
  await expect(panel.locator('article').first()).toContainText('Entrée de cette exécution');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await panel.screenshot({path: info.outputPath('agent-comparison-fr-dark.png')});
  await page.goto('/skills/ws.portal.reply');
  const history = page.locator('app-skill-prompt-history');
  await history.getByRole('button', {name: 'Consulter les versions'}).click();
  await expect(history.getByRole('combobox', {name: 'Version publiée'})).toContainText('21/10/2026');
  await expect(history).toContainText('Seules les consignes du catalogue seront remplacées');
  await history.screenshot({path: info.outputPath('prompt-history-fr-dark.png')});
});

for (const locale of ['en', 'fr'] as const) {
  test(`TypeSafe is configured as a typed evaluator, without entering chat routing (${locale})`, async ({ page }, info) => {
    const h = await setup(page, {locale, dark: locale === 'fr'});
    await page.setViewportSize({width: 1280, height: 900});
    await page.goto('/resources?facet=providers');
    const app = page.locator('app-resources-page');
    const card = app.locator('section').filter({has: page.getByRole('heading', {name:'TypeSafe', exact:true})});
    await expect(card).toBeVisible();
    await expect(card).toContainText(locale === 'fr' ? 'Moteur de décisions typées' : 'Typed decision engine');
    await expect(card).toContainText(locale === 'fr' ? 'plafonds budgétaires' : 'Blocking budget limits');
    await expect(card.locator('a[href="https://console.typesafe.ai/keys"]')).toHaveAttribute('rel', 'noopener noreferrer');
    const key = card.locator('input[type=password]');
    await expect(key).toHaveValue('');
    await key.fill('synthetic-typesafe-key');
    await card.getByRole('button', {name: locale === 'fr' ? 'Enregistrer la connexion' : 'Save connection', exact:true}).click();
    await expect.poll(() => h.calls.filter(c => c.path === '/models/credentials/typesafe' && c.method === 'PUT').length).toBe(1);
    expect(h.calls.find(c => c.path === '/models/credentials/typesafe' && c.method === 'PUT')?.body).toEqual({api_key:'synthetic-typesafe-key'});
    await expect(key).toHaveValue('');
    expect(await app.locator('select').evaluateAll(selects => selects.some(select => Array.from((select as HTMLSelectElement).options).some(option => option.value === 'typesafe')))).toBe(false);
    await card.screenshot({path:info.outputPath('typesafe-provider-'+locale+'.png')});
    await page.setViewportSize({width:390, height:844});
    expect(await card.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(h.calls.some(c => c.path === '/models/test')).toBe(false);
    expect(h.unexpected).toEqual([]);
  });
}
