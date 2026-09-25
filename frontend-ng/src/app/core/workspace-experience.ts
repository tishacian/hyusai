/**
 * Pure, side-effect-free workspace experience model. The V2 projection is
 * executed only when the workspace feature flag is enabled; the independent
 * legacy projection remains the compatibility oracle and rollback path.
 */

import type {
  WorkspaceAppRuntimeExperience,
  WorkspaceAppRuntimeInstallation,
  WorkspaceAppRuntimeProjection,
} from './workspace.service';

export const WORKSPACE_EXPERIENCE_SCHEMA_VERSION = 2 as const;
export const WORKSPACE_EXPERIENCE_EVIDENCE_SCHEMA_VERSION = 1 as const;
export const WORKSPACE_EXPERIENCE_RESOLVER_VERSION = 'workspace-experience-v2.flagged.1' as const;
export const WORKSPACE_APP_UNAVAILABLE_ROUTE = '/workspace-app-unavailable' as const;
export const WORKSPACE_APP_REPAIR_ROUTE = '/workspace-app-repair' as const;

export const BUSINESS_PRIMARY_SURFACE_IDS = [
  'chat',
  'client360-pdr',
  'knowledge-capture',
  'fse-reports',
] as const;

export const FULL_COCKPIT_VERBS = ['hypervisor', 'build', 'operate', 'steer', 'govern'] as const;
export const BUILDER_COCKPIT_VERBS = ['build', 'operate', 'govern'] as const;
export const MISSION_ROOM_NAVIGATION_KEYS = [
  'cockpit',
  'strategie',
  'securite',
  'reputation',
  'agenda',
  'presse',
  'decisions',
] as const;

// Independent legacy UI anchors. These literals intentionally do not reuse
// the candidate registry constants above: changing a V2 expectation must not
// move the compatibility oracle with it and create a synthetic false match.
const LEGACY_BUSINESS_HEADER_SURFACE_IDS = [
  'chat',
  'client360-pdr',
  'knowledge-capture',
  'fse-reports',
] as const;
const LEGACY_FULL_SIDE_RAIL_VERBS = [
  'hypervisor',
  'build',
  'operate',
  'steer',
  'govern',
] as const;
const LEGACY_BUILDER_SIDE_RAIL_VERBS = ['build', 'operate', 'govern'] as const;
const LEGACY_MISSION_ROOM_FALLBACK_KEYS = [
  'cockpit',
  'strategie',
  'securite',
  'reputation',
  'agenda',
  'presse',
  'decisions',
] as const;

export type WorkspaceExperienceShellKind =
  | 'agentium_standard'
  | 'business'
  | 'workspace_app_immersive'
  | 'workspace_focus'
  | 'workspace_app_unavailable';

export type WorkspaceExperienceAdvancedAccess = 'admin_only' | 'link' | 'hidden';
export type WorkspaceExperienceIssueKind = 'error' | 'unknown_adapter';

export interface WorkspaceExperienceWorkspace {
  slug: string;
  mode?: string | null;
  settings?: Readonly<Record<string, unknown>> | null;
  appEntitlements?: readonly string[] | null;
  appRuntime?: WorkspaceAppRuntimeProjection | null;
}

export interface WorkspaceExperienceScenario {
  role?: string | null;
  roleTemplate?: string | null;
  businessPreview?: boolean;
  requestedRoute: string;
}

export interface WorkspaceExperienceInput {
  workspace: WorkspaceExperienceWorkspace;
  scenario: WorkspaceExperienceScenario;
}

export interface WorkspaceExperienceChrome {
  titleBar: boolean;
  sideRail: boolean;
  objectIndex: boolean;
  commandBar: boolean;
  commandPalette: boolean;
  businessHeader: boolean;
  missionRail: boolean;
}

export interface WorkspaceExperienceRouteResolution {
  requestedRoute: string;
  resolvedRoute: string;
  /** Presence-only semantic query contract; values are never retained. */
  semanticQueryKeys: string[];
  /** Whether a workspace route still targets the active workspace. */
  workspaceTargetMatchesCurrent: boolean | null;
  /** Whether a System capture redirect forwards the requested System id. */
  semanticTargetPreserved: boolean | null;
  redirectOwner: 'legacy_navigation_resolver' | 'workspace_experience_v2';
  redirectReason:
    | 'none'
    | 'business_profile_disallowed'
    | 'business_knowledge_compatibility'
    | 'business_system_capture_compatibility'
    | 'workspace_default_route'
    | 'workspace_extension_unavailable'
    | 'legacy_hypervisor_object_lens'
    | 'legacy_focus_query'
    | 'legacy_tab_query'
    | 'legacy_system_id_query'
    | 'legacy_mission_room_path'
    | 'legacy_theme_query'
    | 'workspace_mode_home'
    | 'workspace_settings_entrypoint';
}

export interface WorkspaceExperienceBusinessProjection {
  configured: boolean;
  active: boolean;
  admin: boolean;
  preview: boolean;
  declaredPrimarySurfaceIds: string[];
}

export interface WorkspaceExperienceWorkspaceAppProjection {
  configured: boolean;
  shell: string | null;
  profile: string | null;
  defaultView: string | null;
  immersiveRouteScope: string | null;
}

export interface WorkspaceExperienceMissionRoomProjection {
  profile: string;
  label: string;
  assistantLabel: string;
  assistantProfile: string;
  brandStyle: string;
  navigationKeys: string[];
}

export interface WorkspaceExperienceIssue {
  kind: WorkspaceExperienceIssueKind;
  code: string;
  path: string;
}

export interface WorkspaceExperienceV2 {
  schemaVersion: typeof WORKSPACE_EXPERIENCE_SCHEMA_VERSION;
  resolverVersion: typeof WORKSPACE_EXPERIENCE_RESOLVER_VERSION;
  workspaceSlug: string;
  scenarioKey: string;
  registryEntryIds: string[];
  shellKind: WorkspaceExperienceShellKind;
  homeRoute: string;
  primarySurfaceIds: string[];
  advancedAccess: WorkspaceExperienceAdvancedAccess;
  chrome: WorkspaceExperienceChrome;
  workspaceApp: WorkspaceExperienceWorkspaceAppProjection;
  immersiveRouteScope: string | null;
  cockpitVerbs: string[];
  routeResolution: WorkspaceExperienceRouteResolution;
  business: WorkspaceExperienceBusinessProjection;
  missionRoom: WorkspaceExperienceMissionRoomProjection | null;
  issues: WorkspaceExperienceIssue[];
  provenance: string[];
}

export interface LegacyWorkspaceExperience
  extends Omit<WorkspaceExperienceV2, 'schemaVersion' | 'resolverVersion' | 'registryEntryIds'> {
  schemaVersion: 1;
  resolverVersion: 'legacy-navigation-2026-07';
  registryEntryIds: [];
  missionNavigationObservation: 'not_required' | 'missing' | 'observed' | 'error';
}

export interface MissionNavigationObservation {
  app?: {
    label?: unknown;
    assistant_label?: unknown;
    shell?: unknown;
    default_route?: unknown;
    default_view?: unknown;
    profile?: unknown;
    brand?: {
      label?: unknown;
      lines?: unknown;
      emblem?: unknown;
      style?: unknown;
    } | null;
  } | null;
  items?: ReadonlyArray<{ key?: unknown }> | null;
  error?: unknown;
  /** Presence-only shadow metadata; never accepted from or exposed to UI. */
  brandHasFields?: boolean;
}

interface ExperienceAdapterState {
  businessConfigured: boolean;
  portfolio: boolean;
  workspaceAppShell: string | null;
  missionRoom: WorkspaceExperienceMissionRoomProjection | null;
  provenance: string[];
}

export interface WorkspaceExperienceAdapter {
  readonly id:
    | 'portfolio'
    | 'mission_room_sentinel_legacy'
    | 'mission_room_octocity'
    | 'workspace_app_shell'
    | 'business_end_user';
  readonly priority: number;
  matches(input: WorkspaceExperienceInput): boolean;
  apply(input: WorkspaceExperienceInput, state: ExperienceAdapterState): ExperienceAdapterState;
}

const STANDARD_CHROME: WorkspaceExperienceChrome = {
  titleBar: true,
  sideRail: true,
  objectIndex: true,
  commandBar: true,
  commandPalette: true,
  businessHeader: false,
  missionRail: false,
};

const GOVERNMENT_MISSION_ROOM: WorkspaceExperienceMissionRoomProjection = {
  profile: 'sentinel_government_v1',
  label: 'SENTINEL-CI',
  assistantLabel: 'AYA',
  assistantProfile: 'vigie_executive',
  brandStyle: 'sentinel',
  navigationKeys: [...MISSION_ROOM_NAVIGATION_KEYS],
};

const OCTOCITY_MISSION_ROOM: WorkspaceExperienceMissionRoomProjection = {
  profile: 'octocity_institutional_v1',
  label: 'Octocity Mission Room',
  assistantLabel: 'OCTAVE',
  assistantProfile: 'octave_executive',
  brandStyle: 'agentium',
  navigationKeys: [...MISSION_ROOM_NAVIGATION_KEYS],
};

function record(value: unknown): Readonly<Record<string, unknown>> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Readonly<Record<string, unknown>>
    : {};
}

function settings(input: WorkspaceExperienceInput): Readonly<Record<string, unknown>> {
  return record(input.workspace.settings);
}

function navigationConfig(input: WorkspaceExperienceInput): Readonly<Record<string, unknown>> {
  return record(settings(input)['navigation_profile']);
}

function missionConfig(input: WorkspaceExperienceInput): Readonly<Record<string, unknown>> {
  return record(settings(input)['mission_room']);
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function absoluteRoute(value: unknown): string | null {
  const route = stringValue(value);
  return route?.startsWith('/') ? route : null;
}

function pathOnly(value: string): string {
  const withoutQuery = (value || '/').split('?')[0].split('#')[0] || '/';
  return withoutQuery.startsWith('/') ? withoutQuery : `/${withoutQuery}`;
}

function isAdminScenario(scenario: WorkspaceExperienceScenario): boolean {
  const role = (scenario.role || '').toLowerCase();
  const template = (scenario.roleTemplate || '').toLowerCase();
  return role === 'owner'
    || role === 'admin'
    || template === 'workspace_owner'
    || template === 'workspace_admin';
}

function featureEnabled(input: WorkspaceExperienceInput, feature: string): boolean {
  return record(settings(input)['features'])[feature] === true;
}

function entitledBusinessSurfaces(input: WorkspaceExperienceInput): string[] {
  if (!featureEnabled(input, 'app_entitlements_v1')) {
    return [...BUSINESS_PRIMARY_SURFACE_IDS];
  }
  const grants = Array.isArray(input.workspace.appEntitlements)
    ? new Set(input.workspace.appEntitlements.filter((item): item is string => typeof item === 'string'))
    : new Set<string>();
  return BUSINESS_PRIMARY_SURFACE_IDS.filter((surfaceId) => grants.has(surfaceId));
}

function businessSurfaceRoute(surfaceId: string): string | null {
  if (surfaceId === 'chat') return '/chat';
  if (surfaceId === 'client360-pdr') return '/client360';
  if (surfaceId === 'knowledge-capture') return '/knowledge/capture';
  if (surfaceId === 'fse-reports') return '/knowledge/interventions';
  return null;
}

function businessSurfaceEnabled(input: WorkspaceExperienceInput, surfaceId: string): boolean {
  return entitledBusinessSurfaces(input).includes(surfaceId);
}

function isBusinessAllowedPath(input: WorkspaceExperienceInput, path: string): boolean {
  const normalized = pathOnly(path);
  return (businessSurfaceEnabled(input, 'chat') && normalized === '/chat')
    || (businessSurfaceEnabled(input, 'client360-pdr') && (
      normalized === '/client360' || normalized.startsWith('/client360/')
    ))
    || (businessSurfaceEnabled(input, 'knowledge-capture') && normalized === '/knowledge/capture')
    || (businessSurfaceEnabled(input, 'fse-reports') && normalized === '/knowledge/interventions')
    || normalized === '/account'
    || normalized.startsWith('/account/');
}

function configuredBusinessRoute(input: WorkspaceExperienceInput): string {
  const configured = absoluteRoute(navigationConfig(input)['default_route']);
  // The resolver may execute a configured query string, but the experience
  // contract deliberately retains paths only. Query values must never enter a
  // report or its fingerprint.
  if (configured && isBusinessAllowedPath(input, configured)) return pathOnly(configured);
  for (const surfaceId of entitledBusinessSurfaces(input)) {
    const route = businessSurfaceRoute(surfaceId);
    if (route) return route;
  }
  return '/account/profile';
}

function declaredBusinessSurfaces(input: WorkspaceExperienceInput): string[] {
  const raw = navigationConfig(input)['primary_surfaces'];
  if (!Array.isArray(raw) || !raw.length) return [...BUSINESS_PRIMARY_SURFACE_IDS];
  const values = raw.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
    .map((item) => item.trim());
  return values.length ? values : [...BUSINESS_PRIMARY_SURFACE_IDS];
}

function advancedAccess(input: WorkspaceExperienceInput): WorkspaceExperienceAdvancedAccess {
  const value = navigationConfig(input)['advanced_access'];
  return value === 'link' || value === 'hidden' || value === 'admin_only' ? value : 'admin_only';
}

function missionNavigationKeysFromSettings(input: WorkspaceExperienceInput): string[] {
  const raw = missionConfig(input)['navigation'];
  if (!Array.isArray(raw)) return [...MISSION_ROOM_NAVIGATION_KEYS];
  const present = new Set(raw.map((item) => stringValue(record(item)['key'])).filter((key): key is string => Boolean(key)));
  return MISSION_ROOM_NAVIGATION_KEYS.filter((key) => present.has(key));
}

function missionValue(input: WorkspaceExperienceInput, key: string): string | null {
  return stringValue(missionConfig(input)[key]) || stringValue(settings(input)[key]);
}

function missionApiBrand(input: WorkspaceExperienceInput): Readonly<Record<string, unknown>> {
  const nested = missionConfig(input)['brand'];
  if (isPlainObject(nested)) return nested;
  const root = settings(input)['workspace_app_brand'];
  return isPlainObject(root) ? root : {};
}

function missionRenderedBrand(input: WorkspaceExperienceInput): Readonly<Record<string, unknown>> {
  const apiBrand = missionApiBrand(input);
  if (Object.keys(apiBrand).length > 0) return apiBrand;
  const root = settings(input)['workspace_app_brand'];
  return isPlainObject(root) ? root : {};
}

function missionBrandStyle(input: WorkspaceExperienceInput, fallback: string): string {
  return stringValue(missionRenderedBrand(input)['style']) || fallback;
}

function missionAppLabel(input: WorkspaceExperienceInput, fallback: string): string {
  return stringValue(settings(input)['workspace_app_label'])
    || stringValue(missionApiBrand(input)['label'])
    || fallback;
}

function missionRenderedBrandLabel(
  input: WorkspaceExperienceInput,
  appLabel: string,
  fallback: string,
): string {
  return stringValue(missionRenderedBrand(input)['label']) || appLabel || fallback;
}

function missionProjection(
  input: WorkspaceExperienceInput,
  profile: 'sentinel_government_v1' | 'octocity_institutional_v1',
): WorkspaceExperienceMissionRoomProjection {
  const defaults = profile === 'octocity_institutional_v1' ? OCTOCITY_MISSION_ROOM : GOVERNMENT_MISSION_ROOM;
  const appLabel = missionAppLabel(input, defaults.label);
  return {
    profile,
    // This is the label actually rendered by MissionRoomComponent: a
    // non-empty API brand object owns its label, then app.label is the
    // fallback. `mission_room.label` remains the assistant fallback.
    label: missionRenderedBrandLabel(input, appLabel, defaults.label),
    assistantLabel: stringValue(missionConfig(input)['assistant_label'])
      || stringValue(missionConfig(input)['label'])
      || defaults.assistantLabel,
    assistantProfile: missionValue(input, 'assistant_profile_default') || defaults.assistantProfile,
    brandStyle: missionBrandStyle(input, defaults.brandStyle),
    navigationKeys: missionNavigationKeysFromSettings(input),
  };
}

interface AuthoritativeWorkspaceAppState {
  runtime: WorkspaceAppRuntimeProjection;
  experience: WorkspaceAppRuntimeExperience;
  installations: WorkspaceAppRuntimeInstallation[];
}

function workspaceAppPlatformEnabled(input: WorkspaceExperienceInput): boolean {
  return featureEnabled(input, 'workspace_app_platform_v1');
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value)
    && value.every((item) => typeof item === 'string' && item.trim().length > 0);
}

function orderedUniqueStrings(values: readonly string[]): string[] {
  return [...new Set(values)];
}

function sameStringArray(left: unknown, right: readonly string[]): boolean {
  return stringArray(left)
    && left.length === right.length
    && left.every((value, index) => value === right[index]);
}

function sameStringRecord(left: unknown, right: Readonly<Record<string, string>>): boolean {
  if (!isPlainObject(left)) return false;
  const leftEntries = Object.entries(left).sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey));
  const rightEntries = Object.entries(right).sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey));
  return leftEntries.length === rightEntries.length
    && leftEntries.every(([key, value], index) => (
      key === rightEntries[index]?.[0] && value === rightEntries[index]?.[1]
    ));
}

function runtimeContract(
  input: WorkspaceExperienceInput,
): { state: AuthoritativeWorkspaceAppState | null; issues: WorkspaceExperienceIssue[] } {
  const issues: WorkspaceExperienceIssue[] = [];
  const rawRuntime: unknown = input.workspace.appRuntime;
  if (!isPlainObject(rawRuntime)) {
    return {
      state: null,
      issues: [issue('error', 'workspace_app_runtime_missing', '/workspace/workspace_app_runtime')],
    };
  }
  if (
    rawRuntime['schema_version'] !== 1
    || rawRuntime['mode'] !== 'authoritative'
    || rawRuntime['enabled'] !== true
    || rawRuntime['valid'] !== true
  ) {
    return {
      state: null,
      issues: [issue('error', 'workspace_app_runtime_invalid', '/workspace/workspace_app_runtime')],
    };
  }
  const rolloutPhase = rawRuntime['rollout_phase'];
  const rolloutRef = rawRuntime['rollout_ref'];
  if (
    !['probation', 'active'].includes(String(rolloutPhase))
    || typeof rolloutRef !== 'string'
    || !/^sha256:[0-9a-f]{64}$/.test(rolloutRef)
  ) {
    return {
      state: null,
      issues: [issue(
        'error',
        'workspace_app_runtime_attestation_invalid',
        '/workspace/workspace_app_runtime/rollout_ref',
      )],
    };
  }

  const rawInstallations = rawRuntime['installations'];
  const rawExperience = rawRuntime['experience'];
  if (
    !Array.isArray(rawInstallations)
    || rawInstallations.length === 0
    || !isPlainObject(rawExperience)
  ) {
    return {
      state: null,
      issues: [issue('error', 'workspace_app_runtime_malformed', '/workspace/workspace_app_runtime')],
    };
  }

  const shell = rawExperience['shell'];
  if (!['standard', 'business', 'immersive'].includes(String(shell))) {
    issues.push(issue('error', 'workspace_app_runtime_shell_invalid', '/workspace/workspace_app_runtime/experience/shell'));
  }
  for (const [key, value] of [
    ['routes', rawExperience['routes']],
    ['primary_surface_ids', rawExperience['primary_surface_ids']],
    ['branding_namespaces', rawExperience['branding_namespaces']],
    ['api_prefixes', rawExperience['api_prefixes']],
    ['action_packs', rawExperience['action_packs']],
  ] as const) {
    if (!stringArray(value)) {
      if (!Array.isArray(value) || value.length > 0) {
        issues.push(issue('error', 'workspace_app_runtime_malformed', `/workspace/workspace_app_runtime/experience/${key}`));
      }
    }
  }
  const routes = stringArray(rawExperience['routes']) ? rawExperience['routes'] : [];
  if (routes.some((route) => !route.startsWith('/'))) {
    issues.push(issue('error', 'workspace_app_runtime_route_invalid', '/workspace/workspace_app_runtime/experience/routes'));
  }
  const apiPrefixes = stringArray(rawExperience['api_prefixes'])
    ? rawExperience['api_prefixes']
    : [];
  if (apiPrefixes.some((prefix) => !prefix.startsWith('/api/v1/'))) {
    issues.push(issue('error', 'workspace_app_runtime_api_prefix_invalid', '/workspace/workspace_app_runtime/experience/api_prefixes'));
  }
  const rawDefaultRoutes = rawExperience['default_routes'];
  if (!isPlainObject(rawDefaultRoutes) || Object.values(rawDefaultRoutes).some((route) => (
    typeof route !== 'string' || !route.startsWith('/')
  ))) {
    issues.push(issue('error', 'workspace_app_runtime_default_route_invalid', '/workspace/workspace_app_runtime/experience/default_routes'));
  }

  const installations: WorkspaceAppRuntimeInstallation[] = [];
  for (let index = 0; index < rawInstallations.length; index += 1) {
    const value = rawInstallations[index];
    if (
      !isPlainObject(value)
      || !stringValue(value['app_id'])
      || !stringValue(value['version'])
      || !stringValue(value['manifest_digest'])
      || !stringValue(value['category'])
      || !stringValue(value['primary_surface_id'])
      || !absoluteRoute(value['default_route'])
      || !stringValue(value['branding_namespace'])
      || !stringArray(value['routes'])
      || !stringArray(value['api_prefixes'])
      || !stringArray(value['action_packs'])
      || !stringArray(value['entitlement_keys'])
      || value['routes'].some((route) => !route.startsWith('/'))
      || value['api_prefixes'].some((prefix) => !prefix.startsWith('/api/v1/'))
      || !value['routes'].some((route) => routeWithinScope(String(value['default_route']), route))
    ) {
      issues.push(issue('error', 'workspace_app_runtime_installation_invalid', `/workspace/workspace_app_runtime/installations/${index}`));
      continue;
    }
    installations.push(value as unknown as WorkspaceAppRuntimeInstallation);
  }

  if (installations.length === rawInstallations.length) {
    const expectedRoutes = orderedUniqueStrings(installations.flatMap((item) => item.routes));
    const expectedSurfaces = orderedUniqueStrings(installations.map((item) => item.primary_surface_id));
    const expectedBranding = orderedUniqueStrings(installations.map((item) => item.branding_namespace));
    const expectedApiPrefixes = orderedUniqueStrings(installations.flatMap((item) => item.api_prefixes));
    const expectedActionPacks = orderedUniqueStrings(installations.flatMap((item) => item.action_packs));
    const expectedDefaults = Object.fromEntries(installations.map((item) => [item.app_id, item.default_route]));
    if (
      !sameStringArray(rawExperience['routes'], expectedRoutes)
      || !sameStringArray(rawExperience['primary_surface_ids'], expectedSurfaces)
      || !sameStringArray(rawExperience['branding_namespaces'], expectedBranding)
      || !sameStringArray(rawExperience['api_prefixes'], expectedApiPrefixes)
      || !sameStringArray(rawExperience['action_packs'], expectedActionPacks)
      || !sameStringRecord(rawExperience['default_routes'], expectedDefaults)
    ) {
      issues.push(issue('error', 'workspace_app_runtime_aggregate_mismatch', '/workspace/workspace_app_runtime/experience'));
    }
  }

  const mission = rawExperience['mission_room'];
  if (mission !== null && mission !== undefined) {
    const providerKind = isPlainObject(mission) ? mission['provider_kind'] : undefined;
    const providerEndpoints = isPlainObject(mission) ? mission['provider_endpoints'] : undefined;
    if (
      !isPlainObject(mission)
      || !stringValue(mission['profile'])
      || !stringValue(mission['assistant_profile'])
      || !stringValue(mission['label'])
      || !stringValue(mission['assistant_label'])
      || !stringValue(mission['brand_style'])
      || !stringArray(mission['navigation_keys'])
      || !stringValue(mission['app_id'])
      || !stringValue(mission['version'])
      || !stringValue(mission['manifest_digest'])
      || !absoluteRoute(mission['default_route'])
      || !stringValue(mission['primary_surface_id'])
      || ((providerKind !== undefined || providerEndpoints !== undefined) && (
        !stringValue(providerKind) || !stringArray(providerEndpoints)
      ))
    ) {
      issues.push(issue('error', 'workspace_app_runtime_mission_room_invalid', '/workspace/workspace_app_runtime/experience/mission_room'));
    } else {
      const owner = installations.find((installation) => installation.app_id === mission['app_id']);
      if (
        !owner
        || owner.version !== mission['version']
        || owner.manifest_digest !== mission['manifest_digest']
        || owner.primary_surface_id !== mission['primary_surface_id']
        || owner.default_route !== mission['default_route']
      ) {
        issues.push(issue('error', 'workspace_app_runtime_mission_room_owner_mismatch', '/workspace/workspace_app_runtime/experience/mission_room'));
      }
    }
  }
  if (shell === 'immersive' && !isPlainObject(mission)) {
    issues.push(issue('error', 'workspace_app_runtime_mission_room_missing', '/workspace/workspace_app_runtime/experience/mission_room'));
  }
  if (shell !== 'immersive' && mission !== null) {
    issues.push(issue('error', 'workspace_app_runtime_mission_room_unexpected', '/workspace/workspace_app_runtime/experience/mission_room'));
  }

  const primarySurfaceIds = stringArray(rawExperience['primary_surface_ids'])
    ? rawExperience['primary_surface_ids']
    : [];
  if (shell === 'business' && !primarySurfaceIds.some((surface) => (
    (BUSINESS_PRIMARY_SURFACE_IDS as readonly string[]).includes(surface)
  ))) {
    issues.push(issue('error', 'workspace_app_runtime_business_surface_missing', '/workspace/workspace_app_runtime/experience/primary_surface_ids'));
  }
  if (shell === 'business' && primarySurfaceIds.some((surface) => (
    !(BUSINESS_PRIMARY_SURFACE_IDS as readonly string[]).includes(surface)
  ))) {
    issues.push(issue('error', 'workspace_app_runtime_business_surface_unknown', '/workspace/workspace_app_runtime/experience/primary_surface_ids'));
  }

  if (issues.some((item) => item.kind === 'error')) {
    return { state: null, issues };
  }
  return {
    state: {
      runtime: rawRuntime as unknown as WorkspaceAppRuntimeProjection,
      experience: rawExperience as unknown as WorkspaceAppRuntimeExperience,
      installations,
    },
    issues,
  };
}

function authoritativeInstalledBusinessSurfaces(
  state: AuthoritativeWorkspaceAppState,
): string[] {
  return BUSINESS_PRIMARY_SURFACE_IDS.filter((surfaceId) => {
    const expectedRoute = businessSurfaceRoute(surfaceId);
    return Boolean(expectedRoute && state.installations.some((installation) => (
      installation.entitlement_keys.includes(surfaceId)
      && installation.routes.some((route) => routeWithinScope(expectedRoute, route))
    )));
  });
}

function authoritativeBusinessSurfaces(
  input: WorkspaceExperienceInput,
  state: AuthoritativeWorkspaceAppState,
): string[] {
  const canonical = authoritativeInstalledBusinessSurfaces(state);
  // Workspace App runtime authority owns both the installed surface set and
  // its membership grants.  Once the platform gate is on, falling back to
  // every installed surface when the legacy entitlement flag is absent would
  // disagree with the backend entry dependency and briefly render links that
  // are guaranteed to return 403.
  const grants = new Set(Array.isArray(input.workspace.appEntitlements)
    ? input.workspace.appEntitlements.filter((item): item is string => typeof item === 'string')
    : []);
  return canonical.filter((surface) => grants.has(surface));
}

function installationForSurface(
  state: AuthoritativeWorkspaceAppState,
  surfaceId: string,
): WorkspaceAppRuntimeInstallation | null {
  return state.installations.find((installation) => installation.entitlement_keys.includes(surfaceId)) ?? null;
}

function authoritativeBusinessDefaultRoute(
  input: WorkspaceExperienceInput,
  state: AuthoritativeWorkspaceAppState,
): string {
  for (const surfaceId of authoritativeBusinessSurfaces(input, state)) {
    const route = installationForSurface(state, surfaceId)?.default_route;
    if (route) return pathOnly(route);
  }
  return '/account/profile';
}

function routeWithinScope(path: string, route: string): boolean {
  const normalized = pathOnly(path);
  const scope = pathOnly(route).replace(/\/$/, '');
  return normalized === scope || normalized.startsWith(`${scope}/`);
}

function authoritativeBusinessAllowedPath(
  input: WorkspaceExperienceInput,
  state: AuthoritativeWorkspaceAppState,
  path: string,
): boolean {
  const normalized = pathOnly(path);
  if (normalized === '/account' || normalized.startsWith('/account/')) return true;
  return authoritativeBusinessSurfaces(input, state).some((surfaceId) => {
    const installation = installationForSurface(state, surfaceId);
    return Boolean(installation?.routes.some((route) => routeWithinScope(normalized, route)));
  });
}

function authoritativeDefaultRoute(state: AuthoritativeWorkspaceAppState): string | null {
  if (state.experience.mission_room?.default_route) {
    return pathOnly(state.experience.mission_room.default_route);
  }
  for (const installation of state.installations) {
    if (installation.default_route) return pathOnly(installation.default_route);
  }
  return null;
}

function resolveAuthoritativeRoute(
  input: WorkspaceExperienceInput,
  state: AuthoritativeWorkspaceAppState,
  businessActive: boolean,
): WorkspaceExperienceRouteResolution {
  const requestedRoute = pathOnly(input.scenario.requestedRoute);
  let resolvedRoute = requestedRoute;
  let semanticQueryKeys: string[] = [];
  let workspaceTargetMatchesCurrent: boolean | null = null;
  let semanticTargetPreserved: boolean | null = null;
  let redirectReason: WorkspaceExperienceRouteResolution['redirectReason'] = 'none';

  if (businessActive && !authoritativeBusinessAllowedPath(input, state, requestedRoute)) {
    if (
      requestedRoute === '/knowledge'
      && authoritativeBusinessSurfaces(input, state).includes('knowledge-capture')
    ) {
      resolvedRoute = '/knowledge/capture';
      redirectReason = 'business_knowledge_compatibility';
    } else if (
      /^\/systems\/[^/]+\/capture$/.test(requestedRoute)
      && authoritativeBusinessSurfaces(input, state).includes('knowledge-capture')
    ) {
      resolvedRoute = '/knowledge/capture';
      semanticQueryKeys = ['systemId'];
      semanticTargetPreserved = true;
      redirectReason = 'business_system_capture_compatibility';
    } else {
      resolvedRoute = authoritativeBusinessDefaultRoute(input, state);
      redirectReason = 'business_profile_disallowed';
    }
  } else if (
    state.experience.shell === 'immersive'
    && requestedRoute === '/hypervisor'
    && authoritativeDefaultRoute(state)
  ) {
    resolvedRoute = authoritativeDefaultRoute(state) as string;
    redirectReason = 'workspace_default_route';
  } else if (requestedRoute === '/workspace' && input.workspace.slug) {
    resolvedRoute = `/workspace/${encodeURIComponent(input.workspace.slug)}/settings`;
    workspaceTargetMatchesCurrent = true;
    redirectReason = 'workspace_settings_entrypoint';
  }

  return {
    requestedRoute: canonicalRoute(requestedRoute),
    resolvedRoute: canonicalRoute(resolvedRoute),
    semanticQueryKeys,
    workspaceTargetMatchesCurrent,
    semanticTargetPreserved,
    redirectOwner: 'workspace_experience_v2',
    redirectReason,
  };
}

function runtimeMissionProjection(
  state: AuthoritativeWorkspaceAppState,
): WorkspaceExperienceMissionRoomProjection | null {
  const mission = state.experience.mission_room;
  if (!mission) return null;
  return {
    profile: mission.profile,
    label: mission.label,
    assistantLabel: mission.assistant_label,
    assistantProfile: mission.assistant_profile,
    brandStyle: mission.brand_style,
    navigationKeys: [...mission.navigation_keys],
  };
}

function resolveAuthoritativeWorkspaceExperience(
  input: WorkspaceExperienceInput,
): WorkspaceExperienceV2 {
  const { state, issues } = runtimeContract(input);
  const admin = isAdminScenario(input.scenario);
  const preview = Boolean(input.scenario.businessPreview);
  if (!state) {
    const route = pathOnly(input.scenario.requestedRoute);
    const repairAllowed = admin && route === WORKSPACE_APP_REPAIR_ROUTE;
    const terminalUnavailable = route === WORKSPACE_APP_UNAVAILABLE_ROUTE;
    const resolvedRoute = repairAllowed || terminalUnavailable
      ? route
      : WORKSPACE_APP_UNAVAILABLE_ROUTE;
    return {
      schemaVersion: WORKSPACE_EXPERIENCE_SCHEMA_VERSION,
      resolverVersion: WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
      registryEntryIds: [],
      workspaceSlug: input.workspace.slug,
      scenarioKey: workspaceExperienceScenarioKey(input.scenario),
      shellKind: 'workspace_app_unavailable',
      homeRoute: WORKSPACE_APP_UNAVAILABLE_ROUTE,
      primarySurfaceIds: [],
      advancedAccess: 'admin_only',
      chrome: {
        titleBar: false,
        sideRail: false,
        objectIndex: false,
        commandBar: false,
        commandPalette: false,
        businessHeader: false,
        missionRail: false,
      },
      workspaceApp: {
        configured: false,
        shell: null,
        profile: null,
        defaultView: null,
        immersiveRouteScope: null,
      },
      immersiveRouteScope: null,
      cockpitVerbs: [],
      routeResolution: {
        requestedRoute: canonicalRoute(route),
        resolvedRoute: canonicalRoute(resolvedRoute),
        semanticQueryKeys: [],
        workspaceTargetMatchesCurrent: null,
        semanticTargetPreserved: null,
        redirectOwner: 'workspace_experience_v2',
        redirectReason: resolvedRoute === route ? 'none' : 'workspace_extension_unavailable',
      },
      business: {
        configured: false,
        active: false,
        admin,
        preview,
        declaredPrimarySurfaceIds: [],
      },
      missionRoom: null,
      issues,
      provenance: ['workspace_apps:authoritative_fail_closed'],
    };
  }

  const businessConfigured = state.experience.shell === 'business';
  const businessActive = businessConfigured && (!admin || preview);
  const routeResolution = resolveAuthoritativeRoute(input, state, businessActive);
  const focus = /^\/workspace\/[^/]+\/chat$/.test(routeResolution.resolvedRoute);
  const immersive = state.experience.shell === 'immersive'
    && state.experience.routes.some((route) => routeWithinScope(routeResolution.resolvedRoute, route));
  const kind: WorkspaceExperienceShellKind = focus
    ? 'workspace_focus'
    : businessActive
      ? 'business'
      : immersive
        ? 'workspace_app_immersive'
        : 'agentium_standard';
  const cockpitVerbs = kind === 'agentium_standard'
    ? input.workspace.mode === 'builder'
      ? [...BUILDER_COCKPIT_VERBS]
      : [...FULL_COCKPIT_VERBS]
    : [];
  const businessSurfaces = authoritativeBusinessSurfaces(input, state);
  const missionRoom = runtimeMissionProjection(state);
  const primarySurfaceIds = kind === 'business'
    ? businessSurfaces
    : kind === 'workspace_app_immersive'
      ? [...state.experience.primary_surface_ids]
      : [...cockpitVerbs];
  const immersiveRoot = state.experience.shell === 'immersive'
    ? state.experience.routes[0] ?? null
    : null;
  const immersiveRouteScope = immersiveRoot ? `${pathOnly(immersiveRoot).replace(/\/$/, '')}/**` : null;
  const appDefault = authoritativeDefaultRoute(state);
  const homeRoute = businessActive
    ? authoritativeBusinessDefaultRoute(input, state)
    : state.experience.shell === 'immersive' && appDefault
      ? appDefault
      : '/hypervisor';

  return {
    schemaVersion: WORKSPACE_EXPERIENCE_SCHEMA_VERSION,
    resolverVersion: WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
    registryEntryIds: [
      'workspace_app_runtime',
      ...state.installations.map((installation) => `workspace_app:${installation.app_id}`),
    ],
    workspaceSlug: input.workspace.slug,
    scenarioKey: workspaceExperienceScenarioKey(input.scenario),
    shellKind: kind,
    homeRoute: canonicalRoute(pathOnly(homeRoute)),
    primarySurfaceIds,
    advancedAccess: 'admin_only',
    chrome: chromeFor(kind, routeResolution.resolvedRoute),
    workspaceApp: {
      configured: state.installations.length > 0,
      shell: state.experience.shell,
      profile: missionRoom?.profile ?? null,
      defaultView: state.experience.mission_room?.default_route.split('/').filter(Boolean).at(-1) ?? null,
      immersiveRouteScope,
    },
    immersiveRouteScope,
    cockpitVerbs,
    routeResolution,
    business: {
      configured: businessConfigured,
      active: businessActive,
      admin,
      preview,
      declaredPrimarySurfaceIds: BUSINESS_PRIMARY_SURFACE_IDS.filter((surface) => (
        authoritativeInstalledBusinessSurfaces(state).includes(surface)
      )),
    },
    missionRoom,
    issues,
    provenance: [
      'workspace_apps:authoritative',
      ...state.installations.map((installation) => `workspace_app:${installation.app_id}@${installation.version}`),
    ],
  };
}

const ADAPTERS: WorkspaceExperienceAdapter[] = [
  {
    id: 'portfolio',
    priority: 100,
    matches: (input) => input.workspace.mode === 'portfolio',
    apply: (_input, state) => ({ ...state, portfolio: true, provenance: [...state.provenance, 'mode:portfolio'] }),
  },
  {
    id: 'mission_room_sentinel_legacy',
    priority: 200,
    matches: (input) => {
      const profile = missionConfig(input)['profile'];
      return profile === 'sentinel_government_v1'
        || profile === 'government_mission_room'
        || (profile === undefined && settings(input)['demo_profile'] === 'government_mission_room');
    },
    apply: (input, state) => ({
      ...state,
      missionRoom: missionProjection(input, 'sentinel_government_v1'),
      provenance: [...state.provenance, 'mission_room:sentinel_government_v1'],
    }),
  },
  {
    id: 'mission_room_octocity',
    priority: 210,
    matches: (input) => missionConfig(input)['profile'] === 'octocity_institutional_v1'
      || settings(input)['demo_profile'] === 'octocity_mission_room',
    apply: (input, state) => ({
      ...state,
      missionRoom: missionProjection(input, 'octocity_institutional_v1'),
      provenance: [...state.provenance, 'mission_room:octocity_institutional_v1'],
    }),
  },
  {
    id: 'workspace_app_shell',
    priority: 300,
    matches: (input) => settings(input)['workspace_app_shell'] === 'immersive',
    apply: (input, state) => ({
      ...state,
      workspaceAppShell: String(settings(input)['workspace_app_shell']),
      provenance: [...state.provenance, 'workspace_app_shell:immersive'],
    }),
  },
  {
    id: 'business_end_user',
    priority: 400,
    matches: (input) => navigationConfig(input)['key'] === 'business_end_user',
    apply: (_input, state) => ({
      ...state,
      businessConfigured: true,
      provenance: [...state.provenance, 'navigation_profile:business_end_user'],
    }),
  },
];

/** Ordered and frozen so registry composition cannot depend on import timing. */
export const WORKSPACE_EXPERIENCE_ADAPTERS: readonly WorkspaceExperienceAdapter[] = Object.freeze(
  [...ADAPTERS].sort((left, right) => left.priority - right.priority || left.id.localeCompare(right.id)),
);

function issue(kind: WorkspaceExperienceIssueKind, code: string, path: string): WorkspaceExperienceIssue {
  return { kind, code, path };
}

function inspectConfiguration(input: WorkspaceExperienceInput): WorkspaceExperienceIssue[] {
  const result: WorkspaceExperienceIssue[] = [];
  const rawSettings = input.workspace.settings;
  if (rawSettings !== undefined && rawSettings !== null && (typeof rawSettings !== 'object' || Array.isArray(rawSettings))) {
    result.push(issue('error', 'malformed_settings', '/workspace/settings'));
    return result;
  }

  const knownModes = new Set(['builder', 'operator', 'executive', 'demo', 'portfolio']);
  if (input.workspace.mode && !knownModes.has(input.workspace.mode)) {
    result.push(issue('unknown_adapter', 'unknown_workspace_mode', '/workspace/mode'));
  }

  const rawNavigation = settings(input)['navigation_profile'];
  if (rawNavigation !== undefined && (rawNavigation === null || typeof rawNavigation !== 'object' || Array.isArray(rawNavigation))) {
    result.push(issue('error', 'malformed_navigation_profile', '/workspace/settings/navigation_profile'));
  } else {
    const key = navigationConfig(input)['key'];
    if (key !== undefined && key !== null && typeof key !== 'string') {
      result.push(issue('error', 'malformed_navigation_profile_key', '/workspace/settings/navigation_profile/key'));
    } else if (typeof key === 'string' && key !== 'standard' && key !== 'business_end_user') {
      result.push(issue('unknown_adapter', 'unknown_navigation_profile', '/workspace/settings/navigation_profile/key'));
    }
    const surfaces = navigationConfig(input)['primary_surfaces'];
    if (surfaces !== undefined && (!Array.isArray(surfaces) || surfaces.some((value) => typeof value !== 'string'))) {
      result.push(issue('error', 'malformed_primary_surfaces', '/workspace/settings/navigation_profile/primary_surfaces'));
    }
    const access = navigationConfig(input)['advanced_access'];
    if (access !== undefined && access !== null && typeof access !== 'string') {
      result.push(issue('error', 'malformed_advanced_access', '/workspace/settings/navigation_profile/advanced_access'));
    } else if (typeof access === 'string' && !['admin_only', 'link', 'hidden'].includes(access)) {
      result.push(issue('unknown_adapter', 'unknown_advanced_access', '/workspace/settings/navigation_profile/advanced_access'));
    }
  }

  const appShell = settings(input)['workspace_app_shell'];
  if (appShell !== undefined && appShell !== null && typeof appShell !== 'string') {
    result.push(issue('error', 'malformed_workspace_app_shell', '/workspace/settings/workspace_app_shell'));
  } else if (typeof appShell === 'string' && appShell !== 'immersive' && appShell !== 'standard') {
    result.push(issue('unknown_adapter', 'unknown_workspace_app_shell', '/workspace/settings/workspace_app_shell'));
  }

  const rawMission = settings(input)['mission_room'];
  if (rawMission !== undefined && rawMission !== null && (typeof rawMission !== 'object' || Array.isArray(rawMission))) {
    result.push(issue('error', 'malformed_mission_room', '/workspace/settings/mission_room'));
  } else {
    const profile = missionConfig(input)['profile'];
    if (profile !== undefined && profile !== null && typeof profile !== 'string') {
      result.push(issue('error', 'malformed_mission_room_profile', '/workspace/settings/mission_room/profile'));
    } else if (
      typeof profile === 'string'
      && !['sentinel_government_v1', 'government_mission_room', 'octocity_institutional_v1'].includes(profile)
    ) {
      result.push(issue('unknown_adapter', 'unknown_mission_room_profile', '/workspace/settings/mission_room/profile'));
    }
    const navigation = missionConfig(input)['navigation'];
    if (navigation !== undefined && (!Array.isArray(navigation) || navigation.some((item) => !stringValue(record(item)['key'])))) {
      result.push(issue('error', 'malformed_mission_navigation', '/workspace/settings/mission_room/navigation'));
    }
  }

  return result.sort((left, right) => left.path.localeCompare(right.path) || left.code.localeCompare(right.code));
}

function applyRegistry(input: WorkspaceExperienceInput): { state: ExperienceAdapterState; ids: string[] } {
  let state: ExperienceAdapterState = {
    businessConfigured: false,
    portfolio: false,
    workspaceAppShell: null,
    missionRoom: null,
    provenance: ['base:agentium_standard'],
  };
  const ids: string[] = [];
  for (const adapter of WORKSPACE_EXPERIENCE_ADAPTERS) {
    if (!adapter.matches(input)) continue;
    ids.push(adapter.id);
    state = adapter.apply(input, state);
  }
  return { state, ids };
}

function resolveRoute(
  input: WorkspaceExperienceInput,
  businessActive: boolean,
  owner: WorkspaceExperienceRouteResolution['redirectOwner'],
): WorkspaceExperienceRouteResolution {
  const requestedRoute = pathOnly(input.scenario.requestedRoute);
  let resolvedRoute = requestedRoute;
  let semanticQueryKeys: string[] = [];
  let workspaceTargetMatchesCurrent: boolean | null = null;
  let semanticTargetPreserved: boolean | null = null;
  let redirectReason: WorkspaceExperienceRouteResolution['redirectReason'] = 'none';

  if (businessActive && !isBusinessAllowedPath(input, requestedRoute)) {
    if (requestedRoute === '/knowledge' && businessSurfaceEnabled(input, 'knowledge-capture')) {
      resolvedRoute = '/knowledge/capture';
      redirectReason = 'business_knowledge_compatibility';
    } else if (
      /^\/systems\/[^/]+\/capture$/.test(requestedRoute)
      && businessSurfaceEnabled(input, 'knowledge-capture')
    ) {
      resolvedRoute = '/knowledge/capture';
      semanticQueryKeys = ['systemId'];
      semanticTargetPreserved = true;
      redirectReason = 'business_system_capture_compatibility';
    } else {
      resolvedRoute = configuredBusinessRoute(input);
      redirectReason = 'business_profile_disallowed';
    }
  } else if (input.workspace.mode === 'demo' && requestedRoute === '/hypervisor') {
    const configured = absoluteRoute(settings(input)['default_route']);
    const target = configured || '/hypervisor/mission-room/cockpit';
    if (pathOnly(target) !== '/' && pathOnly(target) !== '/hypervisor') {
      resolvedRoute = pathOnly(target);
      redirectReason = 'workspace_default_route';
    }
  } else if (requestedRoute === '/workspace' && input.workspace.slug) {
    resolvedRoute = `/workspace/${encodeURIComponent(input.workspace.slug)}/settings`;
    workspaceTargetMatchesCurrent = true;
    redirectReason = 'workspace_settings_entrypoint';
  }

  return {
    requestedRoute: canonicalRoute(requestedRoute),
    resolvedRoute: canonicalRoute(resolvedRoute),
    semanticQueryKeys,
    workspaceTargetMatchesCurrent,
    semanticTargetPreserved,
    redirectOwner: owner,
    redirectReason,
  };
}

function shellKind(
  input: WorkspaceExperienceInput,
  route: string,
  businessActive: boolean,
  workspaceAppShell: string | null,
): WorkspaceExperienceShellKind {
  if (/^\/workspace\/[^/]+\/chat$/.test(route)) return 'workspace_focus';
  if (
    input.workspace.mode === 'demo'
    && route.startsWith('/hypervisor/mission-room')
    && workspaceAppShell === 'immersive'
  ) return 'workspace_app_immersive';
  if (businessActive) return 'business';
  return 'agentium_standard';
}

function chromeFor(kind: WorkspaceExperienceShellKind, route: string): WorkspaceExperienceChrome {
  const missionRail = route.startsWith('/hypervisor/mission-room');
  if (kind === 'agentium_standard') return { ...STANDARD_CHROME, missionRail };
  if (kind === 'business') {
    return {
      titleBar: false,
      sideRail: false,
      objectIndex: false,
      commandBar: false,
      commandPalette: false,
      businessHeader: true,
      missionRail: false,
    };
  }
  return {
    titleBar: false,
    sideRail: false,
    objectIndex: false,
    commandBar: false,
    commandPalette: true,
    businessHeader: false,
    missionRail,
  };
}

function cockpitVerbsFor(input: WorkspaceExperienceInput, kind: WorkspaceExperienceShellKind): string[] {
  if (kind !== 'agentium_standard') return [];
  return input.workspace.mode === 'builder' ? [...BUILDER_COCKPIT_VERBS] : [...FULL_COCKPIT_VERBS];
}

function homeRouteFor(input: WorkspaceExperienceInput, businessActive: boolean): string {
  if (businessActive) return configuredBusinessRoute(input);
  if (input.workspace.mode === 'demo') {
    return absoluteRoute(settings(input)['default_route']) || '/hypervisor/mission-room/cockpit';
  }
  return '/hypervisor';
}

function project(
  input: WorkspaceExperienceInput,
  state: ExperienceAdapterState,
  owner: WorkspaceExperienceRouteResolution['redirectOwner'],
) {
  const admin = isAdminScenario(input.scenario);
  const preview = Boolean(input.scenario.businessPreview);
  const businessActive = state.businessConfigured && (!admin || preview);
  const routeResolution = resolveRoute(input, businessActive, owner);
  const kind = shellKind(input, routeResolution.resolvedRoute, businessActive, state.workspaceAppShell);
  const cockpitVerbs = cockpitVerbsFor(input, kind);
  const primarySurfaceIds = businessActive ? entitledBusinessSurfaces(input) : [...cockpitVerbs];
  const workspaceAppConfigured = Boolean(state.workspaceAppShell || state.missionRoom);
  const immersiveRouteScope = state.workspaceAppShell === 'immersive' ? '/hypervisor/mission-room/**' : null;
  return {
    workspaceSlug: input.workspace.slug,
    scenarioKey: workspaceExperienceScenarioKey(input.scenario),
    shellKind: kind,
    homeRoute: canonicalRoute(pathOnly(homeRouteFor(input, businessActive))),
    primarySurfaceIds,
    advancedAccess: advancedAccess(input),
    chrome: chromeFor(kind, routeResolution.resolvedRoute),
    workspaceApp: {
      configured: workspaceAppConfigured,
      shell: state.workspaceAppShell,
      profile: state.missionRoom?.profile || null,
      defaultView: stringValue(settings(input)['workspace_app_default_view'])
        || missionValue(input, 'default_view'),
      immersiveRouteScope,
    },
    immersiveRouteScope,
    cockpitVerbs,
    routeResolution,
    business: {
      configured: state.businessConfigured,
      active: businessActive,
      admin,
      preview,
      declaredPrimarySurfaceIds: declaredBusinessSurfaces(input),
    },
    missionRoom: state.missionRoom ? cloneMissionRoom(state.missionRoom) : null,
  };
}

function cloneMissionRoom(value: WorkspaceExperienceMissionRoomProjection): WorkspaceExperienceMissionRoomProjection {
  return { ...value, navigationKeys: [...value.navigationKeys] };
}

/** New declarative candidate. Its output is deliberately not consumed by Angular. */
export function resolveWorkspaceExperienceV2(input: WorkspaceExperienceInput): WorkspaceExperienceV2 {
  if (workspaceAppPlatformEnabled(input)) {
    return resolveAuthoritativeWorkspaceExperience(input);
  }
  const { state, ids } = applyRegistry(input);
  return {
    schemaVersion: WORKSPACE_EXPERIENCE_SCHEMA_VERSION,
    resolverVersion: WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
    registryEntryIds: ids,
    ...project(input, state, 'workspace_experience_v2'),
    issues: inspectConfiguration(input),
    provenance: [...state.provenance],
  };
}

/**
 * Independent compatibility projection of the currently rendered behavior.
 * It intentionally does not call the adapter registry.
 */
export function resolveLegacyWorkspaceExperience(
  input: WorkspaceExperienceInput,
  observation?: MissionNavigationObservation,
): LegacyWorkspaceExperience {
  const config = settings(input);
  const navigation = navigationConfig(input);
  const mission = missionConfig(input);

  // NavigationProfileService anchors. Keep this calculation independent from
  // the V2 registry and its policy helpers: the shadow comparator needs two
  // genuinely separate implementations in order to detect candidate drift.
  const businessConfigured = navigation['key'] === 'business_end_user';
  const role = stringValue(input.scenario.role)?.toLowerCase() || '';
  const roleTemplate = stringValue(input.scenario.roleTemplate)?.toLowerCase() || '';
  const admin = role === 'owner'
    || role === 'admin'
    || roleTemplate === 'workspace_owner'
    || roleTemplate === 'workspace_admin';
  const preview = Boolean(input.scenario.businessPreview);
  const businessActive = businessConfigured && (!admin || preview);
  const configuredDefault = absoluteRoute(navigation['default_route']);
  const legacyBusinessPathAllowed = (value: string): boolean => {
    const path = pathOnly(value);
    return path === '/chat'
      || path === '/client360'
      || path.startsWith('/client360/')
      || path === '/knowledge/capture'
      || path === '/knowledge/interventions'
      || path === '/account'
      || path.startsWith('/account/');
  };
  const businessDefaultRoute = configuredDefault && legacyBusinessPathAllowed(configuredDefault)
    ? pathOnly(configuredDefault)
    : '/chat';
  const rawDeclaredSurfaces = navigation['primary_surfaces'];
  const declaredPrimarySurfaceIds = Array.isArray(rawDeclaredSurfaces) && rawDeclaredSurfaces.length
    ? rawDeclaredSurfaces.filter((item): item is string =>
      typeof item === 'string' && item.trim().length > 0).map((item) => item.trim())
    : [...LEGACY_BUSINESS_HEADER_SURFACE_IDS];
  const rawAdvancedAccess = navigation['advanced_access'];
  const legacyAdvancedAccess: WorkspaceExperienceAdvancedAccess =
    rawAdvancedAccess === 'link' || rawAdvancedAccess === 'hidden' || rawAdvancedAccess === 'admin_only'
      ? rawAdvancedAccess
      : 'admin_only';

  // NavigationResolverService anchors, including its exact precedence.
  const requestedPath = pathOnly(input.scenario.requestedRoute);
  let resolvedPath = requestedPath;
  let redirectReason: WorkspaceExperienceRouteResolution['redirectReason'] = 'none';
  let semanticQueryKeys: string[] = [];
  let workspaceTargetMatchesCurrent: boolean | null = null;
  let semanticTargetPreserved: boolean | null = null;
  if (businessActive && !legacyBusinessPathAllowed(requestedPath)) {
    if (requestedPath === '/knowledge') {
      resolvedPath = '/knowledge/capture';
      redirectReason = 'business_knowledge_compatibility';
    } else if (/^\/systems\/[^/]+\/capture$/.test(requestedPath)) {
      resolvedPath = '/knowledge/capture';
      semanticQueryKeys = ['systemId'];
      semanticTargetPreserved = true;
      redirectReason = 'business_system_capture_compatibility';
    } else {
      resolvedPath = businessDefaultRoute;
      redirectReason = 'business_profile_disallowed';
    }
  } else if (input.workspace.mode === 'demo' && requestedPath === '/hypervisor') {
    const demoTarget = absoluteRoute(config['default_route']) || '/hypervisor/mission-room/cockpit';
    if (pathOnly(demoTarget) !== '/' && pathOnly(demoTarget) !== '/hypervisor') {
      resolvedPath = pathOnly(demoTarget);
      redirectReason = 'workspace_default_route';
    }
  } else if (requestedPath === '/workspace' && input.workspace.slug) {
    resolvedPath = `/workspace/${encodeURIComponent(input.workspace.slug)}/settings`;
    workspaceTargetMatchesCurrent = true;
    redirectReason = 'workspace_settings_entrypoint';
  }
  const routeResolution: WorkspaceExperienceRouteResolution = {
    requestedRoute: canonicalRoute(requestedPath),
    resolvedRoute: canonicalRoute(resolvedPath),
    semanticQueryKeys,
    workspaceTargetMatchesCurrent,
    semanticTargetPreserved,
    redirectOwner: 'legacy_navigation_resolver',
    redirectReason,
  };

  // MissionRoomComponent/backend navigation payload anchors. The backend owns
  // Systems binding; this projection retains only profile/config/navigation.
  const explicitOctocity = mission['profile'] === 'octocity_institutional_v1'
    || config['demo_profile'] === 'octocity_mission_room';
  const government = (
    mission['profile'] === 'sentinel_government_v1'
    || mission['profile'] === 'government_mission_room'
    || config['demo_profile'] === 'government_mission_room'
  ) && !explicitOctocity;
  const legacyMissionProfile = explicitOctocity
    ? 'octocity_institutional_v1'
    : government
      ? 'sentinel_government_v1'
      : null;
  let missionRoom: WorkspaceExperienceMissionRoomProjection | null = null;
  if (legacyMissionProfile) {
    const octocity = legacyMissionProfile === 'octocity_institutional_v1';
    const rawMissionBrand = mission['brand'];
    const rawSettingsBrand = config['workspace_app_brand'];
    const apiBrand = isPlainObject(rawMissionBrand)
      ? rawMissionBrand
      : isPlainObject(rawSettingsBrand)
        ? rawSettingsBrand
        : {};
    const renderedBrand = Object.keys(apiBrand).length > 0
      ? apiBrand
      : isPlainObject(rawSettingsBrand)
        ? rawSettingsBrand
        : octocity
          ? { label: 'Octocity Mission Room', style: 'agentium' }
          : {};
    // mission_room.navigation() currently falls back to SENTINEL-CI for the
    // API app label; MissionRoomComponent then gives a non-empty brand object
    // precedence over that app label.
    const legacyAppLabel = stringValue(config['workspace_app_label'])
      || stringValue(apiBrand['label'])
      || 'SENTINEL-CI';
    const rawNavigation = mission['navigation'];
    const navigationKeys = Array.isArray(rawNavigation)
      ? LEGACY_MISSION_ROOM_FALLBACK_KEYS.filter((expectedKey) => rawNavigation.some((item) =>
        stringValue(record(item)['key']) === expectedKey))
      : [...LEGACY_MISSION_ROOM_FALLBACK_KEYS];
    missionRoom = {
      profile: legacyMissionProfile,
      label: stringValue(renderedBrand['label']) || legacyAppLabel || 'SENTINEL-CI',
      assistantLabel: stringValue(mission['assistant_label'])
        || stringValue(mission['label'])
        || (octocity ? 'OCTAVE' : 'AYA'),
      assistantProfile: stringValue(config['assistant_profile_default'])
        || (octocity ? 'octave_executive' : 'vigie_executive'),
      brandStyle: stringValue(renderedBrand['style']) || 'sentinel',
      navigationKeys,
    };
  }

  let observationState: LegacyWorkspaceExperience['missionNavigationObservation'] = missionRoom ? 'missing' : 'not_required';
  if (observation && missionRoom) {
    if (!isValidMissionNavigationObservation(observation)) {
      observationState = 'error';
    } else {
      missionRoom = applyMissionObservation(input, missionRoom, observation);
      observationState = 'observed';
    }
  }

  // ShellComponent and SideRailComponent anchors, evaluated on the final route.
  const workspaceAppShell = config['workspace_app_shell'] === 'immersive' ? 'immersive' : null;
  const focusShell = /^\/workspace\/[^/]+\/chat$/.test(routeResolution.resolvedRoute);
  const missionImmersive = input.workspace.mode === 'demo'
    && routeResolution.resolvedRoute.startsWith('/hypervisor/mission-room')
    && workspaceAppShell === 'immersive';
  const legacyShellKind: WorkspaceExperienceShellKind = focusShell
    ? 'workspace_focus'
    : missionImmersive
      ? 'workspace_app_immersive'
      : businessActive
        ? 'business'
        : 'agentium_standard';
  const legacyCockpitVerbs = legacyShellKind === 'agentium_standard'
    ? input.workspace.mode === 'builder'
      ? [...LEGACY_BUILDER_SIDE_RAIL_VERBS]
      : [...LEGACY_FULL_SIDE_RAIL_VERBS]
    : [];
  const missionRail = routeResolution.resolvedRoute.startsWith('/hypervisor/mission-room');
  const legacyChrome: WorkspaceExperienceChrome = legacyShellKind === 'agentium_standard'
    ? {
      titleBar: true,
      sideRail: true,
      objectIndex: true,
      commandBar: true,
      commandPalette: true,
      businessHeader: false,
      missionRail,
    }
    : legacyShellKind === 'business'
      ? {
        titleBar: false,
        sideRail: false,
        objectIndex: false,
        commandBar: false,
        commandPalette: false,
        businessHeader: true,
        missionRail: false,
      }
      : {
        titleBar: false,
        sideRail: false,
        objectIndex: false,
        commandBar: false,
        commandPalette: true,
        businessHeader: false,
        missionRail,
      };
  const immersiveRouteScope = workspaceAppShell === 'immersive'
    ? '/hypervisor/mission-room/**'
    : null;
  const legacyHomeRoute = businessActive
    ? businessDefaultRoute
    : input.workspace.mode === 'demo'
      ? absoluteRoute(config['default_route']) || '/hypervisor/mission-room/cockpit'
      : '/hypervisor';

  return {
    schemaVersion: 1,
    resolverVersion: 'legacy-navigation-2026-07',
    registryEntryIds: [],
    workspaceSlug: input.workspace.slug,
    scenarioKey: workspaceExperienceScenarioKey(input.scenario),
    shellKind: legacyShellKind,
    homeRoute: canonicalRoute(pathOnly(legacyHomeRoute)),
    primarySurfaceIds: legacyShellKind === 'business'
      ? [...LEGACY_BUSINESS_HEADER_SURFACE_IDS]
      : [...legacyCockpitVerbs],
    advancedAccess: legacyAdvancedAccess,
    chrome: legacyChrome,
    workspaceApp: {
      configured: Boolean(workspaceAppShell || missionRoom),
      shell: workspaceAppShell,
      profile: missionRoom?.profile || null,
      defaultView: stringValue(config['workspace_app_default_view'])
        || stringValue(mission['default_view']),
      immersiveRouteScope,
    },
    immersiveRouteScope,
    cockpitVerbs: legacyCockpitVerbs,
    routeResolution,
    business: {
      configured: businessConfigured,
      active: businessActive,
      admin,
      preview,
      declaredPrimarySurfaceIds,
    },
    missionRoom: missionRoom
      ? { ...missionRoom, navigationKeys: [...missionRoom.navigationKeys] }
      : null,
    // Legacy accepts unknown settings opportunistically. Candidate validation
    // remains fail-closed and is reported separately by the comparator.
    issues: [],
    provenance: ['legacy:rendered_behavior', 'legacy:independent_ui_oracle'],
    missionNavigationObservation: observationState,
  };
}

function applyMissionObservation(
  input: WorkspaceExperienceInput,
  fallback: WorkspaceExperienceMissionRoomProjection,
  observation: MissionNavigationObservation,
): WorkspaceExperienceMissionRoomProjection {
  const app = record(observation.app);
  const brand = record(app['brand']);
  const brandHasFields = observation.brandHasFields ?? Object.keys(brand).length > 0;
  const rawSettingsBrand = settings(input)['workspace_app_brand'];
  const renderedBrand = brandHasFields
    ? brand
    : isPlainObject(rawSettingsBrand)
      ? rawSettingsBrand
      : fallback.profile === 'octocity_institutional_v1'
        ? { label: 'Octocity Mission Room', style: 'agentium' }
        : {};
  const observedKeys = Array.isArray(observation.items)
    ? observation.items
      .map((item) => stringValue(record(item)['key']))
      // Preserve API order, duplicates and unknown non-empty keys. Filtering to
      // the frontend's expected seven keys would hide authoritative drift.
      .filter((key): key is string => Boolean(key))
    : fallback.navigationKeys;
  return {
    profile: stringValue(app['profile']) || fallback.profile,
    label: stringValue(renderedBrand['label'])
      || stringValue(app['label'])
      || 'SENTINEL-CI',
    assistantLabel: stringValue(app['assistant_label']) || fallback.assistantLabel,
    assistantProfile: stringValue(app['assistant_profile']) || fallback.assistantProfile,
    // A non-empty API brand is authoritative in MissionRoomComponent. If it
    // omits style, the rendered UI is Sentinel; it must not inherit the
    // workspace-settings fallback and accidentally make Octocity look equal.
    brandStyle: stringValue(renderedBrand['style']) || 'sentinel',
    navigationKeys: [...observedKeys],
  };
}

function isValidMissionNavigationObservation(observation: MissionNavigationObservation): boolean {
  if (observation.error !== undefined || !isPlainObject(observation.app) || !Array.isArray(observation.items)) {
    return false;
  }
  const app = observation.app;
  for (const key of ['label', 'assistant_label', 'shell', 'default_route', 'default_view'] as const) {
    if (!stringValue(app[key])) return false;
  }
  // Sentinel intentionally exposes an empty profile, but the field itself is
  // part of the runtime contract and must be present with a string value.
  if (typeof app.profile !== 'string' || !isPlainObject(app.brand)) return false;
  if (
    observation.brandHasFields !== undefined
    && typeof observation.brandHasFields !== 'boolean'
  ) return false;
  const brand = app.brand;
  if (
    observation.brandHasFields === false
    && Object.keys(brand).length > 0
  ) return false;
  for (const key of ['label', 'style'] as const) {
    if (Object.prototype.hasOwnProperty.call(brand, key) && typeof brand[key] !== 'string') {
      return false;
    }
  }
  return observation.items.every((item) =>
    isPlainObject(item) && Boolean(stringValue(record(item)['key'])));
}

/** Route-safe scenario identity; it contains no query values or dynamic IDs. */
export function workspaceExperienceScenarioKey(scenario: WorkspaceExperienceScenario): string {
  const role = stringValue(scenario.role)?.toLowerCase() || 'member';
  const template = stringValue(scenario.roleTemplate)?.toLowerCase() || 'none';
  return `role=${role};template=${template};preview=${scenario.businessPreview ? '1' : '0'};route=${canonicalRoute(pathOnly(scenario.requestedRoute))}`;
}

function canonicalRoute(route: string): string {
  return route
    .replace(/^\/workspace\/[^/]+/, '/workspace/:workspaceSlug')
    .replace(/^\/systems\/[^/]+/, '/systems/:systemId')
    .replace(/(\/hypervisor\/mission-room\/meetings\/)[^/]+/, '$1:eventId');
}

export interface WorkspaceExperienceDiff {
  path: string;
  code: 'value_mismatch' | 'missing_legacy' | 'missing_candidate';
}

interface RawWorkspaceExperienceDiff extends WorkspaceExperienceDiff {
  legacy: unknown;
  candidate: unknown;
}

export interface WorkspaceExperienceExplanation {
  id: string;
  workspaceSlug: string;
  scenarioKey: string;
  fingerprint: string;
  justification: string;
  owner: string;
  expiresAt: string;
}

export interface WorkspaceExperienceComparison {
  schemaVersion: typeof WORKSPACE_EXPERIENCE_SCHEMA_VERSION;
  resolverVersion: typeof WORKSPACE_EXPERIENCE_RESOLVER_VERSION;
  workspaceSlug: string;
  scenarioKey: string;
  fingerprint: string;
  status: 'match' | 'explained_divergence' | 'unexplained_divergence' | 'error';
  diffs: WorkspaceExperienceDiff[];
  explanationId: string | null;
  explanationState: 'not_needed' | 'missing' | 'valid' | 'expired' | 'invalid';
  legacyObservation: LegacyWorkspaceExperience['missionNavigationObservation'];
  candidateIssues: WorkspaceExperienceIssue[];
}

export interface CompareWorkspaceExperienceOptions {
  legacy?: LegacyWorkspaceExperience;
  candidate?: WorkspaceExperienceV2;
  /**
   * Decision actually returned by NavigationResolverService. `null` means the
   * runtime resolver returned no redirect. Supplying this prevents the shadow
   * comparison from proving route parity with two implementations of the same
   * pure helper.
   */
  observedLegacyRouteDecision?: ObservedLegacyNavigationDecision | null;
  explanations?: readonly WorkspaceExperienceExplanation[];
  now?: string | Date;
}

export interface ObservedLegacyNavigationDecision {
  requestedRoute: string;
  resolvedRoute: string;
  reason: WorkspaceExperienceRouteResolution['redirectReason'];
  /** Optional presence-only keys captured before privacy-safe route redaction. */
  semanticQueryKeys?: readonly string[];
  /** Presence-only equality proof captured before route canonicalization. */
  workspaceTargetMatchesCurrent?: boolean | null;
  /** Presence-only equality proof captured before query redaction. */
  semanticTargetPreserved?: boolean | null;
}

export function applyObservedLegacyRouteDecision(
  legacy: LegacyWorkspaceExperience,
  input: WorkspaceExperienceInput,
  decision: ObservedLegacyNavigationDecision | null,
): LegacyWorkspaceExperience {
  const requestedRoute = pathOnly(decision?.requestedRoute || input.scenario.requestedRoute);
  const resolvedRoute = canonicalRoute(pathOnly(decision?.resolvedRoute || requestedRoute));
  const appShell = settings(input)['workspace_app_shell'] === 'immersive' ? 'immersive' : null;
  const focusShell = /^\/workspace\/[^/]+\/chat$/.test(resolvedRoute);
  const missionImmersive = input.workspace.mode === 'demo'
    && resolvedRoute.startsWith('/hypervisor/mission-room')
    && appShell === 'immersive';
  const shellKind: WorkspaceExperienceShellKind = focusShell
    ? 'workspace_focus'
    : missionImmersive
      ? 'workspace_app_immersive'
      : legacy.business.active
        ? 'business'
        : 'agentium_standard';
  const cockpitVerbs = shellKind === 'agentium_standard'
    ? input.workspace.mode === 'builder'
      ? [...LEGACY_BUILDER_SIDE_RAIL_VERBS]
      : [...LEGACY_FULL_SIDE_RAIL_VERBS]
    : [];
  const missionRail = resolvedRoute.startsWith('/hypervisor/mission-room');
  const chrome: WorkspaceExperienceChrome = shellKind === 'agentium_standard'
    ? {
      titleBar: true,
      sideRail: true,
      objectIndex: true,
      commandBar: true,
      commandPalette: true,
      businessHeader: false,
      missionRail,
    }
    : shellKind === 'business'
      ? {
        titleBar: false,
        sideRail: false,
        objectIndex: false,
        commandBar: false,
        commandPalette: false,
        businessHeader: true,
        missionRail: false,
      }
      : {
        titleBar: false,
        sideRail: false,
        objectIndex: false,
        commandBar: false,
        commandPalette: true,
        businessHeader: false,
        missionRail,
      };
  return {
    ...legacy,
    shellKind,
    primarySurfaceIds: shellKind === 'business'
      ? [...LEGACY_BUSINESS_HEADER_SURFACE_IDS]
      : [...cockpitVerbs],
    chrome,
    cockpitVerbs,
    routeResolution: {
      requestedRoute: canonicalRoute(requestedRoute),
      resolvedRoute,
      semanticQueryKeys: decision
        ? normalizeSemanticQueryKeys(
          decision.semanticQueryKeys === undefined
            ? semanticQueryKeysFromRoute(decision.resolvedRoute)
            : decision.semanticQueryKeys,
        )
        : [],
      workspaceTargetMatchesCurrent: decision
        ? decision.workspaceTargetMatchesCurrent
          ?? observedWorkspaceTargetMatchesCurrent(input.workspace.slug, decision)
        : null,
      semanticTargetPreserved: decision
        ? decision.semanticTargetPreserved
          ?? observedSemanticTargetPreserved(decision)
        : null,
      redirectOwner: 'legacy_navigation_resolver',
      redirectReason: decision?.reason || 'none',
    },
  };
}

function observedWorkspaceTargetMatchesCurrent(
  workspaceSlug: string,
  decision: ObservedLegacyNavigationDecision,
): boolean | null {
  if (decision.reason !== 'workspace_settings_entrypoint') return null;
  const match = pathOnly(decision.resolvedRoute).match(/^\/workspace\/([^/]+)(?:\/|$)/);
  if (!match?.[1]) return false;
  try {
    return decodeURIComponent(match[1]) === workspaceSlug;
  } catch {
    return false;
  }
}

function observedSemanticTargetPreserved(
  decision: ObservedLegacyNavigationDecision,
): boolean | null {
  if (decision.reason !== 'business_system_capture_compatibility') return null;
  const requested = pathOnly(decision.requestedRoute).match(/^\/systems\/([^/]+)\/capture$/);
  if (!requested?.[1]) return false;
  const queryStart = decision.resolvedRoute.indexOf('?');
  if (queryStart < 0) return false;
  const fragmentStart = decision.resolvedRoute.indexOf('#', queryStart + 1);
  const query = decision.resolvedRoute.slice(
    queryStart + 1,
    fragmentStart < 0 ? decision.resolvedRoute.length : fragmentStart,
  );
  let requestedSystemId: string;
  try {
    requestedSystemId = decodeURIComponent(requested[1]);
  } catch {
    requestedSystemId = requested[1];
  }
  return new URLSearchParams(query).get('systemId') === requestedSystemId;
}

function semanticQueryKeysFromRoute(route: string): string[] {
  const query = route.includes('?') ? route.slice(route.indexOf('?') + 1).split('#')[0] : '';
  if (!query) return [];
  const keys: string[] = [];
  // Closed allowlist: capture semantic presence without retaining a value or
  // arbitrary user-controlled query name. Prefer forEach — DOM lib omits keys().
  new URLSearchParams(query).forEach((_value, key) => {
    if (key === 'systemId') keys.push(key);
  });
  return normalizeSemanticQueryKeys(keys);
}

function normalizeSemanticQueryKeys(keys: readonly string[]): string[] {
  return [...new Set(keys.filter((key) => key === 'systemId'))].sort();
}

function comparableProjection(value: WorkspaceExperienceV2 | LegacyWorkspaceExperience): unknown {
  return {
    shellKind: value.shellKind,
    homeRoute: pathOnly(value.homeRoute),
    primarySurfaceIds: value.primarySurfaceIds,
    advancedAccess: value.advancedAccess,
    chrome: value.chrome,
    workspaceApp: value.workspaceApp,
    immersiveRouteScope: value.immersiveRouteScope,
    cockpitVerbs: value.cockpitVerbs,
    routeResolution: {
      requestedRoute: canonicalRoute(pathOnly(value.routeResolution.requestedRoute)),
      resolvedRoute: canonicalRoute(pathOnly(value.routeResolution.resolvedRoute)),
      semanticQueryKeys: value.routeResolution.semanticQueryKeys,
      workspaceTargetMatchesCurrent: value.routeResolution.workspaceTargetMatchesCurrent,
      semanticTargetPreserved: value.routeResolution.semanticTargetPreserved,
      redirectReason: value.routeResolution.redirectReason,
    },
    business: value.business,
    missionRoom: value.missionRoom,
  };
}

const MISSING_VALUE = Object.freeze({ missing: true });

function collectDiffs(legacy: unknown, candidate: unknown, path = ''): RawWorkspaceExperienceDiff[] {
  if (Object.is(legacy, candidate)) return [];
  if (Array.isArray(legacy) && Array.isArray(candidate)) {
    const diffs: RawWorkspaceExperienceDiff[] = [];
    for (let index = 0; index < Math.max(legacy.length, candidate.length); index += 1) {
      const nextPath = `${path}/${index}`;
      if (index >= legacy.length) diffs.push({ path: nextPath, code: 'missing_legacy', legacy: MISSING_VALUE, candidate: candidate[index] });
      else if (index >= candidate.length) diffs.push({ path: nextPath, code: 'missing_candidate', legacy: legacy[index], candidate: MISSING_VALUE });
      else diffs.push(...collectDiffs(legacy[index], candidate[index], nextPath));
    }
    return diffs;
  }
  if (isPlainObject(legacy) && isPlainObject(candidate)) {
    const diffs: RawWorkspaceExperienceDiff[] = [];
    const keys = [...new Set([...Object.keys(legacy), ...Object.keys(candidate)])].sort();
    for (const key of keys) {
      const escaped = key.replace(/~/g, '~0').replace(/\//g, '~1');
      const nextPath = `${path}/${escaped}`;
      if (!(key in legacy)) diffs.push({ path: nextPath, code: 'missing_legacy', legacy: MISSING_VALUE, candidate: candidate[key] });
      else if (!(key in candidate)) diffs.push({ path: nextPath, code: 'missing_candidate', legacy: legacy[key], candidate: MISSING_VALUE });
      else diffs.push(...collectDiffs(legacy[key], candidate[key], nextPath));
    }
    return diffs;
  }
  return [{ path: path || '/', code: 'value_mismatch', legacy, candidate }];
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value as Record<string, unknown>).sort().map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(',')}}`;
}

/** Exact, deterministic fingerprint (FNV-1a 64 over canonical UTF-8 JSON). */
export function workspaceExperienceFingerprint(value: unknown): string {
  const bytes = new TextEncoder().encode(stableJson(value));
  let hash = 0xcbf29ce484222325n;
  for (const byte of bytes) {
    hash ^= BigInt(byte);
    hash = BigInt.asUintN(64, hash * 0x100000001b3n);
  }
  return `wxp2-fnv1a64-${hash.toString(16).padStart(16, '0')}`;
}

export function compareWorkspaceExperiences(
  input: WorkspaceExperienceInput,
  options: CompareWorkspaceExperienceOptions = {},
): WorkspaceExperienceComparison {
  let legacy = options.legacy || resolveLegacyWorkspaceExperience(input);
  if (Object.prototype.hasOwnProperty.call(options, 'observedLegacyRouteDecision')) {
    legacy = applyObservedLegacyRouteDecision(legacy, input, options.observedLegacyRouteDecision ?? null);
  }
  const candidate = options.candidate || resolveWorkspaceExperienceV2(input);
  const scenarioKey = workspaceExperienceScenarioKey(input.scenario);
  const rawDiffs = collectDiffs(comparableProjection(legacy), comparableProjection(candidate));
  const diffs: WorkspaceExperienceDiff[] = rawDiffs.map(({ path, code }) => ({ path, code }));
  const fingerprint = workspaceExperienceFingerprint({
    schemaVersion: WORKSPACE_EXPERIENCE_SCHEMA_VERSION,
    resolverVersion: WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
    workspaceSlug: input.workspace.slug,
    scenarioKey,
    diffs: rawDiffs,
  });
  const blockingIssue = candidate.issues.some((item) => item.kind === 'error' || item.kind === 'unknown_adapter');
  const now = options.now instanceof Date ? options.now : new Date(options.now || Date.now());
  const exactMatches = (options.explanations || []).filter((item) =>
    item.workspaceSlug === input.workspace.slug
    && item.scenarioKey === scenarioKey
    && item.fingerprint === fingerprint,
  );
  const exact = exactMatches.length === 1 ? exactMatches[0] : null;
  const hasGovernance = Boolean(
    exact
    && stringValue(exact.id)
    && stringValue(exact.owner)
    && stringValue(exact.justification),
  );
  const parsedExpiry = exact ? Date.parse(exact.expiresAt) : Number.NaN;
  const validExpiry = Number.isFinite(parsedExpiry);
  const validExplanation = Boolean(hasGovernance && validExpiry && new Date(parsedExpiry) > now);
  let explanationState: WorkspaceExperienceComparison['explanationState'];
  if (exactMatches.length > 1) explanationState = 'invalid';
  else if (!rawDiffs.length) explanationState = 'not_needed';
  else if (!exactMatches.length) explanationState = 'missing';
  else if (!hasGovernance || !validExpiry) explanationState = 'invalid';
  else if (new Date(parsedExpiry) <= now) explanationState = 'expired';
  else explanationState = 'valid';

  let status: WorkspaceExperienceComparison['status'];
  if (blockingIssue || legacy.missionNavigationObservation === 'error') status = 'error';
  else if (!diffs.length) status = 'match';
  else if (validExplanation) status = 'explained_divergence';
  else status = 'unexplained_divergence';

  return {
    schemaVersion: WORKSPACE_EXPERIENCE_SCHEMA_VERSION,
    resolverVersion: WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
    workspaceSlug: input.workspace.slug,
    scenarioKey,
    fingerprint,
    status,
    diffs,
    explanationId: validExplanation ? exact!.id.trim() : null,
    explanationState,
    legacyObservation: legacy.missionNavigationObservation,
    candidateIssues: candidate.issues.map((item) => ({ ...item })),
  };
}

export function compareWorkspaceExperienceWithMissionNavigation(
  input: WorkspaceExperienceInput,
  observation: MissionNavigationObservation,
  options: Omit<CompareWorkspaceExperienceOptions, 'legacy'> = {},
): WorkspaceExperienceComparison {
  return compareWorkspaceExperiences(input, {
    ...options,
    legacy: resolveLegacyWorkspaceExperience(input, observation),
  });
}

export interface WorkspaceExperienceEvidence {
  evidenceSchemaVersion: typeof WORKSPACE_EXPERIENCE_EVIDENCE_SCHEMA_VERSION;
  resolverVersion: typeof WORKSPACE_EXPERIENCE_RESOLVER_VERSION;
  workspaceSlug: string;
  scenarioKey: string;
  workspaceEpoch: number;
  currentWorkspaceEpoch: number;
  comparison?: WorkspaceExperienceComparison;
  errorCode?: string;
}

export function createWorkspaceExperienceEvidence(
  input: WorkspaceExperienceInput,
  comparison: WorkspaceExperienceComparison,
  workspaceEpoch = 0,
  currentWorkspaceEpoch = workspaceEpoch,
): WorkspaceExperienceEvidence {
  return {
    evidenceSchemaVersion: WORKSPACE_EXPERIENCE_EVIDENCE_SCHEMA_VERSION,
    resolverVersion: WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
    workspaceSlug: input.workspace.slug,
    scenarioKey: workspaceExperienceScenarioKey(input.scenario),
    workspaceEpoch,
    currentWorkspaceEpoch,
    comparison,
  };
}

export interface WorkspaceExperienceRolloutBlocker {
  code:
    | 'missing_evidence'
    | 'duplicate_evidence'
    | 'invalid_evidence_schema'
    | 'invalid_resolver_version'
    | 'evidence_error'
    | 'comparison_error'
    | 'unknown_adapter'
    | 'unexplained_divergence'
    | 'expired_explanation'
    | 'stale_workspace_epoch'
    | 'missing_mission_navigation_observation';
  workspaceSlug: string;
  scenarioKey: string;
}

export interface WorkspaceExperienceRolloutResult {
  allowed: boolean;
  blockers: WorkspaceExperienceRolloutBlocker[];
}

export interface WorkspaceExperienceCriticalScenario {
  id: string;
  input: WorkspaceExperienceInput;
  requiresMissionNavigationObservation: boolean;
}

export function evaluateWorkspaceExperienceRolloutGate(
  evidence: readonly WorkspaceExperienceEvidence[],
  required: readonly WorkspaceExperienceCriticalScenario[],
): WorkspaceExperienceRolloutResult {
  const blockers: WorkspaceExperienceRolloutBlocker[] = [];
  const requiredKeys = new Map(required.map((scenario) => [
    `${scenario.input.workspace.slug}::${workspaceExperienceScenarioKey(scenario.input.scenario)}`,
    scenario,
  ]));
  const requiredWorkspaceSlugs = new Set(
    required.map((scenario) => scenario.input.workspace.slug),
  );

  for (const [key, scenario] of requiredKeys) {
    const matches = evidence.filter((item) => `${item.workspaceSlug}::${item.scenarioKey}` === key);
    if (!matches.length) {
      blockers.push(gateBlocker('missing_evidence', scenario.input.workspace.slug, workspaceExperienceScenarioKey(scenario.input.scenario)));
      continue;
    }
    if (matches.length > 1) blockers.push(gateBlocker('duplicate_evidence', matches[0].workspaceSlug, matches[0].scenarioKey));
    inspectEvidence(matches[0], scenario.requiresMissionNavigationObservation, blockers);
  }

  // Extra evidence for a critical workspace must also fail closed.
  for (const item of evidence) {
    if (!requiredWorkspaceSlugs.has(item.workspaceSlug)) continue;
    const key = `${item.workspaceSlug}::${item.scenarioKey}`;
    if (!requiredKeys.has(key)) inspectEvidence(item, false, blockers);
  }

  const unique = new Map(blockers.map((item) => [`${item.code}:${item.workspaceSlug}:${item.scenarioKey}`, item]));
  const sorted = [...unique.values()].sort((left, right) =>
    left.workspaceSlug.localeCompare(right.workspaceSlug)
    || left.scenarioKey.localeCompare(right.scenarioKey)
    || left.code.localeCompare(right.code),
  );
  return { allowed: sorted.length === 0, blockers: sorted };
}

function inspectEvidence(
  evidence: WorkspaceExperienceEvidence,
  requiresObservation: boolean,
  blockers: WorkspaceExperienceRolloutBlocker[],
): void {
  if (evidence.evidenceSchemaVersion !== WORKSPACE_EXPERIENCE_EVIDENCE_SCHEMA_VERSION) {
    blockers.push(gateBlocker('invalid_evidence_schema', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (evidence.resolverVersion !== WORKSPACE_EXPERIENCE_RESOLVER_VERSION
    || evidence.comparison?.resolverVersion !== WORKSPACE_EXPERIENCE_RESOLVER_VERSION
    || (evidence.comparison && evidence.comparison.schemaVersion !== WORKSPACE_EXPERIENCE_SCHEMA_VERSION)) {
    blockers.push(gateBlocker('invalid_resolver_version', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (evidence.errorCode || !evidence.comparison) {
    blockers.push(gateBlocker('evidence_error', evidence.workspaceSlug, evidence.scenarioKey));
    return;
  }
  if (
    evidence.comparison.workspaceSlug !== evidence.workspaceSlug
    || evidence.comparison.scenarioKey !== evidence.scenarioKey
  ) {
    blockers.push(gateBlocker('comparison_error', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (evidence.workspaceEpoch !== evidence.currentWorkspaceEpoch) {
    blockers.push(gateBlocker('stale_workspace_epoch', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (evidence.comparison.candidateIssues.some((item) => item.kind === 'unknown_adapter')) {
    blockers.push(gateBlocker('unknown_adapter', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (
    evidence.comparison.status === 'error'
    || (evidence.comparison.status === 'match' && evidence.comparison.diffs.length !== 0)
  ) {
    blockers.push(gateBlocker('comparison_error', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (
    evidence.comparison.status === 'explained_divergence'
    && (
      evidence.comparison.diffs.length === 0
      || evidence.comparison.explanationState !== 'valid'
      || !evidence.comparison.explanationId
    )
  ) {
    blockers.push(gateBlocker('unexplained_divergence', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (evidence.comparison.status === 'unexplained_divergence') {
    blockers.push(gateBlocker('unexplained_divergence', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (evidence.comparison.explanationState === 'expired') {
    blockers.push(gateBlocker('expired_explanation', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (evidence.comparison.explanationState === 'invalid') {
    blockers.push(gateBlocker('unexplained_divergence', evidence.workspaceSlug, evidence.scenarioKey));
  }
  if (requiresObservation && evidence.comparison.legacyObservation !== 'observed') {
    blockers.push(gateBlocker('missing_mission_navigation_observation', evidence.workspaceSlug, evidence.scenarioKey));
  }
}

function gateBlocker(
  code: WorkspaceExperienceRolloutBlocker['code'],
  workspaceSlug: string,
  scenarioKey: string,
): WorkspaceExperienceRolloutBlocker {
  return { code, workspaceSlug, scenarioKey };
}
