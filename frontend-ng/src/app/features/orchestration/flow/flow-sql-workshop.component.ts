/**
 * `<app-flow-sql-workshop>` — the authoring surface of a SQL transform node.
 *
 * Opened from the inspector for the SELECTED `sql_transform_v1` node. Every
 * edit writes back through the store's dotted-path config writers, so the
 * statement, the output name and the pinned inputs are versioned with the flow
 * like any other node config.
 *
 * The layout is the one every query tool trained analysts on: statement on top,
 * result underneath, catalog on the side.
 *
 *  - **Editor** — `ck-code-editor` in SQL mode, completing against the REAL
 *    columns of the resolved sources (`FROM input` then `input.` offers the
 *    dataset's own columns). Ctrl/⌘+Enter runs.
 *  - **Result** — the shared `ck-data-table`, so the preview of a transform is
 *    literally the table the produced dataset will show, column profiles
 *    included.
 *  - **Inputs** — the pin picker plus the catalog of queryable names, which is
 *    what makes a statement writable without leaving the dialog.
 *  - **Output** — the name of the dataset each run versions.
 *
 * Nothing here validates SQL: refusals come back coded from the server and are
 * rendered as translated sentences (`flow.transform.error.*`).
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  output,
  signal,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { RouterLink } from '@angular/router';
import { CodeEditorComponent } from '@app/shared/ui/code-editor.component';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import { FlowStore } from './flow.store';
import { FlowTransformService } from './flow-transform.service';
import {
  defaultOutputName,
  isSqlTransformNode,
  preflightSql,
  readSqlTransformParams,
  sqlLineCount,
  starterSqlFor,
  transformViewName,
  type SqlTransformParams,
  type SqlTransformSourcePin,
  type TransformFailure,
  type TransformSourceCatalogEntry,
} from './flow-transform.vm';

type WorkshopTab = 'sources' | 'output';

/** Rows a preview asks for: enough to read a shape, small enough to be instant. */
const PREVIEW_ROW_LIMIT = 50;

/** One store write per typing pause — a statement session emits hundreds of
 * edits, and unbatched they would flood the undo stack (one Ctrl+Z per
 * character) and clone the graph per key. Same policy as the recipe workshop. */
const SQL_WRITE_DEBOUNCE_MS = 400;

@Component({
  selector: 'app-flow-sql-workshop',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, RouterLink, CodeEditorComponent, DataTableComponent, IconComponent],
  styleUrl: './flow-sql-workshop.component.scss',
  template: `
    <div
      class="ck-sql-workshop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ck-sql-workshop-title"
      cdkTrapFocus
      [cdkTrapFocusAutoCapture]="true"
      (keydown.escape)="close.emit()"
    >
      <div class="ck-sql-workshop__backdrop" (click)="close.emit()"></div>
      <section class="ck-sql-workshop__panel">
        <header class="ck-sql-workshop__head">
          <div class="ck-sql-workshop__identity">
            <span class="ck-sql-workshop__badge">
              <app-icon name="database" [size]="15" />
            </span>
            <div>
              <h2 id="ck-sql-workshop-title">{{ i18n.t('flow.transform.workshop.title') }}</h2>
              <p>{{ node()?.label || node()?.id }}</p>
            </div>
          </div>
          <div class="ck-sql-workshop__head-actions">
            <button
              type="button"
              class="ck-sql-workshop__action ck-sql-workshop__action--primary"
              data-testid="run-sql-preview"
              [disabled]="transform.busy()"
              (click)="runPreview()"
            >
              <app-icon [name]="transform.busy() ? 'loader-2' : 'play'" [size]="13" />
              {{
                transform.busy()
                  ? i18n.t('flow.transform.run.busy')
                  : i18n.t('flow.transform.run')
              }}
              <kbd>{{ i18n.t('flow.transform.run.shortcut') }}</kbd>
            </button>
            <button
              type="button"
              class="ck-sql-workshop__close"
              (click)="close.emit()"
              [attr.aria-label]="i18n.t('flow.transform.workshop.close')"
            >
              <app-icon name="x" [size]="16" />
            </button>
          </div>
        </header>

        @if (node()) {
          <div class="ck-sql-workshop__body">
            <div class="ck-sql-workshop__main">
              <div class="ck-sql-workshop__editor">
                <div class="ck-sql-workshop__editor-head">
                  <span>{{ i18n.t('flow.transform.editor.label') }}</span>
                  <code>{{ i18n.t('flow.transform.editor.engine') }}</code>
                  <span class="ck-sql-workshop__editor-lines">
                    {{ i18n.t('flow.transform.editor.lines', { count: lineCount() }) }}
                  </span>
                </div>
                <ck-code-editor
                  class="ck-sql-workshop__cm"
                  language="sql"
                  [value]="params().sql"
                  [sqlSchema]="transform.editorSchema()"
                  [ariaLabel]="i18n.t('flow.transform.editor.aria')"
                  [placeholder]="i18n.t('flow.transform.editor.placeholder')"
                  (valueChange)="onSql($event)"
                  (submit)="runPreview()"
                />
              </div>

              <div class="ck-sql-workshop__result">
                @if (failure(); as reason) {
                  <p class="ck-sql-workshop__error" role="alert" data-testid="sql-failure">
                    {{ i18n.t(reason.key) }}
                    @if (reason.detail) {
                      <code class="ck-sql-workshop__detail">{{ reason.detail }}</code>
                    }
                  </p>
                } @else if (transform.preview(); as result) {
                  <ck-data-table
                    [columns]="result.schema"
                    [rows]="result.preview"
                    [stats]="result.stats"
                    maxHeight="100%"
                    [caption]="
                      i18n.t('flow.transform.result.caption', {
                        rows: result.row_count,
                        columns: result.column_count,
                        duration: result.duration_ms,
                      })
                    "
                    [emptyLabel]="i18n.t('flow.transform.result.no_rows')"
                  />
                } @else {
                  <div class="ck-sql-workshop__placeholder">
                    <app-icon name="table" [size]="18" />
                    <p>{{ i18n.t('flow.transform.result.empty') }}</p>
                  </div>
                }
              </div>
            </div>

            <aside class="ck-sql-workshop__side">
              <div
                class="ck-sql-workshop__tabs"
                role="tablist"
                [attr.aria-label]="i18n.t('flow.transform.tabs.aria')"
              >
                <button
                  type="button"
                  role="tab"
                  [attr.aria-selected]="tab() === 'sources'"
                  (click)="tab.set('sources')"
                >
                  <app-icon name="table" [size]="13" /> {{ i18n.t('flow.transform.tab.sources') }}
                </button>
                <button
                  type="button"
                  role="tab"
                  [attr.aria-selected]="tab() === 'output'"
                  (click)="tab.set('output')"
                >
                  <app-icon name="git-branch" [size]="13" />
                  {{ i18n.t('flow.transform.tab.output') }}
                </button>
              </div>

              <div class="ck-sql-workshop__tabpane">
                @switch (tab()) {
                  @case ('sources') {
                    <p class="ck-sql-workshop__hint">{{ i18n.t('flow.transform.sources.hint') }}</p>

                    <label class="ck-sql-workshop__field">
                      <span>{{ i18n.t('flow.transform.sources.add') }}</span>
                      <select
                        data-testid="pin-dataset"
                        [value]="''"
                        [disabled]="transform.datasetsLoading()"
                        (change)="onPin($event)"
                      >
                        <option value="">
                          {{
                            transform.datasetsLoading()
                              ? i18n.t('flow.transform.sources.loading')
                              : pinnable().length
                                ? i18n.t('flow.transform.sources.add')
                                : i18n.t('flow.transform.sources.none_available')
                          }}
                        </option>
                        @for (dataset of pinnable(); track dataset.slug) {
                          <option [value]="dataset.slug">
                            {{ dataset.name }} · v{{ dataset.version }}
                          </option>
                        }
                      </select>
                    </label>

                    @if (params().sources.length === 0) {
                      <p class="ck-sql-workshop__hint">
                        {{ i18n.t('flow.transform.sources.empty') }}
                      </p>
                    }

                    @if (transform.sources().length > 0) {
                      <span class="ck-sql-workshop__label">
                        {{ i18n.t('flow.transform.sources.catalog') }}
                      </span>
                    }
                    @for (source of transform.sources(); track source.dataset_id) {
                      <div class="ck-sql-workshop__source" data-testid="sql-source">
                        <div class="ck-sql-workshop__source-head">
                          <code>{{ source.view }}</code>
                          <button
                            type="button"
                            class="ck-sql-workshop__mini"
                            [attr.aria-label]="
                              i18n.t('flow.transform.sources.starter.aria', { view: source.view })
                            "
                            (click)="useStarter(source)"
                          >
                            {{ i18n.t('flow.transform.sources.starter') }}
                          </button>
                          <button
                            type="button"
                            class="ck-sql-workshop__mini ck-sql-workshop__mini--danger"
                            (click)="unpin(source)"
                          >
                            {{ i18n.t('flow.transform.sources.remove') }}
                          </button>
                        </div>
                        <p class="ck-sql-workshop__source-meta">
                          {{ source.name }} ·
                          {{
                            i18n.t('flow.transform.sources.rows', {
                              rows: source.rows,
                              columns: source.columns.length,
                            })
                          }}
                        </p>
                        @if (source.aliases.length > 0) {
                          <p class="ck-sql-workshop__source-meta">
                            {{
                              i18n.t('flow.transform.sources.alias', {
                                aliases: source.aliases.join(', '),
                              })
                            }}
                          </p>
                        }
                        <ul class="ck-sql-workshop__columns">
                          @for (column of source.columns; track column.name) {
                            <li [attr.data-kind]="column.kind" [title]="column.dtype || column.kind">
                              {{ column.name }}
                            </li>
                          }
                        </ul>
                      </div>
                    }
                  }

                  @case ('output') {
                    <label class="ck-sql-workshop__field">
                      <span>{{ i18n.t('flow.transform.output.name') }}</span>
                      <input
                        type="text"
                        spellcheck="false"
                        data-testid="output-name"
                        [value]="params().output_name"
                        [attr.placeholder]="outputPlaceholder()"
                        (change)="onOutputName($event)"
                      />
                    </label>
                    <p class="ck-sql-workshop__hint">{{ i18n.t('flow.transform.output.hint') }}</p>
                    <p class="ck-sql-workshop__hint">
                      {{ i18n.t('flow.transform.output.versioning') }}
                    </p>
                    <a class="ck-sql-workshop__action" routerLink="/data">
                      <app-icon name="table" [size]="13" />
                      {{ i18n.t('flow.transform.output.open_data') }}
                    </a>
                  }
                }
              </div>
            </aside>
          </div>
        }
      </section>
    </div>
  `,
})
export class FlowSqlWorkshopComponent {
  protected readonly store = inject(FlowStore);
  protected readonly transform = inject(FlowTransformService);
  private readonly destroyRef = inject(DestroyRef);
  readonly i18n = inject(I18nService);

  readonly close = output<void>();

  protected readonly node = this.store.selectedNode;
  protected readonly params = computed<SqlTransformParams>(() =>
    readSqlTransformParams(this.node()),
  );
  protected readonly lineCount = computed(() => sqlLineCount(this.params().sql));
  protected readonly tab = signal<WorkshopTab>('sources');
  /** A client-side preflight refusal shadows the server's last answer. */
  protected readonly preflight = signal<TransformFailure | null>(null);
  protected readonly failure = computed(() => this.preflight() ?? this.transform.failure());

  /** Datasets not already pinned — the picker never offers a duplicate. */
  protected readonly pinnable = computed(() => {
    const pinned = new Set(
      this.params().sources.map((pin) => pin.dataset_slug ?? pin.dataset_id ?? ''),
    );
    return this.transform.datasets().filter((dataset) => !pinned.has(dataset.slug));
  });

  protected readonly outputPlaceholder = computed(() =>
    defaultOutputName(
      this.node()?.label,
      this.i18n.t('flow.transform.output.name.placeholder'),
    ),
  );

  private sqlFlushTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingSql: string | null = null;
  private pendingSqlNodeId: string | null = null;
  private lastResolvedPins = '';

  constructor() {
    // The workshop exists FOR the selected transform node; if it stops being
    // one (deletion, undo, external selection change) the dialog closes itself.
    effect(() => {
      if (!isSqlTransformNode(this.node())) this.close.emit();
    });
    // Pins are what make the editor useful: resolving them yields the columns
    // completion offers. Re-resolves whenever the author pins or unpins one.
    effect(() => {
      const pins = this.params().sources;
      const signature = JSON.stringify(pins);
      if (signature === this.lastResolvedPins) return;
      this.lastResolvedPins = signature;
      void this.transform.resolveSources(pins);
    });
    void this.transform.ensureDatasets();
    this.destroyRef.onDestroy(() => this.flushSql());
  }

  protected onSql(sql: string): void {
    const id = this.node()?.id;
    if (!id) return;
    this.pendingSql = sql;
    this.pendingSqlNodeId = id;
    this.preflight.set(null);
    if (this.sqlFlushTimer !== null) clearTimeout(this.sqlFlushTimer);
    this.sqlFlushTimer = setTimeout(() => this.flushSql(), SQL_WRITE_DEBOUNCE_MS);
  }

  /** Land the pending statement edit in the store (idempotent). Runs on the
   * debounce tick, before a preview, and on destroy — so no keystroke is ever
   * lost to the debounce window. */
  private flushSql(): void {
    if (this.sqlFlushTimer !== null) {
      clearTimeout(this.sqlFlushTimer);
      this.sqlFlushTimer = null;
    }
    if (this.pendingSql === null || this.pendingSqlNodeId === null) return;
    const sql = this.pendingSql;
    const nodeId = this.pendingSqlNodeId;
    this.pendingSql = null;
    this.pendingSqlNodeId = null;
    this.store.updateNodeConfig(nodeId, 'params.sql', sql);
  }

  protected onOutputName(event: Event): void {
    this.writeParam('output_name', (event.target as HTMLInputElement).value.trim());
  }

  /** Pin the picked dataset by slug, so the node follows its latest version. */
  protected onPin(event: Event): void {
    const select = event.target as HTMLSelectElement;
    const slug = select.value;
    select.value = '';
    if (!slug) return;
    const dataset = this.transform.datasets().find((row) => row.slug === slug);
    if (!dataset) return;
    const current = this.params().sources;
    const taken = current.map((pin) => pin.view ?? '').filter(Boolean);
    const pin: SqlTransformSourcePin = {
      dataset_slug: dataset.slug,
      view: transformViewName(dataset.name || dataset.slug, taken),
    };
    this.writeParam('sources', [...current, pin]);
  }

  protected unpin(source: TransformSourceCatalogEntry): void {
    const remaining = this.params().sources.filter(
      (pin) => pin.view !== source.view && pin.dataset_id !== source.dataset_id,
    );
    this.writeParam('sources', remaining);
  }

  /** Write a ready-to-run statement over one source into the editor. */
  protected useStarter(source: TransformSourceCatalogEntry): void {
    const id = this.node()?.id;
    if (!id) return;
    this.pendingSql = null;
    this.pendingSqlNodeId = null;
    this.preflight.set(null);
    this.store.updateNodeConfig(id, 'params.sql', starterSqlFor(source));
    this.transform.clearResult();
  }

  protected async runPreview(): Promise<void> {
    // The dispatch reads the store: the debounced edit must land first, or the
    // preview would run the previous keystroke's statement.
    this.flushSql();
    const params = this.params();
    const refusal = preflightSql(params.sql);
    this.preflight.set(refusal);
    if (refusal) return;
    await this.transform.run(params.sql, params.sources, PREVIEW_ROW_LIMIT);
  }

  private writeParam(field: keyof SqlTransformParams, value: unknown): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeConfig(id, `params.${field}`, value);
  }
}
