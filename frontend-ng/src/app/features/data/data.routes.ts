import { Routes } from '@angular/router';

export const dataRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./data-list.component').then((m) => m.DataListComponent),
  },
  {
    path: ':datasetId',
    loadComponent: () => import('./data-view.component').then((m) => m.DataViewComponent),
  },
];
