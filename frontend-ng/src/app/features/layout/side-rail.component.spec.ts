import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { SideRailComponent } from './side-rail.component';

test('side rail delegates every lens route to the route-owned navigation projection', () => {
  const lens = signal<'hypervisor' | 'build' | 'operate' | 'steer' | 'govern'>('operate');
  const calls: Array<[string, string]> = [];
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: { mode: () => 'portfolio', isDemoMode: () => false },
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

test('demo rail uses Mission Room home only when the extension is enabled', () => {
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

  assert.equal(rail.routeFor(hypervisor), '/hypervisor/mission-room/cockpit');

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
