import { inject } from '@angular/core';
import { Router, type Routes } from '@angular/router';
import { systemCaptureFacetUrl } from '../knowledge/knowledge-capture-redirect';

export const systemsRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./systems-grid.component').then((m) => m.SystemsGridComponent),
  },
  {
    path: 'new',
    loadComponent: () =>
      import('./system-builder.component').then((m) => m.SystemBuilderComponent),
  },
  {
    path: ':systemId/flow',
    loadComponent: () =>
      import('../orchestration/flow/flow-builder.component').then((m) => m.FlowBuilderComponent),
  },
  {
    path: ':systemId/run',
    loadComponent: () =>
      import('./flow-runner.component').then((m) => m.FlowRunnerComponent),
  },
  {
    // L19 — Capture is a System facet (`?facet=capture`), not a child route.
    path: ':systemId/capture',
    redirectTo: ({ params }) =>
      inject(Router).parseUrl(systemCaptureFacetUrl(String(params['systemId'] || ''))),
  },
  {
    path: ':systemId',
    loadComponent: () =>
      import('./system-view.component').then((m) => m.SystemViewComponent),
  },
];
