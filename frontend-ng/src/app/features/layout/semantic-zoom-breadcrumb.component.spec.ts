import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { Router } from '@angular/router';
import { EN_DICT } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService, type ZoomGraphNode } from '@app/core/zoom-context.service';
import { SemanticZoomBreadcrumbComponent } from './semantic-zoom-breadcrumb.component';

test('breadcrumb renders only graph-proven nodes with their canonical labels and hrefs', () => {
  const nodes = signal<readonly ZoomGraphNode[]>([
    { key: 'portfolio', id: 'workspace', label: 'Portfolio', sub: 'Showcase', href: '/hypervisor' },
    { key: 'capability', id: 'cap-1', label: 'Contract Risk', sub: 'Capability', href: '/capabilities/cap-1?lens=steer' },
    { key: 'system', id: 'sys-1', label: 'Contract Risk Copilot', sub: 'System', href: '/systems/sys-1?lens=steer' },
    { key: 'run', id: 'run-1', label: 'Run · run-1', sub: 'Run', href: '/runs/run-1?lens=steer' },
  ]);
  const navigations: string[] = [];
  const injector = Injector.create({
    providers: [
      SemanticZoomBreadcrumbComponent,
      {
        provide: ZoomContextService,
        useValue: {
          nodes,
          axesV3Enabled: () => true,
          route: () => ({ selectedType: 'run' }),
          deepestResolvedType: () => 'run',
        },
      },
      {
        provide: Router,
        useValue: {
          navigate: () => undefined,
          navigateByUrl: (url: string) => navigations.push(url),
        },
      },
      // The portfolio rung takes its label from the dictionary, not the graph,
      // so the breadcrumb needs a resolving translator. Pinned to EN to match
      // the English node labels this fixture feeds it.
      {
        provide: I18nService,
        useValue: {
          locale: () => 'en',
          t: (key: string) => EN_DICT[key as keyof typeof EN_DICT] ?? key,
        },
      },
    ],
  });
  const breadcrumb = injector.get(SemanticZoomBreadcrumbComponent);
  assert.deepEqual(
    breadcrumb.levels().map((level) => [level.key, level.label, level.active]),
    [
      ['portfolio', EN_DICT['nav.zoom.portfolio'], false],
      ['capability', 'Contract Risk', false],
      ['system', 'Contract Risk Copilot', false],
      ['run', 'Run · run-1', true],
    ],
  );
  breadcrumb.goto(breadcrumb.levels()[1]);
  assert.deepEqual(navigations, ['/capabilities/cap-1?lens=steer']);
});
