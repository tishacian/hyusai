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
      { path: '', redirectTo: 'hypervisor', pathMatch: 'full' },
      {
        path: 'hypervisor',
        loadComponent: () =>
          import('./features/hypervisor/hypervisor.component').then((m) => m.HypervisorComponent),
      },
      {
        path: 'steering',
        loadComponent: () =>
          import('./features/steering/steering.component').then((m) => m.SteeringComponent),
      },
      {
        path: 'steering/contexts',
        loadComponent: () =>
          import('./features/contexts/contexts-page.component').then((m) => m.ContextsPageComponent),
      },
      {
        path: 'capabilities',
        loadChildren: () =>
          import('./features/capabilities/capabilities.routes').then((m) => m.capabilitiesRoutes),
      },
      {
        path: 'skills',
        loadChildren: () =>
          import('./features/skills/skills.routes').then((m) => m.skillsRoutes),
      },
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
        path: 'runs',
        loadChildren: () =>
          import('./features/runs/runs.routes').then((m) => m.runsRoutes),
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
      {
        path: 'tasks',
        loadChildren: () =>
          import('./features/tasks/tasks.routes').then((m) => m.tasksRoutes),
      },
      {
        path: 'resources',
        loadChildren: () =>
          import('./features/resources/resources.routes').then((m) => m.resourcesRoutes),
      },
      {
        path: 'apps',
        loadChildren: () =>
          import('./features/apps/apps.routes').then((m) => m.appsRoutes),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
