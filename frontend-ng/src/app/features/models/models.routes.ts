import { Routes } from '@angular/router';

export const modelsRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./models-list.component').then((m) => m.ModelsListComponent),
  },
  {
    path: 'endpoints',
    loadComponent: () => import('./endpoints.component').then(m => m.EndpointsComponent),
  },
  {
    path: ':modelId',
    loadComponent: () =>
      import('./model-view.component').then((m) => m.ModelViewComponent),
  },
];
