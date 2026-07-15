import { Injectable } from '@angular/core';
import {
  ActivatedRouteSnapshot,
  BaseRouteReuseStrategy,
} from '@angular/router';

/**
 * Angular normally reuses a routed component when only path parameters change.
 * Every workspace surface owns tenant-scoped local state. Carrying the shell —
 * or the direct focused Chat tree — from one `:slug` to another would expose
 * state loaded for the previous workspace.
 */
@Injectable()
export class WorkspaceRouteReuseStrategy extends BaseRouteReuseStrategy {
  override shouldReuseRoute(
    future: ActivatedRouteSnapshot,
    current: ActivatedRouteSnapshot,
  ): boolean {
    const routePath = future.routeConfig?.path;
    const sameWorkspaceScopedRoute =
      future.routeConfig === current.routeConfig &&
      (routePath === ':slug' || routePath === ':slug/chat');

    if (
      sameWorkspaceScopedRoute &&
      future.paramMap.get('slug') !== current.paramMap.get('slug')
    ) {
      return false;
    }

    const hierarchyParam = routePath === ':capabilityId'
      ? 'capabilityId'
      : routePath === ':systemId' || routePath === ':systemId/flow' || routePath === ':systemId/capture'
        ? 'systemId'
        : routePath === ':runId'
          ? 'runId'
          : routePath === ':skillId'
            ? 'skillId'
            : null;
    if (
      hierarchyParam &&
      future.routeConfig === current.routeConfig &&
      future.paramMap.get(hierarchyParam) !== current.paramMap.get(hierarchyParam)
    ) {
      return false;
    }

    return super.shouldReuseRoute(future, current);
  }
}
