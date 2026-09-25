import { ChangeDetectionStrategy, Component, ElementRef, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { focusAfterRoute, navigationFocusFromState } from '@app/core/route-focus';
import { automationJobLines, jobLineText, type JobLine } from '@app/features/orchestration/flow/automation-job';
import { WorkApiService, type WorkAutomationJob } from './work-api.service';
import { WorkBarComponent } from './work-bar.component';
import { WorkAppHeaderComponent } from './work-app-header.component';
import { returnToFromParams } from './work-return';

@Component({
  selector: 'app-work-automation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, WorkBarComponent, WorkAppHeaderComponent],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work" data-brand-scope data-theme="light">
      <app-work-bar [appContext]="name() || null" />
      <app-work-app-header
        [title]="name() || i18n.t('experience.work.automation.section')"
        [eyebrow]="i18n.t('experience.work.eyebrow.automation')"
        [identifier]="systemId || null"
        [status]="running() ? i18n.t('experience.work.automation.running') : null"
        [returnTo]="cockpitReturnTo()"
        defaultBackKey="experience.work.back_apps"
      >
        @if (lines(); as shown) {
          <button type="button" class="xp-work-btn xp-work-btn-primary" [disabled]="running()" (click)="runPublished()">
            {{ i18n.t('experience.work.automation.run') }}
          </button>
          <button type="button" class="xp-work-btn" [disabled]="!shown.proof || exporting()" (click)="exportPackage()">
            {{ i18n.t('experience.work.automation.export') }}
          </button>
        }
      </app-work-app-header>
      <section class="xp-work-main xp-work-automation-detail" role="main" aria-labelledby="work-app-title">
        @if (missing()) {
          <p role="alert">{{ i18n.t('experience.work.not_found.title') }}</p>
        } @else if (lines(); as shown) {
          <p>{{ shown.objective ? i18n.t('flow.automation.work.objective', { text: shown.objective }) : i18n.t('flow.automation.work.objective.absent') }}</p>
          @for (line of shown.value; track $index) {
            <p>{{ lineText(line) }}</p>
          }
          <p>{{ shown.proof ? i18n.t('flow.automation.work.proof', { run: shown.proof }) : i18n.t('flow.automation.work.proof.absent') }}</p>
          <p>{{ sharedProof() }}</p>
        }
      </section>
    </div>
  `,
})
export class WorkAutomationComponent {
  readonly i18n = inject(I18nService);
  protected readonly lineText = (line: JobLine): string => jobLineText(this.i18n.t, line);
  private readonly api = inject(WorkApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);
  protected readonly name = signal('');
  protected readonly missing = signal(false);
  protected readonly exporting = signal(false);
  protected readonly running = signal(false);
  protected readonly lines = signal<ReturnType<typeof automationJobLines> | null>(null);
  protected readonly sharedProof = signal('');
  protected readonly cockpitReturnTo = signal<string | null>(null);
  private runId: string | null = null;
  private flowSha = '';
  protected systemId = '';

  constructor() {
    const systemId = this.route.snapshot.paramMap.get('systemId') ?? '';
    this.systemId = systemId;
    this.cockpitReturnTo.set(returnToFromParams(this.route.snapshot.queryParamMap.get('returnTo')));
    this.api.automation(systemId).subscribe({
      next: (card) => this.show(card),
      error: () => {
        this.missing.set(true);
        queueMicrotask(() => this.focusRouteTarget());
      },
    });
  }

  protected runPublished(): void {
    if (!this.flowSha || this.running()) return;
    this.running.set(true);
    this.canonical.triggerRun(this.systemId, {
      trigger: 'manual',
      input_ref: { transcript: this.name() || 'Published automation' },
      expected_flow_sha256: this.flowSha,
    }).subscribe({
      next: (run) => this.wait(run.id),
      error: () => this.running.set(false),
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
    this.flowSha = card.job.flow_sha256 ?? '';
    this.runId = card.proof?.run_id ?? null;
    this.lines.set(automationJobLines(card));
    this.canonical.automationProof(this.systemId).subscribe({
      next: (proof) => this.sharedProof.set(proof.status === 'present'
        ? this.i18n.t('flow.proof.present')
        : this.i18n.t('flow.proof.absent')),
      error: () => this.sharedProof.set(this.i18n.t('flow.proof.absent')),
    });
    queueMicrotask(() => this.focusRouteTarget());
  }

  private focusRouteTarget(): void {
    focusAfterRoute(this.host.nativeElement, {
      focus: navigationFocusFromState(
        this.router.lastSuccessfulNavigation?.extras?.state
          ?? (globalThis.history?.state as Record<string, unknown> | null),
      ),
    });
  }

  private wait(runId: string, attempt = 0): void {
    this.canonical.getRun(runId).subscribe((run) => {
      if (attempt < 40 && (!run || run.status === 'pending' || run.status === 'running')) {
        setTimeout(() => this.wait(runId, attempt + 1), 1500);
        return;
      }
      this.api.automation(this.systemId).subscribe({
        next: (card) => {
          this.show(card);
          this.running.set(false);
        },
        error: () => this.running.set(false),
      });
    });
  }
}
