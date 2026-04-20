import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';
import { loginGuard } from './core/login.guard';

export const routes: Routes = [
  {
    path: 'auth',
    canActivate: [loginGuard],
    loadChildren: () =>
      import('./features/auth/auth.routes').then((m) => m.authRoutes),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/layout/shell.component').then((m) => m.ShellComponent),
    children: [
      { path: '', redirectTo: 'systems', pathMatch: 'full' },
      {
        path: 'systems',
        loadChildren: () =>
          import('./features/systems/systems.routes').then((m) => m.systemsRoutes),
      },
      {
        path: 'knowledge',
        loadChildren: () =>
          import('./features/knowledge/knowledge.routes').then((m) => m.knowledgeRoutes),
      },
      {
        path: 'governance',
        loadChildren: () =>
          import('./features/governance/governance.routes').then((m) => m.governanceRoutes),
      },
      {
        path: 'observability',
        loadChildren: () =>
          import('./features/observability/observability.routes').then((m) => m.observabilityRoutes),
      },
      {
        path: 'intelligence',
        loadChildren: () =>
          import('./features/intelligence/intelligence.routes').then((m) => m.intelligenceRoutes),
      },
      {
        path: 'orchestration',
        loadChildren: () =>
          import('./features/orchestration/orchestration.routes').then((m) => m.orchestrationRoutes),
      },
      {
        path: 'workspace',
        loadChildren: () =>
          import('./features/workspace/workspace.routes').then((m) => m.workspaceRoutes),
      },
      {
        path: 'account',
        loadChildren: () =>
          import('./features/account/account.routes').then((m) => m.accountRoutes),
      },
      {
        path: 'settings',
        loadChildren: () =>
          import('./features/settings/settings.routes').then((m) => m.settingsRoutes),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
