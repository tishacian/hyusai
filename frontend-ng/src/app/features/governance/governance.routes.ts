import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { experienceGovernanceGuard } from './experience-governance.guard';
import { workspaceAppAdminGuard } from './workspace-app-admin.guard';

export const governanceRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./governance-shell.component').then((m) => m.GovernanceShellComponent),
    children: [
      { path: '', redirectTo: 'audit', pathMatch: 'full' },
      {
        path: 'audit',
        loadComponent: () =>
          import('./audit-logs.component').then((m) => m.AuditLogsComponent),
      },
      {
        path: 'experiences',
        canActivate: [experienceGovernanceGuard],
        loadComponent: () =>
          import('./experience-governance.component').then((m) => m.ExperienceGovernanceComponent),
      },
      {
        path: 'access',
        loadComponent: () =>
          import('./access-roles.component').then((m) => m.AccessRolesComponent),
      },
      {
        path: 'chat-history',
        redirectTo: () => inject(Router).parseUrl('/conversations?facet=workspace'),
      },
      {
        path: 'surface-map',
        loadComponent: () =>
          import('./surface-map.component').then((m) => m.SurfaceMapComponent),
      },
      {
        path: 'blueprints',
        loadComponent: () =>
          import('./workspace-blueprints.component').then((m) => m.WorkspaceBlueprintsComponent),
      },
      {
        path: 'workspace-apps',
        canActivate: [workspaceAppAdminGuard],
        loadComponent: () =>
          import('./workspace-app-lifecycle.component').then((m) => m.WorkspaceAppLifecycleComponent),
      },
      {
        path: 'canonical-answers',
        loadComponent: () =>
          import('./canonical-answers.component').then((m) => m.CanonicalAnswersComponent),
      },
    ],
  },
];
