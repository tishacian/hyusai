import {
  ChangeDetectionStrategy,
  Component,
  NgZone,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration, ChartData } from 'chart.js';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import {
  CanonicalApiService,
  type EvaluationTrendResponse,
} from '@app/core/canonical-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  GlyphComponent,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';

interface DimensionsResponse {
  dimensions: Record<string, string>;
}

interface EvaluationRow {
  id: string;
  scores?: Record<string, number>;
  composite_score?: number;
  hallucination_rate?: number;
  drift_rate?: number;
  claim_audit?: { claims?: Array<{ text: string; verdict: string; score: number }> };
  created_at?: string | null;
}

interface HistoryResponse {
  evaluations: EvaluationRow[];
}

interface LatestResponse {
  evaluation: EvaluationRow | null;
}

interface LastEvalContext {
  agent_id: string;
  query: string;
  response: string;
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
    RouterLink,
    BaseChartDirective,
    IconComponent,
    StatReadoutComponent,
    EmptyStateComponent,
    PageFrameComponent,
    GlyphComponent,
    TagComponent,
  ],
  template: `
    <ck-page-frame
      eyebrow="Measure · Observability"
      title="Quality"
      description="Multi-dimensional quality scores, claim audits and trust signals — live from the evaluation engine."
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
          Refresh
        </button>
        <button
          type="button"
          (click)="runEvaluation()"
          [disabled]="running() || !canRunEvaluation()"
          [title]="canRunEvaluation() ? 'Score the last chat exchange' : 'Send a message in the chat first'"
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
          {{ running() ? 'Scoring…' : 'Run evaluation' }}
        </button>
      </div>

    <!-- Vague E / E1 — Threshold monitoring strip (7d aggregate).
         Sits above the per-run tiles because "are we drifting over time?"
         is the question an operator asks first when opening Quality. -->
    @if (trend(); as t) {
      <section
        class="t-card t-elevated rounded-md p-4 mb-4"
        [style.display]="'grid'"
        [style.gridTemplateColumns]="'1fr 1fr 1fr auto'"
        [style.gap.px]="16"
        [style.alignItems]="'center'"
      >
        <div>
          <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="6" [style.marginBottom.px]="4">
            <ck-glyph name="pulse" [size]="12" />
            <span class="ck-mono" [style.fontSize.px]="10" [style.letterSpacing]="'0.08em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-3)'">
              Threshold monitoring · 7d
            </span>
          </div>
          <div [style.display]="'flex'" [style.alignItems]="'baseline'" [style.gap.px]="10">
            <span [style.fontSize.px]="22" [style.fontWeight]="600" [style.color]="'var(--ck-fg-1)'">
              {{ trendRuns() }}
            </span>
            <span [style.fontSize.px]="11" [style.color]="'var(--ck-fg-3)'">
              runs evaluated
            </span>
          </div>
          <div [style.fontSize.px]="11" [style.color]="'var(--ck-fg-3)'" [style.marginTop.px]="2">
            Avg composite {{ trendAvgComposite() }} / 100
          </div>
        </div>

        <div>
          <div [style.fontSize.px]="10" [style.letterSpacing]="'0.08em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-3)'" [style.marginBottom.px]="4">
            Breaches
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
              {{ trendBreachRate() }}% of runs
            </ck-tag>
          </div>
          <div [style.fontSize.px]="11" [style.color]="'var(--ck-fg-3)'" [style.marginTop.px]="2">
            Thresholds: composite ≥ {{ t.thresholds.composite_min }},
            hallucination ≤ {{ (t.thresholds.hallucination_max * 100).toFixed(0) }}%
          </div>
        </div>

        <div>
          <div [style.fontSize.px]="10" [style.letterSpacing]="'0.08em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-3)'" [style.marginBottom.px]="6">
            Daily breach count
          </div>
          @if (trendBars().length > 0) {
            <div [style.display]="'flex'" [style.alignItems]="'flex-end'" [style.gap.px]="3" [style.height.px]="28">
              @for (bar of trendBars(); track bar.bucket) {
                <div
                  [title]="bar.bucket + ' — ' + bar.count + ' run(s)'"
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
              No runs evaluated in the window.
            </div>
          }
        </div>

        <a
          routerLink="/steering/review-queue"
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
          [title]="reviewQueueCount() + ' proposed decisions awaiting review'"
        >
          <ck-glyph name="crosshair" [size]="14" />
          Review queue
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

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <ck-stat-readout variant="tile"
        label="Composite score"
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
        label="Evaluations run"
        [value]="history().length.toString()"
        icon="history"
        [sparkline]="evaluationsSeries()"
        sparklineTone="neutral"
      />
      <ck-stat-readout variant="tile"
        label="Hallucination rate"
        [value]="hallucinationDisplay()"
        unit="%"
        icon="alert-triangle"
        [trend]="hallucinationTrend()"
        trendSentiment="negative"
        [sparkline]="hallucinationSeries()"
        sparklineTone="negative"
      />
      <ck-stat-readout variant="tile"
        label="Drift rate"
        [value]="driftDisplay()"
        unit="%"
        icon="waves"
        [trend]="driftTrend()"
        trendSentiment="negative"
        [sparkline]="driftSeries()"
        sparklineTone="negative"
      />
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <!-- Radar chart -->
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="radar" [size]="16" class="text-brand-400" />
            Quality radar · {{ dimensionLabels().length }} dimensions
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{ latest() ? 'Latest run' : 'No data' }}
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
                title="No evaluation yet"
                description="Chat with a system, then run an evaluation to populate this radar."
              />
            </div>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>

      <!-- History -->
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="history" [size]="16" class="text-brand-400" />
            Score history
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            Last {{ history().length }}
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
                title="No history yet"
                description="Evaluations accumulate here as you score responses."
              />
            </div>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>
    </div>

    <!-- Claim audit -->
    <section class="t-card t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="shield-check" [size]="16" class="text-brand-400" />
          Claim audit
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          {{ claims().length }} claims
        </span>
      </div>
      @if (claims().length === 0) {
        <app-empty-state
          size="sm"
          icon="shield-check"
          title="No claims audited yet"
          description="Run an evaluation to see per-claim grounding."
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
                <div class="text-white">{{ claim.text }}</div>
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
                    {{ claim.verdict }}
                  </span>
                  <span>Confidence {{ claim.score }}%</span>
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
export class QualityDashboardComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly zone = inject(NgZone);
  private readonly toast = inject(ToastrService);

  chartsReady = signal(false);
  loading = signal(false);
  running = signal(false);

  latest = signal<EvaluationRow | null>(null);
  history = signal<EvaluationRow[]>([]);
  dimensions = signal<Record<string, string>>({});

  /** Aggregate trend (Vague E / E1) — feeds the "Threshold monitoring" strip. */
  trend = signal<EvaluationTrendResponse | null>(null);
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
    return typeof r === 'number' ? (r * 100).toFixed(1) : '—';
  });
  readonly trendAvgComposite = computed<string>(() => {
    const buckets = this.trend()?.series ?? [];
    if (!buckets.length) return '—';
    const weighted = buckets.reduce((acc, b) => acc + (b.avg_composite ?? 0) * (b.count ?? 0), 0);
    const total = buckets.reduce((acc, b) => acc + (b.count ?? 0), 0);
    return total > 0 ? (weighted / total).toFixed(1) : '—';
  });
  readonly trendHealthTone = computed<'pos' | 'warn' | 'neg'>(() => {
    const rate = this.trend()?.totals.breach_rate ?? 0;
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
    const threshold = this.trend()?.thresholds?.composite_min ?? 0;
    if (!series.length) return [];
    const maxCount = series.reduce((acc, b) => Math.max(acc, b.count ?? 0), 0);
    const safe = maxCount > 0 ? maxCount : 1;
    return series.map((b) => {
      const ratio = (b.count ?? 0) / safe;
      const isBreach =
        typeof b.avg_composite === 'number' && b.avg_composite < threshold;
      return {
        bucket: b.bucket,
        count: b.count ?? 0,
        heightPx: Math.max(2, Math.round(ratio * 28)),
        isBreach,
      };
    });
  });

  readonly dimensionLabels = computed(() => Object.values(this.dimensions()));
  readonly dimensionKeys = computed(() => Object.keys(this.dimensions()));

  readonly compositeDisplay = computed(() => {
    const v = this.latest()?.composite_score;
    return typeof v === 'number' ? v.toFixed(1) : '—';
  });

  readonly hallucinationDisplay = computed(() => {
    const v = this.latest()?.hallucination_rate;
    return typeof v === 'number' ? (v * 100).toFixed(1) : '—';
  });

  readonly driftDisplay = computed(() => {
    const v = this.latest()?.drift_rate;
    return typeof v === 'number' ? (v * 100).toFixed(1) : '—';
  });

  readonly compositeTrend = computed<'up' | 'down' | null>(() => {
    const hist = this.history();
    if (hist.length < 2) return null;
    const a = hist[0].composite_score ?? 0;
    const b = hist[1].composite_score ?? 0;
    return a >= b ? 'up' : 'down';
  });

  readonly compositeDelta = computed(() => {
    const hist = this.history();
    if (hist.length < 2) return '';
    const a = hist[0].composite_score ?? 0;
    const b = hist[1].composite_score ?? 0;
    const d = a - b;
    return `${d >= 0 ? '+' : ''}${d.toFixed(1)}`;
  });

  readonly hallucinationTrend = computed<'up' | 'down' | null>(() => {
    const hist = this.history();
    if (hist.length < 2) return null;
    const a = hist[0].hallucination_rate ?? 0;
    const b = hist[1].hallucination_rate ?? 0;
    return a <= b ? 'up' : 'down';
  });

  readonly driftTrend = computed<'up' | 'down' | null>(() => {
    const hist = this.history();
    if (hist.length < 2) return null;
    const a = hist[0].drift_rate ?? 0;
    const b = hist[1].drift_rate ?? 0;
    return a <= b ? 'up' : 'down';
  });

  readonly claims = computed(() => this.latest()?.claim_audit?.claims ?? []);

  /** Sparkline series — oldest first. */
  readonly compositeSeries = computed<number[]>(() => {
    const reversed = [...this.history()].reverse();
    return reversed.map((e) => e.composite_score ?? 0).filter((v) => Number.isFinite(v));
  });
  readonly hallucinationSeries = computed<number[]>(() => {
    const reversed = [...this.history()].reverse();
    return reversed.map((e) => (e.hallucination_rate ?? 0) * 100);
  });
  readonly driftSeries = computed<number[]>(() => {
    const reversed = [...this.history()].reverse();
    return reversed.map((e) => (e.drift_rate ?? 0) * 100);
  });
  readonly evaluationsSeries = computed<number[]>(() => {
    const n = Math.min(this.history().length, 20);
    if (n < 2) return [];
    return Array.from({ length: n }, (_, i) => i + 1);
  });

  readonly canRunEvaluation = computed(() => !!this.readLastContext());

  readonly radarData = computed<ChartData<'radar'>>(() => {
    const latest = this.latest();
    const scores = latest?.scores ?? {};
    const keys = this.dimensionKeys();
    const labels = keys.map((k) => this.dimensions()[k] ?? k);
    const current = keys.map((k) => scaleTo100(scores[k]));
    const target = keys.map(() => 85);
    return {
      labels,
      datasets: [
        {
          label: 'Current',
          data: current,
          backgroundColor: PALETTE.current.fill,
          borderColor: PALETTE.current.stroke,
          pointBackgroundColor: PALETTE.current.stroke,
          pointRadius: 3,
          borderWidth: 2,
        },
        {
          label: 'Target',
          data: target,
          backgroundColor: PALETTE.target.fill,
          borderColor: PALETTE.target.stroke,
          borderDash: [4, 4],
          pointRadius: 0,
          borderWidth: 1.5,
        },
      ],
    };
  });

  readonly historyData = computed<ChartData<'line'>>(() => {
    const reversed = [...this.history()].reverse();
    const labels = reversed.map((e) =>
      e.created_at ? new Date(e.created_at).toLocaleDateString() : '—',
    );
    return {
      labels,
      datasets: [
        {
          label: 'Composite score',
          data: reversed.map((e) => e.composite_score ?? 0),
          borderColor: PALETTE.current.stroke,
          backgroundColor: 'rgba(0, 188, 212, 0.15)',
          fill: true,
          tension: 0.35,
          pointRadius: 3,
          borderWidth: 2,
        },
        {
          label: 'Hallucination (%)',
          data: reversed.map((e) => (e.hallucination_rate ?? 0) * 100),
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
        max: 50,
        grid: { display: false },
        ticks: { color: '#94a3b8' },
      },
    },
  };

  ngOnInit(): void {
    this.refresh();
    this.zone.runOutsideAngular(() => {
      const schedule = (window as any).requestIdleCallback ?? window.setTimeout;
      schedule(() => {
        this.zone.run(() => this.chartsReady.set(true));
      }, { timeout: 1500 } as any);
    });
  }

  refresh(): void {
    this.loading.set(true);
    this.api.get<DimensionsResponse>('/evaluation/dimensions').subscribe({
      next: (res) => {
        this.dimensions.set(res?.dimensions ?? {});
      },
      error: () => {},
    });
    this.api.get<LatestResponse>('/evaluation/latest').subscribe({
      next: (res) => this.latest.set(res?.evaluation ?? null),
      error: () => this.latest.set(null),
    });
    this.api.get<HistoryResponse>('/evaluation/history', { limit: '20' }).subscribe({
      next: (res) => {
        this.history.set(res?.evaluations ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.history.set([]);
        this.loading.set(false);
      },
    });
    // Vague E / E1 — aggregate trend + review queue count
    this.canonical.getEvaluationTrend({ since: '7d', group_by: 'day' }).subscribe({
      next: (res) => this.trend.set(res),
      error: () => this.trend.set(null),
    });
    this.canonical.getEvaluationReviewQueue({ status: 'proposed', limit: 200 }).subscribe({
      next: (res) => this.reviewQueueCount.set(res?.count ?? 0),
      error: () => this.reviewQueueCount.set(0),
    });
  }

  runEvaluation(): void {
    const ctx = this.readLastContext();
    if (!ctx) {
      this.toast.warning('Send a message in the chat first', 'Evaluation');
      return;
    }
    this.running.set(true);
    this.api.post<EvaluationRow>('/evaluation/score', ctx).subscribe({
      next: (res) => {
        this.latest.set(res);
        this.history.update((h) => [res, ...h].slice(0, 20));
        this.running.set(false);
        this.toast.success(
          `Composite ${Number(res?.composite_score ?? 0).toFixed(1)}/100`,
          'Evaluation complete',
        );
      },
      error: (err) => {
        this.running.set(false);
        this.toast.error(err?.error?.detail ?? 'Evaluation failed', 'Evaluation');
      },
    });
  }

  private readLastContext(): LastEvalContext | null {
    try {
      const raw = localStorage.getItem('agentium:last_eval_context');
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed?.query || !parsed?.response) return null;
      return parsed as LastEvalContext;
    } catch {
      return null;
    }
  }
}

/** Backend scores come on a 0-5 (or 0-10) scale depending on dimension — normalize to 0-100. */
function scaleTo100(v: unknown): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) return 0;
  if (v <= 1) return Math.round(v * 100);
  if (v <= 5) return Math.round((v / 5) * 100);
  if (v <= 10) return Math.round((v / 10) * 100);
  return Math.min(100, Math.round(v));
}
