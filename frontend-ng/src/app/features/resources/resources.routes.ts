import { Routes } from '@angular/router';

export const resourcesRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./resources-page.component').then((m) => m.ResourcesPageComponent),
  },
];
