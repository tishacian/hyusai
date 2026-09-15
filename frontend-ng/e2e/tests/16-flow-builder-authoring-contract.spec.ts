import { expect, test, type Request, type Route, type TestInfo } from '@playwright/test';

/**
 * P0.3 / P1 — local, fully mocked Flow Builder authoring contract.
 *
 * This test is deliberately local-only. Every `/api/v1/**` request is
 * intercepted and an undeclared endpoint receives a 501, so running this spec
 * can never mutate a shared environment. The fixture System is cloned through
 * the API before the Angular application is opened; every later authoring step
 * is driven through the real UI.
 */

const WORKSPACE_SLUG = 'flow-contract';
const WORKSPACE_ID = 'workspace-flow-contract';
const SYSTEM_ID = 'system-flow-contract-clone';
const RUN_ID = 'run-flow-contract';
const WORKBENCH_RUN_ID = 'run-flow-contract-workbench';
const TOKEN = 'Bearer local-flow-contract-token';

const INITIAL_HASH = '1'.repeat(64);
const EDITED_HASH = '2'.repeat(64);
const PUBLISHED_VERSION_ID = 'version-published-v2';
const INITIAL_LABEL = 'Contract source';
const EDITED_LABEL = 'Contract source edited';

type JsonRecord = Record<string, unknown>;

interface ContractCall {
  step: 'clone' | 'preview' | 'save' | 'execute' | 'restore';
  method: string;
  path: string;
  authorization: string | null;
  workspace: string | null;
  body: JsonRecord;
}

const initialFlow = {
  source: 'flow',
  schema_version: 3,
  io_mode: 'strict',
  variable_namespaces: ['case'],
  nodes: [
    {
      id: 'source.contract',
      type: 'source',
      kind: 'source',
      label: INITIAL_LABEL,
      position: { x: 120, y: 180 },
      inputs: [],
      outputs: [{ name: 'payload', schema: 'object' }],
      config: {
        ingress: { kind: 'manual' },
        input_schema: {
          type: 'object',
          properties: {
            query: { type: 'string' },
            ticket: { type: 'string' },
          },
          required: ['query'],
          additionalProperties: false,
        },
      },
      data: { description: 'Local authoring contract input' },
    },
    {
      id: 'sink.contract',
      type: 'sink',
      kind: 'sink',
      label: 'Contract result',
      position: { x: 520, y: 180 },
      inputs: [{ name: 'result', schema: 'object' }],
      outputs: [],
      config: {},
      data: { description: 'Local authoring contract output' },
    },
  ],
  edges: [
    {
      from: 'source.contract',
      to: 'sink.contract',
      kind: 'data',
      from_port: 'payload',
      to_port: 'result',
    },
  ],
};

const workspace = {
  id: WORKSPACE_ID,
  name: 'Flow contract workspace',
  slug: WORKSPACE_SLUG,
  role: 'admin',
  role_template: 'workspace_admin',
  member_count: 1,
  created_at: '2026-08-06T08:00:00Z',
  is_active: true,
  mode: 'builder',
  settings: { features: { flow_publication_v1: true } },
  effective_features: { flow_publication_v1: true },
  app_entitlements: [],
};

function clone<T>(value: T): T {
  return structuredClone(value);
}

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function requestBody(request: Request): JsonRecord {
  const value = request.postDataJSON() as unknown;
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function sourceLabel(flow: unknown): string | null {
  if (!flow || typeof flow !== 'object' || Array.isArray(flow)) return null;
  const nodes = (flow as JsonRecord)['nodes'];
  if (!Array.isArray(nodes)) return null;
  const source = nodes.find((node) => (
    !!node
    && typeof node === 'object'
    && !Array.isArray(node)
    && (node as JsonRecord)['id'] === 'source.contract'
  ));
  return source && typeof source === 'object' && !Array.isArray(source)
    ? String((source as JsonRecord)['label'] ?? '')
    : null;
}

function localOnly(testInfo: TestInfo): boolean {
  const configured = testInfo.project.use.baseURL;
  if (typeof configured !== 'string') return false;
  try {
    const url = new URL(configured);
    return url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

function assertOrdered(events: readonly string[], expected: readonly string[]): void {
  let previous = -1;
  for (const event of expected) {
    const index = events.indexOf(event, previous + 1);
    expect(index, `missing or out-of-order event ${event}\n${events.join('\n')}`).toBeGreaterThan(previous);
    previous = index;
  }
}

test.use({ serviceWorkers: 'block', video: 'off' });

for (const editable of [true, false]) {
  test(`Skill execution settings — ${editable ? 'edit and reload preserve provider and prompt' : 'read-only catalog hides editing'}`, async ({ page }, testInfo) => {
    test.skip(
      !localOnly(testInfo),
      'This mocked authoring contract is local-only; set E2E_BASE_URL=http://localhost:4200.',
    );

    await page.setViewportSize({ width: 1600, height: 1000 });
    const slug = `ws.${WORKSPACE_ID}.summary_contract`;
    const initialPrompt = 'Summarise {document_text}. Cite the supplied excerpt IDs.';
    const editedPrompt = 'Summarise {document_text}. Cite excerpt IDs and report missing facts.';
    let executor = {
      kind: 'prompt_template',
      params: { provider: 'azure', template: initialPrompt },
    };
    let skillReads = 0;
    let catalogReads = 0;
    const patches: JsonRecord[] = [];
    const unexpectedRequests: string[] = [];
    const inputSchema = {
      type: 'object',
      properties: { document_text: { type: 'string' } },
      required: ['document_text'],
      additionalProperties: false,
    };
    const outputSchema = {
      type: 'object',
      properties: { completion: { type: 'string' } },
      required: ['completion'],
    };
    const publishedPrompt = 'Summarise {document_text}. Preserve the original wording.';
    const skillFlow = {
      source: 'flow', schema_version: 3, io_mode: 'strict',
      nodes: [
        {
          id: 'source.excerpts', type: 'source', kind: 'source', label: 'Transaction excerpts',
          position: { x: 80, y: 180 }, inputs: [],
          outputs: [{ name: 'document_text', schema: 'string' }],
          config: { ingress: { kind: 'manual' }, input_schema: inputSchema },
        },
        {
          id: 'summary', type: 'skill', kind: 'task', label: 'Document summary contract',
          position: { x: 380, y: 180 }, runtime_ref: `skill:${slug}`,
          inputs: [{ name: 'document_text', schema: 'string' }],
          outputs: [{ name: 'completion', schema: 'string' }],
          config: {
            skill_id: 'skill-summary-contract', skill_slug: slug,
            inputs_map: { document_text: { node_id: 'source.excerpts', path: ['document_text'] } },
          },
        },
        {
          id: 'output.summary', type: 'sink', kind: 'sink', label: 'Factual summary',
          position: { x: 680, y: 180 }, inputs: [{ name: 'completion', schema: 'string' }], outputs: [],
          config: { inputs_map: { completion: { node_id: 'summary', path: ['completion'] } }, output_schema: outputSchema },
        },
      ],
      edges: [
        { from: 'source.excerpts', to: 'summary', kind: 'data', from_port: 'document_text', to_port: 'document_text' },
        { from: 'summary', to: 'output.summary', kind: 'data', from_port: 'completion', to_port: 'completion' },
      ],
    };
    const system = {
      id: SYSTEM_ID, workspace_id: WORKSPACE_ID, name: 'Summary execution contract', status: 'active',
      objective: 'Inspect current and published summary settings.',
      skill_ids: ['skill-summary-contract'], flow_definition: skillFlow, flow_sha256: INITIAL_HASH,
    };
    const skill = () => ({
      id: 'skill-summary-contract',
      slug,
      version: '1',
      name: 'Document summary contract',
      description: 'Summarise synthetic excerpts for a human reviewer.',
      type: 'llm',
      category: 'LLM',
      input_schema: inputSchema,
      output_schema: outputSchema,
      execution: { mode: 'sync', timeout_ms: 30000 },
      pricing: {},
      metrics: {},
      certification_level: 'basic',
      is_seeded: false,
      workspace_scope: 'workspace',
      runtime_status: 'bound',
      // Workspace authoring stores the provider inside the executor; the
      // top-level catalog field is deliberately null, as on the real API.
      provider: null,
      executor: clone(executor),
    });

    await page.route('**/*', async (route) => {
      const host = new URL(route.request().url()).hostname;
      if (host === 'localhost' || host === '127.0.0.1') return route.fallback();
      return route.abort('blockedbyclient');
    });
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      const path = decodeURIComponent(new URL(request.url()).pathname.replace(/^\/api\/v1/, ''));
      const method = request.method();
      if (path === '/auth/validate' && method === 'POST') {
        return json(route, { valid: true, user_id: 'user-flow-contract', email: 'flow.contract@example.test', role: 'admin' });
      }
      if (path === '/auth/workspaces' && method === 'GET') return json(route, [workspace]);
      if (path === '/auth/me' && method === 'GET') {
        return json(route, {
          id: 'user-flow-contract', username: 'flow.contract', email: 'flow.contract@example.test',
          role: 'admin', is_active: true, mfa_enabled: false, workspaces: [workspace],
        });
      }
      if (path === '/help-content' && method === 'GET') {
        return json(route, { version: 'local', personas: [], languages: [], items: [] });
      }
      if (path === '/audit' && method === 'POST') return json(route, { id: 'audit-local-only' }, 201);
      if (path === '/telemetry/live' && method === 'GET') {
        return json(route, { throughput_rpm: null, latency_ms: null, yield_pct: null, runs_count: 0 });
      }
      if (path === '/models' && method === 'GET') {
        return json(route, { models: ['openai', 'ollama'].map((provider) => ({
          id: `${provider}:test-model`, model: 'test-model', name: 'test-model', provider,
          configured: true, discovered: true, runtime_available: true, compatibility: 'text_generation', status: 'active',
        })) });
      }
      if (path === '/models/resolve' && method === 'GET') {
        const provider = new URL(request.url()).searchParams.get('provider');
        return json(route, {
          provider: provider === 'azure' ? 'openai' : provider, model: provider === 'azure' ? 'gpt-4o-mini' : 'test-model',
          credential_source: 'env', model_source: provider === 'azure' ? 'legacy_default' : 'global', fallback: false,
          ...(provider === 'azure' ? { legacy_provider: 'azure' } : {}),
        });
      }
      if (path === '/skills/executors' && method === 'GET') {
        catalogReads += 1;
        return json(route, {
          editable,
          categories: ['LLM'],
          executors: [{
            kind: 'prompt_template',
            summary: 'Send a fixed prompt template to a verified model provider.',
            params_schema: {
              type: 'object', additionalProperties: false, required: ['provider', 'template'],
              properties: {
                provider: { enum: ['azure', 'openai', 'azure_openai', 'ollama', 'workspace'] },
                model: { type: 'string', maxLength: 256 },
                template: { type: 'string', minLength: 1, maxLength: 8000 },
              },
            },
          }],
        });
      }
      if (path === '/skills' && method === 'GET') return json(route, { skills: [skill()] });
      if (path === `/skills/${slug}` && method === 'GET') {
        skillReads += 1;
        return json(route, skill());
      }
      if (path === `/skills/${slug}` && method === 'PATCH') {
        if (!editable) return json(route, { detail: { code: 'WORKSPACE_PERMISSION_DENIED' } }, 403);
        expect(request.headers()['authorization']).toBe(TOKEN);
        expect(request.headers()['x-workspace-slug']).toBe(WORKSPACE_SLUG);
        const body = requestBody(request);
        patches.push(clone(body));
        expect(body['executor']).toEqual({ kind: 'prompt_template', params: { provider: 'ollama', template: editedPrompt } });
        expect(body['input_schema']).toEqual(inputSchema);
        expect(body['output_schema']).toEqual(outputSchema);
        executor = clone(body['executor'] as typeof executor);
        return json(route, { ...skill(), published_bindings: [] });
      }
      if (path === `/systems/${SYSTEM_ID}` && method === 'GET') return json(route, system);
      if (path === `/systems/${SYSTEM_ID}/flow-state` && method === 'GET') {
        return json(route, {
          system_id: SYSTEM_ID, status: 'active',
          draft: {
            revision: 3, flow_sha256: INITIAL_HASH, flow_definition: skillFlow,
            base_published_version_id: PUBLISHED_VERSION_ID,
          },
          published: {
            version_id: PUBLISHED_VERSION_ID, version_number: 2, flow_sha256: INITIAL_HASH,
            flow_definition: skillFlow, execution_contract_ready: true,
            execution_contract: {
              schema_version: 1, contract_sha256: '3'.repeat(64), runtime_mode: 'dag_strict',
              nodes: {
                summary: {
                  skill_id: 'skill-summary-contract', skill_slug: slug, skill_version: '1',
                  input_schema: inputSchema, output_schema: outputSchema,
                  executor: { kind: 'prompt_template', params: { provider: 'azure', template: publishedPrompt } },
                },
              },
            },
          },
        });
      }
      if (path === `/systems/${SYSTEM_ID}/flow-manifest` && method === 'GET') {
        return json(route, {
          system_id: SYSTEM_ID, system_name: system.name, flow_sha256: INITIAL_HASH,
          schema_version: 3, source: 'flow_definition', runtime_mode: 'dag_strict', operational_sync: true,
          unit_catalog: [],
          summary: { nodes: 3, edges: 2, operational_units: 1, runtime_refs: 1, skill_units: 1, editable_parameters: 0 },
        });
      }
      if (path === `/systems/${SYSTEM_ID}/validate-flow` && method === 'POST') {
        return json(route, {
          flow_sha256: INITIAL_HASH, analyzer_version: 'local-playwright-contract-v1',
          runtime_mode: 'dag_strict', valid: true, issues: [],
        });
      }
      if (method === 'GET' && ['/capabilities', '/systems', '/runs'].includes(path)) {
        return json(route, { [path.slice(1)]: [] });
      }
      unexpectedRequests.push(`${method} ${path}`);
      return json(route, { detail: `Unhandled local mock endpoint: ${method} ${path}` }, 501);
    });
    await page.addInitScript(({ token, workspaceSlug }) => {
      localStorage.setItem('agentium_token', token);
      localStorage.setItem('agentium_workspace_slug', workspaceSlug);
      localStorage.setItem('agentium_locale', 'en');
    }, { token: TOKEN, workspaceSlug: WORKSPACE_SLUG });

    await page.goto(`/skills/${slug}`);
    await expect(page.getByRole('heading', { name: 'Document summary contract', exact: true })).toBeVisible();
    const settings = page.locator('app-skill-execution').first();
    await expect(settings).toContainText('Model provider');
    await expect(settings).toContainText('azure');
    await expect(settings).toContainText('Public OpenAI');
    await expect(settings.getByRole('link', { name: /View connections and test/ })).toHaveAttribute('target', '_blank');
    await expect(settings).toContainText('Prompt');
    await expect(settings).toContainText(initialPrompt);
    await expect.poll(() => catalogReads).toBeGreaterThan(0);
    const edit = page.getByRole('button', { name: 'Edit execution', exact: true });
    if (!editable) {
      await expect(edit).toHaveCount(0);
      await page.goto(`/skills?create=llm&provider=openai&model=test-model&modelWorkspace=${WORKSPACE_ID}`);
      await expect(page.getByRole('heading', { name: 'Skill registry', exact: true })).toBeVisible();
      await expect(page.getByRole('dialog', { name: 'New skill', exact: true })).toHaveCount(0);
      expect(patches).toHaveLength(0);
      expect(unexpectedRequests).toEqual([]);
      return;
    }

    await expect(edit).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('skill-execution-detail.png'), fullPage: true });
    await edit.click();
    const dialog = page.getByRole('dialog', { name: 'Edit skill', exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('tab', { name: /Execution/ })).toHaveAttribute('aria-selected', 'true');
    const provider = dialog.getByRole('combobox', { name: 'Model provider', exact: true });
    const prompt = dialog.getByRole('textbox', { name: /^Prompt/ });
    await expect(provider).toHaveValue('azure');
    await expect(prompt).toHaveValue(initialPrompt);
    await page.screenshot({ path: testInfo.outputPath('skill-execution-editor.png'), fullPage: true });
    await provider.selectOption('ollama');
    await prompt.fill(editedPrompt);
    await dialog.getByRole('tab', { name: /Review/ }).click();
    await dialog.getByRole('tab', { name: /Execution/ }).click();
    await expect(provider).toHaveValue('ollama');
    await expect(prompt).toHaveValue(editedPrompt);
    await dialog.getByRole('tab', { name: /Review/ }).click();
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dialog).toBeHidden();
    expect(patches).toHaveLength(1);
    await expect(settings).toContainText('ollama');
    await expect(settings).toContainText(editedPrompt);

    const readsBeforeReload = skillReads;
    await page.reload();
    await expect.poll(() => skillReads).toBeGreaterThan(readsBeforeReload);
    await expect(settings).toContainText('ollama');
    await expect(settings).toContainText(editedPrompt);
    await edit.click();
    await expect(provider).toHaveValue('ollama');
    await expect(prompt).toHaveValue(editedPrompt);
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();

    await page.goto(`/systems/${SYSTEM_ID}/flow`);
    await expect(page.getByRole('heading', { name: system.name })).toBeVisible();
    await page.locator('app-flow-node').filter({ hasText: 'Document summary contract' }).click();
    const inspector = page.locator('app-flow-inspector');
    const current = inspector.locator('section').filter({ hasText: 'Current Skill definition' });
    await expect(current.locator('app-skill-execution')).toContainText('ollama');
    await expect(current.locator('app-skill-execution')).toContainText(editedPrompt);
    await expect(current).not.toContainText(publishedPrompt);
    await page.screenshot({ path: testInfo.outputPath('skill-flow-current.png'), fullPage: true });
    const published = inspector.locator('details').filter({ hasText: 'Published version configuration' });
    await expect(published.locator('app-skill-execution')).toBeHidden();
    await published.locator('summary').click();
    await expect(published.locator('app-skill-execution')).toContainText('azure');
    await expect(published.locator('app-skill-execution')).toContainText(publishedPrompt);
    await expect(published).not.toContainText(editedPrompt);
    const definitionLink = current.getByRole('link', { name: 'Open current definition', exact: true });
    const destination = new URL(await definitionLink.getAttribute('href') ?? '', page.url());
    expect(decodeURIComponent(destination.pathname)).toBe(`/skills/${slug}`);
    expect(destination.searchParams.get('facet')).toBe('overview');
    await page.screenshot({ path: testInfo.outputPath('skill-flow-execution.png'), fullPage: true });
    await page.goto(`/skills?create=llm&provider=openai&model=test-model&modelWorkspace=${WORKSPACE_ID}`);
    const modelDraft = page.getByRole('dialog', { name: 'New skill', exact: true });
    await expect(modelDraft).toBeVisible();
    await modelDraft.getByRole('tab', { name: /Execution/ }).click();
    await expect(modelDraft.getByRole('combobox', { name: 'Model provider', exact: true })).toHaveValue('openai');
    await expect(modelDraft.getByRole('combobox', { name: /^Model ·/ })).toHaveValue('test-model');
    await expect(modelDraft.getByRole('textbox', { name: /^Prompt/ })).toHaveValue('{question}');
    await modelDraft.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect(patches).toHaveLength(1);
    expect(unexpectedRequests).toEqual([]);
  });
}

test('clone → edit → validate → save → input → execute → result → restore draft', async ({ page }, testInfo) => {
  test.skip(
    !localOnly(testInfo),
    'This mocked authoring contract is local-only; set E2E_BASE_URL=http://localhost:4200.',
  );

  let draftRevision = 7;
  let draftHash = INITIAL_HASH;
  let draftFlow: JsonRecord = clone(initialFlow) as JsonRecord;
  let restored = false;
  let stateReads = 0;
  const events: string[] = [];
  const mutations: ContractCall[] = [];
  const unexpectedRequests: string[] = [];
  const blockedExternalRequests: string[] = [];

  const system = (): JsonRecord => ({
    id: SYSTEM_ID,
    workspace_id: WORKSPACE_ID,
    name: 'Flow authoring contract clone',
    objective: 'Exercise the complete local authoring lifecycle',
    status: 'active',
    execution_mode: 'event_driven_automation',
    flow_definition: clone(draftFlow),
    flow_sha256: draftHash,
    created_at: '2026-08-06T08:00:00Z',
    updated_at: '2026-08-06T08:00:00Z',
  });

  const flowState = (): JsonRecord => ({
    system_id: SYSTEM_ID,
    status: 'active',
    draft: {
      revision: draftRevision,
      flow_sha256: draftHash,
      flow_definition: clone(draftFlow),
      base_published_version_id: PUBLISHED_VERSION_ID,
      updated_by: 'flow.contract@example.test',
      updated_at: `2026-08-06T08:0${Math.min(draftRevision, 9)}:00Z`,
    },
    published: {
      version_id: PUBLISHED_VERSION_ID,
      version_number: 2,
      flow_sha256: INITIAL_HASH,
      flow_definition: clone(initialFlow),
      release_kind: 'standard',
      execution_contract_ready: true,
      execution_contract: {
        schema_version: 1,
        contract_sha256: 'contract-published-v2',
        runtime_mode: 'dag_strict',
      },
      published_by: 'flow.contract@example.test',
      published_at: '2026-08-06T07:00:00Z',
    },
  });

  const recordMutation = (
    step: ContractCall['step'],
    request: Request,
    path: string,
    body: JsonRecord,
  ): void => {
    mutations.push({
      step,
      method: request.method(),
      path,
      authorization: request.headers()['authorization'] ?? null,
      workspace: request.headers()['x-workspace-slug'] ?? null,
      body: clone(body),
    });
    events.push(`api:${step}`);
  };

  // Keep the contract hermetic even when the development index references
  // remote fonts. API mocks registered below take precedence; every other
  // non-local request is aborted before it can leave the browser process.
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') {
      return route.fallback();
    }
    expect(request.headers()['authorization']).toBeUndefined();
    expect(request.headers()['x-workspace-slug']).toBeUndefined();
    blockedExternalRequests.push(`${request.method()} ${url.origin}${url.pathname}`);
    return route.abort('blockedbyclient');
  });

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const method = request.method();

    if (path === '/auth/validate' && method === 'POST') {
      return json(route, {
        valid: true,
        user_id: 'user-flow-contract',
        email: 'flow.contract@example.test',
        role: 'admin',
      });
    }
    if (path === '/auth/workspaces' && method === 'GET') {
      return json(route, [workspace]);
    }
    if (path === '/auth/me' && method === 'GET') {
      return json(route, {
        id: 'user-flow-contract',
        username: 'flow.contract',
        email: 'flow.contract@example.test',
        role: 'admin',
        is_active: true,
        mfa_enabled: false,
        first_name: 'Flow',
        last_name: 'Contract',
        phone: null,
        company: 'Local test',
        job_title: 'Playwright',
        workspaces: [workspace],
      });
    }
    if (path === '/help-content' && method === 'GET') {
      return json(route, { version: 'local', personas: [], languages: [], items: [] });
    }
    if (path === '/audit' && method === 'POST') {
      return json(route, { id: 'audit-local-only' }, 201);
    }
    if (path === '/telemetry/live' && method === 'GET') {
      return json(route, {
        throughput_rpm: null,
        latency_ms: null,
        yield_pct: null,
        runs_count: 0,
      });
    }
    if (path === '/skills' && method === 'GET') {
      return json(route, { skills: [] });
    }
    // Read-only shell catalogs loaded in the background by shared chrome.
    if (path === '/capabilities' && method === 'GET') {
      return json(route, { capabilities: [] });
    }
    if (path === '/runs' && method === 'GET') {
      return json(route, { runs: [] });
    }

    if (path === '/systems' && method === 'POST') {
      const body = requestBody(request);
      recordMutation('clone', request, path, body);
      expect(body).toMatchObject({
        name: 'Flow authoring contract clone',
        objective: 'Exercise the complete local authoring lifecycle',
        status: 'active',
      });
      expect(sourceLabel(body['flow_definition'])).toBe(INITIAL_LABEL);
      return json(route, system(), 201);
    }
    if (path === '/systems' && method === 'GET') {
      return json(route, { systems: [system()] });
    }
    if (path === `/systems/${SYSTEM_ID}` && method === 'GET') {
      return json(route, system());
    }
    if (path === `/systems/${SYSTEM_ID}/flow-state` && method === 'GET') {
      stateReads += 1;
      events.push(`api:hydrate:${restored ? 'restored' : 'initial'}`);
      return json(route, flowState());
    }
    if (path === `/systems/${SYSTEM_ID}/flow-manifest` && method === 'GET') {
      return json(route, {
        system_id: SYSTEM_ID,
        system_name: 'Flow authoring contract clone',
        flow_sha256: draftHash,
        schema_version: 3,
        source: 'flow_definition',
        runtime_mode: 'dag_strict',
        operational_sync: true,
        unit_catalog: [],
        summary: {
          nodes: 2,
          edges: 1,
          operational_units: 0,
          runtime_refs: 0,
          skill_units: 0,
          editable_parameters: 0,
        },
      });
    }
    if (path === `/systems/${SYSTEM_ID}/validate-flow` && method === 'POST') {
      const body = requestBody(request);
      const flow = body['flow_definition'];
      const label = sourceLabel(flow);
      const phase = restored
        ? 'restored'
        : label === EDITED_LABEL
          ? 'edited'
          : 'initial';
      events.push(`api:validate:${phase}`);
      return json(route, {
        flow_sha256: label === EDITED_LABEL ? EDITED_HASH : INITIAL_HASH,
        analyzer_version: 'local-playwright-contract-v1',
        runtime_mode: 'dag_strict',
        valid: true,
        issues: [],
      });
    }
    if (path === `/systems/${SYSTEM_ID}/flow-draft` && method === 'PUT') {
      const body = requestBody(request);
      recordMutation('save', request, path, body);
      expect(body['expected_revision']).toBe(7);
      expect(sourceLabel(body['flow_definition'])).toBe(EDITED_LABEL);
      draftRevision = 8;
      draftHash = EDITED_HASH;
      draftFlow = clone(body['flow_definition'] as JsonRecord);
      return json(route, {
        system_id: SYSTEM_ID,
        no_op: false,
        revision: draftRevision,
        flow_sha256: draftHash,
        flow_definition: clone(draftFlow),
        base_published_version_id: PUBLISHED_VERSION_ID,
        updated_by: 'flow.contract@example.test',
        updated_at: '2026-08-06T08:08:00Z',
      });
    }
    if (path === `/systems/${SYSTEM_ID}/flow-workbench/preview-runs` && method === 'POST') {
      const body = requestBody(request);
      recordMutation('preview', request, path, body);
      expect(sourceLabel(body['flow_definition'])).toBe(EDITED_LABEL);
      expect(body['expected_flow_sha256']).toBe(EDITED_HASH);
      expect(body['acknowledge_real_side_effects']).toBe(true);
      return json(route, {
        id: WORKBENCH_RUN_ID,
        system_id: SYSTEM_ID,
        status: 'pending',
        execution_surface: 'builder_preview',
        flow_sha256: EDITED_HASH,
        source_flow_sha256: EDITED_HASH,
        runtime_mode: 'dag_strict',
        input_ref: {
          ...(body['input_ref'] as JsonRecord),
          execution: {
            execution_surface: 'builder_preview',
            flow_sha256: EDITED_HASH,
            source_flow_sha256: EDITED_HASH,
            runtime_mode: 'dag_strict',
          },
        },
        output_ref: {},
        checkpoints: [],
      }, 201);
    }
    if (path === `/systems/${SYSTEM_ID}/flow-draft/test-runs` && method === 'POST') {
      const body = requestBody(request);
      recordMutation('execute', request, path, body);
      return json(route, {
        id: RUN_ID,
        system_id: SYSTEM_ID,
        status: 'running',
        trigger: 'manual',
        input_ref: clone(body['input_ref']),
        output_ref: {},
        checkpoints: [],
        started_at: '2026-08-06T08:09:00Z',
      }, 201);
    }
    if (path === `/runs/${RUN_ID}/stream` && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: [
          'event: run_start',
          `data: ${JSON.stringify({ run_id: RUN_ID, status: 'running' })}`,
          '',
          'event: run_end',
          `data: ${JSON.stringify({ run_id: RUN_ID, status: 'completed' })}`,
          '',
          'event: close',
          `data: ${JSON.stringify({ run_id: RUN_ID })}`,
          '',
          '',
        ].join('\n'),
      });
    }
    if (path === `/runs/${WORKBENCH_RUN_ID}` && method === 'GET') {
      return json(route, {
        id: WORKBENCH_RUN_ID,
        system_id: SYSTEM_ID,
        status: 'completed',
        trigger: 'builder_preview',
        input_ref: {
          query: 'Preview this unsaved edit',
          ticket: 'INC-LOCAL',
        },
        output_ref: { answer: 'Unsaved preview result', local_snapshot: true },
        checkpoints: [],
        started_at: '2026-08-06T08:07:00Z',
        completed_at: '2026-08-06T08:07:01Z',
      });
    }
    if (path === `/runs/${RUN_ID}` && method === 'GET') {
      if (!events.includes('api:result')) events.push('api:result');
      return json(route, {
        id: RUN_ID,
        system_id: SYSTEM_ID,
        status: 'completed',
        trigger: 'manual',
        input_ref: { case: { id: 'INC-42' }, priority: 'high' },
        output_ref: { answer: 'Contract result: 42', accepted_revision: 8 },
        checkpoints: [
          {
            kind: 'run_end',
            t: '2026-08-06T08:09:01Z',
            status: 'completed',
          },
        ],
        started_at: '2026-08-06T08:09:00Z',
        completed_at: '2026-08-06T08:09:01Z',
      });
    }
    if (path === `/systems/${SYSTEM_ID}/versions` && method === 'GET') {
      return json(route, {
        total: 1,
        limit: 25,
        offset: 0,
        versions: [
          {
            id: PUBLISHED_VERSION_ID,
            system_id: SYSTEM_ID,
            version_number: 2,
            flow_sha256: INITIAL_HASH,
            release_kind: 'publish',
            draft_revision: 2,
            message: 'Published baseline',
            rolled_back_from_id: null,
            created_at: '2026-08-06T07:00:00Z',
            created_by: 'flow.contract@example.test',
            node_count: 2,
            edge_count: 1,
          },
        ],
      });
    }
    if (path === `/systems/${SYSTEM_ID}/versions/2` && method === 'GET') {
      return json(route, {
        id: PUBLISHED_VERSION_ID,
        system_id: SYSTEM_ID,
        workspace_id: WORKSPACE_ID,
        version_number: 2,
        flow_sha256: INITIAL_HASH,
        release_kind: 'publish',
        draft_revision: 2,
        message: 'Published baseline',
        rolled_back_from_id: null,
        created_at: '2026-08-06T07:00:00Z',
        created_by: 'flow.contract@example.test',
        flow_definition: clone(initialFlow),
        execution_contract: {
          schema_version: 1,
          contract_sha256: 'contract-published-v2',
          runtime_mode: 'dag_strict',
        },
      });
    }
    if (path === `/systems/${SYSTEM_ID}/flow-diff` && method === 'GET') {
      expect(url.searchParams.get('base')).toBe('version:2');
      expect(url.searchParams.get('target')).toBe('draft');
      events.push('api:version-preview');
      return json(route, {
        base: { identity: 'version:2', flow_sha256: INITIAL_HASH },
        target: { identity: 'draft:8', flow_sha256: EDITED_HASH },
        summary: { breaking: 0, behavioral: 0, presentation: 1, total: 1 },
        changes: [
          {
            category: 'presentation',
            impact: 'presentation',
            subject: 'source.contract',
            path: 'nodes/source.contract/presentation',
            description: 'Source label changed.',
          },
        ],
      });
    }
    if (
      path === `/systems/${SYSTEM_ID}/flow-draft/restore/${PUBLISHED_VERSION_ID}`
      && method === 'POST'
    ) {
      const body = requestBody(request);
      recordMutation('restore', request, path, body);
      restored = true;
      draftRevision = 9;
      draftHash = INITIAL_HASH;
      draftFlow = clone(initialFlow) as JsonRecord;
      return json(route, {
        system_id: SYSTEM_ID,
        no_op: false,
        revision: draftRevision,
        flow_sha256: draftHash,
        flow_definition: clone(draftFlow),
        base_published_version_id: PUBLISHED_VERSION_ID,
        updated_by: 'flow.contract@example.test',
        updated_at: '2026-08-06T08:10:00Z',
      });
    }

    unexpectedRequests.push(`${method} ${path}${url.search}`);
    return json(route, { detail: `Unhandled local mock endpoint: ${method} ${path}` }, 501);
  });

  await page.addInitScript(({ token, workspaceSlug }) => {
    localStorage.setItem('agentium_token', token);
    localStorage.setItem('agentium_workspace_slug', workspaceSlug);
    // The accessible names below come from the EN dictionary. Pin the locale so
    // the contract does not depend on the runner's navigator.language.
    localStorage.setItem('agentium_locale', 'en');
  }, { token: TOKEN, workspaceSlug: WORKSPACE_SLUG });

  // Establish the local origin without booting Angular, then clone the fixture
  // through the same browser/API boundary used by the application.
  await page.goto('/assets/nawa/itsd-use-cases.json');
  const cloneResponse = await page.evaluate(async ({ systemId, flow, token, workspaceSlug }) => {
    localStorage.setItem('agentium_token', token);
    localStorage.setItem('agentium_workspace_slug', workspaceSlug);
    const response = await fetch('/api/v1/systems', {
      method: 'POST',
      headers: {
        Authorization: token,
        'X-Workspace-Slug': workspaceSlug,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        id: systemId,
        name: 'Flow authoring contract clone',
        objective: 'Exercise the complete local authoring lifecycle',
        status: 'active',
        flow_definition: flow,
      }),
    });
    return { status: response.status, body: await response.json() };
  }, {
    systemId: SYSTEM_ID,
    flow: initialFlow,
    token: TOKEN,
    workspaceSlug: WORKSPACE_SLUG,
  });
  expect(cloneResponse).toMatchObject({ status: 201, body: { id: SYSTEM_ID } });

  await page.goto(`/systems/${SYSTEM_ID}/flow`);
  await expect(page.getByRole('heading', { name: 'Flow authoring contract clone' })).toBeVisible();
  await expect(page.getByText('Server draft r7')).toBeVisible();
  await expect(page.locator('app-flow-node').filter({ hasText: INITIAL_LABEL })).toBeVisible();
  await expect.poll(() => events.includes('api:validate:initial')).toBe(true);

  // The keyboard-first Outline is a projection of the same graph, not a
  // separate authoring mode. Prove that it opens, exposes every node and keeps
  // focus plus selection coherent before returning to the canvas lifecycle.
  const outlineToggle = page.locator('#flow-builder-view-outline');
  await outlineToggle.click();
  await expect(outlineToggle).toHaveAttribute('aria-pressed', 'true');
  const outline = page.locator('#flow-builder-outline');
  await expect(outline).toBeVisible();
  const outlineNodes = outline.locator('.flow-outline__select');
  await expect(outlineNodes).toHaveCount(2);
  await outlineNodes.first().focus();
  await outlineNodes.first().press('ArrowDown');
  await expect(outlineNodes.nth(1)).toBeFocused();
  await expect(outlineNodes.nth(1)).toHaveAttribute('aria-current', 'true');
  await page.locator('#flow-builder-view-canvas').click();
  await expect(page.locator('app-flow-node').filter({ hasText: INITIAL_LABEL })).toBeVisible();

  // Authoring is the default surface; running, debugging and previewing live
  // one disclosure away. Everything below stays reachable in two clicks.
  const operate = page.getByRole('button', { name: 'Operate', exact: true });
  await expect(operate).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByRole('button', { name: 'Execute on backend' })).toBeHidden();
  await operate.click();
  await expect(operate).toHaveAttribute('aria-expanded', 'true');

  // The autosave hold spans the Workbench panel's lifetime only, so the panel
  // must be open before the edit. Editing first lets the 1.2s autosave debounce
  // persist the draft while no hold exists yet, which the panel cannot undo and
  // which would add a `save` mutation ahead of the preview.
  await page.getByRole('button', { name: 'Toggle local Flow workbench' }).click();
  const workbench = page.getByRole('region', { name: 'Local Flow workbench', exact: true });
  await expect(workbench).toBeVisible();

  // One status line carries the three warnings; the operator detail is one
  // click away and must never be the thing the reader has to decode first.
  await expect(workbench).toContainText('Nothing is saved or published');
  const detail = workbench.getByRole('button', { name: 'What this run touches' });
  await expect(workbench.getByText('Autosave stays paused')).toBeHidden();
  await detail.click();
  await expect(workbench.getByText('Autosave stays paused')).toBeVisible();
  await detail.click();

  await page.locator('app-flow-node').filter({ hasText: INITIAL_LABEL }).click();
  const inspector = page.locator('app-flow-inspector');
  await expect(inspector).toBeVisible();
  await inspector.getByRole('textbox', { name: 'Label' }).fill(EDITED_LABEL);
  events.push('ui:edit');
  await expect(page.locator('app-flow-node').filter({ hasText: EDITED_LABEL })).toBeVisible();

  // The in-builder Workbench must execute the exact dirty snapshot without
  // saving the draft or moving the published pointer first.
  await workbench.getByRole('textbox', { name: 'Additional input_ref (JSON)' }).fill(
    JSON.stringify({ ticket: 'INC-LOCAL' }),
  );
  await workbench.getByRole('textbox', { name: 'Message' }).fill('Preview this unsaved edit');
  await workbench.getByRole('checkbox', {
    name: /I understand this preview invokes real Skills/i,
  }).check();
  events.push('ui:preview');
  await workbench.getByRole('button', { name: 'Send preview' }).click();
  await expect(workbench).toContainText('Unsaved preview result');
  await expect(workbench).toContainText('local_snapshot');
  events.push('ui:preview-result');
  // The workbench is open, so the pill names the hold instead of the generic
  // "Unsaved" — same fact, said out loud. The revision and hash below are what
  // actually pin "the preview ran on the dirty snapshot and saved nothing".
  const statePill = page.locator('app-flow-toolbar .ck-flow-toolbar__state');
  await expect(statePill).toHaveClass(/is-hold/);
  await expect(statePill).toContainText('Autosave paused');
  expect(draftRevision).toBe(7);
  expect(draftHash).toBe(INITIAL_HASH);

  // Validate lives one disclosure away: the author bar keeps only the
  // constant edit loop, everything occasional sits under "More".
  await page.getByRole('button', { name: 'More actions' }).click();
  const validateButton = page.getByRole('button', { name: 'Validate current flow' });
  await expect(validateButton).toBeEnabled();
  await validateButton.click();
  await expect.poll(() => events.includes('api:validate:edited')).toBe(true);
  await page.getByRole('button', { name: 'More actions' }).click();

  const saveButton = page.getByRole('button', { name: 'Save flow' });
  await expect(saveButton).toBeEnabled();
  await saveButton.click();
  // The revision label now shares its element with the Draft ck-help trigger,
  // so `exact` no longer matches the element text; the anchored regex keeps r8
  // from matching an r80.
  await expect(page.locator('.flow-builder__publication-boundary')).toContainText(
    /Server draft r8\b/,
  );
  await expect(page.locator('.flow-builder__publication-boundary')).toContainText('Published v2');
  await expect(page.locator('app-flow-toolbar .ck-flow-toolbar__state')).toContainText('Saved');

  const executeButton = page.getByRole('button', { name: 'Execute on backend' });
  await expect(executeButton).toBeEnabled();
  await executeButton.click();
  const inputDialog = page.getByRole('dialog', { name: 'Run input' });
  await expect(inputDialog).toBeVisible();
  await inputDialog.getByRole('textbox', { name: 'JSON object' }).fill(
    JSON.stringify({ case: { id: 'INC-42' }, priority: 'high' }, null, 2),
  );
  events.push('ui:input');
  await inputDialog.getByRole('button', { name: 'Start draft test-run' }).click();

  const terminal = page.getByLabel('Execution terminal');
  await expect(terminal).toContainText('Contract result: 42');
  await expect(terminal).toContainText('Done');

  await page.getByRole('button', { name: 'Versions' }).click();
  await expect(page.getByText('Flow history')).toBeVisible();
  const versionTwo = page.locator('app-flow-versions li').filter({ hasText: 'v2' });
  await expect(versionTwo).toBeVisible();
  await expect(versionTwo).toContainText('PUBLISHED');
  events.push('ui:restore');
  await versionTwo.getByRole('button', { name: /Restore this version/i }).click();
  const restoreDialog = page.getByRole('dialog', { name: 'Confirm rollback' });
  await expect(restoreDialog).toContainText('published pointer');
  await expect(restoreDialog).toContainText('Exact preview ready');
  await expect(restoreDialog).toContainText('1 presentation');
  const restoreButton = restoreDialog.getByRole('button', { name: 'Restore draft' });
  await expect(restoreButton).toBeEnabled();
  await restoreButton.click();

  await expect(page.locator('.flow-builder__publication-boundary')).toContainText(
    /Server draft r9\b/,
  );
  await expect(page.locator('.flow-builder__publication-boundary')).toContainText('Published v2');
  await expect(page.locator('app-flow-node').filter({ hasText: INITIAL_LABEL })).toBeVisible();
  await expect(page.locator('app-flow-node').filter({ hasText: EDITED_LABEL })).toHaveCount(0);
  await expect.poll(() => events.includes('api:validate:restored')).toBe(true);

  expect(stateReads).toBe(2);
  expect(unexpectedRequests).toEqual([]);
  expect(blockedExternalRequests.every((request) => (
    request.startsWith('GET https://fonts.googleapis.com/')
    || request.startsWith('GET https://fonts.gstatic.com/')
  ))).toBe(true);
  expect(mutations.map((call) => call.step)).toEqual([
    'clone',
    'preview',
    'save',
    'execute',
    'restore',
  ]);
  expect(mutations.map((call) => `${call.method} ${call.path}`)).toEqual([
    'POST /systems',
    `POST /systems/${SYSTEM_ID}/flow-workbench/preview-runs`,
    `PUT /systems/${SYSTEM_ID}/flow-draft`,
    `POST /systems/${SYSTEM_ID}/flow-draft/test-runs`,
    `POST /systems/${SYSTEM_ID}/flow-draft/restore/${PUBLISHED_VERSION_ID}`,
  ]);
  for (const mutation of mutations) {
    expect(mutation.authorization, mutation.step).toBe(TOKEN);
    expect(mutation.workspace, mutation.step).toBe(WORKSPACE_SLUG);
  }

  expect(mutations[1].body).toMatchObject({
    acknowledge_real_side_effects: true,
    expected_flow_sha256: EDITED_HASH,
    ingress_id: 'source.contract',
    kind: 'manual',
    input_ref: {
      query: 'Preview this unsaved edit',
      ticket: 'INC-LOCAL',
    },
  });
  expect(sourceLabel(mutations[1].body['flow_definition'])).toBe(EDITED_LABEL);
  expect(mutations[2].body).toMatchObject({ expected_revision: 7 });
  expect(sourceLabel(mutations[2].body['flow_definition'])).toBe(EDITED_LABEL);
  expect(mutations[3].body).toEqual({
    input_ref: { case: { id: 'INC-42' }, priority: 'high' },
    expected_draft_revision: 8,
    expected_flow_sha256: EDITED_HASH,
    ingress_id: 'source.contract',
    kind: 'manual',
  });
  expect(mutations[4].body).toEqual({ expected_revision: 8 });

  assertOrdered(events, [
    'api:clone',
    'api:hydrate:initial',
    'api:validate:initial',
    'ui:edit',
    'ui:preview',
    'api:validate:edited',
    'api:preview',
    'ui:preview-result',
    'api:save',
    'ui:input',
    'api:execute',
    'api:result',
    'ui:restore',
    'api:version-preview',
    'api:restore',
    'api:hydrate:restored',
    'api:validate:restored',
  ]);
});
