import { Routes } from '@angular/router';

export const knowledgeRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./knowledge-base.component').then((m) => m.KnowledgeBaseComponent),
  },
];
