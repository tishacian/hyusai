import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { canGovernExperiences } from './experience-governance.models';

export const experienceGovernanceGuard: CanActivateFn = () => {
  const workspace = inject(WorkspaceService);
  const router = inject(Router);
  const decide = () => {
    const current = workspace.current();
    return workspace.experienceV1Enabled()
      && canGovernExperiences(current?.role_template, current?.role, workspace.isAdmin())
      ? true
      : router.parseUrl('/governance/audit');
  };
  if (workspace.workspaces().length > 0) return decide();
  return workspace.loadWorkspaces().pipe(
    map(decide),
    catchError(() => of(router.parseUrl('/governance/audit'))),
  );
};
