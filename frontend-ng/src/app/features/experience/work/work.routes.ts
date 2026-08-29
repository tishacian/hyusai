import { Routes } from '@angular/router';

export const workRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./work-launcher.component').then((m) => m.WorkLauncherComponent),
  },
  {
    path: 'pr-to-po',
    loadComponent: () =>
      import('./pr-to-po-board.component').then((m) => m.PrToPoBoardComponent),
  },
  {
    path: ':slug/:pageId',
    loadComponent: () =>
      import('./work-shell.component').then((m) => m.WorkShellComponent),
  },
  {
    path: ':slug',
    loadComponent: () =>
      import('./work-shell.component').then((m) => m.WorkShellComponent),
  },
];
