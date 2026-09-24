import { Injectable, inject } from '@angular/core';
import {
  ActivatedRouteSnapshot,
  BaseRouteReuseStrategy,
  type ResolveFn,
} from '@angular/router';
import { WorkspaceService } from './workspace.service';

/** Route data key: the workspace epoch the shell was last resolved under. */
export const WORKSPACE_EPOCH = 'workspaceEpoch';

export const workspaceEpochResolver: ResolveFn<number> = () =>
  inject(WorkspaceService).contextEpoch();

/**
 * Angular normally reuses a routed component when only path parameters change.
 * Every workspace surface owns tenant-scoped local state. Carrying the shell —
 * or the direct focused Chat tree — from one `:slug` to another would expose
 * state loaded for the previous workspace. For the same reason a page under
 * the shell is recreated when the epoch changed, even at the same URL.
 */
@Injectable()
export class WorkspaceRouteReuseStrategy extends BaseRouteReuseStrategy {
  override shouldReuseRoute(
    future: ActivatedRouteSnapshot,
    current: ActivatedRouteSnapshot,
  ): boolean {
    const nextEpoch = future.parent?.data;
    if (
      nextEpoch
      && WORKSPACE_EPOCH in nextEpoch
      && nextEpoch[WORKSPACE_EPOCH] !== current.parent?.data[WORKSPACE_EPOCH]
    ) {
      return false;
    }

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

    if (
      routePath === 'apps/:id' &&
      future.routeConfig === current.routeConfig &&
      future.paramMap.get('id') !== current.paramMap.get('id')
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
