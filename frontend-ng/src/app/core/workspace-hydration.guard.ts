import { CanActivateFn } from '@angular/router';
import { inject } from '@angular/core';
import { catchError, map, of } from 'rxjs';
import { WorkspaceService } from './workspace.service';

/**
 * Routes mounted outside the shell never cross {@link navigationProfileGuard},
 * which is where memberships are normally hydrated. A white-labelled app still
 * needs its workspace settings, for its brand, and the viewer's role, to decide
 * whether the platform is reachable from it.
 *
 * A load failure is not fatal: API calls are scoped by the stored slug anyway,
 * so the app simply falls back to the unbranded, member-level view.
 */
export const workspaceHydrationGuard: CanActivateFn = () => {
  const workspace = inject(WorkspaceService);
  if (workspace.workspaces().length > 0) return true;
  return workspace.loadWorkspaces().pipe(
    map(() => true),
    catchError(() => of(true)),
  );
};
