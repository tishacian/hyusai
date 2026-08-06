import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { Subscription, switchMap, timer } from 'rxjs';

import {
  CanonicalApiService,
  type FlowRunnerIngress,
  type FlowRunnerPublished,
  type FlowRunnerRun,
  type FlowRunnerSession,
  type FlowRunnerSessionDetail,
} from '@app/core/canonical-api.service';
import {
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';

export type ParsedRunnerPayload =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; message: string };

/** Parse the Runner editor without coercion. Only JSON objects can satisfy the
 * backend ingress envelope; arrays, primitives and null fail before HTTP. */
export function parseRunnerPayload(raw: string): ParsedRunnerPayload {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ok: false, message: 'Input must be valid JSON.' };
  }
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
    return { ok: false, message: 'Input must be a JSON object.' };
  }
  if (Object.prototype.hasOwnProperty.call(parsed, '_debug')) {
    return {
      ok: false,
      message: '“_debug” is reserved for the Flow Builder debugger.',
    };
  }
  return { ok: true, value: parsed as Record<string, unknown> };
}

export function runnerHasLiveRuns(runs: readonly FlowRunnerRun[]): boolean {
  return runs.some((run) =>
    ['pending', 'running', 'hitl_pending', 'debug_pending', 'waiting_subflows'].includes(
      run.status,
    ),
  );
}

@Component({
  selector: 'app-flow-runner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, IconComponent],
  styles: [
    `
      :host { display: block; min-height: 100%; }
      .runner-shell { max-width: 1440px; margin: 0 auto; padding: 1.5rem; }
      .runner-card { border: 1px solid var(--ck-border, rgba(255,255,255,.1)); background: var(--ck-surface, rgba(10,16,26,.82)); border-radius: .5rem; }
      .runner-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(22rem, .8fr); gap: 1rem; }
      .runner-badge { display: inline-flex; align-items: center; gap: .35rem; padding: .28rem .5rem; border: 1px solid rgba(103,232,249,.22); border-radius: .25rem; color: rgb(165,243,252); background: rgba(8,145,178,.08); font: 600 .68rem/1.1 ui-monospace, monospace; letter-spacing: .05em; }
      .runner-label { display: block; color: rgb(148,163,184); font: 600 .68rem/1.2 ui-monospace, monospace; letter-spacing: .12em; text-transform: uppercase; }
      .runner-input { width: 100%; border: 1px solid rgba(255,255,255,.12); border-radius: .35rem; background: rgba(2,6,23,.72); color: rgb(226,232,240); font: .78rem/1.55 ui-monospace, monospace; outline: none; }
      .runner-input:focus { border-color: rgba(34,211,238,.65); box-shadow: 0 0 0 2px rgba(34,211,238,.08); }
      .runner-button { display: inline-flex; align-items: center; justify-content: center; gap: .45rem; border-radius: .35rem; padding: .65rem .9rem; font-size: .78rem; font-weight: 700; transition: .15s ease; }
      .runner-button:disabled { opacity: .38; cursor: not-allowed; }
      .runner-primary { color: rgb(3,7,18); background: rgb(34,211,238); }
      .runner-secondary { color: rgb(203,213,225); border: 1px solid rgba(255,255,255,.12); background: rgba(255,255,255,.04); }
      .runner-run { border-left: 2px solid rgb(71,85,105); }
      .runner-run[data-status='completed'] { border-left-color: rgb(52,211,153); }
      .runner-run[data-status='failed'], .runner-run[data-status='cancelled'] { border-left-color: rgb(248,113,113); }
      .runner-run[data-status='running'], .runner-run[data-status='pending'] { border-left-color: rgb(34,211,238); }
      @media (max-width: 960px) { .runner-grid { grid-template-columns: 1fr; } .runner-shell { padding: 1rem; } }
    `,
  ],
  template: `
    <main class="runner-shell space-y-4" data-testid="flow-runner">
      <header class="runner-card p-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div>
            <a
              [routerLink]="['/systems', systemId]"
              class="runner-label inline-flex items-center gap-1 hover:text-cyan-300"
            >
              <app-icon name="arrow-left" [size]="12" /> System
            </a>
            <h1 class="mt-2 text-2xl font-semibold text-white">Operator Runner</h1>
            <p class="mt-1 text-sm text-slate-400">
              Durable sessions executing the immutable published Flow only.
            </p>
          </div>
          <button
            type="button"
            class="runner-button runner-secondary"
            (click)="createSession()"
            [disabled]="loading() || sessionLoading() || creatingSession() || submitting() || stalePublishedEvidence()"
            data-testid="runner-new-session"
          >
            <app-icon name="plus" [size]="14" /> New session
          </button>
        </div>

        @if (published(); as flow) {
          <div class="mt-5 flex flex-wrap gap-2" data-testid="runner-published-evidence">
            <span class="runner-badge">PUBLISHED v{{ flow.published_flow_version_id }}</span>
            <span class="runner-badge">SHA {{ shortHash(flow.flow_sha256) }}</span>
            <span class="runner-badge">{{ flow.runtime_mode }}</span>
            <span class="runner-badge">{{ flow.system_status }}</span>
          </div>
        }
      </header>

      @if (loading()) {
        <section class="runner-card p-8 text-center text-sm text-slate-400">
          Loading published execution authority…
        </section>
      } @else if (pageError()) {
        <section class="runner-card border-red-400/30 p-5 text-sm text-red-300" role="alert">
          <p>{{ pageError() }}</p>
          <button
            type="button"
            class="runner-button runner-secondary mt-4"
            (click)="reloadAuthoritativeRunner()"
            [disabled]="loading() || sessionLoading() || creatingSession() || submitting()"
            data-testid="runner-reload-after-error"
          >
            <app-icon name="refresh-cw" [size]="14" /> Reload Runner authority
          </button>
        </section>
      } @else if (published(); as flow) {
        @if (stalePublishedEvidence()) {
          <section
            class="runner-card border-amber-400/30 bg-amber-400/5 p-5 text-sm text-amber-100"
            role="alert"
            data-testid="runner-stale-authority"
          >
            <strong>Published authority changed.</strong>
            <p class="mt-1 text-amber-100/80">
              New Runs are locked until the published version, hash and durable session are reloaded together.
            </p>
            <button
              type="button"
              class="runner-button runner-secondary mt-4"
              (click)="reloadAuthoritativeRunner()"
              [disabled]="loading() || sessionLoading() || creatingSession() || submitting()"
              data-testid="runner-reload-authority"
            >
              <app-icon name="refresh-cw" [size]="14" /> Reload published authority
            </button>
          </section>
        }
        <div class="runner-grid">
          <section class="runner-card p-5 space-y-5">
            <div class="flex flex-wrap items-end gap-3">
              <label class="min-w-0 flex-1">
                <span class="runner-label mb-2">Durable session</span>
                <select
                  class="runner-input px-3 py-2"
                  [ngModel]="selectedSessionId()"
                  (ngModelChange)="openSession($event)"
                  [disabled]="loading() || sessionLoading() || creatingSession() || submitting()"
                  data-testid="runner-session-select"
                >
                  @for (session of sessions(); track session.id) {
                    <option [value]="session.id">{{ session.title || session.id }}</option>
                  }
                </select>
              </label>
              <button
                type="button"
                class="runner-button runner-secondary"
                (click)="refreshSession()"
                [disabled]="!activeSession() || loading() || sessionLoading() || creatingSession() || submitting()"
                aria-label="Refresh session Runs"
              >
                <app-icon name="refresh-cw" [size]="14" /> Refresh
              </button>
            </div>

            <label>
              <span class="runner-label mb-2">Published manual ingress</span>
              <select
                class="runner-input px-3 py-2"
                [(ngModel)]="selectedIngressId"
                [disabled]="loading() || sessionLoading() || creatingSession() || submitting() || stalePublishedEvidence()"
                data-testid="runner-ingress-select"
              >
                @for (ingress of flow.ingresses; track ingress.ingress_id) {
                  <option [value]="ingress.ingress_id">{{ ingress.ingress_id }}</option>
                }
              </select>
            </label>

            @if (selectedIngress(); as ingress) {
              <div>
                <span class="runner-label mb-2">Input contract</span>
                <pre class="runner-input max-h-44 overflow-auto p-3 text-[11px]">{{ formatJson(ingress.input_schema || {}) }}</pre>
              </div>
            } @else {
              <p class="rounded border border-amber-400/25 bg-amber-400/5 p-3 text-sm text-amber-200">
                This published Flow has no manual ingress. Add and publish one before using the operator Runner.
              </p>
            }

            <label>
              <span class="runner-label mb-2">JSON input</span>
              <textarea
                class="runner-input min-h-56 resize-y p-3"
                [(ngModel)]="inputJson"
                (ngModelChange)="inputError.set(null)"
                [disabled]="loading() || sessionLoading() || creatingSession() || submitting()"
                spellcheck="false"
                data-testid="runner-json-input"
              ></textarea>
            </label>
            @if (inputError()) {
              <p class="text-sm text-red-300" role="alert" data-testid="runner-input-error">
                {{ inputError() }}
              </p>
            }
            <button
              type="button"
              class="runner-button runner-primary w-full"
              (click)="execute()"
              [disabled]="!canExecute()"
              data-testid="runner-execute"
            >
              <app-icon name="play" [size]="14" />
              {{ submitting() ? 'Queueing…' : 'Execute published Flow' }}
            </button>
          </section>

          <section class="runner-card p-5">
            <div class="flex items-center justify-between gap-3">
              <div>
                <span class="runner-label">Session ledger</span>
                <h2 class="mt-1 text-lg font-semibold text-white">Runs</h2>
              </div>
              <span class="runner-badge">{{ runs().length }}</span>
            </div>

            <div class="mt-4 space-y-3" data-testid="runner-runs">
              @for (run of runs(); track run.id) {
                <article
                  class="runner-run rounded bg-slate-950/40 p-4"
                  [attr.data-status]="run.status"
                >
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <a
                      [routerLink]="['/runs', run.id]"
                      class="font-mono text-xs text-cyan-300 hover:text-cyan-200"
                    >{{ run.id }}</a>
                    <span class="runner-badge">{{ run.status }}</span>
                  </div>
                  <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px] text-slate-500">
                    <span>{{ run.runtime_mode }}</span>
                    <span>{{ shortHash(run.flow_sha256) }}</span>
                    @if (run.duration_ms != null) { <span>{{ run.duration_ms }} ms</span> }
                  </div>
                  @if (run.error) {
                    <p class="mt-3 text-sm text-red-300">{{ run.error }}</p>
                  }
                  @if (run.status === 'completed' || run.status === 'failed') {
                    <pre class="runner-input mt-3 max-h-64 overflow-auto p-3 text-[11px]">{{ formatJson(run.output_ref) }}</pre>
                  }
                </article>
              } @empty {
                <p class="py-10 text-center text-sm text-slate-500">
                  No Run in this durable session yet.
                </p>
              }
            </div>
          </section>
        </div>
      }
    </main>
  `,
})
export class FlowRunnerComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService, { optional: true });
  private pollingSubscription?: Subscription;
  private overviewRequest?: Subscription;
  private sessionRequest?: Subscription;
  private createSessionRequest?: Subscription;
  private runRequest?: Subscription;
  private overviewGeneration = 0;
  private sessionGeneration = 0;
  private createSessionGeneration = 0;
  private runGeneration = 0;
  private readonly unregisterWorkspaceReset = this.workspace?.registerContextReset(() => {
    this.resetForWorkspaceChange();
  });

  readonly systemId = this.route.snapshot.paramMap.get('systemId') ?? '';
  readonly loading = signal(true);
  readonly sessionLoading = signal(false);
  readonly creatingSession = signal(false);
  readonly submitting = signal(false);
  readonly pageError = signal<string | null>(null);
  readonly inputError = signal<string | null>(null);
  readonly published = signal<FlowRunnerPublished | null>(null);
  readonly sessions = signal<FlowRunnerSession[]>([]);
  readonly activeSession = signal<FlowRunnerSession | null>(null);
  readonly runs = signal<FlowRunnerRun[]>([]);
  readonly selectedSessionId = signal('');
  readonly stalePublishedEvidence = signal(false);

  selectedIngressId = '';
  inputJson = '{\n  "query": ""\n}';

  ngOnInit(): void {
    if (!this.systemId) {
      this.pageError.set('System id is missing.');
      this.loading.set(false);
      return;
    }
    this.loadOverview();
  }

  ngOnDestroy(): void {
    this.cancelRequests();
    this.unregisterWorkspaceReset?.();
  }

  selectedIngress(): FlowRunnerIngress | null {
    return (
      this.published()?.ingresses.find(
        (ingress) => ingress.ingress_id === this.selectedIngressId,
      ) ?? null
    );
  }

  canExecute(): boolean {
    const session = this.activeSession();
    return Boolean(
      session
      && this.selectedSessionId() === session.id
      && session.status === 'active'
      && this.selectedIngress()
      && this.published()?.system_status === 'active'
      && !this.loading()
      && !this.sessionLoading()
      && !this.creatingSession()
      && !this.submitting()
      && !this.stalePublishedEvidence()
      && !this.pageError()
    );
  }

  createSession(): void {
    if (
      this.creatingSession()
      || this.loading()
      || this.sessionLoading()
      || this.submitting()
      || this.stalePublishedEvidence()
    ) return;
    this.stopPolling();
    this.createSessionRequest?.unsubscribe();
    const generation = ++this.createSessionGeneration;
    const scope = this.captureWorkspaceScope();
    this.creatingSession.set(true);
    this.sessionLoading.set(true);
    this.selectedSessionId.set('');
    this.activeSession.set(null);
    this.runs.set([]);
    this.pageError.set(null);
    const request = this.api.createFlowRunnerSession(this.systemId).subscribe({
      next: (detail) => {
        if (!this.createRequestIsCurrent(scope, generation)) return;
        if (!this.detailMatchesRequest(detail, detail.session.id)) {
          this.failClosedSessionLoad('Runner returned a session outside the requested System authority.');
          this.creatingSession.set(false);
          return;
        }
        this.applyDetail(detail);
        this.creatingSession.set(false);
        this.sessionLoading.set(false);
      },
      error: (error: unknown) => {
        if (!this.createRequestIsCurrent(scope, generation)) return;
        this.pageError.set(this.errorMessage(error));
        this.creatingSession.set(false);
        this.sessionLoading.set(false);
      },
    });
    this.createSessionRequest = request.closed ? undefined : request;
  }

  openSession(sessionId: string): void {
    if (!sessionId || this.submitting() || this.creatingSession()) return;
    if (
      sessionId === this.activeSession()?.id
      && sessionId === this.selectedSessionId()
      && !this.sessionLoading()
    ) return;
    this.selectedSessionId.set(sessionId);
    this.loadSession(sessionId, { clearStaleOnSuccess: false });
  }

  refreshSession(): void {
    const sessionId = this.activeSession()?.id;
    if (sessionId && !this.submitting() && !this.creatingSession()) {
      this.loadSession(sessionId, { clearStaleOnSuccess: false });
    }
  }

  reloadAuthoritativeRunner(): void {
    if (
      !this.systemId
      || this.loading()
      || this.sessionLoading()
      || this.creatingSession()
      || this.submitting()
    ) return;
    const preferredSessionId = this.selectedSessionId() || this.activeSession()?.id || null;
    this.loadOverview(preferredSessionId, true);
  }

  execute(): void {
    const session = this.activeSession();
    const flow = this.published();
    if (!this.canExecute() || !session || !flow || !this.selectedIngress()) return;
    const parsed = parseRunnerPayload(this.inputJson);
    if (!parsed.ok) {
      this.inputError.set(parsed.message);
      return;
    }
    this.inputError.set(null);
    this.submitting.set(true);
    this.runRequest?.unsubscribe();
    const generation = ++this.runGeneration;
    const scope = this.captureWorkspaceScope();
    const request = this.api
      .createFlowRunnerRun(this.systemId, session.id, {
        ingress_id: this.selectedIngressId,
        payload: parsed.value,
        expected_published_version_id: flow.published_flow_version_id,
        expected_flow_sha256: flow.flow_sha256,
      })
      .subscribe({
        next: (run) => {
          if (!this.runRequestIsCurrent(scope, generation, session.id)) return;
          if (run.system_id !== this.systemId || run.runner_session_id !== session.id) {
            this.inputError.set('Runner returned a Run outside the selected durable session.');
            this.submitting.set(false);
            return;
          }
          this.runs.update((runs) => [run, ...runs.filter((row) => row.id !== run.id)]);
          this.submitting.set(false);
          this.startPolling();
        },
        error: (error: unknown) => {
          if (!this.runRequestIsCurrent(scope, generation, session.id)) return;
          if (error instanceof HttpErrorResponse && error.status === 409) {
            this.stalePublishedEvidence.set(true);
          }
          this.inputError.set(this.errorMessage(error));
          this.submitting.set(false);
        },
      });
    this.runRequest = request.closed ? undefined : request;
  }

  shortHash(value: string): string {
    return value ? `${value.slice(0, 12)}…` : 'unavailable';
  }

  formatJson(value: unknown): string {
    return JSON.stringify(value ?? {}, null, 2);
  }

  private loadOverview(
    preferredSessionId: string | null = null,
    clearStaleAfterSession = false,
  ): void {
    this.stopPolling();
    this.overviewRequest?.unsubscribe();
    this.sessionRequest?.unsubscribe();
    this.createSessionRequest?.unsubscribe();
    const generation = ++this.overviewGeneration;
    ++this.sessionGeneration;
    ++this.createSessionGeneration;
    const scope = this.captureWorkspaceScope();
    this.loading.set(true);
    this.sessionLoading.set(true);
    this.pageError.set(null);
    const request = this.api.getFlowRunner(this.systemId).subscribe({
      next: (overview) => {
        if (!this.overviewRequestIsCurrent(scope, generation)) return;
        if (overview.published.system_id !== this.systemId) {
          this.loading.set(false);
          this.failClosedSessionLoad('Runner returned published authority for another System.');
          return;
        }
        this.published.set(overview.published);
        this.sessions.set(overview.sessions);
        this.alignIngress(overview.published);
        this.loading.set(false);
        const selected = preferredSessionId
          ? overview.sessions.find((session) => session.id === preferredSessionId)
          : null;
        const target = selected ?? overview.sessions[0];
        if (target) {
          this.selectedSessionId.set(target.id);
          this.loadSession(target.id, { clearStaleOnSuccess: clearStaleAfterSession });
        } else {
          this.sessionLoading.set(false);
          this.selectedSessionId.set('');
          this.activeSession.set(null);
          this.runs.set([]);
          // The overview itself is authoritative. With no surviving session,
          // release only the stale evidence latch; Execute remains blocked by
          // the absence of an active durable session.
          if (clearStaleAfterSession) this.stalePublishedEvidence.set(false);
          this.createSession();
        }
      },
      error: (error: unknown) => {
        if (!this.overviewRequestIsCurrent(scope, generation)) return;
        this.pageError.set(this.errorMessage(error));
        this.loading.set(false);
        this.sessionLoading.set(false);
        this.activeSession.set(null);
      },
    });
    this.overviewRequest = request.closed ? undefined : request;
  }

  private loadSession(
    sessionId: string,
    options: { clearStaleOnSuccess: boolean },
  ): void {
    this.stopPolling();
    this.sessionRequest?.unsubscribe();
    const generation = ++this.sessionGeneration;
    const scope = this.captureWorkspaceScope();
    const switching = this.activeSession()?.id !== sessionId;
    this.selectedSessionId.set(sessionId);
    this.sessionLoading.set(true);
    this.pageError.set(null);
    if (switching) {
      this.activeSession.set(null);
      this.runs.set([]);
    }
    const request = this.api.getFlowRunnerSession(this.systemId, sessionId).subscribe({
      next: (detail) => {
        if (!this.sessionRequestIsCurrent(scope, generation, sessionId)) return;
        if (!this.detailMatchesRequest(detail, sessionId)) {
          this.failClosedSessionLoad('Runner returned authority for another durable session.');
          return;
        }
        this.applyDetail(detail);
        this.sessionLoading.set(false);
        this.pageError.set(null);
        if (options.clearStaleOnSuccess) {
          this.stalePublishedEvidence.set(false);
          this.inputError.set(null);
        }
        if (runnerHasLiveRuns(detail.runs)) this.startPolling();
      },
      error: (error: unknown) => {
        if (!this.sessionRequestIsCurrent(scope, generation, sessionId)) return;
        this.pageError.set(this.errorMessage(error));
        this.sessionLoading.set(false);
        this.activeSession.set(null);
      },
    });
    this.sessionRequest = request.closed ? undefined : request;
  }

  private applyDetail(detail: FlowRunnerSessionDetail): void {
    this.published.set(detail.published);
    this.activeSession.set(detail.session);
    this.runs.set(detail.runs);
    this.selectedSessionId.set(detail.session.id);
    this.sessions.update((sessions) => [
      detail.session,
      ...sessions.filter((session) => session.id !== detail.session.id),
    ]);
    this.alignIngress(detail.published);
  }

  private alignIngress(flow: FlowRunnerPublished): void {
    if (!flow.ingresses.some((ingress) => ingress.ingress_id === this.selectedIngressId)) {
      this.selectedIngressId = flow.ingresses[0]?.ingress_id ?? '';
    }
  }

  private startPolling(): void {
    const sessionId = this.activeSession()?.id;
    if (!sessionId) return;
    this.stopPolling();
    const scope = this.captureWorkspaceScope();
    this.pollingSubscription = timer(1200, 1800)
      .pipe(
        switchMap(() => this.api.getFlowRunnerSession(this.systemId, sessionId)),
      )
      .subscribe({
        next: (detail) => {
          if (
            !this.isWorkspaceScopeCurrent(scope)
            || this.activeSession()?.id !== sessionId
            || this.selectedSessionId() !== sessionId
            || this.sessionLoading()
            || !this.detailMatchesRequest(detail, sessionId)
          ) return;
          this.applyDetail(detail);
          if (!runnerHasLiveRuns(detail.runs)) this.stopPolling();
        },
        error: () => this.stopPolling(),
      });
  }

  private stopPolling(): void {
    this.pollingSubscription?.unsubscribe();
    this.pollingSubscription = undefined;
  }

  private cancelRequests(): void {
    this.stopPolling();
    this.overviewRequest?.unsubscribe();
    this.sessionRequest?.unsubscribe();
    this.createSessionRequest?.unsubscribe();
    this.runRequest?.unsubscribe();
    this.overviewRequest = undefined;
    this.sessionRequest = undefined;
    this.createSessionRequest = undefined;
    this.runRequest = undefined;
    ++this.overviewGeneration;
    ++this.sessionGeneration;
    ++this.createSessionGeneration;
    ++this.runGeneration;
  }

  private resetForWorkspaceChange(): void {
    this.cancelRequests();
    this.loading.set(false);
    this.sessionLoading.set(false);
    this.creatingSession.set(false);
    this.submitting.set(false);
    this.published.set(null);
    this.sessions.set([]);
    this.activeSession.set(null);
    this.runs.set([]);
    this.selectedSessionId.set('');
    this.selectedIngressId = '';
    this.stalePublishedEvidence.set(false);
    this.inputError.set(null);
    this.pageError.set('Workspace changed. Reload Runner authority before continuing.');
  }

  private failClosedSessionLoad(message: string): void {
    this.stopPolling();
    this.sessionLoading.set(false);
    this.activeSession.set(null);
    this.runs.set([]);
    this.pageError.set(message);
  }

  private detailMatchesRequest(
    detail: FlowRunnerSessionDetail,
    sessionId: string,
  ): boolean {
    return detail.session.id === sessionId && detail.published.system_id === this.systemId;
  }

  private captureWorkspaceScope(): WorkspaceRequestScope | null {
    return this.workspace?.captureRequestScope() ?? null;
  }

  private isWorkspaceScopeCurrent(scope: WorkspaceRequestScope | null): boolean {
    return scope === null || !this.workspace || this.workspace.isRequestScopeCurrent(scope);
  }

  private overviewRequestIsCurrent(
    scope: WorkspaceRequestScope | null,
    generation: number,
  ): boolean {
    return this.isWorkspaceScopeCurrent(scope) && generation === this.overviewGeneration;
  }

  private sessionRequestIsCurrent(
    scope: WorkspaceRequestScope | null,
    generation: number,
    sessionId: string,
  ): boolean {
    return this.isWorkspaceScopeCurrent(scope)
      && generation === this.sessionGeneration
      && this.selectedSessionId() === sessionId;
  }

  private createRequestIsCurrent(
    scope: WorkspaceRequestScope | null,
    generation: number,
  ): boolean {
    return this.isWorkspaceScopeCurrent(scope) && generation === this.createSessionGeneration;
  }

  private runRequestIsCurrent(
    scope: WorkspaceRequestScope | null,
    generation: number,
    sessionId: string,
  ): boolean {
    return this.isWorkspaceScopeCurrent(scope)
      && generation === this.runGeneration
      && this.activeSession()?.id === sessionId
      && this.selectedSessionId() === sessionId
      && !this.sessionLoading();
  }

  private errorMessage(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detail = error.error?.detail ?? error.error;
      if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
        return detail.message;
      }
      if (typeof detail === 'string') return detail;
      if (error.status === 404) {
        return 'The published Runner is unavailable for this workspace or System.';
      }
      if (error.status === 409) {
        return 'Published Flow evidence changed. Reload the Runner before executing.';
      }
      if (error.status === 422) return 'Input does not satisfy the published ingress contract.';
    }
    return error instanceof Error ? error.message : 'Runner request failed.';
  }
}
