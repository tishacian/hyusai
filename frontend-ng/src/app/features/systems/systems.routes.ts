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
    // Route through the flag-aware wrapper (not the v0 monolith directly) so the
    // system-scoped entry honours `capture_experience` like `/knowledge/capture`.
    // The v0 child still reads `:systemId` from the same ActivatedRoute.
    path: ':systemId/capture',
    loadComponent: () =>
      import('../knowledge/capture-fil/capture-router.component').then(
        (m) => m.CaptureRouterComponent,
      ),
  },
  {
    path: ':systemId',
    loadComponent: () =>
      import('./system-view.component').then((m) => m.SystemViewComponent),
  },
];
