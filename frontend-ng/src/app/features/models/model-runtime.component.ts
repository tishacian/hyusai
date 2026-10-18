import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ModelRuntimeService } from './model-runtime.service';
import {
  activeJob, gapLines, lastAttempt, runtimeActions, runtimeErrorKey, runtimeReasonKey,
  runtimeStatusKey, runtimeTone, type RuntimeState,
} from './model-runtime.vm';

/** Seconds between two reads while a capture or requalification is in flight. */
const POLL_MS = 3000;
/** A requalification is bounded server-side; the card stops asking after this. */
const POLL_LIMIT = 120;

@Component({
  selector: 'ck-model-runtime', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section data-testid="model-runtime" [attr.data-tone]="tone()">
      <h4>{{ t('title') }}</h4>
      <p>{{ t('hint') }}</p>
      @if (state(); as s) {
        <p class="status" data-testid="runtime-status">{{ i18n.t(statusKey()) }}</p>
        @if (reasonKey(); as reason) { <p>{{ i18n.t(reason) }}</p> }
        @if (s.differences.length) {
          <table data-testid="runtime-differences">
            <thead><tr><th>{{ t('package') }}</th><th>{{ t('producer') }}</th><th>{{ t('reader') }}</th></tr></thead>
            <tbody>
              @for (row of s.differences; track row.package) {
                <tr><td class="ck-mono">{{ row.package }}</td><td class="ck-mono">{{ row.producer ?? '—' }}</td><td class="ck-mono">{{ row.reader ?? '—' }}</td></tr>
              }
            </tbody>
          </table>
        }
        @if (s.supported) {
          <p data-testid="runtime-reference">{{ s.reference.status === 'stored'
            ? i18n.t('models.runtime.reference.stored', { rows: s.reference.rows ?? 0, date: day(s.reference.captured_at) })
            : i18n.t('models.runtime.reference.missing') }}</p>
        }
        @if (last(); as attempt) {
          <div class="attempt" data-testid="runtime-attempt">
            <p>{{ i18n.t(attempt.verdict === 'qualified'
              ? (attempt.active ? 'models.runtime.attempt.qualified' : 'models.runtime.attempt.revoked')
              : 'models.runtime.attempt.failed', { date: day(attempt.created_at), rows: attempt.rows_compared }) }}</p>
            @if (attemptError(); as error) { <p>{{ i18n.t(error) }}</p> }
            @for (line of gaps(); track line.key) { <p class="ck-mono">{{ i18n.t(line.key, line.params) }}</p> }
          </div>
        }
        @if (pending(); as job) { <p role="status">{{ i18n.t(job.kind === 'ml_reference_capture' ? 'models.runtime.busy.capture' : 'models.runtime.busy.requalify') }}</p> }
        @if (canRequalify()) {
          <div class="actions">
            @if (actions().capture) { <button type="button" data-testid="runtime-capture" (click)="capture()">{{ t('capture') }}</button> }
            @if (actions().requalify) { <button type="button" data-testid="runtime-requalify" (click)="requalify()">{{ t('requalify') }}</button> }
            @if (actions().revoke; as id) {
              <button type="button" data-testid="runtime-revoke" [title]="t('revoke_hint')" (click)="revoke(id)">{{ t('revoke') }}</button>
            }
          </div>
        }
      } @else if (!error()) { <p role="status">{{ t('loading') }}</p> }
      @if (error()) { <p role="alert">{{ i18n.t(error()) }}</p> }
    </section>
  `,
  styles: [`
    section{padding:12px;border:1px solid var(--ck-stroke-2);border-radius:6px;margin:12px 0;font-size:12px}
    h4{margin:0 0 8px;font-size:13px} p{color:var(--ck-fg-3);line-height:1.5;margin:4px 0}
    .status{color:var(--ck-fg-1);font-weight:500}
    [data-tone=warn] .status{color:var(--ck-signal-warn)} [data-tone=neg] .status{color:var(--ck-signal-neg)}
    table{border-collapse:collapse;margin:8px 0} th,td{padding:2px 12px 2px 0;text-align:left} th{color:var(--ck-fg-3);font-weight:500}
    .attempt{border-top:1px solid var(--ck-stroke-2);margin-top:8px;padding-top:4px}
    .actions{display:flex;gap:8px;margin-top:8px}
    button{padding:8px 12px;background:var(--ck-bg-2);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:4px;cursor:pointer}
    [role=alert]{color:var(--ck-signal-neg)}
  `],
})
export class ModelRuntimeComponent {
  readonly modelId = input.required<string>();
  readonly ready = input(false);
  /** `serving.permissions.requalify` from M1; never inferred from a role here. */
  readonly canRequalify = input(false);
  protected readonly i18n = inject(I18nService);
  private readonly api = inject(ModelRuntimeService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  readonly state = signal<RuntimeState | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  protected readonly statusKey = computed(() => runtimeStatusKey(this.state()));
  protected readonly reasonKey = computed(() => runtimeReasonKey(this.state()?.reason));
  protected readonly tone = computed(() => runtimeTone(this.state()));
  protected readonly last = computed(() => lastAttempt(this.state()));
  protected readonly gaps = computed(() => gapLines(this.last()));
  protected readonly attemptError = computed(() => runtimeErrorKey(this.last()?.error_code));
  protected readonly pending = computed(() => activeJob(this.state()));
  protected readonly actions = computed(() => runtimeActions(this.state(), this.canRequalify(), this.busy()));
  private generation = 0;
  private polls = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    effect(() => { this.modelId(); this.ready(); this.reset(); if (this.ready()) void this.load(); });
    const unregister = this.workspace.registerContextReset(() => this.reset());
    this.destroyRef.onDestroy(() => { this.reset(); unregister(); });
  }

  protected t(key: string): string { return this.i18n.t('models.runtime.' + key); }

  protected day(value: string | null | undefined): string {
    return value ? value.slice(0, 16).replace('T', ' ') : '—';
  }

  private reset(): void {
    this.generation++; this.polls = 0;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.state.set(null); this.busy.set(false); this.error.set('');
  }

  private current(): () => boolean {
    const generation = this.generation, model = this.modelId();
    return () => generation === this.generation && model === this.modelId();
  }

  async load(): Promise<void> {
    const current = this.current();
    try {
      const state = await this.api.state(this.modelId());
      if (!state || !current()) return;
      this.state.set(state); this.error.set('');
      this.schedule();
    } catch {
      if (current()) this.error.set('models.runtime.error.generic');
    }
  }

  /** Re-read while server work is in flight; bounded, and cancelled on any reset. */
  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (!activeJob(this.state()) || this.polls >= POLL_LIMIT) return;
    this.polls++;
    const generation = this.generation;
    this.timer = setTimeout(() => { if (generation === this.generation) void this.load(); }, POLL_MS);
  }

  capture(): Promise<void> { return this.submit(() => this.api.capture(this.modelId()), 'capture'); }

  requalify(): Promise<void> { return this.submit(() => this.api.requalify(this.modelId()), 'requalify'); }

  revoke(attestationId: string): Promise<void> {
    if (this.actions().revoke !== attestationId) return Promise.resolve();
    return this.submit(() => this.api.revoke(this.modelId(), attestationId), 'revoke');
  }

  private async submit(call: () => Promise<{ runtime: RuntimeState } | null>, action: 'capture' | 'requalify' | 'revoke'): Promise<void> {
    if (this.busy() || !this.canRequalify() || !this.actions()[action]) return;
    const current = this.current();
    this.busy.set(true); this.error.set('');
    try {
      const result = await call();
      if (!result || !current()) return;
      this.polls = 0;
      this.state.set(result.runtime);
      this.schedule();
    } catch (failure) {
      if (!current()) return;
      const code = failure instanceof HttpErrorResponse ? failure.error?.detail?.code : null;
      this.error.set(runtimeErrorKey(code) ?? 'models.runtime.error.generic');
    } finally {
      if (current()) this.busy.set(false);
    }
  }
}
