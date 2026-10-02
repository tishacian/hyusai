import { Component, ChangeDetectionStrategy, computed, effect, inject, input, output, signal, DestroyRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { AuthStore } from '@app/store/auth.store';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { CLAIM_ACTION_LABELS } from './claim-run';

interface Trial { id: string; claim_id: string; pair_id: string; condition: 'manual' | 'assisted'; state: string; operator_id: string; events: unknown[]; active_human_seconds: number | null; result: { action: string; amount: string; references: string[]; run_ids: string[] } | null; review: { passed: boolean } | null; }
interface Pair { pair_id: string; first_condition: 'manual' | 'assisted'; manual_claim_id: string; assisted_claim_id: string; }
interface Benchmark { state: string; hourly_eur: string; planned_pairs: number; completed_quality_pairs: number; capacity_value_eur: string | null; incremental_cost_eur: string | null; net_benefit_eur: string | null; roi: string | null; median_difference_seconds: number | null; protocol_sha256: string; trials: Trial[]; protocol: { version: string; pairs: Pair[] }; }

@Component({
  selector: 'app-claims-benchmark', standalone: true, imports: [FormsModule, NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [`:host{display:block;margin:24px 32px}.benchmark{padding:20px;border:1px solid var(--ck-stroke-2);border-radius:8px;background:var(--ck-bg-panel);color:var(--ck-fg-1)}summary{cursor:pointer;font-weight:600}p,li,label{font-size:13px;line-height:1.6}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:20px 0}.metrics span{display:block;font-size:12px;color:var(--ck-fg-2)}.metrics strong{display:block;font-size:22px;margin-top:8px}.controls{display:flex;flex-wrap:wrap;align-items:end;gap:12px;margin:16px 0}label{display:flex;flex-direction:column;gap:6px}input,select,textarea,button{font:inherit;color:inherit;border:1px solid var(--ck-stroke-2);border-radius:4px;padding:10px;background:var(--ck-bg-inset)}button{cursor:pointer;min-height:40px}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}button:disabled{opacity:.5}table{width:100%;border-collapse:collapse;font-size:12px}td,th{text-align:start;padding:10px;border-bottom:1px solid var(--ck-stroke-2)}.table-wrap{overflow:auto}.proofs{display:flex;flex-wrap:wrap;gap:12px}.proofs label{flex-direction:row;align-items:center}.quiet{color:var(--ck-fg-2)}.error{color:var(--ck-signal-danger)}@media(max-width:760px){:host{margin:16px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}`],
  template: `
    @if (data(); as benchmark) {
      <details class="benchmark" [open]="readOnly()" data-testid="claims-benchmark">
        <summary>{{ i18n.t('experience.claims.benchmark.title') }} · {{ benchmark.completed_quality_pairs }}/{{ benchmark.planned_pairs }}</summary>
        <p>{{ i18n.t('experience.claims.benchmark.protocol') }}</p>
        <p class="quiet">{{ i18n.t('experience.claims.benchmark.convention') }}</p>
        <div class="metrics" aria-live="polite">
          <div><span>{{ i18n.t('experience.claims.benchmark.capacity') }}</span><strong>{{ money(benchmark.capacity_value_eur) }}</strong></div>
          <div><span>{{ i18n.t('experience.claims.benchmark.cost') }}</span><strong>{{ money(benchmark.incremental_cost_eur) }}</strong></div>
          <div><span>{{ i18n.t('experience.claims.benchmark.net') }}</span><strong>{{ money(benchmark.net_benefit_eur) }}</strong></div>
          <div><span>{{ i18n.t('experience.claims.benchmark.roi') }}</span><strong>{{ percent(benchmark.roi) }}</strong></div>
        </div>
        @if (benchmark.state !== 'measured') { <p role="status">{{ i18n.t(benchmark.state === 'awaiting_costs' ? 'experience.claims.benchmark.awaiting_costs' : 'experience.claims.benchmark.unmeasured') }}</p> }
        @if (!readOnly()) {
          <div class="controls">
            <label>{{ i18n.t('experience.claims.benchmark.pair') }}<select [(ngModel)]="pairId" [disabled]="busy() || !!active()">@for (pair of benchmark.protocol.pairs; track pair.pair_id) { <option [value]="pair.pair_id">{{ pair.pair_id }}</option> }</select></label>
            <label>{{ i18n.t('experience.claims.benchmark.condition') }}<select [(ngModel)]="condition" [disabled]="busy() || !!active()"><option value="manual">{{ i18n.t('experience.claims.benchmark.manual') }}</option><option value="assisted">{{ i18n.t('experience.claims.benchmark.assisted') }}</option></select></label>
            <button [disabled]="busy() || !!active()" (click)="start()">{{ i18n.t('experience.claims.benchmark.start') }}</button>
          </div>
          @if (active(); as trial) {
            <p role="status"><strong>{{ trial.claim_id }} · {{ i18n.t(trial.condition === 'manual' ? 'experience.claims.benchmark.manual' : 'experience.claims.benchmark.assisted') }}</strong> · {{ i18n.t(trial.state === 'paused' ? 'experience.claims.benchmark.paused' : 'experience.claims.benchmark.active') }}</p>
            <p>{{ i18n.t('experience.claims.benchmark.timing_notice') }}</p>
            <div class="controls"><button [disabled]="busy()" (click)="event(trial.state === 'paused' ? 'resume' : 'pause')">{{ i18n.t(trial.state === 'paused' ? 'experience.claims.benchmark.resume' : 'experience.claims.benchmark.pause') }}</button></div>
            <div class="controls">
              <label>{{ i18n.t('experience.claims.benchmark.outcome') }}<select [(ngModel)]="action"><option value="">{{ i18n.t('experience.claims.benchmark.choose') }}</option>@for (option of actionOptions; track option) { <option [value]="option">{{ i18n.t(actionLabel(option)) }}</option> }<option value="failed">{{ i18n.t('experience.claims.benchmark.failed') }}</option></select></label>
              <label>{{ i18n.t('experience.claims.benchmark.amount') }}<input [(ngModel)]="amount" inputmode="decimal" /></label>
              <label>{{ i18n.t('experience.claims.benchmark.note') }}<textarea [(ngModel)]="note" maxlength="2000"></textarea></label>
            </div>
            <div class="proofs">@for (source of sources(); track source.reference) { <label><input type="checkbox" [checked]="references.includes(source.reference)" (change)="toggle(source.reference)" />{{ source.filename }}</label> }</div>
            <div class="controls"><button [disabled]="busy() || !action || !amount || !note.trim()" (click)="event('finish')">{{ i18n.t('experience.claims.benchmark.finish') }}</button></div>
          }
          <p class="quiet">{{ i18n.t('experience.claims.benchmark.review_notice') }}</p>
          <div class="controls">
            <label>{{ i18n.t('experience.claims.benchmark.review') }}<select [(ngModel)]="reviewId"><option value="">{{ i18n.t('experience.claims.benchmark.choose') }}</option>@for (trial of unreviewed(); track trial.id) { <option [value]="trial.id">{{ trial.claim_id }} · {{ trial.condition }}</option> }</select></label>
            <label>{{ i18n.t('experience.claims.benchmark.note') }}<textarea [(ngModel)]="reviewNote" maxlength="2000"></textarea></label>
            <button [disabled]="busy() || !reviewId || reviewNote.trim().length < 10" (click)="review(true)">{{ i18n.t('experience.claims.benchmark.quality_pass') }}</button>
            <button [disabled]="busy() || !reviewId || reviewNote.trim().length < 10" (click)="review(false)">{{ i18n.t('experience.claims.benchmark.quality_fail') }}</button>
          </div>
        }
        @if (problem()) { <p class="error" role="alert">{{ i18n.t('experience.claims.benchmark.error') }}</p> }
        @if (!readOnly()) { @for (trial of corrections(); track trial.id) { <button [disabled]="busy() || !!active()" (click)="reopen(trial)">{{ i18n.t('experience.claims.benchmark.resume') }} · {{ trial.claim_id }}</button> } }
        <div class="table-wrap"><table><thead><tr><th>{{ i18n.t('experience.claims.benchmark.pair') }}</th><th>{{ i18n.t('experience.claims.dossier') }}</th><th>{{ i18n.t('experience.claims.benchmark.condition') }}</th><th>{{ i18n.t('experience.claims.benchmark.time') }}</th><th>{{ i18n.t('experience.claims.benchmark.quality') }}</th><th>{{ i18n.t('experience.claims.trace') }}</th></tr></thead><tbody>
          @for (trial of benchmark.trials; track trial.id) { <tr><td>{{ trial.pair_id }}</td><td>{{ trial.claim_id }}</td><td>{{ i18n.t(trial.condition === 'manual' ? 'experience.claims.benchmark.manual' : 'experience.claims.benchmark.assisted') }}</td><td>{{ trial.active_human_seconds === null ? i18n.t('experience.claims.unknown') : trial.active_human_seconds.toFixed(1) + ' s' }}</td><td>{{ i18n.t(trial.review ? (trial.review.passed ? 'experience.claims.benchmark.quality_pass' : 'experience.claims.benchmark.quality_fail') : 'experience.claims.benchmark.awaiting_review') }}</td><td>@for (id of trial.result?.run_ids ?? []; track id) { <a [navLink]="{ type: 'run', lens: 'operate', ref: id }">{{ i18n.t('experience.claims.trace') }}</a> }</td></tr> }
        </tbody></table></div>
        <button [disabled]="busy()" (click)="load()">{{ i18n.t('experience.claims.retry') }}</button>
        <p class="quiet">{{ benchmark.protocol.version }} · {{ benchmark.protocol_sha256 }}</p>
      </details>
    }
  `,
})
export class ClaimsBenchmarkComponent {
  readonly i18n = inject(I18nService); private readonly api = inject(ApiService); private readonly workspace = inject(WorkspaceService); private readonly auth = inject(AuthStore); private readonly destroy = inject(DestroyRef);
  readonly readOnly = input(false); readonly sources = input<Array<{ reference: string; filename: string }>>([]);
  readonly caseSelected = output<string>(); readonly manualActive = output<boolean>();
  readonly data = signal<Benchmark | null>(null); readonly active = signal<Trial | null>(null); readonly busy = signal(false); readonly problem = signal(false);
  readonly unreviewed = computed(() => this.data()?.trials.filter(t => t.state === 'finished' && !t.review && t.operator_id !== this.auth.userId()) ?? []);
  readonly corrections = computed(() => this.data()?.trials.filter(t => t.operator_id === this.auth.userId() && t.state === 'finished' && t.review?.passed === false) ?? []);
  readonly actionOptions = Object.keys(CLAIM_ACTION_LABELS);
  pairId = 'P01'; condition: 'manual' | 'assisted' = 'manual'; action = ''; amount = ''; note = ''; references: string[] = []; reviewId = ''; reviewNote = '';
  private generation = 0;
  constructor() { effect(() => { this.workspace.current()?.id; this.auth.authEpoch(); this.active.set(null); this.manualActive.emit(false); void this.load(); }); this.destroy.onDestroy(() => this.generation++); }
  async load(): Promise<void> { const g = ++this.generation; this.data.set(null); try { const data = await firstValueFrom(this.api.get<Benchmark>('/ecommerce-claims/benchmark')); if (g === this.generation) { this.data.set(data); const trial = data.trials.find(t => t.operator_id === this.auth.userId() && ['active', 'paused'].includes(t.state)); this.active.set(trial ?? null); this.manualActive.emit(trial?.condition === 'manual'); if (trial && !this.readOnly()) this.caseSelected.emit(trial.claim_id); } } catch { /* Unavailable outside released, configured workspaces. */ } }
  private async mutate(path: string, body: unknown): Promise<void> {
    const g = this.generation; this.busy.set(true); this.problem.set(false);
    try { const trial = await firstValueFrom(this.api.post<Trial>(path, body)); if (g !== this.generation) return;
      const active = ['active', 'paused'].includes(trial.state) ? trial : null; this.active.set(active); this.manualActive.emit(active?.condition === 'manual');
      if (active) this.caseSelected.emit(active.claim_id);
      const data = await firstValueFrom(this.api.get<Benchmark>('/ecommerce-claims/benchmark')); if (g === this.generation) { this.data.set(data); const current = data.trials.find(t => t.operator_id === this.auth.userId() && ['active', 'paused'].includes(t.state)); this.active.set(current ?? null); this.manualActive.emit(current?.condition === 'manual'); }
    } catch { if (g === this.generation) this.problem.set(true); } finally { if (g === this.generation) this.busy.set(false); }
  }
  start(): void { this.action = ''; this.amount = ''; this.note = ''; this.references = []; void this.mutate('/ecommerce-claims/benchmark/sessions', { pair_id: this.pairId, condition: this.condition }); }
  event(action: 'pause' | 'resume' | 'finish'): void { const trial = this.active(); if (!trial) return; void this.mutate(`/ecommerce-claims/benchmark/sessions/${trial.id}/events`, { action, expected_sequence: trial.events.length, ...(action === 'finish' ? { result: { action: this.action, amount: this.amount.replace(',', '.'), references: this.references, note: this.note } } : {}) }); }
  reopen(trial: Trial): void { this.action = ''; this.amount = ''; this.note = ''; this.references = []; void this.mutate(`/ecommerce-claims/benchmark/sessions/${trial.id}/events`, { action: 'resume', expected_sequence: trial.events.length }); }
  review(passed: boolean): void { void this.mutate(`/ecommerce-claims/benchmark/sessions/${this.reviewId}/review`, { passed, note: this.reviewNote }); }
  toggle(ref: string): void { this.references = this.references.includes(ref) ? this.references.filter(r => r !== ref) : [...this.references, ref]; }
  actionLabel(action: string): string { return CLAIM_ACTION_LABELS[action] ?? 'experience.claims.unknown'; }
  money(value: string | null): string { return value === null ? this.i18n.t('experience.claims.benchmark.not_measured') : new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency: 'EUR' }).format(Number(value)); }
  percent(value: string | null): string { return value === null ? this.i18n.t('experience.claims.benchmark.not_measured') : new Intl.NumberFormat(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 1 }).format(Number(value)); }
}
