import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { CurveChartComponent } from '../data/viz/curve-chart.component';
import type { ScheduledMonitoringReport } from './retraining-evidence.vm';
import { monitoringDate } from './retraining-evidence.vm';
import { monitoringDomain, monitoringSeries } from './monitoring-history.vm';
import type { CurvePoint } from './models.vm';

@Component({
  selector:'ck-monitoring-history', standalone:true, changeDetection:ChangeDetectionStrategy.OnPush,
  imports:[CurveChartComponent],
  template:`
    @if (selected(); as item) {
      <section data-testid="monitoring-history-chart">
        <label>{{i18n.t('models.correctness.history_metric')}}
          <select [value]="item.key" (change)="choice.set($any($event.target).value)">
            @for (option of series(); track option.key) { <option [value]="option.key">{{i18n.t(option.label)}} {{option.feature ?? ''}}</option> }
          </select>
        </label>
        <p>{{i18n.t('models.correctness.history_hint')}}</p>
        <ck-curve-chart [points]="item.points" [domain]="domain()" [label]="i18n.t(item.label)" [xLabel]="i18n.t('models.correctness.observation')" [yLabel]="i18n.t(item.label)" [pointLabel]="pointLabel" />
      </section>
    }
  `,
  styles:[`section{margin:16px 0;max-width:760px}label{display:flex;align-items:center;gap:12px;font-size:12px}select{color:var(--ck-fg-1);background:var(--ck-bg-panel-hi);border:1px solid var(--ck-stroke-2);padding:6px;border-radius:4px}p{font-size:12px;color:var(--ck-fg-3)}`],
})
export class MonitoringHistoryComponent {
  readonly i18n=inject(I18nService);
  readonly history=input<ScheduledMonitoringReport['history']>([]);
  readonly choice=signal('');
  readonly series=computed(()=>monitoringSeries(this.history()));
  readonly selected=computed(()=>this.series().find(item=>item.key===this.choice()) ?? this.series()[0]);
  readonly domain=computed(()=>monitoringDomain(this.selected()?.points ?? []));
  readonly pointLabel=(point:CurvePoint)=>`${monitoringDate(this.selected()?.dates[point.x-1] ?? '',this.i18n.locale())} · ${point.y.toLocaleString(this.i18n.locale())}`;
}
