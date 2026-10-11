import { Routes } from '@angular/router';

export const knowledgeRoutes: Routes = [
  {
    path: 'capture',
    loadComponent: () =>
      import('./capture-fil/capture-router.component').then((m) => m.CaptureRouterComponent),
  },
  {
    path: 'interventions',
    loadComponent: () =>
      import('./capture-fil/capture-router.component').then((m) => m.CaptureRouterComponent),
  },
  {
    path: '',
    loadComponent: () =>
      import('./knowledge-base.component').then((m) => m.KnowledgeBaseComponent),
  },
  {
    path: ':kbId',
    loadComponent: () =>
      import('./knowledge-view.component').then((m) => m.KnowledgeViewComponent),
  },
];
