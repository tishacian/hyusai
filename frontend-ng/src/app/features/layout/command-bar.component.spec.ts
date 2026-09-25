import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Router } from '@angular/router';
import { Subject } from 'rxjs';
import { EN_DICT } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService, type ZoomGraphNode } from '@app/core/zoom-context.service';
import { CommandBarComponent } from './command-bar.component';

function i18n() {
  return {
    locale: () => 'en',
    t: (key: string, params?: Record<string, string>) => {
      let value = EN_DICT[key as keyof typeof EN_DICT] ?? key;
      if (params) {
        for (const [name, item] of Object.entries(params)) {
          value = value.replaceAll(`{${name}}`, item);
        }
      }
      return value;
    },
  };
}

function harness(nodes: ZoomGraphNode[], deepest: string | null = 'system') {
  const events = new Subject<NavigationEnd>();
  const injector = Injector.create({
    providers: [
      CommandBarComponent,
      {
        provide: ZoomContextService,
        useValue: {
          navV5Enabled: () => true,
          zoneI18nKey: () => 'experience.adoption.nav.build',
          deepestResolvedType: () => deepest,
          systemId: () => null,
          capabilityId: () => null,
          nodes: () => nodes,
          visibleNodes: () => nodes,
          depthPair: () => ({ depth: nodes.length, total: nodes.length }),
          zoomParentHint: () => {
            if (nodes.length <= 1) return i18n().t('nav.zoom.hint_at_top');
            const parent = nodes[nodes.length - 2];
            if (parent.key === 'portfolio') return i18n().t('nav.zoom.hint_to_portfolio');
            return i18n().t('nav.zoom.hint_to_parent', { parent: parent.label });
          },
        },
      },
      {
        provide: Router,
        useValue: {
          url: '/systems/sys-1',
          events,
        },
      },
      { provide: I18nService, useValue: i18n() },
    ],
  });
  return injector.get(CommandBarComponent);
}

test('command bar shows level 2 of 2 on a System without Capability', () => {
  const bar = harness([
    { key: 'portfolio', id: null, label: 'Portfolio', sub: '', href: '/hypervisor' },
    { key: 'system', id: 'sys-1', label: 'NAWA Chat', sub: '', href: '/systems/sys-1' },
  ], 'system');
  assert.match(bar.position(), /level 2 of 2/);
  assert.equal(bar.zoomHint(), i18n().t('nav.zoom.hint_to_portfolio'));
});

test('command bar shows level 3 of 3 on a Run', () => {
  const bar = harness([
    { key: 'portfolio', id: null, label: 'Portfolio', sub: '', href: '/hypervisor' },
    { key: 'system', id: 'sys-1', label: 'NAWA Chat', sub: '', href: '/systems/sys-1' },
    { key: 'run', id: 'run-1', label: 'Run', mono: 'run-1', sub: '', href: '/runs/run-1' },
  ], 'run');
  assert.match(bar.position(), /level 3 of 3/);
  assert.match(bar.zoomHint(), /NAWA Chat/);
});

test('command bar names ⌘Z already at the top on the Portfolio', () => {
  const bar = harness([
    { key: 'portfolio', id: null, label: 'Portfolio', sub: '', href: '/hypervisor' },
  ], null);
  assert.match(bar.position(), /level 1 of 1/);
  assert.equal(bar.zoomHint(), i18n().t('nav.zoom.hint_at_top'));
});
