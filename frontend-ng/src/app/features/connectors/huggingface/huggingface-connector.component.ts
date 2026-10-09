import { HuggingfaceLifecycleComponent } from './huggingface-lifecycle.component';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { CkBackLinkComponent } from '@app/shared/cockpit';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import {
  HubArtifact, HubConfig, HubFile, HubFormat, HubImport, HubJob, HubKind, HubRepository, HubSearchResult,
  LicenseClass, defaultSelection, filesForFormat, hasWeights, hubError, isTerminalJob, jobError,
} from './huggingface.models';

@Component({
  selector: 'app-huggingface-connector',
  standalone: true,
  imports: [CommonModule, FormsModule, CkBackLinkComponent, SectionHeaderComponent, HuggingfaceLifecycleComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './huggingface-connector.component.html',
  styleUrl: './huggingface-connector.component.css',
})
export class HuggingfaceConnectorComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);
  private pollTimer?: ReturnType<typeof setTimeout>;
  private searchVersion = 0;
  private repositoryVersion = 0;
  private readonly view = new WorkspaceViewContext(this.workspace, () => this.reset(), () => void this.load());
  readonly config = signal<HubConfig | null>(null);
  readonly platformConfig = signal<Pick<HubConfig, 'connection' | 'policy' | 'limits'> | null>(null);
  readonly results = signal<HubSearchResult[]>([]);
  readonly repository = signal<HubRepository | null>(null);
  readonly artifacts = signal<HubArtifact[]>([]);
  readonly jobs = signal<HubJob[]>([]);
  readonly lifecycleJobs = signal<HubJob[]>([]);
  readonly selectedFiles = signal<string[]>([]);
  readonly busy = signal(false);
  readonly searching = signal(false);
  readonly inspecting = signal(false);
  readonly error = signal('');
  readonly notice = signal('');
  readonly searched = signal(false);
  readonly selectedFormat = signal<HubFormat>('safetensors');
  readonly availableFiles = computed(() => filesForFormat(this.repository()?.metadata.files ?? [], this.selectedFormat()));
  readonly selectedBytes = computed(() => this.availableFiles().filter(f => this.selectedFiles().includes(f.path)).reduce((n, f) => n + f.size_bytes, 0));
  readonly formats = computed<HubFormat[]>(() => {
    const repo = this.repository();
    if (!repo) return [];
    if (repo.metadata.kind === 'dataset') return ['parquet'];
    return (['safetensors', 'gguf', 'onnx'] as HubFormat[]).filter(format => repo.metadata.files.some(f => f.path.toLowerCase().endsWith(`.${format}`)));
  });
  readonly canImport = computed(() => {
    const repo = this.repository();
    const permissions = this.config();
    return !!repo && !!permissions && !repo.metadata.requires_remote_code
      && repo.license.license_class !== 'blocked'
      && (repo.license.license_class === 'allowed' || repo.license.accepted)
      && (repo.metadata.kind === 'model' ? permissions.can_import_models : permissions.can_import_datasets)
      && hasWeights(this.selectedFiles(), this.selectedFormat());
  });
  endpoint = 'https://huggingface.co';
  token = '';
  clearToken = false;
  platformScope = false;
  kind: HubKind = 'model';
  query = '';
  repoId = '';
  revision = 'main';
  variant = '';
  datasetConfig = 'default';
  datasetSplit = 'train';
  columns = '';
  maxRows: number | null = null;
  datasetName = '';
  licenseChecked = false;
  revokeId = '';
  revokeReason = '';
  exceptionReason = '';
  policyTag = '';
  policyClass: LicenseClass = 'blocked';
  limitKey = '';
  limitValue: number | null = null;
  readonly usageDetails = signal<{ artifactId: string; usages: unknown[] } | null>(null);

  ngOnInit(): void { void this.load(); }
  ngOnDestroy(): void { this.view.destroy(); }

  private reset(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    this.pollTimer = undefined;
    this.searchVersion++;
    this.repositoryVersion++;
    this.config.set(null); this.platformConfig.set(null); this.results.set([]); this.repository.set(null); this.artifacts.set([]);
    this.jobs.set([]); this.lifecycleJobs.set([]); this.selectedFiles.set([]); this.usageDetails.set(null);
    this.busy.set(false); this.searching.set(false); this.inspecting.set(false); this.error.set(''); this.notice.set(''); this.searched.set(false);
    this.endpoint = 'https://huggingface.co'; this.token = ''; this.clearToken = false; this.platformScope = false;
    this.kind = 'model'; this.query = ''; this.repoId = ''; this.revision = 'main'; this.variant = '';
    this.datasetConfig = 'default'; this.datasetSplit = 'train'; this.columns = ''; this.maxRows = null; this.datasetName = '';
    this.licenseChecked = false; this.revokeId = ''; this.revokeReason = '';
    this.exceptionReason = ''; this.policyTag = ''; this.policyClass = 'blocked'; this.limitKey = ''; this.limitValue = null;
  }

  async changeConnectionScope(): Promise<void> {
    this.token = ''; this.clearToken = false;
    if (!this.platformScope) { this.endpoint = this.config()?.connection.endpoint ?? 'https://huggingface.co'; return; }
    if (!this.config()?.can_admin_platform) { this.platformScope = false; return; }
    const request = this.view.captureRequest();
    this.busy.set(true);
    try {
      const config = await firstValueFrom(this.api.get<Pick<HubConfig, 'connection' | 'policy' | 'limits'>>('/huggingface/platform/config', undefined, request.scope));
      if (!this.view.isCurrent(request) || !this.platformScope) return;
      this.platformConfig.set(config); this.endpoint = config.connection.endpoint;
    } catch (error) { if (this.view.isCurrent(request)) { this.error.set(hubError(error)); this.platformScope = false; } }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async refreshArtifacts(): Promise<void> {
    const request = this.view.captureRequest();
    try {
      const result = await firstValueFrom(this.api.get<{ artifacts: HubArtifact[] }>('/huggingface/artifacts', undefined, request.scope));
      if (this.view.isCurrent(request)) this.artifacts.set(result.artifacts);
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
  }

  async grantArtifact(artifact: HubArtifact): Promise<void> {
    if (this.busy() || !(artifact.kind === 'model' ? this.config()?.can_import_models : this.config()?.can_import_datasets)) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      const result = await firstValueFrom(this.api.post<{ artifact: HubArtifact; job: HubJob }>(`/huggingface/artifacts/${encodeURIComponent(artifact.artifact_id)}/grant`, {}, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.artifacts.update(items => items.map(item => item.artifact_id === artifact.artifact_id ? result.artifact : item));
      this.jobs.update(items => [result.job, ...items.filter(job => job.id !== result.job.id)]); this.schedulePoll();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async activateArtifact(artifact: HubArtifact, usage: 'forecasting' | 'embedding'): Promise<void> {
    if (!this.config()?.can_import_models || artifact.status !== 'ready' || !artifact.has_access || this.busy()) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      const result = await firstValueFrom(this.api.post<{ job: HubJob }>(`/huggingface/artifacts/${encodeURIComponent(artifact.artifact_id)}/activate`, { usage, runtime: 'ml' }, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.jobs.update(items => [result.job, ...items.filter(job => job.id !== result.job.id)]); this.schedulePoll();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async load(): Promise<void> {
    const request = this.view.beginRequest();
    this.error.set('');
    try {
      const [config, list, jobs] = await Promise.all([
        firstValueFrom(this.api.get<HubConfig>('/huggingface/config', undefined, request.scope)),
        firstValueFrom(this.api.get<{ artifacts: HubArtifact[] }>('/huggingface/artifacts', undefined, request.scope)),
        firstValueFrom(this.api.get<{ jobs: HubJob[] }>('/huggingface/jobs', undefined, request.scope)),
      ]);
      if (!this.view.isCurrent(request)) return;
      this.config.set(config); this.endpoint = config.connection.endpoint; this.artifacts.set(list.artifacts);
      this.jobs.set(jobs.jobs.filter(job => !job.kind || ['hf_import', 'hf_adapter_activate'].includes(job.kind)));
      this.lifecycleJobs.set(jobs.jobs.filter(job => ['hf_bundle_import', 'hf_bundle_export', 'hf_purge'].includes(job.kind ?? ''))); this.schedulePoll();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
  }

  async savePolicy(): Promise<void> {
    if (!this.config()?.can_configure || this.busy() || !this.policyTag.trim() || (this.platformScope && !this.config()?.can_admin_platform)) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      const policy = (this.platformScope ? this.platformConfig()?.policy : this.config()?.policy) ?? {};
      const overrides = { ...((policy['overrides'] ?? {}) as Record<string, string>), [this.policyTag.trim().toLowerCase()]: this.policyClass };
      await firstValueFrom(this.api.put(`/huggingface/${this.platformScope ? 'platform/' : ''}policy`, { overrides }, request.scope));
      const config = await firstValueFrom(this.api.get<HubConfig>('/huggingface/config', undefined, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.config.set(config); this.notice.set(this.i18n.t('connectors.hf.saved')); this.repository.set(null);
      if (this.platformScope) await this.changeConnectionScope();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async saveLimit(): Promise<void> {
    if (!this.config()?.can_admin_platform || this.busy() || !this.limitKey || !Number.isSafeInteger(this.limitValue) || this.limitValue! <= 0) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      await firstValueFrom(this.api.put('/huggingface/platform/limits', { [this.limitKey]: this.limitValue }, request.scope));
      const config = await firstValueFrom(this.api.get<HubConfig>('/huggingface/config', undefined, request.scope));
      if (this.view.isCurrent(request)) { this.config.set(config); this.notice.set(this.i18n.t('connectors.hf.saved')); }
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async grantLicenseException(): Promise<void> {
    const repo = this.repository();
    if (!repo || !this.config()?.can_admin_platform || !this.exceptionReason.trim() || this.busy()) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      await firstValueFrom(this.api.post('/huggingface/licenses/exception', { kind: repo.metadata.kind, repo_id: repo.metadata.repo_id, revision: repo.metadata.revision, reason: this.exceptionReason.trim() }, request.scope));
      if (this.view.isCurrent(request)) { this.exceptionReason = ''; await this.inspect(repo.metadata.repo_id, repo.metadata.revision); }
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async saveConnection(): Promise<void> {
    if (!this.config()?.can_configure || this.busy() || (this.platformScope && !this.config()?.can_admin_platform)) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set(''); this.notice.set('');
    const values: Record<string, string | boolean> = { endpoint: this.endpoint.trim() };
    if (this.clearToken) values['clear_token'] = true;
    else if (this.token) values['token'] = this.token;
    this.token = '';
    try {
      await firstValueFrom(this.api.put(`/huggingface/${this.platformScope ? 'platform/' : ''}config`, { values }, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.clearToken = false;
      const config = await firstValueFrom(this.api.get<HubConfig>('/huggingface/config', undefined, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.config.set(config); this.notice.set(this.i18n.t('connectors.hf.saved'));
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async testConnection(): Promise<void> {
    if (!this.config()?.can_configure || this.busy()) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set(''); this.notice.set('');
    try {
      const result = await firstValueFrom(this.api.post<{ ok?: boolean; success?: boolean; message?: string }>('/huggingface/test', {}, request.scope));
      if (!this.view.isCurrent(request)) return;
      if (result.ok === false || result.success === false) this.error.set(result.message || this.i18n.t('connectors.hf.test_failed'));
      else this.notice.set(this.i18n.t('connectors.hf.test_ok'));
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  changeKind(): void {
    this.searchVersion++; this.repositoryVersion++;
    this.results.set([]); this.repository.set(null); this.selectedFiles.set([]); this.searched.set(false);
    this.searching.set(false); this.inspecting.set(false); this.repoId = ''; this.revision = 'main'; this.licenseChecked = false;
  }

  async search(): Promise<void> {
    const request = this.view.captureRequest();
    const version = ++this.searchVersion;
    this.searching.set(true); this.error.set('');
    try {
      const list = await firstValueFrom(this.api.get<{ results: HubSearchResult[] }>('/huggingface/search', { kind: this.kind, query: this.query.trim() }, request.scope));
      if (!this.view.isCurrent(request) || version !== this.searchVersion) return;
      this.results.set(list.results); this.searched.set(true);
    } catch (error) { if (this.view.isCurrent(request) && version === this.searchVersion) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request) && version === this.searchVersion) this.searching.set(false); }
  }

  async inspect(repoId = this.repoId, revision = this.revision): Promise<void> {
    if (!repoId.trim()) return;
    const request = this.view.captureRequest();
    const version = ++this.repositoryVersion;
    this.repoId = repoId; this.revision = revision;
    this.repository.set(null); this.selectedFiles.set([]); this.licenseChecked = false; this.variant = '';
    this.inspecting.set(true); this.error.set(''); this.notice.set('');
    try {
      const repository = await firstValueFrom(this.api.get<HubRepository>('/huggingface/repository', { kind: this.kind, repo_id: repoId.trim(), revision: revision.trim() || 'main' }, request.scope));
      if (!this.view.isCurrent(request) || version !== this.repositoryVersion) return;
      this.repository.set(repository); this.chooseFormat(this.formats()[0] || 'safetensors');
    } catch (error) { if (this.view.isCurrent(request) && version === this.repositoryVersion) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request) && version === this.repositoryVersion) this.inspecting.set(false); }
  }

  chooseFormat(format: HubFormat): void {
    this.selectedFormat.set(format); this.variant = '';
    this.selectedFiles.set(defaultSelection(this.repository()?.metadata.files ?? [], format));
  }
  toggleFile(file: HubFile, selected: boolean): void {
    this.selectedFiles.update(files => selected ? [...new Set([...files, file.path])] : files.filter(path => path !== file.path));
  }

  async acceptLicense(): Promise<void> {
    const repo = this.repository();
    if (!repo || !this.config()?.can_configure || !this.licenseChecked || this.busy() || repo.license.license_class !== 'acceptance_required') return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      await firstValueFrom(this.api.post('/huggingface/licenses/accept', { kind: repo.metadata.kind, repo_id: repo.metadata.repo_id, revision: repo.metadata.revision }, request.scope));
      if (!this.view.isCurrent(request) || this.repository() !== repo) return;
      // Refresh server policy: successful acceptance alone cannot loosen a newer policy.
      await this.inspect(repo.metadata.repo_id, repo.metadata.revision);
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async importSelection(): Promise<void> {
    const repo = this.repository();
    if (!repo || !this.canImport() || this.busy()) return;
    const request = this.view.captureRequest();
    const body: HubImport = {
      kind: repo.metadata.kind, repo_id: repo.metadata.repo_id, revision: repo.metadata.revision,
      format: this.selectedFormat(), files: [...this.selectedFiles()],
      ...(this.variant.trim() ? { variant: this.variant.trim() } : {}),
    };
    if (body.kind === 'dataset') {
      body.config = this.datasetConfig.trim(); body.split = this.datasetSplit.trim();
      const columns = this.columns.split(',').map(c => c.trim()).filter(Boolean);
      if (columns.length) body.columns = columns;
      if (this.maxRows != null) body.max_rows = this.maxRows;
      if (this.datasetName.trim()) body.name = this.datasetName.trim();
    }
    this.busy.set(true); this.error.set('');
    try {
      const result = await firstValueFrom(this.api.post<{ artifact: HubArtifact; job: HubJob }>('/huggingface/imports', body, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.artifacts.update(items => [result.artifact, ...items.filter(a => a.artifact_id !== result.artifact.artifact_id)]);
      this.jobs.update(items => [result.job, ...items.filter(j => j.id !== result.job.id)]);
      this.schedulePoll();
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  private schedulePoll(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    if (!this.jobs().some(job => !isTerminalJob(job))) return;
    this.pollTimer = setTimeout(() => void this.pollJobs(), 2000);
  }
  async pollJobs(): Promise<void> {
    const request = this.view.captureRequest();
    this.pollTimer = undefined;
    try {
      const updates = await Promise.all(this.jobs().filter(job => !isTerminalJob(job)).map(job => firstValueFrom(this.api.get<HubJob>(`/huggingface/jobs/${encodeURIComponent(job.id)}`, undefined, request.scope))));
      if (!this.view.isCurrent(request)) return;
      this.jobs.update(items => items.map(job => updates.find(update => update.id === job.id) ?? job));
      if (updates.some(isTerminalJob)) {
        const list = await firstValueFrom(this.api.get<{ artifacts: HubArtifact[] }>('/huggingface/artifacts', undefined, request.scope));
        if (!this.view.isCurrent(request)) return;
        this.artifacts.set(list.artifacts);
      }
      this.schedulePoll();
    } catch (error) {
      if (this.view.isCurrent(request)) this.error.set(hubError(error));
      // Leave a manual retry on connectivity failures instead of hiding a polling loop.
    }
  }

  async revokeGrant(): Promise<void> {
    if (!this.config()?.can_configure || !this.revokeId || !this.revokeReason.trim() || this.busy()) return;
    const request = this.view.captureRequest();
    this.busy.set(true); this.error.set('');
    try {
      await firstValueFrom(this.api.post(`/huggingface/artifacts/${encodeURIComponent(this.revokeId)}/revoke-grant`, { reason: this.revokeReason.trim() }, request.scope));
      if (!this.view.isCurrent(request)) return;
      this.revokeId = ''; this.revokeReason = '';
      const list = await firstValueFrom(this.api.get<{ artifacts: HubArtifact[] }>('/huggingface/artifacts', undefined, request.scope));
      if (this.view.isCurrent(request)) this.artifacts.set(list.artifacts);
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
    finally { if (this.view.isCurrent(request)) this.busy.set(false); }
  }

  async showUsages(artifact: HubArtifact): Promise<void> {
    const request = this.view.captureRequest();
    try {
      const result = await firstValueFrom(this.api.get<{ usages: unknown[] }>(`/huggingface/artifacts/${encodeURIComponent(artifact.artifact_id)}/usages`, undefined, request.scope));
      if (this.view.isCurrent(request)) this.usageDetails.set({ artifactId: artifact.artifact_id, usages: result.usages });
    } catch (error) { if (this.view.isCurrent(request)) this.error.set(hubError(error)); }
  }

  readonly jobError = jobError;
  readonly terminal = isTerminalJob;
  bytes(value: number): string {
    if (!value) return '0 B';
    const unit = Math.min(3, Math.floor(Math.log(value) / Math.log(1024)));
    return `${(value / 1024 ** unit).toLocaleString(this.i18n.locale(), { maximumFractionDigits: 1 })} ${['B', 'KiB', 'MiB', 'GiB'][unit]}`;
  }
}
