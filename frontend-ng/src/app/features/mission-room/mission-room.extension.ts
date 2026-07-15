import {
  OCTOCITY_MISSION_ROOM_PROFILE,
  SENTINEL_MISSION_ROOM_PROFILE,
} from './mission-room.presentation';

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

export interface WorkspaceExtensionContext {
  readonly mode?: string | null;
  readonly settings?: Record<string, unknown> | null;
}

export interface MissionRoomExtensionState {
  readonly enabled: boolean;
  readonly profile: string | null;
  readonly label: string | null;
  readonly assistantLabel: string | null;
  readonly actionPacks: readonly string[];
  /** Profile-owned migration hook; never inferred from the workspace slug. */
  readonly legacyMorningDismissedStorageKey: string | null;
}

const LEGACY_MORNING_DISMISSED_STORAGE_KEYS: Readonly<Record<string, string>> = Object.freeze({
  [SENTINEL_MISSION_ROOM_PROFILE]: 'sentinel-ci-aya-morning-dismissed',
});

export function missionRoomExtensionState(
  workspace: WorkspaceExtensionContext | null | undefined,
): MissionRoomExtensionState {
  const settings = asRecord(workspace?.settings);
  const missionRoom = asRecord(settings['mission_room']);
  const brand = asRecord(missionRoom['brand']);
  const actions = asRecord(settings['actions']);
  const configuredProfile = nonEmptyString(missionRoom['profile']);
  const demoProfile = nonEmptyString(settings['demo_profile']);
  const profile = configuredProfile || (
    demoProfile === 'government_mission_room' ? SENTINEL_MISSION_ROOM_PROFILE : null
  );

  return Object.freeze({
    enabled: missionRoom['enabled'] === true,
    profile,
    label: nonEmptyString(brand['label']) || nonEmptyString(settings['workspace_app_label']),
    assistantLabel:
      nonEmptyString(missionRoom['assistant_label']) || nonEmptyString(missionRoom['label']),
    actionPacks: Object.freeze(stringList(actions['enabled_packs'])),
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
