/** Explicit, bounded reading of the dataset retained by one authorized call.
 * A slug/latest lookup cannot establish which rows an old execution returned.
 */
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { AuthStore, type AuthenticationRequestScope } from '@app/store/auth.store';
import type { FlowObservationRun, FlowObservedAttempt } from './flow-observation.vm';
import type { FlowResultDatasetPreview } from './flow-result.vm';

export interface FlowObservationDatasetSelection {
  run: FlowObservationRun;
  nodeId: string;
  attempt: FlowObservedAttempt | null;
}
export interface FlowObservationDatasetReference { datasetId: string; version: number | null; }
export type FlowObservationDatasetError = 'forbidden' | 'missing' | 'not-ready' | 'identity-mismatch' | 'invalid-response' | 'unavailable' | null;
export type FlowObservationDatasetUnavailable = 'held' | 'missing' | 'not-pinned' | 'not-referenced' | null;
interface SelectedDataset extends FlowObservationDatasetReference {
  runId: string;
  nodeId: string;
  attemptId: string;
}
interface ReadContext {
  selection: SelectedDataset;
  generation: number;
  controller: AbortController;
  workspace: WorkspaceRequestScope;
  principal: AuthenticationRequestScope;
}
class DatasetReadError extends Error {
  constructor(readonly reason: Exclude<FlowObservationDatasetError, null>) { super(reason); }
}
const PAGE_LIMIT = 50;
const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
const text = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() && value.length <= 160 ? value.trim() : null;
const integer = (value: unknown): number | null =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;

/** Only explicit native dataset envelopes; never a guessed id or a model id. */
export function flowObservationDatasetReference(value: unknown): FlowObservationDatasetReference | null {
  const output = record(value);
  if (!output) return null;
  const nested = record(output['dataset']);
  const topId = text(output['dataset_id']);
  const nestedId = text(nested?.['dataset_id']) ?? text(nested?.['id']);
  if (topId && nestedId && topId !== nestedId) return null;
  const datasetId = topId ?? nestedId;
  if (!datasetId) return null;
  const declared = [output['dataset_version'], nested?.['version'], topId && !nested ? output['version'] : undefined]
    .filter(value => value != null);
  const versions = declared.map(integer);
  if (versions.some(value => value === null || value < 1) || new Set(versions).size > 1) return null;
  const version = versions[0] ?? null;
  return { datasetId, version };
}

@Injectable()
export class FlowObservationDatasetService {
  private readonly transport = inject(WorkspaceFetchService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly destroyRef = inject(DestroyRef);
  private readonly selected = signal<SelectedDataset | null>(null);
  readonly available = computed(() => this.selected() !== null);
  readonly reference = computed<FlowObservationDatasetReference | null>(() => {
    const selected = this.selected();
    return selected ? { datasetId: selected.datasetId, version: selected.version } : null;
  });
  readonly unavailableReason = signal<FlowObservationDatasetUnavailable>('missing');
  readonly preview = signal<FlowResultDatasetPreview | null>(null);
  readonly status = signal<'idle' | 'loading' | 'ready' | 'error'>('idle');
  readonly error = signal<FlowObservationDatasetError>(null);
  private generation = 0;
  private controller: AbortController | null = null;
  private disposed = false;

  constructor() {
    const resetWorkspace = this.workspace.registerContextReset(() => this.setSelection(null));
    const resetPrincipal = this.auth.registerContextReset(() => this.setSelection(null));
    this.destroyRef.onDestroy(() => {
      this.invalidate(); this.disposed = true;
      this.selected.set(null); this.preview.set(null);
      resetWorkspace(); resetPrincipal();
    });
  }

  setSelection(value: FlowObservationDatasetSelection | null): void {
    if (this.disposed) return;
    const attempt = value?.attempt;
    const recorded = value?.run.skill_invocations?.find(call => call.id === attempt?.id);
    let selected: SelectedDataset | null = null;
    let reason: FlowObservationDatasetUnavailable = 'missing';
    if (value?.run.result_held || attempt?.outputState === 'held') reason = 'held';
    else if (value && attempt && attempt.outputState === 'available' && text(value.run.id)
      && text(value.nodeId) && text(attempt.id) && attempt.nodeId === value.nodeId
      && recorded && record(recorded.trace)?.['node_id'] === value.nodeId) {
      const reference = flowObservationDatasetReference(attempt.output);
      const retained = flowObservationDatasetReference(recorded.output_ref);
      if (reference && retained && reference.datasetId === retained.datasetId && reference.version === retained.version) {
        selected = { ...reference, runId: value.run.id, nodeId: value.nodeId, attemptId: attempt.id };
        reason = null;
      } else {
        const output = record(attempt.output);
        const nested = record(output?.['dataset']);
        reason = text(output?.['dataset_slug']) || text(output?.['slug']) || text(nested?.['slug'])
          ? 'not-pinned' : 'not-referenced';
      }
    }
    if (JSON.stringify(selected) === JSON.stringify(this.selected()) && reason === this.unavailableReason()) return;
    this.invalidate();
    this.selected.set(selected); this.unavailableReason.set(reason);
    this.preview.set(null); this.status.set('idle'); this.error.set(null);
  }

  /** Called only by an explicit reader action. Selection alone performs no IO. */
  async load(offset = 0): Promise<void> {
    const selection = this.selected();
    if (this.disposed || !selection || integer(offset) === null) return;
    this.invalidate();
    const controller = new AbortController(); this.controller = controller;
    const context: ReadContext = {
      selection, controller, generation: this.generation,
      workspace: this.workspace.captureRequestScope(), principal: this.auth.captureRequestScope(),
    };
    this.preview.set(null); this.error.set(null); this.status.set('loading');
    try {
      // Metadata establishes the exact ready version. It never resolves a slug.
      const detail = record(await this.read(`/api/v1/datasets/${encodeURIComponent(selection.datasetId)}`, context));
      const metadata = record(detail?.['dataset']);
      if (metadata?.['id'] !== selection.datasetId) throw new DatasetReadError('identity-mismatch');
      const version = integer(metadata['version']);
      if (version === null || version < 1 || selection.version !== null && version !== selection.version) {
        throw new DatasetReadError('identity-mismatch');
      }
      if (metadata['status'] !== 'ready') throw new DatasetReadError('not-ready');
      const query = new URLSearchParams({ offset: String(offset), limit: String(PAGE_LIMIT) });
      const page = record(await this.read(`/api/v1/datasets/${encodeURIComponent(selection.datasetId)}/preview?${query}`, context));
      if (page?.['dataset_id'] !== selection.datasetId) throw new DatasetReadError('identity-mismatch');
      const rows = page['rows'], limit = integer(page['limit']), total = integer(page['total']);
      if (!Array.isArray(rows) || !rows.every(row => record(row) !== null)
        || page['offset'] !== offset || limit === null || limit < 1 || limit > PAGE_LIMIT
        || rows.length > limit || total === null || rows.length > Math.max(0, total - offset)
        || !Array.isArray(page['schema'])) throw new DatasetReadError('invalid-response');
      this.requireCurrent(context);
      this.preview.set({
        dataset_id: selection.datasetId, rows, schema: page['schema'],
        total_rows: total, returned_rows: rows.length, truncated: offset > 0 || rows.length < total,
        provenance: {
          dataset_id: selection.datasetId, dataset_version: version,
          dataset_name: text(metadata['name']), immutable: true,
          observed_run_id: selection.runId, observed_node_id: selection.nodeId,
          observed_invocation_id: selection.attemptId,
          producer_run_id: text(metadata['run_id']), producer_node_id: text(metadata['node_id']),
          offset, limit, first_row: rows.length ? offset + 1 : null,
          last_row: rows.length ? offset + rows.length : null,
        },
      });
      this.status.set('ready');
    } catch (error) {
      if (!this.current(context)) return;
      this.preview.set(null);
      this.error.set(error instanceof DatasetReadError ? error.reason : 'unavailable');
      this.status.set('error');
    }
  }

  private async read(path: string, context: ReadContext): Promise<unknown> {
    this.requireCurrent(context);
    const response = await this.transport.fetch(path, {
      method: 'GET', signal: context.controller.signal,
      workspaceSlug: context.workspace.workspaceSlug, cache: 'no-store',
    });
    this.requireCurrent(context);
    if (!response.ok) throw new DatasetReadError(
      response.status === 401 || response.status === 403 ? 'forbidden'
        : response.status === 404 ? 'missing' : response.status === 409 ? 'not-ready' : 'unavailable',
    );
    const body: unknown = await response.json();
    this.requireCurrent(context);
    return body;
  }
  private current(context: ReadContext): boolean {
    return !this.disposed && context.generation === this.generation && !context.controller.signal.aborted
      && this.workspace.isRequestScopeCurrent(context.workspace) && this.auth.isRequestScopeCurrent(context.principal);
  }
  private requireCurrent(context: ReadContext): void {
    if (!this.current(context)) throw new DOMException('Aborted', 'AbortError');
  }
  private invalidate(): void { this.generation++; this.controller?.abort(); this.controller = null; }
}
