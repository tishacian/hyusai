import { Routes } from '@angular/router';

export const observabilityRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./quality-dashboard.component').then((m) => m.QualityDashboardComponent),
  },
];
