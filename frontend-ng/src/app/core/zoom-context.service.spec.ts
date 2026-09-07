import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { NavigationEnd, Router, type UrlTree } from '@angular/router';
import { Subject, of } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Run,
  type Skill,
  type SkillInvocation,
  type System,
} from './canonical-api.service';
import { WorkspaceService, type WorkspaceContextTransition } from './workspace.service';
import { COCKPIT_VERBS } from './navigation.catalog';
import { ZoomContextService } from './zoom-context.service';

class RouterStub {
  readonly events = new Subject<unknown>();
  readonly parsedUrls: string[] = [];
  url: string;
  private navigationId = 0;

  constructor(url: string) {
    this.url = url;
  }

  navigate(url: string): void {
    this.url = url;
    this.navigationId += 1;
    this.events.next(new NavigationEnd(this.navigationId, url, url));
  }

  parseUrl(url: string): UrlTree {
    this.parsedUrls.push(url);
    return { toString: () => url } as unknown as UrlTree;
  }
}

class WorkspaceStub {
  readonly contextRefresh$ = new Subject<void>();
  private slug = 'workspace-a';
  private epoch = 1;
  private axesEnabled = true;
  private axesV4 = false;
  private navV5 = false;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  currentSlug = () => this.slug;
  contextEpoch = () => this.epoch;
  current = () => ({
    id: `id-${this.slug}`,
    slug: this.slug,
    name: this.slug === 'workspace-a' ? 'Workspace A' : 'Workspace B',
    settings: { features: {
      cockpit_router_axes_v3: this.axesEnabled,
      cockpit_router_axes_v4: this.axesV4,
      cockpit_nav_v5: this.navV5,
    } },
  });

  captureRequestScope() {
    return Object.freeze({ workspaceSlug: this.slug, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: { workspaceSlug: string | null; epoch: number }): boolean {
    return scope.workspaceSlug === this.slug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  setAxesEnabled(enabled: boolean): void {
    this.axesEnabled = enabled;
  }

  setAxesV4Enabled(enabled: boolean): void {
    this.axesV4 = enabled;
  }

  setNavV5Enabled(enabled: boolean): void {
    this.navV5 = enabled;
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

function graphHarness(url: string, options: { axesV4?: boolean; navV5?: boolean } = {}) {
  const router = new RouterStub(url);
  const workspace = new WorkspaceStub();
  workspace.setAxesV4Enabled(options.axesV4 === true);
  workspace.setNavV5Enabled(options.navV5 === true);
  const capability: Capability = {
    id: 'cap-real',
    slug: 'contract-risk',
    name: 'Contract Risk',
    skill_ids: ['skill-id'],
  };
  const system: System = {
    id: 'sys-real',
    name: 'Contract Risk Copilot',
    capability_id: capability.id,
    skill_ids: ['skill-id'],
  };
  const run: Run = {
    id: 'run-real',
    system_id: system.id,
    capability_id: capability.id,
    status: 'completed',
    skill_invocations: [{
      id: 'inv-real',
      run_id: 'run-real',
      skill_slug: 'contract_extract_v1',
      status: 'completed',
    }],
  };
  const invocation: SkillInvocation = run.skill_invocations![0];
  const skill: Skill = {
    id: 'skill-id',
    slug: 'contract_extract_v1',
    name: 'Contract Extract',
  };
  const canonical = {
    getRun: (id: string) => of(id === run.id ? run : null),
    getSkillInvocation: (runId: string, invocationId: string) => of(
      runId === run.id && invocationId === invocation.id ? invocation : null,
    ),
    getSystem: (id: string) => of(id === system.id ? system : null),
    getCapability: (id: string) => of(id === capability.id ? capability : null),
    getSkill: (slug: string) => of(
      slug === skill.slug
        ? skill
        : {
            ...skill,
            id: slug === 'configured-not-invoked' ? skill.id : 'other-id',
            slug,
            name: 'Other Skill',
          },
    ),
  };
  const injector = Injector.create({
    providers: [
      ZoomContextService,
      { provide: Router, useValue: router },
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: canonical },
    ],
  });
  return { router, workspace, navigation: injector.get(ZoomContextService) };
}

test('Run deep link resolves the real Capability → System → Run graph and keeps the lens', () => {
  const { navigation } = graphHarness(
    '/runs/run-real?lens=steer&systemId=spoof-system&capabilityId=spoof-capability',
  );

  assert.equal(navigation.lens(), 'steer');
  assert.equal(navigation.capabilityId(), 'cap-real');
  assert.equal(navigation.systemId(), 'sys-real');
  assert.equal(navigation.runId(), 'run-real');
  assert.deepEqual(
    navigation.nodes().map((node) => [node.key, node.label]),
    [
      ['portfolio', 'Portfolio'],
      ['capability', 'Contract Risk'],
      ['system', 'Contract Risk Copilot'],
      ['run', 'Run · run-real'],
    ],
  );
  for (const node of navigation.nodes()) {
    assert.match(node.href, /(?:\?|&)lens=steer(?:&|$)/);
  }
});

test('SkillInvocation deep link resolves a runtime leaf without becoming a catalog Skill', () => {
  const { navigation } = graphHarness(
    '/runs/run-real/invocations/inv-real?lens=govern&systemId=spoof&capabilityId=spoof',
  );

  assert.equal(navigation.lens(), 'govern');
  assert.equal(navigation.capabilityId(), 'cap-real');
  assert.equal(navigation.systemId(), 'sys-real');
  assert.equal(navigation.runId(), 'run-real');
  assert.equal(navigation.skillInvocationId(), 'inv-real');
  assert.equal(navigation.skillRef(), null);
  assert.equal(navigation.deepestResolvedType(), 'skill_invocation');
  assert.deepEqual(navigation.nodes().map((node) => node.key), [
    'portfolio',
    'capability',
    'system',
    'run',
    'skill_invocation',
  ]);
  assert.equal(
    navigation.urlForLens('steer', '/steering'),
    '/runs/run-real/invocations/inv-real?lens=steer&capabilityId=cap-real&systemId=sys-real',
  );
});

test('a catalog Skill is not attached to a Run that never invoked it', () => {
  const { navigation } = graphHarness('/skills/not-in-run?runId=run-real&lens=operate');

  assert.equal(navigation.capabilityId(), null);
  assert.equal(navigation.systemId(), null);
  assert.equal(navigation.runId(), null);
  assert.equal(navigation.skillRef(), 'not-in-run');
  assert.deepEqual(navigation.nodes().map((node) => node.key), ['portfolio', 'skill']);
});

test('a Skill configured on the System is still rejected when the selected Run never invoked it', () => {
  const { navigation } = graphHarness(
    '/skills/configured-not-invoked?runId=run-real&lens=operate',
  );

  assert.equal(navigation.capabilityId(), null);
  assert.equal(navigation.systemId(), null);
  assert.equal(navigation.runId(), null);
  assert.equal(navigation.skillRef(), 'configured-not-invoked');
  assert.deepEqual(navigation.nodes().map((node) => node.key), ['portfolio', 'skill']);
});

test('a scoped Skill list cannot forge a Skill edge under a Run that never invoked it', () => {
  const { navigation } = graphHarness(
    '/skills?scope=skills&skillRef=configured-not-invoked&runId=run-real&lens=operate',
  );

  assert.equal(navigation.capabilityId(), null);
  assert.equal(navigation.systemId(), null);
  assert.equal(navigation.runId(), null);
  assert.equal(navigation.skillRef(), 'configured-not-invoked');
  assert.deepEqual(navigation.nodes().map((node) => node.key), ['portfolio', 'skill']);
});

test('scoped-list rail clicks are inert while canonical ancestry is still loading', () => {
  const router = new RouterStub(
    '/runs?scope=runs&capabilityId=cap-pending&systemId=sys-pending&lens=operate',
  );
  const workspace = new WorkspaceStub();
  const pendingSystem = new Subject<System | null>();
  const canonical = {
    getRun: () => of(null),
    getSkill: () => of(null),
    getSystem: () => pendingSystem,
    getCapability: () => of(null),
  };
  const injector = Injector.create({
    providers: [
      ZoomContextService,
      { provide: Router, useValue: router },
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: canonical },
    ],
  });
  const navigation = injector.get(ZoomContextService);
  const runs = COCKPIT_VERBS
    .find((verb) => verb.key === 'operate')!
    .sections!
    .find((section) => section.key === 'runs')!;

  assert.equal(navigation.loading(), true);
  assert.equal(navigation.urlForLens('steer', '/steering'), router.url);
  assert.equal(navigation.urlForScope(runs), router.url);
});

test('global object jumps clear the previous ancestry and UrlTree parsing keeps query separators', () => {
  const { router, navigation } = graphHarness('/runs/run-real?lens=steer');

  assert.equal(navigation.objectUrl('system', 'system-b'), '/systems/system-b?lens=steer');
  const tree = navigation.urlTreeForLens('govern', '/governance');
  assert.equal(
    router.parsedUrls.at(-1),
    '/runs/run-real?lens=govern&capabilityId=cap-real&systemId=sys-real',
  );
  assert.equal(tree.toString(), router.parsedUrls.at(-1));
  assert.doesNotMatch(router.parsedUrls.at(-1)!, /%3F/);
});

test('axes v4 sends Hypervisor to Portfolio while object lenses keep the selected System', () => {
  const { navigation } = graphHarness(
    '/systems/sys-real?lens=operate&facet=runs',
    { axesV4: true },
  );

  assert.equal(navigation.urlForLens('hypervisor', '/wrong'), '/hypervisor');
  assert.equal(
    navigation.urlForLens('steer', '/steering'),
    '/systems/sys-real?facet=runs&lens=steer&capabilityId=cap-real',
  );
  assert.equal(navigation.nodes()[0].href, '/hypervisor');
});

test('the selected System path rejects a Run query from another branch', () => {
  const router = new RouterStub('/systems/system-b?runId=run-from-a&systemId=system-a&capabilityId=cap-a&lens=operate');
  const workspace = new WorkspaceStub();
  let runReads = 0;
  const canonical = {
    getRun: () => {
      runReads += 1;
      return of({ id: 'run-from-a', system_id: 'system-a', capability_id: 'cap-a', status: 'completed' } satisfies Run);
    },
    getSystem: (id: string) => of(id === 'system-b'
      ? { id, name: 'System B', capability_id: 'cap-b' } satisfies System
      : null),
    getCapability: (id: string) => of(id === 'cap-b'
      ? { id, slug: 'cap-b', name: 'Capability B' } satisfies Capability
      : null),
    getSkill: () => of(null),
  };
  const injector = Injector.create({
    providers: [
      ZoomContextService,
      { provide: Router, useValue: router },
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: canonical },
    ],
  });
  const navigation = injector.get(ZoomContextService);

  assert.equal(runReads, 0);
  assert.equal(navigation.capabilityId(), 'cap-b');
  assert.equal(navigation.systemId(), 'system-b');
  assert.equal(navigation.runId(), null);
  assert.deepEqual(navigation.nodes().map((node) => [node.key, node.label]), [
    ['portfolio', 'Portfolio'],
    ['capability', 'Capability B'],
    ['system', 'System B'],
  ]);
});

test('an unflagged workspace ignores routed axes and emits legacy object links', () => {
  const router = new RouterStub('/systems/sys-real?lens=operate&runId=run-real');
  const workspace = new WorkspaceStub();
  workspace.setAxesEnabled(false);
  const canonical = {
    getRun: () => of(null),
    getSystem: () => of({ id: 'sys-real', name: 'System', capability_id: null } satisfies System),
    getCapability: () => of(null),
    getSkill: () => of(null),
  };
  const injector = Injector.create({
    providers: [
      ZoomContextService,
      { provide: Router, useValue: router },
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: canonical },
    ],
  });
  const navigation = injector.get(ZoomContextService);

  assert.equal(navigation.lens(), 'build');
  assert.equal(navigation.scope(), null);
  assert.equal(navigation.runId(), null);
  assert.equal(
    navigation.objectUrl('skill', 'skill-a', {
      capabilityId: 'cap-a',
      systemId: 'sys-real',
      runId: 'run-real',
      lens: 'operate',
      scope: 'skills',
    }),
    '/skills/skill-a',
  );
});

const flowsSection = () => COCKPIT_VERBS
  .find((verb) => verb.key === 'build')!
  .sections!
  .find((section) => section.key === 'flows')!;

test('nav v5 zone sommaire omits ?scope= (I5)', () => {
  const { navigation } = graphHarness('/systems/sys-real?lens=operate', { navV5: true });
  const runs = COCKPIT_VERBS.find((verb) => verb.key === 'operate')!.sections!.find((section) => section.key === 'runs')!;
  const url = navigation.urlForScope(runs);
  assert.equal(url.split('?')[0], '/runs');
  assert.equal(new URL(url, 'https://agentium.local').searchParams.get('scope'), null);
});

test('Flow builder follows the proven System, else the scratchpad — never session memory', () => {
  const { router, navigation } = graphHarness('/systems/sys-real?lens=build');
  const flows = flowsSection();

  assert.equal(navigation.systemId(), 'sys-real');
  assert.equal(navigation.urlForScope(flows).split('?')[0], '/systems/sys-real/flow');

  router.navigate('/skills');
  assert.equal(navigation.systemId(), null);
  assert.equal(navigation.urlForScope(flows).split('?')[0], '/orchestration');
});

test('parentUrl is the breadcrumb parent (D6)', () => {
  const { navigation } = graphHarness('/runs/run-real?lens=operate');
  assert.equal(navigation.parentLabel(), 'Contract Risk Copilot');
  assert.equal(navigation.parentUrl().split('?')[0], '/systems/sys-real');
});

test('parentUrl of a non-hierarchy object is its catalog list', () => {
  const { navigation } = graphHarness('/knowledge/kb-1?lens=operate');
  assert.equal(navigation.parentUrl().split('?')[0], '/knowledge');
});

test('workspace reset clears synchronously and ignores the late graph from the old epoch', async () => {
  const router = new RouterStub('/systems/shared-id?lens=operate');
  const workspace = new WorkspaceStub();
  const systemReads: Array<Subject<System | null>> = [];
  const canonical = {
    getRun: () => of(null),
    getSkill: () => of(null),
    getSystem: () => {
      const response = new Subject<System | null>();
      systemReads.push(response);
      return response;
    },
    getCapability: (id: string) => of({
      id,
      slug: id,
      name: id === 'cap-b' ? 'Capability B' : 'Capability A',
    } satisfies Capability),
  };
  const injector = Injector.create({
    providers: [
      ZoomContextService,
      { provide: Router, useValue: router },
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: canonical },
    ],
  });
  const navigation = injector.get(ZoomContextService);
  assert.equal(systemReads.length, 1);

  workspace.switchWorkspace();
  assert.equal(navigation.systemId(), null, 'A is purged before B becomes current');
  assert.deepEqual(navigation.nodes().map((node) => node.key), ['portfolio']);
  assert.equal(navigation.nodes()[0].id, null);
  assert.equal(navigation.nodes()[0].sub, 'Workspace portfolio');

  await Promise.resolve();
  assert.equal(systemReads.length, 2);
  systemReads[1].next({
    id: 'shared-id',
    name: 'System B',
    capability_id: 'cap-b',
  });
  systemReads[1].complete();
  assert.equal(navigation.systemLabel(), 'System B');
  assert.equal(navigation.capabilityLabel(), 'Capability B');

  systemReads[0].next({
    id: 'shared-id',
    name: 'Late System A',
    capability_id: 'cap-a',
  });
  systemReads[0].complete();
  assert.equal(navigation.systemLabel(), 'System B');
  assert.equal(navigation.capabilityLabel(), 'Capability B');
});
