import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';

export const experienceV1Guard: CanActivateFn = () => {
  const workspace = inject(WorkspaceService);
  const router = inject(Router);
  const decide = () =>
    workspace.experienceV1Enabled() ? true : router.parseUrl('/systems');

  if (workspace.workspaces().length > 0) return decide();
  return workspace.loadWorkspaces().pipe(
    map(decide),
    catchError(() => of(router.parseUrl('/systems'))),
  );
};
