import { CommonModule } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
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
  content_type?: string | null;
  size_bytes: number;
  sha256: string;
  status: 'received' | 'rejected' | 'promoted';
  uploaded_at: string | null;
  promoted_at: string | null;
  promoted_collection_slug?: string | null;
  worker_job_id: string | null;
  promotion_result?: Record<string, unknown> | null;
  rejection_reason?: string | null;
}

interface QueueItem {
  kind: 'folder' | 'file';
  key: string;
  name: string;
  path: string;
  count: number;
  sizeBytes: number;
  file?: DepositFile;
}

interface FolderCrumb {
  label: string;
  path: string;
}

interface DepositPreview {
  kind: 'text' | 'spreadsheet' | 'image' | 'pdf' | 'binary';
  filename: string;
  content_type: string;
  size_bytes: number;
  download_url: string;
  content?: string;
  rows?: string[][];
  sheet_name?: string;
  truncated?: boolean;
  reason?: string;
}

interface SecureDepositHealth {
  status: string;
  workspace: string;
  enabled: boolean;
  default_allowed_extensions: string[];
}

interface WorkspaceJob {
  id: string;
  kind: string;
  title: string;
  status: 'created' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  stage: string;
  error?: string | null;
  input_ref?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
  poll_url?: string;
}

interface SftpLiveUpload {
  id: string;
  temp_name: string;
  filename: string;
  access_id: string;
  link_id?: string | null;
  link_label?: string | null;
  workspace_id: string;
  size_bytes: number;
  max_bytes: number;
  created_at: string;
  modified_at: string;
  age_seconds: number;
  idle_seconds: number;
  status: 'receiving' | 'idle' | 'stale_candidate';
  attributed: boolean;
  actionable: boolean;
}

interface SftpOperationsSummary {
  active_count: number;
  idle_count: number;
  stale_count: number;
  temporary_count: number;
  temporary_size_bytes: number;
  unattributed_partial_count: number;
  unattributed_partial_size_bytes: number;
  last_received_at: string | null;
  last_received_filename: string | null;
  deposit_counts?: Record<string, { count: number; size_bytes: number }>;
  link_count: number;
}

interface SftpReconciliationSummary {
  mode?: string | null;
  status?: string | null;
  stale_after_hours?: number | null;
  stale_partials?: number;
  orphan_files?: number;
  missing_db_files?: number;
  pending_rows?: number;
  unattributed_partials?: number;
  stale_partial_bytes?: number;
  orphan_file_bytes?: number;
  generated_at?: string | null;
  confirm_from_job_id?: string | null;
}

interface SftpOperations {
  stale_after_hours: number;
  poll_interval_seconds: number;
  active_uploads: SftpLiveUpload[];
  stale_partials: SftpLiveUpload[];
  storage_summary: SftpOperationsSummary;
  reconciliation_summary: SftpReconciliationSummary;
  last_jobs: WorkspaceJob[];
}

type QueueStatusFilter = 'received' | 'rejected' | 'promoted' | 'all';

interface QueueStatusSummary {
  status: QueueStatusFilter;
  label: string;
  count: number;
  sizeBytes: number;
}

const DEFAULT_QUEUE_PAGE_SIZE = 100;
const BULK_PROMOTE_LIMIT = 25;

@Component({
  selector: 'app-sftp-connector',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, DrawerComponent, IconComponent, SectionHeaderComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-section-header
      breadcrumb="Connectors"
      title="SFTP / Secure Deposit"
      icon="inbox"
      [subtitle]="'Create external drop links for ' + workspaceName() + '. Files land in this workspace staging queue until manually promoted to Knowledge.'"
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

    @if (health() && !secureDepositEnabled()) {
      <div class="mb-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-100 ring-1 ring-amber-400/25">
        Secure Deposit is not enabled for {{ workspaceName() }}. Existing queues and links remain workspace-scoped; enable the capability before creating external upload links here.
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

    <section class="grid min-w-0 grid-cols-1 gap-5 2xl:grid-cols-[360px_minmax(0,1fr)]">
      <div class="min-w-0 space-y-5 2xl:max-w-[360px]">
        <section class="t-card t-elevated rounded-md p-5">
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">New external access</p>
          <h2 class="mt-1 text-base font-semibold text-white">Create deposit link</h2>
          <form class="mt-4 space-y-4" (ngSubmit)="createLink()">
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Label</span>
              <input
                name="label"
                [(ngModel)]="draftLabel"
                [disabled]="!secureDepositEnabled()"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                [placeholder]="workspaceName() + ' external upload'"
              />
            </label>
            <div class="grid grid-cols-2 gap-3">
              <label class="block min-w-0">
                <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Max MB</span>
                <input
                  name="max"
                  type="number"
                  min="1"
                  max="30720"
                  [(ngModel)]="draftMaxMb"
                  [disabled]="!secureDepositEnabled()"
                  class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                />
              </label>
              <label class="block min-w-0">
                <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Expires</span>
                <input
                  name="expires"
                  type="date"
                  [(ngModel)]="draftExpires"
                  [disabled]="!secureDepositEnabled()"
                  class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                />
              </label>
            </div>
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Extensions</span>
              <input
                name="extensions"
                [(ngModel)]="draftExtensions"
                [disabled]="!secureDepositEnabled()"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                placeholder="Leave empty for all file types"
              />
              <span class="mt-1 block text-xs text-gray-500">Leave empty to accept ZIP and any other extension.</span>
            </label>
            <button
              type="submit"
              class="inline-flex w-full items-center justify-center gap-2 rounded bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-400 disabled:opacity-50"
              [disabled]="saving() || !secureDepositEnabled()"
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

      <div class="min-w-0 space-y-5">
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
                      <button type="button" class="rounded bg-white/5 px-3 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 hover:bg-white/10" (click)="focusLinkQueue(link.id)">
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
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">SFTP operations</p>
              <h2 class="mt-1 text-sm font-semibold text-white">Live uploads and reconciliation</h2>
              <p class="mt-1 text-xs text-gray-500">Workspace-scoped SFTP telemetry and cleanup jobs.</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <label class="flex items-center gap-2 text-xs text-gray-400">
                <span>Stale after</span>
                <input
                  type="number"
                  min="1"
                  max="720"
                  name="staleAfterHours"
                  [(ngModel)]="staleAfterHours"
                  class="w-20 rounded bg-black/30 border border-white/10 px-2 py-1.5 text-xs text-white focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                />
                <span>h</span>
              </label>
              <button
                type="button"
                class="inline-flex items-center justify-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-semibold text-gray-100 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
                [disabled]="operationsLoading()"
                (click)="loadOperations()"
              >
                <app-icon name="refresh-cw" [size]="13" [class.animate-spin]="operationsLoading()" />
                Refresh ops
              </button>
              <button
                type="button"
                class="inline-flex items-center justify-center gap-1.5 rounded bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-100 ring-1 ring-cyan-500/20 hover:bg-cyan-500/15 disabled:opacity-40"
                [disabled]="reconciliationRunning()"
                (click)="runReconciliationCheck()"
              >
                <app-icon name="shield-check" [size]="13" />
                Run check
              </button>
              <button
                type="button"
                class="inline-flex items-center justify-center gap-1.5 rounded bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-100 ring-1 ring-amber-500/20 hover:bg-amber-500/15 disabled:opacity-40"
                [disabled]="reconciliationRunning() || quarantineCandidateCount() <= 0"
                (click)="quarantineFromDryRun()"
              >
                <app-icon name="archive" [size]="13" />
                Move to quarantine
              </button>
            </div>
          </div>

          @if (operationsError()) {
            <div class="border-b border-white/5 px-5 py-3 text-sm text-red-100 bg-red-500/10">
              {{ operationsError() }}
            </div>
          }

          <div class="grid gap-3 border-b border-white/5 px-5 py-4 md:grid-cols-2 xl:grid-cols-5">
            @if (operationsSummary(); as summary) {
              <div class="rounded bg-white/[0.03] p-3 ring-1 ring-white/10">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Receiving</p>
                <p class="mt-1 text-lg font-semibold text-white">{{ summary.active_count }}</p>
                <p class="text-[11px] text-gray-500">{{ formatBytes(summary.temporary_size_bytes) }} temp</p>
              </div>
              <div class="rounded bg-white/[0.03] p-3 ring-1 ring-white/10">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Idle</p>
                <p class="mt-1 text-lg font-semibold text-white">{{ summary.idle_count }}</p>
                <p class="text-[11px] text-gray-500">{{ summary.stale_count }} stale</p>
              </div>
              <div class="rounded bg-white/[0.03] p-3 ring-1 ring-white/10">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Unattributed</p>
                <p class="mt-1 text-lg font-semibold text-white">{{ summary.unattributed_partial_count }}</p>
                <p class="text-[11px] text-gray-500">{{ formatBytes(summary.unattributed_partial_size_bytes) }}</p>
              </div>
              <div class="rounded bg-white/[0.03] p-3 ring-1 ring-white/10">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Last received</p>
                <p class="mt-1 truncate text-sm font-semibold text-white">{{ summary.last_received_filename || 'None' }}</p>
                <p class="text-[11px] text-gray-500">{{ summary.last_received_at ? (summary.last_received_at | date:'short') : 'No file yet' }}</p>
              </div>
              <div class="rounded bg-white/[0.03] p-3 ring-1 ring-white/10">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Last check</p>
                <p class="mt-1 text-lg font-semibold text-white">{{ latestReconciliation().orphan_files || 0 }}</p>
                <p class="text-[11px] text-gray-500">orphans · {{ latestReconciliation().stale_partials || 0 }} stale</p>
              </div>
            } @else {
              <div class="col-span-full rounded bg-white/[0.03] p-4 text-sm text-gray-500 ring-1 ring-white/10">
                Operations snapshot is loading.
              </div>
            }
          </div>

          <div class="grid gap-4 px-5 py-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(280px,0.6fr)]">
            <div class="min-w-0">
              <div class="mb-3 flex items-center justify-between">
                <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-300">Live uploads</h3>
                <span class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ liveUploads().length }} tracked</span>
              </div>
              @if (liveUploads().length === 0) {
                <div class="rounded bg-white/[0.03] p-4 text-sm text-gray-500 ring-1 ring-white/10">
                  No temporary upload currently attributed to this workspace.
                </div>
              } @else {
                <ul class="max-h-72 divide-y divide-white/5 overflow-auto rounded ring-1 ring-white/10">
                  @for (upload of liveUploads(); track upload.id) {
                    <li class="grid gap-3 bg-black/10 px-3 py-3 lg:grid-cols-[minmax(0,1fr)_130px_110px_120px] lg:items-center">
                      <div class="min-w-0">
                        <p class="truncate text-sm font-semibold text-white">{{ upload.filename }}</p>
                        <p class="mt-1 truncate font-mono text-[10px] text-gray-500">{{ upload.temp_name }}</p>
                        <p class="mt-1 truncate text-[11px] text-gray-500">{{ upload.link_label || 'Unknown link' }}</p>
                      </div>
                      <span class="rounded px-2 py-1 text-[11px] ring-1" [class]="uploadStatusClass(upload.status)">
                        {{ uploadStatusLabel(upload.status) }}
                      </span>
                      <span class="text-xs text-gray-400">{{ formatBytes(upload.size_bytes) }}</span>
                      <span class="text-xs text-gray-400">idle {{ formatDuration(upload.idle_seconds) }}</span>
                    </li>
                  }
                </ul>
              }
            </div>
            <div class="min-w-0">
              <div class="mb-3 flex items-center justify-between">
                <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-300">Reconciliation</h3>
                @if (lastDryRunJob(); as dryJob) {
                  <span class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ dryJob.completed_at ? (dryJob.completed_at | date:'short') : dryJob.status }}</span>
                }
              </div>
              <div class="rounded bg-white/[0.03] p-4 ring-1 ring-white/10">
                @if (lastDryRunJob(); as dryJob) {
                  <p class="text-sm font-semibold text-white">Dry-run {{ dryJob.status }}</p>
                  <p class="mt-2 text-xs text-gray-400">
                    {{ quarantineCandidateCount() }} quarantine candidate{{ quarantineCandidateCount() === 1 ? '' : 's' }}
                    · {{ formatBytes(quarantineCandidateBytes()) }}
                  </p>
                  <div class="mt-3 grid grid-cols-2 gap-2 text-[11px] text-gray-400">
                    <span>Stale partials</span>
                    <span class="text-right font-mono">{{ resultCount(dryJob, 'stale_partials') }}</span>
                    <span>Orphan files</span>
                    <span class="text-right font-mono">{{ resultCount(dryJob, 'orphan_files') }}</span>
                    <span>Missing DB files</span>
                    <span class="text-right font-mono">{{ resultCount(dryJob, 'missing_db_files') }}</span>
                    <span>Pending rows</span>
                    <span class="text-right font-mono">{{ resultCount(dryJob, 'pending_rows') }}</span>
                  </div>
                } @else {
                  <p class="text-sm font-semibold text-white">No dry-run yet</p>
                  <p class="mt-2 text-xs text-gray-500">No completed reconciliation check for this workspace.</p>
                }
                @if (lastOperationsJobs().length > 0) {
                  <div class="mt-4 border-t border-white/10 pt-3">
                    <p class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500">Recent jobs</p>
                    <ul class="space-y-1.5">
                      @for (job of lastOperationsJobs().slice(0, 3); track job.id) {
                        <li class="flex items-center justify-between gap-3 text-[11px] text-gray-400">
                          <span class="truncate">{{ job.input_ref?.['mode'] || job.title }}</span>
                          <span class="rounded px-1.5 py-0.5 font-mono ring-1" [ngClass]="job.status === 'completed' ? 'text-emerald-200 ring-emerald-500/20 bg-emerald-500/10' : job.status === 'failed' ? 'text-red-200 ring-red-500/20 bg-red-500/10' : 'text-cyan-200 ring-cyan-500/20 bg-cyan-500/10'">
                            {{ job.status }}
                          </span>
                        </li>
                      }
                    </ul>
                  </div>
                }
              </div>
            </div>
          </div>
        </section>

        <section class="t-card t-elevated rounded-md overflow-hidden">
          <div class="flex flex-col gap-4 border-b border-white/5 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Workspace staging queue</p>
              <h2 class="mt-1 text-sm font-semibold text-white">{{ workspaceName() }} received files</h2>
              <p class="mt-1 text-xs text-gray-500">Files from all visible deposit links stay here until manual promotion.</p>
            </div>
            <div class="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
              <button
                type="button"
                class="inline-flex w-full items-center justify-center gap-1.5 rounded bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-100 ring-1 ring-emerald-500/20 hover:bg-emerald-500/15 disabled:opacity-40 sm:w-auto"
                [disabled]="bulkEligibleFiles().length === 0 || bulkPromoting() || saving()"
                (click)="promoteBatch()"
                title="Promote up to 25 received Knowledge-supported files from the current folder or search view."
              >
                <app-icon name="archive-restore" [size]="13" />
                {{ bulkPromoting() ? 'Promoting batch' : 'Promote batch' }}
                @if (bulkEligibleFiles().length > 0) {
                  <span class="rounded bg-emerald-400/15 px-1.5 py-0.5 font-mono text-[10px]">{{ bulkEligibleFiles().length }}</span>
                }
              </button>
              <button
                type="button"
                class="inline-flex w-full items-center justify-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-semibold text-gray-100 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40 sm:w-auto"
                [disabled]="filteredFiles().length === 0 || statusFilter() === 'rejected' || downloading()"
                (click)="downloadArchive()"
              >
                <app-icon name="download" [size]="13" />
                {{ downloading() ? 'Preparing ZIP' : 'Download ZIP' }}
              </button>
              <label class="relative min-w-0 sm:w-64">
                <span class="sr-only">Search staged files</span>
                <app-icon name="search" [size]="13" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                <input
                  type="search"
                  name="queueSearch"
                  [ngModel]="queueSearch()"
                  (ngModelChange)="setQueueSearch($event)"
                  class="w-full rounded bg-black/30 border border-white/10 py-2 pl-8 pr-3 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-400/60"
                  placeholder="Search path or checksum"
                />
              </label>
              <label class="min-w-0 sm:w-40">
                <span class="sr-only">Filter staging queue by status</span>
                <select
                  name="queueStatusFilter"
                  [ngModel]="statusFilter()"
                  (ngModelChange)="setStatusFilter($event)"
                  class="sftp-select w-full"
                >
                  <option value="received">Received</option>
                  <option value="rejected">Rejected</option>
                  <option value="promoted">Promoted</option>
                  <option value="all">All statuses</option>
                </select>
              </label>
              <label class="min-w-0 sm:w-56">
                <span class="sr-only">Filter staging queue by deposit link</span>
                <select
                  name="queueFilter"
                  [ngModel]="selectedLinkId()"
                  (ngModelChange)="setSelectedLink($event)"
                  class="sftp-select w-full"
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
          <div class="flex flex-col gap-3 border-b border-white/5 px-5 py-3 lg:flex-row lg:items-center lg:justify-between">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              @for (summary of queueStatusSummaries(); track summary.status) {
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-[11px] font-semibold ring-1 transition"
                  [ngClass]="statusSummaryClass(summary.status, statusFilter() === summary.status)"
                  (click)="setStatusFilter(summary.status)"
                  [title]="summary.label + ': ' + summary.count + ' files · ' + formatBytes(summary.sizeBytes)"
                >
                  <span>{{ summary.label }}</span>
                  <span class="font-mono">{{ summary.count }}</span>
                  <span class="font-mono text-[10px] opacity-70">{{ formatBytes(summary.sizeBytes) }}</span>
                </button>
              }
            </div>
            <div class="flex min-w-0 flex-wrap items-center gap-2 text-[11px] text-gray-500">
              @if (hiddenByStatusCount() > 0) {
                <span class="rounded bg-amber-500/10 px-2 py-1 text-amber-100 ring-1 ring-amber-500/20">
                  {{ hiddenByStatusCount() }} hidden by status filter
                </span>
                <button
                  type="button"
                  class="rounded px-2 py-1 text-gray-300 ring-1 ring-white/10 hover:bg-white/5"
                  (click)="setStatusFilter('all')"
                >
                  Show all
                </button>
              }
              <span class="truncate">
                Scope: {{ scopedFiles().length }} files · {{ formatBytes(scopeSizeBytes()) }}
              </span>
            </div>
          </div>
          @if (files().length === 0) {
            <div class="p-8 text-center text-sm text-gray-500">No staged files.</div>
          } @else {
            <div class="flex flex-col gap-3 border-b border-white/5 px-5 py-3 lg:flex-row lg:items-center lg:justify-between">
              <nav class="flex min-w-0 flex-wrap items-center gap-1.5 text-xs" aria-label="Staging folder path">
                @for (crumb of folderCrumbs(); track crumb.path) {
                  <button
                    type="button"
                    class="rounded px-2 py-1 text-gray-300 ring-1 ring-white/10 hover:bg-white/5 hover:text-white"
                    [ngClass]="crumb.path === currentFolder() ? 'bg-white/10' : ''"
                    (click)="goToFolder(crumb.path)"
                  >
                    {{ crumb.label }}
                  </button>
                  @if (!$last) {
                    <app-icon name="chevron-right" [size]="12" class="text-gray-600" />
                  }
                }
              </nav>
              <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                @if (queueSearch().trim()) {
                  <span>Search results across the selected queue</span>
                  <button type="button" class="rounded px-2 py-1 text-gray-300 ring-1 ring-white/10 hover:bg-white/5" (click)="clearQueueSearch()">Clear search</button>
                } @else if (currentFolder()) {
                  <button type="button" class="rounded px-2 py-1 text-gray-300 ring-1 ring-white/10 hover:bg-white/5" (click)="goToParentFolder()">
                    <app-icon name="arrow-left" [size]="12" /> Up
                  </button>
                } @else {
                  <span>Browse folders before promoting individual files.</span>
                }
                <span class="rounded bg-white/5 px-2 py-1 text-gray-300 ring-1 ring-white/10">
                  {{ queueRangeLabel() }}
                </span>
                <label class="sr-only" for="queuePageSize">Rows per page</label>
                <select
                  id="queuePageSize"
                  name="queuePageSize"
                  [ngModel]="queuePageSize()"
                  (ngModelChange)="setQueuePageSize($event)"
                  class="sftp-select sftp-select-sm"
                >
                  @for (size of pageSizeOptions; track size) {
                    <option [value]="size">{{ size }} / page</option>
                  }
                </select>
                <button
                  type="button"
                  class="rounded px-2 py-1 text-gray-300 ring-1 ring-white/10 hover:bg-white/5 disabled:opacity-40"
                  [disabled]="currentQueuePage() <= 1"
                  (click)="previousQueuePage()"
                >
                  <app-icon name="chevron-left" [size]="12" /> Prev
                </button>
                <span class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">
                  Page {{ currentQueuePage() }} / {{ totalQueuePages() }}
                </span>
                <button
                  type="button"
                  class="rounded px-2 py-1 text-gray-300 ring-1 ring-white/10 hover:bg-white/5 disabled:opacity-40"
                  [disabled]="currentQueuePage() >= totalQueuePages()"
                  (click)="nextQueuePage()"
                >
                  Next <app-icon name="chevron-right" [size]="12" />
                </button>
              </div>
            </div>
            <ul class="divide-y divide-white/5">
              @for (item of visibleQueueItems(); track item.key) {
                <li class="px-5 py-4">
                  @if (item.kind === 'folder') {
                    <button
                      type="button"
                      class="grid w-full gap-4 text-left xl:grid-cols-[minmax(0,1.4fr)_180px_120px] xl:items-center"
                      (click)="openFolder(item.path)"
                    >
                      <div class="flex min-w-0 items-center gap-3">
                        <span class="inline-flex h-9 w-9 items-center justify-center rounded bg-cyan-500/10 text-cyan-200 ring-1 ring-cyan-500/20">
                          <app-icon name="folder" [size]="17" />
                        </span>
                        <span class="min-w-0">
                          <span class="block truncate text-sm font-semibold text-white">{{ item.name }}</span>
                          <span class="mt-1 block truncate font-mono text-[10px] text-gray-500">{{ item.path }}</span>
                        </span>
                      </div>
                      <span class="text-xs text-gray-400">{{ item.count }} files</span>
                      <span class="flex items-center justify-end gap-2 text-xs text-gray-400">
                        {{ formatBytes(item.sizeBytes) }}
                        <app-icon name="chevron-right" [size]="14" />
                      </span>
                    </button>
                  } @else if (item.file; as file) {
                    <div class="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(180px,0.75fr)_132px_112px_220px] xl:items-center">
                      <div class="min-w-0">
                        <h3 class="truncate text-sm font-semibold text-white">{{ item.name }}</h3>
                        <p class="mt-1 truncate font-mono text-[10px] text-gray-500">{{ item.path }}</p>
                        <p class="mt-1 truncate font-mono text-[10px] text-gray-600">{{ file.sha256 }}</p>
                        @if (file.status === 'promoted' && file.promoted_collection_slug) {
                          <p class="mt-1 truncate text-[11px] text-emerald-300/80">
                            Indexed target · {{ file.promoted_collection_slug }}
                            @if (promotionIndexingStatus(file); as indexingStatus) {
                              <span class="font-mono text-emerald-200/70">· {{ indexingStatus }}</span>
                            }
                          </p>
                        }
                        @if (file.status === 'rejected' && file.rejection_reason) {
                          <p class="mt-1 line-clamp-2 text-[11px] text-amber-200/80">
                            {{ file.rejection_reason }}
                          </p>
                        }
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
                      <div class="flex flex-wrap items-center gap-2 xl:justify-end">
                        <button
                          type="button"
                          class="inline-flex h-8 w-8 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10 hover:text-brand-300 disabled:opacity-40"
                          title="Preview file"
                          [disabled]="file.status === 'rejected'"
                          (click)="previewFile(file)"
                        >
                          <app-icon name="eye" [size]="13" />
                        </button>
                        <button
                          type="button"
                          class="inline-flex h-8 w-8 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10 hover:text-brand-300 disabled:opacity-40"
                          title="Download file"
                          [disabled]="file.status === 'rejected' || downloadingFileId() === file.id"
                          (click)="downloadFile(file)"
                        >
                          <app-icon name="download" [size]="13" />
                        </button>
                        <button
                          type="button"
                          class="inline-flex h-8 items-center justify-center gap-1.5 rounded bg-emerald-500/10 px-3 text-xs font-semibold text-emerald-200 ring-1 ring-emerald-500/20 hover:bg-emerald-500/15 disabled:opacity-40"
                          [disabled]="file.status !== 'received' || saving()"
                          (click)="promote(file)"
                        >
                          <app-icon name="archive-restore" [size]="13" />
                          {{ file.status === 'promoted' ? 'Promoted' : 'Promote' }}
                        </button>
                      </div>
                    </div>
                  }
                </li>
              } @empty {
                <li class="p-8 text-center text-sm text-gray-500">
                  @if (queueSearch().trim()) {
                    No files match this search.
                  } @else {
                    No files in this folder.
                  }
                </li>
              }
            </ul>
          }
        </section>
      </div>
    </section>

    <app-drawer
      [open]="previewOpen()"
      [title]="previewFileTarget()?.filename ?? 'File preview'"
      subtitle="Secure Deposit staging"
      icon="eye"
      [width]="760"
      (close)="closePreview()"
    >
      @if (previewLoading()) {
        <div class="space-y-2">
          @for (_ of [0, 1, 2, 3, 4, 5, 6]; track $index) {
            <div class="h-3 rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      } @else if (previewError()) {
        <div class="rounded bg-red-500/10 p-3 text-sm text-red-100 ring-1 ring-red-500/20">{{ previewError() }}</div>
      } @else if (previewData(); as preview) {
        <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold text-white">{{ basename(preview.filename) }}</p>
            <p class="mt-1 font-mono text-[11px] text-gray-500">{{ preview.content_type }} · {{ formatBytes(preview.size_bytes) }}</p>
          </div>
          <button
            type="button"
            class="inline-flex items-center justify-center gap-1.5 rounded bg-brand-500 px-3 py-2 text-xs font-semibold text-white hover:bg-brand-400"
            (click)="previewFileTarget() && downloadFile(previewFileTarget()!)"
          >
            <app-icon name="download" [size]="13" /> Download
          </button>
        </div>

        @if (preview.kind === 'text') {
          @if (preview.truncated) {
            <p class="mb-2 rounded bg-amber-500/10 px-3 py-2 text-xs text-amber-100 ring-1 ring-amber-500/20">Preview truncated to the first megabyte.</p>
          }
          <pre class="max-h-[70vh] overflow-auto rounded bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-gray-200 whitespace-pre-wrap ring-1 ring-white/10">{{ preview.content }}</pre>
        } @else if (preview.kind === 'spreadsheet') {
          <div class="mb-2 flex items-center justify-between text-xs text-gray-400">
            <span>Sheet: {{ preview.sheet_name || 'Sheet 1' }}</span>
            @if (preview.truncated) {
              <span class="rounded bg-amber-500/10 px-2 py-1 text-amber-100 ring-1 ring-amber-500/20">Preview truncated</span>
            }
          </div>
          <div class="max-h-[70vh] overflow-auto rounded ring-1 ring-white/10">
            <table class="min-w-full border-collapse text-left text-xs">
              <tbody>
                @for (row of preview.rows || []; track $index) {
                  <tr class="border-b border-white/5 odd:bg-white/[0.02]">
                    @for (cell of row; track $index) {
                      <td class="max-w-[220px] truncate px-3 py-2 text-gray-200">{{ cell || ' ' }}</td>
                    }
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else if (preview.kind === 'image' && previewObjectUrl()) {
          <div class="max-h-[70vh] overflow-auto rounded bg-black/30 p-2 ring-1 ring-white/10">
            <img [src]="previewObjectUrl()!" [alt]="preview.filename" class="mx-auto max-h-[68vh] max-w-full object-contain" />
          </div>
        } @else if (preview.kind === 'pdf' && previewPdfUrl()) {
          <iframe [src]="previewPdfUrl()!" class="h-[70vh] w-full rounded bg-black/30 ring-1 ring-white/10"></iframe>
        } @else {
          <div class="rounded bg-white/5 p-4 text-sm text-gray-300 ring-1 ring-white/10">
            Inline preview is not available for this file type or size. Download the file to inspect it locally.
          </div>
        }
      }
    </app-drawer>
  `,
  styles: [`
    .sftp-select {
      appearance: none;
      min-height: 2.25rem;
      border-radius: 0.375rem;
      border: 1px solid rgba(255, 255, 255, 0.1);
      background-color: rgba(2, 6, 23, 0.72);
      background-image:
        linear-gradient(45deg, transparent 50%, rgba(148, 163, 184, 0.9) 50%),
        linear-gradient(135deg, rgba(148, 163, 184, 0.9) 50%, transparent 50%);
      background-position:
        calc(100% - 15px) 50%,
        calc(100% - 10px) 50%;
      background-size: 5px 5px, 5px 5px;
      background-repeat: no-repeat;
      color: #e5e7eb;
      font-size: 0.75rem;
      line-height: 1rem;
      padding: 0.5rem 2rem 0.5rem 0.75rem;
    }

    .sftp-select-sm {
      min-height: 1.75rem;
      padding: 0.25rem 1.75rem 0.25rem 0.625rem;
      font-size: 0.6875rem;
    }

    .sftp-select:focus {
      outline: none;
      border-color: rgba(103, 232, 249, 0.42);
      box-shadow: 0 0 0 1px rgba(103, 232, 249, 0.24);
    }
  `],
})
export class SftpConnectorComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly toast = inject(ToastrService);

  readonly health = signal<SecureDepositHealth | null>(null);
  readonly workspaceName = computed(() => this.workspace.current()?.name || this.workspace.currentSlug() || 'current workspace');
  readonly workspaceSlug = computed(() => this.workspace.current()?.slug || this.workspace.currentSlug() || 'workspace');
  readonly secureDepositEnabled = computed(() => this.health()?.enabled ?? false);
  readonly links = signal<DepositLink[]>([]);
  readonly files = signal<DepositFile[]>([]);
  readonly secretLink = signal<DepositLink | null>(null);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly bulkPromoting = signal(false);
  readonly downloading = signal(false);
  readonly downloadingFileId = signal<string | null>(null);
  readonly operations = signal<SftpOperations | null>(null);
  readonly operationsLoading = signal(false);
  readonly operationsError = signal<string | null>(null);
  readonly reconciliationRunning = signal(false);
  readonly error = signal<string | null>(null);
  readonly previewOpen = signal(false);
  readonly previewLoading = signal(false);
  readonly previewError = signal<string | null>(null);
  readonly previewFileTarget = signal<DepositFile | null>(null);
  readonly previewData = signal<DepositPreview | null>(null);
  readonly previewObjectUrl = signal<string | null>(null);
  readonly previewPdfUrl = signal<SafeResourceUrl | null>(null);
  readonly selectedLinkId = signal('');
  readonly currentFolder = signal('');
  readonly queueSearch = signal('');
  readonly statusFilter = signal<QueueStatusFilter>('received');
  readonly queuePage = signal(1);
  readonly queuePageSize = signal(DEFAULT_QUEUE_PAGE_SIZE);
  readonly pageSizeOptions = [50, 100, 300];
  readonly linkLookup = computed(() => new Map(this.links().map((link) => [link.id, link])));
  readonly linkFilteredFiles = computed(() => {
    const selected = this.selectedLinkId();
    return this.files().filter((file) => !selected || file.access_link_id === selected);
  });
  readonly scopedFiles = computed(() =>
    this.filesInCurrentScope(this.linkFilteredFiles(), this.currentFolder(), this.queueSearch()),
  );
  readonly queueStatusSummaries = computed(() => this.buildStatusSummaries(this.scopedFiles()));
  readonly hiddenByStatusCount = computed(() => {
    const status = this.statusFilter();
    if (status === 'all') return 0;
    return this.scopedFiles().filter((file) => file.status !== status).length;
  });
  readonly filteredFiles = computed(() => {
    const status = this.statusFilter();
    return this.linkFilteredFiles().filter((file) => {
      const statusMatches = status === 'all' || file.status === status;
      return statusMatches;
    });
  });
  readonly queueItems = computed(() => this.buildQueueItems(this.filteredFiles(), this.currentFolder(), this.queueSearch()));
  readonly totalQueuePages = computed(() => Math.max(1, Math.ceil(this.queueItems().length / this.queuePageSize())));
  readonly currentQueuePage = computed(() => Math.min(Math.max(1, this.queuePage()), this.totalQueuePages()));
  readonly visibleQueueItems = computed(() => {
    const start = (this.currentQueuePage() - 1) * this.queuePageSize();
    return this.queueItems().slice(start, start + this.queuePageSize());
  });
  readonly bulkEligibleFiles = computed(() =>
    this.queueItems()
      .map((item) => item.file)
      .filter((file): file is DepositFile => {
        if (!file) return false;
        return file.status === 'received' && this.isKnowledgePromotable(file);
      })
      .slice(0, BULK_PROMOTE_LIMIT),
  );
  readonly queueRangeLabel = computed(() => {
    const total = this.queueItems().length;
    if (total === 0) return '0 rows';
    const start = (this.currentQueuePage() - 1) * this.queuePageSize() + 1;
    const end = Math.min(total, start + this.visibleQueueItems().length - 1);
    return `${start}-${end} of ${total} rows`;
  });
  readonly folderCrumbs = computed<FolderCrumb[]>(() => {
    const parts = this.currentFolder().split('/').filter(Boolean);
    const crumbs: FolderCrumb[] = [{ label: 'Root', path: '' }];
    parts.reduce((path, part) => {
      const next = path ? `${path}/${part}` : part;
      crumbs.push({ label: part, path: next });
      return next;
    }, '');
    return crumbs;
  });
  readonly liveUploads = computed(() => this.operations()?.active_uploads || []);
  readonly operationsSummary = computed(() => this.operations()?.storage_summary || null);
  readonly lastOperationsJobs = computed(() => this.operations()?.last_jobs || []);
  readonly lastDryRunJob = computed(() =>
    this.lastOperationsJobs().find((job) => job.status === 'completed' && String(job.input_ref?.['mode'] || '') === 'dry_run') || null,
  );
  readonly latestReconciliation = computed(() => this.operations()?.reconciliation_summary || {});
  readonly quarantineCandidateCount = computed(() => {
    const result = this.lastDryRunJob()?.result || {};
    const counts = (result['counts'] as Record<string, unknown> | undefined) || {};
    return Number(counts['stale_partials'] || 0) + Number(counts['orphan_files'] || 0);
  });
  readonly quarantineCandidateBytes = computed(() => {
    const result = this.lastDryRunJob()?.result || {};
    const sizes = (result['sizes'] as Record<string, unknown> | undefined) || {};
    return Number(sizes['stale_partial_bytes'] || 0) + Number(sizes['orphan_file_bytes'] || 0);
  });

  draftLabel = '';
  draftMaxMb = 30720;
  draftExpires = '';
  draftExtensions = '';
  collectionSlug = '';
  staleAfterHours = 24;
  private operationsPollId: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    this.resetWorkspaceDefaults();
    this.load();
    this.operationsPollId = setInterval(() => this.loadOperations(true), 5000);
  }

  ngOnDestroy(): void {
    if (this.operationsPollId) {
      clearInterval(this.operationsPollId);
      this.operationsPollId = null;
    }
    this.revokePreviewObjectUrl();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.get<SecureDepositHealth>('/sftp/health').subscribe({
      next: (res) => this.health.set(res),
      error: () => this.health.set(null),
    });
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
    this.loadOperations(true);
  }

  loadOperations(silent = false): void {
    if (!silent) {
      this.operationsLoading.set(true);
    }
    this.operationsError.set(null);
    this.api
      .get<SftpOperations>('/sftp/operations', { stale_after_hours: String(this.staleAfterHours || 24) })
      .subscribe({
        next: (res) => {
          this.operations.set(res);
          this.operationsLoading.set(false);
        },
        error: (err) => {
          this.operationsError.set(this.errorMessage(err, 'Unable to load SFTP operations.'));
          this.operationsLoading.set(false);
        },
      });
  }

  runReconciliationCheck(): void {
    this.reconciliationRunning.set(true);
    this.api
      .post<{ job: WorkspaceJob }>('/sftp/operations/reconcile', {
        mode: 'dry_run',
        stale_after_hours: Number(this.staleAfterHours) || 24,
      })
      .subscribe({
        next: (res) => {
          this.toast.info(`Reconciliation ${res.job.status}`, 'SFTP Operations');
          this.reconciliationRunning.set(false);
          this.loadOperations();
        },
        error: (err) => {
          this.toast.error(this.errorMessage(err, 'Unable to start reconciliation.'), 'SFTP Operations');
          this.reconciliationRunning.set(false);
        },
      });
  }

  quarantineFromDryRun(): void {
    const job = this.lastDryRunJob();
    if (!job || this.quarantineCandidateCount() <= 0) {
      this.toast.info('Run a reconciliation check before moving files to quarantine.', 'SFTP Operations');
      return;
    }
    const accepted = window.confirm(
      `Move ${this.quarantineCandidateCount()} stale/orphan item(s) (${this.formatBytes(this.quarantineCandidateBytes())}) to quarantine?\n\nNo active upload or recent file will be touched.`,
    );
    if (!accepted) return;
    this.reconciliationRunning.set(true);
    this.api
      .post<{ job: WorkspaceJob }>('/sftp/operations/reconcile', {
        mode: 'quarantine',
        stale_after_hours: Number(this.staleAfterHours) || 24,
        confirm_from_job_id: job.id,
      })
      .subscribe({
        next: (res) => {
          this.toast.success(`Quarantine ${res.job.status}`, 'SFTP Operations');
          this.reconciliationRunning.set(false);
          this.loadOperations();
        },
        error: (err) => {
          this.toast.error(this.errorMessage(err, 'Unable to move files to quarantine.'), 'SFTP Operations');
          this.reconciliationRunning.set(false);
        },
      });
  }

  createLink(): void {
    if (!this.secureDepositEnabled()) {
      this.toast.error('Secure Deposit is not enabled for this workspace.', 'Secure Deposit');
      return;
    }
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
        collection_slug: this.collectionSlug || this.defaultCollectionSlug(),
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

  promoteBatch(): void {
    const files = this.bulkEligibleFiles();
    if (!files.length) {
      this.toast.info('No received Knowledge-supported files in the current view.', 'Secure Deposit');
      return;
    }
    const collection = this.collectionSlug || this.defaultCollectionSlug();
    const accepted = window.confirm(
      `Promote ${files.length} Knowledge-supported files from the current view to "${collection}"?\n\nA single Knowledge worker job will index the batch. Unsupported files such as legacy .xls remain in staging.`,
    );
    if (!accepted) return;

    this.bulkPromoting.set(true);
    this.api
      .post<{ files: DepositFile[]; skipped: { file_id: string; filename: string; reason: string }[]; result: { job_id?: string } }>(
        '/sftp/deposits/promote-bulk',
        {
          collection_slug: collection,
          file_ids: files.map((file) => file.id),
        },
      )
      .subscribe({
        next: (res) => {
          const skipped = res.skipped?.length ? `, ${res.skipped.length} skipped` : '';
          this.toast.success(`${res.files?.length || files.length} files queued${skipped}`, 'Secure Deposit');
          this.bulkPromoting.set(false);
          this.load();
        },
        error: (err) => {
          this.toast.error(this.errorMessage(err, 'Unable to promote batch'), 'Secure Deposit');
          this.bulkPromoting.set(false);
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
    if (this.statusFilter() !== 'all') {
      params = params.set('status', this.statusFilter());
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

  previewFile(file: DepositFile): void {
    this.revokePreviewObjectUrl();
    this.previewOpen.set(true);
    this.previewLoading.set(true);
    this.previewError.set(null);
    this.previewFileTarget.set(file);
    this.previewData.set(null);
    this.api.get<DepositPreview>(`/sftp/deposits/${file.id}/preview`).subscribe({
      next: (preview) => {
        this.previewData.set(preview);
        if (preview.kind === 'image' || preview.kind === 'pdf') {
          this.loadPreviewBlob(file, preview.kind);
          return;
        }
        this.previewLoading.set(false);
      },
      error: (err) => {
        this.previewError.set(this.errorMessage(err, 'Unable to load file preview.'));
        this.previewLoading.set(false);
      },
    });
  }

  closePreview(): void {
    this.previewOpen.set(false);
    this.previewLoading.set(false);
    this.previewFileTarget.set(null);
    this.previewData.set(null);
    this.previewError.set(null);
    this.revokePreviewObjectUrl();
  }

  downloadFile(file: DepositFile): void {
    this.downloadingFileId.set(file.id);
    this.http
      .get(`${this.api.base}/sftp/deposits/${file.id}/download`, {
        observe: 'response',
        responseType: 'blob',
      })
      .subscribe({
        next: (response) => {
          const blob = response.body;
          if (!blob) {
            this.toast.error('Empty file response', 'Secure Deposit');
            this.downloadingFileId.set(null);
            return;
          }
          this.saveBlob(blob, this.responseFilename(response.headers.get('content-disposition'), this.basename(file.filename)));
          this.downloadingFileId.set(null);
        },
        error: (err) => {
          this.toast.error(this.errorMessage(err, 'Unable to download file.'), 'Secure Deposit');
          this.downloadingFileId.set(null);
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

  setSelectedLink(linkId: string): void {
    this.selectedLinkId.set(linkId);
    this.resetQueueViewport();
  }

  setStatusFilter(status: string): void {
    const next = ['received', 'rejected', 'promoted', 'all'].includes(status)
      ? (status as QueueStatusFilter)
      : 'received';
    this.statusFilter.set(next);
    this.resetQueueViewport();
  }

  setQueueSearch(value: string): void {
    this.queueSearch.set(value);
    this.queuePage.set(1);
  }

  setQueuePageSize(size: number | string): void {
    const parsed = Number(size) || DEFAULT_QUEUE_PAGE_SIZE;
    this.queuePageSize.set(parsed);
    this.queuePage.set(1);
  }

  previousQueuePage(): void {
    this.queuePage.set(Math.max(1, this.currentQueuePage() - 1));
  }

  nextQueuePage(): void {
    this.queuePage.set(Math.min(this.totalQueuePages(), this.currentQueuePage() + 1));
  }

  focusLinkQueue(linkId: string): void {
    this.setSelectedLink(linkId);
  }

  openFolder(path: string): void {
    this.currentFolder.set(path);
    this.queueSearch.set('');
    this.queuePage.set(1);
  }

  goToFolder(path: string): void {
    this.currentFolder.set(path);
    this.queueSearch.set('');
    this.queuePage.set(1);
  }

  goToParentFolder(): void {
    const current = this.currentFolder();
    const index = current.lastIndexOf('/');
    this.currentFolder.set(index > -1 ? current.slice(0, index) : '');
    this.queuePage.set(1);
  }

  clearQueueSearch(): void {
    this.queueSearch.set('');
    this.queuePage.set(1);
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

  uploadStatusLabel(status: SftpLiveUpload['status']): string {
    if (status === 'stale_candidate') return 'Stale candidate';
    if (status === 'idle') return 'Idle';
    return 'Receiving';
  }

  uploadStatusClass(status: SftpLiveUpload['status']): string {
    if (status === 'stale_candidate') return 'bg-amber-500/10 text-amber-100 ring-amber-500/25';
    if (status === 'idle') return 'bg-white/5 text-gray-200 ring-white/10';
    return 'bg-cyan-500/10 text-cyan-200 ring-cyan-500/25';
  }

  formatDuration(seconds: number): string {
    const safe = Math.max(0, Number(seconds) || 0);
    if (safe < 60) return `${safe}s`;
    const minutes = Math.floor(safe / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    if (hours < 48) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
  }

  resultCount(job: WorkspaceJob, key: string): number {
    const result = job.result || {};
    const counts = (result['counts'] as Record<string, unknown> | undefined) || {};
    return Number(counts[key] || 0);
  }

  statusSummaryClass(status: QueueStatusFilter, active: boolean): string {
    const base = active ? 'ring-white/25' : 'ring-white/10 hover:bg-white/5';
    if (status === 'all') return `${base} ${active ? 'bg-white/10 text-white' : 'bg-white/[0.03] text-gray-300'}`;
    if (status === 'received') return `${base} ${active ? 'bg-cyan-500/20 text-cyan-100' : 'bg-cyan-500/10 text-cyan-200'}`;
    if (status === 'promoted') return `${base} ${active ? 'bg-emerald-500/20 text-emerald-100' : 'bg-emerald-500/10 text-emerald-200'}`;
    return `${base} ${active ? 'bg-red-500/20 text-red-100' : 'bg-red-500/10 text-red-200'}`;
  }

  scopeSizeBytes(): number {
    return this.scopedFiles().reduce((sum, file) => sum + (file.size_bytes || 0), 0);
  }

  promotionIndexingStatus(file: DepositFile): string | null {
    const result = file.promotion_result || {};
    const value =
      result['indexing_status'] ||
      (result['indexing'] as Record<string, unknown> | undefined)?.['status'] ||
      (result['worker'] as Record<string, unknown> | undefined)?.['status'];
    return typeof value === 'string' && value.trim() ? value.trim() : null;
  }

  basename(path: string): string {
    const parts = path.split('/').filter(Boolean);
    return parts.at(-1) || path || 'upload';
  }

  private loadPreviewBlob(file: DepositFile, kind: 'image' | 'pdf'): void {
    this.http
      .get(`${this.api.base}/sftp/deposits/${file.id}/download`, {
        params: new HttpParams().set('disposition', 'inline'),
        responseType: 'blob',
      })
      .subscribe({
        next: (blob) => {
          const url = URL.createObjectURL(blob);
          this.previewObjectUrl.set(url);
          this.previewPdfUrl.set(kind === 'pdf' ? this.sanitizer.bypassSecurityTrustResourceUrl(url) : null);
          this.previewLoading.set(false);
        },
        error: (err) => {
          this.previewError.set(this.errorMessage(err, 'Unable to load inline preview.'));
          this.previewLoading.set(false);
        },
      });
  }

  private revokePreviewObjectUrl(): void {
    const url = this.previewObjectUrl();
    if (url) URL.revokeObjectURL(url);
    this.previewObjectUrl.set(null);
    this.previewPdfUrl.set(null);
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
      : `${this.defaultCollectionSlug()}-staging.zip`;
    return this.responseFilename(disposition, fallback);
  }

  private resetWorkspaceDefaults(): void {
    if (!this.draftLabel.trim()) {
      this.draftLabel = `${this.workspaceName()} external upload`;
    }
    if (!this.collectionSlug.trim()) {
      this.collectionSlug = this.defaultCollectionSlug();
    }
  }

  private resetQueueViewport(): void {
    this.currentFolder.set('');
    this.queueSearch.set('');
    this.queuePage.set(1);
  }

  private defaultCollectionSlug(): string {
    return `${this.slugify(this.workspaceSlug())}-secure-deposit`;
  }

  private responseFilename(disposition: string | null, fallback: string): string {
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

  private buildQueueItems(files: DepositFile[], folder: string, query: string): QueueItem[] {
    const q = query.trim().toLowerCase();
    if (q) {
      return files
        .filter((file) => {
          const path = this.filePath(file);
          return path.toLowerCase().includes(q) || file.sha256?.toLowerCase().includes(q);
        })
        .sort((a, b) => this.filePath(a).localeCompare(this.filePath(b)))
        .map((file) => this.fileItem(file, this.filePath(file)));
    }

    const folders = new Map<string, QueueItem>();
    const directFiles: QueueItem[] = [];
    const prefix = folder ? `${folder}/` : '';

    for (const file of files) {
      const path = this.filePath(file);
      if (folder && path !== folder && !path.startsWith(prefix)) continue;
      const remainder = folder ? path.slice(prefix.length) : path;
      if (!remainder) continue;
      const [head, ...rest] = remainder.split('/');
      if (rest.length > 0) {
        const folderPath = prefix ? `${folder}/${head}` : head;
        const item = folders.get(folderPath) ?? {
          kind: 'folder',
          key: `folder:${folderPath}`,
          name: head,
          path: folderPath,
          count: 0,
          sizeBytes: 0,
        };
        item.count += 1;
        item.sizeBytes += file.size_bytes || 0;
        folders.set(folderPath, item);
      } else {
        directFiles.push(this.fileItem(file, path));
      }
    }

    return [
      ...Array.from(folders.values()).sort((a, b) => a.name.localeCompare(b.name)),
      ...directFiles.sort((a, b) => a.name.localeCompare(b.name)),
    ];
  }

  private filesInCurrentScope(files: DepositFile[], folder: string, query: string): DepositFile[] {
    const q = query.trim().toLowerCase();
    if (q) {
      return files.filter((file) => {
        const path = this.filePath(file);
        return path.toLowerCase().includes(q) || file.sha256?.toLowerCase().includes(q);
      });
    }
    if (!folder) return files;
    const prefix = `${folder}/`;
    return files.filter((file) => {
      const path = this.filePath(file);
      return path === folder || path.startsWith(prefix);
    });
  }

  private buildStatusSummaries(files: DepositFile[]): QueueStatusSummary[] {
    const initial: Record<QueueStatusFilter, QueueStatusSummary> = {
      all: { status: 'all', label: 'All', count: 0, sizeBytes: 0 },
      received: { status: 'received', label: 'Received', count: 0, sizeBytes: 0 },
      promoted: { status: 'promoted', label: 'Promoted', count: 0, sizeBytes: 0 },
      rejected: { status: 'rejected', label: 'Rejected', count: 0, sizeBytes: 0 },
    };
    for (const file of files) {
      const size = file.size_bytes || 0;
      initial.all.count += 1;
      initial.all.sizeBytes += size;
      initial[file.status].count += 1;
      initial[file.status].sizeBytes += size;
    }
    return [initial.all, initial.received, initial.promoted, initial.rejected];
  }

  private fileItem(file: DepositFile, path: string): QueueItem {
    return {
      kind: 'file',
      key: `file:${file.id}`,
      name: this.basename(path),
      path,
      count: 1,
      sizeBytes: file.size_bytes || 0,
      file,
    };
  }

  private filePath(file: DepositFile): string {
    return (file.filename || 'upload').replace(/\\/g, '/').split('/').filter(Boolean).join('/');
  }

  private isKnowledgePromotable(file: DepositFile): boolean {
    return [
      'csv',
      'html',
      'htm',
      'json',
      'log',
      'markdown',
      'md',
      'pdf',
      'rst',
      'txt',
      'xml',
      'xlsx',
      'xlsm',
      'xltm',
      'xltx',
      'yaml',
      'yml',
      'zip',
    ].includes(this.extension(file.filename));
  }

  private extension(path: string): string {
    const name = this.basename(path).toLowerCase();
    const index = name.lastIndexOf('.');
    return index > -1 ? name.slice(index + 1) : '';
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
