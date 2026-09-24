import { NAWA_SURFACES } from '@app/features/nawa/nawa.surfaces';
import type { AgentiumSurfaceRoute } from './navigation.catalog';

/**
 * The catalogue surfaces of the customer applications this build carries.
 *
 * A customer application lives in `features/<customer>/` and declares its
 * surfaces in `<customer>.surfaces.ts`, pure data; the navigation catalogue
 * spreads them in and names no customer. Its route is listed apart, in
 * client-application-routes.ts (kind `composition` in the tenant-neutral
 * baseline).
 */
export const CLIENT_APPLICATION_SURFACES: readonly AgentiumSurfaceRoute[] = [...NAWA_SURFACES];
