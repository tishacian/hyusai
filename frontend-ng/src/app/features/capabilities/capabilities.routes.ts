import { Routes } from '@angular/router';

export const capabilitiesRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./capabilities.component').then((m) => m.CapabilitiesComponent),
  },
  {
    // Declared before the ``:capabilityId`` leaf, which would otherwise claim it.
    path: 'curation',
    loadComponent: () =>
      import('./catalog-curation.component').then((m) => m.CatalogCurationComponent),
  },
  {
    path: ':capabilityId',
    loadComponent: () =>
      import('./capability-view.component').then((m) => m.CapabilityViewComponent),
  },
];
