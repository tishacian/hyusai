import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, ɵAfterRenderManager, ɵChangeDetectionScheduler, ɵEffectScheduler } from '@angular/core';
import { ActivatedRoute, DefaultUrlSerializer, Router, convertToParamMap } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { EN_DICT } from '@app/core/i18n.dict';
import { ProductTelemetryService } from '@app/core/product-telemetry.service';
import { SettingsService } from '@app/core/settings.service';
import { WorkspaceService, type WorkspaceRequestScope, type WorkspaceContextTransition } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { ResourcesPageComponent } from './resources-page.component';
import type { ModelCatalogEntry } from '@app/core/model-catalog';

const openai: ModelCatalogEntry = { provider: 'openai', model: 'gpt-mini', status: 'active', configured: true, discovered: true, runtime_available: true, compatibility: 'text_generation' };
const ollama = { ...openai, provider: 'ollama', model: 'llama' };
const target = { system_id: 'system-a', system_name: 'Review', node_id: 'summary', node_label: 'Summarise', skill_slug: 'summary', skill_name: 'Summary', provider: 'openai', model: 'gpt-mini', input_schema: { type: 'object', properties: { prompt: { type: 'string' }, count: { type: 'integer' } }, required: ['prompt'] }, input_defaults: { prompt: 'Supplied excerpt', extra: 'preserve' }, expected_flow_sha256: 'a'.repeat(64) };
class WorkspaceStub {
  epoch = 1;
  enabled = true;
  readonly currentSlug = () => `workspace-${this.epoch}`;
  readonly current = () => ({ id: this.currentSlug() });
  readonly contextEpoch = () => this.epoch;
  readonly modelPortalEnabled = () => this.enabled;
  readonly isDemoSafeMode = () => false;
  private resetters = new Set<(t: WorkspaceContextTransition) => void>();
  captureRequestScope(): WorkspaceRequestScope { return { workspaceSlug: this.currentSlug(), workspaceId: this.currentSlug(), epoch: this.epoch }; }
  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean { return scope.epoch === this.epoch; }
  registerContextReset(reset: (t: WorkspaceContextTransition) => void) { this.resetters.add(reset); return () => this.resetters.delete(reset); }
  switch() {
    const t = { previousSlug: this.currentSlug(), nextSlug: 'workspace-2', previousEpoch: this.epoch, nextEpoch: this.epoch + 1 };
    this.resetters.forEach((reset) => reset(t)); this.epoch++;
  }
}
function harness(skillsSurfaceUrl = '/skills') {
  const serializer = new DefaultUrlSerializer();
  const contextQuery = skillsSurfaceUrl.includes('?') ? skillsSurfaceUrl.slice(skillsSurfaceUrl.indexOf('?')) : '';
  const workspace = new WorkspaceStub();
  const calls: Array<{ method: string; path: string; body?: unknown }> = [];
  const responses = new Map<string, unknown>([
    ['/models', { models: [openai, ollama] }], ['/models/providers', { providers: [] }],
    ['/models/config', { can_configure: true, cloud_credentials: [{ key: 'azure_openai', api_key_set: true, endpoint: 'https://example.test', deployment: 'summary', api_version: '2024-10-21' }] }],
    ['/models/routing', { default_provider: 'openai', default_model: 'gpt-mini', fallback_chain: [] }],
    ['/models/distribution', { by_model: [] }], ['/models/nodes', { nodes: [] }],
    ['/models/test-targets', { can_test: true, targets: [target] }],
  ]);
  const pending = new Map<string, Subject<unknown>>();
  const failures = new Set<string>();
  const api = {
    get: (path: string) => { calls.push({ method: 'GET', path }); return pending.get(path) ?? (failures.has(path) ? throwError(() => ({ error: { detail: { message: 'Read failed' } } })) : of(responses.get(path) ?? {})); },
    put: (path: string, body: unknown) => {
      calls.push({ method: 'PUT', path, body });
      if (path === '/models/setup') {
        const setup = body as { provider: string; model: string; fallback_chain: string[] };
        return of({
          routing: {
            default_provider: setup.provider,
            default_model: setup.model,
            fallback_chain: setup.fallback_chain,
          },
          readiness: { ready: true, provider: setup.provider, model: setup.model },
          provider: { key: setup.provider },
        });
      }
      return of({});
    },
    post: (path: string, body: unknown) => { calls.push({ method: 'POST', path, body }); return pending.get(path) ?? of({ id: 'run-1', status: 'pending', system_id: 'system-a' }); },
    delete: (path: string) => { calls.push({ method: 'DELETE', path }); return of({}); },
  };
  const canonical = { getRun: () => of({ id: 'run-1', status: 'completed' }) };
  const injector = Injector.create({ providers: [ResourcesPageComponent,
    { provide: ApiService, useValue: api }, { provide: CanonicalApiService, useValue: canonical },
    { provide: WorkspaceService, useValue: workspace }, { provide: I18nService, useValue: { t: (key: string) => EN_DICT[key as keyof typeof EN_DICT] ?? key } },
    { provide: ToastrService, useValue: { success() {}, error() {}, info() {} } }, { provide: Router, useValue: { url: '/resources', navigate: async () => true } },
    { provide: SettingsService, useValue: { adoptValidatedModelSelection() {} } },
    { provide: ProductTelemetryService, useValue: { recordOnce() {}, recordOccurrence() {} } },
    { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap({}) } } },
    { provide: ZoomContextService, useValue: {
      surfaceUrlTree: () => serializer.parse(skillsSurfaceUrl),
      objectUrlTree: (_t: string, id: string, opts: { runId: string }) => serializer.parse(`/runs/${opts.runId}/invocations/${id}${contextQuery}`),
    } },
    { provide: ɵAfterRenderManager, useValue: { impl: { register() {}, unregister() {} } } },
    { provide: ɵChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
    { provide: ɵEffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
  ] });
  const component = injector.get(ResourcesPageComponent);
  return { component, workspace, responses, pending, failures, calls, canonical, close: () => { component.ngOnDestroy(); injector.destroy(); } };
}

test('routing load failure leaves no invented draft and blocks saving', () => {
  const h = harness(); try {
    h.failures.add('/models/routing'); h.component.refresh();
    assert.equal(h.component.routingError(), 'Read failed');
    assert.deepEqual(h.component.routingDraft, { provider: '', model: '', fallback: [] });
    assert.equal(h.component.canSaveRouting(), false); h.component.saveRouting();
    assert.equal(h.calls.some((c) => c.method === 'PUT'), false);
  } finally { h.close(); }
});
test('permissions fail closed for configuration, credentials, serving and lifecycle', () => {
  const h = harness(); try {
    h.responses.set('/models/config', { can_configure: false }); h.component.refresh();
    h.component.saveRouting(); h.component.clearCredential('openai');
    h.component.testConnection('openai'); h.component.attachServingNode(); h.component.detachServingNode({ key: 'node' });
    h.component.startInstance({ key: 'node' }, { id: 'instance' }); h.component.deleteInstance({ key: 'node' }, { id: 'instance' });
    h.component.openCreateInstance({ key: 'node' }); h.component.submitCreateInstance();
    assert.equal(h.component.createOpen(), false); assert.equal(h.calls.some((c) => c.method !== 'GET'), false);
    h.failures.add('/models/config'); h.component.refresh(); assert.equal(h.component.canConfigure(), false);
  } finally { h.close(); }
});
test('catalog filters provider, task and runtime and preserves explicit empty fallback', () => {
  const h = harness(); try {
    h.component.refresh(); h.component.models.update((all) => [...all, { ...openai, model: 'embedding', compatibility: 'other' }, { ...openai, provider: 'anthropic', runtime_available: false }]);
    assert.deepEqual(h.component.modelsForProvider('openai'), [openai]); assert.deepEqual(h.component.routingProviderOptions(), ['openai', 'ollama']);
    assert.deepEqual(h.component.routingDraft.fallback, []); assert.equal(h.component.canSaveRouting(), true);
    h.component.setRoutingProvider('ollama'); assert.equal(h.component.routingDraft.model, ''); assert.equal(h.component.canSaveRouting(), false);
    h.component.routingDraft.model = 'llama'; h.component.toggleFallback('openai'); h.component.saveRouting();
    assert.deepEqual(h.calls.find((c) => c.method === 'PUT')?.body, { provider: 'ollama', model: 'llama', fallback_chain: ['openai'] });
  } finally { h.close(); }
});
test('saved Azure metadata pre-fills without exposing or inventing secrets', () => {
  const h = harness(); try {
    h.component.refresh(); assert.deepEqual(h.component.credentialDrafts['azure_openai'], { api_key: '', endpoint: 'https://example.test', deployment: 'summary', api_version: '2024-10-21' });
    assert.equal(h.component.savedCredential('azure_openai')?.api_key_set, true);
  } finally { h.close(); }
});
test('workspace transition purges secrets and rejects stale test targets', async () => {
  const h = harness(); try {
    const old = new Subject<unknown>(); h.pending.set('/models/test-targets', old); h.component.refresh(); h.component.selectTestModel(openai);
    h.component.portalUnavailable.set(true);
    h.component.credentialDrafts['openai'] = { api_key: 'new-secret' }; h.workspace.switch();
    assert.equal(h.component.portalUnavailable(), false);
    assert.deepEqual(h.component.credentialDrafts, {}); assert.equal(h.component.selectedTestModel(), null);
    old.next({ can_test: true, targets: [target] }); old.complete(); await Promise.resolve();
    assert.deepEqual(h.component.testTargets(), []); assert.equal(h.component.testRunning(), false);
  } finally { h.close(); }
});
test('canonical targets match the selected pair and form input preserves additional defaults', async () => {
  const h = harness(); try {
    h.responses.set('/models/test-targets', { can_test: true, targets: [target, { ...target, model: 'wrong' }] });
    h.component.refresh(); h.component.selectTestModel(openai); assert.equal(h.component.testTargets().length, 1);
    h.component.selectTarget('system-a:summary'); assert.equal(h.component.testInputMode, 'fields');
    h.component.testValues = { prompt: 'A new excerpt', count: '3' }; h.component.testAcknowledged = true; h.component.startModelTest();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.deepEqual(h.calls.find((c) => c.path === '/models/test')?.body, {
      system_id: 'system-a', node_id: 'summary', provider: 'openai', model: 'gpt-mini', expected_flow_sha256: target.expected_flow_sha256,
      input_ref: { prompt: 'A new excerpt', count: 3, extra: 'preserve' }, acknowledge_real_side_effects: true,
    });
    assert.equal(h.component.testRun()?.status, 'completed'); assert.equal(h.component.testRunning(), false);
  } finally { h.close(); }
});
test('test rejects missing acknowledgement, invalid JSON and absent required inputs', () => {
  const h = harness(); try {
    h.component.refresh(); h.component.selectTestModel(openai); h.component.selectTarget('system-a:summary'); h.component.startModelTest();
    assert.equal(h.calls.some((c) => c.method === 'POST'), false);
    h.component.testAcknowledged = true; h.component.testValues = {}; h.component.startModelTest(); assert.match(h.component.testError()!, /required/);
    h.component.setTestInputMode('json'); h.component.testInputs = '[]'; h.component.startModelTest(); assert.match(h.component.testError()!, /JSON/);
    assert.equal(h.calls.some((c) => c.method === 'POST'), false);
  } finally { h.close(); }
});
test('catalog refresh preserves active test; clearing the selection removes previous result', async () => {
  const h = harness(); try {
    const response = new Subject<unknown>(); h.pending.set('/models/test', response);
    h.component.refresh(); h.component.selectTestModel(openai); h.component.selectTarget('system-a:summary'); h.component.testAcknowledged = true;
    h.component.startModelTest(); h.component.refresh(); response.next({ id: 'run-1', status: 'pending' }); response.complete();
    await new Promise((resolve) => setTimeout(resolve, 10)); assert.equal(h.component.testRun()?.status, 'completed');
    h.component.setTestModel(''); assert.equal(h.component.selectedTestModel(), null); assert.equal(h.component.testRun(), null);
  } finally { h.close(); }
});
test('model and token evidence is canonical trace and metrics, never arbitrary output', () => {
  const h = harness(); try {
    h.component.testRun.set({ id: 'run', status: 'completed', skill_invocations: [{ output_ref: { model: 'fabricated', usage: { total_tokens: 500 } } }] } as Run);
    assert.equal(h.component.testReturnedModel(), '—'); assert.equal(h.component.testTokens(), '—'); assert.equal(h.component.testModelResolution(), null);
    h.component.testRun.set({ id: 'run', status: 'completed', skill_invocations: [{ trace: { model_execution: { provider: 'openai', model: 'gpt-mini', returned_model: 'gpt-mini-revision', credential_source: 'workspace', model_source: 'executor', fallback: false } }, metrics: { total_tokens: 23, token_evidence: { measurement_coverage: 'complete' } } }] } as Run);
    assert.equal(h.component.testReturnedModel(), 'gpt-mini-revision'); assert.equal(h.component.testTokens(), 23);
  } finally { h.close(); }
});
test('costs distinguish catalog calculation, provider-reported zero and missing measurement', () => {
  const h = harness(); try {
    const run = (evidence?: unknown) => ({ id: 'run', status: 'completed', skill_invocations: [{ cost: 0, cost_measured: true, metrics: { cost_evidence: evidence } }] }) as Run;
    assert.equal(h.component.formatCost(1e-8, 'USD'), '< $0.0001');
    assert.equal(h.component.formatCost(0, 'USD'), '$0.00');
    h.component.testRun.set(run()); assert.equal(h.component.testCostLabel(), EN_DICT['resources.cost.unavailable']);
    h.component.testRun.set(run({ method: 'catalog_unit_price', currency: 'USD' })); assert.match(h.component.testCostLabel(), /\$0\.00.*catalog/i);
    h.component.testRun.set(run({ method: 'provider_measurement', currency: 'EUR' })); assert.match(h.component.testCostLabel(), /€0\.00.*provider/i);
    assert.deepEqual(h.component.skillQuery(openai), { provider: 'openai', model: 'gpt-mini', create: 'llm', modelWorkspace: 'workspace-1' });
  } finally { h.close(); }
});


test('unreachable connections stay selectable but carry an explicit warning, including fallback', () => {
  const h = harness(); try {
    h.component.refresh();
    const unavailable = { ...openai, status: 'unreachable' };
    h.component.liveProviders.set([{ key: 'openai', label: 'Public OpenAI', status: 'unreachable', models: ['gpt-mini'], configured: true }]);
    assert.equal(h.component.isSelectableModel(unavailable), true);
    assert.equal(h.component.modelStateLabel(unavailable), EN_DICT['resources.providers.state.unavailable']);
    assert.equal(h.component.providerConnectionUnavailable('openai'), true);
    assert.equal(h.component.modelProviderLabel('openai'), 'Public OpenAI');
    assert.equal(h.component.modelProviderLabel('azure_openai'), 'Azure OpenAI');
  } finally { h.close(); }
});

test('a delayed initial distribution never overwrites a later selected window', () => {
  const h = harness(); try {
    const initial = new Subject<unknown>(); h.pending.set('/models/distribution', initial);
    h.component.refresh(); h.pending.delete('/models/distribution');
    const recent = { window: '30d', by_model: [{ model: 'gpt-mini', invocations: 12 }] };
    h.responses.set('/models/distribution', recent); h.component.setDistWindow('30d');
    initial.next({ window: '7d', by_model: [] }); initial.complete();
    assert.deepEqual(h.component.distribution(), recent);
    h.failures.add('/models/nodes'); h.component.refresh(); assert.equal(h.component.portalError(), 'Read failed');
  } finally { h.close(); }
});


test('a slow canonical Run read is allowed to finish without polling cancellation', async () => {
  const h = harness(); try {
    const slow = new Subject<{ id: string; status: string }>(); let reads = 0;
    h.canonical.getRun = () => { reads++; return slow; };
    h.component.refresh(); h.component.selectTestModel(openai); h.component.selectTarget('system-a:summary');
    h.component.testAcknowledged = true; h.component.startModelTest();
    await new Promise((resolve) => setTimeout(resolve, 1100)); assert.equal(reads, 1);
    slow.next({ id: 'run-1', status: 'completed' }); slow.complete();
    assert.equal(h.component.testRun()?.status, 'completed'); assert.equal(h.component.testRunning(), false);
  } finally { h.close(); }
});


test('Skill creation keeps Govern context and model parameters in the query, not the route path', () => {
  const h = harness('/skills?lens=govern&capabilityId=cap-a'); try {
    const tree = h.component.skillsUrl(openai);
    const url = new URL(new DefaultUrlSerializer().serialize(tree), 'https://agentium.test');
    assert.equal(url.pathname, '/skills');
    assert.deepEqual(Object.fromEntries(url.searchParams), {
      lens: 'govern', capabilityId: 'cap-a', provider: 'openai', model: 'gpt-mini',
      create: 'llm', modelWorkspace: 'workspace-1',
    });
  } finally { h.close(); }
});

test('invocation evidence links preserve Govern as a query parameter', () => {
  const h = harness('/skills?lens=govern'); try {
    const tree = h.component.invocationUrl('run-1', 'invocation-1');
    const url = new URL(new DefaultUrlSerializer().serialize(tree), 'https://agentium.test');
    assert.equal(url.pathname, '/runs/run-1/invocations/invocation-1');
    assert.equal(url.searchParams.get('lens'), 'govern');
  } finally { h.close(); }
});
