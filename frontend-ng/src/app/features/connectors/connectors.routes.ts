import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';

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
  {
    path: 'rpa-bridge',
    loadComponent: () =>
      import('./rpa/rpa-connector.component').then((m) => m.RpaConnectorComponent),
  },
  {
    path: 'mcp',
    loadComponent: () =>
      import('./mcp/mcp-connector.component').then((m) => m.McpConnectorComponent),
  },
  {
    path: 'models',
    pathMatch: 'full',
    // RedirectFunction must return string | UrlTree (not RedirectCommand).
    redirectTo: () => inject(Router).parseUrl('/resources?tab=providers'),
  },
];
