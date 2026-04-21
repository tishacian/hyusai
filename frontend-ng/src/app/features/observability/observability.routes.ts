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
      // Legacy `/observability/traces` is replaced by the canonical `/runs`
      // browser. We keep the path so bookmarks keep working, but redirect to
      // the new home of the execution log.
      { path: 'traces', redirectTo: '/runs', pathMatch: 'full' },
    ],
  },
];
