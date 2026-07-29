import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { WorkspaceService } from '@app/core/workspace.service';

export const workspaceAppAdminGuard: CanActivateFn = () => {
  const workspace = inject(WorkspaceService);
  const navigationProfile = inject(NavigationProfileService);
  const router = inject(Router);
  const decide = () => workspace.isAdmin()
    ? true
    : router.parseUrl(
      navigationProfile.workspaceAppUnavailable()
        ? '/workspace-app-unavailable'
        : '/governance/audit',
    );

  if (workspace.workspaces().length > 0) return decide();
  return workspace.loadWorkspaces().pipe(
    map(decide),
    catchError(() => of(router.parseUrl('/workspace-app-unavailable'))),
  );
};
