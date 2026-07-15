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
          loading: () => false,
          route,
          scope,
          capabilityId: () => ancestry.capabilityId,
          systemId: () => ancestry.systemId,
          runId: () => ancestry.runId,
          skillRef: () => ancestry.skillRef,
          capabilityLabel: () => 'Contract Risk',
          systemLabel: () => null,
          runLabel: () => null,
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
          loading: () => false,
          route,
          scope,
          capabilityId: () => ancestry.capabilityId,
          systemId: () => ancestry.systemId,
          runId: () => ancestry.runId,
          skillRef: () => ancestry.skillRef,
          capabilityLabel: () => 'Capability',
          systemLabel: () => 'System',
          runLabel: () => null,
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
          loading: () => false,
          route: () => navigationRouteContext('/runs', false),
          scope: () => null,
          capabilityId: () => null,
          systemId: () => null,
          runId: () => null,
          skillRef: () => null,
          capabilityLabel: () => null,
          systemLabel: () => null,
          runLabel: () => null,
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
