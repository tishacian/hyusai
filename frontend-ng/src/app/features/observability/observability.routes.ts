import { Routes } from '@angular/router';

export const observabilityRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./observability-shell.component').then((m) => m.ObservabilityShellComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./quality-dashboard.component').then((m) => m.QualityDashboardComponent),
      },
      {
        path: 'performance',
        loadComponent: () =>
          import('./performance-dashboard.component').then((m) => m.PerformanceDashboardComponent),
      },
      {
        path: 'traces',
        loadComponent: () =>
          import('./traces-list.component').then((m) => m.TracesListComponent),
      },
    ],
  },
];
