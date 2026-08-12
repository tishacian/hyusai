import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Skill,
  type SkillDraft,
  type SkillExecutorCatalog,
} from '@app/core/canonical-api.service';
import { EN_DICT } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NewSkillDialogComponent } from './new-skill-dialog.component';
import { SkillsComponent } from './skills.component';

const CATALOG: SkillExecutorCatalog = {
  editable: true,
  categories: ['Analysis', 'Automation', 'Governance', 'LLM'],
  executors: [
    {
      kind: 'prompt_template',
      summary: 'Send a fixed prompt template to a verified model provider.',
      params_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['provider', 'template'],
        properties: {
          provider: { enum: ['azure', 'ollama'] },
          template: { type: 'string', minLength: 1, maxLength: 8000 },
        },
      },
    },
    {
      kind: 'registry_call',
      summary: 'Run a catalog Skill with parameters pinned by this workspace.',
      params_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['skill_slug'],
        properties: {
          skill_slug: { type: 'string', minLength: 1, maxLength: 160 },
          frozen_input: { type: 'object' },
        },
      },
    },
  ],
};

const AUDIT_LOG: Skill = {
  id: 'skill-audit',
  slug: 'audit_log_v1',
  name: 'Audit log',
  runtime_status: 'bound',
  input_schema: {
    type: 'object',
    required: ['event_type'],
    properties: {
      event_type: { type: 'string', enum: ['reset', 'close'] },
      retries: { type: 'integer' },
    },
  },
};

const TRIAGE: Capability = {
  id: 'cap-owned',
  slug: 'ticket-triage',
  name: 'Ticket triage',
  workspace_scope: 'workspace',
};

/**
 * The real English dictionary, so a key the view asks for and never defined
 * shows up here rather than on screen.
 */
const i18n = {
  t: (key: string, params?: Record<string, string | number>) => {
    const raw = (EN_DICT as Record<string, string>)[key] ?? key;
    return raw.replace(/\{(\w+)\}/g, (_match, name: string) =>
      String(params?.[name] ?? `{${name}}`));
  },
};

class ApiStub {
  readonly created: SkillDraft[] = [];
  readonly patched: Array<[string, unknown]> = [];
  readonly responses: Array<Subject<Skill>> = [];

  createSkill(body: SkillDraft) {
    this.created.push(body);
    const response = new Subject<Skill>();
    this.responses.push(response);
    return response;
  }

  updateSkill(slug: string, patch: unknown) {
    this.patched.push([slug, patch]);
    const response = new Subject<Skill>();
    this.responses.push(response);
    return response;
  }
}

function dialog() {
  const api = new ApiStub();
  const injector = Injector.create({
    providers: [
      NewSkillDialogComponent,
      { provide: CanonicalApiService, useValue: api },
      { provide: I18nService, useValue: i18n },
    ],
  });
  const view = injector.get(NewSkillDialogComponent);
  view.catalog = CATALOG;
  view.registryTargets = [AUDIT_LOG];
  view.capabilities = [TRIAGE];
  return { view, api };
}

function fillIdentity(view: NewSkillDialogComponent): void {
  view.localName.set('reset_ticket');
  view.name.set('Reset a ticket');
}

const keys = (view: NewSkillDialogComponent) => view.problems().map((problem) => problem.key);

test('the runtime controls are read from the descriptor, not from a local copy', () => {
  const { view } = dialog();

  view.selectKind('prompt_template');
  assert.deepEqual(
    view.fields().map((field) => [field.key, field.control, field.required, field.maxLength]),
    [
      ['provider', 'select', true, null],
      ['template', 'long_text', true, 8000],
    ],
  );
  assert.deepEqual(view.fields()[0].options, ['azure', 'ollama']);

  view.selectKind('registry_call');
  assert.deepEqual(
    view.fields().map((field) => [field.key, field.control, field.required]),
    [
      ['skill_slug', 'registry_target', true],
      // The preset inputs of the wrapped skill: a form, no longer raw JSON.
      ['frozen_input', 'preset_inputs', false],
    ],
  );

  // A kind the server adds tomorrow gets its controls without a frontend edit.
  view.catalog = {
    ...CATALOG,
    executors: [
      ...CATALOG.executors,
      {
        kind: 'future_kind',
        summary: 'Something authored later.',
        params_schema: { required: ['dialect'], properties: { dialect: { enum: ['a', 'b'] } } },
      },
    ],
  };
  view.selectKind('future_kind');
  assert.deepEqual(view.fields().map((field) => field.key), ['dialect']);
});

test('the runtime is named in plain words with the raw kind still available', () => {
  const { view } = dialog();

  assert.equal(view.runtimeLabel('registry_call'), 'Wrap a core skill');
  assert.equal(view.runtimeLabel('prompt_template'), 'LLM prompt template');
  // A kind nobody has worded yet falls back to itself rather than to a key.
  assert.equal(view.runtimeLabel('future_kind'), 'future_kind');
});

test('a contract cannot be invalid JSON any more, because it is never text', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.selectKind('registry_call');
  view.setParam('skill_slug', 'audit_log_v1');
  view.inputSchema.set({ type: 'object', properties: { details: { type: 'object' } } });

  assert.deepEqual(keys(view), []);
  view.submit();
  assert.equal(api.created.length, 1);
  assert.deepEqual(api.created[0].input_schema, {
    type: 'object',
    properties: { details: { type: 'object' } },
  });
});

test('preset inputs are a form derived from the wrapped skill own contract', () => {
  const { view } = dialog();
  fillIdentity(view);
  view.selectKind('registry_call');

  assert.equal(view.presetTarget(), null, 'nothing to derive from before a target is picked');

  view.setParam('skill_slug', 'audit_log_v1');
  assert.deepEqual(
    view.presetFields().map((field) => [field.name, field.type, field.options]),
    [
      ['event_type', 'string', ['reset', 'close']],
      ['retries', 'integer', []],
    ],
  );

  view.setPresetValue(view.presetFields()[0], 'reset');
  view.setPresetValue(view.presetFields()[1], '2');
  assert.deepEqual(JSON.parse(view.param('frozen_input')), { event_type: 'reset', retries: 2 });
  assert.equal(view.presetValue('event_type'), 'reset');

  // Clearing a value removes the key: presetting nothing is how the caller
  // keeps deciding that input at run time.
  view.setPresetValue(view.presetFields()[1], '');
  assert.deepEqual(JSON.parse(view.param('frozen_input')), { event_type: 'reset' });
});

test('a preset value the target contract does not declare is named, not dropped', () => {
  const { view } = dialog();
  view.selectKind('registry_call');
  view.setParam('skill_slug', 'audit_log_v1');
  view.setParam('frozen_input', '{"event_type":"reset","legacy_flag":true}');

  assert.deepEqual(view.presetExtras(), ['legacy_flag']);
  view.setPresetValue(view.presetFields()[0], 'close');
  assert.deepEqual(JSON.parse(view.param('frozen_input')), {
    event_type: 'close',
    legacy_flag: true,
  });
});

test('preset inputs written by hand are still checked before they are sent', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.selectKind('registry_call');
  view.setParam('skill_slug', 'audit_log_v1');
  view.setParam('frozen_input', 'not json');

  assert.deepEqual(keys(view), ['skills.problem.json']);
  view.submit();
  assert.deepEqual(api.created, []);

  view.setParam('frozen_input', '[]');
  assert.deepEqual(keys(view), ['skills.problem.json_object']);
});

test('a runtime parameter the descriptor requires blocks the submission', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.selectKind('prompt_template');
  view.setParam('template', 'Draft a reply to {ticket}.');

  assert.deepEqual(view.problems(), [
    { key: 'skills.problem.required', params: { field: 'Model provider' } },
  ]);
  view.submit();
  assert.deepEqual(api.created, []);

  view.setParam('provider', 'mistral');
  assert.deepEqual(keys(view), ['skills.problem.enum']);

  view.setParam('provider', 'ollama');
  assert.deepEqual(view.problems(), []);
});

test('switching runtime drops the parameters the previous one owned', () => {
  const { view } = dialog();
  fillIdentity(view);
  view.selectKind('registry_call');
  view.setParam('skill_slug', 'audit_log_v1');

  view.selectKind('prompt_template');

  assert.equal(view.param('skill_slug'), '', 'the params contract is closed server-side');
});

test('a preset picks the runtime and proposes the contract, all of it editable', () => {
  const { view } = dialog();

  view.applyPreset('llm');
  assert.equal(view.executorKind(), 'prompt_template');
  assert.equal(view.category(), 'LLM');
  assert.deepEqual(Object.keys((view.inputSchema()?.['properties'] ?? {}) as object), ['question']);

  view.applyPreset('wrapper');
  assert.equal(view.executorKind(), 'registry_call');
  assert.equal(view.param('skill_slug'), 'audit_log_v1');
  assert.deepEqual(view.inputSchema(), AUDIT_LOG.input_schema);

  view.applyPreset('scratch');
  assert.equal(view.executorKind(), '');
});

test('a complete draft posts exactly what the workspace decided', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.description.set('Records the reset in the ledger.');
  view.category.set('Automation');
  view.capabilityId.set('cap-owned');
  view.inputSchema.set({ type: 'object', properties: { details: { type: 'object' } } });
  view.selectKind('registry_call');
  view.setParam('skill_slug', 'audit_log_v1');
  view.setParam('frozen_input', '{"event_type":"reset"}');

  const emitted: Skill[] = [];
  view.created.subscribe((skill) => emitted.push(skill));
  view.submit();

  assert.equal(view.submitting(), true);
  assert.deepEqual(api.created, [{
    local_name: 'reset_ticket',
    name: 'Reset a ticket',
    description: 'Records the reset in the ledger.',
    type: 'generic',
    category: 'Automation',
    input_schema: { type: 'object', properties: { details: { type: 'object' } } },
    // No slug, no certification, no workspace id: the server owns those.
    output_schema: {},
    executor: {
      kind: 'registry_call',
      params: { skill_slug: 'audit_log_v1', frozen_input: { event_type: 'reset' } },
    },
    capability_id: 'cap-owned',
  }]);

  api.responses[0].next({ ...AUDIT_LOG, id: 'authored', slug: 'ws.ws-nawa.reset_ticket', name: 'Reset a ticket' });
  assert.equal(view.submitting(), false);
  assert.equal(emitted[0].slug, 'ws.ws-nawa.reset_ticket');
});

test('no capability named means no claim asked for', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.selectKind('registry_call');
  view.setParam('skill_slug', 'audit_log_v1');

  view.submit();

  assert.equal('capability_id' in api.created[0], false);
});

test('editing the same screens patches the row and never renames the slug', () => {
  const { view, api } = dialog();
  view.skill = {
    id: 'authored',
    slug: 'ws.ws-nawa.reset_ticket',
    name: 'Reset a ticket',
    description: 'Old wording.',
    type: 'generic',
    category: 'Automation',
    workspace_scope: 'workspace',
    input_schema: { type: 'object', properties: { ticket: { type: 'string' } } },
    executor: { kind: 'registry_call', params: { skill_slug: 'audit_log_v1' } },
  };

  assert.equal(view.editing(), true);
  assert.equal(view.localName(), 'reset_ticket');
  assert.equal(view.executorKind(), 'registry_call');
  assert.equal(view.param('skill_slug'), 'audit_log_v1');

  view.description.set('New wording.');
  const seen: Array<{ publishedIn: string[] }> = [];
  view.updated.subscribe((result) => seen.push(result));
  view.submit();

  assert.equal(api.patched[0][0], 'ws.ws-nawa.reset_ticket');
  assert.equal((api.patched[0][1] as { description: string }).description, 'New wording.');
  assert.equal('local_name' in (api.patched[0][1] as object), false);

  api.responses[0].next({
    id: 'authored',
    slug: 'ws.ws-nawa.reset_ticket',
    name: 'Reset a ticket',
    published_bindings: [{ system_name: 'Ticket desk' }, { system_name: 'Ticket desk' }],
  });
  assert.deepEqual(seen[0].publishedIn, ['Ticket desk'], 'reach is reported, not vetoed');
});

test('a refusal is shown in the server’s own words', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.selectKind('registry_call');
  view.setParam('skill_slug', 'audit_log_v1');

  view.submit();
  api.responses[0].error({
    status: 400,
    error: {
      detail: {
        code: 'executor_target_unbound',
        message: 'params.skill_slug names no verified runtime.',
      },
    },
  });

  assert.equal(view.error(), 'params.skill_slug names no verified runtime.');
  assert.equal(view.submitting(), false);

  view.submit();
  api.responses[1].error({
    status: 422,
    error: {
      detail: [
        { loc: ['body', 'category'], msg: 'category must be one of: Analysis, Automation' },
      ],
    },
  });

  assert.equal(view.error(), 'category: category must be one of: Analysis, Automation');
});

test('an imported requirement opens the wizard already filled in', () => {
  const { view } = dialog();

  view.seed = {
    localName: 'fr_1_draft_a_reply',
    name: 'Draft a reply from the ticket history',
    description: 'Draft a reply from the ticket history',
  };

  assert.equal(view.localName(), 'fr_1_draft_a_reply');
  assert.equal(view.name(), 'Draft a reply from the ticket history');
  assert.deepEqual(keys(view), ['skills.problem.runtime'], 'a draft, not a skill');
});

class WorkspaceStub {
  private slug = 'nawa';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();
  readonly contextRefresh$ = new Subject<void>();

  readonly currentSlug = () => this.slug;
  readonly contextEpoch = () => this.epoch;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, workspaceId: `ws-${this.slug}`, epoch: this.epoch });
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
      nextSlug: 'andritz',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

function registry(options: {
  executors?: SkillExecutorCatalog | 'unreachable';
  pages?: Skill[][];
  capabilities?: Capability[];
  deletion?: unknown;
}) {
  const pages = options.pages ?? [[AUDIT_LOG]];
  let call = 0;
  const deleted: string[] = [];
  const canonical = {
    listSkills: () => of(pages[Math.min(call++, pages.length - 1)]),
    getSkillExecutors: () => (options.executors === 'unreachable'
      ? throwError(() => new Error('offline'))
      : of(options.executors ?? CATALOG)),
    listCapabilities: () => of(options.capabilities ?? [TRIAGE]),
    getCapability: () => of(null),
    getSystem: () => of(null),
    getRun: () => of(null),
    deleteSkill: (slug: string) => {
      deleted.push(slug);
      return options.deletion
        ? throwError(() => options.deletion)
        : of({ deleted: slug });
    },
  };
  const params = new BehaviorSubject(convertToParamMap({}));
  const workspace = new WorkspaceStub();
  const injector = Injector.create({
    providers: [
      SkillsComponent,
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: workspace },
      { provide: I18nService, useValue: i18n },
      {
        provide: ActivatedRoute,
        useValue: { queryParamMap: params.asObservable(), snapshot: { queryParamMap: params.value } },
      },
      {
        provide: ZoomContextService,
        useValue: {
          axesV3Enabled: () => false,
          capabilityId: () => null,
          systemId: () => null,
          runId: () => null,
          objectUrlTree: () => ['/skills'],
        },
      },
    ],
  });
  return { view: injector.get(SkillsComponent), workspace, calls: () => call, deleted };
}

const AUTHORED: Skill = {
  id: 'authored',
  slug: 'ws.ws-nawa.reset_ticket',
  name: 'Reset a ticket',
  workspace_scope: 'workspace',
  executor: { kind: 'registry_call' },
};

test('the New skill affordance appears only when the server grants skill.admin', () => {
  const granted = registry({});
  granted.view.ngOnInit();
  assert.equal(granted.view.canAuthor(), true);
  granted.view.openAuthoring();
  assert.equal(granted.view.authoringCatalog()?.editable, true);
  granted.view.ngOnDestroy();

  const denied = registry({ executors: { ...CATALOG, editable: false } });
  denied.view.ngOnInit();
  assert.equal(denied.view.canAuthor(), false);
  denied.view.openAuthoring();
  assert.equal(denied.view.authoringCatalog(), null, 'a member must not reach the form');
  denied.view.openImport();
  assert.equal(denied.view.importing(), false);
  denied.view.ngOnDestroy();
});

test('an unknown authoring right fails closed rather than assuming an admin', () => {
  const { view } = registry({ executors: 'unreachable' });

  view.ngOnInit();

  assert.equal(view.canAuthor(), false);
  assert.equal(view.skills().length, 1, 'the registry still lists what it can read');
  view.ngOnDestroy();
});

test('an authored skill lands in the registry and is selected', () => {
  const { view, calls } = registry({ pages: [[AUDIT_LOG], [AUDIT_LOG, AUTHORED]] });
  view.ngOnInit();
  view.openAuthoring();

  view.onAuthored({ ...AUTHORED, capability_claim: { attached: true, capability_name: 'Ticket triage' } });

  assert.equal(calls(), 2, 'the list is re-read so the new row exists on the surface');
  assert.equal(view.authoring(), false);
  assert.equal(view.selected()?.slug, 'ws.ws-nawa.reset_ticket');
  assert.match(view.authoredNotice()!, /ws\.ws-nawa\.reset_ticket created/);
  assert.match(view.authoredNotice()!, /Ticket triage/);
  view.ngOnDestroy();
});

test('a refused capability claim is said out loud, and the skill is still there', () => {
  const { view } = registry({ pages: [[AUDIT_LOG], [AUDIT_LOG, AUTHORED]] });
  view.ngOnInit();

  view.onAuthored({
    ...AUTHORED,
    capability_claim: { attached: false, reason: 'no Capability of this workspace has that id' },
  });

  assert.match(view.authoredNotice()!, /no capability could be made to carry it/);
  assert.equal(view.selected()?.slug, 'ws.ws-nawa.reset_ticket');
  view.ngOnDestroy();
});

test('edit and delete are offered on the rows this workspace owns, and only those', () => {
  const { view } = registry({ pages: [[AUDIT_LOG, AUTHORED]] });
  view.ngOnInit();

  assert.equal(view.owns(AUTHORED), true);
  assert.equal(view.owns(AUDIT_LOG), false, 'the seeded catalog is shared, not editable here');

  view.openEditing(AUDIT_LOG);
  assert.equal(view.editingSkill(), null);

  view.openEditing(AUTHORED);
  assert.equal(view.editingSkill()?.slug, AUTHORED.slug);
  assert.equal(view.dialogCatalog()?.editable, true);
  view.ngOnDestroy();
});

test('a delete the API refuses is reported in the API own words', () => {
  const { view, deleted } = registry({
    pages: [[AUDIT_LOG, AUTHORED]],
    deletion: {
      status: 409,
      error: {
        detail: {
          code: 'skill_bound_by_published_flow',
          message: 'This Skill is dispatched by the published Flow of Ticket desk.',
        },
      },
    },
  });
  view.ngOnInit();
  view.select(AUTHORED);
  view.askDelete();
  assert.equal(view.confirmingDelete(), true, 'a delete is never one click away');

  view.confirmDelete(AUTHORED);

  assert.deepEqual(deleted, ['ws.ws-nawa.reset_ticket']);
  assert.match(view.lifecycleError()!, /published Flow of Ticket desk/);
  assert.equal(view.selected()?.slug, AUTHORED.slug, 'nothing was removed from the surface');
  view.ngOnDestroy();
});

test('a delete the API accepts clears the selection and re-reads the list', () => {
  const { view, calls } = registry({ pages: [[AUDIT_LOG, AUTHORED], [AUDIT_LOG]] });
  view.ngOnInit();
  view.select(AUTHORED);

  view.confirmDelete(AUTHORED);

  assert.equal(calls(), 2);
  assert.equal(view.selected(), null);
  assert.match(view.authoredNotice()!, /deleted/);
  view.ngOnDestroy();
});

test('an imported row opens the wizard as a draft rather than creating anything', () => {
  const { view, calls } = registry({});
  view.ngOnInit();
  view.openImport();
  assert.equal(view.importing(), true);

  view.onDrafted({ localName: 'fr_1_draft_a_reply', name: 'Draft a reply' });

  assert.equal(view.importing(), false);
  assert.equal(view.authoring(), true);
  assert.equal(view.draftSeed()?.localName, 'fr_1_draft_a_reply');
  assert.equal(calls(), 1, 'reading a document creates nothing');
  view.ngOnDestroy();
});

test('only a capability this workspace owns is offered as a carrier', () => {
  const { view } = registry({
    capabilities: [TRIAGE, { id: 'cap-shared', slug: 'universal', name: 'Universal', workspace_scope: 'global' }],
  });
  view.ngOnInit();

  assert.deepEqual(view.claimableCapabilities().map((row) => row.id), ['cap-owned']);
  view.ngOnDestroy();
});

test('switching workspace withdraws the authoring right until B answers', async () => {
  const { view, workspace } = registry({});
  view.ngOnInit();
  view.openAuthoring();
  assert.equal(view.canAuthor(), true);

  workspace.switchWorkspace();

  assert.equal(view.canAuthor(), false, 'A’s permission must not decide for B');
  assert.equal(view.authoring(), false);

  await Promise.resolve();
  assert.equal(view.canAuthor(), true);
  view.ngOnDestroy();
});
