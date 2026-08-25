/**
 * `FlowTransformService` — the transform workshop's window onto the data plane.
 *
 * One instance per builder shell, next to the other flow services. It owns the
 * reads the workshop needs and nothing else:
 *
 *  - **the pin catalog** — the ready datasets of the workspace, so the author
 *    picks an input instead of typing a slug;
 *  - **the preview** — the authored program run against those inputs WITHOUT
 *    persisting anything, answering with the same profile shape the dataset
 *    pages render plus the source catalog the editor completes from.
 *
 * The engines differ only in transport, and that difference is a property of
 * the platform rather than a choice:
 *
 *  - **SQL** is answered inline by `/datasets/sql-preview` — duckdb runs in the
 *    API process for the length of one statement.
 *  - **Polars and dbt** cannot be: author-written Python, and the Jinja plus
 *    adapter macros of a dbt project, only ever run on a managed venv
 *    interpreter, in the worker container that mounts the venv store. So
 *    `/datasets/polars-preview` and `/datasets/dbt-preview` hand back a
 *    `RecipeExecution` row and this service follows it to terminal, surfacing
 *    `env_building` on the way — the first run in a workspace pays for the
 *    environment, and the author should see that rather than a mute spinner.
 *
 * A dbt row carries one thing a Polars row does not: the build verdict, on
 * success AND on refusal. `dbtReport` is therefore populated from a failed row
 * too — "which test refused how many rows" is the answer, not the absence of
 * one.
 *
 * The server is the authority on what a transform may do: refusals arrive as
 * `{code, message}` (inline) or as `"CODE: detail"` on the row (queued) and are
 * handed to `transformFailure*()` for translation. The service never validates
 * a program itself and never mutates the graph.
 */
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import type { TabularColumn, TabularColumnStats, TabularRow } from '@app/shared/ui/data-table.vm';
import {
  CanonicalApiService,
  type RecipeExecutionDto,
} from '@app/core/canonical-api.service';
import { DataService, type DatasetDto } from '@app/features/data/data.service';
import {
  dbtReportFrom,
  editorSqlSchema,
  transformFailure,
  transformFailureFromExecution,
  type DbtReport,
  type TransformEngine,
  type TransformFailure,
  type TransformModel,
  type TransformSourceCatalogEntry,
  type TransformSourcePin,
} from './flow-transform.vm';

/** What a settled preview describes, whatever engine produced it. */
export interface TransformPreviewResult {
  row_count: number;
  column_count: number;
  schema: TabularColumn[];
  preview: TabularRow[];
  stats: Record<string, TabularColumnStats>;
  duration_ms: number;
  sources: TransformSourceCatalogEntry[];
}

interface SqlPreviewResponse {
  preview: TransformPreviewResult | null;
  sources: TransformSourceCatalogEntry[];
}

/** Both queued engines answer with a row to follow, not with a result. */
interface QueuedPreviewResponse {
  execution: RecipeExecutionDto | null;
  sources: TransformSourceCatalogEntry[];
}

/** Everything a transform run needs beyond its program and its pins. */
export interface TransformRunOptions {
  rowLimit?: number;
  requirementsText?: string;
  timeoutS?: number;
  /** dbt only: the project, its tests and the model it publishes. */
  models?: readonly TransformModel[];
  testsYml?: string;
  outputModel?: string;
}

/** Poll cadence while a queued preview settles. */
const EXECUTION_POLL_MS = 900;
/** Give up following a row after this long; the worker's own limits are hard. */
const EXECUTION_POLL_TIMEOUT_MS = 15 * 60 * 1000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

@Injectable()
export class FlowTransformService {
  private readonly http = inject(HttpClient);
  private readonly canonical = inject(CanonicalApiService);
  private readonly data = inject(DataService);
  private readonly destroyRef = inject(DestroyRef);

  /** Tables the program can address, as the server resolved them. */
  readonly sources = signal<TransformSourceCatalogEntry[]>([]);
  readonly preview = signal<TransformPreviewResult | null>(null);
  readonly failure = signal<TransformFailure | null>(null);
  readonly busy = signal(false);
  /** Lifecycle of a queued run: `queued | env_building | running` while busy. */
  readonly phase = signal<string | null>(null);
  /** What the author printed. A Python transform is debugged by its prints. */
  readonly stdout = signal<string>('');
  /** The row a queued run is following, so the author can cancel it. */
  readonly execution = signal<RecipeExecutionDto | null>(null);
  /** dbt only: which models built and which tests passed, pass or fail. */
  readonly dbtReport = signal<DbtReport | null>(null);
  /** Ready datasets available for pinning; loaded once per builder shell. */
  readonly datasets = signal<DatasetDto[]>([]);
  readonly datasetsLoading = signal(false);

  /** Completion schema for `<ck-code-editor language="sql">`. */
  readonly editorSchema = computed(() => editorSqlSchema(this.sources()));

  private catalogLoaded = false;
  private disposed = false;

  constructor() {
    this.destroyRef.onDestroy(() => {
      this.disposed = true;
    });
  }

  /** Load the pinnable datasets once (ready rows only: a pin must be usable). */
  async ensureDatasets(force = false): Promise<void> {
    if (this.catalogLoaded && !force) return;
    this.catalogLoaded = true;
    this.datasetsLoading.set(true);
    try {
      const rows = await this.data.refresh();
      if (this.disposed) return;
      this.datasets.set(rows.filter((row) => row.status === 'ready'));
    } catch {
      // The picker degrades to "no dataset available"; the workshop stays
      // usable for an author who wires the input from an upstream node.
      this.catalogLoaded = false;
    } finally {
      this.datasetsLoading.set(false);
    }
  }

  /**
   * Resolve the source catalog without running anything — what the editor needs
   * to complete against as soon as the workshop opens or a pin changes.
   */
  async resolveSources(
    engine: TransformEngine,
    pins: readonly TransformSourcePin[],
  ): Promise<void> {
    if (pins.length === 0) {
      this.sources.set([]);
      return;
    }
    try {
      // An empty program resolves the catalog without running anything, on
      // every engine: that is the contract the three preview endpoints share.
      const sources =
        engine === 'polars'
          ? (await this.postPolars({ code: '', sources: pins, row_limit: 1 })).sources
          : engine === 'dbt'
            ? (await this.postDbt({ models: [], sources: pins, row_limit: 1 })).sources
            : (await this.postSql({ sql: '', sources: pins, row_limit: 1 })).sources;
      if (this.disposed) return;
      this.sources.set(sources ?? []);
      this.failure.set(null);
    } catch (error: unknown) {
      if (this.disposed) return;
      this.sources.set([]);
      this.failure.set(this.toFailure(error));
    }
  }

  /** Run the program for real (still without persisting): the Test button. */
  async run(
    engine: TransformEngine,
    program: string,
    pins: readonly TransformSourcePin[],
    options: TransformRunOptions = {},
  ): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.failure.set(null);
    this.stdout.set('');
    this.execution.set(null);
    this.dbtReport.set(null);
    this.phase.set('queued');
    try {
      if (engine === 'polars') {
        await this.runQueued(
          () =>
            this.postPolars({
              code: program,
              sources: pins,
              row_limit: options.rowLimit ?? 50,
              requirements_text: options.requirementsText ?? '',
              timeout_s: options.timeoutS,
            }),
          'POLARS_CANCELLED',
        );
      } else if (engine === 'dbt') {
        await this.runQueued(
          () =>
            this.postDbt({
              models: options.models ?? [],
              tests_yml: options.testsYml ?? '',
              output_model: options.outputModel ?? '',
              sources: pins,
              row_limit: options.rowLimit ?? 50,
              requirements_text: options.requirementsText ?? '',
              timeout_s: options.timeoutS,
            }),
          'DBT_CANCELLED',
        );
      } else {
        const response = await this.postSql({
          sql: program,
          sources: pins,
          row_limit: options.rowLimit ?? 50,
        });
        if (this.disposed) return;
        this.preview.set(response.preview);
        if (response.sources?.length) this.sources.set(response.sources);
      }
    } catch (error: unknown) {
      if (this.disposed) return;
      this.preview.set(null);
      this.failure.set(this.toFailure(error));
    } finally {
      this.busy.set(false);
      this.phase.set(null);
    }
  }

  /** Ask the worker to stop a queued run (cooperative, like a recipe test). */
  async cancel(): Promise<void> {
    const row = this.execution();
    if (!row || row.cancel_requested) return;
    try {
      this.execution.set(await firstValueFrom(this.canonical.cancelRecipeExecution(row.id)));
    } catch {
      // The poll loop is authoritative: it will report the terminal status.
    }
  }

  /** Drop the last result — the program changed, so it no longer describes it. */
  clearResult(): void {
    this.preview.set(null);
    this.failure.set(null);
    this.stdout.set('');
    this.execution.set(null);
    this.dbtReport.set(null);
  }

  /**
   * Dispatch a queued preview and follow its row to terminal.
   *
   * The row IS the answer: `output_json` carries the profile on success, and
   * `error` carries `"CODE: detail"` on refusal. Nothing is persisted either
   * way — the worker profiles the frame instead of registering it. A dbt build
   * that broke or failed its tests still writes a verdict on `output_json`, so
   * the report is read on both paths.
   */
  private async runQueued(
    dispatch: () => Promise<QueuedPreviewResponse>,
    cancelledCode: string,
  ): Promise<void> {
    const response = await dispatch();
    if (this.disposed) return;
    if (response.sources?.length) this.sources.set(response.sources);
    if (!response.execution) {
      this.preview.set(null);
      return;
    }
    const settled = await this.follow(response.execution);
    if (this.disposed || !settled) return;
    this.stdout.set(settled.stdout_tail ?? '');
    this.dbtReport.set(dbtReportFrom(settled.output_json));
    if (settled.status !== 'succeeded') {
      this.preview.set(null);
      this.failure.set(
        settled.status === 'cancelled'
          ? { key: `flow.transform.error.${cancelledCode}` }
          : transformFailureFromExecution(settled.error),
      );
      return;
    }
    const output = settled.output_json;
    if (!isRecord(output)) {
      this.preview.set(null);
      this.failure.set({ key: 'flow.transform.error.unknown' });
      return;
    }
    this.preview.set(output as unknown as TransformPreviewResult);
    const sources = output['sources'];
    if (Array.isArray(sources) && sources.length) {
      this.sources.set(sources as TransformSourceCatalogEntry[]);
    }
  }

  /** Poll one execution row until terminal (or until the shell goes away). */
  private async follow(row: RecipeExecutionDto): Promise<RecipeExecutionDto | null> {
    let current = row;
    const giveUpAt = Date.now() + EXECUTION_POLL_TIMEOUT_MS;
    this.execution.set(current);
    this.phase.set(current.status);
    while (!this.isTerminal(current.status)) {
      if (this.disposed) return null;
      if (Date.now() > giveUpAt) {
        void this.cancel();
        throw new Error('transform_preview_deadline');
      }
      await sleep(EXECUTION_POLL_MS);
      if (this.disposed) return null;
      current = await firstValueFrom(this.canonical.getRecipeExecution(current.id));
      this.execution.set(current);
      this.phase.set(current.status);
    }
    return current;
  }

  private isTerminal(status: string): boolean {
    return ['succeeded', 'failed', 'cancelled', 'timed_out'].includes(status);
  }

  /** The API forbids unknown keys, so only the three pin fields travel. */
  private pinBody(
    pins: readonly TransformSourcePin[],
  ): Array<Record<string, string>> {
    return pins.map((pin) => ({
      ...(pin.view ? { view: pin.view } : {}),
      ...(pin.dataset_id ? { dataset_id: pin.dataset_id } : {}),
      ...(pin.dataset_slug ? { dataset_slug: pin.dataset_slug } : {}),
    }));
  }

  private postSql(body: {
    sql: string;
    sources: readonly TransformSourcePin[];
    row_limit: number;
  }): Promise<SqlPreviewResponse> {
    return firstValueFrom(
      this.http.post<SqlPreviewResponse>('/api/v1/datasets/sql-preview', {
        sql: body.sql,
        sources: this.pinBody(body.sources),
        row_limit: body.row_limit,
      }),
    );
  }

  private postPolars(body: {
    code: string;
    sources: readonly TransformSourcePin[];
    row_limit: number;
    requirements_text?: string;
    timeout_s?: number;
  }): Promise<QueuedPreviewResponse> {
    return firstValueFrom(
      this.http.post<QueuedPreviewResponse>('/api/v1/datasets/polars-preview', {
        code: body.code,
        sources: this.pinBody(body.sources),
        row_limit: body.row_limit,
        requirements_text: body.requirements_text ?? '',
        ...(body.timeout_s ? { timeout_s: body.timeout_s } : {}),
      }),
    );
  }

  private postDbt(body: {
    models: readonly TransformModel[];
    sources: readonly TransformSourcePin[];
    row_limit: number;
    tests_yml?: string;
    output_model?: string;
    requirements_text?: string;
    timeout_s?: number;
  }): Promise<QueuedPreviewResponse> {
    return firstValueFrom(
      this.http.post<QueuedPreviewResponse>('/api/v1/datasets/dbt-preview', {
        models: body.models.map((model) => ({ name: model.name, sql: model.sql })),
        tests_yml: body.tests_yml ?? '',
        output_model: body.output_model ?? '',
        sources: this.pinBody(body.sources),
        row_limit: body.row_limit,
        requirements_text: body.requirements_text ?? '',
        ...(body.timeout_s ? { timeout_s: body.timeout_s } : {}),
      }),
    );
  }

  /** Turn a transport or business error into a translatable failure. */
  private toFailure(error: unknown): TransformFailure {
    if (error instanceof HttpErrorResponse) {
      const detail = isRecord(error.error) ? error.error['detail'] : null;
      if (isRecord(detail)) {
        return transformFailure(
          typeof detail['code'] === 'string' ? detail['code'] : null,
          typeof detail['message'] === 'string' ? detail['message'] : null,
        );
      }
      return transformFailure(null, typeof detail === 'string' ? detail : error.message);
    }
    return transformFailure(null, error instanceof Error ? error.message : null);
  }
}
