import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import {
  CanonicalApiService,
  type Skill,
  type SkillDraft,
  type SkillExecutorCatalog,
} from '@app/core/canonical-api.service';
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
  categories: ['Analysis', 'Automation', 'Governance'],
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
};

class ApiStub {
  readonly created: SkillDraft[] = [];
  readonly responses: Array<Subject<Skill>> = [];

  createSkill(body: SkillDraft) {
    this.created.push(body);
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
    ],
  });
  const view = injector.get(NewSkillDialogComponent);
  view.catalog = CATALOG;
  view.registryTargets = [AUDIT_LOG];
  return { view, api };
}

function fillIdentity(view: NewSkillDialogComponent): void {
  view.localName.set('reset_ticket');
  view.name.set('Reset a ticket');
}

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
      ['frozen_input', 'json', false],
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

test('a JSON typo is caught here rather than by a round trip', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.selectKind('registry_call');
  view.setParam('skill_slug', 'audit_log_v1');
  view.inputSchema.set('{"type": "object",}');

  assert.ok(view.problems().some((problem) => /Input contract is not valid JSON/.test(problem)));
  view.submit();
  assert.deepEqual(api.created, [], 'an unparseable contract must not be sent');

  view.inputSchema.set('[]');
  assert.ok(view.problems().some((problem) => /must be a JSON object/.test(problem)));

  view.inputSchema.set('{"type": "object"}');
  view.setParam('frozen_input', 'not json');
  assert.ok(view.problems().some((problem) => /frozen input is not valid JSON/.test(problem)));
});

test('a runtime parameter the descriptor requires blocks the submission', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.selectKind('prompt_template');
  view.setParam('template', 'Draft a reply to {ticket}.');

  assert.deepEqual(view.problems(), ['provider is required by this runtime.']);
  view.submit();
  assert.deepEqual(api.created, []);

  view.setParam('provider', 'mistral');
  assert.deepEqual(view.problems(), ['provider must be one of: azure, ollama.']);

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

test('a complete draft posts exactly what the workspace decided', () => {
  const { view, api } = dialog();
  fillIdentity(view);
  view.description.set('Records the reset in the ledger.');
  view.category.set('Automation');
  view.inputSchema.set('{"type":"object","properties":{"details":{"type":"object"}}}');
  view.outputSchema.set('');
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
  }]);

  api.responses[0].next({ ...AUDIT_LOG, id: 'authored', slug: 'ws.ws-nawa.reset_ticket', name: 'Reset a ticket' });
  assert.equal(view.submitting(), false);
  assert.equal(emitted[0].slug, 'ws.ws-nawa.reset_ticket');
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
}) {
  const pages = options.pages ?? [[AUDIT_LOG]];
  let call = 0;
  const canonical = {
    listSkills: () => of(pages[Math.min(call++, pages.length - 1)]),
    getSkillExecutors: () => (options.executors === 'unreachable'
      ? throwError(() => new Error('offline'))
      : of(options.executors ?? CATALOG)),
    getCapability: () => of(null),
    getSystem: () => of(null),
    getRun: () => of(null),
  };
  const params = new BehaviorSubject(convertToParamMap({}));
  const workspace = new WorkspaceStub();
  const injector = Injector.create({
    providers: [
      SkillsComponent,
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: workspace },
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
  return { view: injector.get(SkillsComponent), workspace, calls: () => call };
}

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
  const authored: Skill = {
    id: 'authored',
    slug: 'ws.ws-nawa.reset_ticket',
    name: 'Reset a ticket',
    executor: { kind: 'registry_call' },
  };
  const { view, calls } = registry({ pages: [[AUDIT_LOG], [AUDIT_LOG, authored]] });
  view.ngOnInit();
  view.openAuthoring();

  view.onAuthored(authored);

  assert.equal(calls(), 2, 'the list is re-read so the new row exists on the surface');
  assert.equal(view.authoring(), false);
  assert.equal(view.selected()?.slug, 'ws.ws-nawa.reset_ticket');
  assert.match(view.authoredNotice()!, /ws\.ws-nawa\.reset_ticket created/);
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
