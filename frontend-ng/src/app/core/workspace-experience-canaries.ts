/**
 * Rollout canaries: the live workspaces the shadow gate must prove before the
 * workspace-experience resolver rolls out.
 *
 * This is deployment knowledge, not resolver logic: which workspaces a rollout
 * must not break is a fact about this deployment's customers. It lives here,
 * apart from the generic resolver in `workspace-experience.ts`, which takes the
 * list as a parameter (docs/adr/0003-generalisation-frontieres.md).
 */
import {
  BUSINESS_PRIMARY_SURFACE_IDS,
  MISSION_ROOM_NAVIGATION_KEYS,
  type WorkspaceExperienceCriticalScenario,
} from './workspace-experience';

const ANDRITZ_SETTINGS = {
  navigation_profile: {
    key: 'business_end_user',
    default_route: '/chat',
    primary_surfaces: [...BUSINESS_PRIMARY_SURFACE_IDS],
    advanced_access: 'admin_only',
  },
};

const SENTINEL_SETTINGS = {
  demo_profile: 'government_mission_room',
  workspace_app_shell: 'immersive',
  workspace_app_label: 'SENTINEL-CI',
  workspace_app_default_view: 'cockpit',
  default_route: '/hypervisor/mission-room/cockpit',
  mission_room: {
    enabled: true,
    profile: 'sentinel_government_v1',
    navigation: MISSION_ROOM_NAVIGATION_KEYS.map((key) => ({ key })),
  },
};

const OCTOCITY_SETTINGS = {
  demo_profile: 'octocity_mission_room',
  workspace_app_shell: 'immersive',
  workspace_app_label: 'Octocity Mission Room',
  workspace_app_default_view: 'cockpit',
  default_route: '/hypervisor/mission-room/cockpit',
  assistant_profile_default: 'octave_executive',
  mission_room: {
    enabled: true,
    profile: 'octocity_institutional_v1',
    label: 'Mission Room',
    assistant_label: 'OCTAVE',
    brand: { style: 'agentium' },
    navigation: MISSION_ROOM_NAVIGATION_KEYS.map((key) => ({ key })),
  },
};

export const ANDRITZ_CRITICAL_SCENARIOS: readonly WorkspaceExperienceCriticalScenario[] = Object.freeze([
  { id: 'andritz-member', input: { workspace: { slug: 'andritz', mode: 'builder', settings: ANDRITZ_SETTINGS }, scenario: { role: 'member', businessPreview: false, requestedRoute: '/systems' } }, requiresMissionNavigationObservation: false },
  { id: 'andritz-admin', input: { workspace: { slug: 'andritz', mode: 'builder', settings: ANDRITZ_SETTINGS }, scenario: { role: 'admin', businessPreview: false, requestedRoute: '/systems' } }, requiresMissionNavigationObservation: false },
  { id: 'andritz-admin-preview', input: { workspace: { slug: 'andritz', mode: 'builder', settings: ANDRITZ_SETTINGS }, scenario: { role: 'admin', businessPreview: true, requestedRoute: '/systems' } }, requiresMissionNavigationObservation: false },
]);

export const MISSION_ROOM_CRITICAL_SCENARIOS: readonly WorkspaceExperienceCriticalScenario[] = Object.freeze([
  { id: 'sentinel-home', input: { workspace: { slug: 'sentinel-ci', mode: 'demo', settings: SENTINEL_SETTINGS }, scenario: { role: 'admin', requestedRoute: '/hypervisor' } }, requiresMissionNavigationObservation: true },
  { id: 'sentinel-standard', input: { workspace: { slug: 'sentinel-ci', mode: 'demo', settings: SENTINEL_SETTINGS }, scenario: { role: 'admin', requestedRoute: '/systems' } }, requiresMissionNavigationObservation: true },
  { id: 'octocity-home', input: { workspace: { slug: 'octocity-mission-room', mode: 'demo', settings: OCTOCITY_SETTINGS }, scenario: { role: 'admin', requestedRoute: '/hypervisor' } }, requiresMissionNavigationObservation: true },
  { id: 'octocity-standard', input: { workspace: { slug: 'octocity-mission-room', mode: 'demo', settings: OCTOCITY_SETTINGS }, scenario: { role: 'admin', requestedRoute: '/systems' } }, requiresMissionNavigationObservation: true },
]);

export const WORKSPACE_EXPERIENCE_CRITICAL_SCENARIOS: readonly WorkspaceExperienceCriticalScenario[] = Object.freeze([
  ...ANDRITZ_CRITICAL_SCENARIOS,
  ...MISSION_ROOM_CRITICAL_SCENARIOS,
]);

export const SHOWCASE_PORTFOLIO_SCENARIO: WorkspaceExperienceCriticalScenario = Object.freeze({
  id: 'showcase-portfolio',
  input: { workspace: { slug: 'showcase', mode: 'portfolio', settings: {} }, scenario: { role: 'admin', requestedRoute: '/systems' } },
  requiresMissionNavigationObservation: false,
});
