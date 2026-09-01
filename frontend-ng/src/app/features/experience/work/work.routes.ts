import { Routes } from '@angular/router';

export const workRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./work-launcher.component').then((m) => m.WorkLauncherComponent),
  },
  {
    // The NAWA landing: the Agent Studio owns the app root; the desk moves one
    // level down and keeps every capability it had.
    path: 'pr-to-po',
    loadComponent: () =>
      import('./pr-to-po-studio.component').then((m) => m.PrToPoStudioComponent),
  },
  {
    path: 'pr-to-po/desk',
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
