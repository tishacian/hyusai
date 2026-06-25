import { Routes } from '@angular/router';

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
    path: ':systemId/capture',
    loadComponent: () =>
      import('../knowledge/knowledge-capture.component').then((m) => m.KnowledgeCaptureComponent),
  },
  {
    path: ':systemId',
    loadComponent: () =>
      import('./system-view.component').then((m) => m.SystemViewComponent),
  },
];
