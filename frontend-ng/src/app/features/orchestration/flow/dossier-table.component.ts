import { ChangeDetectionStrategy, Component, inject, input, OnInit, signal } from '@angular/core';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';

interface DossierRow {
  name: string;
  slug: string;
  version: number;
  run_status?: string | null;
  waiting: boolean;
  proof: string;
}

@Component({
  selector: 'app-dossier-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="dossiers" [attr.aria-label]="i18n.t('flow.dossiers.title')">
      <h2>{{ i18n.t('flow.dossiers.title') }}</h2>
      @if (!rows().length) {
        <p>{{ i18n.t('flow.dossiers.empty') }}</p>
      } @else {
        <ul>
          @for (row of rows(); track row.slug + ':' + row.version) {
            <li>
              {{ row.name }} — {{ i18n.t('flow.dossiers.version', { version: row.version }) }}
              — {{ i18n.t(row.proof === 'present' ? 'flow.dossiers.proof' : 'flow.dossiers.proof.absent') }}
              @if (row.waiting) {
                — {{ i18n.t('flow.dossiers.waiting') }}
              }
            </li>
          }
        </ul>
      }
    </section>
  `,
  styles: `
    .dossiers {
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
export class DossierTableComponent implements OnInit {
  readonly systemId = input.required<string>();
  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);
  protected readonly rows = signal<DossierRow[]>([]);

  ngOnInit(): void {
    this.canonical.automationDossiers(this.systemId()).subscribe({
      next: (report) => this.rows.set(report.rows ?? []),
      error: () => this.rows.set([]),
    });
  }
}
