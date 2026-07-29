import {
  OCTOCITY_MISSION_ROOM_PROFILE,
  SENTINEL_MISSION_ROOM_PROFILE,
} from './mission-room.presentation';
import type { WorkspaceAppRuntimeProjection } from '@app/core/workspace.service';

export {
  OCTOCITY_MISSION_ROOM_PROFILE,
  SENTINEL_MISSION_ROOM_PROFILE,
} from './mission-room.presentation';

/**
 * Mission Room workspace-extension contract.
 *
 * Keep this descriptor dependency-free: the Agentium shell and resolver may
 * inspect the extension without importing any of its business components.
 * The components remain owned by this feature and are loaded only by the
 * feature-local route table.
 */
export const MISSION_ROOM_EXTENSION = Object.freeze({
  id: 'mission-room',
  routeRoot: '/hypervisor/mission-room',
  defaultRoute: '/hypervisor/mission-room/cockpit',
  apiPrefix: '/api/v1/mission-room',
});

export const GENERIC_MISSION_ROOM_PROVIDER_KIND = 'workspace_objects_v1' as const;
export const GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS = Object.freeze([
  'GET /overview',
  'GET /navigation',
  'GET /cockpit',
  'GET /briefing',
  'GET /timeline',
  'GET /projects',
  'GET /decisions',
  'GET /library',
  'GET /search',
  'GET /map',
  'GET /monitor',
  'GET /news',
  'POST /actions/draft',
] as const);

export interface WorkspaceExtensionContext {
  readonly mode?: string | null;
  readonly settings?: Record<string, unknown> | null;
  readonly workspace_app_runtime?: WorkspaceAppRuntimeProjection | null;
}

export interface MissionRoomExtensionState {
  readonly authority: 'legacy' | 'workspace_app_runtime' | 'fail_closed';
  readonly enabled: boolean;
  readonly profile: string | null;
  readonly label: string | null;
  readonly assistantLabel: string | null;
  readonly assistantProfile: string | null;
  readonly brandStyle: string | null;
  readonly actionPacks: readonly string[];
  readonly providerKind: string | null;
  readonly providerEndpoints: readonly string[];
  readonly genericProvider: boolean;
  /** Profile-owned migration hook; never inferred from the workspace slug. */
  readonly legacyMorningDismissedStorageKey: string | null;
}

const LEGACY_MORNING_DISMISSED_STORAGE_KEYS: Readonly<Record<string, string>> = Object.freeze({
  [SENTINEL_MISSION_ROOM_PROFILE]: 'sentinel-ci-aya-morning-dismissed',
});
const MISSION_ROOM_PROVIDER_APP_IDS = new Set([
  'sentinel.mission-room',
  'octocity.mission-room',
]);

export function missionRoomExtensionState(
  workspace: WorkspaceExtensionContext | null | undefined,
): MissionRoomExtensionState {
  const settings = asRecord(workspace?.settings);
  const features = asRecord(settings['features']);
  if (features['workspace_app_platform_v1'] === true) {
    return authoritativeMissionRoomExtensionState(workspace?.workspace_app_runtime);
  }
  const missionRoom = asRecord(settings['mission_room']);
  const brand = asRecord(missionRoom['brand']);
  const actions = asRecord(settings['actions']);
  const configuredProfile = nonEmptyString(missionRoom['profile']);
  const demoProfile = nonEmptyString(settings['demo_profile']);
  const profile = configuredProfile || (
    demoProfile === 'government_mission_room' ? SENTINEL_MISSION_ROOM_PROFILE : null
  );

  return Object.freeze({
    authority: 'legacy' as const,
    enabled: missionRoom['enabled'] === true,
    profile,
    label: nonEmptyString(brand['label']) || nonEmptyString(settings['workspace_app_label']),
    assistantLabel:
      nonEmptyString(missionRoom['assistant_label']) || nonEmptyString(missionRoom['label']),
    assistantProfile: nonEmptyString(settings['assistant_profile_default']),
    brandStyle: nonEmptyString(brand['style'])
      || nonEmptyString(asRecord(settings['workspace_app_brand'])['style']),
    actionPacks: Object.freeze(stringList(actions['enabled_packs'])),
    providerKind: null,
    providerEndpoints: Object.freeze([] as string[]),
    genericProvider: false,
    legacyMorningDismissedStorageKey:
      (profile && LEGACY_MORNING_DISMISSED_STORAGE_KEYS[profile]) || null,
  });
}

function authoritativeMissionRoomExtensionState(
  runtime: WorkspaceAppRuntimeProjection | null | undefined,
): MissionRoomExtensionState {
  const rawRuntime = asRecord(runtime);
  const experience = asRecord(rawRuntime['experience']);
  const missionRoom = asRecord(experience['mission_room']);
  const actionPacks = stringList(experience['action_packs']);
  const routes = stringList(experience['routes']);
  const profile = nonEmptyString(missionRoom['profile']);
  const assistantProfile = nonEmptyString(missionRoom['assistant_profile']);
  const label = nonEmptyString(missionRoom['label']);
  const assistantLabel = nonEmptyString(missionRoom['assistant_label']);
  const brandStyle = nonEmptyString(missionRoom['brand_style']);
  const navigationKeys = stringList(missionRoom['navigation_keys']);
  const defaultRoute = nonEmptyString(missionRoom['default_route']);
  const providerAppId = nonEmptyString(missionRoom['app_id']);
  const providerVersion = nonEmptyString(missionRoom['version']);
  const providerDigest = nonEmptyString(missionRoom['manifest_digest']);
  const primarySurfaceId = nonEmptyString(missionRoom['primary_surface_id']);
  const providerKind = nonEmptyString(missionRoom['provider_kind']);
  const providerEndpoints = stringList(missionRoom['provider_endpoints']);
  const genericProvider = providerAppId === 'mission-room.extension'
    && providerKind === GENERIC_MISSION_ROOM_PROVIDER_KIND
    && sameStringList(providerEndpoints, GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS);
  const specializedProvider = Boolean(
    providerAppId && MISSION_ROOM_PROVIDER_APP_IDS.has(providerAppId),
  );
  const installations = Array.isArray(rawRuntime['installations'])
    ? rawRuntime['installations'].map(asRecord)
    : [];
  const owner = installations.find((installation) => (
    installation['app_id'] === providerAppId
    && installation['version'] === providerVersion
    && installation['manifest_digest'] === providerDigest
    && installation['primary_surface_id'] === primarySurfaceId
    && installation['default_route'] === defaultRoute
    && stringList(installation['routes']).includes(MISSION_ROOM_EXTENSION.routeRoot)
    && stringList(installation['api_prefixes']).includes(MISSION_ROOM_EXTENSION.apiPrefix)
  ));
  const valid = rawRuntime['mode'] === 'authoritative'
    && rawRuntime['enabled'] === true
    && rawRuntime['valid'] === true
    && experience['shell'] === 'immersive'
    && routes.some((route) => route === MISSION_ROOM_EXTENSION.routeRoot)
    && Boolean(owner)
    && (specializedProvider || genericProvider)
    && Boolean(profile && assistantProfile && label && assistantLabel && brandStyle)
    && navigationKeys.length > 0
    && Boolean(defaultRoute?.startsWith(`${MISSION_ROOM_EXTENSION.routeRoot}/`));
  if (!valid) {
    return Object.freeze({
      authority: 'fail_closed' as const,
      enabled: false,
      profile: null,
      label: null,
      assistantLabel: null,
      assistantProfile: null,
      brandStyle: null,
      actionPacks: Object.freeze([] as string[]),
      providerKind: null,
      providerEndpoints: Object.freeze([] as string[]),
      genericProvider: false,
      legacyMorningDismissedStorageKey: null,
    });
  }
  return Object.freeze({
    authority: 'workspace_app_runtime' as const,
    enabled: true,
    profile,
    label,
    assistantLabel,
    assistantProfile,
    brandStyle,
    actionPacks: Object.freeze(actionPacks),
    providerKind,
    providerEndpoints: Object.freeze(providerEndpoints),
    genericProvider,
    legacyMorningDismissedStorageKey:
      (profile && LEGACY_MORNING_DISMISSED_STORAGE_KEYS[profile]) || null,
  });
}

/** Preserve the existing immersive-shell behaviour inside the extension only. */
export function missionRoomUsesImmersiveShell(
  workspace: WorkspaceExtensionContext | null | undefined,
  path: string,
): boolean {
  const settings = asRecord(workspace?.settings);
  const features = asRecord(settings['features']);
  if (features['workspace_app_platform_v1'] === true) {
    const runtime = asRecord(workspace?.workspace_app_runtime);
    const experience = asRecord(runtime['experience']);
    return missionRoomExtensionState(workspace).enabled
      && experience['shell'] === 'immersive'
      && stringList(experience['routes']).some((route) => (
        path === route || path.startsWith(`${route.replace(/\/$/, '')}/`)
      ));
  }
  return (
    missionRoomExtensionState(workspace).enabled &&
    workspace?.mode === 'demo' &&
    path.startsWith(MISSION_ROOM_EXTENSION.routeRoot) &&
    settings['workspace_app_shell'] === 'immersive'
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized || null;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean);
}

function sameStringList(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length
    && left.every((value, index) => value === right[index]);
}
