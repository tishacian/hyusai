/**
 * `<ck-data-table>` — the one table every tabular surface renders through.
 *
 * Datasets, SQL/Polars test results, batch-score output and the training
 * feature picker all show the same thing: typed columns over a handful of
 * preview rows. Rendering that well once, here, is what makes the data plane
 * look like a data platform instead of an admin CRUD screen.
 *
 * What it does that a bare `<table>` does not:
 *
 * - **types every column** with a kind glyph, so a schema is readable at a
 *   glance (`42` integer vs `42.0` float vs `"42"` string);
 * - **aligns numbers** right in tabular figures, so digits line up vertically;
 * - **shows a column profile in the header**: a sparkline histogram for numeric
 *   columns, a top-value bar for categorical ones, both drawn from the stats
 *   the ingest worker already computed (no extra request, no client math);
 * - **renders nulls as an explicit muted marker** rather than an empty cell you
 *   cannot distinguish from an empty string.
 *
 * Everything is driven by the `TabularColumn` / `TabularColumnStats` contract
 * the backend emits, so a caller only ever passes `columns`, `rows` and
 * (optionally) `stats`.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import {
  COLUMN_KIND_GLYPH,
  isNumericKind,
  profileBars,
  type ProfileBar,
  type TabularColumn,
  type TabularColumnKind,
  type TabularColumnStats,
  type TabularRow,
} from './data-table.vm';

export type {
  ProfileBar,
  TabularColumn,
  TabularColumnKind,
  TabularColumnStats,
  TabularHistogramBin,
  TabularRow,
  TabularTopValue,
} from './data-table.vm';

/** One column, resolved with its profile and the bars to draw for it. */
interface RenderedColumn {
  name: string;
  kind: TabularColumnKind;
  dtype: string;
  glyph: string;
  numeric: boolean;
  stats: TabularColumnStats | null;
  bars: ProfileBar[];
  summary: string;
}

@Component({
  selector: 'ck-data-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="ck-dt">
      @if (caption()) {
        <div class="ck-dt__caption">
          <span class="ck-dt__count ck-mono">{{ caption() }}</span>
          <ng-content select="[caption-actions]" />
        </div>
      }
      <div class="ck-dt__scroll" [style.maxHeight]="maxHeight()">
        <table class="ck-dt__table">
          <thead>
            <tr>
              @if (showRowNumbers()) {
                <th class="ck-dt__th ck-dt__th--gutter"></th>
              }
              @for (col of rendered(); track col.name) {
                <th class="ck-dt__th" [class.ck-dt__th--num]="col.numeric">
                  <div class="ck-dt__head">
                    <span class="ck-dt__kind ck-mono" [title]="col.dtype">{{
                      col.glyph
                    }}</span>
                    <span class="ck-dt__name" [title]="col.name">{{ col.name }}</span>
                  </div>
                  @if (showProfile() && col.bars.length) {
                    <div
                      class="ck-dt__spark"
                      [class.ck-dt__spark--cat]="!col.numeric"
                      [attr.aria-label]="col.summary"
                      [title]="col.summary"
                    >
                      @for (bar of col.bars; track $index) {
                        <span
                          class="ck-dt__bar"
                          [style.height.%]="bar.height"
                          [title]="bar.title"
                        ></span>
                      }
                    </div>
                  }
                  @if (showProfile() && col.summary) {
                    <div class="ck-dt__meta ck-mono">{{ col.summary }}</div>
                  }
                </th>
              }
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track $index) {
              <tr class="ck-dt__tr">
                @if (showRowNumbers()) {
                  <td class="ck-dt__td ck-dt__td--gutter ck-mono">{{ $index + 1 }}</td>
                }
                @for (col of rendered(); track col.name) {
                  <td
                    class="ck-dt__td"
                    [class.ck-dt__td--num]="col.numeric"
                    [class.ck-dt__td--null]="isNull(row[col.name])"
                  >
                    @if (isNull(row[col.name])) {
                      <span class="ck-dt__null">{{ i18n.t('data.table.null') }}</span>
                    } @else {
                      {{ format(row[col.name]) }}
                    }
                  </td>
                }
              </tr>
            }
            @if (!rows().length) {
              <tr>
                <td
                  class="ck-dt__td ck-dt__empty"
                  [attr.colspan]="rendered().length + (showRowNumbers() ? 1 : 0)"
                >
                  {{ emptyLabel() || i18n.t('data.table.empty') }}
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </div>
  `,
  styles: [
    `
      .ck-dt {
        border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
        border-radius: 8px;
        overflow: hidden;
        background: var(--ck-bg-panel, rgba(255, 255, 255, 0.015));
      }
      .ck-dt__caption {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 8px 12px;
        border-bottom: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
      }
      .ck-dt__count {
        font-size: 10.5px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--ck-fg-4, #8891a0);
      }
      .ck-dt__scroll {
        overflow: auto;
      }
      .ck-dt__table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        font-size: 12px;
      }
      .ck-dt__th {
        position: sticky;
        top: 0;
        z-index: 2;
        text-align: left;
        vertical-align: bottom;
        padding: 7px 10px 6px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
        border-bottom: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
        white-space: nowrap;
      }
      .ck-dt__th--num {
        text-align: right;
      }
      .ck-dt__th--gutter,
      .ck-dt__td--gutter {
        width: 34px;
        text-align: right;
        color: var(--ck-fg-4, #8891a0);
        font-size: 10px;
      }
      .ck-dt__head {
        display: flex;
        align-items: center;
        gap: 5px;
        justify-content: inherit;
      }
      .ck-dt__th--num .ck-dt__head {
        justify-content: flex-end;
      }
      .ck-dt__kind {
        font-size: 9px;
        line-height: 1;
        padding: 2px 3px;
        border-radius: 3px;
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
      }
      .ck-dt__name {
        font-weight: 600;
        color: var(--ck-fg-1, #e6e9ef);
        max-width: 190px;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      /* The column profile: a 22px sparkline is enough to read a distribution
         without stealing the row space the data itself needs. */
      .ck-dt__spark {
        display: flex;
        align-items: flex-end;
        gap: 1px;
        height: 22px;
        margin-top: 5px;
      }
      .ck-dt__th--num .ck-dt__spark {
        justify-content: flex-end;
      }
      .ck-dt__bar {
        flex: 1 1 auto;
        min-width: 2px;
        max-width: 10px;
        background: linear-gradient(
          180deg,
          var(--ck-signal-cool, #7dd3fc) 0%,
          rgba(125, 211, 252, 0.35) 100%
        );
        border-radius: 1px 1px 0 0;
      }
      .ck-dt__spark--cat .ck-dt__bar {
        background: linear-gradient(
          180deg,
          var(--ck-signal-violet, #a78bfa) 0%,
          rgba(167, 139, 250, 0.3) 100%
        );
      }
      .ck-dt__meta {
        margin-top: 4px;
        font-size: 9.5px;
        font-weight: 400;
        color: var(--ck-fg-4, #8891a0);
        text-transform: none;
        letter-spacing: 0;
      }
      .ck-dt__tr:nth-child(even) {
        background: rgba(255, 255, 255, 0.012);
      }
      .ck-dt__tr:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.04));
      }
      .ck-dt__td {
        padding: 5px 10px;
        border-bottom: 1px solid var(--ck-stroke-1, rgba(255, 255, 255, 0.03));
        color: var(--ck-fg-2, #c3c9d4);
        max-width: 320px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      /* Digits must line up vertically or a column of numbers reads as noise. */
      .ck-dt__td--num {
        text-align: right;
        font-variant-numeric: tabular-nums;
        font-family: var(--ck-font-mono, ui-monospace, monospace);
      }
      .ck-dt__null {
        font-style: italic;
        color: var(--ck-fg-4, #8891a0);
        opacity: 0.7;
      }
      .ck-dt__empty {
        text-align: center;
        padding: 22px 10px;
        color: var(--ck-fg-4, #8891a0);
      }
    `,
  ],
})
export class DataTableComponent {
  protected readonly i18n = inject(I18nService);

  readonly columns = input<TabularColumn[]>([]);
  readonly rows = input<TabularRow[]>([]);
  readonly stats = input<Record<string, TabularColumnStats> | null>(null);
  readonly caption = input<string>('');
  readonly emptyLabel = input<string>('');
  readonly showProfile = input<boolean>(true);
  readonly showRowNumbers = input<boolean>(true);
  readonly maxHeight = input<string>('460px');

  /**
   * Columns resolved with their profile. Bar heights are normalized against the
   * tallest bucket so a sparkline stays readable whatever the absolute counts.
   */
  protected readonly rendered = computed<RenderedColumn[]>(() => {
    const stats = this.stats() ?? {};
    return this.columns().map((column) => {
      const kind = column.kind ?? 'other';
      const profile = stats[column.name] ?? null;
      const numeric = isNumericKind(kind);
      return {
        name: column.name,
        kind,
        dtype: column.dtype || kind,
        glyph: COLUMN_KIND_GLYPH[kind] ?? COLUMN_KIND_GLYPH.other,
        numeric,
        stats: profile,
        bars: profileBars(profile, numeric, this.i18n.t('data.table.null')),
        summary: this.summaryFor(profile, numeric),
      };
    });
  });

  protected isNull(value: unknown): boolean {
    return value === null || value === undefined;
  }

  protected format(value: unknown): string {
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) return '—';
      if (Number.isInteger(value)) return value.toLocaleString(this.i18n.locale());
      return value.toLocaleString(this.i18n.locale(), {
        maximumFractionDigits: 4,
      });
    }
    if (typeof value === 'boolean') {
      return value ? 'true' : 'false';
    }
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  private summaryFor(stats: TabularColumnStats | null, numeric: boolean): string {
    if (!stats) return '';
    const parts: string[] = [];
    if (numeric && stats.min !== null && stats.min !== undefined) {
      parts.push(`${this.compact(stats.min)} → ${this.compact(stats.max)}`);
    } else if (typeof stats.distinct === 'number' && stats.distinct > 0) {
      parts.push(this.i18n.t('data.table.distinct', { count: stats.distinct }));
    }
    if (stats.nulls) {
      parts.push(this.i18n.t('data.table.nulls', { count: stats.nulls }));
    }
    return parts.join(' · ');
  }

  private compact(value: number | string | null | undefined): string {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'number') {
      return Math.abs(value) >= 10_000
        ? value.toLocaleString(this.i18n.locale(), { notation: 'compact' })
        : this.format(value);
    }
    return String(value);
  }
}
