import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import {
  navigationRouteContext,
  navigationScopeUrl,
  navigationZoneSurfaceUrl,
  type CockpitLens,
  type CockpitSection,
} from '@app/core/navigation.catalog';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { MiniRailComponent } from './mini-rail.component';

const workspaceStub = { mode: () => 'executive' as const, isBuilderMode: () => false };

test('Capability scope hides its own level and routes Systems inside the same ancestry', () => {
  const lens = signal<CockpitLens>('build');
  const route = signal(navigationRouteContext('/capabilities/cap-42'));
  const scope = signal<string | null>(null);
  const ancestry = {
    capabilityId: 'cap-42',
    systemId: null,
    runId: null,
    skillInvocationId: null,
    skillRef: null,
  };
  const injector = Injector.create({
    providers: [
      MiniRailComponent,
      {
        provide: ZoomContextService,
        useValue: {
          lens,
          axesV3Enabled: () => true,
          axesV4Enabled: () => false,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
          loading: () => false,
          route,
          scope,
          capabilityId: () => ancestry.capabilityId,
          systemId: () => ancestry.systemId,
          runId: () => ancestry.runId,
          skillInvocationId: () => ancestry.skillInvocationId,
          skillRef: () => ancestry.skillRef,
          capabilityLabel: () => 'Contract Risk',
          systemLabel: () => null,
          runLabel: () => null,
          skillInvocationLabel: () => null,
          skillLabel: () => null,
          urlForScope: (section: CockpitSection) => navigationScopeUrl(section, ancestry, lens()),
        },
      },
      { provide: WorkspaceService, useValue: workspaceStub },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(MiniRailComponent);
  assert.equal(rail.visibleSections().some((section) => section.key === 'capabilities'), false);
  assert.equal(rail.visibleSections().some((section) => section.key === 'knowledge'), false);
  assert.equal(rail.visibleSections().some((section) => section.key === 'flows'), true);
  const systems = rail.visibleSections().find((section) => section.key === 'systems')!;
  const parsed = navigationRouteContext(rail.routeFor(systems));
  assert.equal(parsed.path, '/systems');
  assert.equal(parsed.capabilityId, 'cap-42');
  assert.equal(parsed.scope, 'systems');
});

/** The nav v5 Create sommaire on `path`, recording the triggers it registers. */
function createSommaire(path: string, triggers: string[]): MiniRailComponent {
  const injector = Injector.create({
    providers: [
      MiniRailComponent,
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'build',
          axesV3Enabled: () => true,
          axesV4Enabled: () => true,
          navV5Enabled: () => true,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
          loading: () => false,
          route: () => navigationRouteContext(path),
          scope: () => null,
          urlForScope: (section: CockpitSection) => navigationZoneSurfaceUrl(section, 'build'),
        },
      },
      {
        provide: NavigationTelemetryService,
        useValue: { registerTrigger: (trigger: string) => triggers.push(trigger) },
      },
      { provide: WorkspaceService, useValue: workspaceStub },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  return injector.get(MiniRailComponent);
}

function withDocument(value: unknown, run: () => void): void {
  const previous = globalThis.document;
  Object.defineProperty(globalThis, 'document', { configurable: true, value });
  try {
    run();
  } finally {
    if (previous) {
      Object.defineProperty(globalThis, 'document', { configurable: true, value: previous });
    } else {
      Reflect.deleteProperty(globalThis, 'document');
    }
  }
}

test('the active item leads back to its list from a child', () => {
  const triggers: string[] = [];
  const rail = createSommaire('/systems/sys-42', triggers);
  const systems = rail.visibleSections().find((section) => section.key === 'systems')!;
  assert.equal(rail.isSectionActive(systems), true);
  assert.equal(rail.routeFor(systems), '/systems');

  rail.onItemClick(systems);
  assert.deepEqual(triggers, ['minirail']);
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/layout/mini-rail.component.ts'),
    'utf8',
  );
  assert.doesNotMatch(source, /preventDefault/, 'nothing in the sommaire may cancel its links');
});

test('on the list itself, the active item returns to the top without navigating', () => {
  const triggers: string[] = [];
  const rail = createSommaire('/systems', triggers);
  const systems = rail.visibleSections().find((section) => section.key === 'systems')!;
  // The link is the current URL, so the router ignores it.
  assert.equal(rail.routeFor(systems), '/systems');

  const attributes = new Map<string, string>();
  let headingFocus: FocusOptions | undefined;
  const heading = {
    hasAttribute: (name: string) => attributes.has(name),
    setAttribute: (name: string, value: string) => attributes.set(name, value),
    focus: (options?: FocusOptions) => { headingFocus = options; },
  };
  const main = {
    scrollTop: 480,
    querySelector: (selector: string) => (selector === 'h1' ? heading : null),
    focus: () => assert.fail('the title takes the focus, not main'),
  };
  withDocument(
    { getElementById: (id: string) => (id === 'main-content' ? main : null) },
    () => rail.onItemClick(systems),
  );
  assert.equal(main.scrollTop, 0);
  assert.equal(attributes.get('tabindex'), '-1');
  assert.deepEqual(headingFocus, { preventScroll: true });
  assert.deepEqual(triggers, []);
});

test('Data and Models light up on their own list only, and each opens its own', () => {
  const onData = createSommaire('/data', []);
  const models = onData.visibleSections().find((section) => section.key === 'models')!;
  assert.equal(onData.isSectionActive(models), false);
  assert.equal(onData.routeFor(models), '/models');

  const onModel = createSommaire('/models/m-1', []);
  assert.deepEqual(
    onModel.visibleSections()
      .filter((section) => onModel.isSectionActive(section))
      .map((section) => section.key),
    ['models'],
  );
});

test('an unflagged workspace keeps the historical Operate section set', () => {
  const injector = Injector.create({
    providers: [
      MiniRailComponent,
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'operate',
          axesV3Enabled: () => false,
          axesV4Enabled: () => false,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
          loading: () => false,
          route: () => navigationRouteContext('/runs', false),
          scope: () => null,
          capabilityId: () => null,
          systemId: () => null,
          runId: () => null,
          skillInvocationId: () => null,
          skillRef: () => null,
          capabilityLabel: () => null,
          systemLabel: () => null,
          runLabel: () => null,
          skillInvocationLabel: () => null,
          skillLabel: () => null,
          urlForScope: (section: CockpitSection) => section.route,
        },
      },
      { provide: WorkspaceService, useValue: workspaceStub },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  assert.deepEqual(
    injector.get(MiniRailComponent).visibleSections().map((section) => section.key),
    ['runs', 'observability', 'intelligence', 'missions'],
  );
});

/** Both rails branches (axes-v3 `sections` and the legacy set NAWA runs) must
 *  name the Flow entry after whatever `urlForScope` resolved. */
function railWithFlowScope(axesV3: boolean, systemId: string | null): MiniRailComponent {
  const ancestry = {
    capabilityId: null,
    systemId,
    runId: null,
    skillInvocationId: null,
    skillRef: null,
  };
  const injector = Injector.create({
    providers: [
      MiniRailComponent,
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'build',
          axesV3Enabled: () => axesV3,
          axesV4Enabled: () => false,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
          loading: () => false,
          route: () => navigationRouteContext('/skills', axesV3),
          scope: () => null,
          capabilityId: () => ancestry.capabilityId,
          systemId: () => ancestry.systemId,
          runId: () => ancestry.runId,
          skillInvocationId: () => ancestry.skillInvocationId,
          skillRef: () => ancestry.skillRef,
          capabilityLabel: () => null,
          systemLabel: () => null,
          runLabel: () => null,
          skillInvocationLabel: () => null,
          skillLabel: () => null,
          urlForScope: (section: CockpitSection) => (
            section.key === 'flows' && systemId
              ? `/systems/${systemId}/flow`
              : section.route
          ),
        },
      },
      { provide: WorkspaceService, useValue: workspaceStub },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  return injector.get(MiniRailComponent);
}

test('the Flow entry reads Scratchpad only while it opens the scratchpad', () => {
  for (const axesV3 of [true, false]) {
    const scratchpad = railWithFlowScope(axesV3, null);
    const flows = scratchpad.visibleSections().find((section) => section.key === 'flows')!;
    assert.equal(scratchpad.sectionLabel(flows), 'Scratchpad', `axesV3=${axesV3}`);

    const opened = railWithFlowScope(axesV3, 'sys-42');
    const openedFlows = opened.visibleSections().find((section) => section.key === 'flows')!;
    assert.equal(opened.sectionLabel(openedFlows), 'Flow builder', `axesV3=${axesV3}`);

    // The section key and glyph are the rail's identity — naming must not move them.
    assert.equal(openedFlows.key, 'flows');
    assert.equal(openedFlows.glyph, flows.glyph);
  }
});

test('sections other than Flow are named from the catalog whatever the URL', () => {
  const rail = railWithFlowScope(true, null);
  const systems = rail.visibleSections().find((section) => section.key === 'systems')!;
  const skills = rail.visibleSections().find((section) => section.key === 'skills')!;

  assert.equal(rail.sectionLabel(systems), 'Systems');
  assert.equal(rail.sectionLabel(skills), 'Skills');
});

test('axes v4 exposes no object index under the Portfolio-only Hypervisor destination', () => {
  const injector = Injector.create({
    providers: [
      MiniRailComponent,
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'hypervisor',
          axesV3Enabled: () => true,
          axesV4Enabled: () => true,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
          loading: () => false,
          route: () => navigationRouteContext('/hypervisor'),
          scope: () => null,
          capabilityId: () => null,
          systemId: () => null,
          runId: () => null,
          skillInvocationId: () => null,
          skillRef: () => null,
          capabilityLabel: () => null,
          systemLabel: () => null,
          runLabel: () => null,
          skillInvocationLabel: () => null,
          skillLabel: () => null,
          urlForScope: (section: CockpitSection) => section.route,
        },
      },
      { provide: WorkspaceService, useValue: workspaceStub },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  assert.deepEqual(injector.get(MiniRailComponent).visibleSections(), []);
});

test('experience studio prepends Business application to the Create catalogues', () => {
  const injector = Injector.create({
    providers: [
      MiniRailComponent,
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'build',
          axesV3Enabled: () => true,
          axesV4Enabled: () => false,
          experienceV1Enabled: () => true,
          experienceStudioV1Enabled: () => true,
          loading: () => false,
          route: () => navigationRouteContext('/create'),
          scope: () => null,
          capabilityId: () => null,
          systemId: () => null,
          runId: () => null,
          skillInvocationId: () => null,
          skillRef: () => null,
          capabilityLabel: () => null,
          systemLabel: () => null,
          runLabel: () => null,
          skillInvocationLabel: () => null,
          skillLabel: () => null,
          urlForScope: (section: CockpitSection) => section.route,
        },
      },
      { provide: WorkspaceService, useValue: workspaceStub },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(MiniRailComponent);
  const keys = rail.visibleSections().map((section) => section.key);
  assert.deepEqual(keys, [
    'business_apps',
    'systems',
    'capabilities',
    'skills',
    'knowledge',
    'data',
    'models',
    'flows',
  ]);
  assert.equal(rail.sectionLabel(rail.visibleSections()[0]), 'Business application');
});

test('nav v5 Operate sommaire has no object ladder and exposes a System facet branch (I1)', () => {
  const injector = Injector.create({
    providers: [
      MiniRailComponent,
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'operate',
          axesV3Enabled: () => true,
          axesV4Enabled: () => true,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
          navV5Enabled: () => true,
          loading: () => false,
          route: () => navigationRouteContext('/systems/sys-x?lens=operate&facet=runs'),
          scope: () => null,
          capabilityId: () => 'cap-a',
          systemId: () => 'sys-x',
          runId: () => null,
          skillInvocationId: () => null,
          skillRef: () => null,
          capabilityLabel: () => 'Cap',
          systemLabel: () => 'System X',
          runLabel: () => null,
          skillInvocationLabel: () => null,
          skillLabel: () => null,
          deepestResolvedType: () => 'system',
          urlForScope: (section: CockpitSection) => section.route,
        },
      },
      { provide: WorkspaceService, useValue: workspaceStub },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(MiniRailComponent);
  const forbidden = new Set(['capability', 'system', 'run', 'skill']);
  assert.equal(
    rail.visibleSections().some((section) => forbidden.has(section.scopeType)),
    false,
  );
  assert.equal(rail.stableLayout(), true);
  const branch = rail.systemBranch();
  assert.ok(branch);
  assert.deepEqual(branch.facets.map((facet) => facet.id), [
    'overview',
    'runs',
    'design',
    'context',
  ]);
  assert.equal(branch.activeId, 'runs');
});
