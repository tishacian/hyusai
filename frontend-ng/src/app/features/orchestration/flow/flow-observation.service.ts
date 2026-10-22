/** Component-scoped, read-only execution browser for the Flow Builder.
 * There is deliberately no Run dispatch, persistence or editor-store dependency.
 */
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { AuthStore, type AuthenticationRequestScope } from '@app/store/auth.store';
import { STRICT } from '@app/shared/ui/load-state';
import {
  defaultObservationRun, hasObservedNodeResult, observationNodeSummaries,
  observeFlowNodes, protectObservationRun, recentObservationRuns,
  type FlowObservationRun,
} from './flow-observation.vm';

export type FlowObservationLoadState = 'idle' | 'loading' | 'ready' | 'error';
export type FlowObservationError = 'unavailable' | 'forbidden' | 'context' | null;
interface RequestContext {
  generation: number;
  systemId: string;
  workspace: WorkspaceRequestScope;
  principal: AuthenticationRequestScope;
}

@Injectable()
export class FlowObservationService {
  private readonly api = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly destroyRef = inject(DestroyRef);
  readonly enabled = signal(false);
  readonly systemId = signal<string | null>(null);
  /** Windows/pins must clear when this epoch changes; nothing is persisted. */
  readonly scopeEpoch = signal(0);
  /** Retain all revoked ids in this scope because Angular can coalesce several
   * synchronous notifications before a windows effect removes its pins. */
  readonly revocation = signal<{ runId: string; runIds: readonly string[]; events: Readonly<Record<string, number>>; epoch: number } | null>(null);
  readonly runs = signal<FlowObservationRun[]>([]);
  readonly listStatus = signal<FlowObservationLoadState>('idle');
  readonly listError = signal<FlowObservationError>(null);
  readonly detailStatus = signal<FlowObservationLoadState>('idle');
  readonly detailError = signal<FlowObservationError>(null);
  readonly error = computed(() => this.detailError() ?? this.listError());
  readonly selectedRunId = signal<string | null>(null);
  readonly currentRun = signal<FlowObservationRun | null>(null);
  readonly selectedNodeId = signal<string | null>(null);
  readonly selectedAttemptId = signal<string | null>(null);
  readonly nodes = computed(() => observeFlowNodes(this.currentRun()));
  readonly summaries = computed(() => observationNodeSummaries(this.nodes()));
  readonly currentNode = computed(() => {
    const id = this.selectedNodeId();
    return id ? this.nodes()[id] ?? null : null;
  });
  readonly currentAttempt = computed(() => {
    const node = this.currentNode();
    const selected = this.selectedAttemptId() ?? node?.preferredAttemptId;
    return node?.attempts.find(attempt => attempt.id === selected) ?? null;
  });
  readonly searchStatus = signal<'idle' | 'loading' | 'found' | 'not-found' | 'error'>('idle');
  readonly searchError = signal<FlowObservationError>(null);
  private generation = 0;
  private requests = new Subscription();
  private disposed = false;
  private readonly unregisterWorkspace: () => void;
  private readonly unregisterPrincipal: () => void;

  constructor() {
    this.unregisterWorkspace = this.workspace.registerContextReset(() => this.bindSystem(null));
    this.unregisterPrincipal = this.auth.registerContextReset(() => this.bindSystem(null));
    this.destroyRef.onDestroy(() => this.dispose());
  }

  bindSystem(systemId: string | null): void {
    if (this.disposed || this.systemId() === systemId && systemId !== null) return;
    this.invalidate();
    this.systemId.set(systemId);
    this.enabled.set(false);
    this.clearData();
    this.scopeEpoch.update(value => value + 1);
  }
  setSystem(systemId: string | null): void { this.bindSystem(systemId); }

  open(): void {
    if (this.disposed || !this.systemId()) return;
    this.enabled.set(true);
    if (this.listStatus() === 'idle') this.refresh();
  }
  close(): void {
    this.invalidate();
    this.enabled.set(false);
    this.clearData();
    this.scopeEpoch.update(value => value + 1);
  }

  refresh(preferredFlowSha256?: string | null): void {
    if (!this.enabled() || this.disposed || !this.systemId()) return;
    const preferredId = this.selectedRunId();
    this.invalidate();
    this.currentRun.set(null);
    this.selectedAttemptId.set(null);
    this.listStatus.set('loading');
    this.listError.set(null);
    this.detailStatus.set('idle');
    this.detailError.set(null);
    this.searchStatus.set('idle');
    const context = this.context();
    this.requests.add(this.api.listRuns({ system_id: context.systemId }).subscribe({
      next: values => {
        if (!this.current(context)) return;
        const runs = recentObservationRuns(values, context.systemId).map(protectObservationRun);
        for (const run of runs) if (run.result_held) this.revoke(run.id);
        this.runs.set(runs);
        this.listStatus.set('ready');
        const id = runs.some(run => run.id === preferredId) ? preferredId : defaultObservationRun(runs, preferredFlowSha256);
        if (id) this.selectRun(id);
        else this.selectedRunId.set(null);
      },
      error: error => {
        if (!this.current(context)) return;
        this.runs.set([]);
        this.selectedRunId.set(null);
        this.listStatus.set('error');
        this.listError.set(this.classifyError(error));
        if (this.denied(error)) this.scopeEpoch.update(value => value + 1);
      },
    }));
  }

  selectRun(runId: string): void {
    if (!this.enabled() || this.disposed || !this.systemId() || !runId.trim()) return;
    this.invalidate();
    if (this.listStatus() === 'loading') this.listStatus.set(this.runs().length ? 'ready' : 'idle');
    this.selectedRunId.set(runId);
    this.currentRun.set(null);
    this.selectedAttemptId.set(null);
    this.detailStatus.set('loading');
    this.detailError.set(null);
    this.searchStatus.set('idle');
    this.searchError.set(null);
    const context = this.context();
    this.requests.add(this.api.getRun(runId, STRICT).subscribe({
      next: value => {
        if (!this.current(context)) return;
        if (!value || value.id !== runId || value.system_id !== context.systemId) {
          this.revoke(runId);
          this.detailStatus.set('error'); this.detailError.set('unavailable'); return;
        }
        if ((value as FlowObservationRun).result_held) this.revoke(runId);
        this.currentRun.set(protectObservationRun(value));
        this.detailStatus.set('ready');
      },
      error: error => {
        if (!this.current(context)) return;
        if (this.denied(error)) this.revoke(runId);
        this.detailStatus.set('error'); this.detailError.set(this.classifyError(error));
      },
    }));
  }

  inspectNode(nodeId: string): void {
    if (this.searchStatus() === 'loading') this.invalidate();
    this.selectedNodeId.set(nodeId);
    this.selectedAttemptId.set(null);
    this.searchStatus.set('idle');
    this.searchError.set(null);
  }
  closeNode(): void {
    if (this.searchStatus() === 'loading') this.invalidate();
    this.selectedNodeId.set(null); this.selectedAttemptId.set(null);
    this.searchStatus.set('idle'); this.searchError.set(null);
  }
  selectAttempt(invocationId: string): void {
    if (this.currentNode()?.attempts.some(attempt => attempt.id === invocationId)) this.selectedAttemptId.set(invocationId);
  }

  /** Explicit bounded search. Switching Run replaces the entire observation
   * context; never blend this node's historical result into another Run.
   */
  findLatestForNode(nodeId: string): void {
    if (!this.enabled() || this.disposed || !this.systemId()) return;
    this.invalidate();
    if (this.detailStatus() === 'loading') this.detailStatus.set('idle');
    this.selectedNodeId.set(nodeId);
    this.selectedAttemptId.set(null);
    this.searchStatus.set('loading'); this.searchError.set(null);
    const context = this.context();
    const candidates = this.runs().filter(run => run.status === 'completed').slice(0, 10);
    let index = 0;
    const fail = (): void => { this.searchStatus.set('error'); this.searchError.set('unavailable'); };
    const next = (): void => {
      if (!this.current(context)) return;
      const candidate = candidates[index++];
      if (!candidate) { this.searchStatus.set('not-found'); return; }
      this.requests.add(this.api.getRun(candidate.id, STRICT).subscribe({
        next: value => {
          if (!this.current(context)) return;
          if (!value || value.id !== candidate.id || value.system_id !== context.systemId) { this.revoke(candidate.id); fail(); return; }
          const run = protectObservationRun(value);
          if (run.result_held) this.revoke(run.id);
          if (!hasObservedNodeResult(run, nodeId)) { next(); return; }
          this.selectedRunId.set(run.id);
          this.currentRun.set(run);
          this.selectedAttemptId.set(null);
          this.detailStatus.set('ready'); this.detailError.set(null);
          this.searchStatus.set('found');
        },
        // A failed newer read cannot certify that an older result is latest.
        error: error => { if (this.current(context)) { if (this.denied(error)) this.revoke(candidate.id); fail(); } },
      }));
    };
    next();
  }

  dispose(): void {
    if (this.disposed) return;
    this.close(); this.systemId.set(null); this.disposed = true;
    this.unregisterWorkspace(); this.unregisterPrincipal();
  }
  private context(): RequestContext {
    return { generation: this.generation, systemId: this.systemId()!, workspace: this.workspace.captureRequestScope(), principal: this.auth.captureRequestScope() };
  }
  private current(context: RequestContext): boolean {
    return !this.disposed && this.enabled() && this.generation === context.generation && this.systemId() === context.systemId
      && this.workspace.isRequestScopeCurrent(context.workspace) && this.auth.isRequestScopeCurrent(context.principal);
  }
  private invalidate(): void {
    this.generation += 1; this.requests.unsubscribe(); this.requests = new Subscription();
  }
  private clearData(): void {
    this.runs.set([]); this.selectedRunId.set(null); this.currentRun.set(null);
    this.selectedNodeId.set(null); this.selectedAttemptId.set(null);
    this.listStatus.set('idle'); this.detailStatus.set('idle'); this.listError.set(null); this.detailError.set(null);
    this.searchStatus.set('idle'); this.searchError.set(null);
    this.revocation.set(null);
  }
  private revoke(runId: string): void {
    const previous = this.revocation();
    const epoch = (previous?.epoch ?? 0) + 1;
    this.revocation.set({ runId, runIds: [...new Set([...(previous?.runIds ?? []), runId])], events: { ...previous?.events, [runId]: epoch }, epoch });
  }
  private denied(error: unknown): boolean {
    const status = typeof error === 'object' && error !== null && 'status' in error ? error.status : null;
    return status === 401 || status === 403 || status === 404;
  }
  private classifyError(error: unknown): FlowObservationError {
    const status = typeof error === 'object' && error !== null && 'status' in error ? error.status : null;
    return status === 401 || status === 403 ? 'forbidden' : 'unavailable';
  }
}
