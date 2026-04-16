import { Routes } from '@angular/router';

export const workspaceRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./workspace-settings.component').then((m) => m.WorkspaceSettingsComponent),
  },
  {
    path: 'members',
    loadComponent: () =>
      import('./workspace-members.component').then((m) => m.WorkspaceMembersComponent),
  },
];
