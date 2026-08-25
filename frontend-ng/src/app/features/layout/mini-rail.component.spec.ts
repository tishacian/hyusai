import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import {
  navigationRouteContext,
  navigationScopeUrl,
  type CockpitLens,
  type CockpitSection,
} from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { MiniRailComponent } from './mini-rail.component';

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

test('clicking the active mini-rail scope is a strict no-op', () => {
  const lens = signal<CockpitLens>('operate');
  const route = signal(navigationRouteContext('/runs?systemId=sys-42&scope=runs'));
  const scope = signal<'runs'>('runs');
  const ancestry = {
    capabilityId: 'cap-42',
    systemId: 'sys-42',
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
          capabilityLabel: () => 'Capability',
          systemLabel: () => 'System',
          runLabel: () => null,
          skillInvocationLabel: () => null,
          skillLabel: () => null,
          urlForScope: (section: CockpitSection) => navigationScopeUrl(section, ancestry, lens()),
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(MiniRailComponent);
  const runs = rail.visibleSections().find((section) => section.key === 'runs')!;
  let prevented = false;
  let stopped = false;
  rail.onItemClick({
    preventDefault: () => { prevented = true; },
    stopPropagation: () => { stopped = true; },
  } as unknown as MouseEvent, runs);
  assert.equal(prevented, true);
  assert.equal(stopped, true);
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
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  assert.deepEqual(injector.get(MiniRailComponent).visibleSections(), []);
});

test('experience_v1 Build menu is grouped Create plus library and has no Flow entry', () => {
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
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(MiniRailComponent);
  const keys = rail.visibleSections().map((section) => section.key);
  assert.deepEqual(keys, [
    'business_apps',
    'systems',
    'knowledge',
    'data',
    'models',
    'capabilities',
    'skills',
    'certified',
    'integrations',
  ]);
  assert.equal(rail.sectionGroupLabel(rail.visibleSections()[0], 0), 'nav.group.create');
  assert.equal(rail.sectionGroupLabel(rail.visibleSections()[5], 5), 'nav.group.library');
  assert.equal(rail.sectionLabel(rail.visibleSections()[0]), 'Business application');
});
