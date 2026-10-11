import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { AdoptionService } from '@app/core/adoption.service';
import type { RailLabelsPreference } from '@app/core/rail-labels';
import { SideRailComponent } from './side-rail.component';

test('side rail delegates every lens route to the route-owned navigation projection', () => {
  const lens = signal<'hypervisor' | 'build' | 'operate' | 'steer' | 'govern'>('operate');
  const calls: Array<[string, string]> = [];
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: {
          mode: () => 'portfolio',
          isDemoMode: () => false,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
        },
      },
      {
        provide: ZoomContextService,
        useValue: {
          lens,
          axesV4Enabled: () => false,
          urlForLens: (target: string, fallback: string) => {
            calls.push([target, fallback]);
            return `/systems/system-42?lens=${target}`;
          },
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(SideRailComponent);
  const operate = rail.visibleVerbs().find((verb) => verb.key === 'operate')!;
  const govern = rail.visibleVerbs().find((verb) => verb.key === 'govern')!;

  assert.equal(rail.isActive(operate), true);
  assert.equal(rail.isActive(govern), false);
  assert.equal(rail.routeFor(govern), '/systems/system-42?lens=govern');
  assert.deepEqual(calls, [['govern', '/governance']]);
});

test('demo rail always opens Impact Portfolio, never Mission Room', () => {
  let current = {
    mode: 'demo',
    settings: { mission_room: { enabled: true } },
  };
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: {
          current: () => current,
          mode: () => 'demo',
          isDemoMode: () => true,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
        },
      },
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'hypervisor',
          axesV4Enabled: () => false,
          urlForLens: (_target: string, fallback: string) => fallback,
          urlTreeForLens: (_target: string, fallback: string) => fallback,
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(SideRailComponent);
  const hypervisor = rail.visibleVerbs().find((verb) => verb.key === 'hypervisor')!;

  assert.equal(rail.routeFor(hypervisor), '/hypervisor');

  current = { mode: 'demo', settings: { mission_room: { enabled: false } } };
  assert.equal(rail.routeFor(hypervisor), '/hypervisor');
});

test('axes v4 makes Hypervisor the Portfolio home even in a demo workspace', () => {
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: {
          current: () => ({ mode: 'demo', settings: { mission_room: { enabled: true } } }),
          mode: () => 'demo',
          isDemoMode: () => true,
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
        },
      },
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'operate',
          axesV4Enabled: () => true,
          urlForLens: (_target: string, fallback: string) => fallback,
          urlTreeForLens: (_target: string, fallback: string) => fallback,
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(SideRailComponent);
  const hypervisor = rail.visibleVerbs().find((verb) => verb.key === 'hypervisor')!;
  assert.equal(rail.routeFor(hypervisor), '/hypervisor');
});

test('experience_v1 Build verb opens the first Create sommaire entry', () => {
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: {
          mode: () => 'portfolio',
          isDemoMode: () => false,
          current: () => ({settings:{features:{}}}),
          experienceV1Enabled: () => true,
          experienceStudioV1Enabled: () => true,
        },
      },
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'build',
          axesV4Enabled: () => false,
          urlForLens: (_target: string, fallback: string) => fallback,
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(SideRailComponent);
  const build = rail.visibleVerbs().find((verb) => verb.key === 'build')!;
  assert.equal(rail.routeFor(build), '/create/apps');
  assert.equal(rail.verbLabel(build), 'experience.adoption.nav.build');
});

test('each rail item aria-label equals the adoption zone name', () => {
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: {
          mode: () => 'portfolio',
          isDemoMode: () => false,
          current: () => ({ settings: { features: {} } }),
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
        },
      },
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'operate',
          axesV4Enabled: () => false,
          urlForLens: (_target: string, fallback: string) => fallback,
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(SideRailComponent);
  for (const verb of rail.visibleVerbs()) {
    assert.equal(
      rail.verbLabel(verb),
      `experience.adoption.nav.${verb.key}`,
      `aria-label source for ${verb.key}`,
    );
  }
  assert.equal(rail.paletteLabel(), 'nav.rail.search');
  assert.equal(rail.paletteTooltip(), 'nav.rail.search.tooltip');
  assert.equal(rail.labelsToggleLabel(), 'nav.rail.labels.toggle');
});

test('side rail has no expanded state', () => {
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: {
          mode: () => 'portfolio',
          isDemoMode: () => false,
          current: () => ({ settings: { features: {} } }),
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
        },
      },
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'operate',
          axesV4Enabled: () => false,
          urlForLens: (_target: string, fallback: string) => fallback,
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const rail = injector.get(SideRailComponent) as SideRailComponent & { expanded?: unknown };
  assert.equal('expanded' in rail, false);
  assert.equal(rail.expanded, undefined);
  assert.equal(rail.tooltipKey(), null);
});

function railWithAdoption(adoption: unknown): SideRailComponent {
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: {
          mode: () => 'portfolio',
          isDemoMode: () => false,
          current: () => ({ settings: { features: {} } }),
          experienceV1Enabled: () => false,
          experienceStudioV1Enabled: () => false,
        },
      },
      {
        provide: ZoomContextService,
        useValue: {
          lens: () => 'operate',
          axesV4Enabled: () => false,
          urlForLens: (_target: string, fallback: string) => fallback,
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
      { provide: AdoptionService, useValue: adoption },
    ],
  });
  return injector.get(SideRailComponent);
}

test('L27 — no labels and no toggle while the preference is unknown', () => {
  const visible = signal<boolean | null>(null);
  const rail = railWithAdoption({
    enabled: () => true,
    railLabelsVisible: visible,
    railLabelsError: () => false,
    setRailLabels: () => undefined,
  });
  assert.equal(rail.labelsVisible(), false, 'never flash labels before the record is known');
  assert.equal(rail.labelsToggleAvailable(), false);
  visible.set(false);
  assert.equal(rail.labelsVisible(), false);
  assert.equal(rail.labelsToggleAvailable(), true, 'an expert can turn labels on');
});

test('L27 — the toggle writes the opposite of what the rail shows', () => {
  const visible = signal<boolean | null>(true);
  const writes: RailLabelsPreference[] = [];
  const rail = railWithAdoption({
    enabled: () => true,
    railLabelsVisible: visible,
    railLabelsError: () => false,
    setRailLabels: (value: RailLabelsPreference) => {
      writes.push(value);
      visible.set(value === 'shown');
    },
  });
  assert.equal(rail.labelsVisible(), true);
  rail.toggleLabels();
  assert.equal(rail.labelsVisible(), false);
  rail.toggleLabels();
  assert.deepEqual(writes, ['hidden', 'shown']);
  assert.equal(rail.tooltipKey(), null, 'toggling closes any open tooltip');
});

test('L27 — without the adoption experience the toggle is not offered', () => {
  const rail = railWithAdoption({
    enabled: () => false,
    railLabelsVisible: () => false,
    railLabelsError: () => false,
    setRailLabels: () => assert.fail('must not write'),
  });
  assert.equal(rail.labelsVisible(), false);
  assert.equal(rail.labelsToggleAvailable(), false);
});

test('L27 — a failed save is exposed for the polite status', () => {
  const rail = railWithAdoption({
    enabled: () => true,
    railLabelsVisible: () => true,
    railLabelsError: () => true,
    setRailLabels: () => undefined,
  });
  assert.equal(rail.labelsError(), true);
});
