import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off' });
// This fixture is the catalog's llm_label_dataset_v1 descriptor. The manifest
// derives editable fields from it exactly as the backend does.
const descriptor = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/llm-label-dataset.json'), 'utf8'));
const skill = { ...descriptor, id: 'skill-label', category: 'Data', runtime_status: 'bound' };
const workspace = { id: 'label-qa', slug: 'label-qa', name: 'Label QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const systemId = 'label-system';
const nodeId = 'label.tickets';
const hash = '4'.repeat(64);

async function setup(page: Page, theme: string, locale: string) {
  const defaults = Object.fromEntries(Object.entries(descriptor.input_schema.properties)
    .filter(([, value]: [string, any]) => 'default' in value)
    .map(([key, value]: [string, any]) => [key, value.default]));
  let graph: any = {
    schema_version: 3, source: 'flow', io_mode: 'overlay',
    nodes: [
      { id: 'source', type: 'source', kind: 'source', label: 'Tickets', position: { x: 40, y: 80 }, config: {} },
      { id: nodeId, type: 'skill', kind: 'task', label: 'Label tickets', position: { x: 360, y: 80 }, config: { skill_slug: skill.slug, skill_id: skill.id, runtime_ref: `skill:${skill.slug}`, params: defaults } },
      { id: 'sink', type: 'sink', kind: 'sink', label: 'Labeled dataset', position: { x: 680, y: 80 }, config: {} },
    ],
    edges: [{ id: 'source-label', from: 'source', to: nodeId, kind: 'data' }, { id: 'label-sink', from: nodeId, to: 'sink', kind: 'data' }],
  };
  let revision = 1;
  const drafts: any[] = [];
  const system = () => ({ id: systemId, workspace_id: workspace.id, name: 'Ticket labeling', status: 'active', flow_definition: graph, flow_sha256: hash, objective: 'Label ticket topics' });
  const state = () => ({ system_id: systemId, status: 'active', draft: { revision, base_published_version_id: 'published-v1', flow_sha256: hash, flow_definition: graph }, published: { version_id: 'published-v1', version_number: 1, flow_sha256: hash, flow_definition: graph, execution_contract_ready: true } });
  const manifest = () => ({
    system_id: systemId, system_name: system().name, flow_sha256: hash, schema_version: 3, source: 'flow_definition', runtime_mode: 'dag_overlay', operational_sync: true,
    unit_catalog: [{
      id: nodeId, kind: 'task', type: 'skill', label: 'Label tickets', skill_slug: skill.slug,
      runtime_ref: `skill:${skill.slug}`, runtime_status: 'bound', operational: true,
      implementation: { input_schema: descriptor.input_schema, output_schema: descriptor.output_schema },
      editable_fields: Object.entries(descriptor.input_schema.properties).map(([key, value]: [string, any]) => ({ key, source: 'skill.input_schema', type: value.type, required: false, description: value.description, enum: value.enum })),
    }],
    summary: { nodes: 3, edges: 2, operational_units: 1, runtime_refs: 1, skill_units: 1, editable_parameters: 15 },
  });
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ theme, locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer label-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', theme);
    localStorage.setItem('agentium_locale', locale);
  }, { theme, locale, slug: workspace.slug });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/systems') return json(route, { systems: [system()] });
    if (path === `/systems/${systemId}`) return json(route, system());
    if (path === `/systems/${systemId}/flow-state`) return json(route, state());
    if (path === `/systems/${systemId}/flow-manifest`) return json(route, manifest());
    if (path === `/systems/${systemId}/flow-draft` && request.method() === 'PUT') {
      graph = request.postDataJSON().flow_definition;
      drafts.push(structuredClone(graph)); revision++;
      return json(route, { ...state().draft, system_id: systemId, no_op: false });
    }
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_overlay', flow_sha256: hash });
    if (path === '/skills') return json(route, { skills: [skill] });
    if (path === `/skills/${skill.slug}`) return json(route, skill);
    if (path === '/documents/collections') return json(route, { collections: [] });
    if (path === '/connectors') return json(route, { can_configure: true, connectors: [] });
    if (path === '/datasets') return json(route, { datasets: [], feature: { enabled: true } });
    if (path === '/capabilities') return json(route, { capabilities: [] });
    return json(route, {});
  });
  return { params: () => drafts.at(-1)?.nodes.find((node: any) => node.id === nodeId)?.config?.params ?? {} };
}

test.describe('LLM dataset labeling · graph-owned form', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });

  for (const [theme, locale] of [['dark', 'fr'], ['light', 'en']] as const) {
    test(`${theme}/${locale}: configures and reloads labels, explicit prices and resume settings`, async ({ page }, info) => {
      await page.setViewportSize({ width: 1440, height: 1000 });
      const api = await setup(page, theme, locale);
      await page.goto(`/systems/${systemId}/flow?lens=build`);
      await page.locator('app-flow-node').filter({ hasText: 'Label tickets' }).click();
      const form = page.locator('app-manifest-fields');
      await expect(form.locator('#mf-text_columns')).toBeVisible();
      await expect(form).toContainText(locale === 'fr' ? 'Colonnes de texte' : 'Text columns');
      await expect(form).toContainText(locale === 'fr' ? 'Classes autorisées' : 'Allowed classes');
      await expect(form).toContainText(locale === 'fr' ? 'USD par million de tokens d’entrée' : 'USD per million input tokens');
      await expect(form.locator('#mf-input_cost_per_million')).toHaveValue('');
      await expect(form.locator('#mf-output_cost_per_million')).toHaveValue('');
      await expect(form.locator('#mf-input_cost_per_million')).toHaveAttribute('aria-invalid', 'true');
      await expect(form.locator('textarea#mf-instruction')).toHaveCount(1);
      await expect(form.locator('#mf-provider, #mf-model')).toHaveCount(0);
      const values: Record<string, string> = {
        sources: '[{"dataset_id":"tickets-source"}]', text_columns: '["subject", "message"]',
        labels: '["billing", "technical", "other"]', label_column: 'topic',
        instruction: 'Classify the ticket by topic.', output_name: 'Tickets labeled',
        batch_size: '5', max_rows: '200', max_tokens: '150000', max_output_tokens: '1024',
        max_cost_usd: '2.5', input_cost_per_million: '0', output_cost_per_million: '1.25',
        timeout_s: '120', resume_job_id: 'label-operation-previous',
      };
      for (const [key, value] of Object.entries(values)) {
        await form.locator(`#mf-${key}`).fill(value);
        await form.locator(`#mf-${key}`).press('Tab');
      }
      await expect(form.locator('#mf-input_cost_per_million')).toHaveAttribute('aria-invalid', 'false');
      await expect(form).toContainText(locale === 'fr' ? 'Identifiant de l’étiquetage à reprendre' : 'Labeling operation ID to resume');
      await expect.poll(() => api.params()).toEqual({
        sources: [{ dataset_id: 'tickets-source' }], text_columns: ['subject', 'message'],
        labels: ['billing', 'technical', 'other'], label_column: 'topic',
        instruction: 'Classify the ticket by topic.', output_name: 'Tickets labeled',
        batch_size: 5, max_rows: 200, max_tokens: 150000, max_output_tokens: 1024,
        max_cost_usd: 2.5, input_cost_per_million: 0, output_cost_per_million: 1.25,
        timeout_s: 120, resume_job_id: 'label-operation-previous',
      });
      await page.screenshot({ path: info.outputPath(`label-form-${theme}-${locale}.png`) });
      await page.reload();
      await page.locator('app-flow-node').filter({ hasText: 'Label tickets' }).click();
      await expect(form.locator('#mf-input_cost_per_million')).toHaveValue('0');
      await expect(form.locator('#mf-output_cost_per_million')).toHaveValue('1.25');
      await expect(form.locator('#mf-resume_job_id')).toHaveValue('label-operation-previous');
      await expect(form.locator('#mf-instruction')).toHaveValue('Classify the ticket by topic.');
      expect(JSON.parse(await form.locator('#mf-labels').inputValue())).toEqual(['billing', 'technical', 'other']);
    });
  }
});
