/**
 * `<app-flow-recipe-workshop>` — the full-screen authoring surface of a
 * Python recipe node.
 *
 * Opened from the inspector for the SELECTED recipe node; every edit writes
 * back through the store's dotted-path config writers, so the script and its
 * environment spec are versioned with the flow like any other node config.
 *
 * Left: the Python editor (`ck-code-editor`, CodeMirror in a lazy chunk).
 * Right, three tabs:
 *  - Environment — requirements (one per line, or imported from a local
 *    `requirements.txt` read client-side), registries, timeout, and the live
 *    state of the resolved managed environment (+ "prepare now").
 *  - Inputs/Outputs — the node contract, on the shared schema builder.
 *  - Test — an isolated node run through the existing workbench dispatch,
 *    with the recipe execution's own status timeline, stdout/stderr tails,
 *    output and cooperative cancel.
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
import { firstValueFrom } from 'rxjs';
import { CodeEditorComponent } from '@app/shared/ui/code-editor.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import {
  CanonicalApiService,
  type RecipeExecutionDto,
} from '@app/core/canonical-api.service';
import { FlowStore } from './flow.store';
import { FlowSchemaEditorComponent } from './flow-schema-editor.component';
import {
  FLOW_WORKBENCH_RECIPE_POLL_POLICY,
  FlowWorkbenchService,
} from './flow-workbench.service';
import { parseWorkbenchObject } from './flow-workbench-panel.component';
import { FlowRecipeService } from './flow-recipe.service';
import {
  RECIPE_TIMEOUT_MAX_S,
  clampRecipeTimeout,
  formatBytes,
  isActiveRecipeExecution,
  isPythonRecipeNode,
  previewRequirements,
  readRecipeParams,
  recipeCodeLineCount,
  recipeEnvStatusKey,
  recipeExecutionReason,
  recipeExecutionStatusKey,
  recipeSpecKey,
  recipeTimeline,
  shortFingerprint,
  type RecipeNodeParams,
} from './flow-recipe.vm';

type WorkshopTab = 'env' | 'io' | 'test';

/** Poll cadence for the execution row while a test run is in flight. */
const EXECUTION_POLL_INTERVAL_MS = 1_000;

/** One store write per typing pause. Inspector inputs write per keystroke,
 * but a script session emits hundreds of edits: unbatched they would flood
 * the undo stack (one Ctrl+Z per character) and clone the graph per key. */
const CODE_WRITE_DEBOUNCE_MS = 400;

@Component({
  selector: 'app-flow-recipe-workshop',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, CodeEditorComponent, IconComponent, FlowSchemaEditorComponent],
  styleUrl: './flow-recipe-workshop.component.scss',
  template: `
    <div
      class="ck-recipe-workshop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ck-recipe-workshop-title"
      cdkTrapFocus
      [cdkTrapFocusAutoCapture]="true"
      (keydown.escape)="close.emit()"
    >
      <div class="ck-recipe-workshop__backdrop" (click)="close.emit()"></div>
      <section class="ck-recipe-workshop__panel">
        <header class="ck-recipe-workshop__head">
          <div class="ck-recipe-workshop__identity">
            <span class="ck-recipe-workshop__badge">
              <app-icon name="code-2" [size]="15" />
            </span>
            <div>
              <h2 id="ck-recipe-workshop-title">{{ i18n.t('flow.recipe.workshop.title') }}</h2>
              <p>{{ node()?.label || node()?.id }}</p>
            </div>
          </div>
          <button
            type="button"
            class="ck-recipe-workshop__close"
            (click)="close.emit()"
            [attr.aria-label]="i18n.t('flow.recipe.workshop.close')"
          >
            <app-icon name="x" [size]="16" />
          </button>
        </header>

        @if (node(); as n) {
          <div class="ck-recipe-workshop__body">
            <div class="ck-recipe-workshop__editor">
              <div class="ck-recipe-workshop__editor-head">
                <span>{{ i18n.t('flow.recipe.editor.label') }}</span>
                <code>{{ i18n.t('flow.recipe.editor.contract') }}</code>
                <span class="ck-recipe-workshop__editor-lines">
                  {{ i18n.t('flow.recipe.editor.lines', { count: lineCount() }) }}
                </span>
              </div>
              <ck-code-editor
                class="ck-recipe-workshop__cm"
                language="python"
                [value]="params().code"
                [ariaLabel]="i18n.t('flow.recipe.editor.aria')"
                (valueChange)="onCode($event)"
              />
            </div>

            <aside class="ck-recipe-workshop__side">
              <div
                class="ck-recipe-workshop__tabs"
                role="tablist"
                [attr.aria-label]="i18n.t('flow.recipe.tabs.aria')"
              >
                <button type="button" role="tab" [attr.aria-selected]="tab() === 'env'" (click)="tab.set('env')">
                  <app-icon name="package" [size]="13" /> {{ i18n.t('flow.recipe.tab.env') }}
                </button>
                <button type="button" role="tab" [attr.aria-selected]="tab() === 'io'" (click)="tab.set('io')">
                  <app-icon name="braces" [size]="13" /> {{ i18n.t('flow.recipe.tab.io') }}
                </button>
                <button type="button" role="tab" [attr.aria-selected]="tab() === 'test'" (click)="tab.set('test')">
                  <app-icon name="play" [size]="13" /> {{ i18n.t('flow.recipe.tab.test') }}
                </button>
              </div>

              <div class="ck-recipe-workshop__tabpane">
                @switch (tab()) {
                  @case ('env') {
                    <label class="ck-recipe-workshop__field">
                      <span>{{ i18n.t('flow.recipe.env.requirements') }}</span>
                      <textarea
                        rows="7"
                        spellcheck="false"
                        [value]="params().requirements_text"
                        (change)="onRequirementsChange($event)"
                        [attr.placeholder]="i18n.t('flow.recipe.env.requirements.placeholder')"
                      ></textarea>
                    </label>
                    <div class="ck-recipe-workshop__row">
                      <button type="button" class="ck-recipe-workshop__action" (click)="fileInput.click()">
                        <app-icon name="upload" [size]="13" />
                        {{ i18n.t('flow.recipe.env.import') }}
                      </button>
                      <input
                        #fileInput
                        type="file"
                        accept=".txt,text/plain"
                        class="sr-only"
                        [attr.aria-label]="i18n.t('flow.recipe.env.import.aria')"
                        (change)="onRequirementsFile($event)"
                      />
                      <span class="ck-recipe-workshop__hint">
                        {{ i18n.t('flow.recipe.env.packages', { count: requirementsPreview().lines.length }) }}
                      </span>
                    </div>
                    @if (requirementsPreview().invalid.length > 0) {
                      <p class="ck-recipe-workshop__error" role="alert">
                        {{ i18n.t('flow.recipe.env.invalid_lines', { line: requirementsPreview().invalid[0] }) }}
                      </p>
                    }

                    <label class="ck-recipe-workshop__field">
                      <span>{{ i18n.t('flow.recipe.env.registry') }}</span>
                      <input
                        type="url"
                        spellcheck="false"
                        [value]="params().index_url"
                        (change)="onIndexUrlChange($event)"
                        [attr.placeholder]="i18n.t('flow.recipe.env.registry.placeholder')"
                      />
                    </label>
                    <label class="ck-recipe-workshop__field">
                      <span>{{ i18n.t('flow.recipe.env.extra_registries') }}</span>
                      <textarea
                        rows="2"
                        spellcheck="false"
                        [value]="params().extra_index_urls.join('\n')"
                        (change)="onExtraIndexUrlsChange($event)"
                        [attr.placeholder]="i18n.t('flow.recipe.env.extra_registries.placeholder')"
                      ></textarea>
                    </label>
                    <label class="ck-recipe-workshop__field ck-recipe-workshop__field--inline">
                      <span>{{ i18n.t('flow.recipe.env.timeout') }}</span>
                      <input
                        type="number"
                        min="1"
                        [max]="timeoutMax"
                        [value]="params().timeout_s"
                        (change)="onTimeoutChange($event)"
                      />
                    </label>

                    <div class="ck-recipe-workshop__env-card" [attr.data-status]="recipe.env()?.status ?? 'none'">
                      <div class="ck-recipe-workshop__env-head">
                        <span>{{ i18n.t('flow.recipe.env.state') }}</span>
                        <button
                          type="button"
                          class="ck-recipe-workshop__action"
                          [disabled]="recipe.state() === 'resolving'"
                          (click)="resolveEnv(true)"
                        >
                          <app-icon [name]="recipe.state() === 'resolving' ? 'loader-2' : 'refresh-cw'" [size]="12" />
                          {{ i18n.t('flow.recipe.env.refresh') }}
                        </button>
                      </div>

                      @if (recipe.featureEnabled() === false) {
                        <p class="ck-recipe-workshop__error" role="alert">
                          {{ i18n.t('flow.recipe.env.disabled') }}
                        </p>
                      }
                      @if (envStale()) {
                        <p class="ck-recipe-workshop__hint">{{ i18n.t('flow.recipe.env.stale') }}</p>
                      }

                      @if (recipe.env(); as env) {
                        <div class="ck-recipe-workshop__env-status">
                          <span class="ck-recipe-workshop__chip" [attr.data-status]="env.status">
                            {{ i18n.t(envStatusKey(env.status)) }}
                          </span>
                          <code [title]="env.fingerprint">{{ fingerprint(env.fingerprint) }}</code>
                          <span>Python {{ env.python_version }}</span>
                          @if (env.size_bytes > 0) {
                            <span>{{ bytes(env.size_bytes) }}</span>
                          }
                          @if (env.has_lock) {
                            <span class="ck-recipe-workshop__lock">
                              {{ i18n.t('flow.recipe.env.locked') }}
                            </span>
                          }
                        </div>
                        @if (env.status === 'failed' && env.build_error) {
                          <p class="ck-recipe-workshop__error">{{ env.build_error }}</p>
                        }
                        @if (env.status === 'failed' && env.build_log_tail) {
                          <pre class="ck-recipe-workshop__pre">{{ env.build_log_tail }}</pre>
                        }
                        @if (canPrepare(env.status)) {
                          <button
                            type="button"
                            class="ck-recipe-workshop__action ck-recipe-workshop__action--primary"
                            [disabled]="recipe.preparing() || recipe.featureEnabled() === false"
                            (click)="prepareEnv()"
                          >
                            <app-icon [name]="recipe.preparing() ? 'loader-2' : 'package'" [size]="13" />
                            {{
                              recipe.preparing()
                                ? i18n.t('flow.recipe.env.preparing')
                                : i18n.t('flow.recipe.env.prepare')
                            }}
                          </button>
                        }
                      } @else if (recipe.state() === 'resolving') {
                        <p class="ck-recipe-workshop__hint">{{ i18n.t('flow.recipe.env.resolving') }}</p>
                      } @else if (recipe.error(); as envError) {
                        <p class="ck-recipe-workshop__error" role="alert">{{ envError }}</p>
                      }
                    </div>
                  }

                  @case ('io') {
                    <p class="ck-recipe-workshop__hint">{{ i18n.t('flow.recipe.io.hint') }}</p>
                    <app-flow-schema-editor
                      configKey="input_schema"
                      [label]="i18n.t('flow.recipe.io.input.label')"
                      deriveFrom="inputs"
                      [hint]="i18n.t('flow.recipe.io.input.hint')"
                      [fallbackHint]="i18n.t('flow.recipe.io.input.fallback')"
                    />
                    <app-flow-schema-editor
                      configKey="output_schema"
                      [label]="i18n.t('flow.recipe.io.output.label')"
                      deriveFrom="outputs"
                      [hint]="i18n.t('flow.recipe.io.output.hint')"
                      [fallbackHint]="i18n.t('flow.recipe.io.output.fallback')"
                    />
                  }

                  @case ('test') {
                    @if (!workbench.systemId()) {
                      <p class="ck-recipe-workshop__hint">{{ i18n.t('flow.recipe.test.no_system') }}</p>
                    } @else {
                      <label class="ck-recipe-workshop__consent">
                        <input
                          type="checkbox"
                          [checked]="consent()"
                          (change)="onConsentChange($event)"
                        />
                        <span>{{ i18n.t('flow.workbench.consent') }}</span>
                      </label>
                      <label class="ck-recipe-workshop__field">
                        <span>{{ i18n.t('flow.recipe.test.input') }}</span>
                        <textarea
                          rows="5"
                          spellcheck="false"
                          [value]="testInputText()"
                          (input)="testInputText.set(textValue($event))"
                        ></textarea>
                      </label>
                      <div class="ck-recipe-workshop__row">
                        <button
                          type="button"
                          class="ck-recipe-workshop__action ck-recipe-workshop__action--primary"
                          [disabled]="testBusy() || workbench.busy()"
                          (click)="runTest()"
                        >
                          <app-icon [name]="testBusy() ? 'loader-2' : 'play'" [size]="13" />
                          {{ testBusy() ? i18n.t('flow.recipe.test.busy') : i18n.t('flow.recipe.test.run') }}
                        </button>
                        @if (execution(); as exec) {
                          @if (cancellable(exec)) {
                            <button
                              type="button"
                              class="ck-recipe-workshop__action ck-recipe-workshop__action--danger"
                              [disabled]="cancelBusy()"
                              (click)="cancelTest()"
                            >
                              <app-icon [name]="cancelBusy() ? 'loader-2' : 'square'" [size]="13" />
                              {{ i18n.t('flow.recipe.test.cancel') }}
                            </button>
                          }
                        }
                      </div>

                      @if (execution(); as exec) {
                        <ol class="ck-recipe-workshop__timeline" aria-live="polite">
                          @for (step of timeline(exec.status); track step.status) {
                            <li [attr.data-state]="step.state">
                              {{ i18n.t(executionStatusKey(step.status)) }}
                            </li>
                          }
                          @if (!isActive(exec.status)) {
                            <li data-state="terminal" [attr.data-status]="exec.status">
                              {{ i18n.t(executionStatusKey(exec.status)) }}
                            </li>
                          }
                        </ol>
                        @if (exec.cancel_requested && isActive(exec.status)) {
                          <p class="ck-recipe-workshop__hint">{{ i18n.t('flow.recipe.test.cancel_requested') }}</p>
                        }
                        @if (executionReason(); as reason) {
                          <p class="ck-recipe-workshop__error" role="alert">
                            {{ i18n.t(reason.key, reason.params) }}
                            @if (reason.detail) {
                              <code class="ck-recipe-workshop__reason-detail">{{ reason.detail }}</code>
                            }
                          </p>
                        }
                        @if (exec.output_json) {
                          <span class="ck-recipe-workshop__stream-label">{{ i18n.t('flow.recipe.test.output') }}</span>
                          <pre class="ck-recipe-workshop__pre">{{ json(exec.output_json) }}</pre>
                        }
                        @if (exec.stdout_tail) {
                          <span class="ck-recipe-workshop__stream-label">stdout</span>
                          <pre class="ck-recipe-workshop__pre">{{ exec.stdout_tail }}</pre>
                        }
                        @if (exec.stderr_tail) {
                          <span class="ck-recipe-workshop__stream-label">stderr</span>
                          <pre class="ck-recipe-workshop__pre ck-recipe-workshop__pre--stderr">{{ exec.stderr_tail }}</pre>
                        }
                        @if (exec.duration_ms !== null && !isActive(exec.status)) {
                          <p class="ck-recipe-workshop__hint">
                            {{ i18n.t('flow.recipe.test.duration', { seconds: durationSeconds(exec) }) }}
                          </p>
                        }
                      } @else if (testBusy()) {
                        <p class="ck-recipe-workshop__hint">{{ i18n.t('flow.recipe.test.dispatching') }}</p>
                      }

                      @if (testError() || workbench.error(); as message) {
                        <p class="ck-recipe-workshop__error" role="alert">{{ testError() || message }}</p>
                      }
                    }
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
export class FlowRecipeWorkshopComponent {
  protected readonly store = inject(FlowStore);
  protected readonly workbench = inject(FlowWorkbenchService);
  protected readonly recipe = inject(FlowRecipeService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly i18n = inject(I18nService);

  readonly close = output<void>();

  protected readonly node = this.store.selectedNode;
  protected readonly params = computed<RecipeNodeParams>(() => readRecipeParams(this.node()));
  protected readonly lineCount = computed(() => recipeCodeLineCount(this.params().code));
  protected readonly requirementsPreview = computed(() =>
    previewRequirements(this.params().requirements_text),
  );
  /** True when the spec on the node moved past the env row being displayed. */
  protected readonly envStale = computed(() => {
    const resolved = this.recipe.resolvedKey();
    return resolved !== null && resolved !== recipeSpecKey(this.params());
  });

  protected readonly tab = signal<WorkshopTab>('env');
  protected readonly consent = signal(false);
  protected readonly testInputText = signal('{}');
  protected readonly testBusy = signal(false);
  protected readonly cancelBusy = signal(false);
  protected readonly testError = signal<string | null>(null);
  protected readonly execution = signal<RecipeExecutionDto | null>(null);
  /** Machine failure code of the settled execution, projected for i18n. */
  protected readonly executionReason = computed(() => {
    const error = this.execution()?.error;
    return error ? recipeExecutionReason(error) : null;
  });

  protected readonly timeoutMax = RECIPE_TIMEOUT_MAX_S;
  protected readonly fingerprint = shortFingerprint;
  protected readonly bytes = formatBytes;
  protected readonly envStatusKey = recipeEnvStatusKey;
  protected readonly executionStatusKey = recipeExecutionStatusKey;
  protected readonly timeline = recipeTimeline;
  protected readonly isActive = isActiveRecipeExecution;

  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pollBusy = false;
  private codeFlushTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingCode: string | null = null;
  private pendingCodeNodeId: string | null = null;

  constructor() {
    // The workshop exists FOR the selected recipe node; if it stops being one
    // (deletion, undo, external selection change) the dialog closes itself.
    effect(() => {
      if (!isPythonRecipeNode(this.node())) this.close.emit();
    });
    void this.resolveEnv(false);
    this.destroyRef.onDestroy(() => {
      this.flushCode();
      this.stopExecutionPolling();
    });
  }

  protected textValue(event: Event): string {
    return (event.target as HTMLTextAreaElement).value;
  }

  protected onConsentChange(event: Event): void {
    this.consent.set((event.target as HTMLInputElement).checked);
    this.testError.set(null);
  }

  protected onCode(code: string): void {
    const id = this.node()?.id;
    if (!id) return;
    this.pendingCode = code;
    this.pendingCodeNodeId = id;
    if (this.codeFlushTimer !== null) clearTimeout(this.codeFlushTimer);
    this.codeFlushTimer = setTimeout(() => this.flushCode(), CODE_WRITE_DEBOUNCE_MS);
  }

  /** Land the pending script edit in the store (idempotent). Runs on the
   * debounce tick, before a test dispatch, and on destroy — so no keystroke
   * is ever lost to the debounce window. */
  private flushCode(): void {
    if (this.codeFlushTimer !== null) {
      clearTimeout(this.codeFlushTimer);
      this.codeFlushTimer = null;
    }
    if (this.pendingCode === null || this.pendingCodeNodeId === null) return;
    const code = this.pendingCode;
    const nodeId = this.pendingCodeNodeId;
    this.pendingCode = null;
    this.pendingCodeNodeId = null;
    this.store.updateNodeConfig(nodeId, 'params.code', code);
  }

  protected onRequirementsChange(event: Event): void {
    this.writeParam('requirements_text', (event.target as HTMLTextAreaElement).value);
    void this.resolveEnv(true);
  }

  protected async onRequirementsFile(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    // Read client-side: the file never leaves the browser — its content
    // becomes the node's versioned requirements text.
    const text = await file.text();
    this.writeParam('requirements_text', text);
    void this.resolveEnv(true);
  }

  protected onIndexUrlChange(event: Event): void {
    this.writeParam('index_url', (event.target as HTMLInputElement).value.trim());
    void this.resolveEnv(true);
  }

  protected onExtraIndexUrlsChange(event: Event): void {
    const urls = (event.target as HTMLTextAreaElement).value
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    this.writeParam('extra_index_urls', urls);
    void this.resolveEnv(true);
  }

  protected onTimeoutChange(event: Event): void {
    this.writeParam('timeout_s', clampRecipeTimeout((event.target as HTMLInputElement).value));
  }

  protected canPrepare(status: string): boolean {
    return status === 'pending' || status === 'failed' || status === 'evicted';
  }

  protected async resolveEnv(force: boolean): Promise<void> {
    const preview = this.requirementsPreview();
    if (preview.invalid.length > 0 || preview.tooMany) return;
    await this.recipe.ensureResolved(this.params(), force);
  }

  protected async prepareEnv(): Promise<void> {
    await this.recipe.prepare();
  }

  protected cancellable(execution: RecipeExecutionDto): boolean {
    return isActiveRecipeExecution(execution.status) && !execution.cancel_requested;
  }

  protected durationSeconds(execution: RecipeExecutionDto): string {
    return ((execution.duration_ms ?? 0) / 1000).toFixed(1);
  }

  protected async runTest(): Promise<void> {
    const node = this.node();
    if (!node || this.testBusy() || this.workbench.busy()) return;
    // The dispatch snapshots the store: the debounced script edit must land
    // first, or the test would execute the previous keystroke's code.
    this.flushCode();
    const parsed = parseWorkbenchObject(this.testInputText());
    if (!parsed.ok) {
      this.testError.set(this.i18n.t(parsed.messageKey, parsed.params));
      return;
    }
    if (!this.consent()) {
      this.testError.set(this.i18n.t('flow.workbench.error.consent'));
      return;
    }
    this.testError.set(null);
    this.execution.set(null);
    this.testBusy.set(true);
    this.startExecutionPolling();
    try {
      // The workbench owns dispatch, hash fencing and run polling; this
      // component follows the recipe execution row for the finer statuses.
      await this.workbench.runSelectedNode(
        node.id,
        parsed.value,
        true,
        FLOW_WORKBENCH_RECIPE_POLL_POLICY,
      );
    } finally {
      await this.refreshExecution();
      this.stopExecutionPolling();
      this.testBusy.set(false);
    }
  }

  protected async cancelTest(): Promise<void> {
    const execution = this.execution();
    if (!execution || !this.cancellable(execution) || this.cancelBusy()) return;
    this.cancelBusy.set(true);
    try {
      this.execution.set(
        await firstValueFrom(this.canonical.cancelRecipeExecution(execution.id)),
      );
    } catch (error: unknown) {
      this.testError.set(this.recipe.errorMessage(error));
    } finally {
      this.cancelBusy.set(false);
    }
  }

  protected json(value: unknown): string {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return this.i18n.t('flow.workbench.error.unserialisable');
    }
  }

  private writeParam(field: keyof RecipeNodeParams, value: unknown): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeConfig(id, `params.${field}`, value);
  }

  private startExecutionPolling(): void {
    this.stopExecutionPolling();
    this.pollTimer = setInterval(() => void this.refreshExecution(), EXECUTION_POLL_INTERVAL_MS);
  }

  private stopExecutionPolling(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  /** Locate (by the dispatched run id) then follow the execution row. */
  private async refreshExecution(): Promise<void> {
    if (this.pollBusy) return;
    const runId = this.workbench.nodeResult()?.run.id ?? null;
    if (!runId) return;
    this.pollBusy = true;
    try {
      const current = this.execution();
      if (current && current.run_id === runId) {
        this.execution.set(
          await firstValueFrom(this.canonical.getRecipeExecution(current.id)),
        );
      } else {
        const rows = await firstValueFrom(
          this.canonical.listRecipeExecutions({ run_id: runId, limit: 1 }),
        );
        if (rows.length > 0) this.execution.set(rows[0]);
      }
    } catch {
      // Transient read fault — the next tick retries; the run poller is the
      // authoritative completion signal either way.
    } finally {
      this.pollBusy = false;
    }
  }
}
