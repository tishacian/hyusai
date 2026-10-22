import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, concat, defer, map, of, timer } from 'rxjs';
import { catchError, filter, switchMap, take, takeWhile, tap } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { runIsSettled, type RuntimeNodeContext } from './model';

export interface BindingSnapshot {
  binding_key?: string;
  confirmation_policy?: string;
  on_unavailable?: string;
  system_id?: string;
}

export interface BindingResolve {
  status: 'ok' | 'unavailable' | 'drift' | string;
  reasons: string[];
  binding: BindingSnapshot;
}

export interface BindingInvokeResult {
  id: string;
  status: Run['status'] | string;
  system_id?: string;
  binding_key?: string;
  experience_slug?: string;
  experience_release_id?: string;
  experience_deployment_id?: string;
  channel?: string;
  origin?: string;
  idempotent_replay?: boolean;
}

export interface RuntimeFileReference {
  kind: 'document';
  document_id: string | null;
  filename: string;
  collection_name: string;
  job_id?: string;
  status: string;
}

export type RuntimePhase = 'idle' | 'loading' | 'restoring' | 'running' | 'error';
/**
 * What the last-result lookup found. The server only resumes a result this
 * reader started on the current release with the same fixed input, so "no
 * result" must say that, never "not started yet".
 */
export type RuntimePreviousResult = 'unchecked' | 'restored' | 'none_for_you' | 'not_resumable';

export interface RuntimeExecutionState {
  run: Run | null;
  history: Run[];
  phase: RuntimePhase;
  previousResult?: RuntimePreviousResult;
  lastError: string | null;
  lastInvoke: {
    context: RuntimeNodeContext;
    bindingKey: string;
    payload: Record<string, unknown>;
    confirmed?: boolean;
    idempotencyKey: string;
  } | null;
}

interface UploadResponse {
  status?: string;
  collection_name?: string;
  job_id?: string;
  documents?: Array<{
    document_id?: string | null;
    filename?: string | null;
    status?: string | null;
  }>;
}

interface UploadJob {
  status?: string;
}

interface CollectionInventory {
  sources?: Array<{
    id?: string;
    filename?: string;
    status?: string;
    metadata?: Record<string, unknown>;
  }>;
}

const POLL_MS = 1500;
const MAX_POLLS = 80;
const EMPTY_STATE: RuntimeExecutionState = {
  run: null,
  history: [],
  phase: 'idle',
  lastError: null,
  lastInvoke: null,
};

@Injectable({ providedIn: 'root' })
export class ExperienceRuntimeService {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly executions = signal<Record<string, RuntimeExecutionState>>({});
  private epoch = 0;
  private readonly operations = new Map<string, number>();
  private readonly contexts = new Map<string, RuntimeNodeContext>();

  /** Every action owns its state; cross-component output reads are explicit. */
  readonly runs = computed(() => {
    const seen = new Set<string>();
    const out: Run[] = [];
    for (const state of Object.values(this.executions())) {
      for (const run of state.history) {
        if (!run.id || seen.has(run.id)) continue;
        seen.add(run.id);
        out.push(run);
      }
    }
    return out;
  });

  state(key: string): RuntimeExecutionState {
    return this.executions()[key] ?? EMPTY_STATE;
  }

  run(key: string): Run | null {
    return this.state(key).run;
  }

  phase(key: string): RuntimePhase {
    return this.state(key).phase;
  }

  previousResult(key: string): RuntimePreviousResult {
    return this.state(key).previousResult ?? 'unchecked';
  }

  lastError(key: string): string | null {
    return this.state(key).lastError;
  }

  resolve(context: RuntimeNodeContext, bindingKey: string): Observable<BindingResolve | null> {
    if (context.mode !== 'live' || !context.experienceSlug) return of(null);
    const slug = encodeURIComponent(context.experienceSlug);
    const key = encodeURIComponent(bindingKey);
    return this.api
      .get<BindingResolve>(`/work/${slug}/bindings/${key}/resolve`)
      .pipe(catchError(() => of(null)));
  }

  /** Read the last authorised execution of this released, fixed-input action.
   * The server owns selection and access checks. No action is submitted, and
   * restoring a completed action never replays its after-success navigation.
   */
  restore(context: RuntimeNodeContext, bindingKey: string): Observable<Run | null> {
    if (context.mode !== 'live' || !context.experienceSlug || !context.releaseId || !bindingKey) return of(null);
    if (this.lastError(context.stateKey) === 'release_changed'
      && this.contexts.get(context.stateKey)?.releaseId === context.releaseId) return of(null);
    return defer(() => {
      this.contexts.set(context.stateKey, context);
      const current = this.beginOperation(context.stateKey);
      // A remount reauthorises the current release. Old in-memory history is
      // not evidence that those Runs remain readable in this context.
      this.patch(context.stateKey, { run: null, history: [], phase: 'restoring', lastError: null, lastInvoke: null });
      const slug = encodeURIComponent(context.experienceSlug);
      const key = encodeURIComponent(bindingKey);
      return this.api.get<{ run: BindingInvokeResult | null }>(`/work/${slug}/bindings/${key}/runs/latest`, {
        page_id: context.pageId,
        component_id: context.componentId,
        release_id: context.releaseId!,
      }).pipe(
        switchMap((result) => {
          if (!current()) return of(null);
          if (!result.run?.id) {
            this.patch(context.stateKey, { phase: 'idle', previousResult: 'none_for_you' });
            return of(null);
          }
          return this.canonical.getRun(result.run.id).pipe(
            switchMap((run) => {
              if (!current()) return of(null);
              if (!run) {
                this.patch(context.stateKey, { phase: 'error', lastError: 'network' });
                return of(null);
              }
              const settled = runIsSettled(run.status);
              this.patch(context.stateKey, {
                run,
                history: upsertRun(this.state(context.stateKey).history, run),
                previousResult: 'restored',
                phase: run.status === 'failed' ? 'error' : settled ? 'idle' : 'running',
                lastError: run.status === 'failed' ? run.error ?? 'failed' : null,
              });
              return settled ? of(run) : concat(of(run), this.poll(context, run.id));
            }),
          );
        }),
        catchError((err: unknown) => {
          if (current() && err instanceof HttpErrorResponse && err.status === 404
            && err.error?.detail?.code === 'WORK_RUN_RESUME_UNSUPPORTED') {
            // Not an outage: this component cannot resume an earlier result.
            this.patch(context.stateKey, { run: null, phase: 'idle', previousResult: 'not_resumable', lastError: null });
            return of(null);
          }
          if (current()) this.patch(context.stateKey, {
            run: null, phase: 'error',
            lastError: err instanceof HttpErrorResponse && err.status === 409
              && err.error?.detail?.code === 'WORK_RELEASE_CHANGED' ? 'release_changed'
              : err instanceof HttpErrorResponse && [401, 403].includes(err.status)
                ? `http_${err.status}` : 'network',
          });
          return of(null);
        }),
      );
    });
  }

  invoke(
    context: RuntimeNodeContext,
    bindingKey: string,
    payload: Record<string, unknown>,
    confirmed?: boolean,
    idempotencyKey = invocationKey(),
  ): Observable<BindingInvokeResult | null> {
    if (this.lastError(context.stateKey) === 'release_changed') return of(null);
    if (context.mode !== 'live' || !context.experienceSlug) {
      this.patch(context.stateKey, { phase: 'error', lastError: 'preview_disabled' });
      return of(null);
    }
    const current = this.beginOperation(context.stateKey);
    this.contexts.set(context.stateKey, context);
    this.patch(context.stateKey, {
      phase: 'loading',
      // A rejected submission has no execution of its own. Keep older runs in
      // history, but never present one as the cause/result of this new action.
      run: null,
      lastError: null,
      lastInvoke: { context, bindingKey, payload, confirmed, idempotencyKey },
    });
    const body: {
      payload: Record<string, unknown>;
      confirmed?: boolean;
      page_id: string;
      component_id: string;
    } = {
      payload,
      page_id: context.pageId,
      component_id: context.componentId,
    };
    if (confirmed !== undefined) body.confirmed = confirmed;
    const slug = encodeURIComponent(context.experienceSlug);
    const key = encodeURIComponent(bindingKey);
    return this.api
      .post<BindingInvokeResult>(`/work/${slug}/bindings/${key}/runs`, body, {
        headers: { 'Idempotency-Key': idempotencyKey },
      })
      .pipe(
        filter(() => current()),
        tap((started) => {
          const run: Run = {
            id: started.id,
            system_id: started.system_id ?? '',
            status: (started.status as Run['status']) || 'pending',
          };
          this.patch(context.stateKey, {
            phase: 'running',
            run,
            history: upsertRun(this.state(context.stateKey).history, run),
          });
        }),
        catchError((err: unknown) => {
          if (current()) this.patch(context.stateKey, { phase: 'error', lastError: requestErrorMessage(err) });
          return of(null);
        }),
      );
  }

  poll(context: RuntimeNodeContext, runId: string): Observable<Run | null> {
    const current = this.currentOperation(context.stateKey);
    let polls = 0;
    return timer(0, POLL_MS).pipe(
      takeWhile(() => current()),
      switchMap(() => this.canonical.getRun(runId)),
      filter(() => current()),
      tap((run) => {
        polls += 1;
        if (run) {
          this.patch(context.stateKey, {
            run,
            history: upsertRun(this.state(context.stateKey).history, run),
          });
        }
        if (run && runIsSettled(run.status)) {
          this.patch(context.stateKey, {
            phase: run.status === 'failed' ? 'error' : 'idle',
            lastError: run.status === 'failed' ? run.error ?? 'failed' : null,
          });
        } else if (polls >= MAX_POLLS) {
          this.patch(context.stateKey, { phase: 'error', lastError: 'timeout' });
        }
      }),
      takeWhile((run) => polls < MAX_POLLS && !runIsSettled(run?.status), true),
      catchError(() => {
        if (current()) this.patch(context.stateKey, { phase: 'error', lastError: 'network' });
        return of(null);
      }),
    );
  }

  retry(context: RuntimeNodeContext): Observable<BindingInvokeResult | null> {
    const previous = this.state(context.stateKey).lastInvoke;
    if (!previous) return of(null);
    return this.invoke(
      context,
      previous.bindingKey,
      previous.payload,
      previous.confirmed,
      previous.idempotencyKey,
    );
  }

  /** Resume the component that owns a Run after its HITL decision. */
  resumeAfterDecision(run: Run): void {
    const match = Object.entries(this.executions()).find(([, state]) =>
      state.run?.id === run.id || state.history.some((item) => item.id === run.id),
    );
    if (!match) return;
    const [stateKey, state] = match;
    // The canonical HITL endpoint returns the status captured before the
    // decision commit. Treat hitl_pending as a transition and re-read the Run.
    const staleDecisionStatus = run.status === 'hitl_pending';
    const settled = !staleDecisionStatus && runIsSettled(run.status);
    this.patch(stateKey, {
      run,
      history: upsertRun(state.history, run),
      phase: run.status === 'failed' ? 'error' : settled ? 'idle' : 'running',
      lastError: run.status === 'failed' ? run.error ?? 'failed' : null,
    });
    const context = state.lastInvoke?.context ?? this.contexts.get(stateKey);
    if (context && (!settled || staleDecisionStatus)) this.poll(context, run.id).subscribe();
  }

  uploadFile(
    context: RuntimeNodeContext,
    file: File,
    collectionName = 'documents',
  ): Observable<RuntimeFileReference | null> {
    if (context.mode !== 'live' || !context.experienceSlug) return of(null);
    const form = new FormData();
    form.append('files', file, file.name);
    form.append('collection_name', collectionName || 'documents');
    form.append('source', 'experience_runtime');
    return this.api.post<UploadResponse>('/documents/upload-batch', form).pipe(
      switchMap((response) => {
        const item = response.documents?.[0];
        const collection = response.collection_name || collectionName || 'documents';
        if (item?.document_id) {
          return of({
            kind: 'document' as const,
            document_id: item.document_id,
            filename: item.filename || file.name,
            collection_name: collection,
            job_id: response.job_id,
            status: item.status || response.status || 'success',
          });
        }
        if (!response.job_id) return of(null);
        return this.waitForUploadedDocument(response.job_id, collection, item?.filename || file.name);
      }),
      catchError(() => of(null)),
    );
  }

  reset(): void {
    this.epoch++;
    this.operations.clear();
    this.contexts.clear();
    this.executions.set({});
  }

  private beginOperation(key: string): () => boolean {
    this.operations.set(key, (this.operations.get(key) ?? 0) + 1);
    return this.currentOperation(key);
  }

  private currentOperation(key: string): () => boolean {
    const epoch = this.epoch, operation = this.operations.get(key);
    return () => this.epoch === epoch && this.operations.get(key) === operation;
  }

  private patch(key: string, change: Partial<RuntimeExecutionState>): void {
    this.executions.update((current) => ({
      ...current,
      [key]: { ...(current[key] ?? EMPTY_STATE), ...change },
    }));
  }

  private waitForUploadedDocument(
    jobId: string,
    collectionName: string,
    filename: string,
  ): Observable<RuntimeFileReference | null> {
    let polls = 0;
    return timer(0, POLL_MS).pipe(
      switchMap(() => this.api.get<UploadJob>(`/documents/jobs/${encodeURIComponent(jobId)}`)),
      tap(() => { polls += 1; }),
      takeWhile(
        (job) => polls < MAX_POLLS && job.status !== 'completed' && job.status !== 'failed',
        true,
      ),
      filter((job) => job.status === 'completed' || job.status === 'failed' || polls >= MAX_POLLS),
      take(1),
      switchMap((job) => {
        if (job.status !== 'completed') return of(null);
        return this.api
          .get<CollectionInventory>(
            `/documents/collections/${encodeURIComponent(collectionName)}/inventory`,
            { q: filename, source_limit: '20' },
          )
          .pipe(
            map((inventory) => {
              const source = (inventory.sources ?? []).find((item) => item.filename === filename);
              if (!source?.id) return null;
              const storedId = source.metadata?.['document_id'];
              return {
                kind: 'document' as const,
                document_id: typeof storedId === 'string' && storedId ? storedId : source.id,
                filename: source.filename || filename,
                collection_name: collectionName,
                job_id: jobId,
                status: source.status || 'ready',
              };
            }),
          );
      }),
    );
  }
}

function invocationKey(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `experience-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function upsertRun(history: readonly Run[], run: Run): Run[] {
  const index = history.findIndex((item) => item.id === run.id);
  if (index < 0) return [...history, run];
  return history.map((item, i) => (i === index ? run : item));
}

function requestErrorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const detail = err.error;
    if (detail && typeof detail === 'object') {
      const rec = detail as Record<string, unknown>;
      if (typeof rec['message'] === 'string') return rec['message'];
      const nested = rec['detail'];
      if (nested && typeof nested === 'object' && typeof (nested as { message?: unknown }).message === 'string') {
        return (nested as { message: string }).message;
      }
      if (typeof nested === 'string') return nested;
    }
    return err.status === 0 ? 'network' : `http_${err.status}`;
  }
  return 'failed';
}
