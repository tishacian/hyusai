import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const systemId = 'agent-controls-qa';
const hash = 'a'.repeat(64);
const workspace = { id: 'agent-controls-qa', slug: 'agent-controls-qa', name: 'Agent controls QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };

async function setup(page: Page, locale: 'fr' | 'en') {
  let graph: any = {
    version: 3, runtime_mode: 'dag_overlay', nodes: [
      { id: 'source', kind: 'source', type: 'source', label: 'Prepared case', position: { x: 40, y: 80 }, config: {}, outputs: [{ name: 'out', schema: 'object' }] },
      {
        id: 'agent', kind: 'agent_loop', type: 'agent_loop', label: 'Investigate the claim', position: { x: 390, y: 80 },
        config: {
          goal: { objective: 'Find evidence for a claim and propose a resolution', done_when: ['Evidence complete'], status: 'active' },
          skill_allowlist: ['retired_tool'], model: 'old_provider:retired_model', budget: { max_turns: 6 }, confidence_floor: 0.7,
          privilege_tier: 'act_with_approval', on_budget: 'ask_human',
          inputs_map: { risk_score: { node_id: 'source', path: ['score'] }, case_id: 'run.case_id', model: 'run.model', _internal: 'run._internal' },
          decision_context: { keys: ['removed_input'], max_bytes: 8192 },
        }, inputs: [{ name: 'in', schema: 'object' }], outputs: [{ name: 'out', schema: 'object' }],
      },
      { id: 'output', kind: 'sink', type: 'sink', label: 'Resolution', position: { x: 740, y: 80 }, config: {}, inputs: [{ name: 'in', schema: 'object' }] },
      { id: 'user-draft', kind: 'task', type: 'skill', label: 'Unfinished user preparation', position: { x: 390, y: 400 }, config: { skill_slug: 'sql_transform_v1', params: { sql: '-- keep my unfinished draft' } }, inputs: [], outputs: [] },
    ], edges: [
      { from: 'source', from_port: 'out', to: 'agent', to_port: 'in', kind: 'data' },
      { from: 'agent', from_port: 'out', to: 'output', to_port: 'in', kind: 'data' },
    ],
  };
  const published = structuredClone(graph), writes: Array<{ path: string; body: any }> = [];
  let revision = 1;
  const json = (route: Route, body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  const system = () => ({ id: systemId, workspace_id: workspace.id, name: 'Claims assistant', status: 'active', flow_definition: published, flow_sha256: hash });
  const state = () => ({ system_id: systemId, status: 'active', draft: { revision, base_published_version_id: 'agent-v1', flow_sha256: hash, flow_definition: graph }, published: { version_id: 'agent-v1', version_number: 1, flow_sha256: hash, flow_definition: published, execution_contract_ready: true } });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-agent-controls-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light');
  }, { slug: workspace.slug, locale });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa-human', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'qa-human', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON() });
    if (path === '/systems') return json(route, { systems: [system()] });
    if (path === `/systems/${systemId}`) return json(route, system());
    if (path === `/systems/${systemId}/flow-state`) return json(route, state());
    if (path === `/systems/${systemId}/flow-draft` && request.method() === 'PUT') {
      graph = request.postDataJSON().flow_definition; revision++;
      return json(route, { ...state().draft, system_id: systemId, no_op: false });
    }
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_overlay', flow_sha256: hash });
    if (path === '/skills') return json(route, { skills: [
      { slug: 'read_order', name: 'Read order', description: 'Check delivery and payment evidence', runtime_status: 'bound' },
      { slug: 'read_policy', name: 'Read refund policy', description: 'Find the applicable refund conditions', runtime_status: 'bound' },
      { slug: 'payment_stub', name: 'Payment integration', description: 'Integration not connected yet', runtime_status: 'stub' },
    ].map(skill => ({ ...skill, id: skill.slug, version: '1', type: 'workflow', category: 'Retrieval', input_schema: { type: 'object', properties: {} }, output_schema: { type: 'object', properties: {} }, visibility: { visible: true, reason: 'visible', capabilities: [] } })) });
    if (path === '/models') return json(route, { models: [
      { provider: 'openai', model: 'gpt-5-mini', configured: true, runtime_available: true, compatibility: 'text_generation', status: 'configured' },
      { provider: 'openai', model: 'embedding', configured: true, runtime_available: true, compatibility: 'other', status: 'configured' },
      { provider: 'ollama', model: 'unconfigured', configured: false, runtime_available: false, compatibility: 'text_generation', status: 'unconfigured' },
    ] });
    if (path === '/connectors') return json(route, { can_configure: true, connectors: [] });
    if (path === '/documents/collections') return json(route, { collections: [] });
    return json(route, {});
  });
  return { writes, graph: () => graph, agent: () => graph.nodes.find((node: any) => node.id === 'agent') };
}

test.describe('Agent authoring controls — local API fixtures', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const locale of ['fr', 'en'] as const) test(`${locale}: author tools, model and authorized evidence without replacing the user draft`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const api = await setup(page, locale), original = structuredClone(api.graph());
    await page.goto(`/systems/${systemId}/flow?lens=build`);
    await page.locator('app-flow-node').filter({ hasText: 'Investigate the claim' }).click();
    const inspector = page.locator('app-flow-inspector'), model = inspector.getByTestId('agent-decision-model');
    await expect(model).toBeDisabled();
    expect(api.writes.filter(write => write.path.endsWith('/flow-draft'))).toHaveLength(0);
    await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
    await page.locator('app-flow-node').filter({ hasText: 'Investigate the claim' }).click();
    await expect(model).toHaveValue('old_provider:retired_model');
    await expect(model.locator('option')).toHaveCount(3);
    await expect(inspector.getByRole('checkbox', { name: /Retired tool/ })).toBeChecked();
    await expect(inspector.getByRole('checkbox', { name: /Payment integration/ })).toBeDisabled();
    await expect(inspector.getByRole('checkbox', { name: /Model|Internal/ })).toHaveCount(0);
    const identifiers = inspector.locator('details').filter({ hasText: locale === 'fr' ? 'Identifiants techniques' : 'Technical identifiers' });
    await expect(identifiers).not.toHaveAttribute('open', '');
    await model.selectOption('openai:gpt-5-mini');
    await inspector.getByRole('spinbutton', { name: locale === 'fr' ? 'Tours max.' : 'Max turns', exact: true }).fill('8');
    await inspector.getByRole('spinbutton', { name: locale === 'fr' ? 'Seuil de coût déclaré (optionnel)' : 'Reported cost threshold (optional)', exact: true }).fill('0.5');
    await inspector.getByRole('spinbutton', { name: locale === 'fr' ? 'Délai en minutes (optionnel)' : 'Deadline in minutes (optional)', exact: true }).fill('2');
    await inspector.getByRole('checkbox', { name: /Retired tool/ }).click();
    await inspector.getByRole('checkbox', { name: /Read order Check delivery/ }).check();
    await inspector.getByRole('checkbox', { name: /Removed input/ }).click();
    await inspector.getByRole('checkbox', { name: /Risk score Prepared case/ }).check();
    await inspector.getByRole('spinbutton', { name: locale === 'fr' ? 'Taille maximale du contexte (octets)' : 'Maximum context size (bytes)' }).fill('4096');
    await page.keyboard.press('Tab');
    await expect.poll(() => api.agent().config.decision_context).toEqual({ keys: ['risk_score'], max_bytes: 4096 });
    await expect.poll(() => api.agent().config.model).toBe('openai:gpt-5-mini');
    expect(api.agent().config.skill_allowlist).toEqual(['read_order']);
    expect(api.agent().config.budget).toEqual({ max_turns: 8, max_cost: 0.5, deadline_ms: 120000 });
    expect(api.graph().nodes.find((node: any) => node.id === 'user-draft')).toEqual(original.nodes.find((node: any) => node.id === 'user-draft'));
    expect(api.graph().edges).toEqual(original.edges);
    expect(api.agent().config.goal).toEqual(original.nodes[1].config.goal);
    expect(api.agent().config.inputs_map).toEqual(original.nodes[1].config.inputs_map);
    expect(api.writes.some(write => /\/publish$|\/node-runs$|\/executions$/.test(write.path))).toBe(false);
    await model.scrollIntoViewIfNeeded();
    await inspector.screenshot({ path: info.outputPath(`agent-controls-${locale}.png`) });
    expect(await inspector.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await page.reload();
    await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
    await page.locator('app-flow-node').filter({ hasText: 'Investigate the claim' }).click();
    await expect(model).toHaveValue('openai:gpt-5-mini');
    await expect(inspector.getByRole('checkbox', { name: /Risk score Prepared case/ })).toBeChecked();
  });
});
