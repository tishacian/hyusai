import { Routes } from '@angular/router';

export const workRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./work-launcher.component').then((m) => m.WorkLauncherComponent),
  },
  {
    path: ':slug',
    loadComponent: () =>
      import('./work-shell.component').then((m) => m.WorkShellComponent),
  },
];
