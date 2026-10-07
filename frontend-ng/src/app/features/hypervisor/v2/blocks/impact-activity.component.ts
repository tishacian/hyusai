import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { CkChartStreamComponent, NavLinkDirective, type CkStreamSeries } from '@app/shared/cockpit';
import { activityMetrics, type ExecutionActivity } from '../impact-product-blocks';
import type { HypervisorBlockRef } from '../hypervisor-v2-views';

@Component({
  selector: 'app-impact-activity', standalone: true,
  imports: [CkChartStreamComponent, NavLinkDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './impact-activity.html', styleUrl: './impact-product-blocks.scss',
})
export class ImpactActivityComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  readonly block = input.required<HypervisorBlockRef>();
  readonly systemId = input<string | null>(null);
  readonly scopeLabel = input('');
  readonly period = input('30d');
  readonly canEdit = input(false);
  readonly configure = output<void>();
  readonly data = signal<ExecutionActivity | null>(null);
  readonly busy = signal(true);
  readonly problem = signal(false);
  readonly refresh = signal(0);
  readonly selectedDay = signal<number | null>(null);
  readonly metrics = computed(() => activityMetrics(this.block()));
  readonly dates = computed(() => {
    const data = this.data();
    if (!data) return [];
    const cursor = new Date(data.from.slice(0, 10) + 'T00:00:00Z');
    const end = data.to.slice(0, 10);
    const dates: string[] = [];
    while (cursor.toISOString().slice(0, 10) <= end && dates.length < 91) {
      dates.push(cursor.toISOString().slice(0, 10)); cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
    return dates;
  });
  readonly dayLabels = computed(() => this.dates().map(date => this.date(date)));
  readonly chart = computed((): CkStreamSeries[] => {
    this.i18n.locale();
    const byDate = new Map(this.data()?.buckets.map(bucket => [bucket.date, bucket.attempts]) ?? []);
    return [{ id: 'attempts', label: this.i18n.t('hypervisor.v2.activity.attempts'), values: this.dates().map(date => byDate.get(date) ?? 0), tone: 'ink' }];
  });
  readonly ticks = computed(() => this.dayLabels().flatMap((label, index, labels) =>
    index === 0 || index === labels.length - 1 ? [{ index, label, anchor: index === 0 ? 'start' as const : 'end' as const }] : []));
  readonly selected = computed(() => {
    const date = this.dates()[this.selectedDay() ?? -1];
    return date ? { date, attempts: 0, completed: 0, failed: 0, cancelled: 0, pending: 0, ...this.data()?.buckets.find(bucket => bucket.date === date) } : null;
  });
  readonly prices = computed(() => Object.entries(this.data()?.costs.by_currency ?? {}).map(([currency, amount]) => this.money(Number(amount), currency)).join(' / ') || '—');

  constructor() {
    effect(onCleanup => {
      const workspaceId = this.workspace.current()?.id;
      this.auth.authEpoch(); this.refresh();
      const window = this.period(), systemId = this.systemId();
      this.data.set(null); this.problem.set(false); this.busy.set(true); this.selectedDay.set(null);
      if (!workspaceId) return;
      const subscription = this.api.get<ExecutionActivity>('/hypervisor/activity', {
        window, ...(systemId ? { system_id: systemId } : {}),
      }).subscribe({
        next: data => { this.data.set(data); this.busy.set(false); },
        error: () => { this.problem.set(true); this.busy.set(false); },
      });
      onCleanup(() => subscription.unsubscribe());
    });
  }
  refreshActivity(): void { this.refresh.update(value => value + 1); }
  number(value: number | null, digits = 0): string {
    return value == null ? '—' : new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: digits }).format(value);
  }
  money(value: number, currency: string): string {
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(value);
  }
  date(value: string): string {
    return new Intl.DateTimeFormat(this.i18n.locale(), { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(value.slice(0, 10) + 'T00:00:00Z'));
  }
  status(value: string): string {
    return this.i18n.t('hypervisor.v2.activity.' + (['completed', 'failed', 'cancelled'].includes(value) ? value : 'pending'));
  }
}
