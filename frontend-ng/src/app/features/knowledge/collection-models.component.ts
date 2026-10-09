import { ChangeDetectionStrategy, Component, Input, OnChanges, OnDestroy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { HubArtifact, HubJob, hubError, isTerminalJob, jobError } from '../connectors/huggingface/huggingface.models';

interface CollectionModels {
  id: string; slug: string; chunk_count?: number; embedding_model?: string;
  embedding_artifact_id?: string | null; reranker_artifact_id?: string | null;
  embedding_dimension?: number; active_generation?: string; pending_generation?: string | null;
  permissions?: { can_write?: boolean };
}

@Component({
  selector: 'app-collection-models', standalone: true, imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <details class="ck-surface rounded-md p-4 mb-4" (toggle)="opened($event)">
      <summary class="cursor-pointer font-semibold">{{ i18n.t('knowledge.models.title') }}</summary>
      @if (error()) { <p role="alert" class="ck-warn text-sm my-3">{{ error() }}</p> }
      @if (collection(); as current) {
        <p class="text-sm my-3">{{ i18n.t('knowledge.models.active') }}: {{ current.embedding_artifact_id || current.embedding_model }} · {{ current.active_generation }} · {{ current.embedding_dimension }}</p>
        @if (current.pending_generation) { <p class="text-sm ck-fg-3">{{ i18n.t('knowledge.models.pending') }}: {{ current.pending_generation }}</p> }
        @if (current.permissions?.can_write) {
          <div class="grid md:grid-cols-2 gap-4 my-3">
            <label class="text-sm grid gap-2">{{ i18n.t('knowledge.models.embedding') }}
              <select class="ck-input" [(ngModel)]="embeddingId" [disabled]="busy()">
                <option value="">{{ i18n.t('knowledge.models.choose') }}</option>
                @for (artifact of embeddingArtifacts(); track artifact.artifact_id) { <option [value]="artifact.artifact_id">{{ artifact.repo_id }} · {{ artifact.revision }}</option> }
              </select>
            </label>
            <label class="text-sm grid gap-2">{{ i18n.t('knowledge.models.reranker') }}
              <select class="ck-input" [(ngModel)]="rerankerId" [disabled]="busy()">
                <option value="">{{ i18n.t('knowledge.models.built_in') }}</option>
                @for (artifact of rerankerArtifacts(); track artifact.artifact_id) { <option [value]="artifact.artifact_id">{{ artifact.repo_id }} · {{ artifact.revision }}</option> }
              </select>
            </label>
          </div>
          <p class="text-sm ck-fg-3 my-2">{{ i18n.t('knowledge.models.reindex_help', { count: current.chunk_count || 0 }) }}</p>
          <label class="flex items-center gap-2 text-sm my-3"><input type="checkbox" [(ngModel)]="confirmed" />{{ i18n.t('knowledge.models.confirm') }}</label>
          <div class="flex flex-wrap gap-2">
            <button type="button" class="ck-btn ck-btn-accent" [disabled]="busy() || !embeddingId || !confirmed || !!current.pending_generation" (click)="reindex()">{{ i18n.t('knowledge.models.reindex') }}</button>
            <button type="button" class="ck-btn" [disabled]="busy() || rerankerId === (current.reranker_artifact_id || '')" (click)="setReranker()">{{ i18n.t('knowledge.models.set_reranker') }}</button>
          </div>
        }
      }
      @if (job(); as currentJob) {
        <div aria-live="polite" class="my-3 text-sm"><p>{{ currentJob.status }} · {{ currentJob.stage }}</p>
          @if (!terminal(currentJob) && currentJob.id && collection()?.permissions?.can_write) { <button type="button" class="ck-btn" [disabled]="busy()" (click)="cancel()">{{ i18n.t('connectors.hf.cancel') }}</button> }
          @if (!terminal(currentJob)) { <progress class="w-full" max="100" [value]="currentJob.progress || 0" [attr.aria-label]="i18n.t('connectors.hf.progress')"></progress> }
          @if (jobError(currentJob)) { <p class="ck-warn">{{ jobError(currentJob) }}</p> }
        </div>
      }
      <button type="button" class="ck-btn mt-3" (click)="refresh()">{{ i18n.t('connectors.hf.refresh') }}</button>
    </details>
  `,
})
export class CollectionModelsComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) collectionId = '';
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private timer?: ReturnType<typeof setTimeout>;
  private isOpen = false;
  private readonly view = new WorkspaceViewContext(this.workspace, () => this.reset(), () => { if (this.isOpen) void this.load(); });
  readonly collection = signal<CollectionModels | null>(null);
  readonly embeddingArtifacts = signal<HubArtifact[]>([]);
  readonly rerankerArtifacts = signal<HubArtifact[]>([]);
  readonly job = signal<HubJob | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  embeddingId = '';
  rerankerId = '';
  confirmed = false;
  readonly terminal = isTerminalJob;
  readonly jobError = jobError;

  ngOnChanges(): void { this.view.invalidate(); this.reset(); if (this.isOpen) void this.load(); }
  ngOnDestroy(): void { this.view.destroy(); }
  opened(event: Event): void { this.isOpen = (event.target as HTMLDetailsElement).open; if (this.isOpen && !this.collection()) void this.load(); }
  private reset(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined; this.collection.set(null); this.embeddingArtifacts.set([]); this.rerankerArtifacts.set([]);
    this.job.set(null); this.busy.set(false); this.error.set(''); this.embeddingId = ''; this.rerankerId = ''; this.confirmed = false;
  }
  async load(): Promise<void> {
    if (!this.collectionId) return;
    const request = this.view.captureRequest();
    try {
      const [collections, artifacts, modelJobs] = await Promise.all([
        firstValueFrom(this.api.get<{ items: CollectionModels[] }>('/documents/collections', undefined, request.scope)),
        firstValueFrom(this.api.get<{ artifacts: HubArtifact[] }>('/huggingface/artifacts', undefined, request.scope)),
        firstValueFrom(this.api.get<{ items: HubJob[] }>('/documents/jobs', { collection_id: this.collectionId, limit: '100' }, request.scope)),
      ]);
      if (!this.view.isCurrent(request)) return;
      const current = collections.items.find(item => item.id === this.collectionId || item.slug === this.collectionId) ?? null;
      if (!this.job()) {
        const candidates = modelJobs.items.filter(job => ['vector_reindex', 'rag_reranker_activate'].includes(job.kind ?? ''));
        const job = candidates.find(job => !isTerminalJob(job)) ?? candidates[0];
        if (job) { this.job.set(job); this.schedule(); }
      }
      this.collection.set(current); this.rerankerId = current?.reranker_artifact_id ?? '';
      const ready = artifacts.artifacts.filter(a => a.kind === 'model' && a.status === 'ready' && a.has_access);
      this.embeddingArtifacts.set(ready.filter(a => a.format === 'safetensors' && (a.library === 'sentence-transformers' || a.pipeline_tag === 'sentence-similarity' || a.pipeline_tag === 'feature-extraction')));
      this.rerankerArtifacts.set(ready.filter(a => ['onnx', 'safetensors'].includes(a.format) && ['text-classification', 'text-ranking', 'sentence-similarity'].includes(a.pipeline_tag ?? '')));
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
  }
  async reindex(): Promise<void> {
    if (!this.embeddingId || !this.confirmed || this.collection()?.pending_generation) return;
    await this.start('embedding/reindex', { artifact_id: this.embeddingId, normalize_embeddings: true, batch_size: 32 });
  }
  async setReranker(): Promise<void> { await this.start('reranker', { artifact_id: this.rerankerId || null }); }
  private async start(action: string, body: unknown): Promise<void> {
    const collection = this.collection();
    if (!collection?.permissions?.can_write || this.busy()) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      const result = await firstValueFrom(this.api.post<{ job: HubJob | null; pending_generation?: string }>(`/documents/collections/${encodeURIComponent(collection.id || collection.slug)}/${action}`, body, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.job.set(result.job); this.confirmed = false;
      if (result.pending_generation) this.collection.set({ ...collection, pending_generation: result.pending_generation });
      if (result.job) this.schedule(); else await this.load();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }
  async cancel(): Promise<void> {
    const current = this.job(); const collection = this.collection();
    if (!current || !collection?.permissions?.can_write || this.busy()) return;
    const request = this.view.captureRequest(); this.busy.set(true);
    try {
      const result = await firstValueFrom(this.api.post<{ job: HubJob }>(`/documents/collections/${encodeURIComponent(collection.id || collection.slug)}/model-jobs/${encodeURIComponent(current.id)}/cancel`, {}, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.job.set(result.job); if (this.timer) clearTimeout(this.timer); await this.load();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }
  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    if (this.job() && !isTerminalJob(this.job()!)) this.timer = setTimeout(() => void this.poll(), 2000);
  }
  async refresh(): Promise<void> { this.error.set(''); await this.load(); if (this.job()) await this.poll(); }
  private async poll(): Promise<void> {
    const job = this.job();
    if (!job) return;
    const request = this.view.captureRequest();
    try {
      const current = await firstValueFrom(this.api.get<HubJob>(`/documents/jobs/${encodeURIComponent(job.id)}`, undefined, request.scope));
      if (!this.view.isCurrent(request) || this.job()?.id !== job.id) return;
      this.job.set(current);
      if (isTerminalJob(current)) await this.load(); else this.schedule();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
  }
}
