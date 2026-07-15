import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import type { NavigationRedirectDecision } from './navigation-telemetry.service';
import { privacySafeNavigationRoute } from './navigation-telemetry.service';
import { NavigationProfileService } from './navigation-profile.service';
import {
  WORKSPACE_EXPERIENCE_CRITICAL_SCENARIOS,
  WORKSPACE_EXPERIENCE_EVIDENCE_SCHEMA_VERSION,
  WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
  compareWorkspaceExperienceWithMissionNavigation,
  compareWorkspaceExperiences,
  createWorkspaceExperienceEvidence,
  evaluateWorkspaceExperienceRolloutGate,
  workspaceExperienceFingerprint,
  workspaceExperienceScenarioKey,
  type MissionNavigationObservation,
  type WorkspaceExperienceComparison,
  type WorkspaceExperienceEvidence,
  type WorkspaceExperienceInput,
} from './workspace-experience';
import {
  WorkspaceService,
  type WorkspaceInfo,
  type WorkspaceRequestScope,
} from './workspace.service';

interface ObservedNavigation {
  readonly requestedRoute: string;
  readonly legacyDecision: SanitizedLegacyDecision | null;
  readonly workspaceSlug: string | null;
  readonly workspaceEpoch: number;
}

type SanitizedLegacyDecision = Pick<
  NavigationRedirectDecision,
  'requestedRoute' | 'resolvedRoute' | 'reason'
> & {
  readonly semanticQueryKeys: readonly string[];
  readonly workspaceTargetMatchesCurrent: boolean | null;
  readonly semanticTargetPreserved: boolean | null;
};

type ShadowEvidenceProvenance =
  | 'synthetic_projection'
  | 'mission_navigation_observed'
  | 'runtime_navigation_observed';

interface EvaluatedWorkspaceEvidence {
  readonly evidence: WorkspaceExperienceEvidence;
  readonly configFingerprint: string | null;
  readonly provenance: ShadowEvidenceProvenance;
}

interface SealedWorkspaceEvidence {
  readonly evidence: WorkspaceExperienceEvidence;
  readonly configFingerprint: string;
  readonly provenance: ShadowEvidenceProvenance;
}

interface ScopedMissionObservation {
  readonly observation: MissionNavigationObservation;
  readonly workspaceSlug: string;
  readonly workspaceId: string;
  readonly workspaceEpoch: number;
  readonly configFingerprint: string;
}

/**
 * Passive runtime harness for the Lot 2 workspace-experience resolver.
 *
 * It compares V2 with the already-executed legacy behavior and exposes only
 * in-memory evidence. It never navigates, writes storage, calls the backend,
 * or replaces a Mission Room payload.
 */
@Injectable({ providedIn: 'root' })
export class WorkspaceExperienceShadowService implements OnDestroy {
  private readonly workspace = inject(WorkspaceService);
  private readonly navigationProfile = inject(NavigationProfileService);
  private readonly reportsState = signal<readonly WorkspaceExperienceEvidence[]>([]);
  private readonly sealedEvidenceState = signal<readonly SealedWorkspaceEvidence[]>([]);
  private readonly missionObservations = new Map<string, ScopedMissionObservation>();
  private readonly loggedFingerprints = new Set<string>();
  private lastNavigation: ObservedNavigation | null = null;
  private readonly unregisterContextReset: () => void;

  readonly reports = this.reportsState.asReadonly();
  readonly gate = computed(() => evaluateWorkspaceExperienceRolloutGate(
    this.validSealedEvidence().map((item) => item.evidence),
  ));

  constructor() {
    this.unregisterContextReset = this.workspace.registerContextReset(() => {
      // The reset callback runs synchronously before WorkspaceService publishes
      // the new slug/epoch. Clear every tenant-derived value in one turn.
      this.lastNavigation = null;
      this.missionObservations.clear();
      this.loggedFingerprints.clear();
      this.reportsState.set(Object.freeze([]));
    });
  }

  ngOnDestroy(): void {
    this.unregisterContextReset();
  }

  observeNavigation(
    requestedRoute: string,
    legacyDecision: NavigationRedirectDecision | null,
  ): void {
    try {
      const safeRoute = privacySafeNavigationRoute(requestedRoute);
      this.lastNavigation = Object.freeze({
        requestedRoute: safeRoute,
        legacyDecision: this.sanitizeLegacyDecision(safeRoute, legacyDecision),
        workspaceSlug: this.workspace.currentSlug(),
        workspaceEpoch: this.workspace.contextEpoch(),
      });
      this.publishEvaluation(this.evaluateReports(this.lastNavigation));
    } catch {
      this.recordUnexpectedFailure(requestedRoute);
    }
  }

  observeMissionNavigation(
    navigation: MissionNavigationObservation,
    scope: WorkspaceRequestScope,
  ): void {
    try {
      if (!scope.workspaceSlug || !this.workspace.isRequestScopeCurrent(scope)) return;
      const payloadWorkspace = this.missionNavigationWorkspaceIdentity(navigation);
      if (payloadWorkspace.slug && payloadWorkspace.slug !== scope.workspaceSlug) return;
      const currentWorkspace = this.workspace.current();
      if (!currentWorkspace || currentWorkspace.slug !== scope.workspaceSlug) return;
      if (payloadWorkspace.id && currentWorkspace?.id !== payloadWorkspace.id) return;
      this.missionObservations.set(
        scope.workspaceSlug,
        Object.freeze({
          observation: this.sanitizeMissionObservation(navigation),
          workspaceSlug: scope.workspaceSlug,
          workspaceId: currentWorkspace.id,
          workspaceEpoch: scope.epoch,
          configFingerprint: this.workspaceConfigFingerprint(currentWorkspace),
        }),
      );

      // Re-check immediately before publishing. A synchronous context reset
      // between observation and evaluation must not resurrect tenant A.
      if (!this.workspace.isRequestScopeCurrent(scope)) {
        this.missionObservations.delete(scope.workspaceSlug);
        return;
      }
      this.publishEvaluation(this.evaluateReports(this.currentObservedNavigation(scope)));
    } catch {
      if (this.workspace.isRequestScopeCurrent(scope)) {
        this.recordUnexpectedFailure(this.lastNavigation?.requestedRoute || '/hypervisor/mission-room');
      }
    }
  }

  /** Best-effort blocking evidence for a failure beyond the service boundary. */
  recordUnexpectedFailure(requestedRoute: string): void {
    try {
      const current = this.workspace.current();
      if (!current) return;
      const epoch = this.workspace.contextEpoch();
      const input = this.runtimeInput(
        current,
        privacySafeNavigationRoute(requestedRoute),
      );
      const evidence = this.errorEvidence(input, 'shadow_runtime_failure', epoch);
      this.publishReports(this.upsertEvidence(this.reportsState(), evidence));
      this.sealEvaluations([{
        evidence,
        configFingerprint: this.workspaceConfigFingerprint(current),
        provenance: 'runtime_navigation_observed',
      }]);
    } catch {
      // Shadow instrumentation is strictly non-blocking. There is no safe
      // fallback left if even workspace identity cannot be read.
    }
  }

  private evaluateReports(observedNavigation: ObservedNavigation | null): EvaluatedWorkspaceEvidence[] {
    const epoch = this.workspace.contextEpoch();
    const runtimeWorkspaces = this.workspace.workspaces();
    const evaluated: EvaluatedWorkspaceEvidence[] = [];

    for (const critical of WORKSPACE_EXPERIENCE_CRITICAL_SCENARIOS) {
      const runtimeWorkspace = runtimeWorkspaces.find(
        (item) => item.slug === critical.input.workspace.slug,
      );
      if (!runtimeWorkspace) {
        evaluated.push({
          evidence: this.errorEvidence(
            critical.input,
            'workspace_missing_from_runtime_list',
            epoch,
          ),
          configFingerprint: null,
          provenance: 'synthetic_projection',
        });
        continue;
      }

      const input: WorkspaceExperienceInput = {
        workspace: {
          slug: runtimeWorkspace.slug,
          mode: runtimeWorkspace.mode,
          settings: runtimeWorkspace.settings,
          appEntitlements: runtimeWorkspace.app_entitlements,
        },
        scenario: { ...critical.input.scenario },
      };
      const missionObservation = this.validMissionObservation(runtimeWorkspace, epoch);
      evaluated.push({
        evidence: this.compareSafely(input, epoch, undefined, missionObservation),
        configFingerprint: this.workspaceConfigFingerprint(runtimeWorkspace),
        provenance: missionObservation
          ? 'mission_navigation_observed'
          : 'synthetic_projection',
      });
    }

    const current = this.workspace.current();
    if (
      current
      && observedNavigation
      && observedNavigation.workspaceSlug === current.slug
      && observedNavigation.workspaceEpoch === epoch
    ) {
      const actualInput = this.runtimeInput(current, observedNavigation.requestedRoute);
      const missionObservation = this.validMissionObservation(current, epoch);
      evaluated.push({
        evidence: this.compareSafely(
          actualInput,
          epoch,
          observedNavigation.legacyDecision,
          missionObservation,
        ),
        configFingerprint: this.workspaceConfigFingerprint(current),
        provenance: 'runtime_navigation_observed',
      });
    }

    return this.dedupeEvaluations(evaluated);
  }

  private compareSafely(
    input: WorkspaceExperienceInput,
    epoch: number,
    legacyDecision?: SanitizedLegacyDecision | null,
    observation?: MissionNavigationObservation,
  ): WorkspaceExperienceEvidence {
    try {
      let comparison: WorkspaceExperienceComparison;
      if (legacyDecision !== undefined) {
        comparison = observation
          ? compareWorkspaceExperienceWithMissionNavigation(input, observation, {
            observedLegacyRouteDecision: legacyDecision,
          })
          : compareWorkspaceExperiences(input, {
            observedLegacyRouteDecision: legacyDecision,
          });
      } else if (observation) {
        comparison = compareWorkspaceExperienceWithMissionNavigation(input, observation);
      } else {
        comparison = compareWorkspaceExperiences(input);
      }
      return createWorkspaceExperienceEvidence(input, comparison, epoch, epoch);
    } catch {
      return this.errorEvidence(input, 'comparison_failed', epoch);
    }
  }

  private validMissionObservation(
    workspace: WorkspaceInfo,
    epoch: number,
  ): MissionNavigationObservation | undefined {
    const scoped = this.missionObservations.get(workspace.slug);
    if (!scoped) return undefined;
    const valid = scoped.workspaceSlug === workspace.slug
      && scoped.workspaceId === workspace.id
      && scoped.workspaceEpoch === epoch
      && scoped.configFingerprint === this.workspaceConfigFingerprint(workspace);
    if (valid) return scoped.observation;
    // Same-slug membership refreshes do not necessarily bump the context
    // epoch. Drop the raw payload immediately so it cannot be resealed under
    // a recreated workspace id or a changed configuration fingerprint.
    this.missionObservations.delete(workspace.slug);
    return undefined;
  }

  private runtimeInput(workspace: WorkspaceInfo, requestedRoute: string): WorkspaceExperienceInput {
    return {
      workspace: {
        slug: workspace.slug,
        mode: workspace.mode,
        settings: workspace.settings,
        appEntitlements: workspace.app_entitlements,
      },
      scenario: {
        role: workspace.role,
        roleTemplate: workspace.role_template,
        businessPreview: this.navigationProfile.effective().preview,
        requestedRoute,
      },
    };
  }

  private currentObservedNavigation(scope: WorkspaceRequestScope): ObservedNavigation | null {
    const observed = this.lastNavigation;
    return observed
      && observed.workspaceSlug === scope.workspaceSlug
      && observed.workspaceEpoch === scope.epoch
      ? observed
      : null;
  }

  private sanitizeLegacyDecision(
    requestedRoute: string,
    decision: NavigationRedirectDecision | null,
  ): SanitizedLegacyDecision | null {
    if (!decision) return null;
    // Extract allowlisted semantic presence while the raw query still exists.
    // The value itself is never copied into shadow state or evidence.
    const semanticQueryKeys = this.extractSemanticQueryKeys(decision.resolvedRoute);
    return Object.freeze({
      requestedRoute,
      resolvedRoute: privacySafeNavigationRoute(decision.resolvedRoute),
      reason: decision.reason,
      semanticQueryKeys,
      workspaceTargetMatchesCurrent: this.workspaceTargetMatchesCurrent(decision),
      semanticTargetPreserved: this.semanticTargetPreserved(decision),
    });
  }

  private workspaceTargetMatchesCurrent(
    decision: NavigationRedirectDecision,
  ): boolean | null {
    if (decision.reason !== 'workspace_settings_entrypoint') return null;
    const match = this.pathOnly(decision.resolvedRoute).match(/^\/workspace\/([^/]+)(?:\/|$)/);
    if (!match?.[1]) return false;
    try {
      return decodeURIComponent(match[1]) === this.workspace.currentSlug();
    } catch {
      return false;
    }
  }

  private semanticTargetPreserved(
    decision: NavigationRedirectDecision,
  ): boolean | null {
    if (decision.reason !== 'business_system_capture_compatibility') return null;
    const requested = this.pathOnly(decision.requestedRoute).match(
      /^\/systems\/([^/]+)\/capture$/,
    );
    if (!requested?.[1]) return false;
    let requestedSystemId: string;
    try {
      requestedSystemId = decodeURIComponent(requested[1]);
    } catch {
      requestedSystemId = requested[1];
    }
    const queryStart = decision.resolvedRoute.indexOf('?');
    if (queryStart < 0) return false;
    const fragmentStart = decision.resolvedRoute.indexOf('#', queryStart + 1);
    const query = decision.resolvedRoute.slice(
      queryStart + 1,
      fragmentStart < 0 ? decision.resolvedRoute.length : fragmentStart,
    );
    return new URLSearchParams(query).get('systemId') === requestedSystemId;
  }

  private pathOnly(route: string): string {
    return (route || '/').split('?')[0].split('#')[0] || '/';
  }

  private extractSemanticQueryKeys(resolvedRoute: string): readonly string[] {
    const queryStart = resolvedRoute.indexOf('?');
    if (queryStart < 0) return Object.freeze([]);
    const fragmentStart = resolvedRoute.indexOf('#', queryStart + 1);
    const query = resolvedRoute.slice(
      queryStart + 1,
      fragmentStart < 0 ? resolvedRoute.length : fragmentStart,
    );
    const keys = new URLSearchParams(query).has('systemId') ? ['systemId'] : [];
    return Object.freeze(keys);
  }

  private sanitizeMissionObservation(
    navigation: MissionNavigationObservation,
  ): MissionNavigationObservation {
    const rawApp = this.record(navigation?.app);
    const rawBrand = rawApp['brand'];
    let brand: unknown = rawBrand;
    let brandHasFields: boolean | undefined;
    if (this.isRecord(rawBrand)) {
      const comparedBrand: Record<string, unknown> = {};
      if (Object.prototype.hasOwnProperty.call(rawBrand, 'label')) {
        comparedBrand['label'] = rawBrand['label'];
      }
      if (Object.prototype.hasOwnProperty.call(rawBrand, 'style')) {
        comparedBrand['style'] = rawBrand['style'];
      }
      brand = Object.freeze(comparedBrand);
      // MissionRoomComponent treats any non-empty API brand object as
      // authoritative, including one containing only lines/emblem/unknown
      // future fields. Preserve that fact without copying their values.
      brandHasFields = Object.keys(rawBrand).length > 0;
    }
    const app: Record<string, unknown> = {
      label: rawApp['label'],
      assistant_label: rawApp['assistant_label'],
      assistant_profile: rawApp['assistant_profile'],
      shell: rawApp['shell'],
      default_route: rawApp['default_route'],
      default_view: rawApp['default_view'],
      profile: rawApp['profile'],
      // Absence/null/primitives are kept invalid so core validation remains
      // fail-closed. Only a real object is reduced to the compared field.
      brand,
    };
    const items = Array.isArray(navigation?.items)
      ? navigation.items.map((item) => ({ key: this.record(item)['key'] }))
      : navigation?.items === null
        ? null
        : undefined;
    return Object.freeze({
      app: Object.freeze(app) as MissionNavigationObservation['app'],
      items: items ? Object.freeze(items.map((item) => Object.freeze(item))) : items,
      error: navigation?.error,
      brandHasFields,
    });
  }

  private missionNavigationWorkspaceIdentity(
    navigation: MissionNavigationObservation,
  ): { readonly id: string | null; readonly slug: string | null } {
    const workspace = this.record(
      (navigation as MissionNavigationObservation & { workspace?: unknown }).workspace,
    );
    return {
      id: typeof workspace['id'] === 'string' ? workspace['id'] : null,
      slug: typeof workspace['slug'] === 'string' ? workspace['slug'] : null,
    };
  }

  private errorEvidence(
    input: WorkspaceExperienceInput,
    errorCode: string,
    epoch: number,
  ): WorkspaceExperienceEvidence {
    return Object.freeze({
      evidenceSchemaVersion: WORKSPACE_EXPERIENCE_EVIDENCE_SCHEMA_VERSION,
      resolverVersion: WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
      workspaceSlug: input.workspace.slug,
      scenarioKey: workspaceExperienceScenarioKey(input.scenario),
      workspaceEpoch: epoch,
      currentWorkspaceEpoch: epoch,
      errorCode,
    });
  }

  private publishEvaluation(evaluated: readonly EvaluatedWorkspaceEvidence[]): void {
    this.publishReports(evaluated.map((item) => item.evidence));
    this.sealEvaluations(evaluated);
  }

  private publishReports(reports: readonly WorkspaceExperienceEvidence[]): void {
    const next = Object.freeze([...reports]);
    this.reportsState.set(next);
    for (const evidence of next) this.logBlockingSummary(evidence);
  }

  private logBlockingSummary(evidence: WorkspaceExperienceEvidence): void {
    const comparison = evidence.comparison;
    if (!evidence.errorCode && comparison?.status === 'match') return;
    const codes = evidence.errorCode
      ? [evidence.errorCode]
      : [
        ...(comparison?.candidateIssues.map((item) => item.code) || []),
        ...(comparison?.diffs.map((item) => item.code) || []),
      ];
    const fingerprint = comparison?.fingerprint || workspaceExperienceFingerprint({
      scenarioKey: evidence.scenarioKey,
      codes,
    });
    const logKey = `${comparison?.status || 'error'}:${fingerprint}`;
    if (this.loggedFingerprints.has(logKey)) return;
    this.loggedFingerprints.add(logKey);
    console.warn('[workspace-experience-shadow]', {
      status: comparison?.status || 'error',
      codes: [...new Set(codes)].sort(),
      fingerprint,
    });
  }

  private sealEvaluations(evaluated: readonly EvaluatedWorkspaceEvidence[]): void {
    const liveFingerprints = this.liveWorkspaceConfigFingerprints();
    const next = new Map<string, SealedWorkspaceEvidence>();

    // Prune evidence immediately when its workspace disappears or its runtime
    // config changes. The computed gate repeats this filter reactively so a
    // refresh invalidates proofs even before another shadow observation.
    for (const sealed of this.sealedEvidenceState()) {
      if (liveFingerprints.get(sealed.evidence.workspaceSlug) !== sealed.configFingerprint) continue;
      next.set(this.evidenceKey(sealed.evidence), sealed);
    }

    for (const item of evaluated) {
      if (!item.configFingerprint) continue;
      if (liveFingerprints.get(item.evidence.workspaceSlug) !== item.configFingerprint) continue;
      const sealed: SealedWorkspaceEvidence = Object.freeze({
        evidence: this.sealEvidence(item.evidence),
        configFingerprint: item.configFingerprint,
        provenance: item.provenance,
      });
      const key = this.evidenceKey(sealed.evidence);
      const existing = next.get(key);
      if (!existing || this.shouldReplaceSealedEvidence(existing, sealed)) {
        next.set(key, sealed);
      }
    }

    this.sealedEvidenceState.set(Object.freeze([...next.values()]));
  }

  private validSealedEvidence(): SealedWorkspaceEvidence[] {
    const liveFingerprints = this.liveWorkspaceConfigFingerprints();
    return this.sealedEvidenceState().filter((item) =>
      liveFingerprints.get(item.evidence.workspaceSlug) === item.configFingerprint,
    );
  }

  private shouldReplaceSealedEvidence(
    existing: SealedWorkspaceEvidence,
    incoming: SealedWorkspaceEvidence,
  ): boolean {
    if (existing.configFingerprint !== incoming.configFingerprint) return true;
    if (existing.provenance === incoming.provenance) return true;

    // A real runtime divergence remains authoritative until another runtime
    // decision for the same scenario supersedes it. A synthetic projection
    // must never make the rollout gate look greener than observed behavior.
    if (
      existing.provenance === 'runtime_navigation_observed'
      && this.isBlockingEvidence(existing.evidence)
      && incoming.provenance !== 'runtime_navigation_observed'
    ) return false;

    return this.evidenceQuality(incoming) >= this.evidenceQuality(existing);
  }

  private evidenceQuality(item: SealedWorkspaceEvidence): number {
    const blocking = this.isBlockingEvidence(item.evidence);
    if (blocking) {
      if (item.provenance === 'runtime_navigation_observed') return 100;
      if (item.provenance === 'mission_navigation_observed') return 80;
      return 60;
    }

    const requiresMissionObservation = WORKSPACE_EXPERIENCE_CRITICAL_SCENARIOS.some(
      (critical) => critical.requiresMissionNavigationObservation
        && critical.input.workspace.slug === item.evidence.workspaceSlug
        && workspaceExperienceScenarioKey(critical.input.scenario) === item.evidence.scenarioKey,
    );
    if (requiresMissionObservation) {
      const observed = item.evidence.comparison?.legacyObservation === 'observed';
      if (observed && item.provenance === 'runtime_navigation_observed') return 50;
      if (observed && item.provenance === 'mission_navigation_observed') return 40;
      if (observed) return 30;
      if (item.provenance === 'runtime_navigation_observed') return 20;
      if (item.provenance === 'mission_navigation_observed') return 15;
      return 10;
    }

    if (item.provenance === 'runtime_navigation_observed') return 50;
    if (item.provenance === 'mission_navigation_observed') return 40;
    return 30;
  }

  private isBlockingEvidence(evidence: WorkspaceExperienceEvidence): boolean {
    return Boolean(
      evidence.errorCode
      || !evidence.comparison
      || evidence.comparison.status === 'error'
      || evidence.comparison.status === 'unexplained_divergence',
    );
  }

  private sealEvidence(evidence: WorkspaceExperienceEvidence): WorkspaceExperienceEvidence {
    const comparison = evidence.comparison ? {
      ...evidence.comparison,
      diffs: evidence.comparison.diffs.map((item) => ({
        path: item.path,
        code: item.code,
      })),
      candidateIssues: evidence.comparison.candidateIssues.map((item) => ({
        kind: item.kind,
        code: item.code,
        path: item.path,
      })),
    } : undefined;
    return Object.freeze({
      evidenceSchemaVersion: evidence.evidenceSchemaVersion,
      resolverVersion: evidence.resolverVersion,
      workspaceSlug: evidence.workspaceSlug,
      scenarioKey: evidence.scenarioKey,
      workspaceEpoch: evidence.workspaceEpoch,
      currentWorkspaceEpoch: evidence.currentWorkspaceEpoch,
      comparison,
      errorCode: evidence.errorCode,
    });
  }

  private liveWorkspaceConfigFingerprints(): Map<string, string> {
    return new Map(this.workspace.workspaces().map((workspace) => [
      workspace.slug,
      this.workspaceConfigFingerprint(workspace),
    ]));
  }

  private workspaceConfigFingerprint(workspace: WorkspaceInfo): string {
    return workspaceExperienceFingerprint({
      resolverVersion: WORKSPACE_EXPERIENCE_RESOLVER_VERSION,
      workspace: {
        id: workspace.id,
        slug: workspace.slug,
        mode: workspace.mode ?? null,
        settings: workspace.settings ?? null,
        appEntitlements: workspace.app_entitlements ?? null,
      },
    });
  }

  private evidenceKey(evidence: WorkspaceExperienceEvidence): string {
    return `${evidence.workspaceSlug}::${evidence.scenarioKey}`;
  }

  private dedupeEvidence(
    evidence: readonly WorkspaceExperienceEvidence[],
  ): WorkspaceExperienceEvidence[] {
    const byScenario = new Map<string, WorkspaceExperienceEvidence>();
    for (const item of evidence) {
      byScenario.set(`${item.workspaceSlug}::${item.scenarioKey}`, item);
    }
    return [...byScenario.values()];
  }

  private dedupeEvaluations(
    evaluated: readonly EvaluatedWorkspaceEvidence[],
  ): EvaluatedWorkspaceEvidence[] {
    const byScenario = new Map<string, EvaluatedWorkspaceEvidence>();
    for (const item of evaluated) {
      byScenario.set(this.evidenceKey(item.evidence), item);
    }
    return [...byScenario.values()];
  }

  private upsertEvidence(
    evidence: readonly WorkspaceExperienceEvidence[],
    next: WorkspaceExperienceEvidence,
  ): WorkspaceExperienceEvidence[] {
    return this.dedupeEvidence([...evidence, next]);
  }

  private record(value: unknown): Readonly<Record<string, unknown>> {
    return this.isRecord(value)
      ? value as Readonly<Record<string, unknown>>
      : {};
  }

  private isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }
}
