import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal, type WritableSignal } from '@angular/core';
import { NavigationProfileService } from './navigation-profile.service';
import type { NavigationRedirectDecision } from './navigation-telemetry.service';
import {
  MISSION_ROOM_NAVIGATION_KEYS,
  workspaceExperienceScenarioKey,
  type MissionNavigationObservation,
  type WorkspaceExperienceEvidence,
} from './workspace-experience';
import { WorkspaceExperienceShadowService } from './workspace-experience-shadow.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceInfo,
  type WorkspaceRequestScope,
} from './workspace.service';

const ANDRITZ_SETTINGS = {
  navigation_profile: {
    key: 'business_end_user',
    default_route: '/chat',
    primary_surfaces: ['chat', 'client360-pdr', 'knowledge-capture'],
    advanced_access: 'admin_only',
  },
};

const ANDRITZ: WorkspaceInfo = {
  id: 'workspace-andritz',
  name: 'Andritz',
  slug: 'andritz',
  role: 'member',
  mode: 'builder',
  settings: ANDRITZ_SETTINGS,
};

const SENTINEL: WorkspaceInfo = {
  id: 'workspace-sentinel',
  name: 'Sentinel',
  slug: 'sentinel-ci',
  role: 'admin',
  mode: 'demo',
  settings: {
    demo_profile: 'government_mission_room',
    workspace_app_shell: 'immersive',
    workspace_app_label: 'SENTINEL-CI',
    workspace_app_default_view: 'cockpit',
    default_route: '/hypervisor/mission-room/cockpit',
    assistant_profile_default: 'vigie_executive',
    mission_room: {
      enabled: true,
      profile: 'sentinel_government_v1',
      label: 'AYA',
      navigation: MISSION_ROOM_NAVIGATION_KEYS.map((key) => ({ key })),
    },
  },
};

const OCTOCITY: WorkspaceInfo = {
  id: 'workspace-octocity',
  name: 'Octocity Mission Room',
  slug: 'octocity-mission-room',
  role: 'admin',
  mode: 'demo',
  settings: {
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
  },
};

const MATCHING_DECISION: NavigationRedirectDecision = {
  requestedRoute: '/systems',
  resolvedRoute: '/chat',
  owner: 'navigation_resolver',
  reason: 'business_profile_disallowed',
};

class WorkspaceStub {
  private readonly listState: WritableSignal<WorkspaceInfo[]>;
  private readonly slugState: WritableSignal<string | null>;
  private readonly epochState = signal(7);
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  constructor(list: WorkspaceInfo[], activeSlug: string | null) {
    this.listState = signal([...list]);
    this.slugState = signal(activeSlug);
  }

  workspaces = () => this.listState();
  currentSlug = () => this.slugState();
  contextEpoch = () => this.epochState();
  current = () => this.listState().find((item) => item.slug === this.slugState()) || null;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slugState(), workspaceId: `workspace-${this.slugState()}`, epoch: this.epochState() });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slugState() && scope.epoch === this.epochState();
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  switchWorkspace(nextSlug: string): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slugState(),
      nextSlug,
      previousEpoch: this.epochState(),
      nextEpoch: this.epochState() + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slugState.set(nextSlug);
    this.epochState.set(transition.nextEpoch);
  }

  replaceWorkspace(next: WorkspaceInfo): void {
    this.listState.update((list) => list.map((item) => item.slug === next.slug ? next : item));
  }
}

function createHarness(
  workspaces: WorkspaceInfo[] = [ANDRITZ],
  activeSlug = 'andritz',
) {
  const workspace = new WorkspaceStub(workspaces, activeSlug);
  const injector = Injector.create({
    providers: [
      WorkspaceExperienceShadowService,
      { provide: WorkspaceService, useValue: workspace },
      {
        provide: NavigationProfileService,
        useValue: { effective: () => ({ preview: false }) },
      },
    ],
  });
  return {
    workspace,
    shadow: injector.get(WorkspaceExperienceShadowService),
  };
}

function memberSystemsScenarioKey(): string {
  return workspaceExperienceScenarioKey({
    role: 'member',
    roleTemplate: null,
    businessPreview: false,
    requestedRoute: '/systems',
  });
}

function memberSystemCaptureScenarioKey(): string {
  return workspaceExperienceScenarioKey({
    role: 'member',
    roleTemplate: null,
    businessPreview: false,
    requestedRoute: '/systems/system-A/capture',
  });
}

function sentinelNavigationPayload() {
  return {
    workspace: {
      id: 'workspace-sentinel',
      slug: 'sentinel-ci',
      name: 'SENTINEL-CI',
    },
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
      label: key,
      route: `/hypervisor/mission-room/${key}`,
      api: `/api/v1/mission-room/${key}`,
    })),
    exit_routes: [{ label: 'Agentium', route: '/hypervisor' }],
  };
}

function octocityNavigationPayload() {
  return {
    workspace: {
      id: 'workspace-octocity',
      slug: 'octocity-mission-room',
      name: 'Octocity Mission Room',
    },
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
      label: key,
      route: `/hypervisor/mission-room/${key}`,
      api: `/api/v1/mission-room/${key}`,
    })),
    exit_routes: [{ label: 'Agentium', route: '/hypervisor' }],
  };
}

function assertSentinelObservationError(shadow: WorkspaceExperienceShadowService): void {
  const sentinelReports = shadow.reports().filter(
    (item) => item.workspaceSlug === 'sentinel-ci',
  );
  assert.equal(sentinelReports.length, 2);
  assert.ok(sentinelReports.every((item) => item.comparison?.status === 'error'));
  assert.ok(sentinelReports.every((item) =>
    item.comparison?.legacyObservation === 'error',
  ));
  assert.ok(shadow.gate().blockers.some((item) =>
    item.workspaceSlug === 'sentinel-ci' && item.code === 'comparison_error',
  ));
}

function openCrossWorkspaceGate() {
  const harness = createHarness(
    [ANDRITZ, SENTINEL, OCTOCITY],
    'sentinel-ci',
  );
  const staleSentinelScope = harness.workspace.captureRequestScope();
  harness.shadow.observeMissionNavigation(
    sentinelNavigationPayload() as unknown as MissionNavigationObservation,
    staleSentinelScope,
  );
  assert.equal(harness.shadow.gate().allowed, false);

  harness.workspace.switchWorkspace('octocity-mission-room');
  assert.deepEqual(harness.shadow.reports(), []);
  harness.shadow.observeMissionNavigation(
    octocityNavigationPayload() as unknown as MissionNavigationObservation,
    harness.workspace.captureRequestScope(),
  );
  assert.equal(harness.shadow.gate().allowed, true);
  return { ...harness, staleSentinelScope };
}

function withMutedWarnings<T>(run: () => T): T {
  const original = console.warn;
  console.warn = () => undefined;
  try {
    return run();
  } finally {
    console.warn = original;
  }
}

test('shadow runtime records a match against the exact legacy redirect decision', () => {
  withMutedWarnings(() => {
    const { shadow } = createHarness();
    try {
      shadow.observeNavigation('/systems?secret=not-evidence', MATCHING_DECISION);

      const report = shadow.reports().find((item) =>
        item.workspaceSlug === 'andritz'
        && item.scenarioKey === memberSystemsScenarioKey(),
      );
      assert.equal(report?.comparison?.status, 'match');
      assert.equal(report?.comparison?.diffs.length, 0);
      assert.ok(shadow.gate().blockers.some((item) => item.code === 'missing_evidence'));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('shadow runtime reports but never applies a divergent legacy decision', () => {
  const warnings: unknown[][] = [];
  const original = console.warn;
  console.warn = (...args: unknown[]) => warnings.push(args);
  try {
    const { shadow } = createHarness();
    try {
      shadow.observeNavigation('/systems', {
        ...MATCHING_DECISION,
        resolvedRoute: '/client360',
      });

      const report = shadow.reports().find((item) =>
        item.workspaceSlug === 'andritz'
        && item.scenarioKey === memberSystemsScenarioKey(),
      );
      assert.equal(report?.comparison?.status, 'unexplained_divergence');
      assert.ok(report?.comparison?.diffs.some((item) =>
        item.path === '/routeResolution/resolvedRoute',
      ));
      assert.ok(shadow.gate().blockers.some((item) => item.code === 'unexplained_divergence'));

      for (const warning of warnings) {
        assert.equal(warning[0], '[workspace-experience-shadow]');
        assert.deepEqual(
          Object.keys(warning[1] as Record<string, unknown>).sort(),
          ['codes', 'fingerprint', 'status'],
        );
      }
    } finally {
      shadow.ngOnDestroy();
    }
  } finally {
    console.warn = original;
  }
});

test('workspace entrypoint blocks a cross-workspace target before slug redaction', () => {
  withMutedWarnings(() => {
    const adminWorkspace: WorkspaceInfo = { ...ANDRITZ, role: 'admin' };
    const { shadow } = createHarness([adminWorkspace]);
    const privateOtherSlug = 'private-other-tenant';
    try {
      shadow.observeNavigation('/workspace', {
        requestedRoute: '/workspace',
        resolvedRoute: `/workspace/${privateOtherSlug}/settings`,
        owner: 'navigation_resolver',
        reason: 'workspace_settings_entrypoint',
      });
      const scenarioKey = workspaceExperienceScenarioKey({
        role: 'admin',
        roleTemplate: null,
        businessPreview: false,
        requestedRoute: '/workspace',
      });
      const report = shadow.reports().find((item) =>
        item.workspaceSlug === 'andritz' && item.scenarioKey === scenarioKey,
      );
      assert.equal(report?.comparison?.status, 'unexplained_divergence');
      assert.ok(report?.comparison?.diffs.some((item) =>
        item.path === '/routeResolution/workspaceTargetMatchesCurrent',
      ));
      assert.equal(JSON.stringify(shadow.reports()).includes(privateOtherSlug), false);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('system capture keeps only equality/presence proofs and never retains its query value', () => {
  const warnings: unknown[][] = [];
  const original = console.warn;
  console.warn = (...args: unknown[]) => warnings.push(args);
  try {
    const { shadow } = createHarness();
    try {
      shadow.observeNavigation('/systems/system-A/capture', {
        requestedRoute: '/systems/system-A/capture',
        resolvedRoute: '/knowledge/capture?systemId=system-A',
        owner: 'navigation_resolver',
        reason: 'business_system_capture_compatibility',
      });

      const report = shadow.reports().find((item) =>
        item.workspaceSlug === 'andritz'
        && item.scenarioKey === memberSystemCaptureScenarioKey(),
      );
      assert.equal(report?.comparison?.status, 'match');
      assert.equal(report?.comparison?.diffs.length, 0);
      assert.equal(JSON.stringify(shadow.reports()).includes('system-A'), false);
      assert.equal(JSON.stringify(warnings).includes('system-A'), false);
    } finally {
      shadow.ngOnDestroy();
    }
  } finally {
    console.warn = original;
  }
});

test('system capture blocks a different forwarded System id without retaining either id', () => {
  withMutedWarnings(() => {
    const { shadow } = createHarness();
    try {
      shadow.observeNavigation('/systems/system-A/capture', {
        requestedRoute: '/systems/system-A/capture',
        resolvedRoute: '/knowledge/capture?systemId=private-wrong-system-B',
        owner: 'navigation_resolver',
        reason: 'business_system_capture_compatibility',
      });

      const report = shadow.reports().find((item) =>
        item.workspaceSlug === 'andritz'
        && item.scenarioKey === memberSystemCaptureScenarioKey(),
      );
      assert.equal(report?.comparison?.status, 'unexplained_divergence');
      assert.ok(report?.comparison?.diffs.some((item) =>
        item.path === '/routeResolution/semanticTargetPreserved',
      ));
      const serialized = JSON.stringify(shadow.reports());
      assert.equal(serialized.includes('system-A'), false);
      assert.equal(serialized.includes('private-wrong-system-B'), false);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('system capture without the semantic systemId key is an observed divergence', () => {
  withMutedWarnings(() => {
    const { shadow } = createHarness();
    try {
      shadow.observeNavigation('/systems/system-A/capture', {
        requestedRoute: '/systems/system-A/capture',
        resolvedRoute: '/knowledge/capture',
        owner: 'navigation_resolver',
        reason: 'business_system_capture_compatibility',
      });

      const report = shadow.reports().find((item) =>
        item.workspaceSlug === 'andritz'
        && item.scenarioKey === memberSystemCaptureScenarioKey(),
      );
      assert.equal(report?.comparison?.status, 'unexplained_divergence');
      assert.ok(report?.comparison?.diffs.some((item) =>
        item.path.startsWith('/routeResolution/semanticQueryKeys'),
      ));
      assert.ok(shadow.gate().blockers.some((item) =>
        item.code === 'unexplained_divergence',
      ));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('unknown runtime configuration is fail-closed evidence instead of a thrown error', () => {
  withMutedWarnings(() => {
    const invalid = {
      ...ANDRITZ,
      mode: 'future-mode',
    } as unknown as WorkspaceInfo;
    const { shadow } = createHarness([invalid]);
    try {
      assert.doesNotThrow(() => shadow.observeNavigation('/systems', MATCHING_DECISION));
      const report = shadow.reports().find((item) => item.workspaceSlug === 'andritz');
      assert.equal(report?.comparison?.status, 'error');
      assert.ok(report?.comparison?.candidateIssues.some((item) =>
        item.code === 'unknown_workspace_mode',
      ));
      assert.ok(shadow.gate().blockers.some((item) => item.code === 'unknown_adapter'));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('workspace reset atomically clears reports and rejects late A observations', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([ANDRITZ, SENTINEL]);
    try {
      shadow.observeNavigation('/systems', MATCHING_DECISION);
      assert.ok(shadow.reports().length > 0);
      const staleScope = workspace.captureRequestScope();

      workspace.switchWorkspace('sentinel-ci');
      assert.deepEqual(shadow.reports(), []);
      assert.equal(shadow.gate().allowed, false);

      shadow.observeMissionNavigation({
        workspace: { slug: 'andritz' },
        app: { label: 'late A' },
        items: [{ key: 'cockpit' }],
      } as MissionNavigationObservation, staleScope);
      assert.deepEqual(shadow.reports(), []);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('current complete Sentinel payload marks both critical scenarios observed without mutation', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([SENTINEL], 'sentinel-ci');
    const navigation = sentinelNavigationPayload();
    const snapshot = structuredClone(navigation);

    try {
      shadow.observeMissionNavigation(
        navigation as unknown as MissionNavigationObservation,
        workspace.captureRequestScope(),
      );

      const sentinelReports = shadow.reports().filter(
        (item) => item.workspaceSlug === 'sentinel-ci',
      );
      assert.equal(sentinelReports.length, 2);
      assert.ok(sentinelReports.every((item) =>
        item.comparison?.legacyObservation === 'observed',
      ));
      assert.ok(sentinelReports.every((item) =>
        item.comparison?.status === 'match',
      ));
      assert.deepEqual(navigation, snapshot);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('sealed Mission Room proofs aggregate across workspaces and invalidate on config drift', () => {
  withMutedWarnings(() => {
    const { shadow, workspace, staleSentinelScope } = openCrossWorkspaceGate();
    try {
      const sealed = (
        shadow as unknown as {
          sealedEvidenceState: () => readonly { evidence: WorkspaceExperienceEvidence }[];
        }
      ).sealedEvidenceState();
      const serializedCache = JSON.stringify(sealed);
      for (const rawLabel of ['SENTINEL-CI', 'Octocity Mission Room', 'AYA', 'OCTAVE']) {
        assert.equal(serializedCache.includes(rawLabel), false);
      }
      const currentOctocityReport = shadow.reports().find(
        (item) => item.workspaceSlug === 'octocity-mission-room',
      );
      const sealedOctocityReport = sealed.find(
        (item) => item.evidence.workspaceSlug === 'octocity-mission-room',
      )?.evidence;
      assert.notEqual(sealedOctocityReport, currentOctocityReport);
      assert.notEqual(sealedOctocityReport?.comparison, currentOctocityReport?.comparison);
      assert.notEqual(
        sealedOctocityReport?.comparison?.diffs,
        currentOctocityReport?.comparison?.diffs,
      );

      const reportsBeforeLateA = JSON.stringify(shadow.reports());
      const gateBeforeLateA = shadow.gate();
      shadow.observeMissionNavigation(
        sentinelNavigationPayload() as unknown as MissionNavigationObservation,
        staleSentinelScope,
      );
      assert.equal(JSON.stringify(shadow.reports()), reportsBeforeLateA);
      assert.deepEqual(shadow.gate(), gateBeforeLateA);

      workspace.replaceWorkspace({
        ...SENTINEL,
        settings: {
          ...SENTINEL.settings,
          workspace_app_label: 'SENTINEL-CI changed',
        },
      });
      assert.equal(shadow.gate().allowed, false);
      assert.ok(shadow.gate().blockers.some((item) =>
        item.workspaceSlug === 'sentinel-ci' && item.code === 'missing_evidence',
      ));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('sealed proof does not survive workspace recreation with the same slug and config', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = openCrossWorkspaceGate();
    try {
      workspace.replaceWorkspace({
        ...SENTINEL,
        id: 'workspace-sentinel-recreated',
      });
      assert.equal(shadow.gate().allowed, false);
      assert.ok(shadow.gate().blockers.some((item) =>
        item.workspaceSlug === 'sentinel-ci' && item.code === 'missing_evidence',
      ));

      // A subsequent evaluation must not reuse and reseal the Octocity
      // payload captured under the old workspace id.
      workspace.replaceWorkspace({
        ...OCTOCITY,
        id: 'workspace-octocity-recreated',
      });
      assert.equal(shadow.gate().allowed, false);
      shadow.observeNavigation('/systems', null);
      assert.equal(shadow.gate().allowed, false);
      assert.ok(shadow.gate().blockers.some((item) =>
        item.workspaceSlug === 'octocity-mission-room'
        && item.code === 'missing_mission_navigation_observation',
      ));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('raw Mission Room observation cannot be resealed after same-id config drift', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = openCrossWorkspaceGate();
    try {
      workspace.replaceWorkspace({
        ...OCTOCITY,
        settings: {
          ...OCTOCITY.settings,
          workspace_app_label: 'Octocity changed configuration',
        },
      });
      assert.equal(shadow.gate().allowed, false);

      shadow.observeNavigation('/systems', null);
      assert.equal(shadow.gate().allowed, false);
      assert.ok(shadow.gate().blockers.some((item) =>
        item.workspaceSlug === 'octocity-mission-room'
        && item.code === 'missing_mission_navigation_observation',
      ));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('a synthetic projection cannot overwrite an observed runtime divergence', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness(
      [ANDRITZ, SENTINEL, OCTOCITY],
      'andritz',
    );
    try {
      shadow.observeNavigation('/systems', {
        ...MATCHING_DECISION,
        resolvedRoute: '/client360',
      });
      assert.ok(shadow.gate().blockers.some((item) =>
        item.workspaceSlug === 'andritz' && item.code === 'unexplained_divergence',
      ));

      workspace.switchWorkspace('sentinel-ci');
      shadow.observeMissionNavigation(
        sentinelNavigationPayload() as unknown as MissionNavigationObservation,
        workspace.captureRequestScope(),
      );
      assert.ok(shadow.gate().blockers.some((item) =>
        item.workspaceSlug === 'andritz' && item.code === 'unexplained_divergence',
      ));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('Mission Room rejects an old workspace id after same-slug recreation without epoch change', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([SENTINEL], 'sentinel-ci');
    const oldScope = workspace.captureRequestScope();
    workspace.replaceWorkspace({
      ...SENTINEL,
      id: 'workspace-sentinel-recreated',
    });
    try {
      shadow.observeMissionNavigation(
        sentinelNavigationPayload() as unknown as MissionNavigationObservation,
        oldScope,
      );
      assert.deepEqual(shadow.reports(), []);
      assert.ok(shadow.gate().blockers.some((item) =>
        item.workspaceSlug === 'sentinel-ci' && item.code === 'missing_evidence',
      ));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('Sentinel observation with an absent brand remains invalid and fail-closed', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([SENTINEL], 'sentinel-ci');
    const navigation = sentinelNavigationPayload();
    delete (navigation.app as unknown as Record<string, unknown>)['brand'];
    try {
      shadow.observeMissionNavigation(
        navigation as unknown as MissionNavigationObservation,
        workspace.captureRequestScope(),
      );
      assertSentinelObservationError(shadow);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('Sentinel observation with a primitive brand remains invalid and fail-closed', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([SENTINEL], 'sentinel-ci');
    const navigation = sentinelNavigationPayload();
    (navigation.app as unknown as Record<string, unknown>)['brand'] = 'invalid-brand';
    try {
      shadow.observeMissionNavigation(
        navigation as unknown as MissionNavigationObservation,
        workspace.captureRequestScope(),
      );
      assertSentinelObservationError(shadow);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('Octocity non-empty brand without style is compared as the Sentinel UI fallback', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([OCTOCITY], 'octocity-mission-room');
    const navigation = octocityNavigationPayload();
    (navigation.app as unknown as { brand: Record<string, unknown> }).brand = {
      label: 'Octocity Mission Room',
    };
    try {
      shadow.observeMissionNavigation(
        navigation as unknown as MissionNavigationObservation,
        workspace.captureRequestScope(),
      );
      const reports = shadow.reports().filter((item) =>
        item.workspaceSlug === 'octocity-mission-room',
      );
      assert.equal(reports.length, 2);
      assert.ok(reports.every((item) =>
        item.comparison?.status === 'unexplained_divergence',
      ));
      assert.ok(reports.every((item) => item.comparison?.diffs.some((diff) =>
        diff.path === '/missionRoom/brandStyle',
      )));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('Octocity contradictory brand label is retained only as a private fingerprint input', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([OCTOCITY], 'octocity-mission-room');
    const navigation = octocityNavigationPayload();
    const privateLabel = 'PRIVATE CONTRADICTORY BRAND';
    (navigation.app as unknown as { brand: Record<string, unknown> }).brand = {
      label: privateLabel,
      style: 'agentium',
    };
    try {
      shadow.observeMissionNavigation(
        navigation as unknown as MissionNavigationObservation,
        workspace.captureRequestScope(),
      );
      const reports = shadow.reports().filter((item) =>
        item.workspaceSlug === 'octocity-mission-room',
      );
      assert.ok(reports.every((item) => item.comparison?.diffs.some((diff) =>
        diff.path === '/missionRoom/label',
      )));
      assert.equal(JSON.stringify(reports).includes(privateLabel), false);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('Mission Room brand label/style fields fail closed when present with invalid types', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([OCTOCITY], 'octocity-mission-room');
    const navigation = octocityNavigationPayload();
    (navigation.app as unknown as { brand: unknown }).brand = {
      label: 'Octocity Mission Room',
      style: 42,
    };
    try {
      shadow.observeMissionNavigation(
        navigation as unknown as MissionNavigationObservation,
        workspace.captureRequestScope(),
      );
      const reports = shadow.reports().filter((item) =>
        item.workspaceSlug === 'octocity-mission-room',
      );
      assert.ok(reports.every((item) => item.comparison?.status === 'error'));
      assert.ok(reports.every((item) =>
        item.comparison?.legacyObservation === 'error',
      ));
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('Mission Room observation error is preserved as fail-closed evidence', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness([SENTINEL], 'sentinel-ci');
    const navigation = sentinelNavigationPayload() as ReturnType<typeof sentinelNavigationPayload> & {
      error?: unknown;
    };
    navigation.error = { code: 'upstream_unavailable' };
    try {
      shadow.observeMissionNavigation(
        navigation as unknown as MissionNavigationObservation,
        workspace.captureRequestScope(),
      );
      assertSentinelObservationError(shadow);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});

test('Mission Room payload with a slug inconsistent with its scope is ignored', () => {
  withMutedWarnings(() => {
    const { shadow, workspace } = createHarness();
    try {
      shadow.observeMissionNavigation({
        workspace: { slug: 'sentinel-ci' },
        app: { label: 'wrong tenant' },
        items: [{ key: 'cockpit' }],
      } as MissionNavigationObservation, workspace.captureRequestScope());
      assert.deepEqual(shadow.reports(), []);
    } finally {
      shadow.ngOnDestroy();
    }
  });
});
