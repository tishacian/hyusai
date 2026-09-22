import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { automationJobLines } from '@app/features/orchestration/flow/automation-job';
import { WorkApiService, type WorkAutomationJob } from './work-api.service';

@Component({
  selector: 'app-work-automation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <section class="xp-work-automation-detail">
      <a routerLink="/work">{{ i18n.t('experience.work.back') }}</a>
      @if (missing()) {
        <p role="alert">{{ i18n.t('experience.work.not_found.title') }}</p>
      } @else if (lines(); as shown) {
        <h1>{{ name() }}</h1>
        <p>{{ shown.objective ? i18n.t('flow.automation.work.objective', { text: shown.objective }) : i18n.t('flow.automation.work.objective.absent') }}</p>
        <p>{{ shown.convention ? i18n.t('flow.automation.work.convention', { rate: shown.convention }) : i18n.t('flow.automation.work.convention.absent') }}</p>
        <p>{{ shown.gap ? i18n.t('flow.automation.work.gap', { gap: shown.gap }) : i18n.t('flow.automation.work.gap.absent') }}</p>
        <p>{{ shown.proof ? i18n.t('flow.automation.work.proof', { run: shown.proof }) : i18n.t('flow.automation.work.proof.absent') }}</p>
        <button type="button" [disabled]="!shown.proof || exporting()" (click)="exportPackage()">
          {{ i18n.t('experience.work.automation.export') }}
        </button>
      }
    </section>
  `,
  styles: `
    .xp-work-automation-detail {
      display: grid;
      gap: 8px;
      max-width: 40rem;
      margin: 24px auto;
      padding: 16px;
    }
  `,
})
export class WorkAutomationComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(WorkApiService);
  private readonly route = inject(ActivatedRoute);
  protected readonly name = signal('');
  protected readonly missing = signal(false);
  protected readonly exporting = signal(false);
  protected readonly lines = signal<ReturnType<typeof automationJobLines> | null>(null);
  private runId: string | null = null;
  private systemId = '';

  constructor() {
    const systemId = this.route.snapshot.paramMap.get('systemId') ?? '';
    this.systemId = systemId;
    this.api.automation(systemId).subscribe({
      next: (card) => this.show(card),
      error: () => this.missing.set(true),
    });
  }

  protected exportPackage(): void {
    if (!this.runId || this.exporting()) return;
    this.exporting.set(true);
    this.api.automationPackage(this.systemId, this.runId).subscribe({
      next: (body) => {
        const blob = new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `automation-${this.systemId}-${this.runId}.json`;
        link.click();
        URL.revokeObjectURL(url);
        this.exporting.set(false);
      },
      error: () => this.exporting.set(false),
    });
  }

  private show(card: WorkAutomationJob): void {
    this.name.set(card.job.name ?? '');
    this.runId = card.proof?.run_id ?? null;
    this.lines.set(automationJobLines(card));
  }
}
