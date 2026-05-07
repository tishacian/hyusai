import { Routes } from '@angular/router';

export const workspaceRoutes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    loadComponent: () =>
      import('./workspace-redirect.component').then((m) => m.WorkspaceRedirectComponent),
  },
  {
    path: ':slug',
    loadComponent: () =>
      import('./workspace-shell.component').then((m) => m.WorkspaceShellComponent),
    children: [
      { path: '', redirectTo: 'settings', pathMatch: 'full' },
      {
        path: 'settings',
        loadComponent: () =>
          import('./general.component').then((m) => m.WorkspaceGeneralComponent),
      },
      {
        path: 'members',
        loadComponent: () =>
          import('./members.component').then((m) => m.WorkspaceMembersComponent),
      },
      {
        path: 'access',
        loadComponent: () =>
          import('../governance/access-roles.component').then((m) => m.AccessRolesComponent),
      },
      {
        path: 'danger',
        loadComponent: () =>
          import('./danger.component').then((m) => m.WorkspaceDangerComponent),
      },
    ],
  },
];
