import { inject } from '@angular/core';
import { DefaultUrlSerializer, Routes } from '@angular/router';
import { ASK_HOME_ROUTE } from './core/navigation.catalog';
import { authGuard } from './core/auth.guard';
import { loginGuard } from './core/login.guard';
import { navigationProfileGuard } from './core/navigation-profile.guard';
import { workspaceHydrationGuard } from './core/workspace-hydration.guard';
import { WorkspaceService } from './core/workspace.service';
import { workspaceAppAdminGuard } from './features/governance/workspace-app-admin.guard';
import { experienceV1Guard } from './features/experience/experience.guard';

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
    // Business launcher: no cockpit chrome. Same hydration + flag gate as /create.
    path: 'work',
    canActivate: [authGuard, workspaceHydrationGuard, experienceV1Guard],
    loadChildren: () =>
      import('./features/experience/work/work.routes').then((m) => m.workRoutes),
  },
  {
    path: '',
    canActivate: [authGuard],
    canActivateChild: [navigationProfileGuard],
    loadComponent: () =>
      import('./features/layout/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        // Ask is the first useful action, so the authenticated root lands on
        // the simple grounded-question surface instead of Hypervisor. The
        // canonical `?mode=quick` query needs no workspace slug, so it
        // resolves before a workspace is known. Configured business-workspace
        // homes still win: `navigationProfileGuard` runs on the resolved URL.
        path: '',
        pathMatch: 'full',
        redirectTo: () => new DefaultUrlSerializer().parse(ASK_HOME_ROUTE),
      },
      {
        path: 'workspace-app-unavailable',
        loadComponent: () =>
          import('./features/workspace-app-runtime/workspace-app-unavailable.component').then(
            (m) => m.WorkspaceAppUnavailableComponent,
          ),
      },
      {
        path: 'workspace-app-repair',
        canActivate: [workspaceAppAdminGuard],
        loadComponent: () =>
          import('./features/governance/workspace-app-lifecycle.component').then(
            (m) => m.WorkspaceAppLifecycleComponent,
          ),
      },
      {
        path: 'hypervisor/mission-room',
        loadChildren: () =>
          import('./features/mission-room/mission-room.routes').then((m) => m.missionRoomRoutes),
      },
      {
        path: 'hypervisor',
        loadComponent: () => {
          const workspace = inject(WorkspaceService);
          return workspace.hypervisorV2Enabled()
            ? import('./features/hypervisor/v2/hypervisor-v2.component').then(
              (m) => m.HypervisorV2Component,
            )
            : import('./features/hypervisor/hypervisor.component').then(
              (m) => m.HypervisorComponent,
            );
        },
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
        path: 'create',
        loadChildren: () =>
          import('./features/experience/experience.routes').then((m) => m.experienceRoutes),
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
        path: 'data',
        loadChildren: () => import('./features/data/data.routes').then((m) => m.dataRoutes),
      },
      {
        path: 'models',
        loadChildren: () =>
          import('./features/models/models.routes').then((m) => m.modelsRoutes),
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
        data: { defaultFacet: 'providers' },
        loadComponent: () =>
          import('./features/resources/resources-page.component').then(
            (m) => m.ResourcesPageComponent,
          ),
        pathMatch: 'full',
      },
      {
        path: 'settings/models',
        redirectTo: 'settings',
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
