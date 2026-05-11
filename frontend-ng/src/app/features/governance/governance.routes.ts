import { Routes } from '@angular/router';

export const governanceRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./governance-shell.component').then((m) => m.GovernanceShellComponent),
    children: [
      { path: '', redirectTo: 'audit', pathMatch: 'full' },
      {
        path: 'audit',
        loadComponent: () =>
          import('./audit-logs.component').then((m) => m.AuditLogsComponent),
      },
      {
        path: 'access',
        loadComponent: () =>
          import('./access-roles.component').then((m) => m.AccessRolesComponent),
      },
      {
        path: 'surface-map',
        loadComponent: () =>
          import('./surface-map.component').then((m) => m.SurfaceMapComponent),
      },
      {
        path: 'canonical-answers',
        loadComponent: () =>
          import('./canonical-answers.component').then((m) => m.CanonicalAnswersComponent),
      },
    ],
  },
];
