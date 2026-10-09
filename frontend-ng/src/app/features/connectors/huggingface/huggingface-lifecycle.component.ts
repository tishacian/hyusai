import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnChanges, OnDestroy, Output, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { HubArtifact, HubConfig, HubJob, hubError } from './huggingface.models';

interface Deployment { deployment_id: string; artifact_id: string; state: string; node_name?: string; error_code?: string; }
interface LifecycleJob { job_id: string; status: string; stage?: string; error_code?: string; download_available?: boolean; license?: { tag: string; text: string; digest: string }; }

@Component({
  selector: 'app-huggingface-lifecycle', standalone: true, imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './huggingface-lifecycle.component.html', styleUrl: './huggingface-connector.component.css',
})
export class HuggingfaceLifecycleComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) config!: HubConfig;
  @Input({ required: true }) artifacts: HubArtifact[] = [];
  @Input() restoredJobs: HubJob[] = [];
  @Output() changed = new EventEmitter<void>();
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly transport = inject(WorkspaceFetchService);
  private readonly view = new WorkspaceViewContext(this.workspace, () => this.reset(), () => undefined);
  private timer?: ReturnType<typeof setTimeout>;
  private downloadController?: AbortController;
  readonly error = signal('');
  readonly busy = signal(false);
  readonly capabilities = signal<unknown>(null);
  readonly deployments = signal<Deployment[]>([]);
  readonly jobs = signal<LifecycleJob[]>([]);
  artifactId = '';
  nodeName = '';
  architecture = '';
  contextLength = 4096;
  memoryGiB: number | null = null;
  deploymentId = '';
  reason = '';
  globalConfirmed = false;
  file: File | null = null;
  readonly downloadBusy = signal(false);
  readonly acceptedLicenses = signal<string[]>([]);
  readonly readyArtifacts = () => this.artifacts.filter(a => a.kind === 'model' && a.status === 'ready' && a.has_access);
  readonly selectedArtifact = () => this.artifacts.find(a => a.artifact_id === this.artifactId);

  ngOnChanges(): void {
    const missing = this.restoredJobs.filter(job => !this.jobs().some(existing => existing.job_id === job.id));
    if (missing.length) {
      this.jobs.update(jobs => [...jobs, ...missing.map(job => ({ job_id: job.id, status: job.status, stage: job.stage }))]);
      void this.refresh();
    }
  }
  ngOnDestroy(): void { this.view.destroy(); }
  private reset(): void {
    if (this.timer) clearTimeout(this.timer);
    this.downloadController?.abort(); this.downloadController = undefined;
    this.timer = undefined; this.error.set(''); this.busy.set(false); this.capabilities.set(null); this.deployments.set([]); this.jobs.set([]); this.downloadBusy.set(false); this.acceptedLicenses.set([]);
    this.artifactId = ''; this.nodeName = ''; this.architecture = ''; this.contextLength = 4096; this.memoryGiB = null; this.deploymentId = ''; this.reason = ''; this.globalConfirmed = false; this.file = null;
  }
  selectFile(event: Event): void { this.file = (event.target as HTMLInputElement).files?.[0] ?? null; }
  async inspectNode(): Promise<void> {
    if (!this.config.can_configure || !this.nodeName.trim()) return;
    await this.perform(async scope => {
      const result = await firstValueFrom(this.api.get(`/huggingface/nodes/${encodeURIComponent(this.nodeName.trim())}/capabilities`, undefined, scope));
      return () => this.capabilities.set(result);
    });
  }
  async deploy(): Promise<void> {
    if (!this.config.can_configure || !this.readyArtifacts().some(a => a.artifact_id === this.artifactId) || !this.nodeName.trim() || !this.architecture.trim() || !this.memoryGiB || this.memoryGiB <= 0 || this.contextLength <= 0) return;
    await this.perform(async scope => {
      const result = await firstValueFrom(this.api.post<Deployment>(`/huggingface/artifacts/${encodeURIComponent(this.artifactId)}/deployments`, {
        node_name: this.nodeName.trim(), architecture: this.architecture.trim(), context_length: this.contextLength,
        required_memory_bytes: Math.ceil(this.memoryGiB! * 1024 ** 3),
      }, scope));
      return () => { this.saveDeployment(result); this.schedule(); };
    });
  }
  async deploymentAction(id: string, action = ''): Promise<void> {
    if (!this.config.can_configure || !id.trim()) return;
    await this.perform(async scope => {
      const path = `/huggingface/deployments/${encodeURIComponent(id.trim())}${action ? `/${action}` : ''}`;
      const result = await firstValueFrom(action ? this.api.post<Deployment>(path, {}, scope) : this.api.get<Deployment>(path, undefined, scope));
      return () => { this.saveDeployment(result); this.schedule(); };
    });
  }
  private saveDeployment(result: Deployment): void { this.deployments.update(items => [result, ...items.filter(item => item.deployment_id !== result.deployment_id)]); }
  async exportBundle(): Promise<void> {
    if (!this.config.can_configure || !this.artifactId) return;
    await this.startJob(`/huggingface/artifacts/${encodeURIComponent(this.artifactId)}/bundles`, { expiry_seconds: 86400 });
  }
  async uploadBundle(): Promise<void> {
    if (!this.config.can_configure || !this.file) return;
    const file = this.file;
    await this.perform(async scope => {
      const result = await firstValueFrom(this.api.post<LifecycleJob>('/huggingface/bundles', file, { ...scope, headers: { 'Content-Type': 'application/x-tar' } }));
      return () => { this.file = null; this.jobs.update(items => [result, ...items]); this.schedule(); };
    });
  }
  async purge(): Promise<void> {
    if (!this.config.can_admin_platform || !this.globalConfirmed || this.selectedArtifact()?.status !== 'revoked') return;
    await this.startJob(`/huggingface/artifacts/${encodeURIComponent(this.artifactId)}/purge`, {});
  }
  async revoke(): Promise<void> {
    if (!this.config.can_admin_platform || !this.globalConfirmed || !this.reason.trim() || !this.artifactId) return;
    await this.perform(async scope => {
      await firstValueFrom(this.api.post(`/huggingface/artifacts/${encodeURIComponent(this.artifactId)}/revoke`, { reason: this.reason.trim() }, scope));
      return () => { this.globalConfirmed = false; this.changed.emit(); };
    });
  }
  async publish(published: boolean): Promise<void> {
    if (!this.config.can_admin_platform || !this.artifactId) return;
    await this.perform(async scope => {
      await firstValueFrom(this.api.put(`/huggingface/artifacts/${encodeURIComponent(this.artifactId)}/catalogue`, { published }, scope));
      return () => this.changed.emit();
    });
  }
  toggleLicense(id: string, accepted: boolean): void {
    this.acceptedLicenses.update(ids => accepted ? [...new Set([...ids, id])] : ids.filter(value => value !== id));
  }
  async acceptLicense(job: LifecycleJob): Promise<void> {
    if (!this.config.can_configure || !job.license?.text || !this.acceptedLicenses().includes(job.job_id)) return;
    await this.perform(async scope => {
      const result = await firstValueFrom(this.api.post<LifecycleJob>(`/huggingface/bundle-jobs/${encodeURIComponent(job.job_id)}/accept-license`, {}, scope));
      return () => { this.jobs.update(items => items.map(item => item.job_id === job.job_id ? result : item)); this.toggleLicense(job.job_id, false); this.schedule(); };
    });
  }
  private async startJob(path: string, body: unknown): Promise<void> {
    await this.perform(async scope => {
      const job = await firstValueFrom(this.api.post<LifecycleJob>(path, body, scope));
      return () => { this.jobs.update(items => [job, ...items]); this.schedule(); };
    });
  }
  private async perform(action: (scope: { workspaceSlug: string | null }) => Promise<() => void>): Promise<void> {
    if (this.busy()) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      const apply = await action(request.scope);
      if (this.view.isCurrent(request)) apply();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }
  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    if (this.jobs().some(j => ['queued', 'running'].includes(j.status)) || this.deployments().some(d => ['preparing', 'verifying', 'starting', 'draining'].includes(d.state))) this.timer = setTimeout(() => void this.refresh(), 2500);
  }
  async refresh(): Promise<void> {
    const request = this.view.captureRequest();
    this.error.set('');
    try {
      const [jobs, deployments] = await Promise.all([
        Promise.all(this.jobs().map(job => firstValueFrom(this.api.get<LifecycleJob>(`/huggingface/bundle-jobs/${encodeURIComponent(job.job_id)}`, undefined, request.scope)))),
        Promise.all(this.deployments().map(d => firstValueFrom(this.api.get<Deployment>(`/huggingface/deployments/${encodeURIComponent(d.deployment_id)}`, undefined, request.scope)))),
      ]);
      if (!this.view.isCurrent(request)) return;
      const completed = jobs.some(job => job.status === 'completed' && this.jobs().find(old => old.job_id === job.job_id)?.status !== 'completed');
      this.jobs.set(jobs.map(job => ({ ...this.jobs().find(old => old.job_id === job.job_id), ...job }))); this.deployments.set(deployments); if (completed) this.changed.emit(); this.schedule();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
  }
  async download(job: LifecycleJob): Promise<void> {
    if (!this.config.can_configure || !job.download_available || this.downloadBusy()) return;
    const request = this.view.captureRequest();
    this.downloadBusy.set(true);
    const controller = new AbortController(); this.downloadController = controller;
    try {
      const picker = (window as Window & {
        showSaveFilePicker?: (options: { suggestedName: string }) => Promise<{ createWritable(): Promise<WritableStream<Uint8Array>> }>;
      }).showSaveFilePicker;
      // Large model bundles stream directly to disk on supporting browsers.
      const handle = picker ? await picker.call(window, { suggestedName: `huggingface-${job.job_id}.tar` }) : null;
      if (!this.view.isCurrent(request)) return;
      const response = await this.transport.fetch(`/api/v1/huggingface/bundle-jobs/${encodeURIComponent(job.job_id)}/download`, { workspaceSlug: request.scope.workspaceSlug, signal: controller.signal });
      if (!response.ok) throw { error: await response.json() };
      if (!response.body || !this.view.isCurrent(request)) { controller.abort(); return; }
      if (handle) {
        await response.body.pipeTo(await handle.createWritable(), { signal: controller.signal });
      } else {
        // Bound the fallback: never buffer a tens-of-GiB model in browser RAM.
        const maximum = 256 * 1024 ** 2;
        const parts: Uint8Array<ArrayBuffer>[] = []; let size = 0;
        const reader = response.body.getReader();
        for (;;) {
          const { done, value } = await reader.read(); if (done) break;
          size += value.byteLength;
          if (size > maximum) { controller.abort(); throw new Error(this.i18n.t('connectors.hf.streaming_browser')); }
          parts.push(new Uint8Array(value));
        }
        if (!this.view.isCurrent(request)) return;
        const url = URL.createObjectURL(new Blob(parts, { type: 'application/x-tar' }));
        const anchor = document.createElement('a'); anchor.href = url; anchor.download = `huggingface-${job.job_id}.tar`; anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) { if (this.view.isCurrent(request) && !(error instanceof DOMException && error.name === 'AbortError')) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) { this.downloadBusy.set(false); this.downloadController = undefined; } }
  }
}
