import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ANDRITZ_CRITICAL_SCENARIOS,
  BUSINESS_PRIMARY_SURFACE_IDS,
  FULL_COCKPIT_VERBS,
  MISSION_ROOM_CRITICAL_SCENARIOS,
  MISSION_ROOM_NAVIGATION_KEYS,
  SHOWCASE_PORTFOLIO_SCENARIO,
  WORKSPACE_EXPERIENCE_ADAPTERS,
  WORKSPACE_EXPERIENCE_CRITICAL_SCENARIOS,
  WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
  applyObservedLegacyRouteDecision,
  compareWorkspaceExperienceWithMissionNavigation,
  compareWorkspaceExperiences,
  createWorkspaceExperienceEvidence,
  evaluateWorkspaceExperienceRolloutGate,
  resolveLegacyWorkspaceExperience,
  resolveWorkspaceExperienceV2,
  workspaceExperienceFingerprint,
  workspaceExperienceScenarioKey,
  type MissionNavigationObservation,
  type WorkspaceExperienceEvidence,
  type WorkspaceExperienceExplanation,
  type WorkspaceExperienceInput,
  type WorkspaceExperienceV2,
} from './workspace-experience';

const BUSINESS_SETTINGS = {
  navigation_profile: {
    key: 'business_end_user',
    default_route: '/chat',
    primary_surfaces: ['chat', 'client360-pdr', 'knowledge-capture'],
    advanced_access: 'admin_only',
  },
};

const SENTINEL_SETTINGS = {
  demo_profile: 'government_mission_room',
  default_route: '/hypervisor/mission-room/cockpit',
  workspace_app_shell: 'immersive',
  workspace_app_label: 'SENTINEL-CI',
  workspace_app_default_view: 'cockpit',
  assistant_profile_default: 'vigie_executive',
  mission_room: {
    enabled: true,
    profile: 'sentinel_government_v1',
    label: 'AYA',
    navigation: MISSION_ROOM_NAVIGATION_KEYS.map((key) => ({ key })),
  },
};

const OCTOCITY_SETTINGS = {
  demo_profile: 'octocity_mission_room',
  default_route: '/hypervisor/mission-room/cockpit',
  workspace_app_shell: 'immersive',
  workspace_app_label: 'Octocity Mission Room',
  workspace_app_default_view: 'cockpit',
  workspace_app_brand: {
    label: 'Octocity Mission Room',
    style: 'agentium',
  },
  assistant_profile_default: 'octave_executive',
  mission_room: {
    enabled: true,
    profile: 'octocity_institutional_v1',
    label: 'OCTAVE',
    assistant_label: 'OCTAVE',
    brand: { label: 'Octocity Mission Room', style: 'agentium' },
    navigation: MISSION_ROOM_NAVIGATION_KEYS.map((key) => ({ key })),
  },
};

const SENTINEL_OBSERVATION: MissionNavigationObservation = {
  app: {
    label: 'SENTINEL-CI',
    assistant_label: 'AYA',
    shell: 'immersive',
    default_route: '/hypervisor/mission-room/cockpit',
    default_view: 'cockpit',
    profile: 'sentinel_government_v1',
    brand: {},
  },
  items: MISSION_ROOM_NAVIGATION_KEYS.map((key) => ({
    key,
    system_id: `backend-owned-${key}`,
    system_name: `ignored-${key}`,
  })),
};

const OCTOCITY_OBSERVATION: MissionNavigationObservation = {
  app: {
    label: 'Octocity Mission Room',
    assistant_label: 'OCTAVE',
    shell: 'immersive',
    default_route: '/hypervisor/mission-room/cockpit',
    default_view: 'cockpit',
    profile: 'octocity_institutional_v1',
    brand: { style: 'agentium' },
  },
  items: MISSION_ROOM_NAVIGATION_KEYS.map((key) => ({
    key,
    system_id: `backend-owned-${key}`,
    object: `backend-owned-${key}`,
  })),
};

function input(
  slug: string,
  mode: string,
  settings: Readonly<Record<string, unknown>>,
  scenario: WorkspaceExperienceInput['scenario'],
): WorkspaceExperienceInput {
  return { workspace: { slug, mode, settings }, scenario };
}

function assertParity(
  value: WorkspaceExperienceInput,
  observation?: MissionNavigationObservation,
): WorkspaceExperienceV2 {
  const comparison = observation
    ? compareWorkspaceExperienceWithMissionNavigation(value, observation)
    : compareWorkspaceExperiences(value);
  assert.equal(comparison.status, 'match', JSON.stringify(comparison.diffs, null, 2));
  assert.deepEqual(comparison.diffs, []);
  return resolveWorkspaceExperienceV2(value);
}

test('registry IDs are unique and deterministically ordered by priority', () => {
  const ids = WORKSPACE_EXPERIENCE_ADAPTERS.map((adapter) => adapter.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.deepEqual(ids, [
    'portfolio',
    'mission_room_sentinel_legacy',
    'mission_room_octocity',
    'workspace_app_shell',
    'business_end_user',
  ]);
  assert.deepEqual(
    WORKSPACE_EXPERIENCE_ADAPTERS.map((adapter) => adapter.priority),
    [100, 200, 210, 300, 400],
  );
});

test('Andritz member keeps the rendered business experience and hard-coded surface order', () => {
  const experience = assertParity(input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    businessPreview: false,
    requestedRoute: '/systems',
  }));

  assert.equal(experience.shellKind, 'business');
  assert.equal(experience.homeRoute, '/chat');
  assert.deepEqual(experience.primarySurfaceIds, BUSINESS_PRIMARY_SURFACE_IDS);
  assert.deepEqual(experience.cockpitVerbs, []);
  assert.deepEqual(experience.routeResolution, {
    requestedRoute: '/systems',
    resolvedRoute: '/chat',
    semanticQueryKeys: [],
    workspaceTargetMatchesCurrent: null,
    semanticTargetPreserved: null,
    redirectOwner: 'workspace_experience_v2',
    redirectReason: 'business_profile_disallowed',
  });
  assert.deepEqual(experience.chrome, {
    titleBar: false,
    sideRail: false,
    objectIndex: false,
    commandBar: false,
    commandPalette: false,
    businessHeader: true,
    missionRail: false,
  });
});

test('app entitlements filter the V2 business policy in canonical order and fail closed', () => {
  const settings = {
    ...BUSINESS_SETTINGS,
    features: { app_entitlements_v1: true },
  };
  const client360Only = resolveWorkspaceExperienceV2({
    workspace: {
      slug: 'andritz',
      mode: 'builder',
      settings,
      appEntitlements: ['unknown-app', 'client360-pdr', 'client360-pdr'],
    },
    scenario: { role: 'member', requestedRoute: '/chat' },
  });
  assert.deepEqual(client360Only.primarySurfaceIds, ['client360-pdr']);
  assert.equal(client360Only.homeRoute, '/client360');
  assert.equal(client360Only.routeResolution.resolvedRoute, '/client360');
  assert.equal(client360Only.routeResolution.redirectReason, 'business_profile_disallowed');

  const missingGrants = resolveWorkspaceExperienceV2({
    workspace: { slug: 'andritz', mode: 'builder', settings },
    scenario: { role: 'member', requestedRoute: '/knowledge' },
  });
  assert.deepEqual(missingGrants.primarySurfaceIds, []);
  assert.equal(missingGrants.homeRoute, '/account/profile');
  assert.equal(missingGrants.routeResolution.resolvedRoute, '/account/profile');
  assert.equal(missingGrants.routeResolution.redirectReason, 'business_profile_disallowed');
  assert.deepEqual(missingGrants.routeResolution.semanticQueryKeys, []);
});

test('app entitlement payload is ignored until its feature flag is enabled', () => {
  const experience = resolveWorkspaceExperienceV2({
    workspace: {
      slug: 'andritz',
      mode: 'builder',
      settings: BUSINESS_SETTINGS,
      appEntitlements: [],
    },
    scenario: { role: 'member', requestedRoute: '/systems' },
  });

  assert.deepEqual(experience.primarySurfaceIds, BUSINESS_PRIMARY_SURFACE_IDS);
  assert.equal(experience.homeRoute, '/chat');
  assert.equal(experience.routeResolution.resolvedRoute, '/chat');
});

test('Andritz admin remains standard while admin preview restores business', () => {
  const admin = assertParity(input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'admin',
    businessPreview: false,
    requestedRoute: '/systems',
  }));
  assert.equal(admin.shellKind, 'agentium_standard');
  assert.equal(admin.homeRoute, '/hypervisor');
  assert.deepEqual(admin.cockpitVerbs, ['build', 'operate', 'govern']);
  assert.equal(admin.business.active, false);

  const preview = assertParity(input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'admin',
    businessPreview: true,
    requestedRoute: '/systems',
  }));
  assert.equal(preview.shellKind, 'business');
  assert.deepEqual(preview.primarySurfaceIds, BUSINESS_PRIMARY_SURFACE_IDS);
  assert.equal(preview.business.active, true);
});

test('workspace_admin role template is classified as admin', () => {
  const admin = assertParity(input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    roleTemplate: 'workspace_admin',
    businessPreview: false,
    requestedRoute: '/systems',
  }));
  assert.equal(admin.business.admin, true);
  assert.equal(admin.business.active, false);
  assert.equal(admin.shellKind, 'agentium_standard');
});

test('unsupported admin shorthand is not broader than WorkspaceService.isAdmin', () => {
  const member = assertParity(input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    roleTemplate: 'admin',
    businessPreview: false,
    requestedRoute: '/systems',
  }));
  assert.equal(member.business.admin, false);
  assert.equal(member.business.active, true);
  assert.equal(member.shellKind, 'business');
});

test('custom primary_surfaces and link/hidden access do not drive legacy shell or routes', () => {
  for (const access of ['link', 'hidden'] as const) {
    const value = input('configured-business', 'builder', {
      navigation_profile: {
        key: 'business_end_user',
        default_route: '/systems',
        primary_surfaces: ['custom-one', 'custom-two'],
        advanced_access: access,
      },
    }, { role: 'member', requestedRoute: '/runs' });
    const experience = assertParity(value);
    assert.deepEqual(experience.business.declaredPrimarySurfaceIds, ['custom-one', 'custom-two']);
    assert.deepEqual(experience.primarySurfaceIds, BUSINESS_PRIMARY_SURFACE_IDS);
    assert.equal(experience.advancedAccess, access);
    assert.equal(experience.routeResolution.resolvedRoute, '/chat');
    assert.equal(experience.shellKind, 'business');
  }
});

test('business compatibility aliases remain route-sensitive and canonical', () => {
  const knowledge = assertParity(input('business', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/knowledge?private=value',
  }));
  assert.equal(knowledge.routeResolution.resolvedRoute, '/knowledge/capture');
  assert.equal(knowledge.routeResolution.redirectReason, 'business_knowledge_compatibility');

  const capture = assertParity(input('business', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/systems/private-system-id/capture',
  }));
  assert.equal(capture.routeResolution.requestedRoute, '/systems/:systemId/capture');
  assert.equal(capture.routeResolution.resolvedRoute, '/knowledge/capture');
  assert.deepEqual(capture.routeResolution.semanticQueryKeys, ['systemId']);
  assert.equal(capture.routeResolution.redirectReason, 'business_system_capture_compatibility');
});

test('configured business defaults never retain query values in either projection', () => {
  const value = input('business', 'builder', {
    navigation_profile: {
      key: 'business_end_user',
      default_route: '/chat?customer=private-value',
      primary_surfaces: [...BUSINESS_PRIMARY_SURFACE_IDS],
      advanced_access: 'admin_only',
    },
  }, { role: 'member', requestedRoute: '/systems' });

  const legacy = resolveLegacyWorkspaceExperience(value);
  const candidate = resolveWorkspaceExperienceV2(value);
  assert.equal(legacy.homeRoute, '/chat');
  assert.equal(candidate.homeRoute, '/chat');
  assert.equal(legacy.routeResolution.resolvedRoute, '/chat');
  assert.equal(candidate.routeResolution.resolvedRoute, '/chat');
  assert.equal(JSON.stringify({ legacy, candidate }).includes('private-value'), false);
  assert.equal(compareWorkspaceExperiences(value).status, 'match');
});

test('system capture compares semantic query presence without retaining its value or System id', () => {
  const privateSystemId = 'secret-system-A';
  const privateQueryValue = 'secret-query-value-A';
  const value = input('business', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: `/systems/${privateSystemId}/capture`,
  });
  const observedWithScope = compareWorkspaceExperiences(value, {
    observedLegacyRouteDecision: {
      requestedRoute: `/systems/${privateSystemId}/capture`,
      resolvedRoute: `/knowledge/capture?systemId=${privateSystemId}`,
      reason: 'business_system_capture_compatibility',
    },
  });
  assert.equal(observedWithScope.status, 'match');

  const observedWithWrongTarget = compareWorkspaceExperiences(value, {
    observedLegacyRouteDecision: {
      requestedRoute: `/systems/${privateSystemId}/capture`,
      resolvedRoute: `/knowledge/capture?systemId=${privateQueryValue}`,
      reason: 'business_system_capture_compatibility',
    },
  });
  assert.equal(observedWithWrongTarget.status, 'unexplained_divergence');
  assert.ok(observedWithWrongTarget.diffs.some((diff) =>
    diff.path === '/routeResolution/semanticTargetPreserved'));

  const observedWithoutScope = compareWorkspaceExperiences(value, {
    observedLegacyRouteDecision: {
      requestedRoute: `/systems/${privateSystemId}/capture`,
      resolvedRoute: '/knowledge/capture',
      reason: 'business_system_capture_compatibility',
      semanticQueryKeys: [],
    },
  });
  assert.equal(observedWithoutScope.status, 'unexplained_divergence');
  assert.deepEqual(observedWithoutScope.diffs, [
    {
      path: '/routeResolution/semanticQueryKeys/0',
      code: 'missing_legacy',
    },
    {
      path: '/routeResolution/semanticTargetPreserved',
      code: 'value_mismatch',
    },
  ]);

  const projection = resolveWorkspaceExperienceV2(value);
  assert.equal(projection.routeResolution.requestedRoute, '/systems/:systemId/capture');
  assert.deepEqual(projection.routeResolution.semanticQueryKeys, ['systemId']);
  assert.equal(projection.routeResolution.semanticTargetPreserved, true);
  for (const serialized of [
    JSON.stringify(projection),
    JSON.stringify(observedWithScope),
    JSON.stringify(observedWithWrongTarget),
    JSON.stringify(observedWithoutScope),
    observedWithScope.fingerprint,
    observedWithScope.scenarioKey,
  ]) {
    assert.equal(serialized.includes(privateSystemId), false);
    assert.equal(serialized.includes(privateQueryValue), false);
  }
});

test('observed system capture compares a decoded query to an encoded route segment', () => {
  const value = input('business', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/systems/system%2042/capture',
  });

  const comparison = compareWorkspaceExperiences(value, {
    observedLegacyRouteDecision: {
      requestedRoute: '/systems/system%2042/capture',
      resolvedRoute: '/knowledge/capture?systemId=system%2042',
      reason: 'business_system_capture_compatibility',
    },
  });

  assert.equal(comparison.status, 'match');
});

test('workspace entrypoint comparison preserves tenant equality without retaining the target slug', () => {
  const privateOtherSlug = 'private-other-tenant';
  const value = input('andritz', 'builder', {}, {
    role: 'admin',
    requestedRoute: '/workspace',
  });
  const matching = compareWorkspaceExperiences(value, {
    observedLegacyRouteDecision: {
      requestedRoute: '/workspace',
      resolvedRoute: '/workspace/andritz/settings',
      reason: 'workspace_settings_entrypoint',
    },
  });
  assert.equal(matching.status, 'match');

  const drift = compareWorkspaceExperiences(value, {
    observedLegacyRouteDecision: {
      requestedRoute: '/workspace',
      resolvedRoute: `/workspace/${privateOtherSlug}/settings`,
      reason: 'workspace_settings_entrypoint',
    },
  });
  assert.equal(drift.status, 'unexplained_divergence');
  assert.ok(drift.diffs.some((diff) =>
    diff.path === '/routeResolution/workspaceTargetMatchesCurrent'));
  assert.equal(JSON.stringify(drift).includes(privateOtherSlug), false);
});

test('comparator consumes the decision actually observed from NavigationResolverService', () => {
  const value = input('business', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/systems',
  });
  assert.equal(compareWorkspaceExperiences(value, {
    observedLegacyRouteDecision: {
      requestedRoute: '/systems',
      resolvedRoute: '/chat',
      reason: 'business_profile_disallowed',
    },
  }).status, 'match');

  const drift = compareWorkspaceExperiences(value, {
    observedLegacyRouteDecision: null,
  });
  assert.equal(drift.status, 'unexplained_divergence');
  assert.ok(drift.diffs.some((diff) => diff.path === '/routeResolution/resolvedRoute'));
  assert.ok(drift.diffs.some((diff) => diff.path === '/routeResolution/redirectReason'));
});

test('legacy Showcase portfolio projects standard chrome and all five cockpit verbs', () => {
  const experience = assertParity(SHOWCASE_PORTFOLIO_SCENARIO.input);
  assert.deepEqual(experience.registryEntryIds, ['portfolio']);
  assert.equal(experience.shellKind, 'agentium_standard');
  assert.equal(experience.homeRoute, '/hypervisor');
  assert.deepEqual(experience.cockpitVerbs, FULL_COCKPIT_VERBS);
  assert.deepEqual(experience.primarySurfaceIds, FULL_COCKPIT_VERBS);
});

test('Sentinel API observation maps app label separately from assistant and ignores Systems ownership', () => {
  const value = input('any-government-room', 'demo', SENTINEL_SETTINGS, {
    role: 'admin',
    requestedRoute: '/hypervisor',
  });
  const experience = assertParity(value, SENTINEL_OBSERVATION);
  assert.deepEqual(experience.registryEntryIds, [
    'mission_room_sentinel_legacy',
    'workspace_app_shell',
  ]);
  assert.equal(experience.shellKind, 'workspace_app_immersive');
  assert.equal(experience.homeRoute, '/hypervisor/mission-room/cockpit');
  assert.equal(experience.missionRoom?.label, 'SENTINEL-CI');
  assert.equal(experience.missionRoom?.assistantLabel, 'AYA');
  assert.equal(experience.missionRoom?.profile, 'sentinel_government_v1');
  assert.equal(experience.missionRoom?.brandStyle, 'sentinel');
  assert.deepEqual(experience.missionRoom?.navigationKeys, MISSION_ROOM_NAVIGATION_KEYS);
  assert.equal(JSON.stringify(experience).includes('backend-owned-'), false);
});

test('Octocity API observation is selected by settings, never by slug', () => {
  const value = input('renamed-institutional-room', 'demo', OCTOCITY_SETTINGS, {
    role: 'admin',
    requestedRoute: '/hypervisor',
  });
  const experience = assertParity(value, OCTOCITY_OBSERVATION);
  assert.deepEqual(experience.registryEntryIds, [
    'mission_room_octocity',
    'workspace_app_shell',
  ]);
  assert.equal(experience.missionRoom?.label, 'Octocity Mission Room');
  assert.equal(experience.missionRoom?.assistantLabel, 'OCTAVE');
  assert.equal(experience.missionRoom?.assistantProfile, 'octave_executive');
  assert.equal(experience.missionRoom?.brandStyle, 'agentium');
});

test('Mission Room compares the effective rendered brand label and style', () => {
  const value = input('octocity-mission-room', 'demo', OCTOCITY_SETTINGS, {
    role: 'admin',
    requestedRoute: '/hypervisor',
  });
  const styleMissing: MissionNavigationObservation = {
    ...OCTOCITY_OBSERVATION,
    app: {
      ...OCTOCITY_OBSERVATION.app,
      brand: { label: 'Octocity Mission Room' },
    },
  };
  const styleDrift = compareWorkspaceExperienceWithMissionNavigation(value, styleMissing);
  assert.equal(styleDrift.status, 'unexplained_divergence');
  assert.ok(styleDrift.diffs.some((diff) =>
    diff.path === '/missionRoom/brandStyle'));

  const privateBrandLabel = 'PRIVATE CONTRADICTORY BRAND';
  const labelDrift = compareWorkspaceExperienceWithMissionNavigation(value, {
    ...OCTOCITY_OBSERVATION,
    app: {
      ...OCTOCITY_OBSERVATION.app,
      brand: { label: privateBrandLabel, style: 'agentium' },
    },
  });
  assert.equal(labelDrift.status, 'unexplained_divergence');
  assert.ok(labelDrift.diffs.some((diff) => diff.path === '/missionRoom/label'));
  assert.equal(JSON.stringify(labelDrift).includes(privateBrandLabel), false);

  const malformedStyle = compareWorkspaceExperienceWithMissionNavigation(value, {
    ...OCTOCITY_OBSERVATION,
    app: {
      ...OCTOCITY_OBSERVATION.app,
      brand: { label: 'Octocity Mission Room', style: 42 },
    },
  });
  assert.equal(malformedStyle.status, 'error');
  assert.equal(malformedStyle.legacyObservation, 'error');
});

test('candidate and independent legacy oracle honor Mission Room label as assistant fallback', () => {
  const customSettings = {
    ...SENTINEL_SETTINGS,
    mission_room: {
      ...SENTINEL_SETTINGS.mission_room,
      label: 'CUSTOM ASSISTANT',
    },
  };
  const value = input('custom-government-room', 'demo', customSettings, {
    role: 'admin',
    requestedRoute: '/hypervisor',
  });
  const legacy = resolveLegacyWorkspaceExperience(value);
  const candidate = resolveWorkspaceExperienceV2(value);
  assert.equal(legacy.missionRoom?.assistantLabel, 'CUSTOM ASSISTANT');
  assert.equal(candidate.missionRoom?.assistantLabel, 'CUSTOM ASSISTANT');
  assert.equal(compareWorkspaceExperiences(value).status, 'match');
});

test('immersive workspace app is scoped to final Mission Room route only', () => {
  const standard = assertParity(input('sentinel-ci', 'demo', SENTINEL_SETTINGS, {
    role: 'admin',
    requestedRoute: '/systems',
  }), SENTINEL_OBSERVATION);
  assert.equal(standard.shellKind, 'agentium_standard');
  assert.deepEqual(standard.cockpitVerbs, FULL_COCKPIT_VERBS);
  assert.equal(standard.chrome.missionRail, false);

  const focus = assertParity(input('sentinel-ci', 'demo', SENTINEL_SETTINGS, {
    role: 'admin',
    requestedRoute: '/workspace/sentinel-ci/chat',
  }), SENTINEL_OBSERVATION);
  assert.equal(focus.shellKind, 'workspace_focus');
  assert.equal(focus.immersiveRouteScope, '/hypervisor/mission-room/**');

  const nonDemo = assertParity(input('not-demo', 'builder', SENTINEL_SETTINGS, {
    role: 'admin',
    requestedRoute: '/hypervisor/mission-room/cockpit',
  }), SENTINEL_OBSERVATION);
  assert.equal(nonDemo.shellKind, 'agentium_standard');
});

test('overlap precedence composes profiles then workspace app then active business', () => {
  const combined = input('combined', 'demo', {
    ...OCTOCITY_SETTINGS,
    ...BUSINESS_SETTINGS,
  }, { role: 'member', requestedRoute: '/hypervisor' });
  const experience = assertParity(combined);
  assert.deepEqual(experience.registryEntryIds, [
    'mission_room_octocity',
    'workspace_app_shell',
    'business_end_user',
  ]);
  assert.equal(experience.routeResolution.resolvedRoute, '/chat');
  assert.equal(experience.shellKind, 'business');
});

test('malformed settings and unknown adapters are reported fail-closed without throwing', () => {
  const malformed = resolveWorkspaceExperienceV2(input('broken', 'future-mode', {
    navigation_profile: {
      key: 'future_profile',
      primary_surfaces: 'not-an-array',
      advanced_access: 12,
    },
    workspace_app_shell: 'future-shell',
    mission_room: { profile: 'future-profile', navigation: [{ missing: 'key' }] },
  }, { role: 'member', requestedRoute: '/systems' }));

  assert.ok(malformed.issues.some((item) => item.kind === 'unknown_adapter' && item.code === 'unknown_workspace_mode'));
  assert.ok(malformed.issues.some((item) => item.kind === 'unknown_adapter' && item.code === 'unknown_navigation_profile'));
  assert.ok(malformed.issues.some((item) => item.kind === 'error' && item.code === 'malformed_primary_surfaces'));
  assert.ok(malformed.issues.some((item) => item.kind === 'unknown_adapter' && item.code === 'unknown_workspace_app_shell'));
  assert.equal(compareWorkspaceExperiences(input('broken', 'future-mode', {
    navigation_profile: { key: 'future_profile' },
  }, { requestedRoute: '/systems' })).status, 'error');
});

test('comparator emits sorted canonical paths and explanations require exact triple', () => {
  const value = input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/systems/private-id/capture?secret=yes',
  });
  const candidate = resolveWorkspaceExperienceV2(value);
  const changed: WorkspaceExperienceV2 = {
    ...candidate,
    homeRoute: '/client360',
    chrome: { ...candidate.chrome, businessHeader: false },
  };
  const unexplained = compareWorkspaceExperiences(value, { candidate: changed, now: '2026-07-15T00:00:00Z' });
  assert.equal(unexplained.status, 'unexplained_divergence');
  assert.deepEqual(unexplained.diffs.map((diff) => diff.path), ['/chrome/businessHeader', '/homeRoute']);
  assert.equal(unexplained.scenarioKey.includes('private-id'), false);
  assert.equal(unexplained.scenarioKey.includes('secret'), false);

  const exact: WorkspaceExperienceExplanation = {
    id: 'WX-001',
    workspaceSlug: value.workspace.slug,
    scenarioKey: unexplained.scenarioKey,
    fingerprint: unexplained.fingerprint,
    owner: 'frontend-platform',
    justification: 'Temporary route projection migration.',
    expiresAt: '2026-08-01T00:00:00Z',
  };
  assert.equal(compareWorkspaceExperiences(value, {
    candidate: changed,
    explanations: [exact],
    now: '2026-07-15T00:00:00Z',
  }).status, 'explained_divergence');

  for (const mismatch of [
    { ...exact, workspaceSlug: 'another-workspace' },
    { ...exact, scenarioKey: `${exact.scenarioKey}:another` },
    { ...exact, fingerprint: `${exact.fingerprint}-another` },
  ]) {
    assert.equal(compareWorkspaceExperiences(value, {
      candidate: changed,
      explanations: [mismatch],
      now: '2026-07-15T00:00:00Z',
    }).status, 'unexplained_divergence');
  }

  const expired = compareWorkspaceExperiences(value, {
    candidate: changed,
    explanations: [{ ...exact, expiresAt: '2026-07-14T00:00:00Z' }],
    now: '2026-07-15T00:00:00Z',
  });
  assert.equal(expired.status, 'unexplained_divergence');
  assert.equal(expired.explanationState, 'expired');
});

test('explanations require complete non-empty governance and exactly one exact match', () => {
  const value = input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/systems',
  });
  const candidate = { ...resolveWorkspaceExperienceV2(value), homeRoute: '/client360' };
  const initial = compareWorkspaceExperiences(value, {
    candidate,
    now: '2026-07-15T00:00:00Z',
  });
  const valid: WorkspaceExperienceExplanation = {
    id: 'WX-GOV-001',
    workspaceSlug: value.workspace.slug,
    scenarioKey: initial.scenarioKey,
    fingerprint: initial.fingerprint,
    owner: 'frontend-platform',
    justification: 'Bounded migration waiver.',
    expiresAt: '2026-08-01T00:00:00Z',
  };
  const { owner: _owner, ...withoutOwner } = valid;
  const { justification: _justification, ...withoutJustification } = valid;
  const invalidSets: readonly WorkspaceExperienceExplanation[][] = [
    [withoutOwner as unknown as WorkspaceExperienceExplanation],
    [withoutJustification as unknown as WorkspaceExperienceExplanation],
    [{ ...valid, id: '   ' }],
    [{ ...valid, owner: '' }],
    [{ ...valid, justification: '   ' }],
    [{ ...valid, expiresAt: 'not-a-date' }],
    [valid, { ...valid, id: 'WX-GOV-002' }],
  ];

  for (const explanations of invalidSets) {
    const comparison = compareWorkspaceExperiences(value, {
      candidate,
      explanations,
      now: '2026-07-15T00:00:00Z',
    });
    assert.equal(comparison.status, 'unexplained_divergence');
    assert.equal(comparison.explanationState, 'invalid');
    assert.equal(comparison.explanationId, null);
  }

  const duplicateComparison = compareWorkspaceExperiences(value, {
    candidate,
    explanations: [valid, { ...valid, id: 'WX-GOV-002' }],
    now: '2026-07-15T00:00:00Z',
  });
  const evidence = completeCriticalEvidence();
  evidence[0] = createWorkspaceExperienceEvidence(value, duplicateComparison);
  const gate = evaluateWorkspaceExperienceRolloutGate(evidence);
  assert.equal(gate.allowed, false);
  assert.ok(gate.blockers.some((blocker) =>
    blocker.code === 'unexplained_divergence' && blocker.scenarioKey === duplicateComparison.scenarioKey));

  const matching = compareWorkspaceExperiences(value, { now: '2026-07-15T00:00:00Z' });
  const matchingExplanation = {
    ...valid,
    fingerprint: matching.fingerprint,
  };
  const duplicateOnMatch = compareWorkspaceExperiences(value, {
    explanations: [matchingExplanation, { ...matchingExplanation, id: 'WX-GOV-003' }],
    now: '2026-07-15T00:00:00Z',
  });
  assert.equal(duplicateOnMatch.status, 'match');
  assert.equal(duplicateOnMatch.explanationState, 'invalid');
  evidence[0] = createWorkspaceExperienceEvidence(value, duplicateOnMatch);
  assert.ok(evaluateWorkspaceExperienceRolloutGate(evidence).blockers.some((blocker) =>
    blocker.code === 'unexplained_divergence' && blocker.scenarioKey === duplicateOnMatch.scenarioKey));
});

test('fingerprint is canonical, exact, and changes with any compared value', () => {
  assert.equal(
    workspaceExperienceFingerprint({ b: 2, a: ['x', 1] }),
    'wxp2-fnv1a64-d0994a18e78256cb',
  );
  assert.equal(
    workspaceExperienceFingerprint({ b: 2, a: ['x', 1] }),
    workspaceExperienceFingerprint({ a: ['x', 1], b: 2 }),
  );
  assert.notEqual(
    workspaceExperienceFingerprint({ a: ['x', 1], b: 2 }),
    workspaceExperienceFingerprint({ a: ['x', 2], b: 2 }),
  );
});

test('public diffs redact values while the exact raw mismatch still changes the fingerprint', () => {
  const value = input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/systems',
  });
  const base = resolveWorkspaceExperienceV2(value);
  const first = compareWorkspaceExperiences(value, {
    candidate: { ...base, homeRoute: '/private-home-A' },
  });
  const second = compareWorkspaceExperiences(value, {
    candidate: { ...base, homeRoute: '/private-home-B' },
  });
  assert.deepEqual(first.diffs, [{ path: '/homeRoute', code: 'value_mismatch' }]);
  assert.deepEqual(second.diffs, first.diffs);
  assert.notEqual(first.fingerprint, second.fingerprint);
  assert.equal(JSON.stringify(first).includes('/private-home-A'), false);
  assert.equal(JSON.stringify(second).includes('/private-home-B'), false);
});

test('MissionNavigation observation detects exact item order but never resolves backend Systems', () => {
  const value = input('sentinel-ci', 'demo', SENTINEL_SETTINGS, {
    role: 'admin',
    requestedRoute: '/hypervisor',
  });
  const correct = compareWorkspaceExperienceWithMissionNavigation(value, SENTINEL_OBSERVATION);
  assert.equal(correct.status, 'match');
  assert.equal(correct.legacyObservation, 'observed');

  const reversed: MissionNavigationObservation = {
    ...SENTINEL_OBSERVATION,
    items: [...(SENTINEL_OBSERVATION.items || [])].reverse(),
  };
  const mismatch = compareWorkspaceExperienceWithMissionNavigation(value, reversed);
  assert.equal(mismatch.status, 'unexplained_divergence');
  assert.ok(mismatch.diffs.some((diff) => diff.path.startsWith('/missionRoom/navigationKeys/')));

  const error = compareWorkspaceExperienceWithMissionNavigation(value, { error: 'network' });
  assert.equal(error.status, 'error');
});

test('MissionNavigation proof fails closed when items or required app fields are absent or malformed', () => {
  const value = input('sentinel-ci', 'demo', SENTINEL_SETTINGS, {
    role: 'admin',
    requestedRoute: '/hypervisor',
  });
  const app = SENTINEL_OBSERVATION.app!;
  const { label: _label, ...appWithoutLabel } = app;
  const invalidObservations: MissionNavigationObservation[] = [
    { ...SENTINEL_OBSERVATION, items: null },
    { app },
    { ...SENTINEL_OBSERVATION, app: null },
    { ...SENTINEL_OBSERVATION, app: appWithoutLabel },
    { ...SENTINEL_OBSERVATION, app: { ...app, profile: 42 } },
    { ...SENTINEL_OBSERVATION, app: { ...app, brand: null } },
    { ...SENTINEL_OBSERVATION, items: [...(SENTINEL_OBSERVATION.items || []), {}] },
  ];

  for (const observation of invalidObservations) {
    const comparison = compareWorkspaceExperienceWithMissionNavigation(value, observation);
    assert.equal(comparison.status, 'error');
    assert.equal(comparison.legacyObservation, 'error');
  }
});

test('MissionNavigation observation preserves extra keys and duplicates so drift remains visible', () => {
  const value = input('sentinel-ci', 'demo', SENTINEL_SETTINGS, {
    role: 'admin',
    requestedRoute: '/hypervisor',
  });
  const observation: MissionNavigationObservation = {
    ...SENTINEL_OBSERVATION,
    items: [
      ...(SENTINEL_OBSERVATION.items || []),
      { key: 'future-backend-surface' },
      { key: 'cockpit' },
    ],
  };
  const legacy = resolveLegacyWorkspaceExperience(value, observation);
  assert.deepEqual(legacy.missionRoom?.navigationKeys, [
    ...MISSION_ROOM_NAVIGATION_KEYS,
    'future-backend-surface',
    'cockpit',
  ]);
  const comparison = compareWorkspaceExperienceWithMissionNavigation(value, observation);
  assert.equal(comparison.status, 'unexplained_divergence');
  assert.deepEqual(
    comparison.diffs.filter((diff) => diff.path.startsWith('/missionRoom/navigationKeys/')).map((diff) => diff.path),
    ['/missionRoom/navigationKeys/7', '/missionRoom/navigationKeys/8'],
  );
});

function observationFor(value: WorkspaceExperienceInput): MissionNavigationObservation {
  return value.workspace.settings?.['demo_profile'] === 'octocity_mission_room'
    ? OCTOCITY_OBSERVATION
    : SENTINEL_OBSERVATION;
}

function completeCriticalEvidence(): WorkspaceExperienceEvidence[] {
  return WORKSPACE_EXPERIENCE_CRITICAL_SCENARIOS.map((scenario) => {
    const comparison = scenario.requiresMissionNavigationObservation
      ? compareWorkspaceExperienceWithMissionNavigation(scenario.input, observationFor(scenario.input))
      : compareWorkspaceExperiences(scenario.input);
    return createWorkspaceExperienceEvidence(scenario.input, comparison, 7, 7);
  });
}

test('exported critical matrices are complete and produce parity', () => {
  assert.equal(ANDRITZ_CRITICAL_SCENARIOS.length, 3);
  assert.equal(MISSION_ROOM_CRITICAL_SCENARIOS.length, 4);
  assert.equal(WORKSPACE_EXPERIENCE_CRITICAL_SCENARIOS.length, 7);
  for (const scenario of WORKSPACE_EXPERIENCE_CRITICAL_SCENARIOS) {
    const comparison = scenario.requiresMissionNavigationObservation
      ? compareWorkspaceExperienceWithMissionNavigation(scenario.input, observationFor(scenario.input))
      : compareWorkspaceExperiences(scenario.input);
    assert.equal(comparison.status, 'match', scenario.id);
  }
});

test('rollout gate opens only with one current valid observed proof per critical scenario', () => {
  const complete = completeCriticalEvidence();
  assert.deepEqual(evaluateWorkspaceExperienceRolloutGate(complete), { allowed: true, blockers: [] });

  const missing = evaluateWorkspaceExperienceRolloutGate(complete.slice(1));
  assert.equal(missing.allowed, false);
  assert.ok(missing.blockers.some((blocker) => blocker.code === 'missing_evidence'));

  const duplicate = evaluateWorkspaceExperienceRolloutGate([...complete, complete[0]]);
  assert.ok(duplicate.blockers.some((blocker) => blocker.code === 'duplicate_evidence'));
});

test('rollout gate blocks wrong versions, stale epoch, unknown adapter and missing MR observation', () => {
  const complete = completeCriticalEvidence();
  const wrongVersion = {
    ...complete[0],
    resolverVersion: 'old-resolver',
  } as unknown as WorkspaceExperienceEvidence;
  const stale = { ...complete[1], workspaceEpoch: 1, currentWorkspaceEpoch: 2 };
  const unknown = {
    ...complete[2],
    comparison: {
      ...complete[2].comparison!,
      candidateIssues: [{ kind: 'unknown_adapter' as const, code: 'future', path: '/mode' }],
    },
  };
  const missingObservationScenario = MISSION_ROOM_CRITICAL_SCENARIOS[0];
  const missingObservation = createWorkspaceExperienceEvidence(
    missingObservationScenario.input,
    compareWorkspaceExperiences(missingObservationScenario.input),
  );
  const replacements = new Map([
    [`${wrongVersion.workspaceSlug}::${wrongVersion.scenarioKey}`, wrongVersion],
    [`${stale.workspaceSlug}::${stale.scenarioKey}`, stale],
    [`${unknown.workspaceSlug}::${unknown.scenarioKey}`, unknown],
    [`${missingObservation.workspaceSlug}::${missingObservation.scenarioKey}`, missingObservation],
  ]);
  const result = evaluateWorkspaceExperienceRolloutGate(complete.map((item) =>
    replacements.get(`${item.workspaceSlug}::${item.scenarioKey}`) || item,
  ));
  assert.equal(result.allowed, false);
  assert.ok(result.blockers.some((blocker) => blocker.code === 'invalid_resolver_version'));
  assert.ok(result.blockers.some((blocker) => blocker.code === 'stale_workspace_epoch'));
  assert.ok(result.blockers.some((blocker) => blocker.code === 'unknown_adapter'));
  assert.ok(result.blockers.some((blocker) => blocker.code === 'missing_mission_navigation_observation'));
});

test('rollout gate blocks an expired explanation and an unexplained divergence', () => {
  const complete = completeCriticalEvidence();
  const baseScenario = ANDRITZ_CRITICAL_SCENARIOS[0];
  const candidate = { ...resolveWorkspaceExperienceV2(baseScenario.input), homeRoute: '/client360' };
  const initial = compareWorkspaceExperiences(baseScenario.input, {
    candidate,
    now: '2026-07-15T00:00:00Z',
  });
  const expired = compareWorkspaceExperiences(baseScenario.input, {
    candidate,
    now: '2026-07-15T00:00:00Z',
    explanations: [{
      id: 'expired',
      workspaceSlug: baseScenario.input.workspace.slug,
      scenarioKey: initial.scenarioKey,
      fingerprint: initial.fingerprint,
      owner: 'frontend-platform',
      justification: 'Expired test waiver.',
      expiresAt: '2026-07-14T00:00:00Z',
    }],
  });
  complete[0] = createWorkspaceExperienceEvidence(baseScenario.input, expired);
  const result = evaluateWorkspaceExperienceRolloutGate(complete);
  assert.equal(result.allowed, false);
  assert.ok(result.blockers.some((blocker) => blocker.code === 'unexplained_divergence'));
  assert.ok(result.blockers.some((blocker) => blocker.code === 'expired_explanation'));
});

test('rollout gate rejects tampered comparison identities and internally inconsistent statuses', () => {
  const complete = completeCriticalEvidence();
  const fakeDiff = {
    path: '/homeRoute',
    code: 'value_mismatch' as const,
  };
  const matchWithDiffs: WorkspaceExperienceEvidence = {
    ...complete[0],
    comparison: { ...complete[0].comparison!, diffs: [fakeDiff] },
  };
  const explainedWithoutExactProof: WorkspaceExperienceEvidence = {
    ...complete[1],
    comparison: {
      ...complete[1].comparison!,
      status: 'explained_divergence',
      diffs: [fakeDiff],
      explanationState: 'missing',
      explanationId: null,
    },
  };
  const mismatchedIdentity: WorkspaceExperienceEvidence = {
    ...complete[2],
    comparison: { ...complete[2].comparison!, workspaceSlug: 'another-workspace' },
  };
  complete.splice(0, 3, matchWithDiffs, explainedWithoutExactProof, mismatchedIdentity);

  const result = evaluateWorkspaceExperienceRolloutGate(complete);
  assert.equal(result.allowed, false);
  assert.ok(result.blockers.some((blocker) =>
    blocker.code === 'comparison_error' && blocker.scenarioKey === matchWithDiffs.scenarioKey));
  assert.ok(result.blockers.some((blocker) =>
    blocker.code === 'unexplained_divergence' && blocker.scenarioKey === explainedWithoutExactProof.scenarioKey));
  assert.ok(result.blockers.some((blocker) =>
    blocker.code === 'comparison_error' && blocker.scenarioKey === mismatchedIdentity.scenarioKey));
});

test('scenario key drops query/fragment and canonicalizes dynamic workspace and System segments', () => {
  const left = workspaceExperienceScenarioKey({
    role: 'member',
    requestedRoute: '/systems/private-a/capture?token=one#secret',
  });
  const right = workspaceExperienceScenarioKey({
    role: 'member',
    requestedRoute: '/systems/private-b/capture?token=two',
  });
  assert.equal(left, right);
  assert.equal(left.includes('private-a'), false);
  assert.equal(left.includes('token'), false);
});

test('legacy projection is independent from the exported adapter registry', () => {
  const value = input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/systems',
  });
  const legacy = resolveLegacyWorkspaceExperience(value);
  assert.deepEqual(legacy.registryEntryIds, []);
  assert.deepEqual(legacy.provenance, [
    'legacy:rendered_behavior',
    'legacy:independent_ui_oracle',
  ]);
  assert.equal(legacy.shellKind, 'business');
  assert.equal(legacy.routeResolution.redirectOwner, 'legacy_navigation_resolver');
  assert.equal(WORKSPACE_EXPERIENCE_RESOLVER_VERSION, 'workspace-experience-v2.flagged.1');
});

test('legacy oracle has no structural dependency on candidate registry or policy functions', () => {
  const implementation = [
    resolveLegacyWorkspaceExperience.toString(),
    applyObservedLegacyRouteDecision.toString(),
  ].join('\n');
  const forbiddenCalls = [
    'applyRegistry',
    'isAdminScenario',
    'isBusinessAllowedPath',
    'configuredBusinessRoute',
    'declaredBusinessSurfaces',
    'advancedAccess',
    'missionNavigationKeysFromSettings',
    'missionValue',
    'missionBrandStyle',
    'missionAppLabel',
    'missionProjection',
    'resolveRoute',
    'shellKind',
    'chromeFor',
    'cockpitVerbsFor',
    'homeRouteFor',
    'project',
  ];
  for (const name of forbiddenCalls) {
    assert.equal(
      new RegExp(`\\b${name}\\s*\\(`).test(implementation),
      false,
      `legacy oracle must not call candidate function ${name}`,
    );
  }
  assert.equal(implementation.includes('WORKSPACE_EXPERIENCE_ADAPTERS'), false);
  for (const candidateConstant of [
    'BUSINESS_PRIMARY_SURFACE_IDS',
    'FULL_COCKPIT_VERBS',
    'BUILDER_COCKPIT_VERBS',
    'MISSION_ROOM_NAVIGATION_KEYS',
  ]) {
    assert.equal(
      implementation.includes(candidateConstant),
      false,
      `legacy oracle must not reuse candidate constant ${candidateConstant}`,
    );
  }
});

test('legacy oracle is anchored directly to NavigationProfile, Shell, SideRail and Mission Room UI', () => {
  const business = resolveLegacyWorkspaceExperience(input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    requestedRoute: '/systems',
  }));
  assert.equal(business.business.active, true);
  assert.equal(business.shellKind, 'business');
  assert.deepEqual(business.primarySurfaceIds, BUSINESS_PRIMARY_SURFACE_IDS);
  assert.equal(business.routeResolution.resolvedRoute, '/chat');
  assert.deepEqual(business.chrome, {
    titleBar: false,
    sideRail: false,
    objectIndex: false,
    commandBar: false,
    commandPalette: false,
    businessHeader: true,
    missionRail: false,
  });

  const admin = resolveLegacyWorkspaceExperience(input('andritz', 'builder', BUSINESS_SETTINGS, {
    role: 'member',
    roleTemplate: 'workspace_admin',
    requestedRoute: '/systems',
  }));
  assert.equal(admin.business.active, false);
  assert.equal(admin.shellKind, 'agentium_standard');
  assert.deepEqual(admin.cockpitVerbs, ['build', 'operate', 'govern']);
  assert.equal(admin.chrome.titleBar, true);
  assert.equal(admin.chrome.commandPalette, true);

  const missionRoom = resolveLegacyWorkspaceExperience(
    input('sentinel-ci', 'demo', SENTINEL_SETTINGS, {
      role: 'admin',
      requestedRoute: '/hypervisor',
    }),
    SENTINEL_OBSERVATION,
  );
  assert.equal(missionRoom.shellKind, 'workspace_app_immersive');
  assert.equal(missionRoom.chrome.commandPalette, true);
  assert.equal(missionRoom.chrome.titleBar, false);
  assert.equal(missionRoom.missionRoom?.brandStyle, 'sentinel');
  assert.equal(missionRoom.missionRoom?.assistantLabel, 'AYA');
  assert.deepEqual(missionRoom.missionRoom?.navigationKeys, MISSION_ROOM_NAVIGATION_KEYS);
});

test('independent legacy parsing can expose candidate drift instead of producing a synthetic match', () => {
  const value = input('business', 'builder', {
    navigation_profile: {
      key: 'business_end_user',
      default_route: '/chat',
      // NavigationProfileService returns the filtered empty array here; the
      // candidate currently applies its own non-empty fallback.
      primary_surfaces: ['   '],
      advanced_access: 'admin_only',
    },
  }, { role: 'member', requestedRoute: '/systems' });
  const legacy = resolveLegacyWorkspaceExperience(value);
  const candidate = resolveWorkspaceExperienceV2(value);
  assert.deepEqual(legacy.business.declaredPrimarySurfaceIds, []);
  assert.deepEqual(candidate.business.declaredPrimarySurfaceIds, BUSINESS_PRIMARY_SURFACE_IDS);
  const comparison = compareWorkspaceExperiences(value);
  assert.equal(comparison.status, 'unexplained_divergence');
  assert.ok(comparison.diffs.some((diff) =>
    diff.path === '/business/declaredPrimarySurfaceIds/0'));
});

test('candidate constant drift cannot move the independent legacy UI oracle', () => {
  const mutableCandidateSurfaces = BUSINESS_PRIMARY_SURFACE_IDS as unknown as string[];
  mutableCandidateSurfaces.push('candidate-only-drift');
  try {
    const value = input('andritz', 'builder', BUSINESS_SETTINGS, {
      role: 'member',
      requestedRoute: '/systems',
    });
    const legacy = resolveLegacyWorkspaceExperience(value);
    const candidate = resolveWorkspaceExperienceV2(value);
    assert.deepEqual(legacy.primarySurfaceIds, [
      'chat',
      'client360-pdr',
      'knowledge-capture',
    ]);
    assert.equal(candidate.primarySurfaceIds.includes('candidate-only-drift'), true);
    assert.equal(compareWorkspaceExperiences(value).status, 'unexplained_divergence');
  } finally {
    mutableCandidateSurfaces.pop();
  }
});
