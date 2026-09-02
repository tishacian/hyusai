import { Routes } from '@angular/router';

export const workRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./work-launcher.component').then((m) => m.WorkLauncherComponent),
  },
  {
    // The NAWA landing: the Agent Studio is the one client of the published
    // PR → PO run. The former desk route stays reachable and lands here.
    path: 'pr-to-po',
    loadComponent: () =>
      import('./pr-to-po-studio.component').then((m) => m.PrToPoStudioComponent),
  },
  { path: 'pr-to-po/desk', redirectTo: 'pr-to-po', pathMatch: 'full' },
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
