import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { GlyphComponent } from '@app/shared/cockpit';
import {
  NAWA_ASSISTANT,
  NAWA_ASSISTANT_SUBTITLE,
  type NawaUseCase,
} from './nawa-itsd.model';
import { NawaItsdService } from './nawa-itsd.service';

type CatalogFilter = 'all' | 'live' | 'planned' | 'pattern';

/**
 * `/nawa/itsd` — catalogue of the 39 IT automation use cases extracted from the
 * customer workbook. Static asset only, no backend call (SPEC §7.1).
 */
@Component({
  selector: 'app-nawa-itsd-catalog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, GlyphComponent],
  styleUrls: ['./nawa-theme.scss', './nawa-itsd-catalog.component.scss'],
  template: `
    <header class="nawa-header">
      <img class="nawa-logo" src="/assets/nawa/nawa-logo.png" alt="Nawa" />
      <div class="nawa-header-copy">
        <h1 class="nawa-title">{{ assistant }} · IT Service Desk</h1>
        <span class="nawa-subtitle">{{ subtitle }} — IT operations automation</span>
      </div>
      <div class="nawa-header-spacer"></div>
      <div class="nawa-header-meta">
        <div class="nawa-metric">
          <span class="nawa-metric-value">{{ total() }}</span>
          <span class="nawa-metric-label">Use cases</span>
        </div>
        <div class="nawa-metric">
          <span class="nawa-metric-value">{{ plannedAgents() }}</span>
          <span class="nawa-metric-label">Agents planned</span>
        </div>
        <div class="nawa-metric">
          <span class="nawa-metric-value">{{ patternCount() }}</span>
          <span class="nawa-metric-label">Same pattern</span>
        </div>
      </div>
    </header>

    <div class="nawa-body">
      <div class="catalog-controls">
        <label class="catalog-search">
          <ck-glyph name="focus" [size]="13" />
          <input
            type="search"
            [ngModel]="query()"
            (ngModelChange)="query.set($event)"
            placeholder="Search a use case or a process…"
            aria-label="Search use cases"
          />
        </label>
        <div class="catalog-filters" role="group" aria-label="Filter by status">
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
      </div>

      <div class="nawa-card catalog-table-card">
        <table class="catalog-table">
          <thead>
            <tr>
              <th class="col-sr">#</th>
              <th>Automation</th>
              <th class="col-num">Agents</th>
              <th class="col-num">Volume / month</th>
              <th class="col-speedup">Target speed-up</th>
              <th class="col-action"></th>
            </tr>
          </thead>
          <tbody>
            @for (item of visible(); track item.sr) {
              <tr
                class="catalog-row"
                [class.catalog-row-live]="item.status === 'live'"
                [class.catalog-row-open]="expanded() === item.sr"
                (click)="toggle(item.sr)"
              >
                <td class="col-sr">{{ item.sr }}</td>
                <td>
                  <div class="catalog-name">
                    <span class="catalog-name-text">{{ item.name }}</span>
                    @if (item.status === 'live') {
                      <span class="nawa-badge nawa-badge-live">Live</span>
                    } @else {
                      <span class="nawa-badge">Planned</span>
                    }
                    @if (item.pattern_group) {
                      <span class="nawa-badge nawa-badge-pattern" [title]="item.pattern_group">
                        Same pattern
                      </span>
                    }
                  </div>
                </td>
                <td class="col-num">{{ item.agents ?? '—' }}</td>
                <td class="col-num">{{ item.monthly_volume ?? '—' }}</td>
                <td class="col-speedup" [class.catalog-speedup]="isSpeedup(item)">
                  {{ speedup(item) }}
                </td>
                <td class="col-action">
                  @if (item.route) {
                    <a
                      class="nawa-link"
                      [routerLink]="item.route"
                      (click)="$event.stopPropagation()"
                    >
                      Open
                      <ck-glyph name="arrow-right" [size]="12" />
                    </a>
                  } @else {
                    <ck-glyph
                      class="catalog-chevron"
                      [name]="expanded() === item.sr ? 'arrow-down' : 'arrow-right'"
                      [size]="12"
                    />
                  }
                </td>
              </tr>
              @if (expanded() === item.sr) {
                <tr class="catalog-detail-row">
                  <td colspan="6">
                    <div class="catalog-detail">
                      <section>
                        <h3>Manual process — today</h3>
                        @if (item.manual_process) {
                          <ul>
                            @for (line of lines(item.manual_process); track $index) {
                              <li>{{ line }}</li>
                            }
                          </ul>
                        } @else {
                          <p class="nawa-note">Not documented in the source file.</p>
                        }
                      </section>
                      <section>
                        <h3>Automation target</h3>
                        @if (item.automated_process) {
                          <ul>
                            @for (line of lines(item.automated_process); track $index) {
                              <li>{{ line }}</li>
                            }
                          </ul>
                        } @else {
                          <p class="nawa-note">Not documented in the source file.</p>
                        }
                        @if (item.pattern_group) {
                          <p class="catalog-pattern-note">
                            {{ item.pattern_group }} — {{ item.agents }} agents planned for one
                            variant of a pattern shared by
                            {{ patternCount() }} use cases.
                          </p>
                        }
                      </section>
                    </div>
                  </td>
                </tr>
              }
            } @empty {
              <tr>
                <td colspan="6" class="catalog-empty">No use case matches this filter.</td>
              </tr>
            }
          </tbody>
        </table>
      </div>

      <p class="nawa-note catalog-footnote">
        Volumes, staffing and speed-ups taken from the IT automation workbook provided by Nawa.
      </p>
    </div>
  `,
})
export class NawaItsdCatalogComponent {
  private readonly service = inject(NawaItsdService);

  protected readonly assistant = NAWA_ASSISTANT;
  protected readonly subtitle = NAWA_ASSISTANT_SUBTITLE;

  protected readonly filters: { key: CatalogFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'live', label: 'Live' },
    { key: 'planned', label: 'Planned' },
    { key: 'pattern', label: 'Same pattern' },
  ];

  protected readonly query = signal('');
  protected readonly filter = signal<CatalogFilter>('all');
  protected readonly expanded = signal<number | null>(null);

  private readonly catalog = toSignal(this.service.catalog(), { initialValue: null });

  protected readonly total = computed(() => this.catalog()?.use_cases.length ?? 0);
  protected readonly plannedAgents = computed(() => this.catalog()?.meta.planned_agent_total ?? 0);
  protected readonly patternCount = computed(
    () => this.useCases().filter((item) => item.pattern_group).length,
  );

  protected readonly visible = computed(() => {
    const needle = this.query().trim().toLowerCase();
    const mode = this.filter();
    return this.useCases().filter((item) => {
      if (mode === 'live' && item.status !== 'live') return false;
      if (mode === 'planned' && item.status !== 'planned') return false;
      if (mode === 'pattern' && !item.pattern_group) return false;
      if (!needle) return true;
      return `${item.sr} ${item.name} ${item.manual_process} ${item.automated_process}`
        .toLowerCase()
        .includes(needle);
    });
  });

  protected toggle(sr: number): void {
    this.expanded.update((current) => (current === sr ? null : sr));
  }

  protected lines(value: string): string[] {
    return value.split('\n').filter((line) => line.trim().length > 0);
  }

  /**
   * Acceleration targeted by the customer's own plan, derived from its two time
   * columns. No absolute duration is shown: the workbook annotates the target
   * column with "Time in hours" while the legacy column is declared in minutes,
   * so printing either unit would be a claim we cannot back.
   *
   * A ratio only survives that ambiguity if it refuses to speak when the two
   * numbers do not support a claim. Anything at or below parity renders as
   * parity or a dash instead of a multiplier, so if the columns turned out to
   * carry different units every row would degrade to that rather than show a
   * confident wrong figure.
   */
  protected speedup(item: NawaUseCase): string {
    const ratio = this.ratio(item);
    if (ratio === null || ratio < 0.95) return '—';
    if (ratio < 1.05) return 'at parity';
    // One outlier compares a multi-week calendar delay to a handling time.
    // Beyond two orders of magnitude the figure stops informing anyone.
    if (ratio >= 100) return '> 100× faster';
    const value = ratio < 10 ? ratio.toFixed(1).replace(/\.0$/, '') : String(Math.round(ratio));
    return `~${value}× faster`;
  }

  protected isSpeedup(item: NawaUseCase): boolean {
    const ratio = this.ratio(item);
    return ratio !== null && ratio >= 1.05;
  }

  private ratio(item: NawaUseCase): number | null {
    const legacy = item.legacy_minutes;
    const target = item.automated_minutes;
    if (typeof legacy !== 'number' || typeof target !== 'number') return null;
    if (legacy <= 0 || target <= 0) return null;
    return legacy / target;
  }

  private useCases(): NawaUseCase[] {
    return this.catalog()?.use_cases ?? [];
  }
}
