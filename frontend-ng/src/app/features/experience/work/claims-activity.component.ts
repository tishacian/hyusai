import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { NavLinkDirective } from '@app/shared/cockpit';
import { CLAIM_ACTION_LABELS } from './claim-run';
import { ClaimsFinancialAssumptions, claimsFinancialProjection } from './claims-financial';

interface Activity {
  system_id: string;
  assumptions: { manual_minutes: number; assisted_minutes: number; hourly_eur: string; incremental_eur_per_case: string };
  counts: { attempts: number; completed: number; failed: number; duplicate_blocked: number; pending: number; unique_cases: number; rule_matched_cases: number; simulated_receipts: number; waiting_information_cases: number; invocations: number };
  catalog_costs: { state: string; by_currency: Record<string, string>; priced_invocations: number; unpriced_invocations: number };
  median_technical_seconds: number | null;
  period: { limited: boolean };
  runs: Array<{ run_id: string; claim_id: string; status: string; reason: string | null; action: string | null; automatic_rule_match: boolean | null; technical_seconds: number | null }>;
}

@Component({
  selector: 'app-claims-activity', standalone: true,
  imports: [FormsModule, NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './claims-activity.html', styleUrl: './claims-activity.scss',
})
export class ClaimsActivityComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly destroy = inject(DestroyRef);
  readonly data = signal<Activity | null>(null);
  readonly busy = signal(false);
  readonly problem = signal(false);
  readonly assumptions = signal<ClaimsFinancialAssumptions>({ manualMinutes: 8, assistedMinutes: 2, hourlyEur: 40, budgetEur: 0.5, volume: 1000 });
  readonly projection = computed(() => claimsFinancialProjection(this.assumptions()));
  private generation = 0;
  private edited = false;
  constructor() {
    effect(() => {
      this.workspace.current()?.id; this.auth.authEpoch();
      this.edited = false; this.data.set(null); void this.load();
    });
    this.destroy.onDestroy(() => this.generation++);
  }
  async load(): Promise<void> {
    const generation = ++this.generation;
    this.busy.set(true); this.problem.set(false);
    try {
      const data = await firstValueFrom(this.api.get<Activity>('/ecommerce-claims/activity'));
      if (generation !== this.generation) return;
      this.data.set(data);
      if (!this.edited) this.assumptions.set({
        manualMinutes: data.assumptions.manual_minutes, assistedMinutes: data.assumptions.assisted_minutes,
        hourlyEur: Number(data.assumptions.hourly_eur), budgetEur: Number(data.assumptions.incremental_eur_per_case), volume: 1000,
      });
    } catch { if (generation === this.generation) this.problem.set(true); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  change(key: keyof ClaimsFinancialAssumptions, value: number): void {
    this.edited = true; this.assumptions.update(current => ({ ...current, [key]: value }));
  }
  money(value: number | string | null, currency = 'EUR'): string {
    return value === null || !Number.isFinite(Number(value)) ? '—'
      : new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(Number(value));
  }
  number(value: number | null, digits = 1): string {
    return value === null ? '—' : new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: digits }).format(value);
  }
  percent(value: number | null): string {
    return value === null ? '—' : new Intl.NumberFormat(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 0 }).format(value);
  }
  action(value: string | null): string { return this.i18n.t(CLAIM_ACTION_LABELS[value ?? ''] ?? 'experience.claims.unknown'); }
  status(value: string, reason: string | null = null): string {
    if (reason === 'duplicate_action') return this.i18n.t('experience.claims.activity.duplicate');
    if (reason === 'missing_information') return this.i18n.t('experience.claims.activity.information_state');
    return this.i18n.t(value === 'completed' ? 'experience.claims.step.done'
      : ['failed', 'cancelled'].includes(value) ? 'experience.claims.activity.failed'
      : value === 'hitl_pending' ? 'experience.claims.activity.approval' : 'experience.claims.running');
  }
}
