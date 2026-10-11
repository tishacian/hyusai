import { Routes } from '@angular/router';

export const client360Routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./client360-page.component').then((m) => m.Client360PageComponent),
  },
];
