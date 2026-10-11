import { Routes } from '@angular/router';

export const appsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./apps-page.component').then((m) => m.AppsPageComponent),
  },
];
