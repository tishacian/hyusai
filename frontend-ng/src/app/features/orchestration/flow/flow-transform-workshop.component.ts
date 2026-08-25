/**
 * `<app-flow-transform-workshop>` — the authoring surface of a transform node.
 *
 * Opened from the inspector for the SELECTED transform node, whatever its
 * engine. Every edit writes back through the store's dotted-path config
 * writers, so the program, the output name, the pinned inputs and the declared
 * libraries are versioned with the flow like any other node config.
 *
 * The layout is the one every query tool trained analysts on: program on top,
 * result underneath, catalog on the side. **One chrome for both engines** —
 * switching from SQL to Polars must feel like switching language, not tool — so
 * everything engine-specific is read from `TRANSFORM_ENGINES` rather than
 * branched here.
 *
 *  - **Editor** — `ck-code-editor` in the engine's language. In SQL mode it
 *    completes against the REAL columns of the resolved sources (`FROM input`
 *    then `input.` offers the dataset's own columns). Ctrl/⌘+Enter runs.
 *  - **Result** — the shared `ck-data-table`, so the preview of a transform is
 *    literally the table the produced dataset will show, column profiles
 *    included. For Polars, whatever the author printed is shown under it.
 *  - **Inputs** — the pin picker plus the catalog of addressable names, which
 *    is what makes a program writable without leaving the dialog.
 *  - **Libraries** — Polars only: the extra requirements its managed venv
 *    carries. The first run in a workspace builds it, and the run phase says so.
 *  - **Output** — the name of the dataset each run versions.
 *
 * Nothing here validates a program beyond the two habitual mistakes: refusals
 * come back coded from the server and are rendered as translated sentences
 * (`flow.transform.error.*`).
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
  TRANSFORM_ENGINES,
  clampTransformTimeout,
  defaultOutputName,
  isTransformNode,
  preflightProgram,
  programLineCount,
  readTransformParams,
  requirementLines,
  starterProgramFor,
  transformEngineOf,
  transformViewName,
  type TransformFailure,
  type TransformParams,
  type TransformSourceCatalogEntry,
  type TransformSourcePin,
} from './flow-transform.vm';

type WorkshopTab = 'sources' | 'environment' | 'output';

/** Rows a preview asks for: enough to read a shape, small enough to be instant. */
const PREVIEW_ROW_LIMIT = 50;

/** One store write per typing pause — an authoring session emits hundreds of
 * edits, and unbatched they would flood the undo stack (one Ctrl+Z per
 * character) and clone the graph per key. Same policy as the recipe workshop. */
const PROGRAM_WRITE_DEBOUNCE_MS = 400;

@Component({
  selector: 'app-flow-transform-workshop',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, RouterLink, CodeEditorComponent, DataTableComponent, IconComponent],
  styleUrl: './flow-transform-workshop.component.scss',
  template: `
    <div
      class="ck-transform-workshop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ck-transform-workshop-title"
      cdkTrapFocus
      [cdkTrapFocusAutoCapture]="true"
      (keydown.escape)="close.emit()"
    >
      <div class="ck-transform-workshop__backdrop" (click)="close.emit()"></div>
      <section class="ck-transform-workshop__panel">
        <header class="ck-transform-workshop__head">
          <div class="ck-transform-workshop__identity">
            <span class="ck-transform-workshop__badge">
              <app-icon [name]="engine() === 'polars' ? 'code' : 'database'" [size]="15" />
            </span>
            <div>
              <h2 id="ck-transform-workshop-title">{{ i18n.t(copy().title) }}</h2>
              <p>{{ node()?.label || node()?.id }}</p>
            </div>
          </div>
          <div class="ck-transform-workshop__head-actions">
            @if (transform.busy() && transform.phase(); as phase) {
              <span class="ck-transform-workshop__phase" data-testid="transform-phase">
                <app-icon name="loader-2" [size]="12" />
                {{ i18n.t('flow.transform.phase.' + phase) }}
              </span>
            }
            @if (cancellable()) {
              <button
                type="button"
                class="ck-transform-workshop__action"
                data-testid="cancel-transform-preview"
                (click)="transform.cancel()"
              >
                <app-icon name="x" [size]="13" />
                {{ i18n.t('flow.transform.run.cancel') }}
              </button>
            }
            <button
              type="button"
              class="ck-transform-workshop__action ck-transform-workshop__action--primary"
              data-testid="run-transform-preview"
              [disabled]="transform.busy()"
              (click)="runPreview()"
            >
              <app-icon [name]="transform.busy() ? 'loader-2' : 'play'" [size]="13" />
              {{
                transform.busy() ? i18n.t('flow.transform.run.busy') : i18n.t(copy().run)
              }}
              <kbd>{{ i18n.t('flow.transform.run.shortcut') }}</kbd>
            </button>
            <button
              type="button"
              class="ck-transform-workshop__close"
              (click)="close.emit()"
              [attr.aria-label]="i18n.t(copy().close)"
            >
              <app-icon name="x" [size]="16" />
            </button>
          </div>
        </header>

        @if (node()) {
          <div class="ck-transform-workshop__body">
            <div class="ck-transform-workshop__main">
              <div class="ck-transform-workshop__editor">
                <div class="ck-transform-workshop__editor-head">
                  <span>{{ i18n.t(copy().editorLabel) }}</span>
                  <code>{{ i18n.t(copy().editorEngine) }}</code>
                  <span class="ck-transform-workshop__editor-lines">
                    {{ i18n.t('flow.transform.editor.lines', { count: lineCount() }) }}
                  </span>
                </div>
                <ck-code-editor
                  class="ck-transform-workshop__cm"
                  [language]="descriptor().language"
                  [value]="params().program"
                  [sqlSchema]="transform.editorSchema()"
                  [ariaLabel]="i18n.t(copy().editorAria)"
                  [placeholder]="i18n.t(copy().editorPlaceholder)"
                  (valueChange)="onProgram($event)"
                  (submit)="runPreview()"
                />
              </div>

              <div class="ck-transform-workshop__result">
                @if (failure(); as reason) {
                  <p
                    class="ck-transform-workshop__error"
                    role="alert"
                    data-testid="transform-failure"
                  >
                    {{ i18n.t(reason.key) }}
                    @if (reason.detail) {
                      <code class="ck-transform-workshop__detail">{{ reason.detail }}</code>
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
                  <div class="ck-transform-workshop__placeholder">
                    <app-icon name="table" [size]="18" />
                    <p>{{ i18n.t(copy().resultEmpty) }}</p>
                  </div>
                }
                @if (transform.stdout(); as printed) {
                  <span class="ck-transform-workshop__label">
                    {{ i18n.t('flow.transform.stdout') }}
                  </span>
                  <pre class="ck-transform-workshop__stdout" data-testid="transform-stdout">{{
                    printed
                  }}</pre>
                }
              </div>
            </div>

            <aside class="ck-transform-workshop__side">
              <div
                class="ck-transform-workshop__tabs"
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
                @if (descriptor().managedEnvironment) {
                  <button
                    type="button"
                    role="tab"
                    data-testid="tab-environment"
                    [attr.aria-selected]="tab() === 'environment'"
                    (click)="tab.set('environment')"
                  >
                    <app-icon name="package" [size]="13" />
                    {{ i18n.t('flow.transform.tab.environment') }}
                  </button>
                }
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

              <div class="ck-transform-workshop__tabpane">
                @switch (tab()) {
                  @case ('sources') {
                    <p class="ck-transform-workshop__hint">{{ i18n.t(copy().sourcesHint) }}</p>

                    <label class="ck-transform-workshop__field">
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
                      <p class="ck-transform-workshop__hint">
                        {{ i18n.t('flow.transform.sources.empty') }}
                      </p>
                    }

                    @if (transform.sources().length > 0) {
                      <span class="ck-transform-workshop__label">
                        {{ i18n.t('flow.transform.sources.catalog') }}
                      </span>
                    }
                    @for (source of transform.sources(); track source.dataset_id) {
                      <div class="ck-transform-workshop__source" data-testid="transform-source">
                        <div class="ck-transform-workshop__source-head">
                          <code>{{ source.view }}</code>
                          <button
                            type="button"
                            class="ck-transform-workshop__mini"
                            [attr.aria-label]="
                              i18n.t('flow.transform.sources.starter.aria', { view: source.view })
                            "
                            (click)="useStarter(source)"
                          >
                            {{ i18n.t('flow.transform.sources.starter') }}
                          </button>
                          <button
                            type="button"
                            class="ck-transform-workshop__mini ck-transform-workshop__mini--danger"
                            (click)="unpin(source)"
                          >
                            {{ i18n.t('flow.transform.sources.remove') }}
                          </button>
                        </div>
                        <p class="ck-transform-workshop__source-meta">
                          {{ source.name }} ·
                          {{
                            i18n.t('flow.transform.sources.rows', {
                              rows: source.rows,
                              columns: source.columns.length,
                            })
                          }}
                        </p>
                        @if (source.aliases.length > 0) {
                          <p class="ck-transform-workshop__source-meta">
                            {{
                              i18n.t('flow.transform.sources.alias', {
                                aliases: source.aliases.join(', '),
                              })
                            }}
                          </p>
                        }
                        <ul class="ck-transform-workshop__columns">
                          @for (column of source.columns; track column.name) {
                            <li [attr.data-kind]="column.kind" [title]="column.dtype || column.kind">
                              {{ column.name }}
                            </li>
                          }
                        </ul>
                      </div>
                    }
                  }

                  @case ('environment') {
                    <p class="ck-transform-workshop__hint">
                      {{ i18n.t('flow.transform.environment.hint') }}
                    </p>
                    <label class="ck-transform-workshop__field">
                      <span>{{ i18n.t('flow.transform.environment.requirements') }}</span>
                      <textarea
                        class="ck-transform-workshop__textarea"
                        spellcheck="false"
                        data-testid="requirements-text"
                        [value]="params().requirements_text"
                        [attr.placeholder]="
                          i18n.t('flow.transform.environment.requirements.placeholder')
                        "
                        (change)="onRequirements($event)"
                      ></textarea>
                    </label>
                    <p class="ck-transform-workshop__hint">
                      {{
                        i18n.t('flow.transform.environment.count', {
                          count: declaredLibraries().length,
                        })
                      }}
                    </p>
                    <label class="ck-transform-workshop__field">
                      <span>{{ i18n.t('flow.transform.environment.timeout') }}</span>
                      <input
                        type="number"
                        min="1"
                        max="600"
                        data-testid="transform-timeout"
                        [value]="params().timeout_s"
                        (change)="onTimeout($event)"
                      />
                    </label>
                  }

                  @case ('output') {
                    <label class="ck-transform-workshop__field">
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
                    <p class="ck-transform-workshop__hint">{{ i18n.t('flow.transform.output.hint') }}</p>
                    <p class="ck-transform-workshop__hint">
                      {{ i18n.t('flow.transform.output.versioning') }}
                    </p>
                    <a class="ck-transform-workshop__action" routerLink="/data">
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
export class FlowTransformWorkshopComponent {
  protected readonly store = inject(FlowStore);
  protected readonly transform = inject(FlowTransformService);
  private readonly destroyRef = inject(DestroyRef);
  readonly i18n = inject(I18nService);

  readonly close = output<void>();

  protected readonly node = this.store.selectedNode;
  protected readonly engine = computed(() => transformEngineOf(this.node()) ?? 'sql');
  protected readonly descriptor = computed(() => TRANSFORM_ENGINES[this.engine()]);
  protected readonly copy = computed(() => this.descriptor().copy);
  protected readonly params = computed<TransformParams>(() =>
    readTransformParams(this.node(), this.engine()),
  );
  protected readonly lineCount = computed(() => programLineCount(this.params().program));
  protected readonly declaredLibraries = computed(() =>
    requirementLines(this.params().requirements_text),
  );
  protected readonly tab = signal<WorkshopTab>('sources');
  /** A client-side preflight refusal shadows the server's last answer. */
  protected readonly preflight = signal<TransformFailure | null>(null);
  protected readonly failure = computed(() => this.preflight() ?? this.transform.failure());
  /** Only a queued run can be stopped; an inline one is already over. */
  protected readonly cancellable = computed(() => {
    const row = this.transform.execution();
    return this.transform.busy() && !!row && !row.cancel_requested;
  });

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

  private programFlushTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingProgram: string | null = null;
  private pendingProgramNodeId: string | null = null;
  private lastResolvedPins = '';

  constructor() {
    // The workshop exists FOR the selected transform node; if it stops being
    // one (deletion, undo, external selection change) the dialog closes itself.
    effect(() => {
      if (!isTransformNode(this.node())) this.close.emit();
    });
    // Pins are what make the editor useful: resolving them yields the columns
    // completion offers. Re-resolves whenever the author pins or unpins one.
    effect(() => {
      const engine = this.engine();
      const pins = this.params().sources;
      const signature = `${engine}:${JSON.stringify(pins)}`;
      if (signature === this.lastResolvedPins) return;
      this.lastResolvedPins = signature;
      void this.transform.resolveSources(engine, pins);
    });
    void this.transform.ensureDatasets();
    this.destroyRef.onDestroy(() => this.flushProgram());
  }

  protected onProgram(program: string): void {
    const id = this.node()?.id;
    if (!id) return;
    this.pendingProgram = program;
    this.pendingProgramNodeId = id;
    this.preflight.set(null);
    if (this.programFlushTimer !== null) clearTimeout(this.programFlushTimer);
    this.programFlushTimer = setTimeout(
      () => this.flushProgram(),
      PROGRAM_WRITE_DEBOUNCE_MS,
    );
  }

  /** Land the pending program edit in the store (idempotent). Runs on the
   * debounce tick, before a preview, and on destroy — so no keystroke is ever
   * lost to the debounce window. */
  private flushProgram(): void {
    if (this.programFlushTimer !== null) {
      clearTimeout(this.programFlushTimer);
      this.programFlushTimer = null;
    }
    if (this.pendingProgram === null || this.pendingProgramNodeId === null) return;
    const program = this.pendingProgram;
    const nodeId = this.pendingProgramNodeId;
    this.pendingProgram = null;
    this.pendingProgramNodeId = null;
    this.store.updateNodeConfig(
      nodeId,
      `params.${this.descriptor().programField}`,
      program,
    );
  }

  protected onOutputName(event: Event): void {
    this.writeParam('output_name', (event.target as HTMLInputElement).value.trim());
  }

  protected onRequirements(event: Event): void {
    this.writeParam('requirements_text', (event.target as HTMLTextAreaElement).value);
  }

  protected onTimeout(event: Event): void {
    this.writeParam(
      'timeout_s',
      clampTransformTimeout((event.target as HTMLInputElement).value),
    );
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
    const pin: TransformSourcePin = {
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

  /** Write a ready-to-run program over one source into the editor. */
  protected useStarter(source: TransformSourceCatalogEntry): void {
    const id = this.node()?.id;
    if (!id) return;
    this.pendingProgram = null;
    this.pendingProgramNodeId = null;
    this.preflight.set(null);
    this.store.updateNodeConfig(
      id,
      `params.${this.descriptor().programField}`,
      starterProgramFor(source, this.engine()),
    );
    this.transform.clearResult();
  }

  protected async runPreview(): Promise<void> {
    // The dispatch reads the store: the debounced edit must land first, or the
    // preview would run the previous keystroke's program.
    this.flushProgram();
    const params = this.params();
    const engine = this.engine();
    const refusal = preflightProgram(params.program, engine);
    this.preflight.set(refusal);
    if (refusal) return;
    await this.transform.run(engine, params.program, params.sources, {
      rowLimit: PREVIEW_ROW_LIMIT,
      requirementsText: params.requirements_text,
      timeoutS: params.timeout_s,
    });
  }

  private writeParam(field: string, value: unknown): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeConfig(id, `params.${field}`, value);
  }
}
