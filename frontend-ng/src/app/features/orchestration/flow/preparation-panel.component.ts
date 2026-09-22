import { ChangeDetectionStrategy, Component, inject, input, OnInit, signal } from '@angular/core';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';

interface PreparationCheck {
  name: string;
  status: 'ready' | 'blocked' | 'not_checked' | 'not_applicable';
  detail?: string | null;
}

@Component({
  selector: 'app-preparation-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="preparation" [attr.aria-label]="i18n.t('flow.preparation.title')">
      <h2>{{ i18n.t('flow.preparation.title') }}</h2>
      @if (ready() !== null) {
        <p role="status">{{ i18n.t(ready() ? 'flow.preparation.ready' : 'flow.preparation.not_ready') }}</p>
      }
      <ul>
        @for (check of checks(); track check.name) {
          <li>{{ i18n.t('flow.preparation.' + check.name) }} — {{ label(check) }}</li>
        }
      </ul>
    </section>
  `,
  styles: `
    .preparation {
      display: grid;
      gap: 4px;
      margin: 0;
      padding: 12px;
      border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      border-radius: 12px;
      h2, p, ul { margin: 0; }
      h2 { font-size: 1rem; }
    }
  `,
})
export class PreparationPanelComponent implements OnInit {
  readonly systemId = input.required<string>();
  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);
  protected readonly ready = signal<boolean | null>(null);
  protected readonly checks = signal<PreparationCheck[]>([]);

  ngOnInit(): void {
    this.canonical.automationPreparation(this.systemId()).subscribe({
      next: (report) => {
        this.ready.set(report.ready);
        this.checks.set(report.checks ?? []);
      },
      error: () => {
        this.ready.set(false);
        this.checks.set([]);
      },
    });
  }

  protected label(check: PreparationCheck): string {
    const status = this.i18n.t(`flow.preparation.${check.status}`);
    return check.detail ? `${status} (${check.detail})` : status;
  }
}
