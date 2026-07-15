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
