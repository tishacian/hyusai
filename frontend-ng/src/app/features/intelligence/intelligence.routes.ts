import { Routes } from '@angular/router';

export const intelligenceRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./news-lab.component').then((m) => m.NewsLabComponent),
  },
];
