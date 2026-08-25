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
 * - **opens that profile on click**: nulls, distincts, range, mean and standard
 *   deviation as figures, plus the ranked top values — the numbers behind the
 *   sparkline, for the reader who wants to read rather than eyeball;
 * - **renders nulls as an explicit muted marker** rather than an empty cell you
 *   cannot distinguish from an empty string.
 *
 * Everything is driven by the `TabularColumn` / `TabularColumnStats` contract
 * the backend emits, so a caller only ever passes `columns`, `rows` and
 * (optionally) `stats`.
 */
import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  ElementRef,
  inject,
  input,
  signal,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import {
  COLUMN_KIND_GLYPH,
  isNumericKind,
  profileBars,
  profileFacts,
  topValueBars,
  type ProfileBar,
  type ProfileFact,
  type TabularColumn,
  type TabularColumnKind,
  type TabularColumnStats,
  type TabularRow,
  type TopValueBar,
} from './data-table.vm';

export type {
  ProfileBar,
  ProfileFact,
  TabularColumn,
  TabularColumnKind,
  TabularColumnStats,
  TabularHistogramBin,
  TabularRow,
  TabularTopValue,
  TopValueBar,
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
  facts: ProfileFact[];
  topValues: TopValueBar[];
  alignEnd: boolean;
}

@Component({
  selector: 'ck-data-table',
  standalone: true,
  imports: [NgTemplateOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(document:click)': 'onDocumentClick($event)',
    '(document:keydown.escape)': 'closeProfile()',
  },
  template: `
    <ng-template #head let-col="col">
      <span class="ck-dt__head">
        <span class="ck-dt__kind ck-mono" [title]="col.dtype">{{ col.glyph }}</span>
        <span class="ck-dt__name" [title]="col.name">{{ col.name }}</span>
      </span>
      @if (showProfile() && col.bars.length) {
        <span
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
        </span>
      }
      @if (showProfile() && col.summary) {
        <span class="ck-dt__meta ck-mono">{{ col.summary }}</span>
      }
    </ng-template>

    <div class="ck-dt">
      @if (caption()) {
        <div class="ck-dt__caption">
          <span class="ck-dt__count ck-mono">{{ caption() }}</span>
          <ng-content select="[caption-actions]" />
        </div>
      }
      <div
        class="ck-dt__scroll"
        [class.ck-dt__scroll--probing]="probing()"
        [style.maxHeight]="maxHeight()"
      >
        <table class="ck-dt__table">
          <thead>
            <tr>
              @if (showRowNumbers()) {
                <th class="ck-dt__th ck-dt__th--gutter"></th>
              }
              @for (col of rendered(); track col.name) {
                <th class="ck-dt__th" [class.ck-dt__th--num]="col.numeric">
                  @if (openable(col)) {
                    <button
                      type="button"
                      class="ck-dt__probe"
                      data-testid="column-profile-toggle"
                      [attr.aria-expanded]="open() === col.name"
                      [attr.aria-label]="
                        i18n.t('data.table.profile.open', { column: col.name })
                      "
                      (click)="toggle(col.name)"
                    >
                      <ng-container [ngTemplateOutlet]="head" [ngTemplateOutletContext]="{ col }" />
                    </button>
                  } @else {
                    <ng-container [ngTemplateOutlet]="head" [ngTemplateOutletContext]="{ col }" />
                  }
                  @if (open() === col.name) {
                    <div
                      class="ck-dt__pop"
                      [class.ck-dt__pop--end]="col.alignEnd"
                      data-testid="column-profile"
                      role="dialog"
                      [attr.aria-label]="
                        i18n.t('data.table.profile.title', { column: col.name })
                      "
                    >
                      <div class="ck-dt__pop-head">
                        <span class="ck-dt__pop-name ck-mono">{{ col.name }}</span>
                        <span class="ck-dt__pop-type ck-mono">{{ col.dtype }}</span>
                      </div>
                      <dl class="ck-dt__facts">
                        @for (fact of col.facts; track fact.key) {
                          <div class="ck-dt__fact">
                            <dt>{{ i18n.t('data.table.profile.' + fact.key) }}</dt>
                            <dd class="ck-mono">
                              {{ format(fact.value) }}
                              @if (fact.key === 'nulls' && fact.ratio) {
                                <span class="ck-dt__fact-share">{{ share(fact.ratio) }}</span>
                              }
                            </dd>
                          </div>
                        }
                      </dl>
                      @if (col.topValues.length) {
                        <div class="ck-dt__pop-label">
                          {{ i18n.t('data.table.profile.top') }}
                        </div>
                        <div class="ck-dt__tops">
                          @for (top of col.topValues; track $index) {
                            <div class="ck-dt__top">
                              <span class="ck-dt__top-label" [title]="top.label">{{
                                top.label
                              }}</span>
                              <span class="ck-dt__top-track">
                                <span
                                  class="ck-dt__top-fill"
                                  [style.width.%]="top.width"
                                ></span>
                              </span>
                              <span class="ck-dt__top-count ck-mono">{{
                                format(top.count)
                              }}</span>
                            </div>
                          }
                        </div>
                      }
                    </div>
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
      /* A preview of three rows is shorter than an open profile, and the scroll
         box would clip it. Reserving the height only while one is open keeps a
         short table short the rest of the time. */
      .ck-dt__scroll--probing {
        min-height: 268px;
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
      /* The whole header stack is the affordance, so the sparkline is part of
         the target rather than decoration sitting next to a small caret. */
      .ck-dt__probe {
        display: block;
        width: 100%;
        padding: 0;
        border: 0;
        background: none;
        text-align: inherit;
        font: inherit;
        color: inherit;
        cursor: pointer;
        border-radius: 4px;
      }
      .ck-dt__probe:hover .ck-dt__name {
        color: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-dt__probe:focus-visible {
        outline: 1px solid var(--ck-signal-cool, #7dd3fc);
        outline-offset: 2px;
      }
      .ck-dt__probe[aria-expanded='true'] .ck-dt__name {
        color: var(--ck-signal-cool, #7dd3fc);
      }
      /* Anchored to the header cell and lifted above the sticky row, so a
         profile opened on the first column is not clipped by the next one. */
      .ck-dt__pop {
        position: absolute;
        z-index: 5;
        top: calc(100% - 2px);
        left: 6px;
        min-width: 208px;
        max-width: 288px;
        padding: 9px 10px 10px;
        border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.1));
        border-radius: 8px;
        background: var(--ck-bg-elevated, #14161c);
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
        white-space: normal;
        cursor: default;
      }
      /* Columns near the right edge open inward, or the panel would hang off
         the table and force a horizontal scroll to be read. */
      .ck-dt__pop--end {
        left: auto;
        right: 6px;
      }
      .ck-dt__pop-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        padding-bottom: 6px;
        margin-bottom: 6px;
        border-bottom: 1px solid var(--ck-stroke-1, rgba(255, 255, 255, 0.05));
      }
      .ck-dt__pop-name {
        font-size: 11px;
        font-weight: 600;
        color: var(--ck-fg-1, #e6e9ef);
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .ck-dt__pop-type {
        font-size: 9px;
        color: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-dt__facts {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: 3px 10px;
        margin: 0;
        font-weight: 400;
      }
      .ck-dt__fact {
        display: contents;
      }
      .ck-dt__fact dt {
        font-size: 10px;
        color: var(--ck-fg-4, #8891a0);
        text-transform: none;
        letter-spacing: 0;
      }
      .ck-dt__fact dd {
        margin: 0;
        font-size: 10.5px;
        text-align: right;
        color: var(--ck-fg-2, #c3c9d4);
        font-variant-numeric: tabular-nums;
      }
      .ck-dt__fact-share {
        margin-left: 4px;
        color: var(--ck-fg-4, #8891a0);
      }
      .ck-dt__pop-label {
        margin: 9px 0 5px;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--ck-fg-4, #8891a0);
      }
      .ck-dt__tops {
        display: flex;
        flex-direction: column;
        gap: 3px;
      }
      .ck-dt__top {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 52px auto;
        align-items: center;
        gap: 6px;
      }
      .ck-dt__top-label {
        font-size: 10px;
        font-weight: 400;
        color: var(--ck-fg-2, #c3c9d4);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .ck-dt__top-track {
        height: 5px;
        border-radius: 3px;
        background: var(--ck-stroke-1, rgba(255, 255, 255, 0.06));
        overflow: hidden;
      }
      .ck-dt__top-fill {
        display: block;
        height: 100%;
        border-radius: 3px;
        background: var(--ck-signal-violet, #a78bfa);
      }
      .ck-dt__top-count {
        font-size: 9.5px;
        font-weight: 400;
        color: var(--ck-fg-4, #8891a0);
        font-variant-numeric: tabular-nums;
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
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly columns = input<TabularColumn[]>([]);
  readonly rows = input<TabularRow[]>([]);
  readonly stats = input<Record<string, TabularColumnStats> | null>(null);
  readonly caption = input<string>('');
  readonly emptyLabel = input<string>('');
  readonly showProfile = input<boolean>(true);
  readonly showRowNumbers = input<boolean>(true);
  readonly maxHeight = input<string>('460px');
  /** Row count of the whole dataset, stated in the profile beside the nulls. */
  readonly rowCount = input<number | null>(null);

  /** Name of the column whose profile is open, or `null` when none is. */
  protected readonly open = signal<string | null>(null);

  /**
   * Columns resolved with their profile. Bar heights are normalized against the
   * tallest bucket so a sparkline stays readable whatever the absolute counts.
   */
  protected readonly rendered = computed<RenderedColumn[]>(() => {
    const stats = this.stats() ?? {};
    const columns = this.columns();
    const nullLabel = this.i18n.t('data.table.null');
    return columns.map((column, index) => {
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
        bars: profileBars(profile, numeric, nullLabel),
        summary: this.summaryFor(profile, numeric),
        facts: profileFacts(profile, numeric, this.rowCount()),
        topValues: topValueBars(profile, nullLabel),
        alignEnd: index > 0 && index >= columns.length - 2,
      };
    });
  });

  /** Whether a profile is actually on screen — a stale name is not one. */
  protected readonly probing = computed(() =>
    this.rendered().some((column) => column.name === this.open()),
  );

  /** A header is a button only when there is a profile behind it to open. */
  protected openable(column: RenderedColumn): boolean {
    return this.showProfile() && column.facts.length > 0;
  }

  protected toggle(name: string): void {
    this.open.update((current) => (current === name ? null : name));
  }

  protected closeProfile(): void {
    this.open.set(null);
  }

  protected onDocumentClick(event: Event): void {
    if (this.open() === null) return;
    const target = event.target;
    if (target instanceof Node && this.host.nativeElement.contains(target)) return;
    this.closeProfile();
  }

  protected share(ratio: number): string {
    return `${(ratio * 100).toLocaleString(this.i18n.locale(), {
      maximumFractionDigits: ratio < 0.01 ? 2 : 1,
    })} %`;
  }

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
