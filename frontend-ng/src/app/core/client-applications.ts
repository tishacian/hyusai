import type { LoadChildrenCallback } from '@angular/router';
import { NAWA_ROUTE, NAWA_SURFACES } from '@app/features/nawa/nawa.app';
import type { AgentiumSurfaceRoute } from './navigation.catalog';

/**
 * The customer applications this build carries, and the product's only list
 * of them.
 *
 * A customer application lives in `features/<customer>/` and describes itself
 * in a dependency-free `<customer>.app.ts`: the route it owns and its catalogue
 * surfaces. The router mounts the routes outside the Agentium shell and the
 * navigation catalogue lists the surfaces; neither names a customer. Adding an
 * application adds one import here (kind `composition` in the tenant-neutral
 * baseline), nothing in the shell.
 */

export interface ClientApplicationRoute {
  /** The first URL segment the application owns. */
  readonly path: string;
  readonly loadChildren: LoadChildrenCallback;
}

export const CLIENT_APPLICATION_ROUTES: readonly ClientApplicationRoute[] = [NAWA_ROUTE];

export const CLIENT_APPLICATION_SURFACES: readonly AgentiumSurfaceRoute[] = [...NAWA_SURFACES];
