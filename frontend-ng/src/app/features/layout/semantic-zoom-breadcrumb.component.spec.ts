import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { Router } from '@angular/router';
import { EN_DICT } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService, type ZoomGraphNode } from '@app/core/zoom-context.service';
import { SemanticZoomBreadcrumbComponent } from './semantic-zoom-breadcrumb.component';

function i18n() {
  return {
    locale: () => 'en',
    t: (key: string) => EN_DICT[key as keyof typeof EN_DICT] ?? key,
  };
}

test('breadcrumb renders only graph-proven nodes with their canonical labels and hrefs', () => {
  const nodes = signal<readonly ZoomGraphNode[]>([
    { key: 'portfolio', id: 'workspace', label: 'Portfolio', sub: 'Showcase', href: '/hypervisor' },
    { key: 'capability', id: 'cap-1', label: 'Contract Risk', sub: 'Capability', href: '/capabilities/cap-1?lens=steer' },
    { key: 'system', id: 'sys-1', label: 'Contract Risk Copilot', sub: 'System', href: '/systems/sys-1?lens=steer' },
    { key: 'run', id: 'run-1', label: 'Run', mono: 'run-1', sub: 'Run', href: '/runs/run-1?lens=steer' },
  ]);
  const navigations: string[] = [];
  const injector = Injector.create({
    providers: [
      SemanticZoomBreadcrumbComponent,
      {
        provide: ZoomContextService,
        useValue: {
          nodes,
          visibleNodes: () => nodes(),
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
      { provide: I18nService, useValue: i18n() },
    ],
  });
  const breadcrumb = injector.get(SemanticZoomBreadcrumbComponent);
  assert.deepEqual(
    breadcrumb.levels().map((level) => [level.key, level.label, level.active, level.current]),
    [
      ['portfolio', EN_DICT['nav.zoom.portfolio'], false, false],
      ['capability', 'Contract Risk', false, false],
      ['system', 'Contract Risk Copilot', false, false],
      ['run', 'Run', true, true],
    ],
  );
  breadcrumb.goto(breadcrumb.levels()[1]);
  assert.deepEqual(navigations, ['/capabilities/cap-1?lens=steer']);
});

test('collection, dataset, model and context crumbs name the object and mark aria-current on the leaf', () => {
  const cases: Array<{ nodes: ZoomGraphNode[]; selected: string; leafLabel: string }> = [
    {
      selected: 'collection',
      leafLabel: 'Collection Policies',
      nodes: [
        { key: 'portfolio', id: null, label: 'Portfolio', sub: '', href: '/hypervisor' },
        { key: 'collection', id: 'kb-1', label: 'Collection Policies', sub: '', href: '/knowledge/kb-1' },
      ],
    },
    {
      selected: 'dataset',
      leafLabel: 'Dataset Orders',
      nodes: [
        { key: 'portfolio', id: null, label: 'Portfolio', sub: '', href: '/hypervisor' },
        { key: 'dataset', id: 'ds-1', label: 'Dataset Orders', sub: '', href: '/data/ds-1' },
      ],
    },
    {
      selected: 'model',
      leafLabel: 'Model Churn v2',
      nodes: [
        { key: 'portfolio', id: null, label: 'Portfolio', sub: '', href: '/hypervisor' },
        { key: 'model', id: 'm-1', label: 'Model Churn v2', sub: '', href: '/models/m-1' },
      ],
    },
    {
      selected: 'context',
      leafLabel: 'Context Leave policy',
      nodes: [
        { key: 'portfolio', id: null, label: 'Portfolio', sub: '', href: '/hypervisor' },
        { key: 'system', id: 'sys-1', label: 'NAWA Chat', sub: '', href: '/systems/sys-1' },
        { key: 'context', id: 'ctx-1', label: 'Context Leave policy', sub: '', href: '/steering/contexts/ctx-1' },
      ],
    },
  ];

  for (const fixture of cases) {
    const nodes = signal(fixture.nodes);
    const injector = Injector.create({
      providers: [
        SemanticZoomBreadcrumbComponent,
        {
          provide: ZoomContextService,
          useValue: {
            nodes,
            visibleNodes: () => nodes(),
            route: () => ({ selectedType: fixture.selected }),
            deepestResolvedType: () => fixture.selected,
          },
        },
        { provide: Router, useValue: { navigate: () => undefined, navigateByUrl: () => undefined } },
        { provide: I18nService, useValue: i18n() },
      ],
    });
    const levels = injector.get(SemanticZoomBreadcrumbComponent).levels();
    const leaf = levels[levels.length - 1];
    assert.equal(leaf.label, fixture.leafLabel);
    assert.equal(leaf.current, true);
    assert.equal(leaf.active, true);
  }
});

test('a ⌘Z another surface already handled does not zoom out', () => {
  const navigations: string[] = [];
  const injector = Injector.create({
    providers: [
      SemanticZoomBreadcrumbComponent,
      {
        provide: ZoomContextService,
        useValue: {
          nodes: () => [
            { key: 'portfolio', id: 'workspace', label: 'Portfolio', href: '/hypervisor' },
            { key: 'system', id: 'sys-1', label: 'Contract Risk Copilot', href: '/systems/sys-1' },
          ],
          visibleNodes: () => [
            { key: 'portfolio', id: 'workspace', label: 'Portfolio', href: '/hypervisor' },
            { key: 'system', id: 'sys-1', label: 'Contract Risk Copilot', href: '/systems/sys-1' },
          ],
          route: () => ({ selectedType: 'system' }),
          deepestResolvedType: () => 'system',
          navV5Enabled: () => true,
        },
      },
      {
        provide: Router,
        useValue: {
          navigate: () => undefined,
          navigateByUrl: (url: string) => navigations.push(url),
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  const breadcrumb = injector.get(SemanticZoomBreadcrumbComponent);
  const zoomOut = (defaultPrevented: boolean) => {
    const calls: string[] = [];
    const event = {
      key: 'z',
      metaKey: true,
      ctrlKey: false,
      altKey: false,
      shiftKey: false,
      defaultPrevented,
      target: null,
      preventDefault: () => calls.push('preventDefault'),
      stopPropagation: () => calls.push('stopPropagation'),
    } as unknown as KeyboardEvent;
    breadcrumb.onZoomKey(event);
    return calls;
  };

  const previousDocument = globalThis.document;
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { activeElement: null } });
  try {
    assert.deepEqual(zoomOut(true), []);
    assert.deepEqual(navigations, []);

    assert.deepEqual(zoomOut(false), ['preventDefault', 'stopPropagation']);
    assert.deepEqual(navigations, ['/hypervisor']);
  } finally {
    if (previousDocument) {
      Object.defineProperty(globalThis, 'document', { configurable: true, value: previousDocument });
    } else {
      Reflect.deleteProperty(globalThis, 'document');
    }
  }
});
