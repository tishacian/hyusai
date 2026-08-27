/**
 * `<app-flow-transform-workshop>` — the authoring surface of a transform node.
 *
 * Opened from the inspector for the SELECTED transform node, whatever its
 * engine. Every edit writes back through the store's dotted-path config
 * writers, so the program, the output name, the pinned inputs and the declared
 * libraries are versioned with the flow like any other node config.
 *
 * The layout is the one every query tool trained analysts on: program on top,
 * result underneath, catalog on the side. **One chrome for every engine** —
 * switching from SQL to Polars to dbt must feel like switching language, not
 * tool — so everything engine-specific is read from `TRANSFORM_ENGINES` rather
 * than branched here. Even the number of files is: the editor always shows one
 * `TransformFile`, and a single-statement engine simply has exactly one.
 *
 *  - **Files** — dbt only: the model tree plus `schema.yml`, with the published
 *    model badged. Adding, renaming, publishing and deleting a model are one
 *    store write each, so a rename is one Ctrl+Z.
 *  - **Editor** — `ck-code-editor` in the ACTIVE FILE's language. In SQL mode
 *    it completes against the REAL columns of the resolved sources (`FROM input`
 *    then `input.` offers the dataset's own columns). Ctrl/⌘+Enter runs.
 *  - **Build** — dbt only: which models built and which tests passed, rendered
 *    on refusal too, because "which test refused how many rows" IS the answer.
 *  - **Result** — the shared `ck-data-table`, so the preview of a transform is
 *    literally the table the produced dataset will show, column profiles
 *    included. For Polars, whatever the author printed is shown under it.
 *  - **Inputs** — the pin picker plus the catalog of addressable names, which
 *    is what makes a program writable without leaving the dialog.
 *  - **Libraries** — managed engines only: the extra requirements their venv
 *    carries. The first run in a workspace builds it, and the phase says so.
 *  - **Output** — the name of the dataset each run versions.
 *
 * Nothing here validates a program beyond the habitual mistakes: refusals come
 * back coded from the server and are rendered as translated sentences
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
  viewChild,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { RouterLink } from '@angular/router';
import {
  CodeEditorComponent,
  type CodeEditorPosition,
} from '@app/shared/ui/code-editor.component';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import { FlowStore } from './flow.store';
import { FlowTransformService } from './flow-transform.service';
import {
  DBT_MAX_MODELS,
  TRANSFORM_ENGINES,
  addDbtModel,
  clampTransformTimeout,
  dbtNodePassed,
  defaultOutputName,
  fileWrite,
  isTransformNode,
  modelIndexOf,
  preflightTransform,
  programLineCount,
  publishDbtModel,
  readTransformParams,
  removeDbtModel,
  renameDbtModel,
  requirementLines,
  starterProgramFor,
  toggleDbtMaterialize,
  transformChecklist,
  transformEngineOf,
  transformFiles,
  transformViewName,
  type DbtNodeResult,
  type TransformFailure,
  type TransformFile,
  type TransformParams,
  type TransformParamsPatch,
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
              <app-icon [name]="descriptor().icon" [size]="15" />
            </span>
            <div>
              <h2 id="ck-transform-workshop-title">{{ i18n.t(copy().title) }}</h2>
              <p>{{ node()?.label || node()?.id }}</p>
            </div>
          </div>
          <div class="ck-transform-workshop__head-actions">
            @if (transform.busy() && currentPhase(); as step) {
              <span class="ck-transform-workshop__phase" data-testid="transform-phase">
                <app-icon name="loader-2" [size]="12" />
                {{ i18n.t(step.key) }}
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
                @if (descriptor().multiFile) {
                  <div
                    class="ck-transform-workshop__files"
                    role="tablist"
                    data-testid="transform-files"
                    [attr.aria-label]="i18n.t('flow.transform.files.aria')"
                  >
                    @for (file of files(); track file.id) {
                      <button
                        type="button"
                        role="tab"
                        class="ck-transform-workshop__file"
                        [attr.data-kind]="file.kind"
                        [attr.data-published]="file.published ? 'true' : null"
                        [attr.aria-selected]="file.id === activeFile().id"
                        (click)="activeFileId.set(file.id)"
                      >
                        <app-icon
                          [name]="file.kind === 'tests' ? 'shield-check' : 'file-code'"
                          [size]="12"
                        />
                        {{ file.name }}
                        @if (file.published) {
                          <span
                            class="ck-transform-workshop__pill"
                            [title]="i18n.t('flow.transform.files.published.hint')"
                          >
                            {{ i18n.t('flow.transform.files.published') }}
                          </span>
                        } @else if (file.materialized) {
                          <span
                            class="ck-transform-workshop__pill"
                            data-testid="materialized-pill"
                            [title]="i18n.t('flow.transform.files.materialized.hint')"
                          >
                            {{ i18n.t('flow.transform.files.materialized') }}
                          </span>
                        }
                      </button>
                    }
                    <button
                      type="button"
                      class="ck-transform-workshop__file ck-transform-workshop__file--add"
                      data-testid="add-dbt-model"
                      [disabled]="!canAddModel()"
                      (click)="addModel()"
                    >
                      <app-icon name="plus" [size]="12" />
                      {{ i18n.t('flow.transform.files.add') }}
                    </button>
                  </div>
                }
                <div class="ck-transform-workshop__editor-head">
                  @if (activeModelIndex() !== null) {
                    <input
                      class="ck-transform-workshop__rename"
                      type="text"
                      spellcheck="false"
                      data-testid="dbt-model-name"
                      [value]="activeModelName()"
                      [attr.aria-label]="i18n.t('flow.transform.files.rename.aria')"
                      (change)="onModelName($event)"
                    />
                    <button
                      type="button"
                      class="ck-transform-workshop__mini"
                      data-testid="publish-dbt-model"
                      [disabled]="activeFile().published"
                      [title]="i18n.t('flow.transform.files.publish.hint')"
                      (click)="publishActiveModel()"
                    >
                      {{ i18n.t('flow.transform.files.publish') }}
                    </button>
                    <button
                      type="button"
                      class="ck-transform-workshop__mini"
                      data-testid="materialize-dbt-model"
                      [disabled]="activeFile().published"
                      [title]="i18n.t('flow.transform.files.materialize.hint')"
                      (click)="toggleMaterializeActiveModel()"
                    >
                      {{
                        i18n.t(
                          activeFile().materialized
                            ? 'flow.transform.files.materialize.off'
                            : 'flow.transform.files.materialize'
                        )
                      }}
                    </button>
                    <button
                      type="button"
                      class="ck-transform-workshop__mini ck-transform-workshop__mini--danger"
                      data-testid="remove-dbt-model"
                      [disabled]="params().models.length <= 1"
                      (click)="removeActiveModel()"
                    >
                      {{ i18n.t('flow.transform.files.remove') }}
                    </button>
                  } @else {
                    <span>{{ i18n.t(activeFile().kind === 'tests' ? 'flow.transform.files.tests.label' : copy().editorLabel) }}</span>
                  }
                  <code>{{ i18n.t(copy().editorEngine) }}</code>
                  <span class="ck-transform-workshop__editor-lines">
                    {{ i18n.t('flow.transform.editor.lines', { count: lineCount() }) }}
                  </span>
                </div>
                <ck-code-editor
                  #editor
                  class="ck-transform-workshop__cm"
                  [language]="activeFile().language"
                  [value]="activeFile().content"
                  [sqlSchema]="transform.editorSchema()"
                  [ariaLabel]="i18n.t(copy().editorAria)"
                  [placeholder]="i18n.t(copy().editorPlaceholder)"
                  (valueChange)="onProgram($event)"
                  (submit)="runPreview()"
                />
              </div>

              @if (transform.dbtReport(); as report) {
                <div class="ck-transform-workshop__build" data-testid="dbt-report">
                  <div class="ck-transform-workshop__build-head">
                    <span [attr.data-ok]="report.tests_failed === 0 ? 'true' : 'false'">
                      <app-icon
                        [name]="report.tests_failed === 0 ? 'check' : 'x-circle'"
                        [size]="12"
                      />
                      {{
                        report.tests_failed === 0
                          ? i18n.t('flow.transform.dbt.build.passed', {
                              models: report.models_total,
                              tests: report.tests_total,
                            })
                          : i18n.t('flow.transform.dbt.build.refused', {
                              count: report.tests_failed,
                            })
                      }}
                    </span>
                    @if (report.selected) {
                      <code>{{ report.selected }}</code>
                    }
                  </div>
                  <ul class="ck-transform-workshop__build-nodes">
                    @for (dbtNode of report.nodes; track dbtNode.kind + dbtNode.name) {
                      <li
                        [attr.data-kind]="dbtNode.kind"
                        [attr.data-ok]="passed(dbtNode) ? 'true' : 'false'"
                        [title]="dbtNode.message || dbtNode.status"
                      >
                        <app-icon
                          [name]="dbtNode.kind === 'test' ? 'shield-check' : 'file-code'"
                          [size]="11"
                        />
                        {{ dbtNode.name }}
                        @if (dbtNode.failures > 0) {
                          <em>
                            {{
                              i18n.t('flow.transform.dbt.build.failures', {
                                count: dbtNode.failures,
                              })
                            }}
                          </em>
                        }
                      </li>
                    }
                  </ul>
                </div>
              }

              <div class="ck-transform-workshop__result">
                @if (transform.busy()) {
                  <ol class="ck-transform-workshop__steps" data-testid="transform-steps">
                    @for (step of phases(); track step.phase) {
                      <li [attr.data-state]="step.state">
                        <app-icon
                          [name]="
                            step.state === 'done'
                              ? 'check'
                              : step.state === 'active'
                                ? 'loader-2'
                                : 'circle'
                          "
                          [size]="11"
                        />
                        {{ i18n.t(step.key) }}
                      </li>
                    }
                  </ol>
                }
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
                    @if (reason.position; as at) {
                      <button
                        type="button"
                        class="ck-transform-workshop__jump"
                        data-testid="jump-to-error"
                        (click)="pointAtError(at)"
                      >
                        <app-icon name="crosshair" [size]="11" />
                        {{
                          i18n.t('flow.transform.error.at_line', {
                            line: at.line,
                            column: at.column
                          })
                        }}
                      </button>
                    }
                  </p>
                } @else if (transform.preview(); as result) {
                  <ck-data-table
                    [columns]="result.schema"
                    [rows]="result.preview"
                    [stats]="result.stats"
                    [rowCount]="result.row_count"
                    maxHeight="100%"
                    [caption]="
                      i18n.t('flow.transform.result.caption', {
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
                            <li [attr.data-kind]="column.kind">
                              <button
                                type="button"
                                data-testid="insert-column"
                                [title]="column.dtype || column.kind"
                                [attr.aria-label]="
                                  i18n.t('flow.transform.sources.insert.aria', {
                                    column: column.name,
                                    view: source.view
                                  })
                                "
                                (click)="insertColumn(source, column.name)"
                              >
                                {{ column.name }}
                              </button>
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

  /** The editor, so a sidebar click and an engine error can both reach it. */
  private readonly editor = viewChild<CodeEditorComponent>('editor');

  protected readonly node = this.store.selectedNode;
  protected readonly engine = computed(() => transformEngineOf(this.node()) ?? 'sql');
  protected readonly descriptor = computed(() => TRANSFORM_ENGINES[this.engine()]);
  protected readonly copy = computed(() => this.descriptor().copy);

  /**
   * The preview as a check-list rather than a word.
   *
   * The wait is short for SQL and long for a first Polars or dbt run, which
   * builds a venv before it runs anything — and that asymmetry is exactly why a
   * single word is not enough: "Running…" for forty seconds reads as a hang,
   * where a ticked "Preparing the environment" reads as a warm-up.
   */
  protected readonly phases = computed(() =>
    transformChecklist(this.engine(), this.transform.phase()),
  );

  protected readonly currentPhase = computed(
    () => this.phases().find((step) => step.state === 'active') ?? null,
  );

  protected readonly params = computed<TransformParams>(() =>
    readTransformParams(this.node(), this.engine()),
  );
  protected readonly files = computed<TransformFile[]>(() =>
    transformFiles(this.params(), this.engine()),
  );
  /** Which file the editor shows; `null` means "the engine's first one". */
  protected readonly activeFileId = signal<string | null>(null);
  /**
   * The file being edited, resolved against the CURRENT file set.
   *
   * Deriving it rather than storing it is what keeps deleting a model safe:
   * the selection follows the tree instead of pointing at a gone file.
   */
  protected readonly activeFile = computed<TransformFile>(() => {
    const files = this.files();
    const requested = this.activeFileId();
    return files.find((file) => file.id === requested) ?? files[0];
  });
  protected readonly activeModelIndex = computed(() =>
    this.engine() === 'dbt' ? modelIndexOf(this.activeFile().id) : null,
  );
  protected readonly activeModelName = computed(() => {
    const index = this.activeModelIndex();
    return index === null ? '' : (this.params().models[index]?.name ?? '');
  });
  protected readonly canAddModel = computed(
    () => this.params().models.length < DBT_MAX_MODELS,
  );
  protected readonly lineCount = computed(() =>
    programLineCount(this.activeFile().content),
  );
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
  private pendingProgramFileId: string | null = null;
  private lastResolvedPins = '';
  private lastNodeId: string | null = null;
  /** The coordinate already jumped to, so an unrelated redraw does not re-jump. */
  private lastPointedError: string | null = null;

  constructor() {
    // The workshop exists FOR the selected transform node; if it stops being
    // one (deletion, undo, external selection change) the dialog closes itself.
    effect(() => {
      if (!isTransformNode(this.node())) this.close.emit();
    });
    // A different node is a different project: the file selection cannot carry
    // over, or `models.3` would open the wrong model of the new node.
    effect(() => {
      const id = this.node()?.id ?? null;
      if (id === this.lastNodeId) return;
      this.lastNodeId = id;
      this.activeFileId.set(null);
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
    // A refusal that names a place goes to that place. The author pressed Test a
    // moment ago, so this is the gesture they were expecting next; leaving them
    // to count lines under "Referenced column not found" is the alternative.
    effect(() => {
      const at = this.transform.failure()?.position;
      const signature = at ? `${at.line}:${at.column}` : null;
      if (signature === this.lastPointedError) return;
      this.lastPointedError = signature;
      if (at) this.editor()?.pointAt(at);
    });
    void this.transform.ensureDatasets();
    this.destroyRef.onDestroy(() => this.flushProgram());
  }

  protected onProgram(program: string): void {
    const id = this.node()?.id;
    if (!id) return;
    this.pendingProgram = program;
    this.pendingProgramNodeId = id;
    this.pendingProgramFileId = this.activeFile().id;
    this.preflight.set(null);
    if (this.programFlushTimer !== null) clearTimeout(this.programFlushTimer);
    this.programFlushTimer = setTimeout(
      () => this.flushProgram(),
      PROGRAM_WRITE_DEBOUNCE_MS,
    );
  }

  /** Land the pending file edit in the store (idempotent). Runs on the
   * debounce tick, before a preview, before any project gesture, and on
   * destroy — so no keystroke is ever lost to the debounce window.
   *
   * The FILE the edit belongs to is captured with it: switching file mid-window
   * must not land the previous model's text in the one just opened. */
  private flushProgram(): void {
    if (this.programFlushTimer !== null) {
      clearTimeout(this.programFlushTimer);
      this.programFlushTimer = null;
    }
    const program = this.pendingProgram;
    const nodeId = this.pendingProgramNodeId;
    const fileId = this.pendingProgramFileId;
    this.pendingProgram = null;
    this.pendingProgramNodeId = null;
    this.pendingProgramFileId = null;
    if (program === null || nodeId === null || fileId === null) return;
    const write = fileWrite(this.params(), this.engine(), fileId, program);
    if (!write) return;
    this.store.updateNodeConfig(nodeId, write.path, write.value);
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

  /** Write a ready-to-run program over one source into the active file. */
  protected useStarter(source: TransformSourceCatalogEntry): void {
    const id = this.node()?.id;
    if (!id) return;
    this.discardPending();
    const target = this.activeFile();
    // `schema.yml` is not a place a starter select belongs; the tests file is
    // skipped in favour of the model this node publishes.
    const fileId =
      target.kind === 'tests'
        ? (this.files().find((file) => file.published)?.id ?? target.id)
        : target.id;
    this.activeFileId.set(fileId);
    const write = fileWrite(
      this.params(),
      this.engine(),
      fileId,
      starterProgramFor(source, this.engine()),
    );
    if (!write) return;
    this.store.updateNodeConfig(id, write.path, write.value);
    this.transform.clearResult();
  }

  /**
   * Put a column name where the caret is, qualified when the query joins.
   *
   * Reading a name off a sidebar and typing it back is transcription, and a
   * mistyped column costs a whole round-trip to the engine to discover. The
   * qualifier is only added when there is more than one source: `region` is
   * what an author writes over one table, and `subscribers.region` is what
   * they have to write over two.
   */
  protected insertColumn(source: TransformSourceCatalogEntry, column: string): void {
    const many = this.transform.sources().length > 1;
    this.editor()?.insertAtCursor(many ? `${source.view}.${column}` : column);
  }

  /** Send the caret to the coordinate the engine complained about. */
  protected pointAtError(position: CodeEditorPosition): void {
    this.editor()?.pointAt(position);
  }

  /** Add a model that already selects from the published one, and open it. */
  protected addModel(): void {
    this.flushProgram();
    const params = this.params();
    if (params.models.length >= DBT_MAX_MODELS) return;
    if (!this.writeProject(addDbtModel(params))) return;
    this.activeFileId.set(`models.${params.models.length}`);
  }

  protected publishActiveModel(): void {
    const name = this.activeModelName();
    if (!name) return;
    this.flushProgram();
    this.writeProject(publishDbtModel(this.params(), name));
  }

  /** Tick or untick the active model as a sibling dataset of the run. */
  protected toggleMaterializeActiveModel(): void {
    const name = this.activeModelName();
    if (!name) return;
    this.flushProgram();
    this.writeProject(toggleDbtMaterialize(this.params(), name));
  }

  protected removeActiveModel(): void {
    const index = this.activeModelIndex();
    if (index === null) return;
    // The pending edit belongs to the file being deleted: writing it back would
    // resurrect the model the author just dropped.
    this.discardPending();
    if (!this.writeProject(removeDbtModel(this.params(), index))) return;
    this.activeFileId.set(null);
  }

  protected onModelName(event: Event): void {
    const index = this.activeModelIndex();
    const input = event.target as HTMLInputElement;
    if (index === null) return;
    // The rename rewrites `params.models` wholesale, so a pending SQL edit on
    // the same array has to land first or it would be overwritten.
    this.flushProgram();
    const patch = renameDbtModel(this.params(), index, input.value);
    if (!this.writeProject(patch)) input.value = this.activeModelName();
  }

  protected passed(node: DbtNodeResult): boolean {
    return dbtNodePassed(node);
  }

  protected async runPreview(): Promise<void> {
    // The dispatch reads the store: the debounced edit must land first, or the
    // preview would run the previous keystroke's program.
    this.flushProgram();
    const params = this.params();
    const engine = this.engine();
    const refusal = preflightTransform(params, engine);
    this.preflight.set(refusal);
    if (refusal) return;
    await this.transform.run(engine, params.program, params.sources, {
      rowLimit: PREVIEW_ROW_LIMIT,
      requirementsText: params.requirements_text,
      timeoutS: params.timeout_s,
      models: params.models,
      testsYml: params.tests_yml,
      outputModel: params.output_model,
    });
  }

  private writeParam(field: string, value: unknown): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeConfig(id, `params.${field}`, value);
  }

  /**
   * Apply a multi-field project patch as ONE store write.
   *
   * A rename touches the models AND the publication; two `updateNodeConfig`
   * calls would be two undo steps for one gesture. Merging into the raw params
   * bag rather than the read one also preserves any key this view model does
   * not know about.
   */
  private writeProject(patch: TransformParamsPatch): boolean {
    const node = this.node();
    if (!node || Object.keys(patch).length === 0) return false;
    const config = (node.config ?? {}) as Record<string, unknown>;
    const raw = config['params'];
    const current =
      raw !== null && typeof raw === 'object' && !Array.isArray(raw)
        ? (raw as Record<string, unknown>)
        : {};
    this.store.updateNodeConfig(node.id, 'params', { ...current, ...patch });
    return true;
  }

  /** Forget the debounced edit without writing it. */
  private discardPending(): void {
    if (this.programFlushTimer !== null) {
      clearTimeout(this.programFlushTimer);
      this.programFlushTimer = null;
    }
    this.pendingProgram = null;
    this.pendingProgramNodeId = null;
    this.pendingProgramFileId = null;
    this.preflight.set(null);
  }
}
