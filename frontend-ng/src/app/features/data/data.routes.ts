import { Routes } from '@angular/router';

export const dataRoutes: Routes = [
  { path: 'preparation', loadComponent: () => import('./data-preparation.component').then(m => m.DataPreparationComponent) },
  {
    path: '',
    loadComponent: () => import('./data-list.component').then((m) => m.DataListComponent),
  },
  {
    path: ':datasetId',
    loadComponent: () => import('./data-view.component').then((m) => m.DataViewComponent),
  },
];
