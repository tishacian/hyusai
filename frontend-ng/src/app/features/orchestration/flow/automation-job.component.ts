import { ChangeDetectionStrategy, Component, inject, input, OnInit, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { automationJobLines, jobLineText, type AutomationJobView, type JobLine } from './automation-job';

@Component({
  selector: 'app-automation-job',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="automation-job" aria-label="{{ i18n.t('flow.automation.work.title') }}">
      <h2>{{ i18n.t('flow.automation.work.title') }}</h2>
      @if (unpublished()) {
        <p role="status">{{ i18n.t('flow.automation.work.unpublished') }}</p>
      } @else if (lines(); as shown) {
        <p>{{ shown.objective ? i18n.t('flow.automation.work.objective', { text: shown.objective }) : i18n.t('flow.automation.work.objective.absent') }}</p>
        @for (line of shown.value; track $index) {
          <p>{{ lineText(line) }}</p>
        }
        <p>{{ shown.proof ? i18n.t('flow.automation.work.proof', { run: shown.proof }) : i18n.t('flow.automation.work.proof.absent') }}</p>
      }
    </section>
  `,
  styles: `
    .automation-job {
      display: grid;
      gap: 4px;
      margin: 0;
      padding: 12px;
      border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      border-radius: 12px;
      h2, p { margin: 0; }
      h2 { font-size: 1rem; }
    }
  `,
})
export class AutomationJobComponent implements OnInit {
  readonly systemId = input.required<string>();
  readonly i18n = inject(I18nService);
  protected readonly lineText = (line: JobLine): string => jobLineText(this.i18n.t, line);
  private readonly canonical = inject(CanonicalApiService);
  protected readonly unpublished = signal(false);
  protected readonly lines = signal<ReturnType<typeof automationJobLines> | null>(null);

  ngOnInit(): void {
    this.canonical.automationWorkJob(this.systemId()).subscribe({
      next: (job) => this.lines.set(automationJobLines(job as AutomationJobView)),
      error: (error: unknown) => {
        const code = error instanceof HttpErrorResponse ? error.error?.detail?.code : '';
        this.unpublished.set(code === 'unpublished' || code === 'not_automation');
      },
    });
  }
}
