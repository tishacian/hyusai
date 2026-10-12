import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { benchMetric, ratioPercent, shortSha, type PublicBenchRun } from './public-bench.vm';

interface PublicBenchResponse {
  bench: string;
  runs: PublicBenchRun[];
}

@Component({
  selector: 'app-public-bench-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<section class="bench" [attr.aria-label]="i18n.t('observability.bench.title')">
 <header><div><p class="eyebrow">{{i18n.t('observability.bench.eyebrow')}}</p><h2>{{i18n.t('observability.bench.title')}}</h2></div><p class="scope">{{i18n.t('observability.bench.scope')}}</p></header>
 @if(loadError()){<p role="alert">{{i18n.t('observability.bench.load_error')}}</p>}
 @else if(!runs().length){<p>{{i18n.t('observability.bench.empty')}}</p>}
 @else {
 <div class="metrics">
  @for(metric of metrics();track metric.label){<div><span class="label">{{metric.label}}</span><strong>{{metric.value === null ? '—' : metric.value + ' %'}}</strong>@if(metric.delta !== null){<span class="delta" [class.down]="metric.delta < 0">{{metric.delta > 0 ? '+' : ''}}{{metric.delta}} pt</span>}</div>}
 </div>
 <table><thead><tr><th>{{i18n.t('observability.bench.col.date')}}</th><th>{{i18n.t('observability.bench.col.status')}}</th><th>{{i18n.t('observability.bench.recall')}}</th><th>{{i18n.t('observability.bench.facts')}}</th><th>{{i18n.t('observability.bench.col.cases')}}</th><th>{{i18n.t('observability.bench.col.revision')}}</th></tr></thead>
 <tbody>@for(run of runs();track run.id){<tr><td>{{run.started_at ? run.started_at.slice(0,16).replace('T',' ') : '—'}}</td><td>{{run.status}}</td><td>{{percent(run.recall_at_k)}}</td><td>{{percent(run.supporting_fact_rate)}}</td><td>{{run.case_count}}@if(run.error_count){ <span class="delta down">({{run.error_count}})</span>}</td><td class="mono">{{sha(run.git_sha)}}</td></tr>}</tbody></table>
 }
 </section>`,
  styles: [`.bench{padding:28px 0 32px;color:var(--ck-fg-1);border-top:1px solid var(--ck-stroke-2)}header{display:flex;justify-content:space-between;align-items:end;gap:24px}.eyebrow{font-size:13px;color:var(--ck-fg-3);margin:0 0 10px}h2{font-size:24px;font-weight:600;letter-spacing:-.02em}.scope{font-size:13px;color:var(--ck-fg-3);max-width:420px}.metrics{display:flex;gap:40px;margin:20px 0}.metrics div{display:flex;flex-direction:column;gap:4px}.label{font-size:12px;color:var(--ck-fg-3)}strong{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums}.delta{font-size:12px;color:var(--ck-signal-cool)}.delta.down{color:var(--ck-signal-warm)}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--ck-fg-3);font-weight:500;padding:6px 8px;border-bottom:1px solid var(--ck-stroke-2)}td{padding:6px 8px;border-bottom:1px solid var(--ck-stroke-1, var(--ck-stroke-2));font-variant-numeric:tabular-nums}.mono{font-family:var(--ck-font-mono, monospace)}@media(max-width:600px){header{display:block}.metrics{gap:24px}}`],
})
export class PublicBenchPanelComponent implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly runs = signal<PublicBenchRun[]>([]);
  readonly loadError = signal(false);
  readonly metrics = computed(() => [
    { label: this.i18n.t('observability.bench.recall'), ...benchMetric(this.runs(), 'recall_at_k') },
    { label: this.i18n.t('observability.bench.facts'), ...benchMetric(this.runs(), 'supporting_fact_rate') },
  ]);

  ngOnInit(): void {
    this.api
      .get<PublicBenchResponse>('/evaluation/public-bench/runs', { limit: '14' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (body) => this.runs.set(body.runs ?? []),
        error: () => this.loadError.set(true),
      });
  }

  percent(value: number | null | undefined): string {
    const pct = ratioPercent(value);
    return pct === null ? '—' : `${pct} %`;
  }

  sha(value: string | null | undefined): string {
    return shortSha(value);
  }
}
