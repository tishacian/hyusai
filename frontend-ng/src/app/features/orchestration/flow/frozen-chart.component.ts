import { ChangeDetectionStrategy, Component, inject, input, OnInit, signal } from '@angular/core';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';

interface ChartPoint {
  id: string;
  name: string;
  version: number;
  proof: string;
}

@Component({
  selector: 'app-frozen-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="chart" [attr.aria-label]="i18n.t('flow.chart.title')">
      <h2>{{ i18n.t('flow.chart.title') }}</h2>
      <p>{{ proofLine() }}</p>
      @if (!points().length) {
        <p>{{ i18n.t('flow.chart.empty') }}</p>
      } @else {
        <ul>
          @for (point of points(); track point.id) {
            <li>
              <button type="button" (click)="open(point.id)">{{ point.name }} · {{ point.version }}</button>
            </li>
          }
        </ul>
      }
      @if (opened(); as path) {
        <p role="status">{{ path }}</p>
      }
    </section>
  `,
  styles: `
    .chart {
      display: grid;
      gap: 4px;
      margin: 0;
      padding: 12px;
      border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      border-radius: 12px;
      h2, p, ul { margin: 0; }
      h2 { font-size: 1rem; }
      button { font: inherit; }
    }
  `,
})
export class FrozenChartComponent implements OnInit {
  readonly systemId = input.required<string>();
  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);
  protected readonly points = signal<ChartPoint[]>([]);
  protected readonly opened = signal('');
  protected readonly proofLine = signal('');

  ngOnInit(): void {
    this.canonical.automationChart(this.systemId()).subscribe({
      next: (chart) => this.points.set(chart.points ?? []),
      error: () => this.points.set([]),
    });
    this.canonical.automationProof(this.systemId()).subscribe({
      next: (proof) => this.proofLine.set(this.describe(proof)),
      error: () => this.proofLine.set(this.i18n.t('flow.proof.absent')),
    });
  }

  protected open(pointId: string): void {
    this.canonical.automationChartPoint(this.systemId(), pointId).subscribe({
      next: (path) => {
        const dossier = `${path.dossier.name} · ${path.dossier.version}`;
        const run = path.run ? this.i18n.t('flow.chart.run', { status: path.run.status }) : this.i18n.t('flow.chart.no_run');
        this.opened.set(`${dossier} — ${run}`);
      },
      error: () => this.opened.set(this.i18n.t('flow.chart.no_run')),
    });
  }

  private describe(proof: { status: string; sealed?: boolean | null; called?: boolean | null }): string {
    if (proof.status !== 'present') return this.i18n.t('flow.proof.absent');
    const base = this.i18n.t('flow.proof.present');
    if (proof.sealed === true && proof.called === false) return `${base} ${this.i18n.t('flow.proof.sealed')}`;
    return base;
  }
}
