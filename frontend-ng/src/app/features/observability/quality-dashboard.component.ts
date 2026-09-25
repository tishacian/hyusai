import {
  ChangeDetectionStrategy,
  Component,
  NgZone,
  OnInit,
  OnDestroy,
  effect,
  untracked,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subject, takeUntil } from 'rxjs';
import { ActivatedRoute, Router } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { observabilityText, observabilityNumber } from './observability-labels';
import { observabilitySystemId } from './observability-facets';
import { QualityEvidenceChartsComponent } from './quality-evidence-charts.component';
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration, ChartData } from 'chart.js';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import type { NavLinkInput } from '@app/core/navigation.catalog';
import {
  CanonicalApiService,
  type EvaluationComponentHealthResponse,
  type EvaluationTrendResponse,
} from '@app/core/canonical-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  GlyphComponent,
  NavLinkDirective,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';

interface DimensionsResponse {
  dimensions: Record<string, string>;
}

interface EvaluationRow {
  id: string;
  run_id?: string | null;
  status?: string;
  threshold_breach?: boolean | null;
  scores?: Record<string, number>;
  composite_score?: number | null;
  hallucination_rate?: number | null;
  drift_rate?: number | null;
  claim_audit?: { claims?: Array<{ text?: string; claim?: string; verdict?: string }> };
  created_at?: string | null;
}

interface HistoryResponse {
  evaluations: EvaluationRow[];
}

interface LatestResponse {
  evaluation: EvaluationRow | null;
}

const PALETTE = {
  current: { stroke: '#00bcd4', fill: 'rgba(0,188,212,0.18)' },
  target: { stroke: 'rgba(139,92,246,0.6)', fill: 'rgba(139,92,246,0.08)' },
};

@Component({
  selector: 'app-quality-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NavLinkDirective,
    FormsModule,
    BaseChartDirective,
    QualityEvidenceChartsComponent,
    IconComponent,
    StatReadoutComponent,
    EmptyStateComponent,
    PageFrameComponent,
    GlyphComponent,
    TagComponent,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('observability.charts.context')"
      [title]="i18n.t('observability.charts.page_title')"
    >
      <div actions [style.display]="'inline-flex'" [style.gap.px]="6">
        <button
          type="button"
          (click)="refresh()"
          [disabled]="loading()"
          class="ck-mono"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="6"
          [style.height.px]="28"
          [style.padding]="'0 12px'"
          [style.background]="'transparent'"
          [style.color]="'var(--ck-fg-2)'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="4"
          [style.fontSize.px]="11"
          [style.letterSpacing]="'0.08em'"
          [style.textTransform]="'uppercase'"
          [style.cursor]="'pointer'"
        >
          <ck-glyph name="orbit" [size]="12" />
          {{i18n.t('observability.charts.refresh')}}
        </button>
        <button
          type="button"
          (click)="runEvaluation()"
          [disabled]="running() || !canRunEvaluation()"
          [title]="i18n.t('runs.investigation.title')"
          class="ck-mono"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="6"
          [style.height.px]="28"
          [style.padding]="'0 12px'"
          [style.background]="canRunEvaluation() && !running() ? 'var(--ck-signal-cool)' : 'var(--ck-bg-inset)'"
          [style.color]="canRunEvaluation() && !running() ? 'var(--ck-on-signal)' : 'var(--ck-fg-4)'"
          [style.border]="'1px solid ' + (canRunEvaluation() && !running() ? 'var(--ck-signal-cool)' : 'var(--ck-stroke-2)')"
          [style.borderRadius.px]="4"
          [style.fontSize.px]="11"
          [style.fontWeight]="600"
          [style.letterSpacing]="'0.08em'"
          [style.textTransform]="'uppercase'"
          [style.cursor]="canRunEvaluation() && !running() ? 'pointer' : 'not-allowed'"
        >
          <ck-glyph [name]="running() ? 'orbit' : 'play'" [size]="12" />
          {{ i18n.t('runs.investigation.title') }}
        </button>
      </div>

    <div class="flex gap-4 flex-wrap items-end my-4">
     <label>{{i18n.t('observability.charts.system')}}<select class="ck-surface p-2 block" [ngModel]="systemFilter()" (ngModelChange)="setScope($event,period())"><option value="">{{i18n.t('observability.charts.all_systems')}}</option>@for(system of systems();track system.id){<option [value]="system.id">{{system.name}}</option>}</select></label>
     <label>{{i18n.t('observability.charts.period')}}<select class="ck-surface p-2 block" [ngModel]="period()" (ngModelChange)="setScope(systemFilter(),$event)"><option value="7d">{{i18n.t('observability.charts.week')}}</option><option value="30d">{{i18n.t('observability.charts.month')}}</option></select></label>
    </div>
    @if(loadError()){<p role="alert">{{i18n.t('observability.charts.load_error')}}</p>}
    <app-quality-evidence-charts [rows]="history()" />

    <!-- Vague E / E1 — Threshold monitoring strip (7d aggregate).
         Sits above the per-run tiles because "are we drifting over time?"
         is the question an operator asks first when opening Quality. -->
    @if (trend(); as t) {
      <section
        class="ck-surface t-elevated rounded-md p-4 mb-4"
        [style.display]="'grid'"
        [style.gridTemplateColumns]="'1fr 1fr 1fr auto'"
        [style.gap.px]="16"
        [style.alignItems]="'center'"
      >
        <div>
          <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="6" [style.marginBottom.px]="4">
            <ck-glyph name="pulse" [size]="12" />
            <span class="ck-mono" [style.fontSize.px]="10" [style.letterSpacing]="'0.08em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-3)'">
              {{i18n.t('observability.quality.thresholds')}} · {{periodLabel()}}
            </span>
          </div>
          <div [style.display]="'flex'" [style.alignItems]="'baseline'" [style.gap.px]="10">
            <span [style.fontSize.px]="22" [style.fontWeight]="600" [style.color]="'var(--ck-fg-1)'">
              {{ trendRuns() }}
            </span>
            <span [style.fontSize.px]="11" [style.color]="'var(--ck-fg-3)'">
              {{i18n.t('observability.quality.evaluated')}}
            </span>
          </div>
          <div [style.fontSize.px]="11" [style.color]="'var(--ck-fg-3)'" [style.marginTop.px]="2">
            {{i18n.t('observability.quality.average')}} {{trendAvgComposite()}} / 100
          </div>
        </div>

        <div>
          <div [style.fontSize.px]="10" [style.letterSpacing]="'0.08em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-3)'" [style.marginBottom.px]="4">
            {{i18n.t('observability.quality.breaches')}}
          </div>
          <div [style.display]="'flex'" [style.alignItems]="'baseline'" [style.gap.px]="10">
            <span
              [style.fontSize.px]="22"
              [style.fontWeight]="600"
              [style.color]="trendBreaches() > 0 ? 'var(--ck-signal-warm)' : 'var(--ck-fg-1)'"
            >
              {{ trendBreaches() }}
            </span>
            <ck-tag [tone]="trendHealthTone()" variant="soft">
              {{i18n.t('observability.quality.rate', {rate:trendBreachRate()})}}
            </ck-tag>
          </div>
          <div [style.fontSize.px]="11" [style.color]="'var(--ck-fg-3)'" [style.marginTop.px]="2">
            {{ i18n.t('runs.investigation.method') }}: {{ t.totals.threshold_coverage ?? 0 }} / {{ t.totals.runs_evaluated }}
          </div>
        </div>

        <div>
          <div [style.fontSize.px]="10" [style.letterSpacing]="'0.08em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-3)'" [style.marginBottom.px]="6">
            {{i18n.t('observability.quality.daily')}}
          </div>
          @if (trendBars().length > 0) {
            <div [style.display]="'flex'" [style.alignItems]="'flex-end'" [style.gap.px]="3" [style.height.px]="28">
              @for (bar of trendBars(); track bar.bucket) {
                <div
                  [title]="i18n.t('observability.quality.bucket',{date:date(bar.bucket),count:bar.count})"
                  [style.flex]="'1 1 0'"
                  [style.minHeight.px]="2"
                  [style.height.px]="bar.heightPx"
                  [style.background]="bar.isBreach ? 'var(--ck-signal-warm)' : 'var(--ck-signal-cool)'"
                  [style.borderRadius.px]="2"
                  [style.opacity]="bar.count > 0 ? 1 : 0.25"
                ></div>
              }
            </div>
          } @else {
            <div [style.fontSize.px]="11" [style.color]="'var(--ck-fg-4)'" [style.fontStyle]="'italic'">
              No {{i18n.t('observability.quality.evaluated')}} in the window.
            </div>
          }
        </div>

        <a
          [navLink]="reviewQueueLink()"
          class="ck-mono"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="8"
          [style.height.px]="40"
          [style.padding]="'0 14px'"
          [style.background]="reviewQueueCount() > 0 ? 'var(--ck-signal-warm)' : 'transparent'"
          [style.color]="reviewQueueCount() > 0 ? 'var(--ck-on-signal)' : 'var(--ck-fg-2)'"
          [style.border]="'1px solid ' + (reviewQueueCount() > 0 ? 'var(--ck-signal-warm)' : 'var(--ck-stroke-2)')"
          [style.borderRadius.px]="4"
          [style.fontSize.px]="11"
          [style.fontWeight]="600"
          [style.letterSpacing]="'0.08em'"
          [style.textTransform]="'uppercase'"
          [style.textDecoration]="'none'"
          [title]="i18n.t('observability.quality.review_count',{count:reviewQueueCount()})"
        >
          <ck-glyph name="crosshair" [size]="14" />
          {{i18n.t('observability.quality.review_queue')}}
          @if (reviewQueueCount() > 0) {
            <span
              [style.background]="'rgba(0,0,0,0.25)'"
              [style.color]="'inherit'"
              [style.padding]="'1px 6px'"
              [style.borderRadius.px]="8"
              [style.fontSize.px]="10"
              [style.fontWeight]="700"
            >
              {{ reviewQueueCount() }}
            </span>
          }
        </a>
      </section>
    }

    @if (componentHealthItems().length > 0) {
      <section class="ck-surface t-elevated rounded-md p-4 mb-4">
        <div class="flex items-center justify-between mb-3">
          <div>
            <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="6">
              <ck-glyph name="pulse" [size]="12" />
              <span class="ck-mono" [style.fontSize.px]="10" [style.letterSpacing]="'0.08em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-3)'">
                {{i18n.t('observability.quality.components')}} · {{periodLabel()}}
              </span>
            </div>
            <div [style.fontSize.px]="11" [style.color]="'var(--ck-fg-3)'" [style.marginTop.px]="3">
              {{i18n.t('observability.quality.attribution')}}
            </div>
          </div>
          <ck-tag [tone]="componentHealthTone()" variant="soft">
            {{i18n.t('observability.quality.attributions',{count:componentHealthBreaches()})}}
          </ck-tag>
        </div>

        <div [style.display]="'grid'" [style.gridTemplateColumns]="'repeat(auto-fit, minmax(170px, 1fr))'" [style.gap.px]="10">
          @for (item of componentHealthItems(); track item.component) {
            <a
              [navLink]="reviewQueueLink(item.component)"
              [style.display]="'block'"
              [style.textDecoration]="'none'"
              [style.padding.px]="12"
              [style.borderRadius.px]="5"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.background]="'var(--ck-bg-inset)'"
              [title]="i18n.t('observability.quality.component_link',{component:code('component',item.component)})"
            >
              <div [style.display]="'flex'" [style.justifyContent]="'space-between'" [style.alignItems]="'center'" [style.gap.px]="8">
                <span class="ck-mono" [style.fontSize.px]="10" [style.letterSpacing]="'0.08em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-3)'">
                  {{code('component',item.component)}}
                </span>
                <ck-tag [tone]="item.tone" variant="soft">
                  {{ item.rateLabel }}
                </ck-tag>
              </div>
              <div [style.display]="'flex'" [style.alignItems]="'baseline'" [style.gap.px]="8" [style.marginTop.px]="8">
                <span [style.fontSize.px]="22" [style.fontWeight]="600" [style.color]="item.breaches > 0 ? 'var(--ck-signal-warm)' : 'var(--ck-fg-1)'">
                  {{ item.breaches }}
                </span>
                <span [style.fontSize.px]="11" [style.color]="'var(--ck-fg-4)'">
                  {{i18n.t('observability.quality.applicable',{count:item.evaluated})}}
                </span>
              </div>
              <div [style.fontSize.px]="11" [style.color]="'var(--ck-fg-3)'" [style.marginTop.px]="4">
                {{i18n.t('observability.quality.component_summary',{score:number(item.avg_composite,1),rate:number(item.avg_hallucination == null ? null : item.avg_hallucination*100,1)})}}
              </div>
            </a>
          }
        </div>
      </section>
    }

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <ck-stat-readout variant="tile"
        [label]="i18n.t('observability.quality.composite')"
        [value]="compositeDisplay()"
        unit="/100"
        icon="target"
        [trend]="compositeTrend()"
        trendSentiment="positive"
        [delta]="compositeDelta()"
        [sparkline]="compositeSeries()"
        sparklineTone="positive"
      />
      <ck-stat-readout variant="tile"
        [label]="i18n.t('observability.quality.count')"
        [value]="history().length.toString()"
        icon="history"
        [sparkline]="evaluationsSeries()"
        sparklineTone="neutral"
      />
      <ck-stat-readout variant="tile"
        [label]="i18n.t('observability.quality.unsupported')"
        [value]="unsupportedClaimsDisplay()"
        unit="%"
        icon="alert-triangle"
        [trend]="unsupportedClaimsTrend()"
        trendSentiment="negative"
        [sparkline]="unsupportedClaimsSeries()"
        sparklineTone="negative"
        [hint]="unsupportedClaimsHint()"
      />
      <ck-stat-readout variant="tile"
        [label]="i18n.t('observability.quality.drift')"
        [value]="driftDisplay()"
        unit="%"
        icon="waves"
        [trend]="driftTrend()"
        trendSentiment="negative"
        [sparkline]="driftSeries()"
        sparklineTone="negative"
      />
    </div>

    <details class="mb-6"><summary class="cursor-pointer py-3">{{i18n.t('observability.charts.details')}}</summary>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <!-- Radar chart -->
      <section class="ck-surface t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="radar" [size]="16" class="text-cyan-400" />
            {{i18n.t('observability.quality.radar',{count:dimensionLabels().length})}}
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{i18n.t(latest() ? 'observability.quality.latest' : 'observability.quality.no_data')}}
          </span>
        </div>
        <div class="h-80">
          @if (chartsReady() && latest()) {
            <canvas
              baseChart
              [data]="radarData()"
              [options]="radarOptions"
              type="radar"
            ></canvas>
          } @else if (chartsReady()) {
            <div class="h-full flex items-center justify-center">
              <app-empty-state
                size="sm"
                icon="radar"
                [title]="i18n.t('observability.quality.no_evaluation')"
                [description]="i18n.t('observability.quality.start_evaluation')"
              />
            </div>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>

      <!-- History -->
      <section class="ck-surface t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="history" [size]="16" class="text-cyan-400" />
            {{i18n.t('observability.quality.history')}}
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{i18n.t('observability.quality.last_count',{count:history().length})}}
          </span>
        </div>
        <div class="h-80">
          @if (chartsReady() && history().length > 0) {
            <canvas
              baseChart
              [data]="historyData()"
              [options]="lineOptions"
              type="line"
            ></canvas>
          } @else if (chartsReady()) {
            <div class="h-full flex items-center justify-center">
              <app-empty-state
                size="sm"
                icon="line-chart"
                [title]="i18n.t('observability.quality.no_history')"
                [description]="i18n.t('observability.quality.history_hint')"
              />
            </div>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>
    </div>

    </details>
    <section class="ck-surface t-elevated rounded-md p-5 mb-4">
      <h3>{{ i18n.t('runs.investigation.title') }}</h3>
      @for (row of history(); track row.id) {
        @if (row.run_id) {
          <p><a [navLink]="{type: 'run', ref: row.run_id}">{{date(row.created_at)}} · {{code('status',row.status || 'historical')}}</a></p>
        }
      }
    </section>
    <!-- Claim audit -->
    <section class="ck-surface t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="shield-check" [size]="16" class="text-cyan-400" />
          {{i18n.t('observability.quality.claim_audit')}}
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          {{i18n.t('observability.quality.claim_count',{count:claims().length})}}
        </span>
      </div>
      @if (claims().length === 0) {
        <app-empty-state
          size="sm"
          icon="shield-check"
          [title]="i18n.t('observability.quality.no_claims')"
          [description]="i18n.t('observability.quality.claims_hint')"
        />
      } @else {
        <ul class="divide-y divide-white/5">
          @for (claim of claims(); track $index) {
            <li class="px-5 py-3 flex items-start gap-3 text-sm">
              <div
                class="w-2 h-2 rounded-full mt-1.5 shrink-0"
                [class.bg-emerald-400]="claim.verdict === 'supported'"
                [class.bg-amber-400]="claim.verdict === 'partial'"
                [class.bg-red-400]="claim.verdict === 'unsupported'"
              ></div>
              <div class="flex-1 min-w-0">
                <div class="text-white">{{ claim.text || claim.claim }}</div>
                <div class="text-[11px] text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
                  <span
                    class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded capitalize"
                    [class.bg-emerald-500\\/10]="claim.verdict === 'supported'"
                    [class.text-emerald-400]="claim.verdict === 'supported'"
                    [class.bg-amber-500\\/10]="claim.verdict === 'partial'"
                    [class.text-amber-400]="claim.verdict === 'partial'"
                    [class.bg-red-500\\/10]="claim.verdict === 'unsupported'"
                    [class.text-red-400]="claim.verdict === 'unsupported'"
                  >
                    {{code('verdict',claim.verdict)}}
                  </span>

                </div>
              </div>
            </li>
          }
        </ul>
      }
    </section>
    </ck-page-frame>
  `,
})
export class QualityDashboardComponent implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService);
  code(category: string, value: unknown): string { return observabilityText(this.i18n, category, value); }
  number(value: number | null | undefined, digits=0): string { return observabilityNumber(value, this.i18n.locale(), digits); }
  date(value: string | null | undefined): string { const d=new Date(value || ''); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString(this.i18n.locale()); }
  periodLabel(): string { return this.i18n.t(this.period()==='30d'?'observability.charts.month':'observability.charts.week'); }
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly cancel = new Subject<void>();
  readonly systemFilter = signal(observabilitySystemId(this.route.snapshot.queryParamMap));
  readonly period = signal(this.route.snapshot.queryParamMap.get('since') === '30d' ? '30d' : '7d');
  readonly systems = signal<Array<{id:string;name:string}>>([]);
  readonly loadError = signal(false);
  private readonly navigation = inject(ZoomContextService);
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly zone = inject(NgZone);
  private readonly toast = inject(ToastrService);

  reviewQueueLink(component?: string): NavLinkInput {
    return {
      surface: 'review-queue',
      systemId: this.systemFilter() || null,
      params: {
        since: this.period(),
        ...(component ? { component } : {}),
      },
    };
  }

  chartsReady = signal(false);
  loading = signal(false);
  running = signal(false);

  latest = signal<EvaluationRow | null>(null);
  history = signal<EvaluationRow[]>([]);
  dimensions = signal<Record<string, string>>({});

  /** Aggregate trend (Vague E / E1) — feeds the "Threshold monitoring" strip. */
  trend = signal<EvaluationTrendResponse | null>(null);
  /** E1.5.3 — RAG component attribution inspired by Giskard RAGET. */
  componentHealth = signal<EvaluationComponentHealthResponse | null>(null);
  /** Count of review_required decisions with status=proposed, for the deeplink badge. */
  reviewQueueCount = signal<number>(0);

  readonly trendBreaches = computed<number>(
    () => this.trend()?.totals.breaches ?? 0,
  );
  readonly trendRuns = computed<number>(
    () => this.trend()?.totals.runs_evaluated ?? 0,
  );
  readonly trendBreachRate = computed<string>(() => {
    const r = this.trend()?.totals.breach_rate;
    return typeof r === 'number' ? this.number(r * 100,1) : '—';
  });
  readonly trendAvgComposite = computed<string>(() => {
    const buckets = (this.trend()?.series ?? []).filter(b => b.avg_composite != null);
    if (!buckets.length) return '—';
    const weighted = buckets.reduce((acc, b) => acc + (b.avg_composite ?? 0) * (b.observed_composite_count ?? 0), 0);
    const total = buckets.reduce((acc, b) => acc + (b.observed_composite_count ?? 0), 0);
    return total > 0 ? this.number(weighted / total,1) : '—';
  });
  readonly unsupportedClaimsAverage = computed<number | null>(() => {
    const buckets = (this.trend()?.series ?? []).filter(b => b.avg_hallucination != null);
    if (buckets.length) {
      const weighted = buckets.reduce((acc, b) => acc + (b.avg_hallucination ?? 0) * (b.observed_hallucination_count ?? 0), 0);
      const total = buckets.reduce((acc, b) => acc + (b.observed_hallucination_count ?? 0), 0);
      if (total > 0) return weighted / total;
    }
    const rows = this.history().filter((row) => typeof row.hallucination_rate === 'number');
    if (!rows.length) return null;
    return rows.reduce((acc, row) => acc + (row.hallucination_rate ?? 0), 0) / rows.length;
  });
  readonly trendHealthTone = computed<'pos' | 'warn' | 'neg'>(() => {
    const rate = this.trend()?.totals.breach_rate;
    if (rate == null) return 'warn';
    if (rate === 0) return 'pos';
    if (rate < 0.1) return 'warn';
    return 'neg';
  });

  /**
   * Pre-computed per-bucket render info for the mini breach bars so the
   * template doesn't have to call `Math.max`/`Math.round` (Angular
   * templates have no access to the global Math unless explicitly
   * exposed). Height is normalized to the busiest day.
   */
  readonly trendBars = computed(() => {
    const series = this.trend()?.series ?? [];
    const compositeThreshold = this.trend()?.thresholds?.composite_min ?? 0;
    const unsupportedThreshold = this.trend()?.thresholds?.hallucination_max ?? 1;
    if (!series.length) return [];
    const maxCount = series.reduce((acc, b) => Math.max(acc, b.count ?? 0), 0);
    const safe = maxCount > 0 ? maxCount : 1;
    return series.map((b) => {
      const ratio = (b.count ?? 0) / safe;
      const isBreach = (b.breaches ?? 0) > 0;
      return {
        bucket: b.bucket,
        count: b.count ?? 0,
        heightPx: Math.max(2, Math.round(ratio * 28)),
        isBreach,
      };
    });
  });

  readonly componentHealthItems = computed(() =>
    (this.componentHealth()?.components ?? []).map((item) => {
      const rate = item.breach_rate;
      return {
        ...item,
        rateLabel: rate == null ? '—' : `${this.number(rate * 100,1)} %`,
        tone: (rate == null ? 'warn' : rate === 0 ? 'pos' : rate < 0.2 ? 'warn' : 'neg') as
          | 'pos'
          | 'warn'
          | 'neg',
      };
    }),
  );
  readonly componentHealthBreaches = computed(() =>
    this.componentHealthItems().reduce((acc, item) => acc + (item.breaches ?? 0), 0),
  );
  readonly componentHealthTone = computed<'pos' | 'warn' | 'neg'>(() => {
    const total = this.componentHealthBreaches();
    if (!this.componentHealthItems().some(item => item.evaluated > 0)) return 'warn';
    if (total === 0) return 'pos';
    const evaluated = this.componentHealthItems().reduce(
      (acc, item) => acc + (item.evaluated ?? 0),
      0,
    );
    const rate = evaluated > 0 ? total / evaluated : 0;
    return rate < 0.1 ? 'warn' : 'neg';
  });

  readonly dimensionLabels = computed(() => Object.keys(this.dimensions()).map(key=>this.code('dimension',key)));
  readonly dimensionKeys = computed(() => Object.keys(this.dimensions()));

  readonly compositeDisplay = computed(() => {
    const v = this.latest()?.composite_score;
    return typeof v === 'number' ? this.number(v,1) : '—';
  });

  readonly unsupportedClaimsDisplay = computed(() => {
    const v = this.unsupportedClaimsAverage();
    return typeof v === 'number' ? this.number(v*100,1) : '—';
  });

  readonly unsupportedClaimsHint = computed(() => {
    const latest = this.latest()?.hallucination_rate;
    if (typeof latest !== 'number') return this.i18n.t('observability.quality.average_hint',{period:this.periodLabel()});
    return this.i18n.t('observability.quality.latest_hint',{period:this.periodLabel(),rate:this.number(latest*100,1)});
  });

  readonly driftDisplay = computed(() => {
    const v = this.latest()?.drift_rate;
    return typeof v === 'number' ? this.number(v*100,1) : '—';
  });

  readonly compositeTrend = computed<'up' | 'down' | null>(() => {
    const hist = this.history();
    if (hist.length < 2) return null;
    const a = hist[0].composite_score;
    const b = hist[1].composite_score;
    if (a == null || b == null) return null;
    return a >= b ? 'up' : 'down';
  });

  readonly compositeDelta = computed(() => {
    const hist = this.history();
    if (hist.length < 2) return '';
    const a = hist[0].composite_score;
    const b = hist[1].composite_score;
    if (a == null || b == null) return '';
    const d = a - b;
    return `${d >= 0 ? '+' : ''}${this.number(d,1)}`;
  });

  readonly unsupportedClaimsTrend = computed<'up' | 'down' | null>(() => {
    const buckets = (this.trend()?.series ?? []).filter((b) => (b.count ?? 0) > 0 && b.avg_hallucination != null);
    if (buckets.length >= 2) {
      const current = buckets[buckets.length - 1].avg_hallucination ?? 0;
      const previous = buckets[buckets.length - 2].avg_hallucination ?? 0;
      return current <= previous ? 'down' : 'up';
    }
    const hist = this.history();
    if (hist.length < 2) return null;
    const current = hist[0].hallucination_rate;
    const previous = hist[1].hallucination_rate;
    if (current == null || previous == null) return null;
    return current <= previous ? 'down' : 'up';
  });

  readonly driftTrend = computed<'up' | 'down' | null>(() => {
    const hist = this.history();
    if (hist.length < 2) return null;
    const a = hist[0].drift_rate;
    const b = hist[1].drift_rate;
    if (a == null || b == null) return null;
    return a <= b ? 'up' : 'down';
  });

  readonly claims = computed(() => this.latest()?.claim_audit?.claims ?? []);

  /** Sparkline series — oldest first. */
  readonly compositeSeries = computed<number[]>(() => {
    const reversed = [...this.history()].reverse();
    return reversed.map((e) => e.composite_score).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  });
  readonly unsupportedClaimsSeries = computed<number[]>(() => {
    const trendSeries = this.trend()?.series ?? [];
    if (trendSeries.length >= 2) {
      return trendSeries.filter(e => e.avg_hallucination != null).map((e) => e.avg_hallucination! * 100);
    }
    const reversed = [...this.history()].reverse();
    return reversed.filter(e => e.hallucination_rate != null).map((e) => e.hallucination_rate! * 100);
  });
  readonly driftSeries = computed<number[]>(() => {
    const reversed = [...this.history()].reverse();
    return reversed.filter(e => e.drift_rate != null).map((e) => e.drift_rate! * 100);
  });
  readonly evaluationsSeries = computed<number[]>(() => {
    const n = Math.min(this.history().length, 20);
    if (n < 2) return [];
    return Array.from({ length: n }, (_, i) => i + 1);
  });

  readonly canRunEvaluation = computed(() => !!this.latest()?.run_id);

  readonly radarData = computed<ChartData<'radar'>>(() => {
    const latest = this.latest();
    const scores = latest?.scores ?? {};
    const keys = this.dimensionKeys();
    const labels = keys.map((k) => this.code('dimension',k));
    const current = keys.map((k) => scaleTo100(scores[k]));

    return {
      labels,
      datasets: [
        {
          label: this.i18n.t('observability.quality.current'),
          data: current,
          backgroundColor: PALETTE.current.fill,
          borderColor: PALETTE.current.stroke,
          pointBackgroundColor: PALETTE.current.stroke,
          pointRadius: 3,
          borderWidth: 2,
        },

      ],
    };
  });

  readonly historyData = computed<ChartData<'line'>>(() => {
    const reversed = [...this.history()].reverse();
    const labels = reversed.map((e) =>
      e.created_at ? new Date(e.created_at).toLocaleDateString(this.i18n.locale()) : '—',
    );
    return {
      labels,
      datasets: [
        {
          label: this.i18n.t('observability.quality.composite'),
          data: reversed.map((e) => e.composite_score ?? null),
          borderColor: PALETTE.current.stroke,
          backgroundColor: 'rgba(0, 188, 212, 0.15)',
          fill: true,
          tension: 0.35,
          pointRadius: 3,
          borderWidth: 2,
        },
        {
          label: this.i18n.t('observability.quality.unsupported') + ' (%)',
          data: reversed.map((e) => e.hallucination_rate == null ? null : e.hallucination_rate * 100),
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239,68,68,0.08)',
          tension: 0.35,
          pointRadius: 3,
          borderWidth: 2,
          yAxisID: 'y1',
        },
      ],
    };
  });

  readonly radarOptions: ChartConfiguration<'radar'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: '#cbd5e1' } } },
    scales: {
      r: {
        min: 0,
        max: 100,
        angleLines: { color: 'rgba(255,255,255,0.08)' },
        grid: { color: 'rgba(255,255,255,0.06)' },
        pointLabels: { color: '#94a3b8', font: { size: 11 } },
        ticks: { display: false, stepSize: 20 },
      },
    },
  };

  readonly lineOptions: ChartConfiguration<'line'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: '#cbd5e1' } } },
    scales: {
      x: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#94a3b8' } },
      y: {
        min: 0,
        max: 100,
        grid: { color: 'rgba(255,255,255,0.06)' },
        ticks: { color: '#94a3b8' },
      },
      y1: {
        position: 'right',
        min: 0,
        max: 100,
        grid: { display: false },
        ticks: { color: '#94a3b8' },
      },
    },
  };

  constructor() {
    effect(() => {
      this.workspace.current()?.id; this.systemFilter(); this.period();
      untracked(() => this.refresh());
    });
  }
  setScope(systemId:string,since:string):void {
    this.systemFilter.set(systemId);this.period.set(since==='30d'?'30d':'7d');
    void this.router.navigate([],{relativeTo:this.route,queryParams:{systemId:systemId||null,system_id:null,since:this.period()},queryParamsHandling:'merge',replaceUrl:true});
  }
  ngOnDestroy():void { this.cancel.next();this.cancel.complete(); }
  ngOnInit(): void {
    this.zone.runOutsideAngular(() => {
      const schedule = (window as any).requestIdleCallback ?? window.setTimeout;
      schedule(() => {
        this.zone.run(() => this.chartsReady.set(true));
      }, { timeout: 1500 } as any);
    });
  }

  refresh(): void {
    this.cancel.next();this.loading.set(true);this.loadError.set(false);
    this.latest.set(null);this.history.set([]);this.trend.set(null);this.componentHealth.set(null);this.systems.set([]);
    const scope = {since:this.period(), ...(this.systemFilter()?{system_id:this.systemFilter()}: {})};
    this.canonical.listSystems().pipe(takeUntil(this.cancel)).subscribe(rows=>this.systems.set(rows));
    this.api.get<DimensionsResponse>('/evaluation/dimensions').pipe(takeUntil(this.cancel)).subscribe({
      next: (res) => {
        this.dimensions.set(res?.dimensions ?? {});
      },
      error: () => {},
    });
    this.api.get<LatestResponse>('/evaluation/latest',scope).pipe(takeUntil(this.cancel)).subscribe({
      next: (res) => this.latest.set(res?.evaluation ?? null),
      error: () => this.latest.set(null),
    });
    this.api.get<HistoryResponse>('/evaluation/history', { limit: '20',...scope }).pipe(takeUntil(this.cancel)).subscribe({
      next: (res) => {
        this.history.set(res?.evaluations ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.history.set([]);this.loadError.set(true);
        this.loading.set(false);
      },
    });
    // Vague E / E1 — aggregate trend + review queue count
    this.canonical.getEvaluationTrend({ ...scope, group_by: 'day' }).pipe(takeUntil(this.cancel)).subscribe({
      next: (res) => this.trend.set(res),
      error: () => this.trend.set(null),
    });
    this.canonical.getEvaluationComponentHealth(scope).pipe(takeUntil(this.cancel)).subscribe({
      next: (res) => this.componentHealth.set(res),
      error: () => this.componentHealth.set(null),
    });
    this.canonical.getEvaluationReviewQueue({ ...scope, status: 'proposed', limit: 200 }).pipe(takeUntil(this.cancel)).subscribe({
      next: (res) => this.reviewQueueCount.set(res?.count ?? 0),
      error: () => this.reviewQueueCount.set(0),
    });
  }

  runEvaluation(): void {
    const runId = this.latest()?.run_id;
    if (runId) void this.router.navigateByUrl(this.navigation.objectUrlTree('run', runId));
  }
}

/** Judge dimensions already use a 0–100 scale; missing stays missing. */
function scaleTo100(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : null;
}
