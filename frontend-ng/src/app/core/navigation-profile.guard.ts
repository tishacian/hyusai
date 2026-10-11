import { inject } from '@angular/core';
import { CanActivateChildFn, RedirectCommand, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { NavigationResolverService } from './navigation-resolver.service';
import { NavigationTelemetryService } from './navigation-telemetry.service';
import { WorkspaceService } from './workspace.service';
import { WorkspaceExperienceShadowService } from './workspace-experience-shadow.service';

export const navigationProfileGuard: CanActivateChildFn = (_route, state) => {
  const router = inject(Router);
  const workspace = inject(WorkspaceService);
  const navigationResolver = inject(NavigationResolverService);
  const navigationTelemetry = inject(NavigationTelemetryService);
  const workspaceExperienceShadow = inject(WorkspaceExperienceShadowService);

  const execute = (resolution: ReturnType<NavigationResolverService['resolve']>) => {
    if (!resolution) return true;
    navigationTelemetry.registerRedirect(resolution);
    const tree = router.parseUrl(resolution.resolvedRoute);
    if (resolution.state) {
      return new RedirectCommand(tree, { replaceUrl: true, state: resolution.state });
    }
    return tree;
  };

  const observeThenExecute = (
    resolution: ReturnType<NavigationResolverService['resolve']>,
  ) => {
    try {
      // Lot 2 is deliberately passive: the shadow resolver receives the
      // already-owned legacy decision, but only ``execute`` below can affect
      // Angular navigation. Its return value is intentionally ignored.
      workspaceExperienceShadow.observeNavigation(state.url, resolution);
    } catch {
      // A shadow failure must never interrupt the legacy navigation path. The
      // service normally records failures itself; this boundary also protects
      // the guard against an unexpected instrumentation error while retaining
      // fail-closed rollout evidence when the recorder is still available.
      try {
        workspaceExperienceShadow.recordUnexpectedFailure(state.url);
      } catch {
        // Even the failure recorder is passive instrumentation.
      }
    }
    return execute(resolution);
  };

  const evaluate = () => {
    const activationResolution = navigationResolver.activateWorkspaceFromRoute(state.url);
    // Activating the deep-link tenant can change the effective navigation
    // profile. Re-evaluate policy afterwards and let it keep precedence over
    // the invalid-workspace fallback.
    const resolution = navigationResolver.resolve(state.url) || activationResolution;
    return observeThenExecute(resolution);
  };

  if (workspace.workspaces().length > 0) {
    return evaluate();
  }

  return workspace.loadWorkspaces().pipe(
    map(evaluate),
    catchError(() => workspace.loadWorkspaces(true).pipe(
      map(evaluate),
      catchError(() => of(observeThenExecute(
        navigationResolver.resolveWorkspaceLoadFailure(state.url),
      ))),
    )),
  );
};
