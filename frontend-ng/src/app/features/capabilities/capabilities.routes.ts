import { Routes } from '@angular/router';

export const capabilitiesRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./capabilities.component').then((m) => m.CapabilitiesComponent),
  },
  {
    path: ':capabilityId',
    loadComponent: () =>
      import('./capability-view.component').then((m) => m.CapabilityViewComponent),
  },
];
