/**
 * `FlowRunService` — the run / debug / replay orchestrator (component-scoped).
 *
 * Restored from the deleted `workflow-editor.component.ts` monolith, but
 * extracted into a single focused service so NO component owns run state. It
 * is provided by `FlowBuilderComponent` (NOT `providedIn: 'root'`), so the
 * shell, the projected run-controls, the bottom terminal and every node share
 * exactly ONE instance and one set of signals.
 *
 * Responsibilities:
 *   - Validate `store.snapshot()` through the serializer BEFORE launching.
 *   - Trigger real runs through the single `triggerRun` contract, then stream events
 *     over SSE (`RunStreamService`) with a transparent fallback to polling.
 *   - Resolve HITL gates and drive the step-debugger (step / continue / stop).
 *   - Hold the breakpoint set + debug mode HERE (never in the CanonicalFlow).
 *   - Client-side `simulate()` (no backend) and checkpoint `replayRun()`.
 *
 * It owns NO graph state — it reads/validates via `FlowStore` + serializer
 * only, and surfaces everything else as signals the UI renders. It is also
 * toast-free and effect-free so it stays trivially unit-testable through a
 * bare `Injector` with mocked `CanonicalApiService` / `RunStreamService`.
 */
import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Subscription, timer } from 'rxjs';
import { switchMap, takeWhile } from 'rxjs/operators';
import {
  CanonicalApiService,
  type Run,
  type RunDebugPayload,
  type RunHitlPayload,
  type RunTriggerRequest,
} from '@app/core/canonical-api.service';
import {
  RunStreamService,
  type RunStreamEvent,
} from '@app/core/run-stream.service';
import {
  FlowSerializerService,
  type CanonicalFlow,
  type CanonicalFlowNode,
} from '@app/core/flow-serializer.service';
import {
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { type I18nKey } from '@app/core/i18n.dict';
import { FlowStore } from './flow.store';
import {
  FlowManifestService,
  runtimeModeKey,
} from './flow-manifest.service';
import { FlowPersistenceService } from './flow-persistence.service';
import { readNodeRunSummary, type NodeRunSummary } from './flow-node-run.vm';
import type { DebugMode, RunLogEntry, RunUiStatus } from './flow-run.types';

/** Cap so a chatty run can never grow the terminal unbounded. */
const LOG_LIMIT = 200;
/** Polling cadence used only when the SSE stream drops. */
const POLL_INTERVAL_MS = 1500;

export type RunInputParseResult =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; messageKey: I18nKey };

/** Parse the operator input without persisting or normalising it into the
 * Flow. `_debug` is service-owned and cannot be smuggled through the editor. */
export function parseRunInputRef(text: string): RunInputParseResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, messageKey: 'flow.run.input.error.json' };
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, messageKey: 'flow.run.input.error.object' };
  }
  if (Object.prototype.hasOwnProperty.call(parsed, '_debug')) {
    return { ok: false, messageKey: 'flow.run.input.error.debug_reserved' };
  }
  return { ok: true, value: parsed as Record<string, unknown> };
}

export type DraftTestIngressKind = 'manual' | 'chat' | 'http' | 'schedule' | 'event';

export interface DraftTestIngressSelection {
  ingress_id: string;
  kind: DraftTestIngressKind;
}

export interface DraftTestIngressOption extends DraftTestIngressSelection {
  label: string;
}

const DRAFT_INGRESS_KINDS = new Set<DraftTestIngressKind>([
  'manual',
  'chat',
  'http',
  'schedule',
  'event',
]);

function draftIngressKind(node: CanonicalFlowNode): DraftTestIngressKind | null {
  if (node.kind !== 'source') return null;
  const config = node.config as Record<string, unknown> | undefined;
  const explicit = config?.['ingress_kind'];
  if (typeof explicit === 'string' && DRAFT_INGRESS_KINDS.has(explicit as DraftTestIngressKind)) {
    return explicit as DraftTestIngressKind;
  }
  if (node.type === 'source.webhook') return 'http';
  if (node.type === 'source.schedule') return 'schedule';
  if (node.type === 'input' && node.id === 'source.request') return 'chat';
  if (node.type.startsWith('source.')) return 'event';
  return 'manual';
}

/** Enumerate every executable draft entry point in stable graph order. */
export function draftTestIngressOptions(
  flow: CanonicalFlow,
): DraftTestIngressOption[] {
  return flow.nodes.flatMap((node) => {
    const kind = draftIngressKind(node);
    return kind
      ? [{ ingress_id: node.id, kind, label: node.label?.trim() || node.id }]
      : [];
  });
}

/** Resolve an explicit Builder entry point. With no explicit id, only a Flow
 * with exactly one ingress is unambiguous; multiple ingresses must be chosen
 * by the operator in the input dialog. */
export function selectDraftTestIngress(
  flow: CanonicalFlow,
  ingressId?: string,
): DraftTestIngressSelection | null {
  const candidates = draftTestIngressOptions(flow);
  const selected = ingressId
    ? candidates.find((candidate) => candidate.ingress_id === ingressId)
    : candidates.length === 1
      ? candidates[0]
      : null;
  return selected ? { ingress_id: selected.ingress_id, kind: selected.kind } : null;
}

@Injectable()
export class FlowRunService {
  private readonly store = inject(FlowStore);
  private readonly canonical = inject(CanonicalApiService);
  private readonly runStream = inject(RunStreamService);
  private readonly serializer = inject(FlowSerializerService);
  private readonly persistence = inject(FlowPersistenceService);
  private readonly manifest = inject(FlowManifestService);
  private readonly workspace = inject(WorkspaceService, { optional: true });
  private readonly i18n = inject(I18nService);

  // ---- shared UI state (signals) ------------------------------------------
  /** The System this builder is bound to, or `null` on the scratchpad. */
  readonly systemId = signal<string | null>(null);
  readonly status = signal<RunUiStatus>('idle');
  readonly log = signal<RunLogEntry[]>([]);
  readonly currentRun = signal<Run | null>(null);
  readonly executing = signal(false);
  readonly hitlResolving = signal(false);
  readonly debugStepping = signal(false);
  readonly terminalOpen = signal(false);

  /** Component-scoped, ephemeral input editor state. It is intentionally
   * never copied into localStorage or the canonical Flow. */
  readonly inputEditorOpen = signal(false);
  readonly inputText = signal('{}');
  readonly dispatchError = signal<string | null>(null);
  readonly selectedDraftIngressId = signal('');
  readonly inputValidationError = computed(() => {
    const parsed = parseRunInputRef(this.inputText());
    return parsed.ok ? null : this.i18n.t(parsed.messageKey);
  });

  readonly debugMode = signal<DebugMode>('off');
  private readonly _breakpoints = signal<string[]>([]);
  readonly breakpoints = this._breakpoints.asReadonly();

  readonly runtimeMode = computed(() =>
    this.persistence.publicationMode()
      ? this.persistence.serverValidation()?.runtime_mode ?? null
      : this.manifest.runtimeMode(),
  );
  readonly runtimeModeLabel = computed(() =>
    this.i18n.t(runtimeModeKey(this.runtimeMode())),
  );
  readonly executionSurfaceLabel = computed(() =>
    this.i18n.t(
      this.persistence.publicationMode()
        ? 'flow.runtime.surface.draft'
        : 'flow.runtime.surface.published',
    ),
  );
  readonly draftTestMode = computed(() => this.persistence.publicationMode());
  readonly draftTestIngresses = computed(() =>
    draftTestIngressOptions(this.store.snapshot()),
  );
  readonly selectedDraftTestIngress = computed(() =>
    selectDraftTestIngress(this.store.snapshot(), this.selectedDraftIngressId()),
  );
  readonly draftIngressSelectionError = computed(() => {
    if (!this.draftTestMode()) return null;
    const candidates = this.draftTestIngresses();
    if (candidates.length === 0) {
      return this.i18n.t('flow.run.entry.none');
    }
    if (!this.selectedDraftTestIngress()) {
      return candidates.length === 1
        ? this.i18n.t('flow.run.entry.select')
        : this.i18n.t('flow.run.entry.choose', { count: candidates.length });
    }
    return null;
  });

  /** Node currently executing / paused on — drives the canvas run overlay. */
  readonly activeNodeId = signal<string | null>(null);

  /**
   * What each node did on its last execution, keyed by node id.
   *
   * Fed from the `node_end` frames — live over SSE, and by the same replay that
   * fills the terminal when a finished run is loaded — so the canvas badges are
   * populated whether you watched the run or opened it afterwards. Ephemeral by
   * design: this is evidence about a run, never part of the graph, so it is
   * neither saved nor allowed to dirty the flow.
   */
  private readonly _nodeRuns = signal<Record<string, NodeRunSummary>>({});
  readonly nodeRuns = this._nodeRuns.asReadonly();

  nodeRunFor(nodeId: string): NodeRunSummary | null {
    return this._nodeRuns()[nodeId] ?? null;
  }

  /** Versions are per-System but do not require an executable runtime. */
  readonly canUseSystemActions = computed(
    () =>
      this.systemId() !== null &&
      this.persistence.hydrationReady() &&
      !this.persistence.actionsDisabled(),
  );

  /** Fail-closed reason shared by button state, tooltip and direct calls. */
  readonly executionBlockReason = computed(() => this.computeExecutionBlockReason());
  readonly canExecute = computed(() => this.executionBlockReason() === null);
  readonly canDebug = computed(
    () =>
      this.computeExecutionBlockReason({ ignoreDebugMode: true }) === null &&
      this.runtimeMode() !== 'sequential_legacy',
  );
  readonly canSubmitInput = computed(
    () =>
      this.canExecute() &&
      !this.executing() &&
      this.inputValidationError() === null &&
      this.draftIngressSelectionError() === null,
  );

  /** Hash for which the backend returned 409. It remains blocked until a
   * strict reload supplies a different authoritative hash. */
  private readonly staleRejectedSha256 = signal<string | null>(null);

  /** HITL gate payload, present only while paused for human approval. */
  readonly pendingHitl = computed<RunHitlPayload | null>(() => {
    const run = this.currentRun();
    return run?.status === 'hitl_pending' ? run.hitl ?? {} : null;
  });

  /** Debugger pause payload, present only while paused on a node. */
  readonly pendingDebug = computed<RunDebugPayload | null>(() => {
    const run = this.currentRun();
    return run?.status === 'debug_pending' ? run.debug ?? {} : null;
  });

  readonly canReplay = computed(() => (this.currentRun()?.checkpoints?.length ?? 0) > 0);

  // ---- internals ----------------------------------------------------------
  private streamSub: Subscription | null = null;
  private pollSub: Subscription | null = null;
  private streamFellBackToPoll = false;
  private resultLogged = false;
  private logSeq = 0;
  private readonly seenCheckpoints = new Set<string>();
  private readonly seenInvocationIds = new Set<string>();
  private readonly unregisterContextReset = this.workspace?.registerContextReset(() => {
    this.stopStream();
    this.systemId.set(null);
    this.status.set('idle');
    this.log.set([]);
    this.currentRun.set(null);
    this.executing.set(false);
    this.hitlResolving.set(false);
    this.debugStepping.set(false);
    this.terminalOpen.set(false);
    this.inputEditorOpen.set(false);
    this.inputText.set('{}');
    this.dispatchError.set(null);
    this.selectedDraftIngressId.set('');
    this.staleRejectedSha256.set(null);
    this.activeNodeId.set(null);
    this._nodeRuns.set({});
    this.seenCheckpoints.clear();
    this.seenInvocationIds.clear();
  });

  private captureWorkspaceScope(): WorkspaceRequestScope | null {
    return this.workspace?.captureRequestScope() ?? null;
  }

  private isWorkspaceScopeCurrent(scope: WorkspaceRequestScope | null): boolean {
    return scope === null || !this.workspace || this.workspace.isRequestScopeCurrent(scope);
  }

  /** Bind (or rebind) the owning System. Called once by the shell. */
  bindSystem(systemId: string | null): void {
    this.systemId.set(systemId);
    this.inputEditorOpen.set(false);
    this.inputText.set('{}');
    this.dispatchError.set(null);
    this.selectedDraftIngressId.set('');
    this.staleRejectedSha256.set(null);
  }

  /** A strict Builder hydration is authoritative even when the reloaded graph
   * has the same canonical hash as the rejected request. Revision or published
   * pointer drift can produce a legitimate 409 without changing graph bytes,
   * so only this explicit acknowledgement—not hash inequality—releases the
   * stale Execute latch. */
  acknowledgeAuthoritativeHydration(): void {
    this.staleRejectedSha256.set(null);
    this.dispatchError.set(null);
  }

  // ---- breakpoints / debug mode (state lives HERE, not in the flow) -------
  isBreakpoint(nodeId: string): boolean {
    return this._breakpoints().includes(nodeId);
  }

  toggleBreakpoint(nodeId: string): void {
    const set = new Set(this._breakpoints());
    if (set.has(nodeId)) set.delete(nodeId);
    else set.add(nodeId);
    this._breakpoints.set([...set]);
  }

  /** off → step → breakpoints → off. */
  cycleDebugMode(): DebugMode {
    if (!this.canDebug()) {
      this.debugMode.set('off');
      return 'off';
    }
    const next: DebugMode =
      this.debugMode() === 'off'
        ? 'step'
        : this.debugMode() === 'step'
          ? 'breakpoints'
          : 'off';
    this.debugMode.set(next);
    return next;
  }

  isActiveNode(nodeId: string): boolean {
    return this.activeNodeId() === nodeId;
  }

  // ---- terminal helpers ---------------------------------------------------
  toggleTerminal(): void {
    this.terminalOpen.update((v) => !v);
  }

  clearLog(): void {
    this.log.set([]);
  }

  openInputEditor(): void {
    if (!this.canExecute() || this.executing()) {
      this.terminalOpen.set(true);
      this.push({
        tone: 'warn',
        tag: 'EXEC',
        text: this.executionBlockReason() ?? this.i18n.t('flow.run.log.already_running'),
      });
      return;
    }
    this.dispatchError.set(null);
    this.alignDraftIngressSelection();
    this.inputEditorOpen.set(true);
  }

  closeInputEditor(): void {
    if (this.executing()) return;
    this.inputEditorOpen.set(false);
    this.dispatchError.set(null);
  }

  updateInputText(value: string): void {
    this.inputText.set(value);
    this.dispatchError.set(null);
  }

  chooseDraftTestIngress(ingressId: string): void {
    const exists = this.draftTestIngresses().some(
      (candidate) => candidate.ingress_id === ingressId,
    );
    this.selectedDraftIngressId.set(exists ? ingressId : '');
    this.dispatchError.set(null);
  }

  submitInputEditor(): void {
    const parsed = parseRunInputRef(this.inputText());
    if (!parsed.ok) {
      this.dispatchError.set(this.i18n.t(parsed.messageKey));
      return;
    }
    this.executeOnBackend(parsed.value);
  }

  private alignDraftIngressSelection(): void {
    if (!this.draftTestMode()) {
      this.selectedDraftIngressId.set('');
      return;
    }
    const candidates = this.draftTestIngresses();
    const selected = this.selectedDraftIngressId();
    if (candidates.some((candidate) => candidate.ingress_id === selected)) return;
    this.selectedDraftIngressId.set(
      candidates.length === 1 ? candidates[0].ingress_id : '',
    );
  }

  /** Push a line into the terminal (capped at {@link LOG_LIMIT}). */
  push(entry: Omit<RunLogEntry, 'id' | 't'>): void {
    const t = new Date().toTimeString().slice(0, 8);
    this.log.update((log) => {
      const next = [...log, { id: `run-${++this.logSeq}`, t, ...entry }];
      return next.length > LOG_LIMIT ? next.slice(next.length - LOG_LIMIT) : next;
    });
  }

  // ---- client-side dry run (no backend, works on the scratchpad) ----------
  simulate(): void {
    if (this.store.nodeCount() === 0) {
      this.terminalOpen.set(true);
      this.push({ tone: 'warn', tag: 'SIM', text: this.i18n.t('flow.run.log.sim_empty') });
      return;
    }
    const errors = this.blockingIssues();
    if (errors.length > 0) {
      this.terminalOpen.set(true);
      this.reportIssues('SIM', errors);
      return;
    }
    const flow = this.store.snapshot();
    const order = this.serializer.topoSort(flow) ?? flow.nodes.map((n) => n.id);
    const byId = new Map(flow.nodes.map((n) => [n.id, n] as const));
    this.terminalOpen.set(true);
    this.push({ tone: 'cyan', tag: 'SIM', text: this.i18n.t('flow.run.log.sim_start') });
    this.push({
      tone: 'info',
      tag: 'PLAN',
      text: `${flow.nodes.length} nodes · ${flow.edges.length} edges`,
    });
    for (const id of order) {
      const node = byId.get(id);
      if (!node) continue;
      const kind = node.kind ?? 'task';
      if (kind === 'source' || kind === 'sink') continue;
      this.push({ tone: 'info', tag: kind.toUpperCase(), text: `▷ ${node.label ?? id}` });
    }
    this.push({ tone: 'pos', tag: 'DONE', text: this.i18n.t('flow.run.log.sim_done') });
  }

  // ---- real backend run ---------------------------------------------------
  executeOnBackend(inputRef: Record<string, unknown> = {}): void {
    const sid = this.systemId();
    if (Object.prototype.hasOwnProperty.call(inputRef, '_debug')) {
      const message = this.i18n.t('flow.run.log.debug_reserved');
      this.inputEditorOpen.set(true);
      this.dispatchError.set(message);
      this.terminalOpen.set(true);
      this.fail(message);
      return;
    }
    const validationErrors = this.blockingIssues();
    if (sid && validationErrors.length > 0) {
      this.terminalOpen.set(true);
      this.reportIssues('EXEC', validationErrors);
      this.status.set('error');
      return;
    }
    const blocked = this.executionBlockReason();
    if (!sid || blocked) {
      this.terminalOpen.set(true);
      this.push({
        tone: 'warn',
        tag: 'EXEC',
        text: blocked ?? this.i18n.t('flow.run.blocked.scratchpad'),
      });
      if (sid) this.status.set('error');
      return;
    }
    this.alignDraftIngressSelection();
    const draftIngress = this.draftTestMode()
      ? this.selectedDraftTestIngress()
      : null;
    if (this.draftTestMode() && !draftIngress) {
      const message =
        this.draftIngressSelectionError() ??
        this.i18n.t('flow.run.entry.required');
      this.inputEditorOpen.set(true);
      this.dispatchError.set(message);
      this.terminalOpen.set(true);
      this.fail(message);
      return;
    }
    if (this.executing()) return;

    this.stopStream();
    this.seenInvocationIds.clear();
    this.seenCheckpoints.clear();
    // A new run makes every figure on the canvas stale at once.
    this._nodeRuns.set({});
    this.streamFellBackToPoll = false;
    this.resultLogged = false;
    this.terminalOpen.set(true);
    this.executing.set(true);
    this.dispatchError.set(null);
    this.status.set('running');
    this.push({ tone: 'cyan', tag: 'EXEC', text: this.i18n.t('flow.run.log.dispatching') });

    const mode = this.debugMode();
    const expectedFlowSha256 = this.persistence.savedFlowSha256();
    // The readiness gate above proves this exists. Keep the local guard so a
    // future refactor cannot emit a trigger without its concurrency token.
    if (!expectedFlowSha256) {
      this.fail(this.i18n.t('flow.run.log.no_hash'));
      return;
    }
    const canonicalInput = structuredClone(inputRef);
    if (mode !== 'off') {
      canonicalInput['_debug'] = {
        mode,
        breakpoints: [...this._breakpoints()],
      };
    }
    const request: RunTriggerRequest = {
      trigger: 'manual',
      input_ref: canonicalInput,
      expected_flow_sha256: expectedFlowSha256,
    };
    const trigger$ = this.draftTestMode()
      ? this.canonical.triggerSystemFlowDraftTestRun(sid, {
          input_ref: canonicalInput,
          expected_draft_revision: this.persistence.draftRevision()!,
          expected_flow_sha256: expectedFlowSha256,
          ...draftIngress!,
        })
      : this.canonical.triggerRun(sid, request);
    const scope = this.captureWorkspaceScope();
    if (mode !== 'off') {
      this.push({
        tone: 'warn',
        tag: 'DEBUG',
        text: this.i18n.t('flow.run.log.debugger_attached', {
          mode,
          count: this._breakpoints().length,
        }),
      });
    }

    trigger$.subscribe({
      next: (run) => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        if (!run) {
          this.fail(this.i18n.t('flow.run.log.trigger_rejected'));
          return;
        }
        this.currentRun.set(run);
        this.inputEditorOpen.set(false);
        this.inputText.set('{}');
        this.dispatchError.set(null);
        this.push({
          tone: 'info',
          tag: 'RUN',
          text: this.i18n.t('flow.run.log.scheduled', {
            id: run.id.slice(0, 8),
            status: run.status,
          }),
        });
        this.startStreaming(run.id, scope);
      },
      error: (error: unknown) => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        const message = this.triggerErrorMessage(error);
        if (error instanceof HttpErrorResponse && error.status === 409) {
          this.staleRejectedSha256.set(expectedFlowSha256);
          if (this.persistence.publicationMode()) {
            this.persistence.markRevisionConflict(
              this.i18n.t('flow.run.log.draft_changed'),
            );
          }
        }
        this.dispatchError.set(message);
        // Keep the editor open with the exact operator input on every HTTP
        // rejection, including 403/409/422.
        this.inputEditorOpen.set(true);
        this.fail(message);
      },
    });
  }

  // ---- HITL ---------------------------------------------------------------
  resolveHitl(action: 'accept' | 'reject'): void {
    const run = this.currentRun();
    if (!run || run.status !== 'hitl_pending') return;
    if (this.hitlResolving()) return;
    this.hitlResolving.set(true);
    const scope = this.captureWorkspaceScope();
    this.canonical.resolveRunHitl(run.id, { action, expected_decision_id: run.hitl?.decision_id }).subscribe({
      next: (updated) => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        this.hitlResolving.set(false);
        if (!updated) {
          this.push({ tone: 'neg', tag: 'ERR', text: this.i18n.t('flow.run.log.approval_rejected') });
          return;
        }
        this.push({
          tone: action === 'accept' ? 'pos' : 'warn',
          tag: 'HITL',
          text: this.i18n.t(
            action === 'accept'
              ? 'flow.run.log.approval_accepted'
              : 'flow.run.log.approval_declined',
          ),
        });
        this.currentRun.set(updated);
        this.executing.set(true);
        this.status.set('running');
        this.seenCheckpoints.clear();
        this.startStreaming(run.id, scope);
      },
      error: () => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        this.hitlResolving.set(false);
        this.push({ tone: 'neg', tag: 'ERR', text: this.i18n.t('flow.run.log.approval_network') });
      },
    });
  }

  // ---- step debugger ------------------------------------------------------
  debugAction(action: 'step' | 'continue' | 'stop'): void {
    const run = this.currentRun();
    if (!run || run.status !== 'debug_pending') return;
    if (this.debugStepping()) return;
    this.debugStepping.set(true);
    this.push({
      tone: action === 'stop' ? 'neg' : 'cyan',
      tag: 'DEBUG',
      text: this.i18n.t('flow.run.log.operator_action', { action }),
    });
    const scope = this.captureWorkspaceScope();
    this.canonical.stepRun(run.id, { action, breakpoints: this._breakpoints() }).subscribe({
      next: (updated) => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        this.debugStepping.set(false);
        if (!updated) {
          this.push({ tone: 'neg', tag: 'ERR', text: this.i18n.t('flow.run.log.debug_rejected') });
          return;
        }
        if (action === 'stop') {
          this.executing.set(false);
          this.status.set('done');
          this.activeNodeId.set(null);
          this.currentRun.set(updated);
          this.canonical.getRun(run.id).subscribe((r) => {
            if (!this.isWorkspaceScopeCurrent(scope)) return;
            if (r) this.currentRun.set(r);
          });
          return;
        }
        this.currentRun.set(updated);
        this.executing.set(true);
        this.status.set('running');
        this.seenCheckpoints.clear();
        this.startStreaming(run.id, scope);
      },
      error: () => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        this.debugStepping.set(false);
        this.push({ tone: 'neg', tag: 'ERR', text: this.i18n.t('flow.run.log.debug_network') });
      },
    });
  }

  // ---- checkpoint replay (client-side, re-emits the run's checkpoints) ----
  replayRun(): void {
    const run = this.currentRun();
    const checkpoints = (run?.checkpoints ?? []) as Array<Record<string, unknown> & { kind?: string }>;
    if (!run || checkpoints.length === 0) {
      this.terminalOpen.set(true);
      this.push({ tone: 'info', tag: 'REPLAY', text: this.i18n.t('flow.run.log.replay_none') });
      return;
    }
    this.terminalOpen.set(true);
    this.log.set([]);
    this.logSeq = 0;
    this.push({
      tone: 'cyan',
      tag: 'REPLAY',
      text: this.i18n.t('flow.run.log.replay_start', {
        count: checkpoints.length,
        id: run.id.slice(0, 8),
      }),
    });
    for (const cp of checkpoints) {
      this.emitStreamEvent(
        run.id,
        { event: String(cp['kind'] ?? 'event'), data: cp },
        this.captureWorkspaceScope(),
      );
    }
    this.push({ tone: 'pos', tag: 'REPLAY', text: this.i18n.t('flow.run.log.replay_done') });
  }

  /** Stop all live connections. Called by the shell on destroy. */
  dispose(): void {
    this.stopStream();
    this.unregisterContextReset?.();
  }

  // ---- validation ---------------------------------------------------------
  private computeExecutionBlockReason(
    options: { ignoreDebugMode?: boolean } = {},
  ): string | null {
    const sid = this.systemId();
    if (!sid) return this.i18n.t('flow.run.blocked.scratchpad');
    if (!this.persistence.hydrationReady()) {
      return this.i18n.t('flow.run.blocked.hydration');
    }
    const saveState = this.persistence.saveState();
    if (saveState === 'saving' || this.persistence.actionsDisabled()) {
      return this.i18n.t('flow.run.blocked.saving');
    }
    if (saveState === 'error') {
      return this.i18n.t('flow.run.blocked.save_failed');
    }
    if (this.store.dirty() || saveState === 'unsaved') {
      return this.i18n.t('flow.run.blocked.unsaved');
    }
    const savedSha = this.persistence.savedFlowSha256();
    if (!savedSha) {
      return this.i18n.t('flow.run.blocked.no_hash');
    }
    if (this.staleRejectedSha256() === savedSha) {
      return this.i18n.t('flow.run.blocked.server_changed');
    }
    const serverValidation = this.persistence.serverValidation();
    if (!serverValidation) {
      return this.persistence.serverValidationState() === 'error'
        ? this.i18n.t('flow.run.blocked.validation_failed')
        : this.i18n.t('flow.run.blocked.validation_pending');
    }
    if (serverValidation.flow_sha256 !== savedSha) {
      return this.i18n.t('flow.run.blocked.validation_refreshing');
    }
    if (
      !serverValidation.valid ||
      serverValidation.issues.some((issue) => issue.level === 'error')
    ) {
      return this.i18n.t('flow.run.blocked.server_errors');
    }
    if (this.blockingIssues().length > 0) {
      return this.i18n.t('flow.run.blocked.local_errors');
    }
    if (
      !options.ignoreDebugMode &&
      this.debugMode() === 'breakpoints' &&
      this._breakpoints().length === 0
    ) {
      return this.i18n.t('flow.run.blocked.breakpoints');
    }

    if (this.persistence.publicationMode()) {
      if (this.persistence.draftRevision() === null) {
        return this.i18n.t('flow.run.blocked.revision_missing');
      }
      const runtimeMode = this.runtimeMode();
      if (!runtimeMode) {
        return this.i18n.t('flow.run.blocked.draft_mode_unknown');
      }
      if (
        !options.ignoreDebugMode &&
        this.debugMode() !== 'off' &&
        runtimeMode === 'sequential_legacy'
      ) {
        return this.i18n.t('flow.run.debug.unavailable.sequential');
      }
      return null;
    }

    const manifest = this.manifest.manifest();
    if (!manifest || manifest.system_id !== sid) {
      return this.i18n.t('flow.run.blocked.contract_loading');
    }
    if (!manifest.flow_sha256) {
      return this.i18n.t('flow.run.blocked.contract_no_hash');
    }
    if (manifest.flow_sha256 !== savedSha) {
      return this.i18n.t('flow.run.blocked.contract_refreshing');
    }
    const runtimeMode = this.runtimeMode();
    if (!runtimeMode) {
      return this.i18n.t('flow.run.blocked.server_mode_unknown');
    }
    if (!options.ignoreDebugMode && this.debugMode() !== 'off' && runtimeMode === 'sequential_legacy') {
      return this.i18n.t('flow.run.debug.unavailable.sequential');
    }
    return null;
  }

  private triggerErrorMessage(error: unknown): string {
    if (!(error instanceof HttpErrorResponse)) {
      return this.i18n.t('flow.run.error.network');
    }
    switch (error.status) {
      case 403:
        return this.i18n.t('flow.run.error.denied');
      case 409:
        return this.i18n.t('flow.run.error.flow_changed');
      case 422:
        return this.i18n.t('flow.run.error.invalid_input');
      default:
        return error.status > 0
          ? this.i18n.t('flow.run.error.http', { status: error.status })
          : this.i18n.t('flow.run.error.network');
    }
  }

  /** Error-level diagnostics that must block a backend launch. */
  private blockingIssues(): { node_id?: string; message: string }[] {
    return this.serializer
      .validateFlow(this.store.snapshot())
      .filter((i) => i.level === 'error')
      .map((i) => ({ node_id: i.node_id, message: i.message }));
  }

  private reportIssues(tag: string, issues: { node_id?: string; message: string }[]): void {
    this.push({
      tone: 'neg',
      tag,
      text: this.i18n.t('flow.run.log.validation_blocked', { count: issues.length }),
    });
    for (const issue of issues) {
      this.push({ tone: 'neg', tag: 'ERR', text: issue.message });
    }
  }

  private fail(message: string): void {
    this.executing.set(false);
    this.status.set('error');
    this.activeNodeId.set(null);
    this.push({ tone: 'neg', tag: 'ERR', text: message });
  }

  // ---- SSE streaming + polling fallback -----------------------------------
  private startStreaming(
    runId: string,
    scope: WorkspaceRequestScope | null = this.captureWorkspaceScope(),
  ): void {
    this.stopStream();
    this.streamSub = this.runStream.streamRun(runId).subscribe({
      next: (event) => {
        if (this.isWorkspaceScopeCurrent(scope)) this.emitStreamEvent(runId, event, scope);
      },
      error: () => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        if (!this.streamFellBackToPoll) {
          this.streamFellBackToPoll = true;
          this.push({ tone: 'warn', tag: 'STREAM', text: this.i18n.t('flow.run.log.stream_interrupted') });
          this.startPolling(runId, scope);
        } else {
          this.fail(this.i18n.t('flow.run.log.connection_lost'));
        }
      },
      complete: () => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        this.canonical.getRun(runId).subscribe((r) => {
          if (!this.isWorkspaceScopeCurrent(scope)) return;
          if (r) {
            this.currentRun.set(r);
            this.applyTerminalStatus(r);
            this.logRunOutcome(r, scope);
          }
          this.executing.set(false);
        });
      },
    });
  }

  private stopStream(): void {
    this.streamSub?.unsubscribe();
    this.streamSub = null;
    this.stopPolling();
  }

  private startPolling(runId: string, scope: WorkspaceRequestScope | null): void {
    this.stopPolling();
    this.pollSub = timer(0, POLL_INTERVAL_MS)
      .pipe(
        switchMap(() => this.canonical.getRun(runId)),
        takeWhile((r) => !!r && !this.isTerminal(r.status) && !this.isPaused(r.status), true),
      )
      .subscribe({
        next: (r) => {
          if (!this.isWorkspaceScopeCurrent(scope)) return;
          if (!r) return;
          this.currentRun.set(r);
          this.applyTerminalStatus(r);
          if (this.isTerminal(r.status) || this.isPaused(r.status)) {
            if (this.isTerminal(r.status)) this.logRunOutcome(r, scope);
            this.executing.set(false);
            this.stopPolling();
          }
        },
        error: () => {
          if (!this.isWorkspaceScopeCurrent(scope)) return;
          this.executing.set(false);
          this.stopPolling();
          this.push({ tone: 'neg', tag: 'ERR', text: this.i18n.t('flow.run.log.poll_lost') });
        },
      });
  }

  private stopPolling(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = null;
  }

  private isTerminal(status: Run['status'] | undefined): boolean {
    return status === 'completed' || status === 'failed' || status === 'cancelled';
  }

  private isPaused(status: Run['status'] | undefined): boolean {
    return status === 'hitl_pending' || status === 'debug_pending';
  }

  /**
   * Surface the run's outcome in the terminal once it reaches a terminal
   * state: replay any node checkpoints the live stream missed (fast runs
   * often finish before the SSE subscription lands — `seenCheckpoints`
   * dedupes the overlap), then print the final answer / failed steps so the
   * result is consumable without leaving the builder.
   */
  private logRunOutcome(run: Run, scope: WorkspaceRequestScope | null): void {
    if (this.resultLogged) return;
    this.resultLogged = true;

    const checkpoints = (run.checkpoints ?? []) as Array<
      Record<string, unknown> & { kind?: string }
    >;
    for (const cp of checkpoints) {
      this.emitStreamEvent(run.id, { event: String(cp['kind'] ?? 'event'), data: cp }, scope);
    }

    if (run.status === 'failed') {
      this.push({
        tone: 'neg',
        tag: 'RESULT',
        text: run.error
          ? this.i18n.t('flow.run.log.failed_detail', {
            detail: String(run.error).slice(0, 160),
          })
          : this.i18n.t('flow.run.log.failed'),
      });
      return;
    }
    if (run.status !== 'completed') return;

    const output = (run.output_ref ?? {}) as Record<string, unknown>;
    const answer = typeof output['answer'] === 'string' ? (output['answer'] as string) : null;
    if (answer) {
      this.push({ tone: 'pos', tag: 'RESULT', text: answer });
    } else if (Object.keys(output).length > 0) {
      this.push({ tone: 'pos', tag: 'RESULT', text: JSON.stringify(output).slice(0, 600) });
    } else {
      this.push({ tone: 'info', tag: 'RESULT', text: this.i18n.t('flow.run.log.no_output') });
    }
    const citations = Array.isArray(output['citations']) ? (output['citations'] as unknown[]) : [];
    if (citations.length > 0) {
      this.push({ tone: 'info', tag: 'SOURCES', text: `${citations.length} grounded citation(s).` });
    }
  }

  /** Map a freshly-fetched Run onto the coarse UI status. */
  private applyTerminalStatus(run: Run): void {
    switch (run.status) {
      case 'completed':
        this.status.set('done');
        this.activeNodeId.set(null);
        break;
      case 'failed':
        this.status.set('error');
        this.activeNodeId.set(null);
        break;
      case 'cancelled':
        this.status.set('done');
        this.activeNodeId.set(null);
        break;
      case 'hitl_pending':
      case 'debug_pending':
        this.status.set('paused');
        break;
      default:
        break;
    }
  }

  /** Translate one SSE frame into a terminal line + minimal state update. */
  private emitStreamEvent(
    runId: string,
    event: RunStreamEvent,
    scope: WorkspaceRequestScope | null = this.captureWorkspaceScope(),
  ): void {
    if (!this.isWorkspaceScopeCurrent(scope)) return;
    const data = event.data as {
      t?: string;
      node_id?: string;
      node_kind?: string;
      label?: string;
      status?: string;
      skill_slug?: string;
      latency_ms?: number;
      error?: string;
      chosen_branch?: string;
      resolution?: 'matched' | 'defaulted' | 'no_match' | 'unroutable' | 'error';
      reason?: string;
      outcome?: Run['outcome'];
      invocation_id?: string;
      text?: string;
    };

    // Dedupe checkpoint-stamped frames so replay-then-live can't double-log.
    if (typeof data.t === 'string') {
      const key = `${event.event}:${data.t}:${data.node_id ?? ''}`;
      if (this.seenCheckpoints.has(key)) return;
      this.seenCheckpoints.add(key);
    }

    switch (event.event) {
      case 'run_start':
        this.push({ tone: 'info', tag: 'START', text: this.i18n.t('flow.run.log.walker_booted') });
        break;
      case 'node_start': {
        if (data.node_id) {
          this.activeNodeId.set(data.node_id);
          // The previous run's figure must not sit next to the pulse of this
          // one: a node that starts again has, for now, nothing to report.
          this.forgetNodeRun(data.node_id);
        }
        const tag = (data.node_kind ?? 'NODE').toUpperCase();
        this.push({
          tone: 'info',
          tag,
          text: `▶ ${data.label ?? data.node_id ?? 'node'}${data.skill_slug ? ` · ${data.skill_slug}` : ''}`,
        });
        break;
      }
      case 'node_end': {
        this.recordNodeRun(event.data);
        const tag = (data.node_kind ?? 'NODE').toUpperCase();
        const latency = data.latency_ms != null ? ` · ${Math.round(data.latency_ms)}ms` : '';
        const branch = data.chosen_branch ? ` · branch=${data.chosen_branch}` : '';
        const tone: RunLogEntry['tone'] =
          data.status === 'failed' ? 'neg' : data.status === 'completed' ? 'pos' : 'info';
        this.push({
          tone,
          tag,
          text: `◼ ${data.label ?? data.node_id ?? 'node'}${data.status ? ` · ${data.status}` : ''}${latency}${branch}${
            data.error ? ` · ${data.error.slice(0, 80)}` : ''
          }`,
        });
        break;
      }
      case 'decision_resolution': {
        const resolution = data.resolution ?? 'error';
        const branch = data.chosen_branch ? ` → ${data.chosen_branch}` : '';
        const text =
          resolution === 'matched'
            ? this.i18n.t('flow.run.log.decision_matched', { node: data.node_id ?? '', branch })
            : resolution === 'defaulted'
              ? this.i18n.t('flow.run.log.decision_default', {
                node: data.node_id ?? '',
                branch,
              })
              : resolution === 'no_match'
                ? this.i18n.t('flow.run.log.decision_no_match', { node: data.node_id ?? '' })
                : resolution === 'unroutable'
                  ? this.i18n.t('flow.run.log.decision_unroutable', {
                    node: data.node_id ?? '',
                    branch,
                  })
                  : this.i18n.t('flow.run.log.decision_error', { node: data.node_id ?? '' });
        this.push({
          tone:
            resolution === 'matched' || resolution === 'defaulted'
              ? 'cyan'
              : resolution === 'no_match' || resolution === 'unroutable'
                ? 'warn'
                : 'neg',
          tag: 'DECISION',
          text,
        });
        break;
      }
      case 'hitl_pause':
        this.push({
          tone: 'warn',
          tag: 'HITL',
          text: `⏸ Paused on ${data.label ?? data.node_id ?? 'hitl gate'} — awaiting operator.`,
        });
        if (data.node_id) this.activeNodeId.set(data.node_id);
        this.status.set('paused');
        this.canonical.getRun(runId).subscribe((r) => {
          if (!this.isWorkspaceScopeCurrent(scope)) return;
          if (r) this.currentRun.set(r);
          this.executing.set(false);
        });
        break;
      case 'hitl_resume':
        this.push({ tone: 'info', tag: 'HITL', text: `▶ Resumed from ${data.node_id ?? 'gate'}.` });
        break;
      case 'debug_pause':
        this.push({
          tone: 'warn',
          tag: 'DEBUG',
          text: `⏸ Paused after ${data.node_id ?? 'node'} — inspect context and advance.`,
        });
        if (data.node_id) this.activeNodeId.set(data.node_id);
        this.status.set('paused');
        this.canonical.getRun(runId).subscribe((r) => {
          if (!this.isWorkspaceScopeCurrent(scope)) return;
          if (r) this.currentRun.set(r);
          this.executing.set(false);
        });
        break;
      case 'debug_resume':
        this.push({ tone: 'cyan', tag: 'DEBUG', text: `▶ Resumed from ${data.node_id ?? 'node'}` });
        break;
      case 'run_end':
        this.push({
          tone: data.status === 'completed' ? 'pos' : 'neg',
          tag: 'END',
          text: this.i18n.t('flow.run.log.finished', { status: data.status ?? 'unknown' }),
        });
        this.status.set(data.status === 'completed' ? 'done' : 'error');
        this.activeNodeId.set(null);
        break;
      case 'token_delta':
        this.appendStreamToken(data.invocation_id ?? data.node_id ?? runId, data.text ?? '');
        break;
      case 'snapshot':
        if (data.status || data.outcome) {
          const prev = this.currentRun();
          if (prev) {
            this.currentRun.set({
              ...prev,
              status: (data.status as Run['status']) ?? prev.status,
              outcome: data.outcome ?? prev.outcome,
            });
          }
        }
        break;
      case 'close':
        break;
      case 'error':
        this.push({ tone: 'neg', tag: 'ERR', text: data.reason ?? 'Stream error.' });
        break;
      default:
        this.push({
          tone: 'info',
          tag: event.event.toUpperCase().slice(0, 10),
          text: JSON.stringify(data).slice(0, 120),
        });
    }
  }

  /** Remember what a node just did, for the canvas badge. */
  private recordNodeRun(frame: unknown): void {
    const summary = readNodeRunSummary(frame);
    if (!summary) return;
    this._nodeRuns.update((runs) => ({ ...runs, [summary.nodeId]: summary }));
  }

  private forgetNodeRun(nodeId: string): void {
    this._nodeRuns.update((runs) => {
      if (!(nodeId in runs)) return runs;
      const next = { ...runs };
      delete next[nodeId];
      return next;
    });
  }

  /** Grow a single streaming line in place instead of one entry per chunk. */
  private appendStreamToken(streamId: string, delta: string): void {
    if (!delta) return;
    this.log.update((log) => {
      for (let i = log.length - 1; i >= 0; i--) {
        if (log[i].streamId === streamId) {
          const next = [...log];
          next[i] = { ...next[i], text: next[i].text + delta };
          return next;
        }
      }
      const t = new Date().toTimeString().slice(0, 8);
      const next = [...log, { id: `run-${++this.logSeq}`, t, tag: 'LLM', tone: 'cyan' as const, text: delta, streamId }];
      return next.length > LOG_LIMIT ? next.slice(next.length - LOG_LIMIT) : next;
    });
  }
}
