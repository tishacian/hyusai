/**
 * Dataset detail — preview, column profile, lineage and versions.
 *
 * The whole page is served by one request: the ingest worker already folded the
 * schema, the preview rows and the per-column profile into the row, so there is
 * nothing to compute client-side and nothing to fetch per tab.
 *
 * The profile tab is the "this is a data platform" moment: every column shows
 * its distribution, its nulls and its frequent values, the same numbers the
 * table header sparklines are drawn from.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabComponent, CkTabsComponent } from '@app/shared/cockpit/tabs.component';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import {
  formatBytes,
  isNumericKind,
  nullPercent,
  profileBars,
  type TabularColumn,
  type TabularColumnStats,
  type TabularRow,
} from '@app/shared/ui/data-table.vm';
import { I18nService } from '@app/core/i18n.service';
import {
  DataService,
  isDatasetActive,
  type DatasetDetailDto,
  type DatasetDto,
} from './data.service';
import { ingestStepKey, scoredByLabel, scoredColumns } from './data.vm';

const POLL_INTERVAL_MS = 1500;
/** Rows per window past the cached preview — the same size the cache holds. */
const PAGE_SIZE = 50;

@Component({
  selector: 'app-data-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    IconComponent,
    EmptyStateComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    DataTableComponent,
  ],
  template: `
    <a
      routerLink="/data"
      class="inline-flex items-center gap-1.5 text-[11px] ck-mono mb-3 transition"
      style="color: var(--ck-fg-4)"
    >
      <app-icon name="chevron-left" [size]="13" /> {{ i18n.t('data.detail.back') }}
    </a>

    @if (dataset(); as ds) {
      <ck-object-header
        [eyebrow]="i18n.t('data.source.' + ds.source)"
        [title]="ds.name"
        [subtitle]="ds.description || subtitleFor(ds)"
        [kpis]="kpis()"
      >
        <div actions class="flex items-center gap-1.5">
          @if (ds.status === 'failed') {
            <button
              type="button"
              class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
              (click)="retry()"
            >
              <app-icon name="refresh-cw" [size]="14" /> {{ i18n.t('data.detail.retry') }}
            </button>
          }
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
            (click)="remove()"
          >
            <app-icon name="trash-2" [size]="14" /> {{ i18n.t('data.detail.delete') }}
          </button>
        </div>
      </ck-object-header>

      @if (isActive(ds)) {
        <div class="ck-progress rounded-md px-4 py-3 mb-3">
          <div class="flex items-center gap-2 text-sm" style="color: var(--ck-fg-1)">
            <app-icon name="loader-2" [size]="14" class="animate-spin" />
            {{ i18n.t('data.progress.title') }}
          </div>
          <div class="text-[11px] ck-mono mt-1" style="color: var(--ck-signal-cool)">
            {{ i18n.t(stepKey(ds.status_detail, ds.source)) }}
          </div>
        </div>
      } @else if (ds.status === 'failed') {
        <div class="ck-error rounded-md px-4 py-3 mb-3">
          <div class="text-sm font-medium" style="color: var(--ck-signal-neg)">
            {{ i18n.t('data.detail.error.title') }}
          </div>
          <code class="text-[11px] block mt-1" style="color: var(--ck-fg-3)">{{ ds.error }}</code>
        </div>
      }

      <ck-tabs [active]="tab()" (activeChange)="tab.set($event)">
        <ck-tab id="preview" [label]="i18n.t('data.detail.tab.preview')">
          <ck-data-table
            [columns]="columns()"
            [rows]="previewRows()"
            [stats]="ds.stats ?? null"
            [rowCount]="ds.row_count ?? null"
            [caption]="previewCaption()"
          >
            <span caption-actions class="flex items-center gap-1.5">
              @if (paging()) {
                <app-icon name="loader-2" [size]="12" class="animate-spin" />
              }
              <button
                type="button"
                class="ck-page"
                data-testid="preview-prev"
                [disabled]="!canPrev() || paging()"
                [attr.aria-label]="i18n.t('data.detail.preview.prev')"
                [title]="i18n.t('data.detail.preview.prev')"
                (click)="page(-1)"
              >
                <app-icon name="chevron-left" [size]="13" />
              </button>
              <button
                type="button"
                class="ck-page"
                data-testid="preview-next"
                [disabled]="!canNext() || paging()"
                [attr.aria-label]="i18n.t('data.detail.preview.next')"
                [title]="i18n.t('data.detail.preview.next')"
                (click)="page(1)"
              >
                <app-icon name="chevron-right" [size]="13" />
              </button>
            </span>
          </ck-data-table>
        </ck-tab>

        <ck-tab id="schema" [label]="i18n.t('data.detail.tab.schema')">
          <div class="ck-surface rounded-md overflow-hidden">
            <table class="w-full text-sm ck-schema">
              <thead>
                <tr>
                  <th class="ck-schema__th">{{ i18n.t('data.schema.column') }}</th>
                  <th class="ck-schema__th">{{ i18n.t('data.schema.kind') }}</th>
                  <th class="ck-schema__th ck-schema__th--num">
                    {{ i18n.t('data.schema.nulls') }}
                  </th>
                  <th class="ck-schema__th ck-schema__th--num">
                    {{ i18n.t('data.schema.distinct') }}
                  </th>
                  <th class="ck-schema__th">{{ i18n.t('data.schema.profile') }}</th>
                </tr>
              </thead>
              <tbody>
                @for (col of profiled(); track col.name) {
                  <tr class="ck-schema__tr">
                    <td class="ck-schema__td ck-mono" style="color: var(--ck-fg-1)">
                      {{ col.name }}
                      @if (col.scored && scoredBy(); as model) {
                        <span
                          class="ck-scored"
                          data-testid="scored-column"
                          [title]="i18n.t('data.lineage.scored_by.hint', { model: model })"
                        >
                          <app-icon name="target" [size]="9" />
                          {{ i18n.t('data.lineage.scored_by', { model: model }) }}
                        </span>
                      }
                    </td>
                    <td class="ck-schema__td">
                      <span class="ck-kind">{{ i18n.t('data.kind.' + col.kind) }}</span>
                    </td>
                    <td class="ck-schema__td ck-schema__td--num">
                      {{ col.nulls }}
                      @if (col.nullRatio) {
                        <span style="color: var(--ck-fg-4)"> ({{ col.nullRatio }}%)</span>
                      }
                    </td>
                    <td class="ck-schema__td ck-schema__td--num">{{ col.distinct }}</td>
                    <td class="ck-schema__td">
                      @if (col.bars.length) {
                        <div class="ck-profile">
                          @for (bar of col.bars; track $index) {
                            <span
                              class="ck-profile__bar"
                              [class.ck-profile__bar--cat]="!col.numeric"
                              [style.height.%]="bar.height"
                              [title]="bar.title"
                            ></span>
                          }
                        </div>
                      }
                      <div class="text-[10.5px] ck-mono mt-0.5" style="color: var(--ck-fg-4)">
                        {{ col.summary }}
                      </div>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </ck-tab>

        <ck-tab id="lineage" [label]="i18n.t('data.detail.tab.lineage')">
          <div class="space-y-4">
            <div>
              <div class="ck-section-label">{{ i18n.t('data.lineage.parents') }}</div>
              @if (parents().length) {
                <div class="flex items-center gap-2 flex-wrap">
                  @for (parent of parents(); track parent.id) {
                    <a [routerLink]="['/data', parent.id]" class="ck-lineage-chip">
                      <app-icon name="table" [size]="12" />
                      {{ parent.name }}
                      <span class="ck-mono" style="color: var(--ck-fg-4)">
                        {{ i18n.t('data.versions.label', { version: parent.version }) }}
                      </span>
                    </a>
                  }
                </div>
              } @else {
                <div class="text-[11px] ck-mono" style="color: var(--ck-fg-4)">
                  {{ originLabel() }}
                </div>
              }
            </div>

            @if (dataset()?.produced_by) {
              <div class="text-[11px] ck-mono" style="color: var(--ck-fg-3)">
                {{ i18n.t('data.lineage.produced_by', { producer: dataset()!.produced_by! }) }}
              </div>
            }

            @if (scoredBy(); as model) {
              <div>
                <div class="ck-section-label">{{ i18n.t('data.lineage.model') }}</div>
                <div class="flex items-center gap-2 flex-wrap">
                  <a
                    class="ck-lineage-chip"
                    data-testid="scored-by-model"
                    [routerLink]="modelLink()"
                  >
                    <app-icon name="brain" [size]="12" />
                    {{ model }}
                  </a>
                  @if (addedColumns().length) {
                    <span class="text-[11px] ck-mono" style="color: var(--ck-fg-4)">
                      {{
                        i18n.t('data.lineage.added_columns', {
                          columns: addedColumns().join(', ')
                        })
                      }}
                    </span>
                  }
                </div>
              </div>
            }

            <div>
              <div class="ck-section-label">{{ i18n.t('data.lineage.children') }}</div>
              @if (children().length) {
                <div class="flex items-center gap-2 flex-wrap">
                  @for (child of children(); track child.id) {
                    <a [routerLink]="['/data', child.id]" class="ck-lineage-chip">
                      <app-icon [name]="child.source === 'score' ? 'target' : 'git-branch'" [size]="12" />
                      {{ child.name }}
                    </a>
                  }
                </div>
              } @else {
                <div class="text-[11px] ck-mono" style="color: var(--ck-fg-4)">
                  {{ i18n.t('data.lineage.none') }}
                </div>
              }
            </div>
          </div>
        </ck-tab>

        <ck-tab id="versions" [label]="i18n.t('data.detail.tab.versions')">
          <ul class="space-y-2">
            @for (version of versions(); track version.id) {
              <li>
                <a
                  [routerLink]="['/data', version.id]"
                  class="flex items-center gap-3 ck-surface rounded-md px-4 py-2.5 transition ck-row"
                >
                  <span class="ck-badge ck-mono">{{
                    i18n.t('data.versions.label', { version: version.version })
                  }}</span>
                  <span class="flex-1 text-[11px] ck-mono" style="color: var(--ck-fg-4)">
                    {{
                      i18n.t('data.list.meta', {
                        rows: (version.row_count ?? 0).toLocaleString(i18n.locale()),
                        columns: version.column_count ?? 0,
                        size: bytes(version.size_bytes)
                      })
                    }}
                  </span>
                  @if (version.id === dataset()?.id) {
                    <span class="ck-badge ck-badge--on ck-mono">{{
                      i18n.t('data.versions.current')
                    }}</span>
                  }
                </a>
              </li>
            }
          </ul>
        </ck-tab>
      </ck-tabs>
    } @else if (loading()) {
      <div class="ck-surface rounded-md p-6 animate-pulse">
        <div class="h-3 w-48 rounded" style="background: rgba(255,255,255,0.05)"></div>
      </div>
    } @else {
      <!-- Not "no datasets yet": there are datasets, this id is not one of
           them. Saying the list's empty copy here sends the reader looking for
           an import button to solve a bad link. -->
      <app-empty-state
        icon="table"
        [title]="i18n.t('data.detail.gone.title')"
        [description]="i18n.t('data.detail.gone.description')"
      >
        <a routerLink="/data" class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm">
          <app-icon name="chevron-left" [size]="13" /> {{ i18n.t('data.detail.back') }}
        </a>
      </app-empty-state>
    }
  `,
  styles: [
    `
      .ck-progress {
        border: 1px solid rgba(125, 211, 252, 0.25);
        background: rgba(125, 211, 252, 0.05);
      }
      .ck-error {
        border: 1px solid rgba(239, 90, 111, 0.25);
        background: rgba(239, 90, 111, 0.05);
      }
      .ck-schema {
        border-collapse: separate;
        border-spacing: 0;
      }
      .ck-schema__th {
        text-align: left;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-weight: 600;
        color: var(--ck-fg-4, #8891a0);
        padding: 8px 12px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
        border-bottom: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      }
      .ck-schema__th--num,
      .ck-schema__td--num {
        text-align: right;
        font-variant-numeric: tabular-nums;
      }
      .ck-schema__td {
        padding: 7px 12px;
        border-bottom: 1px solid var(--ck-stroke-1, rgba(255, 255, 255, 0.03));
        color: var(--ck-fg-2, #c3c9d4);
        font-size: 12px;
      }
      .ck-schema__tr:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
      }
      .ck-kind {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 2px 5px;
        border-radius: 3px;
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
      }
      .ck-profile {
        display: flex;
        align-items: flex-end;
        gap: 1px;
        height: 24px;
        width: 140px;
      }
      .ck-profile__bar {
        flex: 1 1 auto;
        min-width: 2px;
        border-radius: 1px 1px 0 0;
        background: linear-gradient(
          180deg,
          var(--ck-signal-cool, #7dd3fc) 0%,
          rgba(125, 211, 252, 0.3) 100%
        );
      }
      .ck-profile__bar--cat {
        background: linear-gradient(
          180deg,
          var(--ck-signal-violet, #a78bfa) 0%,
          rgba(167, 139, 250, 0.3) 100%
        );
      }
      .ck-section-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--ck-fg-4, #8891a0);
        margin-bottom: 7px;
      }
      .ck-lineage-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 11.5px;
        padding: 5px 9px;
        border-radius: 999px;
        color: var(--ck-fg-2, #c3c9d4);
        background: rgba(255, 255, 255, 0.03);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-lineage-chip:hover {
        color: var(--ck-fg-1, #e6e9ef);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.35);
      }
      .ck-row:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.04));
      }
      .ck-badge {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 2px 5px;
        border-radius: 3px;
        color: var(--ck-fg-4, #8891a0);
        background: rgba(255, 255, 255, 0.04);
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
      }
      .ck-badge--on {
        color: var(--ck-signal-pos, #34d399);
        background: rgba(52, 211, 153, 0.1);
      }
      /* Paging the preview: two quiet steppers in the caption bar, disabled at
         the ends rather than hidden, so the reader can see where they are. */
      .ck-page {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        height: 22px;
        border-radius: 4px;
        color: var(--ck-fg-3, #9aa4b2);
        background: var(--ck-bg-inset, rgba(255, 255, 255, 0.04));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-page:hover:not(:disabled) {
        color: var(--ck-signal-cool, #7dd3fc);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.35);
      }
      .ck-page:disabled {
        opacity: 0.35;
        cursor: default;
      }
      /* A column nobody uploaded says who wrote it, on its own row. */
      .ck-scored {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        margin-left: 6px;
        font-size: 9.5px;
        padding: 1.5px 5px;
        border-radius: 999px;
        color: var(--ck-signal-violet, #a78bfa);
        background: rgba(167, 139, 250, 0.12);
        vertical-align: middle;
        white-space: nowrap;
      }
    `,
  ],
})
export class DataViewComponent implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly data = inject(DataService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastrService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly detail = signal<DatasetDetailDto | null>(null);
  protected readonly loading = signal(false);
  protected readonly tab = signal('preview');
  /** Where the window on screen starts, and the rows it holds once paged. */
  protected readonly offset = signal(0);
  protected readonly paging = signal(false);
  private readonly pageRows = signal<TabularRow[] | null>(null);

  private datasetId = '';
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  protected readonly dataset = computed(() => this.detail()?.dataset ?? null);

  protected readonly columns = computed<TabularColumn[]>(
    () => this.dataset()?.schema ?? [],
  );
  /**
   * The rows on screen: the ingest cache until the reader asks for more.
   *
   * The first window costs nothing because the worker already folded it into
   * the row; every window after it is a read of the Parquet, which is the only
   * place row 8 400 exists.
   */
  protected readonly previewRows = computed<TabularRow[]>(
    () => this.pageRows() ?? this.dataset()?.preview ?? [],
  );

  protected readonly canPrev = computed(() => this.offset() > 0);
  protected readonly canNext = computed(() => {
    const total = this.dataset()?.row_count ?? 0;
    return this.offset() + this.previewRows().length < total;
  });

  protected readonly parents = computed(() => this.detail()?.lineage.parents ?? []);
  protected readonly children = computed(() => this.detail()?.lineage.children ?? []);
  protected readonly versions = computed(() => this.detail()?.versions ?? []);

  protected readonly kpis = computed<CkObjectKpi[]>(() => {
    const ds = this.dataset();
    if (!ds) return [];
    return [
      {
        label: this.i18n.t('data.kpi.rows'),
        value: (ds.row_count ?? 0).toLocaleString(this.i18n.locale()),
        tone: 'cool',
      },
      {
        label: this.i18n.t('data.kpi.columns'),
        value: String(ds.column_count ?? 0),
      },
      { label: this.i18n.t('data.kpi.size'), value: this.bytes(ds.size_bytes) },
      {
        label: this.i18n.t('data.kpi.versions'),
        value: String(this.versions().length || 1),
      },
    ];
  });

  /**
   * The model credited for this dataset's extra columns, or `null`.
   *
   * It is the thread the whole lineage story hangs on: a scored dataset must
   * name the version that wrote its predictions, both next to the columns and
   * as a link back to the card that argues for them.
   */
  protected readonly scoredBy = computed(() =>
    scoredByLabel(this.dataset()?.lineage),
  );
  protected readonly addedColumns = computed(() => [
    ...scoredColumns(this.dataset()?.lineage),
  ]);
  protected readonly modelLink = computed(() => {
    const id = this.dataset()?.lineage?.model?.model_id;
    return id ? ['/models', id] : ['/models'];
  });

  /** Column rows for the schema tab, with the same bars the header draws. */
  protected readonly profiled = computed(() => {
    const ds = this.dataset();
    if (!ds) return [];
    const stats = ds.stats ?? {};
    const nullLabel = this.i18n.t('data.table.null');
    const scored = scoredColumns(ds.lineage);
    return (ds.schema ?? []).map((column) => {
      const profile: TabularColumnStats = stats[column.name] ?? {};
      const numeric = isNumericKind(column.kind);
      return {
        name: column.name,
        kind: column.kind,
        numeric,
        scored: scored.has(column.name),
        nulls: (profile.nulls ?? 0).toLocaleString(this.i18n.locale()),
        nullRatio: nullPercent(profile),
        distinct: (profile.distinct ?? 0).toLocaleString(this.i18n.locale()),
        bars: profileBars(profile, numeric, nullLabel),
        summary: this.summaryFor(profile, numeric),
      };
    });
  });

  ngOnInit(): void {
    this.datasetId = this.route.snapshot.paramMap.get('datasetId') ?? '';
    void this.load();
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  protected isActive(dataset: DatasetDto): boolean {
    return isDatasetActive(dataset);
  }

  /** The worker names its step as a code; the locale supplies the sentence. */
  protected stepKey(
    detail: string | null | undefined,
    source: DatasetDto['source'] | undefined,
  ): string {
    return ingestStepKey(detail, source);
  }

  protected bytes(value: number | null | undefined): string {
    return formatBytes(value, this.i18n.locale());
  }

  protected previewCaption(): string {
    const ds = this.dataset();
    if (!ds) return '';
    const shown = this.previewRows().length;
    if (!shown) return '';
    // The shape — how many rows, how many columns — is the table's own badge.
    // What only this page knows is which of them are on screen.
    const locale = this.i18n.locale();
    return this.i18n.t('data.detail.preview.caption', {
      from: (this.offset() + 1).toLocaleString(locale),
      to: (this.offset() + shown).toLocaleString(locale),
    });
  }

  /**
   * Move the window one page forward or back.
   *
   * The first page is the cached preview and costs nothing to return to, so
   * stepping back to zero drops the fetched rows instead of asking for them
   * again.
   */
  protected async page(step: number): Promise<void> {
    const ds = this.dataset();
    if (!ds || this.paging()) return;
    const size = this.previewRows().length || PAGE_SIZE;
    const next = Math.max(0, this.offset() + step * size);
    if (next === this.offset()) return;
    if (next === 0) {
      this.offset.set(0);
      this.pageRows.set(null);
      return;
    }
    this.paging.set(true);
    try {
      const page = await this.data.preview(ds.id, { offset: next, limit: PAGE_SIZE });
      if (!page.rows.length) return;
      this.offset.set(page.offset);
      this.pageRows.set(page.rows);
    } catch {
      this.toast.error(this.i18n.t('data.detail.preview.failed'));
    } finally {
      this.paging.set(false);
    }
  }

  protected subtitleFor(dataset: DatasetDto): string {
    return this.i18n.t('data.table.rows_columns', {
      rows: (dataset.row_count ?? 0).toLocaleString(this.i18n.locale()),
      columns: dataset.column_count ?? 0,
    });
  }

  protected originLabel(): string {
    const ds = this.dataset();
    if (ds?.original_filename) {
      return this.i18n.t('data.lineage.origin', { filename: ds.original_filename });
    }
    return this.i18n.t('data.lineage.none');
  }

  protected async retry(): Promise<void> {
    // A re-ingest rewrites the Parquet, so any window read from the old one is
    // no longer about this dataset.
    this.offset.set(0);
    this.pageRows.set(null);
    await this.data.reingest(this.datasetId);
    await this.load();
  }

  protected async remove(): Promise<void> {
    const ds = this.dataset();
    if (!ds) return;
    if (!confirm(this.i18n.t('data.detail.delete_confirm', { name: ds.name }))) return;
    await this.data.remove(ds.id);
    this.toast.success(this.i18n.t('data.detail.deleted', { name: ds.name }));
    void this.router.navigate(['/data']);
  }

  private async load(): Promise<void> {
    if (!this.datasetId) return;
    this.loading.set(true);
    try {
      this.detail.set(await this.data.detail(this.datasetId));
      this.syncPolling();
    } catch {
      this.detail.set(null);
    } finally {
      this.loading.set(false);
    }
  }

  private summaryFor(profile: TabularColumnStats, numeric: boolean): string {
    const parts: string[] = [];
    if (numeric && profile.min !== null && profile.min !== undefined) {
      parts.push(`${profile.min} → ${profile.max}`);
      if (profile.mean !== null && profile.mean !== undefined) {
        parts.push(
          `${this.i18n.t('data.schema.mean')} ${Number(profile.mean).toLocaleString(
            this.i18n.locale(),
            { maximumFractionDigits: 2 },
          )}`,
        );
      }
    } else if (profile.top_values?.length) {
      parts.push(
        profile.top_values
          .slice(0, 3)
          .map((entry) => String(entry.value ?? this.i18n.t('data.table.null')))
          .join(', '),
      );
    }
    return parts.join(' · ');
  }

  private syncPolling(): void {
    const ds = this.dataset();
    if (ds && isDatasetActive(ds)) {
      if (this.pollTimer) return;
      this.pollTimer = setInterval(() => void this.load(), POLL_INTERVAL_MS);
    } else {
      this.stopPolling();
    }
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
}
