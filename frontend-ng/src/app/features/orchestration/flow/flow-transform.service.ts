/**
 * `FlowTransformService` — the SQL workshop's window onto the data plane.
 *
 * One instance per builder shell, next to the other flow services. It owns two
 * reads and nothing else:
 *
 *  - **the pin catalog** — the ready datasets of the workspace, so the author
 *    picks an input instead of typing a slug;
 *  - **`/datasets/sql-preview`** — the statement run against those inputs
 *    WITHOUT persisting anything, which answers with the same profile shape the
 *    dataset pages render plus the source catalog the editor completes from.
 *
 * The server is the authority on what a transform may do: refusals arrive as
 * `{code, message}` and are handed to `transformFailure()` for translation. The
 * service never validates SQL itself and never mutates the graph.
 */
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import type { TabularColumn, TabularColumnStats, TabularRow } from '@app/shared/ui/data-table.vm';
import { DataService, type DatasetDto } from '@app/features/data/data.service';
import {
  editorSqlSchema,
  transformFailure,
  type SqlTransformSourcePin,
  type TransformFailure,
  type TransformSourceCatalogEntry,
} from './flow-transform.vm';

/** What `/datasets/sql-preview` returns for a statement that ran. */
export interface SqlPreviewResult {
  row_count: number;
  column_count: number;
  schema: TabularColumn[];
  preview: TabularRow[];
  stats: Record<string, TabularColumnStats>;
  duration_ms: number;
  sources: TransformSourceCatalogEntry[];
}

interface SqlPreviewResponse {
  preview: SqlPreviewResult | null;
  sources: TransformSourceCatalogEntry[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

@Injectable()
export class FlowTransformService {
  private readonly http = inject(HttpClient);
  private readonly data = inject(DataService);
  private readonly destroyRef = inject(DestroyRef);

  /** Tables the statement can address, as the server resolved them. */
  readonly sources = signal<TransformSourceCatalogEntry[]>([]);
  readonly preview = signal<SqlPreviewResult | null>(null);
  readonly failure = signal<TransformFailure | null>(null);
  readonly busy = signal(false);
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
  async resolveSources(pins: readonly SqlTransformSourcePin[]): Promise<void> {
    if (pins.length === 0) {
      this.sources.set([]);
      return;
    }
    try {
      const response = await this.post({ sql: '', sources: pins, row_limit: 1 });
      if (this.disposed) return;
      this.sources.set(response.sources ?? []);
      this.failure.set(null);
    } catch (error: unknown) {
      if (this.disposed) return;
      this.sources.set([]);
      this.failure.set(this.toFailure(error));
    }
  }

  /** Run the statement for real (still without persisting): the Test button. */
  async run(
    sql: string,
    pins: readonly SqlTransformSourcePin[],
    rowLimit = 50,
  ): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.failure.set(null);
    try {
      const response = await this.post({ sql, sources: pins, row_limit: rowLimit });
      if (this.disposed) return;
      this.preview.set(response.preview);
      if (response.sources?.length) this.sources.set(response.sources);
    } catch (error: unknown) {
      if (this.disposed) return;
      this.preview.set(null);
      this.failure.set(this.toFailure(error));
    } finally {
      this.busy.set(false);
    }
  }

  /** Drop the last result — the statement changed, so it no longer describes it. */
  clearResult(): void {
    this.preview.set(null);
    this.failure.set(null);
  }

  private post(body: {
    sql: string;
    sources: readonly SqlTransformSourcePin[];
    row_limit: number;
  }): Promise<SqlPreviewResponse> {
    return firstValueFrom(
      this.http.post<SqlPreviewResponse>('/api/v1/datasets/sql-preview', {
        sql: body.sql,
        // The API forbids unknown keys, so only the three pin fields travel.
        sources: body.sources.map((pin) => ({
          ...(pin.view ? { view: pin.view } : {}),
          ...(pin.dataset_id ? { dataset_id: pin.dataset_id } : {}),
          ...(pin.dataset_slug ? { dataset_slug: pin.dataset_slug } : {}),
        })),
        row_limit: body.row_limit,
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
