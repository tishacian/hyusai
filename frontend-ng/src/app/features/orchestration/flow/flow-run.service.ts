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
 *   - Trigger real runs (`triggerRun` / `triggerRunDebug`), then stream events
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
import { Injectable, computed, inject, signal } from '@angular/core';
import { Subscription, timer } from 'rxjs';
import { switchMap, takeWhile } from 'rxjs/operators';
import {
  CanonicalApiService,
  type Run,
  type RunDebugPayload,
  type RunHitlPayload,
} from '@app/core/canonical-api.service';
import {
  RunStreamService,
  type RunStreamEvent,
} from '@app/core/run-stream.service';
import { FlowSerializerService } from '@app/core/flow-serializer.service';
import {
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { FlowStore } from './flow.store';
import type { DebugMode, RunLogEntry, RunUiStatus } from './flow-run.types';

/** Cap so a chatty run can never grow the terminal unbounded. */
const LOG_LIMIT = 200;
/** Polling cadence used only when the SSE stream drops. */
const POLL_INTERVAL_MS = 1500;

@Injectable()
export class FlowRunService {
  private readonly store = inject(FlowStore);
  private readonly canonical = inject(CanonicalApiService);
  private readonly runStream = inject(RunStreamService);
  private readonly serializer = inject(FlowSerializerService);
  private readonly workspace = inject(WorkspaceService, { optional: true });

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

  readonly debugMode = signal<DebugMode>('off');
  private readonly _breakpoints = signal<string[]>([]);
  readonly breakpoints = this._breakpoints.asReadonly();

  /** Node currently executing / paused on — drives the canvas run overlay. */
  readonly activeNodeId = signal<string | null>(null);

  /** Execute / Debug / Versions require a saved System. */
  readonly canExecute = computed(() => this.systemId() !== null);

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
    this.activeNodeId.set(null);
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
      this.push({ tone: 'warn', tag: 'SIM', text: 'Add at least one node before simulating.' });
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
    this.push({ tone: 'cyan', tag: 'SIM', text: 'Client-side simulation — no backend call.' });
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
    this.push({ tone: 'pos', tag: 'DONE', text: 'Simulation finished (dry run).' });
  }

  // ---- real backend run ---------------------------------------------------
  executeOnBackend(): void {
    const sid = this.systemId();
    if (!sid) {
      this.terminalOpen.set(true);
      this.push({
        tone: 'warn',
        tag: 'EXEC',
        text: 'Scratchpad cannot Execute — promote to a System first.',
      });
      return;
    }
    if (this.executing()) return;

    const errors = this.blockingIssues();
    if (errors.length > 0) {
      this.terminalOpen.set(true);
      this.reportIssues('EXEC', errors);
      this.status.set('error');
      return;
    }

    this.stopStream();
    this.seenInvocationIds.clear();
    this.seenCheckpoints.clear();
    this.streamFellBackToPoll = false;
    this.terminalOpen.set(true);
    this.executing.set(true);
    this.status.set('running');
    this.push({ tone: 'cyan', tag: 'EXEC', text: 'Dispatching run to backend…' });

    const mode = this.debugMode();
    const trigger$ =
      mode === 'off'
        ? this.canonical.triggerRun(sid, {})
        : this.canonical.triggerRunDebug(sid, { mode, breakpoints: this._breakpoints() });
    const scope = this.captureWorkspaceScope();
    if (mode !== 'off') {
      this.push({
        tone: 'warn',
        tag: 'DEBUG',
        text: `Debugger attached · mode=${mode} · breakpoints=${this._breakpoints().length}`,
      });
    }

    trigger$.subscribe({
      next: (run) => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        if (!run) {
          this.fail('Backend rejected the trigger request.');
          return;
        }
        this.currentRun.set(run);
        this.push({
          tone: 'info',
          tag: 'RUN',
          text: `Run ${run.id.slice(0, 8)}… scheduled (status=${run.status}).`,
        });
        this.startStreaming(run.id, scope);
      },
      error: () => {
        if (this.isWorkspaceScopeCurrent(scope)) this.fail('Network error while triggering run.');
      },
    });
  }

  // ---- HITL ---------------------------------------------------------------
  resolveHitl(action: 'accept' | 'reject'): void {
    const run = this.currentRun();
    if (!run || run.status !== 'hitl_pending') return;
    if (this.hitlResolving()) return;
    this.hitlResolving.set(true);
    this.push({
      tone: action === 'accept' ? 'pos' : 'warn',
      tag: 'HITL',
      text: `Operator ${action === 'accept' ? 'approved' : 'rejected'} the pending step.`,
    });
    const scope = this.captureWorkspaceScope();
    this.canonical.resolveRunHitl(run.id, { action }).subscribe({
      next: (updated) => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        this.hitlResolving.set(false);
        if (!updated) {
          this.push({ tone: 'neg', tag: 'ERR', text: 'HITL resolve rejected by backend.' });
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
        this.hitlResolving.set(false);
        this.push({ tone: 'neg', tag: 'ERR', text: 'Network error during HITL resolve.' });
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
      text: `Operator → ${action}`,
    });
    const scope = this.captureWorkspaceScope();
    this.canonical.stepRun(run.id, { action, breakpoints: this._breakpoints() }).subscribe({
      next: (updated) => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        this.debugStepping.set(false);
        if (!updated) {
          this.push({ tone: 'neg', tag: 'ERR', text: 'Debugger rejected by backend.' });
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
        this.push({ tone: 'neg', tag: 'ERR', text: 'Network error during debug action.' });
      },
    });
  }

  // ---- checkpoint replay (client-side, re-emits the run's checkpoints) ----
  replayRun(): void {
    const run = this.currentRun();
    const checkpoints = (run?.checkpoints ?? []) as Array<Record<string, unknown> & { kind?: string }>;
    if (!run || checkpoints.length === 0) {
      this.terminalOpen.set(true);
      this.push({ tone: 'info', tag: 'REPLAY', text: 'No checkpoints to replay on this run.' });
      return;
    }
    this.terminalOpen.set(true);
    this.log.set([]);
    this.logSeq = 0;
    this.push({
      tone: 'cyan',
      tag: 'REPLAY',
      text: `Replaying ${checkpoints.length} checkpoints from run ${run.id.slice(0, 8)}…`,
    });
    for (const cp of checkpoints) {
      this.emitStreamEvent(
        run.id,
        { event: String(cp['kind'] ?? 'event'), data: cp },
        this.captureWorkspaceScope(),
      );
    }
    this.push({ tone: 'pos', tag: 'REPLAY', text: 'Replay done.' });
  }

  /** Stop all live connections. Called by the shell on destroy. */
  dispose(): void {
    this.stopStream();
    this.unregisterContextReset?.();
  }

  // ---- validation ---------------------------------------------------------
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
      text: `Blocked — ${issues.length} validation error(s). Fix before running:`,
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
          this.push({ tone: 'warn', tag: 'STREAM', text: 'Live stream interrupted — falling back to polling.' });
          this.startPolling(runId, scope);
        } else {
          this.fail('Lost connection to the backend (stream + poll).');
        }
      },
      complete: () => {
        if (!this.isWorkspaceScopeCurrent(scope)) return;
        this.canonical.getRun(runId).subscribe((r) => {
          if (!this.isWorkspaceScopeCurrent(scope)) return;
          if (r) {
            this.currentRun.set(r);
            this.applyTerminalStatus(r);
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
            this.executing.set(false);
            this.stopPolling();
          }
        },
        error: () => {
          if (!this.isWorkspaceScopeCurrent(scope)) return;
          this.executing.set(false);
          this.stopPolling();
          this.push({ tone: 'neg', tag: 'ERR', text: 'Lost connection while polling run.' });
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
        this.push({ tone: 'info', tag: 'START', text: 'Walker booted — executing DAG.' });
        break;
      case 'node_start': {
        if (data.node_id) this.activeNodeId.set(data.node_id);
        const tag = (data.node_kind ?? 'NODE').toUpperCase();
        this.push({
          tone: 'info',
          tag,
          text: `▶ ${data.label ?? data.node_id ?? 'node'}${data.skill_slug ? ` · ${data.skill_slug}` : ''}`,
        });
        break;
      }
      case 'node_end': {
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
          text: `Run finished · status=${data.status ?? 'unknown'}`,
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
