import { Component, inject, signal, OnInit } from '@angular/core';
import { ApiService } from '@app/core/api.service';

@Component({
  selector: 'app-quality-dashboard',
  standalone: true,
  template: `
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">Observability</h1>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      @for (metric of metrics(); track metric.label) {
        <div class="p-5 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
          <div class="text-sm text-gray-500 dark:text-gray-400">{{ metric.label }}</div>
          <div class="text-2xl font-bold text-gray-900 dark:text-white mt-1">{{ metric.value }}</div>
        </div>
      }
    </div>

    @defer (on viewport) {
      <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Quality Scores</h2>
        <p class="text-gray-500 dark:text-gray-400">Chart.js visualization will be rendered here with ng2-charts.</p>
      </div>
    } @placeholder {
      <div class="h-48 flex items-center justify-center text-gray-400">Loading charts...</div>
    }
  `,
})
export class QualityDashboardComponent implements OnInit {
  private readonly api = inject(ApiService);
  metrics = signal<{ label: string; value: string }[]>([]);

  ngOnInit(): void {
    this.api.get<any>('/evaluation/summary').subscribe({
      next: (data) => {
        this.metrics.set([
          { label: 'Avg. Score', value: `${data.avg_score?.toFixed(1) ?? '--'}` },
          { label: 'Total Evaluations', value: `${data.total ?? 0}` },
          { label: 'Hallucination Rate', value: `${((data.avg_hallucination ?? 0) * 100).toFixed(1)}%` },
        ]);
      },
      error: () => {
        this.metrics.set([
          { label: 'Avg. Score', value: '--' },
          { label: 'Total Evaluations', value: '0' },
          { label: 'Hallucination Rate', value: '--' },
        ]);
      },
    });
  }
}
