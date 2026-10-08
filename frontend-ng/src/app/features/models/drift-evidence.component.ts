import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { driftNumber, driftTestRows } from './drift-evidence.vm';
import type { DriftFeature } from './models.vm';

@Component({
  selector: 'ck-drift-evidence', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (rows().length) {
      <section data-testid="drift-tests">
        <h3>{{ i18n.t('models.monitor.tests.title') }}</h3>
        <p>{{ i18n.t('models.monitor.tests.hint') }}</p>
        <div class="table-wrap"><table>
          <thead><tr>
            <th>{{ i18n.t('models.monitor.tests.feature') }}</th><th>{{ i18n.t('models.monitor.tests.method') }}</th>
            <th>{{ i18n.t('models.monitor.tests.statistic') }}</th><th>{{ i18n.t('models.monitor.tests.adjusted_p') }}</th>
            <th>{{ i18n.t('models.monitor.tests.reference_n') }}</th><th>{{ i18n.t('models.monitor.tests.current_n') }}</th>
            <th>{{ i18n.t('models.monitor.tests.result') }}</th>
          </tr></thead>
          <tbody>@for (row of rows(); track row.name) {
            <tr [attr.data-feature]="row.name" [attr.data-status]="row.status">
              <th scope="row">{{ row.name }}</th><td>{{ row.method ? i18n.t('models.monitor.tests.method.' + row.method) : '—' }}</td>
              <td class="number" data-statistic>{{ format(row.statistic) }}</td><td class="number" data-adjusted-p>{{ format(row.adjustedP) }}</td>
              <td class="number" data-reference-n>{{ row.referenceCount ?? '—' }}</td><td class="number" data-current-n>{{ row.currentCount ?? '—' }}</td>
              <td><span class="status">{{ i18n.t('models.monitor.tests.status.' + row.status) }}</span>
                @if (row.reason) { <small>{{ i18n.t('models.monitor.tests.reason.' + row.reason) }}</small> }
              </td>
            </tr>
          }</tbody>
        </table></div>
      </section>
    }
  `,
  styles: [`section{padding:14px;border:1px solid var(--ck-stroke-2);border-radius:6px;color:var(--ck-fg-1)}h3{margin:0 0 8px;font-size:13px}p,small{font-size:12px;line-height:1.5;color:var(--ck-fg-3)}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--ck-stroke-2);vertical-align:top}thead th{font-weight:500;color:var(--ck-fg-3)}.number{font-variant-numeric:tabular-nums;white-space:nowrap}small{display:block;max-width:280px;margin-top:4px}[data-status=alert] .status{color:var(--ck-signal-neg)}[data-status=watch] .status{color:var(--ck-signal-warm)}`],
})
export class DriftEvidenceComponent {
  readonly i18n = inject(I18nService);
  readonly features = input<DriftFeature[]>();
  readonly rows = computed(() => driftTestRows(this.features()));
  format(value: number | null): string { return driftNumber(value, this.i18n.locale()); }
}
