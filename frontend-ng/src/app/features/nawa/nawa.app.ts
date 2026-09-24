import type { ClientApplicationRoute } from '@app/core/client-applications';
import type { AgentiumSurfaceRoute } from '@app/core/navigation.catalog';

/**
 * The NAWA application as the product shell sees it.
 *
 * Dependency-free on purpose, like the Mission Room extension descriptor: the
 * navigation catalogue and the router read it without importing any NAWA
 * component. The components load only through the lazy route below.
 */

/**
 * Catalogue entries of the NAWA surfaces. The workspace home
 * (`navigation_profile.default_route: /nawa/itsd`) resolves through this entry;
 * without it the home falls back to /work.
 */
export const NAWA_SURFACES: readonly AgentiumSurfaceRoute[] = [
  {
    id: 'nawa-itsd',
    label: 'Nawa ITSD',
    route: '/nawa/itsd',
    routeAliases: ['/nawa/itsd/password-reset'],
    lens: 'operate',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/runs',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'IT automation use-case catalogue and the Password Reset simulation bench.',
  },
];

/** Mounted outside the Agentium shell: the application owns the whole page. */
export const NAWA_ROUTE: ClientApplicationRoute = {
  path: 'nawa',
  loadChildren: () => import('./nawa.routes').then((m) => m.nawaRoutes),
};
