import { inject } from '@angular/core';
import { CanActivateChildFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { NavigationProfileService } from './navigation-profile.service';
import { WorkspaceService } from './workspace.service';

export const navigationProfileGuard: CanActivateChildFn = (_route, state) => {
  const router = inject(Router);
  const workspace = inject(WorkspaceService);
  const navigationProfile = inject(NavigationProfileService);

  const evaluate = () => {
    const redirect = navigationProfile.businessRedirectFor(state.url);
    return redirect ? router.parseUrl(redirect) : true;
  };

  if (workspace.workspaces().length > 0) {
    return evaluate();
  }

  return workspace.loadWorkspaces().pipe(
    map(evaluate),
    catchError(() => of(true)),
  );
};
