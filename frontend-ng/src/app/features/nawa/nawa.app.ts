import type { ClientApplicationRoute } from '@app/core/client-application-routes';

/**
 * The route the NAWA application owns, mounted outside the Agentium shell:
 * the application owns the whole page. Its components load only through this
 * lazy route; its catalogue surfaces live in nawa.surfaces.ts.
 */
export const NAWA_ROUTE: ClientApplicationRoute = {
  path: 'nawa',
  loadChildren: () => import('./nawa.routes').then((m) => m.nawaRoutes),
};
