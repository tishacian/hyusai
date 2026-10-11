/**
 * Runs feature routes — canonical home of the `/runs` browser and the
 * `/runs/:runId` drill-down. The former `/observability/traces` pages
 * redirect here so every legacy link lands on the canonical view.
 */
import { Routes } from '@angular/router';

export const runsRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./runs-list.component').then((m) => m.RunsListComponent),
  },
  {
    path: ':runId/invocations/:invocationId',
    loadComponent: () =>
      import('./skill-invocation-view.component').then((m) => m.SkillInvocationViewComponent),
  },
  {
    path: ':runId',
    loadComponent: () =>
      import('./run-view.component').then((m) => m.RunViewComponent),
  },
];
