import { inject } from '@angular/core';
import { CanActivateChildFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { NavigationProfileService } from './navigation-profile.service';
import { NavigationTelemetryService } from './navigation-telemetry.service';
import { WorkspaceService } from './workspace.service';

export const navigationProfileGuard: CanActivateChildFn = (_route, state) => {
  const router = inject(Router);
  const workspace = inject(WorkspaceService);
  const navigationProfile = inject(NavigationProfileService);
  const navigationTelemetry = inject(NavigationTelemetryService);

  const evaluate = () => {
    const resolution = navigationProfile.businessResolutionFor(state.url);
    if (!resolution) return true;
    navigationTelemetry.registerRedirect(resolution);
    return router.parseUrl(resolution.resolvedRoute);
  };

  if (workspace.workspaces().length > 0) {
    return evaluate();
  }

  return workspace.loadWorkspaces().pipe(
    map(evaluate),
    catchError(() => of(true)),
  );
};
