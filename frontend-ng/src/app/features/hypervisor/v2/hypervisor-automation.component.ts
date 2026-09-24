import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { Router } from '@angular/router';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { automationJobLines, jobLineText, type AutomationJobView, type JobLine } from '@app/features/orchestration/flow/automation-job';

@Component({
  selector: 'app-hypervisor-automation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (rows().length > 0) {
      <section class="hv2-card" data-testid="hypervisor-automation-explanations">
        <h3>{{ i18n.t('hypervisor.v2.automation.title') }}</h3>
        @for (row of rows(); track row.id) {
          <article>
            <h4>{{ row.name }}</h4>
            <p>{{ row.objective ? i18n.t('flow.automation.work.objective', { text: row.objective }) : i18n.t('flow.automation.work.objective.absent') }}</p>
            @for (line of row.value; track $index) {
              <p>{{ lineText(line) }}</p>
            }
            <p>{{ row.proof ? i18n.t('flow.automation.work.proof', { run: row.proof }) : i18n.t('flow.automation.work.proof.absent') }}</p>
            <button type="button" (click)="open(row.id)">{{ i18n.t('hypervisor.v2.automation.open') }}</button>
          </article>
        }
      </section>
    }
  `,
})
export class HypervisorAutomationComponent implements OnInit {
  readonly i18n = inject(I18nService);
  protected readonly lineText = (line: JobLine): string => jobLineText(this.i18n.t, line);
  private readonly canonical = inject(CanonicalApiService);
  private readonly router = inject(Router);
  protected readonly rows = signal<Array<{ id: string; name: string; objective: string; value: JobLine[]; proof: string }>>([]);

  protected open(systemId: string): void {
    const path = ['', 'work', 'automation', systemId].join('/');
    void this.router.navigateByUrl(path);
  }

  ngOnInit(): void {
    this.canonical.hypervisorAutomationExplanations().subscribe({
      next: (body) => {
        this.rows.set((body.items ?? []).map((item) => {
          const lines = automationJobLines(item as AutomationJobView);
          return {
            id: item.job.system_id,
            name: item.job.name ?? '',
            ...lines,
          };
        }));
      },
      error: () => this.rows.set([]),
    });
  }
}
