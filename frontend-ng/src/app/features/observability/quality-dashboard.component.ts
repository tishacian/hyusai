import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration, ChartData } from 'chart.js';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';

interface Claim {
  text: string;
  verdict: 'supported' | 'unsupported' | 'partial';
  score: number;
}

interface EvalRun {
  at: string;
  score: number;
  latency: number;
}

@Component({
  selector: 'app-quality-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BaseChartDirective, IconComponent, SectionHeaderComponent, StatTileComponent],
  template: `
    <app-section-header
      breadcrumb="Measure"
      title="Observability"
      icon="activity"
      subtitle="Multi-dimensional quality scores, claim audits and trust signals."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="refresh-cw" [size]="14" /> Refresh
      </button>
    </app-section-header>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile label="Overall score" [value]="overallScore()" unit="/100" icon="target" trend="up" delta="+3" />
      <app-stat-tile label="Claims verified" value="1,842" icon="shield-check" trend="up" delta="+12%" />
      <app-stat-tile label="Hallucination rate" [value]="hallucinationRate()" unit="%" icon="alert-triangle" trend="down" delta="-0.8pt" />
      <app-stat-tile label="Latency p95" value="1.2" unit="s" icon="gauge" trend="down" delta="-90ms" />
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <!-- Radar chart -->
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="radar" [size]="16" class="text-brand-400" /> Quality radar · 12 dimensions
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            Last 7 days
          </span>
        </div>
        <div class="h-80">
          <canvas
            baseChart
            [data]="radarData"
            [options]="radarOptions"
            type="radar"
          ></canvas>
        </div>
      </section>

      <!-- History -->
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="history" [size]="16" class="text-brand-400" /> Score history
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            Rolling
          </span>
        </div>
        <div class="h-80">
          <canvas
            baseChart
            [data]="historyData"
            [options]="lineOptions"
            type="line"
          ></canvas>
        </div>
      </section>
    </div>

    <!-- Claims -->
    <section class="t-card t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="shield-check" [size]="16" class="text-brand-400" /> Recent claim audit
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          {{ claims.length }} claims
        </span>
      </div>
      <ul class="divide-y divide-white/5">
        @for (claim of claims; track claim.text) {
          <li class="px-5 py-3 flex items-start gap-3 text-sm">
            <div
              class="w-2 h-2 rounded-full mt-1.5 shrink-0"
              [class.bg-emerald-400]="claim.verdict === 'supported'"
              [class.bg-amber-400]="claim.verdict === 'partial'"
              [class.bg-red-400]="claim.verdict === 'unsupported'"
            ></div>
            <div class="flex-1 min-w-0">
              <div class="text-white truncate">{{ claim.text }}</div>
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
    </section>
  `,
})
export class QualityDashboardComponent implements OnInit {
  private readonly api = inject(ApiService);

  overallScore = signal<number>(86);
  hallucinationRate = signal<number>(2.4);

  readonly radarData: ChartData<'radar'> = {
    labels: [
      'Accuracy',
      'Relevance',
      'Completeness',
      'Faithfulness',
      'Coherence',
      'Fluency',
      'Safety',
      'Toxicity',
      'Bias',
      'PII',
      'Cost',
      'Latency',
    ],
    datasets: [
      {
        label: 'Current',
        data: [92, 88, 85, 91, 94, 96, 98, 99, 95, 97, 82, 88],
        backgroundColor: 'rgba(0, 188, 212, 0.18)',
        borderColor: '#00bcd4',
        pointBackgroundColor: '#00bcd4',
        pointRadius: 3,
        borderWidth: 2,
      },
      {
        label: 'Target',
        data: [85, 85, 85, 85, 85, 85, 95, 95, 85, 95, 80, 85],
        backgroundColor: 'rgba(139, 92, 246, 0.08)',
        borderColor: 'rgba(139, 92, 246, 0.6)',
        borderDash: [4, 4],
        pointRadius: 0,
        borderWidth: 1.5,
      },
    ],
  };

  readonly radarOptions: ChartConfiguration<'radar'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: '#cbd5e1' } },
    },
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

  readonly historyData: ChartData<'line'> = {
    labels: ['M', 'T', 'W', 'T', 'F', 'S', 'S'],
    datasets: [
      {
        label: 'Score',
        data: [82, 84, 83, 86, 88, 87, 86],
        borderColor: '#00bcd4',
        backgroundColor: 'rgba(0, 188, 212, 0.15)',
        fill: true,
        tension: 0.35,
        pointRadius: 3,
        borderWidth: 2,
      },
      {
        label: 'Latency p95 (s)',
        data: [1.5, 1.4, 1.4, 1.3, 1.25, 1.22, 1.2],
        borderColor: '#8b5cf6',
        backgroundColor: 'rgba(139, 92, 246, 0.05)',
        yAxisID: 'y1',
        tension: 0.35,
        pointRadius: 3,
        borderWidth: 2,
      },
    ],
  };

  readonly lineOptions: ChartConfiguration<'line'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: '#cbd5e1' } },
    },
    scales: {
      x: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#94a3b8' } },
      y: {
        min: 70,
        max: 100,
        grid: { color: 'rgba(255,255,255,0.06)' },
        ticks: { color: '#94a3b8' },
      },
      y1: {
        position: 'right',
        min: 0,
        max: 3,
        grid: { display: false },
        ticks: { color: '#94a3b8' },
      },
    },
  };

  readonly claims: Claim[] = [
    { text: 'The Q4 NPS jumped to 72 after the onboarding revamp', verdict: 'supported', score: 96 },
    { text: 'The new pricing plan doubled revenue per seat', verdict: 'partial', score: 74 },
    { text: 'Our SLA is 99.999% across all regions', verdict: 'unsupported', score: 28 },
    { text: 'Support deflection reached 41% this month', verdict: 'supported', score: 89 },
    { text: 'Every customer deploys in EU-West by default', verdict: 'partial', score: 62 },
  ];

  ngOnInit(): void {
    this.api.get<any>('/evaluation/summary').subscribe({
      next: (data) => {
        if (typeof data?.avg_score === 'number') this.overallScore.set(Math.round(data.avg_score));
        if (typeof data?.avg_hallucination === 'number')
          this.hallucinationRate.set(+(data.avg_hallucination * 100).toFixed(1));
      },
      error: () => {},
    });
  }
}
