import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';
import { loginGuard } from './core/login.guard';
import { navigationProfileGuard } from './core/navigation-profile.guard';
import { workspaceHydrationGuard } from './core/workspace-hydration.guard';

export const routes: Routes = [
  {
    path: 'auth',
    canActivate: [loginGuard],
    loadChildren: () =>
      import('./features/auth/auth.routes').then((m) => m.authRoutes),
  },
  {
    path: 'deposit/:accessId',
    loadComponent: () =>
      import('./features/deposit/deposit-portal.component').then((m) => m.DepositPortalComponent),
  },
  {
    // White-labelled customer app: it owns the whole page, so it is mounted
    // outside the Agentium shell. Business stakeholders must see the Nawa brand
    // only, never the platform title bar, side rail or workspace switcher.
    path: 'nawa',
    canActivate: [authGuard, workspaceHydrationGuard],
    loadChildren: () => import('./features/nawa/nawa.routes').then((m) => m.nawaRoutes),
  },
  {
    path: '',
    canActivate: [authGuard],
    canActivateChild: [navigationProfileGuard],
    loadComponent: () =>
      import('./features/layout/shell.component').then((m) => m.ShellComponent),
    children: [
      { path: '', redirectTo: 'hypervisor', pathMatch: 'full' },
      {
        path: 'hypervisor/mission-room',
        loadChildren: () =>
          import('./features/mission-room/mission-room.routes').then((m) => m.missionRoomRoutes),
      },
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
        path: 'steering/review-queue',
        loadComponent: () =>
          import('./features/steering/review-queue.component').then(
            (m) => m.SteeringReviewQueueComponent,
          ),
      },
      {
        path: 'steering/contexts/:id',
        loadComponent: () =>
          import('./features/contexts/context-view.component').then((m) => m.ContextViewComponent),
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
        path: 'chat',
        loadComponent: () =>
          import('./features/chat/chat-workspace.component').then((m) => m.ChatWorkspaceComponent),
      },
      {
        path: 'client360',
        loadChildren: () =>
          import('./features/client360/client360.routes').then((m) => m.client360Routes),
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
        path: 'presets',
        loadChildren: () =>
          import('./features/presets/presets.routes').then((m) => m.presetsRoutes),
      },
      {
        path: 'settings',
        redirectTo: 'presets',
        pathMatch: 'full',
      },
      {
        path: 'settings/legacy',
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
        path: 'connectors',
        loadChildren: () =>
          import('./features/connectors/connectors.routes').then((m) => m.connectorsRoutes),
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
