import { Routes } from '@angular/router';

export const connectorsRoutes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    loadComponent: () =>
      import('./connectors-page.component').then((m) => m.ConnectorsPageComponent),
  },
  {
    path: 'sharepoint',
    loadComponent: () =>
      import('./sharepoint/sharepoint-connector.component').then(
        (m) => m.SharepointConnectorComponent,
      ),
  },
  {
    path: 'sftp',
    loadComponent: () =>
      import('./sftp/sftp-connector.component').then((m) => m.SftpConnectorComponent),
  },
  {
    path: 'sap-hana',
    loadComponent: () =>
      import('./hana/hana-connector.component').then((m) => m.HanaConnectorComponent),
  },
];
