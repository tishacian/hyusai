import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { GlyphComponent } from '@app/shared/cockpit';
import {
  NAWA_APP_NAME,
  NAWA_APP_SUBTITLE,
  NAWA_LOGO,
  type NawaUseCase,
} from './nawa-itsd.model';
import {
  NAWA_AVAILABILITY,
  businessTotals,
  hasSpeedup,
  matchesQuery,
  narrativeLines,
  serviceSummary,
  speedupLabel,
  staffingLines,
} from './nawa-catalog-view';
import { NawaItsdService } from './nawa-itsd.service';
import { NawaThemeToggleComponent } from './nawa-theme-toggle.component';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';

type CatalogFilter = 'all' | 'available' | 'family';

/** One entry as the screen reads it, so the template calls nothing per row. */
interface CatalogRow {
  item: NawaUseCase;
  summary: string;
  availability: string;
  speedup: string;
  fast: boolean;
}

/**
 * `/nawa/itsd` — catalogue of the 39 IT automation use cases extracted from the
 * customer workbook. Static asset only, no backend call (SPEC §7.1).
 *
 * Two readings of the same list. By default the page is the service catalogue
 * of the delivered application: what each service does, which family it belongs
 * to, whether it can be requested today. Staffing, monthly volumes and target
 * speed-ups are the customer's own requirement and payback figures — they stay
 * one toggle away, because a screen that leads with them is a proposal annex
 * rather than the application.
 */
@Component({
  selector: 'app-nawa-itsd-catalog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DecimalPipe,
    NgTemplateOutlet,
    FormsModule,
    RouterLink,
    GlyphComponent,
    NawaThemeToggleComponent,
  ],
  styleUrls: ['./nawa-theme.scss', './nawa-itsd-catalog.component.scss'],
  host: { '[attr.data-theme]': 'theme()' },
  template: `
    <header class="nawa-header">
      <img class="nawa-logo" [src]="logo()" alt="NAWA" />
      <div class="nawa-header-copy">
        <h1 class="nawa-title">{{ appName }} · IT Service Desk</h1>
        <span class="nawa-subtitle">{{ subtitle }} — service catalogue</span>
      </div>
      <div class="nawa-header-spacer"></div>
      <app-nawa-theme-toggle />
      @if (platform()) {
        <a class="nawa-link" routerLink="/systems">
          <ck-glyph name="cube" [size]="12" />
          Builder view
        </a>
      }
    </header>

    <div class="nawa-body">
      <div class="catalog-controls">
        <label class="catalog-search">
          <ck-glyph name="focus" [size]="13" />
          <input
            type="search"
            [ngModel]="query()"
            (ngModelChange)="query.set($event)"
            placeholder="Search a service…"
            aria-label="Search the service catalogue"
          />
        </label>
        <div class="catalog-filters" role="group" aria-label="Filter the catalogue">
          @for (option of filters; track option.key) {
            <button
              type="button"
              class="catalog-filter"
              [class.catalog-filter-on]="filter() === option.key"
              (click)="filter.set(option.key)"
            >
              {{ option.label }}
            </button>
          }
        </div>
        <div class="catalog-controls-spacer"></div>
        <button
          type="button"
          class="catalog-switch"
          [class.catalog-switch-on]="businessCase()"
          [attr.aria-pressed]="businessCase()"
          (click)="businessCase.set(!businessCase())"
        >
          <span class="catalog-switch-track"><span class="catalog-switch-knob"></span></span>
          Business case
        </button>
      </div>

      @if (businessCase()) {
        <div class="nawa-card business-strip">
          <div class="business-metrics">
            <div class="nawa-metric">
              <span class="nawa-metric-value">{{ totals().services }}</span>
              <span class="nawa-metric-label">Services listed</span>
            </div>
            <div class="nawa-metric">
              <span class="nawa-metric-value">{{ totals().available }}</span>
              <span class="nawa-metric-label">Available today</span>
            </div>
            <div class="nawa-metric">
              <span class="nawa-metric-value">{{ totals().agents }}</span>
              <span class="nawa-metric-label">Agents planned</span>
            </div>
            <div class="nawa-metric">
              <span class="nawa-metric-value">{{ totals().monthlyVolume | number }}</span>
              <span class="nawa-metric-label">Requests / month</span>
            </div>
          </div>
          <p class="nawa-note">
            Volumes, staffing and speed-ups taken from the IT automation workbook provided by Nawa.
            Totals cover the services listed below.
          </p>
        </div>

        <div class="nawa-card catalog-table-card">
          <table class="catalog-table">
            <thead>
              <tr>
                <th class="col-sr">#</th>
                <th>Service</th>
                <th class="col-num">Agents</th>
                <th class="col-num">Requests / month</th>
                <th class="col-speedup">Target speed-up</th>
                <th class="col-action"></th>
              </tr>
            </thead>
            <tbody>
              @for (row of visible(); track row.item.sr) {
                <tr
                  class="catalog-row"
                  [class.catalog-row-live]="row.item.status === 'live'"
                  [class.catalog-row-open]="expanded() === row.item.sr"
                  (click)="toggle(row.item.sr)"
                >
                  <td class="col-sr">{{ row.item.sr }}</td>
                  <td>
                    <div class="catalog-name">
                      <span class="catalog-name-text">{{ row.item.name }}</span>
                      <span
                        class="service-state"
                        [class.service-state-on]="row.item.status === 'live'"
                      >
                        {{ row.availability }}
                      </span>
                      @if (row.item.pattern_group) {
                        <span class="service-family" [title]="row.item.pattern_group">
                          <ck-glyph name="layers" [size]="11" />
                          <span class="service-family-text">{{ row.item.pattern_group }}</span>
                        </span>
                      }
                    </div>
                  </td>
                  <td class="col-num">{{ row.item.agents ?? '—' }}</td>
                  <td class="col-num">{{ row.item.monthly_volume ?? '—' }}</td>
                  <td class="col-speedup" [class.catalog-speedup]="row.fast">
                    {{ row.speedup }}
                  </td>
                  <td class="col-action">
                    @if (row.item.route) {
                      <a
                        class="nawa-link"
                        [routerLink]="row.item.route"
                        (click)="$event.stopPropagation()"
                      >
                        Open
                        <ck-glyph name="arrow-right" [size]="12" />
                      </a>
                    } @else {
                      <ck-glyph
                        class="catalog-chevron"
                        [name]="expanded() === row.item.sr ? 'arrow-down' : 'arrow-right'"
                        [size]="12"
                      />
                    }
                  </td>
                </tr>
                @if (expanded() === row.item.sr) {
                  <tr class="catalog-detail-row">
                    <td colspan="6">
                      <ng-container
                        *ngTemplateOutlet="detail; context: { $implicit: row.item }"
                      ></ng-container>
                    </td>
                  </tr>
                }
              } @empty {
                <tr>
                  <td colspan="6" class="catalog-empty">No service matches this search.</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else {
        <div class="service-grid">
          @for (row of visible(); track row.item.sr) {
            <article
              class="nawa-card service-card"
              [class.service-card-open]="expanded() === row.item.sr"
            >
              <button
                type="button"
                class="service-head"
                [attr.aria-expanded]="expanded() === row.item.sr"
                (click)="toggle(row.item.sr)"
              >
                <span class="service-name">{{ row.item.name }}</span>
                <span class="service-state" [class.service-state-on]="row.item.status === 'live'">
                  @if (row.item.status === 'live') {
                    <ck-glyph name="check" [size]="11" />
                  }
                  {{ row.availability }}
                </span>
              </button>
              @if (row.summary) {
                <p class="service-summary">{{ row.summary }}</p>
              }
              <div class="service-foot">
                @if (row.item.pattern_group) {
                  <span class="service-family" [title]="row.item.pattern_group">
                    <ck-glyph name="layers" [size]="11" />
                    <span class="service-family-text">{{ row.item.pattern_group }}</span>
                  </span>
                }
                @if (row.item.route) {
                  <a class="nawa-link service-open" [routerLink]="row.item.route">
                    Open
                    <ck-glyph name="arrow-right" [size]="12" />
                  </a>
                }
              </div>
              @if (expanded() === row.item.sr) {
                <ng-container
                  *ngTemplateOutlet="detail; context: { $implicit: row.item }"
                ></ng-container>
              }
            </article>
          } @empty {
            <p class="catalog-empty">No service matches this search.</p>
          }
        </div>
      }
    </div>

    <ng-template #detail let-item>
      <div class="catalog-detail">
        <section>
          <h3>Manual process — today</h3>
          @if (manualLines(item).length) {
            <ul>
              @for (line of manualLines(item); track $index) {
                <li>{{ line }}</li>
              }
            </ul>
          } @else {
            <p class="nawa-note">Not documented in the source file.</p>
          }
        </section>
        <section>
          <h3>Automation target</h3>
          @if (automatedLines(item).length) {
            <ul>
              @for (line of automatedLines(item); track $index) {
                <li>{{ line }}</li>
              }
            </ul>
          } @else {
            <p class="nawa-note">Not documented in the source file.</p>
          }
          @if (businessCase() && staffing(item).length) {
            <div class="catalog-staffing">
              @for (line of staffing(item); track $index) {
                <span class="nawa-badge">{{ line }}</span>
              }
            </div>
          }
          @if (item.pattern_group) {
            <p class="catalog-pattern-note">
              {{ item.pattern_group }} — {{ familySize(item.pattern_group) }} services of this
              catalogue follow the same pattern.
            </p>
          }
        </section>
      </div>
    </ng-template>
  `,
})
export class NawaItsdCatalogComponent {
  private readonly service = inject(NawaItsdService);
  private readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);

  protected readonly appName = NAWA_APP_NAME;
  protected readonly subtitle = NAWA_APP_SUBTITLE;

  /** Mirrored on the host so the `--nawa-*` palette follows the global theme. */
  protected readonly theme = inject(ThemeService).businessResolved;
  protected readonly logo = computed(() => NAWA_LOGO[this.theme()]);

  /** The pivot into the platform belongs to whoever administers the workspace. */
  protected readonly platform = computed(() =>
    this.workspace.isAdmin() || this.route.snapshot.queryParamMap.get('platform') === '1',
  );

  protected readonly filters: { key: CatalogFilter; label: string }[] = [
    { key: 'all', label: 'All services' },
    { key: 'available', label: 'Available' },
    { key: 'family', label: 'Same service family' },
  ];

  protected readonly query = signal('');
  protected readonly filter = signal<CatalogFilter>('all');
  protected readonly expanded = signal<number | null>(null);

  /** In memory only: the reading is a conversation, not a saved preference. */
  protected readonly businessCase = signal(false);

  private readonly catalog = toSignal(this.service.catalog(), { initialValue: null });

  protected readonly visible = computed<CatalogRow[]>(() => {
    const needle = this.query().trim().toLowerCase();
    const mode = this.filter();
    return this.useCases()
      .filter((item) => {
        if (mode === 'available' && item.status !== 'live') return false;
        if (mode === 'family' && !item.pattern_group) return false;
        return matchesQuery(item, needle);
      })
      .map((item) => ({
        item,
        summary: serviceSummary(item),
        availability: NAWA_AVAILABILITY[item.status],
        speedup: speedupLabel(item),
        fast: hasSpeedup(item),
      }));
  });

  protected readonly totals = computed(() => businessTotals(this.visible().map((row) => row.item)));

  protected toggle(sr: number): void {
    this.expanded.update((current) => (current === sr ? null : sr));
  }

  protected manualLines(item: NawaUseCase): string[] {
    return narrativeLines(item.manual_process);
  }

  protected automatedLines(item: NawaUseCase): string[] {
    return narrativeLines(item.automated_process);
  }

  protected staffing(item: NawaUseCase): string[] {
    return staffingLines(item.automated_process);
  }

  protected familySize(group: string): number {
    return this.useCases().filter((item) => item.pattern_group === group).length;
  }

  private useCases(): NawaUseCase[] {
    return this.catalog()?.use_cases ?? [];
  }
}
