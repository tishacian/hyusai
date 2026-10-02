import { Routes } from '@angular/router';

export const workRoutes: Routes = [
  { path: 'reclamations/studio', loadComponent: () => import('./claims-studio.component').then(m => m.ClaimsStudioComponent) },
  { path: 'getting-started', loadComponent: () => import('./adoption-journey.component').then(m => m.AdoptionPageComponent) },
  {
    path: '',
    loadComponent: () =>
      import('./work-launcher.component').then((m) => m.WorkLauncherComponent),
  },
  {
    // The NAWA landing: the Agent Studio is the one client of the published
    // PR → PO run. The retired /desk route stays reachable and lands here.
    path: 'pr-to-po',
    loadComponent: () =>
      import('./pr-to-po-studio.component').then((m) => m.PrToPoStudioComponent),
  },
  { path: 'pr-to-po/desk', redirectTo: 'pr-to-po', pathMatch: 'full' },
  {
    path: 'automation/:systemId',
    loadComponent: () =>
      import('./work-automation.component').then((m) => m.WorkAutomationComponent),
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
