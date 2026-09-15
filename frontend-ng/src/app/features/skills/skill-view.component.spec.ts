import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject, of } from 'rxjs';
import { CanonicalApiService, type Skill, type SkillDraft, type SkillExecutorCatalog } from '@app/core/canonical-api.service';
import { EN_DICT } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import { LensService } from '@app/core/lens';
import { ZoomContextService } from '@app/core/zoom-context.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { SkillViewComponent } from './skill-view.component';
import { formatSkillCost, observedSkillCost } from './skill-cost';
import { NewSkillDialogComponent } from './new-skill-dialog.component';

test('Skill costs distinguish missing, zero and positive amounts below display precision', () => {
  for (const value of [null, undefined, NaN, Infinity, -0.01]) {
    assert.equal(formatSkillCost(value), '—');
  }
  assert.equal(formatSkillCost(0), '$0.00');
  assert.equal(formatSkillCost(-0), '$0.00');
  assert.equal(formatSkillCost(Number.MIN_VALUE), '< $0.0001');
  assert.equal(formatSkillCost(0.000001), '< $0.0001');
  assert.equal(formatSkillCost(0.000099), '< $0.0001');
  assert.equal(formatSkillCost(0.0001), '$0.0001');
  assert.equal(formatSkillCost(0.0008), '$0.0008');
  assert.equal(formatSkillCost(0.012), '$0.012');
  assert.equal(formatSkillCost(125.25), '$125.25');
  assert.equal(formatSkillCost(0.000001, 'EUR'), '< €0.0001');
  assert.equal(formatSkillCost(2, 'EUR'), '€2.00');
  assert.equal(formatSkillCost(2, null), '—');
  assert.equal(formatSkillCost(2, 'invalid'), '—');
  assert.equal(formatSkillCost(2, 42 as unknown as string), '—');
});

test('Observed Skill costs never substitute a catalog price or unmeasured default', () => {
  assert.equal(observedSkillCost(undefined), null);
  assert.equal(observedSkillCost({}), null);
  assert.equal(observedSkillCost({ calls: 0, total_cost: 0 }), null);
  assert.equal(observedSkillCost({ calls: 1, total_cost: 0, cost_state: 'not_measured' }), null);
  assert.equal(observedSkillCost({ calls: 1, total_cost: null }), null);
  assert.equal(observedSkillCost({ calls: 1, total_cost: 0, cost_state: 'available' }), 0);
  assert.equal(observedSkillCost({ calls: 1, total_cost: 0.000001 }), 0.000001);
});

class WorkspaceStub {
  private slug = 'workspace-a';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  readonly currentSlug = () => this.slug;
  readonly contextEpoch = () => this.epoch;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, workspaceId: `workspace-${this.slug}`, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'workspace-b',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

test('Skill view purges A synchronously and only accepts the B reload', async () => {
  const params = new BehaviorSubject(convertToParamMap({ skillId: 'shared-skill' }));
  const workspace = new WorkspaceStub();
  const reads: Array<Subject<Skill | null>> = [];
  const canonical = {
    getSkillExecutors: () => of({ editable: false, executors: [], categories: [] }),
    getSkill: () => {
      const response = new Subject<Skill | null>();
      reads.push(response);
      return response;
    },
  };
  const injector = Injector.create({
    providers: [
      SkillViewComponent,
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: params.asObservable(),
          snapshot: { paramMap: params.value, queryParamMap: convertToParamMap({}) },
        },
      },
      { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: workspace },
      { provide: LensService, useValue: { lens: () => 'build' } },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
      { provide: ZoomContextService, useValue: { navV5Enabled: () => false, zoneI18nKey: () => 'nav.build.create' } },
    ],
  });
  const view = injector.get(SkillViewComponent);
  view.ngOnInit();
  const skill = { id: 'skill-a', slug: 'shared-skill', name: 'Skill A', pricing: { unit: 'per_call', unit_price: 0, currency: 'USD' } };
  reads[0].next(skill);
  assert.equal(view.skill()?.name, 'Skill A');
  const observedCost = () => view.kpis().find(kpi => kpi.label === 'skills.cost.observed')?.value;
  assert.equal(observedCost(), 'skills.cost.not_measured', 'a default zero tariff is not an observed invocation cost');
  reads[0].next({ ...skill, metrics: { calls: 1, total_cost: 0 } });
  assert.equal(observedCost(), '$0.00');
  reads[0].next({ ...skill, metrics: { calls: 1, total_cost: 0.000001 } });
  assert.equal(observedCost(), '< $0.0001');
  view.activeTab.set('spec');
  view.specPanelOpen.set(true);

  workspace.switchWorkspace();
  assert.equal(view.skill(), null, 'A is removed before B becomes current');
  assert.equal(view.activeTab(), 'overview');
  assert.equal(view.specPanelOpen(), false);

  await Promise.resolve();
  assert.equal(reads.length, 2);
  reads[0].next({ id: 'late-a', slug: 'shared-skill', name: 'Late Skill A' });
  reads[1].next({ id: 'skill-b', slug: 'shared-skill', name: 'Skill B' });
  assert.equal(view.skill()?.name, 'Skill B');

  view.ngOnDestroy();
});

const EXECUTORS: SkillExecutorCatalog = {
  editable: true,
  categories: ['LLM'],
  executors: [
    {
      kind: 'prompt_template',
      summary: 'LLM prompt',
      params_schema: {
        required: ['provider', 'template'],
        properties: {
          provider: { enum: ['azure', 'ollama'] },
          template: { type: 'string', maxLength: 8000 },
        },
      },
    },
    {
      kind: 'registry_call',
      summary: 'Wrapped Skill',
      params_schema: {
        required: ['skill_slug'],
        properties: { skill_slug: { type: 'string' }, frozen_input: { type: 'object' } },
      },
    },
  ],
};

const AUTHORED: Skill = {
  id: 'authored', slug: 'ws.workspace-a.summary', name: 'Summary', description: 'A factual summary.',
  type: 'llm', category: 'LLM', workspace_scope: 'workspace',
  input_schema: { type: 'object', properties: { document: { type: 'string', maxLength: 3500 } }, required: ['document'], additionalProperties: false },
  output_schema: { type: 'object', properties: { completion: { type: 'string', minLength: 1 } }, required: ['completion'], additionalProperties: true },
  executor: { kind: 'prompt_template', params: { provider: 'azure', template: 'Summarise {document}.\nCite sources.' } },
};

function detailHarness() {
  const params = new BehaviorSubject(convertToParamMap({ skillId: AUTHORED.slug }));
  const workspace = new WorkspaceStub();
  const reads: Subject<Skill | null>[] = [];
  const catalogs: Subject<SkillExecutorCatalog>[] = [];
  const targetReads: Subject<Skill[]>[] = [];
  const patches: Array<{ slug: string; patch: Partial<Omit<SkillDraft, 'local_name'>>; response: Subject<Skill> }> = [];
  const canonical = {
    getSkill: () => { const response = new Subject<Skill | null>(); reads.push(response); return response; },
    getSkillExecutors: () => { const response = new Subject<SkillExecutorCatalog>(); catalogs.push(response); return response; },
    listSkills: () => { const response = new Subject<Skill[]>(); targetReads.push(response); return response; },
    updateSkill: (slug: string, patch: Partial<Omit<SkillDraft, 'local_name'>>) => {
      const response = new Subject<Skill>(); patches.push({ slug, patch, response }); return response;
    },
  };
  const injector = Injector.create({
    providers: [
      SkillViewComponent, NewSkillDialogComponent,
      { provide: ActivatedRoute, useValue: { paramMap: params, snapshot: { paramMap: params.value, queryParamMap: convertToParamMap({}) } } },
      { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: workspace },
      { provide: LensService, useValue: { lens: () => 'build' } },
      { provide: I18nService, useValue: { t: (key: string, values?: Record<string, string | number>) =>
        ((EN_DICT as Record<string, string>)[key] ?? key).replace(/\{(\w+)\}/g, (_match, name: string) => String(values?.[name] ?? `{${name}}`)) } },
      { provide: ZoomContextService, useValue: { navV5Enabled: () => false, zoneI18nKey: () => 'nav.build.create' } },
    ],
  });
  const view = injector.get(SkillViewComponent);
  view.ngOnInit();
  return { view, injector, params, workspace, reads, catalogs, targetReads, patches };
}

test('Skill detail requires both the server editing right and workspace ownership', () => {
  for (const permission of ['pending', 'denied', 'unreachable', 'allowed'] as const) {
    for (const scope of ['workspace', 'global', undefined] as const) {
      const h = detailHarness();
      h.reads[0].next({ ...AUTHORED, workspace_scope: scope });
      assert.equal(h.view.skill()?.name, AUTHORED.name, 'reading the execution does not wait for authoring permissions');
      if (permission === 'unreachable') h.catalogs[0].error(new Error('Unavailable'));
      else if (permission !== 'pending') h.catalogs[0].next({ ...EXECUTORS, editable: permission === 'allowed' });
      const allowed = permission === 'allowed' && scope === 'workspace';
      assert.equal(h.view.canEdit(), allowed);
      assert.equal(h.targetReads.length, 0, 'reading a detail never fetches the entire catalog');
      h.view.openEditing();
      assert.equal(h.targetReads.length, allowed ? 1 : 0);
      assert.equal(h.view.dialogCatalog(), null, 'editing waits for its required registry targets');
      h.view.ngOnDestroy();
    }
  }
});

for (const executor of [
  AUTHORED.executor!,
  { kind: 'registry_call', params: { skill_slug: 'audit_log_v1', frozen_input: { event_type: 'review', retries: 0, enabled: false } } },
]) {
  test(`Skill detail edits ${executor.kind} through the existing wizard without losing contracts or params`, () => {
    const h = detailHarness();
    const skill = { ...AUTHORED, executor };
    h.reads[0].next(skill);
    h.catalogs[0].next(EXECUTORS);
    assert.deepEqual(JSON.parse(h.view.specPreview()).executor, executor);
    h.view.openEditing();
    const target: Skill = { id: 'audit', slug: 'audit_log_v1', name: 'Audit log', runtime_status: 'bound', input_schema: { type: 'object', properties: { retries: { type: 'integer' } } } };
    h.targetReads[0].next([target, skill, { ...target, id: 'stub', slug: 'unbound', runtime_status: 'unbound' }, { ...target, id: 'catalog', slug: 'catalog-only', runtime_status: 'catalog_only' }]);
    assert.deepEqual(h.view.registryTargets(), [target]);
    const wizard = h.injector.get(NewSkillDialogComponent);
    wizard.catalog = h.view.dialogCatalog()!;
    wizard.registryTargets = h.view.registryTargets();
    wizard.skill = h.view.editingSkill();
    wizard.initialStep = 'runtime';
    assert.equal(wizard.step(), 'runtime');
    assert.equal(wizard.editing(), true);
    assert.equal(wizard.executorKind(), executor.kind);
    for (const [key, value] of Object.entries(executor.params!)) {
      assert.deepEqual(typeof value === 'string' ? wizard.param(key) : JSON.parse(wizard.param(key)), value);
    }
    if (executor.kind === 'prompt_template') wizard.setParam('template', 'Updated summary of {document}.');
    wizard.updated.subscribe((result) => h.view.onUpdated(result));
    wizard.submit();
    assert.equal(h.patches.length, 1);
    const { slug, patch, response } = h.patches[0];
    assert.equal(slug, skill.slug);
    assert.equal('local_name' in patch, false);
    assert.deepEqual(patch.input_schema, skill.input_schema);
    assert.deepEqual(patch.output_schema, skill.output_schema);
    assert.deepEqual(patch.executor, executor.kind === 'prompt_template'
      ? { kind: 'prompt_template', params: { provider: 'azure', template: 'Updated summary of {document}.' } }
      : executor);
    const updated = { ...skill, ...patch, published_bindings: [{ system_name: 'Published summary' }] };
    response.next(updated);
    assert.equal(h.view.dialogCatalog(), null);
    assert.deepEqual(h.view.skill()?.executor, patch.executor);
    assert.match(h.view.authoredNotice()!, /Published summary/);
    assert.equal(h.reads.length, 2, 'saved detail is reloaded through the canonical endpoint');
    h.view.ngOnDestroy();
  });
}

test('Skill detail skips registry loading when only a prompt executor is available and keeps create at Intent', () => {
  const h = detailHarness();
  h.reads[0].next(AUTHORED);
  h.catalogs[0].next({ ...EXECUTORS, executors: [EXECUTORS.executors[0]] });
  h.view.openEditing();
  assert.equal(h.targetReads.length, 0);
  assert.equal(h.view.editingSkill(), AUTHORED);
  assert.equal(h.injector.get(NewSkillDialogComponent).step(), 'intent');
  h.view.ngOnDestroy();
});

test('Skill detail reports a failed registry load and allows a fresh attempt', () => {
  const h = detailHarness();
  h.reads[0].next(AUTHORED);
  h.catalogs[0].next(EXECUTORS);
  h.view.openEditing();
  h.targetReads[0].error(new Error('Unavailable'));
  assert.equal(h.view.editingLoading(), false);
  assert.equal(h.view.dialogCatalog(), null);
  assert.ok(h.view.editingError());
  h.view.openEditing();
  h.targetReads[1].next([]);
  assert.equal(h.view.editingError(), null);
  assert.equal(h.view.editingSkill(), AUTHORED);
  h.view.ngOnDestroy();
});

test('Skill detail purges editing rights, targets, notices and stale updates on workspace change', async () => {
  const h = detailHarness();
  h.reads[0].next(AUTHORED);
  h.catalogs[0].next(EXECUTORS);
  h.view.openEditing();
  h.targetReads[0].next([{ id: 'audit', slug: 'audit_log_v1', name: 'Audit', runtime_status: 'bound' }]);
  h.view.authoredNotice.set('A notice');
  h.workspace.switchWorkspace();
  assert.equal(h.view.skill(), null);
  assert.equal(h.view.canEdit(), false);
  assert.equal(h.view.dialogCatalog(), null);
  assert.equal(h.view.editingSkill(), null);
  assert.deepEqual(h.view.registryTargets(), []);
  assert.equal(h.view.authoredNotice(), null);
  h.view.onUpdated({ skill: { ...AUTHORED, name: 'Late saved A' }, publishedIn: ['A System'] });
  h.targetReads[0].next([AUTHORED]);
  h.catalogs[0].next(EXECUTORS);
  assert.equal(h.view.skill(), null);
  assert.equal(h.view.authoredNotice(), null);
  assert.deepEqual(h.view.registryTargets(), []);
  await Promise.resolve();
  h.reads[1].next({ ...AUTHORED, name: 'B Skill' });
  h.catalogs[1].next({ ...EXECUTORS, editable: false });
  assert.equal(h.view.skill()?.name, 'B Skill');
  assert.equal(h.view.canEdit(), false);
  h.view.ngOnDestroy();
});

test('Skill detail discards a pending edit and old reads when navigating to another Skill', () => {
  const h = detailHarness();
  h.reads[0].next(AUTHORED);
  h.catalogs[0].next(EXECUTORS);
  h.view.openEditing();
  h.params.next(convertToParamMap({ skillId: 'second-skill' }));
  h.targetReads[0].next([AUTHORED]);
  h.reads[0].next(AUTHORED);
  assert.equal(h.view.editingSkill(), null);
  assert.equal(h.view.editingLoading(), false);
  assert.equal(h.view.skill(), null);
  h.reads[1].next({ ...AUTHORED, slug: 'second-skill', name: 'Second skill' });
  h.catalogs[1].next(EXECUTORS);
  assert.equal(h.view.skill()?.name, 'Second skill');
  h.view.ngOnDestroy();
});
