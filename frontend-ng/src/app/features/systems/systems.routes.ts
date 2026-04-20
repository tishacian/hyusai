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
    path: ':systemId',
    loadComponent: () =>
      import('./system-view.component').then((m) => m.SystemViewComponent),
  },
];
