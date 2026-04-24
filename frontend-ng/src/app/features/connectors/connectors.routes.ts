import { Routes } from '@angular/router';

export const connectorsRoutes: Routes = [
  {
    path: 'sharepoint',
    loadComponent: () =>
      import('./sharepoint/sharepoint-connector.component').then(
        (m) => m.SharepointConnectorComponent,
      ),
  },
];
