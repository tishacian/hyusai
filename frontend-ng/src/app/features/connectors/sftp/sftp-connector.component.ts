import { CommonModule } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

interface DepositLink {
  id: string;
  label: string;
  access_id: string;
  public_url: string;
  status: string;
  expires_at: string | null;
  max_file_size_mb: number;
  allowed_extensions: string[];
  created_at: string | null;
  created_by_user_id: string;
  created_by?: string | null;
  generated_password?: string | null;
}

interface DepositFile {
  id: string;
  access_link_id: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  status: 'received' | 'rejected' | 'promoted';
  uploaded_at: string | null;
  promoted_at: string | null;
  promoted_collection_slug?: string | null;
  worker_job_id: string | null;
}

@Component({
  selector: 'app-sftp-connector',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, IconComponent, SectionHeaderComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-section-header
      breadcrumb="Connectors"
      title="SFTP / Secure Deposit"
      icon="inbox"
      subtitle="Create external drop links for Andritz. Files land in staging until manually promoted to Knowledge."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="load()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        Refresh
      </button>
      <a
        routerLink="/resources"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back to Resources
      </a>
    </app-section-header>

    @if (error()) {
      <div class="mb-4 rounded-md bg-red-500/10 p-3 text-sm text-red-100 ring-1 ring-red-400/25">
        {{ error() }}
      </div>
    }

    @if (secretLink(); as link) {
      <section class="mb-5 rounded-md bg-cyan-500/10 p-4 ring-1 ring-cyan-400/30">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div class="min-w-0">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Share once</p>
            <h2 class="mt-1 text-sm font-semibold text-white">{{ link.label }}</h2>
            <p class="mt-2 break-all font-mono text-xs text-cyan-100">{{ absoluteUrl(link.public_url) }}</p>
            <p class="mt-2 break-all font-mono text-xs text-amber-100">Password: {{ link.generated_password }}</p>
          </div>
          <div class="flex shrink-0 flex-wrap gap-2">
            <button type="button" class="rounded bg-white/10 px-3 py-2 text-xs text-white ring-1 ring-white/15 hover:bg-white/15" (click)="copy(absoluteUrl(link.public_url), 'URL copied')">
              <app-icon name="copy" [size]="13" /> URL
            </button>
            <button type="button" class="rounded bg-white/10 px-3 py-2 text-xs text-white ring-1 ring-white/15 hover:bg-white/15" (click)="copy(link.generated_password || '', 'Password copied')">
              <app-icon name="copy" [size]="13" /> Password
            </button>
            <button type="button" class="rounded bg-black/20 px-3 py-2 text-xs text-gray-200 ring-1 ring-white/10 hover:bg-black/30" (click)="secretLink.set(null)">
              Hide
            </button>
          </div>
        </div>
      </section>
    }

    <section class="grid grid-cols-1 gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
      <div class="space-y-5">
        <section class="t-card t-elevated rounded-md p-5">
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">New external access</p>
          <h2 class="mt-1 text-base font-semibold text-white">Create deposit link</h2>
          <form class="mt-4 space-y-4" (ngSubmit)="createLink()">
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Label</span>
              <input
                name="label"
                [(ngModel)]="draftLabel"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                placeholder="Andritz supplier upload"
              />
            </label>
            <div class="grid grid-cols-2 gap-3">
              <label class="block">
                <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Max MB</span>
                <input
                  name="max"
                  type="number"
                  min="1"
                  max="30720"
                  [(ngModel)]="draftMaxMb"
                  class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Expires</span>
                <input
                  name="expires"
                  type="date"
                  [(ngModel)]="draftExpires"
                  class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                />
              </label>
            </div>
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Extensions</span>
              <input
                name="extensions"
                [(ngModel)]="draftExtensions"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                placeholder="Leave empty for all file types"
              />
              <span class="mt-1 block text-xs text-gray-500">Leave empty to accept ZIP and any other extension.</span>
            </label>
            <button
              type="submit"
              class="inline-flex w-full items-center justify-center gap-2 rounded bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-400 disabled:opacity-50"
              [disabled]="saving()"
            >
              <app-icon name="plus" [size]="15" />
              Create link
            </button>
          </form>
        </section>

        <section class="t-card t-elevated rounded-md p-5">
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Promotion target</p>
          <label class="mt-3 block">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Collection slug</span>
            <input
              name="collection"
              [(ngModel)]="collectionSlug"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand-400/60"
            />
          </label>
        </section>
      </div>

      <div class="space-y-5">
        <section class="t-card t-elevated rounded-md overflow-hidden">
          <div class="flex items-center justify-between border-b border-white/5 px-5 py-4">
            <h2 class="text-sm font-semibold text-white">Deposit links</h2>
            <span class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ links().length }} links</span>
          </div>
          @if (links().length === 0) {
            <div class="p-8 text-center text-sm text-gray-500">No deposit links yet.</div>
          } @else {
            <ul class="divide-y divide-white/5">
              @for (link of links(); track link.id) {
                <li class="px-5 py-4">
                  <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div class="min-w-0">
                      <div class="flex items-center gap-2">
                        <h3 class="truncate text-sm font-semibold text-white">{{ link.label }}</h3>
                        <span class="rounded px-2 py-0.5 text-[10px] ring-1" [class]="link.status === 'active' ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20' : 'bg-white/5 text-gray-400 ring-white/10'">
                          {{ link.status }}
                        </span>
                      </div>
                      <p class="mt-1 truncate font-mono text-[11px] text-gray-500">{{ absoluteUrl(link.public_url) }}</p>
                    </div>
                    <div class="flex shrink-0 flex-wrap gap-2">
                      <button type="button" class="rounded bg-white/5 px-3 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 hover:bg-white/10" (click)="copy(absoluteUrl(link.public_url), 'URL copied')">
                        <app-icon name="copy" [size]="12" /> Copy URL
                      </button>
                      <button type="button" class="rounded bg-white/5 px-3 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 hover:bg-white/10" (click)="selectedLinkId.set(link.id)">
                        <app-icon name="list-filter" [size]="12" /> Queue
                      </button>
                      <button type="button" class="rounded bg-white/5 px-3 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 hover:bg-white/10" (click)="rotate(link)">
                        <app-icon name="rotate-cw" [size]="12" /> Rotate
                      </button>
                      <button type="button" class="rounded bg-red-500/10 px-3 py-1.5 text-xs text-red-200 ring-1 ring-red-500/20 hover:bg-red-500/15" (click)="revoke(link)" [disabled]="link.status !== 'active'">
                        <app-icon name="x-circle" [size]="12" /> Revoke
                      </button>
                    </div>
                  </div>
                </li>
              }
            </ul>
          }
        </section>

        <section class="t-card t-elevated rounded-md overflow-hidden">
          <div class="flex flex-col gap-4 border-b border-white/5 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Workspace staging queue</p>
              <h2 class="mt-1 text-sm font-semibold text-white">Andritz-wide received files</h2>
              <p class="mt-1 text-xs text-gray-500">Files from all visible deposit links stay here until manual promotion.</p>
            </div>
            <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
              <button
                type="button"
                class="inline-flex items-center justify-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-semibold text-gray-100 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
                [disabled]="filteredFiles().length === 0 || downloading()"
                (click)="downloadArchive()"
              >
                <app-icon name="download" [size]="13" />
                {{ downloading() ? 'Preparing ZIP' : 'Download ZIP' }}
              </button>
              <label class="min-w-[220px]">
                <span class="sr-only">Filter staging queue by deposit link</span>
                <select
                  name="queueFilter"
                  [ngModel]="selectedLinkId()"
                  (ngModelChange)="selectedLinkId.set($event)"
                  class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-xs text-gray-200 focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                >
                  <option value="">All deposit links</option>
                  @for (link of links(); track link.id) {
                    <option [value]="link.id">{{ link.label }}</option>
                  }
                </select>
              </label>
              <span class="ck-mono whitespace-nowrap text-[10px] uppercase tracking-wider text-gray-500">
                {{ filteredFiles().length }} / {{ files().length }} files
              </span>
            </div>
          </div>
          @if (files().length === 0) {
            <div class="p-8 text-center text-sm text-gray-500">No staged files.</div>
          } @else {
            <ul class="divide-y divide-white/5">
              @for (file of filteredFiles(); track file.id) {
                <li class="px-5 py-4">
                  <div class="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(180px,0.8fr)_132px_112px_120px] xl:items-center">
                    <div class="min-w-0">
                      <h3 class="truncate text-sm font-semibold text-white">{{ file.filename }}</h3>
                      <p class="mt-1 truncate font-mono text-[10px] text-gray-500">{{ file.sha256 }}</p>
                    </div>
                    <div class="min-w-0">
                      <p class="truncate text-xs font-medium text-gray-200">{{ linkLabel(file.access_link_id) }}</p>
                      <p class="mt-1 truncate text-[11px] text-gray-500">Created by {{ linkCreator(file.access_link_id) }}</p>
                    </div>
                    <div class="text-xs text-gray-400">
                      <span class="block text-[10px] uppercase tracking-wider text-gray-600 xl:hidden">Uploaded</span>
                      {{ file.uploaded_at ? (file.uploaded_at | date:'short') : 'Unknown' }}
                    </div>
                    <div class="flex items-center gap-3 xl:justify-end">
                      <span class="rounded px-2 py-1 text-[11px] ring-1" [class]="statusClass(file.status)">
                        {{ file.status }}
                      </span>
                      <span class="text-xs text-gray-400">{{ formatBytes(file.size_bytes) }}</span>
                    </div>
                    <button
                      type="button"
                      class="inline-flex items-center justify-center gap-1.5 rounded bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-200 ring-1 ring-emerald-500/20 hover:bg-emerald-500/15 disabled:opacity-40"
                      [disabled]="file.status !== 'received' || saving()"
                      (click)="promote(file)"
                    >
                      <app-icon name="archive-restore" [size]="13" />
                      {{ file.status === 'promoted' ? 'Promoted' : 'Promote' }}
                    </button>
                  </div>
                </li>
              } @empty {
                <li class="p-8 text-center text-sm text-gray-500">No files for this deposit link.</li>
              }
            </ul>
          }
        </section>
      </div>
    </section>
  `,
})
export class SftpConnectorComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly http = inject(HttpClient);
  private readonly toast = inject(ToastrService);

  readonly links = signal<DepositLink[]>([]);
  readonly files = signal<DepositFile[]>([]);
  readonly secretLink = signal<DepositLink | null>(null);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly downloading = signal(false);
  readonly error = signal<string | null>(null);
  readonly selectedLinkId = signal('');
  readonly linkLookup = computed(() => new Map(this.links().map((link) => [link.id, link])));
  readonly filteredFiles = computed(() => {
    const selected = this.selectedLinkId();
    if (!selected) return this.files();
    return this.files().filter((file) => file.access_link_id === selected);
  });

  draftLabel = 'Andritz external upload';
  draftMaxMb = 30720;
  draftExpires = '';
  draftExtensions = '';
  collectionSlug = 'andritz-secure-deposit';

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.get<{ links: DepositLink[] }>('/sftp/links').subscribe({
      next: (res) => {
        this.links.set(res.links || []);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(this.errorMessage(err, 'Unable to load deposit links.'));
        this.loading.set(false);
      },
    });
    this.api.get<{ files: DepositFile[] }>('/sftp/deposits').subscribe({
      next: (res) => this.files.set(res.files || []),
      error: () => this.files.set([]),
    });
  }

  createLink(): void {
    this.saving.set(true);
    this.api
      .post<{ link: DepositLink }>('/sftp/links', {
        label: this.draftLabel || 'External deposit',
        expires_at: this.draftExpires ? new Date(`${this.draftExpires}T23:59:59`).toISOString() : null,
        max_file_size_mb: Number(this.draftMaxMb) || 100,
        allowed_extensions: this.parseExtensions(),
      })
      .subscribe({
        next: (res) => {
          this.secretLink.set(res.link);
          this.toast.success('Deposit link created', 'Secure Deposit');
          this.saving.set(false);
          this.load();
        },
        error: (err) => {
          this.error.set(this.errorMessage(err, 'Unable to create deposit link.'));
          this.saving.set(false);
        },
      });
  }

  rotate(link: DepositLink): void {
    this.saving.set(true);
    this.api.post<{ link: DepositLink }>(`/sftp/links/${link.id}/rotate`, {}).subscribe({
      next: (res) => {
        this.secretLink.set(res.link);
        this.toast.info('Password rotated', 'Secure Deposit');
        this.saving.set(false);
        this.load();
      },
      error: () => {
        this.toast.error('Unable to rotate password', 'Secure Deposit');
        this.saving.set(false);
      },
    });
  }

  revoke(link: DepositLink): void {
    this.saving.set(true);
    this.api.post<{ link: DepositLink }>(`/sftp/links/${link.id}/revoke`, {}).subscribe({
      next: () => {
        this.toast.info('Deposit link revoked', 'Secure Deposit');
        this.saving.set(false);
        this.load();
      },
      error: () => {
        this.toast.error('Unable to revoke link', 'Secure Deposit');
        this.saving.set(false);
      },
    });
  }

  promote(file: DepositFile): void {
    this.saving.set(true);
    this.api
      .post<{ file: DepositFile }>(`/sftp/deposits/${file.id}/promote`, {
        collection_slug: this.collectionSlug || 'andritz-secure-deposit',
      })
      .subscribe({
        next: () => {
          this.toast.success('File promoted to Knowledge ingestion', 'Secure Deposit');
          this.saving.set(false);
          this.load();
        },
        error: (err) => {
          this.toast.error(this.errorMessage(err, 'Unable to promote file'), 'Secure Deposit');
          this.saving.set(false);
        },
      });
  }

  downloadArchive(): void {
    this.downloading.set(true);
    this.error.set(null);
    let params = new HttpParams();
    if (this.selectedLinkId()) {
      params = params.set('link_id', this.selectedLinkId());
    }
    this.http
      .get(`${this.api.base}/sftp/deposits/archive`, {
        params,
        observe: 'response',
        responseType: 'blob',
      })
      .subscribe({
        next: (response) => {
          const blob = response.body;
          if (!blob) {
            this.toast.error('Empty archive response', 'Secure Deposit');
            this.downloading.set(false);
            return;
          }
          this.saveBlob(blob, this.archiveFilename(response.headers.get('content-disposition')));
          this.toast.success('Archive download started', 'Secure Deposit');
          this.downloading.set(false);
        },
        error: (err) => {
          this.error.set(this.errorMessage(err, 'Unable to download staging archive.'));
          this.downloading.set(false);
        },
      });
  }

  absoluteUrl(url: string): string {
    return new URL(url, window.location.origin).href;
  }

  copy(value: string, label: string): void {
    navigator.clipboard?.writeText(value).then(
      () => this.toast.success(label, 'Clipboard'),
      () => this.toast.error('Copy failed', 'Clipboard'),
    );
  }

  formatBytes(size: number): string {
    if (!size) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
    return `${(size / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
  }

  linkLabel(linkId: string): string {
    return this.linkLookup().get(linkId)?.label || 'Unknown deposit link';
  }

  linkCreator(linkId: string): string {
    return this.linkLookup().get(linkId)?.created_by || 'unknown';
  }

  statusClass(status: DepositFile['status']): string {
    if (status === 'received') return 'bg-cyan-500/10 text-cyan-200 ring-cyan-500/25';
    if (status === 'promoted') return 'bg-emerald-500/10 text-emerald-200 ring-emerald-500/25';
    return 'bg-red-500/10 text-red-200 ring-red-500/25';
  }

  private saveBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  private archiveFilename(disposition: string | null): string {
    const fallback = this.selectedLinkId()
      ? `${this.slugify(this.linkLabel(this.selectedLinkId()))}-staging.zip`
      : 'andritz-secure-deposit-staging.zip';
    if (!disposition) return fallback;
    const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    if (encoded?.[1]) return decodeURIComponent(encoded[1].replace(/"/g, ''));
    const quoted = /filename="?([^";]+)"?/i.exec(disposition);
    return quoted?.[1] || fallback;
  }

  private slugify(value: string): string {
    return value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'secure-deposit';
  }

  private parseExtensions(): string[] {
    return this.draftExtensions
      .split(',')
      .map((item) => item.trim().toLowerCase().replace(/^\./, ''))
      .filter(Boolean);
  }

  private errorMessage(err: unknown, fallback: string): string {
    const detail = (err as { error?: { detail?: unknown; message?: unknown } })?.error?.detail;
    const message = (err as { error?: { message?: unknown } })?.error?.message;
    const value = detail ?? message;
    if (!value) return fallback;
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) {
      return value
        .map((item) => {
          if (typeof item === 'string') return item;
          const entry = item as { loc?: unknown[]; msg?: string };
          const where = Array.isArray(entry.loc) ? entry.loc.join('.') : '';
          return where && entry.msg ? `${where}: ${entry.msg}` : entry.msg || JSON.stringify(item);
        })
        .join(' | ');
    }
    if (typeof value === 'object') {
      const body = value as { message?: string; msg?: string; detail?: string };
      return body.message || body.msg || body.detail || JSON.stringify(value);
    }
    return String(value);
  }
}
