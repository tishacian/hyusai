import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, exhaustMap, of, takeWhile, timer } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';

export interface IngestionJob {
  id: string;
  status: string;
  stage?: string | null;
  progress: number;
  error?: string | null;
  updated_at: string;
  celery_task_id?: string | null;
  result?: {
    source_failure?: { code?: string; filename?: string };
    dispatch_error?: string;
    ingest_options?: { source_profile?: string; wave_id?: string };
    retry_history?: Array<{ error?: string; completed_at?: string }>;
  };
}

@Component({
  selector: 'app-ingestion-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ck-surface rounded-md p-4 space-y-3" aria-labelledby="ingestion-title">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 id="ingestion-title" class="font-semibold ck-fg-1">{{ i18n.t('capture.ingest.title') }}</h2>
        <button type="button" class="ck-btn-soft rounded px-3 py-2 text-sm" (click)="refresh()" [disabled]="busy()">
          {{ i18n.t('capture.ingest.refresh') }}
        </button>
      </div>
      @if (loadError()) {
        <p role="alert" class="ck-warn text-sm">{{ i18n.t('capture.ingest.load_error') }}</p>
      } @else if (loading()) {
        <p role="status" class="ck-fg-3 text-sm">{{ i18n.t('capture.ingest.loading') }}</p>
      } @else if (job(); as current) {
        <div class="flex flex-wrap items-baseline justify-between gap-2 text-sm">
          <p role="status" class="ck-fg-1">{{ statusLabel(current) }}</p>
          <time class="ck-fg-3" [attr.datetime]="current.updated_at">{{ dateLabel(current.updated_at) }}</time>
        </div>
        @if (current.status === 'running') {
          <progress class="w-full" max="100" [value]="current.progress" [attr.aria-label]="i18n.t('capture.ingest.progress')"></progress>
        }
        @if (current.error || dispatchPending(current)) {
          <p class="ck-warn text-sm break-words">{{ failureLabel(current) }}</p>
        }
        @if (missingOriginal(current) && !governed(current)) {
          <p class="ck-fg-2 text-sm">{{ i18n.t('capture.ingest.restore_original') }}</p>
        }
        @if (current.status === 'failed' || dispatchPending(current)) {
          @if (governed(current)) {
            <p class="ck-fg-2 text-sm">{{ i18n.t('capture.ingest.campaign_required') }}</p>
          } @else if (!workspace.isAdmin()) {
            <p class="ck-fg-2 text-sm">{{ i18n.t('capture.ingest.admin_required') }}</p>
          } @else {
            @if (!missingOriginal(current)) { <p class="ck-fg-2 text-sm">{{ i18n.t('capture.ingest.retry_hint') }}</p> }
            <button type="button" class="ck-btn-soft rounded px-3 py-2 text-sm" [disabled]="busy()" (click)="retry()">
              {{ i18n.t(busy() ? 'capture.ingest.retrying' : 'capture.ingest.retry') }}
            </button>
          }
        }
        <details class="text-sm ck-fg-3">
          <summary class="cursor-pointer py-1">{{ i18n.t('capture.ingest.details') }}</summary>
          <p class="mt-2 font-mono text-xs break-all">{{ current.id }}</p>
          <p class="mt-1 break-words">{{ current.stage }}</p>
          @if (missingOriginal(current)) { <p class="mt-1 break-words">{{ current.error }}</p> }
          @for (attempt of current.result?.retry_history || []; track $index) {
            <div class="mt-3 border-t pt-2" style="border-color:var(--ck-stroke)">
              <p>{{ i18n.t('capture.ingest.previous_attempt', { number: $index + 1 }) }} · {{ dateLabel(attempt.completed_at) }}</p>
              <p class="break-words">{{ attempt.error }}</p>
            </div>
          }
        </details>
      } @else {
        <p class="ck-fg-3 text-sm">{{ i18n.t('capture.ingest.empty') }}</p>
      }
      @if (retryError()) { <p role="alert" class="ck-warn text-sm">{{ retryError() }}</p> }
    </section>
  `,
})
export class IngestionStatusComponent {
  readonly collectionId = input.required<string>();
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly reload = signal(0);
  readonly job = signal<IngestionJob | null>(null);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  readonly busy = signal(false);
  readonly retryError = signal('');
  private retryRequest: { jobId: string; request_id: string; observed_updated_at: string } | null = null;

  constructor() {
    effect((cleanup) => {
      const collection = this.collectionId();
      const workspaceId = this.workspace.current()?.id;
      this.reload();
      const scope = this.workspace.captureRequestScope();
      this.loading.set(true);
      this.loadError.set(false);
      if (!collection || !workspaceId) { this.job.set(null); this.loading.set(false); return; }
      const subscription = timer(0, 5000).pipe(
        exhaustMap(() => this.http.get<{ items: IngestionJob[] }>('/api/v1/documents/jobs', {
          params: { kind: 'document_ingest_index', collection_id: collection, limit: '1' },
        }).pipe(catchError(() => of(null)))),
        takeWhile((response) => !!response?.items.some((job) => ['queued', 'running'].includes(job.status) && !this.dispatchPending(job)), true),
      ).subscribe((response) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.loading.set(false);
        this.loadError.set(response === null);
        this.job.set(response?.items[0] || null);
      });
      cleanup(() => { subscription.unsubscribe(); this.job.set(null); this.busy.set(false); this.retryError.set(''); });
    });
  }

  dateLabel(value?: string): string {
    if (!value) return '—';
    // WorkerJob timestamps are UTC, including legacy ISO strings without a suffix.
    const date = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
    return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(this.i18n.locale(), {
      dateStyle: 'short', timeStyle: 'short',
    }).format(date);
  }

  refresh(): void { this.reload.update((value) => value + 1); }
  dispatchPending(job: IngestionJob): boolean {
    return job.status === 'queued' && job.stage === 'dispatch_pending' && !job.celery_task_id;
  }
  governed(job: IngestionJob): boolean {
    return job.result?.ingest_options?.source_profile === 'needlepunch' || !!job.result?.ingest_options?.wave_id;
  }
  missingOriginal(job: IngestionJob): boolean {
    return job.status === 'failed' && ['original_source_missing', 'originals_missing'].includes(job.result?.source_failure?.code || '');
  }
  failureLabel(job: IngestionJob): string {
    if (this.missingOriginal(job)) {
      const failure = job.result!.source_failure!;
      return failure.code === 'original_source_missing' && failure.filename
        ? this.i18n.t('capture.ingest.original_missing', { filename: failure.filename })
        : this.i18n.t('capture.ingest.originals_missing');
    }
    return job.error || job.result?.dispatch_error || this.i18n.t('capture.ingest.dispatch_pending');
  }
  statusLabel(job: IngestionJob): string {
    const state = this.dispatchPending(job) ? 'dispatch_pending' : job.status;
    return this.i18n.t(`capture.ingest.status.${state}`);
  }
  retry(): void {
    const job = this.job();
    if (!job || this.busy() || !this.workspace.isAdmin() || this.governed(job) || (job.status !== 'failed' && !this.dispatchPending(job))) return;
    const collection = this.collectionId();
    const scope = this.workspace.captureRequestScope();
    if (this.retryRequest?.jobId !== job.id) {
      this.retryRequest = { jobId: job.id, request_id: crypto.randomUUID(), observed_updated_at: job.updated_at };
    }
    const request = this.retryRequest;
    this.busy.set(true);
    this.retryError.set('');
    this.http.post<IngestionJob>(`/api/v1/documents/jobs/${encodeURIComponent(job.id)}/retry`, {
      request_id: request.request_id, observed_updated_at: request.observed_updated_at,
    }).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (response) => {
        if (!this.workspace.isRequestScopeCurrent(scope) || this.collectionId() !== collection) return;
        this.retryRequest = null;
        this.job.set(response);
        this.busy.set(false);
        this.refresh();
      },
      error: (error) => {
        if (!this.workspace.isRequestScopeCurrent(scope) || this.collectionId() !== collection) return;
        this.busy.set(false);
        const code = error?.error?.detail?.code;
        const key = `capture.ingest.error.${code}`;
        const translated = code ? this.i18n.t(key) : key;
        this.retryError.set(translated !== key ? translated : this.i18n.t('capture.ingest.retry_error'));
        // Unknown delivery keeps the same request key for a safe repeat.
        if (error.status > 0 && error.status < 500) this.retryRequest = null;
      },
    });
  }
}
