import { Routes } from '@angular/router';

export const knowledgeRoutes: Routes = [
  {
    path: 'capture',
    loadComponent: () =>
      import('./knowledge-capture.component').then((m) => m.KnowledgeCaptureComponent),
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
