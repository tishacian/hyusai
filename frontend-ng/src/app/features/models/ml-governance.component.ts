import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, output, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';

interface Policy {
  promotion_requires_approval: boolean;
  store_inputs: boolean;
  prediction_retention_days: number;
  predict_requests_per_minute: number;
  predict_rows_per_minute: number;
  max_exposed_models: number;
}
interface Promotion { id: string; model_id: string; can_decide: boolean; expires_at: string; }
interface Governance { retention_enabled: boolean; policy: Policy; permissions: Record<string, boolean>; promotions: Promotion[]; }

@Component({
  selector: 'ck-ml-governance', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ck-panel" data-testid="ml-governance">
      <h3>{{ t('title') }}</h3>
      @if (error()) { <p role="alert">{{ error() }}</p> }
      @if (state(); as state) {
        <p>{{ t('scope') }}</p>
        @if (!state.retention_enabled) { <p role="status" data-testid="ml-retention-disabled">{{ t('retention_disabled') }}</p> }
        @if (draft(); as p) {
          <fieldset [disabled]="busy() || !state.permissions['policy']">
            <label><input type="checkbox" [checked]="p.promotion_requires_approval" (change)="set('promotion_requires_approval', $any($event.target).checked)" /> {{ t('approval') }}</label>
            <label><input type="checkbox" [checked]="p.store_inputs" (change)="set('store_inputs', $any($event.target).checked)" /> {{ t('store') }}</label>
            <div class="budgets">
              @for (field of numbers; track field) {
                <label>{{ t(field) }}<input type="number" min="1" step="1" [value]="p[field]" (input)="set(field, +$any($event.target).value)" /></label>
              }
            </div>
            @if (state.permissions['policy']) { <button type="button" class="ck-btn-soft" (click)="save()">{{ t('save') }}</button> }
          </fieldset>
          @if (saved()) { <p role="status">{{ t('saved') }}</p> }
        }
        @for (request of state.promotions; track request.id) {
          @if (request.model_id === modelId()) {
            <div class="review" data-testid="ml-promotion-review">
              <p>{{ t('pending') }} · {{ request.expires_at }}</p>
              @if (request.can_decide) {
                <button class="ck-btn-soft" type="button" [disabled]="busy()" (click)="decide(request.id, true)">{{ t('approve') }}</button>
                <button class="ck-btn-soft" type="button" [disabled]="busy()" (click)="decide(request.id, false)">{{ t('reject') }}</button>
              } @else { <p>{{ t('second_reviewer') }}</p> }
            </div>
          }
        }
      } @else if (!error()) { <p role="status">{{ t('loading') }}</p> }
    </section>
  `,
  styles: [`
    :host { display:block; margin-top:16px; }
    h3 { margin:0 0 8px; font-size:14px; } p,label { font-size:12px; color:var(--ck-fg-2); }
    fieldset { border:0; padding:0; display:grid; gap:12px; } label { display:flex; gap:8px; align-items:center; }
    .budgets { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }
    .budgets label { display:grid; } input[type=number] { padding:8px; background:var(--ck-bg-2); border:1px solid var(--ck-stroke-2); border-radius:4px; color:var(--ck-fg-1); }
    .review { border-top:1px solid var(--ck-stroke-2); margin-top:16px; padding-top:8px; } button { padding:8px 12px; margin-right:8px; }
  `],
})
export class MlGovernanceComponent {
  readonly modelId = input.required<string>();
  readonly changed = output<void>();
  protected readonly i18n = inject(I18nService);
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly state = signal<Governance | null>(null);
  protected readonly draft = signal<Policy | null>(null);
  protected readonly busy = signal(false);
  protected readonly saved = signal(false);
  protected readonly error = signal('');
  protected readonly numbers = ['prediction_retention_days', 'predict_requests_per_minute', 'predict_rows_per_minute', 'max_exposed_models'] as const;
  private generation = 0;
  constructor() {
    effect(() => { this.modelId(); this.workspace.current()?.id; this.state.set(null); this.draft.set(null); this.saved.set(false); this.busy.set(false); void this.load(); });
    this.destroyRef.onDestroy(() => { this.generation++; });
  }
  private requestCurrent(): () => boolean {
    const id = this.modelId(), generation = this.generation, scope = this.workspace.captureRequestScope();
    return () => id === this.modelId() && generation === this.generation && this.workspace.isRequestScopeCurrent(scope);
  }
  protected t(key: string): string { return this.i18n.t('models.governance.' + key); }
  protected set(key: keyof Policy, value: boolean | number): void { this.saved.set(false); this.draft.update(p => p ? { ...p, [key]: value } : p); }
  private async load(): Promise<void> {
    ++this.generation;
    const current = this.requestCurrent();
    this.error.set('');
    try {
      const state = await firstValueFrom(this.http.get<Governance>('/api/v1/ml-governance'));
      if (!current()) return;
      this.state.set(state); this.draft.set({ ...state.policy });
    } catch { if (current()) { this.state.set(null); this.error.set(this.t('failed')); } }
  }
  protected async save(): Promise<void> {
    if (!this.state()?.permissions['policy'] || this.busy()) return;
    const current = this.requestCurrent();
    this.busy.set(true); this.error.set('');
    try {
      const result = await firstValueFrom(this.http.put<{ policy: Policy }>('/api/v1/ml-governance/policy', this.draft()));
      if (!current()) return;
      this.draft.set(result.policy); this.state.update(state => state ? {...state, policy: result.policy} : state); this.saved.set(true);
    } catch { if (current()) this.error.set(this.t('failed')); }
    finally { if (current()) this.busy.set(false); }
  }
  protected async decide(id: string, approve: boolean): Promise<void> {
    if (!this.state()?.promotions.some(p => p.id === id && p.can_decide) || this.busy()) return;
    const current = this.requestCurrent();
    this.busy.set(true); this.error.set('');
    try {
      await firstValueFrom(this.http.post('/api/v1/ml-governance/promotions/' + encodeURIComponent(id), { approve }));
      if (!current()) return;
      this.changed.emit(); this.busy.set(false); await this.load();
    } catch (error) { if (current()) this.error.set(this.t(error instanceof HttpErrorResponse && error.status === 409 ? 'stale' : 'failed')); }
    finally { if (current()) this.busy.set(false); }
  }
}
