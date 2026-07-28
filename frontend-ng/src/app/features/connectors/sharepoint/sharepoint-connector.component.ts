/**
 * SharePoint connector page — Vague E / E4.1 (scope commun E4a + E4b).
 *
 * One UI, two auth modes:
 *  - **Standard (OAuth)** → `auth_mode='msal'`. Requires an Entra ID app
 *    with admin-consented delegated permissions on the tenant. MSAL
 *    refresh is silent server-side; operator just supplies client_id +
 *    tenant_host + (optional) user_hint.
 *  - **Guest Link (OTP)** → `auth_mode='session'`. For clients where IT
 *    cannot consent an app (type Andritz). Operator captures a
 *    Playwright `storage_state` on their laptop via the CLI and uploads
 *    it here; backend re-encrypts it with Fernet and re-plays it.
 *
 * Responsibilities:
 *  1. Guide the operator to the right mode via a clear binary question.
 *  2. Upload session JSON (Guest Link) or validate client_id/tenant
 *     (Standard).
 *  3. Trigger a sync → watch progress live.
 *  4. Surface ingest result (how many files landed in the RAG collection).
 *  5. Show the last 20 jobs for the workspace.
 *
 * RAG wiring: syncs ingest into `collection_name` (default "documents"),
 * the same collection the drop-and-ask flow reads from. User asks
 * questions → chat sees the SharePoint files without re-configuring
 * anything. See `_ingest_downloaded_files` in
 * `backend/app/api/v1/endpoints/sharepoint.py`.
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { WorkspaceService } from '@app/core/workspace.service';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  SharePointAuthMode,
  SharePointJobSummary,
  SharePointSessionStatus,
  SharepointApiService,
} from './sharepoint.service';

type UiMode = 'guest_link' | 'oauth';

@Component({
  selector: 'app-sharepoint-connector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    IconComponent,
    SectionHeaderComponent,
    EmptyStateComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Connectors"
      title="Microsoft SharePoint"
      icon="folder"
      subtitle="Ingest a shared folder into the RAG pipeline. Two auth modes: Standard (OAuth / admin consent) or Guest Link (OTP captured locally)."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="refreshJobs()"
        [disabled]="jobsLoading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="jobsLoading()" />
        Refresh jobs
      </button>
      <a
        routerLink="/resources"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back to Resources
      </a>
    </app-section-header>

    <div class="grid grid-cols-1 xl:grid-cols-3 gap-5">
      <!-- Left: mode picker + configuration -->
      <div class="xl:col-span-2 space-y-5">
        <!-- Mode picker -->
        <section class="ck-surface t-elevated rounded-md p-5">
          <header class="flex items-center gap-2 mb-4">
            <h2 class="text-sm font-semibold text-white">Authentication mode</h2>
            <span class="text-[10px] font-mono text-gray-500">one per session_key</span>
          </header>
          <p class="text-[12px] text-gray-400 mb-4 leading-relaxed">
            Has your client's IT consented an Entra ID app for {{ brand() }} on their tenant?
          </p>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <button
              type="button"
              (click)="setMode('oauth')"
              class="group rounded-md p-4 text-left ring-1 transition"
              [class.bg-cyan-500\\/10]="uiMode() === 'oauth'"
              [class.ring-cyan-500\\/40]="uiMode() === 'oauth'"
              [class.bg-black\\/20]="uiMode() !== 'oauth'"
              [class.ring-white\\/10]="uiMode() !== 'oauth'"
            >
              <div class="flex items-center gap-2 mb-2">
                <app-icon name="shield-check" [size]="16" class="text-emerald-400" />
                <span class="text-sm font-semibold text-white">Standard (OAuth)</span>
              </div>
              <p class="text-[11px] text-gray-400 leading-relaxed">
                Client IT registered an app with <span class="font-mono text-gray-300">Sites.Read.All</span>,
                admin consent accepted. Silent refresh, no recapture needed.
              </p>
            </button>
            <button
              type="button"
              (click)="setMode('guest_link')"
              class="group rounded-md p-4 text-left ring-1 transition"
              [class.bg-cyan-500\\/10]="uiMode() === 'guest_link'"
              [class.ring-cyan-500\\/40]="uiMode() === 'guest_link'"
              [class.bg-black\\/20]="uiMode() !== 'guest_link'"
              [class.ring-white\\/10]="uiMode() !== 'guest_link'"
            >
              <div class="flex items-center gap-2 mb-2">
                <app-icon name="key-round" [size]="16" class="text-amber-400" />
                <span class="text-sm font-semibold text-white">Guest Link (OTP)</span>
              </div>
              <p class="text-[11px] text-gray-400 leading-relaxed">
                Sharing URL + OTP mail + Authenticator. Capture the session locally, upload the JSON.
                Works even when the tenant locks consent (type Andritz).
              </p>
            </button>
          </div>
        </section>

        <!-- Guest Link: session upload -->
        @if (uiMode() === 'guest_link') {
          <section class="ck-surface t-elevated rounded-md p-5">
            <header class="flex items-center justify-between gap-2 mb-3">
              <div>
                <h2 class="text-sm font-semibold text-white">Session (Guest Link)</h2>
                <p class="text-[11px] text-gray-400">
                  Paste the JSON produced locally by the Agentium Connector CLI.
                </p>
              </div>
              @if (sessionStatus()?.exists) {
                <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20">
                  <app-icon name="check-circle-2" [size]="10" /> cached
                </span>
              } @else if (sessionKey()) {
                <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/20">
                  <app-icon name="alert-triangle" [size]="10" /> no session
                </span>
              }
            </header>

            @if (hasShowcaseJob()) {
              <div class="mb-3 rounded-md bg-amber-500/10 ring-1 ring-amber-500/20 p-3">
                <div class="flex items-start gap-2">
                  <app-icon name="info" [size]="14" class="text-amber-300 mt-0.5" />
                  <div class="min-w-0">
                    <div class="text-[11px] font-semibold text-amber-200 uppercase tracking-wider">
                      Showcase demo job detected
                    </div>
                    <p class="text-[11px] text-gray-300 mt-1">
                      Recent syncs include <span class="font-mono text-amber-200">showcase-guest-link</span>.
                      Use the button below to prefill the demo session key; a real sync still requires an uploaded session JSON.
                    </p>
                    <button
                      type="button"
                      (click)="prefillShowcaseSession()"
                      class="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-amber-500/15 hover:bg-amber-500/25 text-amber-100 text-[11px] ring-1 ring-amber-500/30 transition"
                    >
                      Prefill showcase key
                    </button>
                  </div>
                </div>
              </div>
            }

            <div class="rounded-md bg-black/30 ring-1 ring-white/10 p-3 mb-3">
              <p class="text-[11px] text-gray-400 font-mono leading-relaxed mb-2">
                # On your local machine
              </p>
              <code class="block text-[11px] font-mono text-gray-200 whitespace-pre-wrap break-all">
                python scripts/sharepoint_connector_demo.py \\<br />
                &nbsp;&nbsp;--sharing-url "&lt;your sharing URL&gt;" \\<br />
                &nbsp;&nbsp;--folder "/sites/.../Shared Documents/&lt;folder&gt;" \\<br />
                &nbsp;&nbsp;--force-reauth --export-session
              </code>
            </div>

            <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
              session_dict JSON
            </label>
            <textarea
              rows="6"
              [value]="sessionJsonRaw()"
              (input)="onSessionJsonInput($event)"
              placeholder='{"sharing_url": "...", "storage_state": "..."}'
              class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-[12px] font-mono"
            ></textarea>
            <div class="flex items-center gap-2 mt-3">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-medium transition"
                (click)="uploadSession()"
                [disabled]="!canUploadSession() || sessionUploading()"
              >
                <app-icon name="upload-cloud" [size]="14" />
                {{ sessionUploading() ? 'Uploading…' : 'Upload session' }}
              </button>
              @if (sessionStatus()?.exists) {
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition"
                  (click)="forgetSession()"
                  [disabled]="sessionUploading()"
                >
                  <app-icon name="trash-2" [size]="14" /> Forget session
                </button>
              }
            </div>
          </section>
        }

        <!-- Sync form -->
        <section class="ck-surface t-elevated rounded-md p-5">
          <header class="flex items-center gap-2 mb-4">
            <h2 class="text-sm font-semibold text-white">Sync</h2>
            <span class="text-[10px] font-mono text-gray-500">
              → collection <span class="text-cyan-300">{{ collectionName() || 'documents' }}</span>
            </span>
          </header>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="md:col-span-2">
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                Session key <span class="text-red-400">*</span>
                <span class="text-[10px] text-gray-500 normal-case ml-1">
                  (identifies this connector within your workspace)
                </span>
              </label>
              <input
                type="text"
                [ngModel]="sessionKey()"
                (ngModelChange)="onSessionKeyChange($event)"
                name="session_key"
                placeholder="andritz-partage-externe"
                class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm"
              />
            </div>

            <div class="md:col-span-2">
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                Folder server-relative URL <span class="text-red-400">*</span>
              </label>
              <input
                type="text"
                [(ngModel)]="folderUrl"
                name="folder"
                placeholder="/sites/107645/Shared Documents/Test_partage_externe"
                class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm font-mono"
              />
            </div>

            @if (uiMode() === 'guest_link') {
              <div class="md:col-span-2">
                <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Sharing URL <span class="text-red-400">*</span>
                </label>
                <input
                  type="url"
                  [(ngModel)]="sharingUrl"
                  name="sharing_url"
                  placeholder="https://tenant.sharepoint.com/:f:/s/…?e=…"
                  class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm font-mono"
                />
              </div>
            } @else {
              <div>
                <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Client ID <span class="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  [(ngModel)]="clientId"
                  name="client_id"
                  placeholder="49888603-…"
                  class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm font-mono"
                />
              </div>
              <div>
                <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Tenant host <span class="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  [(ngModel)]="tenantHost"
                  name="tenant_host"
                  placeholder="tenant.onmicrosoft.com"
                  class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm font-mono"
                />
              </div>
              <div class="md:col-span-2">
                <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  User hint
                  <span class="text-[10px] text-gray-500 normal-case ml-1">
                    (optional; account to prefill on interactive login)
                  </span>
                </label>
                <input
                  type="email"
                  [(ngModel)]="userHint"
                  name="user_hint"
                  placeholder="agent@datategy.net"
                  class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm font-mono"
                />
              </div>
            }

            <div>
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                Collection
                <span class="text-[10px] text-gray-500 normal-case ml-1">(RAG target)</span>
              </label>
              <input
                type="text"
                [ngModel]="collectionName()"
                (ngModelChange)="onCollectionChange($event)"
                name="collection_name"
                placeholder="documents"
                class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm font-mono"
              />
            </div>

            <div class="flex items-center gap-2 pt-6">
              <input
                id="prune-local"
                type="checkbox"
                [(ngModel)]="pruneLocal"
                name="prune_local_files"
                class="w-4 h-4 rounded border-white/20 bg-black/30"
              />
              <label for="prune-local" class="text-[12px] text-gray-300 cursor-pointer">
                Prune files no longer present remotely
              </label>
            </div>
          </div>

          <div class="flex items-center gap-2 pt-4 mt-4 border-t border-white/5">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
              (click)="triggerSync()"
              [disabled]="!canTriggerSync() || syncEnqueuing()"
            >
              <app-icon name="play" [size]="14" />
              {{ syncEnqueuing() ? 'Enqueuing…' : 'Sync now' }}
            </button>
            <span class="text-[11px] text-gray-500">
              Job runs in background; progress appears below.
            </span>
          </div>
        </section>
      </div>

      <!-- Right: jobs list -->
      <aside class="space-y-3">
        <div class="ck-surface t-elevated rounded-md overflow-hidden">
          <header class="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <div class="flex items-center gap-2">
              <app-icon name="history" [size]="14" class="text-gray-400" />
              <h2 class="text-sm font-semibold text-white">Recent syncs</h2>
            </div>
            <span class="text-[10px] font-mono text-gray-500">{{ jobs().length }}</span>
          </header>

          @if (jobs().length === 0) {
            <div class="p-8">
              <app-empty-state
                icon="inbox"
                title="No syncs yet"
                subtitle="Once you trigger a sync it lands here with live progress."
              />
            </div>
          } @else {
            <ul class="divide-y divide-white/5 max-h-[70vh] overflow-auto">
              @for (j of jobs(); track j.job_id) {
                <li class="p-3 text-[12px]">
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-[10px] font-mono text-gray-500 truncate" [title]="j.job_id">
                      {{ j.job_id.slice(0, 8) }}
                    </span>
                    <span
                      class="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded ring-1"
                      [ngClass]="jobBadgeClass(j)"
                    >
                      <app-icon [name]="jobBadgeIcon(j)" [size]="10" />
                      {{ jobBadgeLabel(j) }}
                    </span>
                    <span class="ml-auto text-[10px] font-mono text-gray-500">
                      {{ j.auth_mode === 'msal' ? 'OAuth' : 'Guest' }}
                    </span>
                  </div>
                  <div class="text-gray-200 font-mono text-[11px] truncate" [title]="j.folder_server_relative_url ?? ''">
                    {{ j.folder_server_relative_url }}
                  </div>
                  @if (j.state === 'running' || j.progress === 'ingesting') {
                    <div class="mt-1.5 text-[10px] text-cyan-300 font-mono">
                      <app-icon name="loader" [size]="10" class="inline-block animate-spin" />
                      {{ j.progress || 'running' }}
                    </div>
                  }
                  <div class="mt-1.5 flex items-center gap-3 text-[10px] text-gray-400 font-mono">
                    <span title="downloaded / total">
                      <app-icon name="download" [size]="10" /> {{ j.files_downloaded }}/{{ j.files_total }}
                    </span>
                    <span title="ingested / failed (RAG)">
                      <app-icon name="database" [size]="10" />
                      {{ j.ingested_count }}<span class="text-red-400" [class.hidden]="!j.ingest_failed_count">/{{ j.ingest_failed_count }}</span>
                    </span>
                    <span title="bytes">{{ formatBytes(j.bytes_total) }}</span>
                  </div>
                  @if (j.status === 'login_required') {
                    <div class="mt-2 text-[10px] text-amber-300 leading-relaxed">
                      <app-icon name="alert-triangle" [size]="10" />
                      Session expired — recapture with the CLI and re-upload above.
                    </div>
                  }
                  @if (j.error) {
                    <div class="mt-2 text-[10px] text-red-400 font-mono break-all">
                      {{ j.error }}
                    </div>
                  }
                  <div class="mt-1 text-[9px] font-mono text-gray-600">
                    {{ j.updated_at }}
                  </div>
                </li>
              }
            </ul>
          }
        </div>

        <div class="ck-surface t-elevated rounded-md p-4 text-[11px] text-gray-400 leading-relaxed">
          <div class="flex items-center gap-1.5 mb-1.5">
            <app-icon name="info" [size]="12" class="text-cyan-400" />
            <span class="font-semibold text-gray-200">Idempotent syncs.</span>
          </div>
          Each sync writes a manifest under
          <span class="font-mono text-gray-300">.sharepoint_manifest.json</span> next to the
          downloaded files. Unchanged files are skipped on subsequent runs — switching a
          connector from Guest Link to Standard keeps the same cache.
        </div>
      </aside>
    </div>
  `,
})
export class SharepointConnectorComponent implements OnInit, OnDestroy {
  /** Screen copy names the product by its brand in this workspace. */
  protected readonly brand = inject(WorkspaceService).brandName;
  private readonly api = inject(SharepointApiService);
  private readonly toast = inject(ToastrService);

  readonly uiMode = signal<UiMode>('guest_link');
  readonly sessionKey = signal<string>('');
  folderUrl = '';
  sharingUrl = '';
  clientId = '';
  tenantHost = '';
  userHint = '';
  pruneLocal = false;
  readonly collectionName = signal<string>('documents');

  readonly sessionStatus = signal<SharePointSessionStatus | null>(null);
  readonly sessionJsonRaw = signal<string>('');
  readonly sessionUploading = signal(false);

  readonly jobs = signal<SharePointJobSummary[]>([]);
  readonly jobsLoading = signal(false);
  readonly syncEnqueuing = signal(false);
  readonly hasShowcaseJob = computed(() =>
    this.jobs().some((job) => job.session_key === 'showcase-guest-link'),
  );

  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionDebounce: ReturnType<typeof setTimeout> | null = null;

  readonly canUploadSession = computed(() => {
    const raw = this.sessionJsonRaw().trim();
    if (!raw || !this.sessionKey().trim()) return false;
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object';
    } catch {
      return false;
    }
  });

  readonly canTriggerSync = computed(() => {
    if (!this.sessionKey().trim() || !this.folderUrl.trim()) return false;
    if (this.uiMode() === 'guest_link') {
      return !!this.sharingUrl.trim();
    }
    return !!this.clientId.trim() && !!this.tenantHost.trim();
  });

  ngOnInit(): void {
    this.refreshJobs();
  }

  ngOnDestroy(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    if (this.sessionDebounce) clearTimeout(this.sessionDebounce);
  }

  setMode(mode: UiMode): void {
    this.uiMode.set(mode);
  }

  onSessionKeyChange(value: string): void {
    this.sessionKey.set(value);
    if (this.sessionDebounce) clearTimeout(this.sessionDebounce);
    this.sessionDebounce = setTimeout(() => this.probeSession(), 400);
  }

  prefillShowcaseSession(): void {
    this.uiMode.set('guest_link');
    this.folderUrl = '/sites/showcase/Shared Documents/Agentium';
    this.sharingUrl = 'https://contoso.sharepoint.com/:f:/s/showcase-demo';
    this.collectionName.set('documents');
    this.onSessionKeyChange('showcase-guest-link');
  }

  onCollectionChange(value: string): void {
    this.collectionName.set(value || 'documents');
  }

  onSessionJsonInput(ev: Event): void {
    const t = ev.target as HTMLTextAreaElement;
    this.sessionJsonRaw.set(t.value);
  }

  private probeSession(): void {
    const key = this.sessionKey().trim();
    if (!key) {
      this.sessionStatus.set(null);
      return;
    }
    this.api.getSessionStatus(key).subscribe({
      next: (res) => this.sessionStatus.set(res),
      error: () => this.sessionStatus.set(null),
    });
  }

  uploadSession(): void {
    if (!this.canUploadSession()) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(this.sessionJsonRaw());
    } catch {
      this.toast.error('Invalid JSON — paste the CLI `--export-session` output.', 'SharePoint');
      return;
    }
    this.sessionUploading.set(true);
    this.api.uploadSession(this.sessionKey().trim(), { session_dict: parsed }).subscribe({
      next: () => {
        this.toast.success('Session cached server-side.', 'SharePoint');
        this.sessionJsonRaw.set('');
        this.probeSession();
        this.sessionUploading.set(false);
      },
      error: (err) => {
        this.sessionUploading.set(false);
        const detail = err?.error?.detail || err?.message || 'Upload failed';
        this.toast.error(String(detail), 'SharePoint');
      },
    });
  }

  forgetSession(): void {
    const key = this.sessionKey().trim();
    if (!key) return;
    this.api.deleteSession(key).subscribe({
      next: () => {
        this.toast.info('Session forgotten.', 'SharePoint');
        this.sessionStatus.set(null);
      },
      error: () => this.toast.error('Could not forget session.', 'SharePoint'),
    });
  }

  triggerSync(): void {
    if (!this.canTriggerSync()) return;
    const backendMode: SharePointAuthMode = this.uiMode() === 'oauth' ? 'msal' : 'session';
    this.syncEnqueuing.set(true);
    this.api
      .enqueueSync({
        session_key: this.sessionKey().trim(),
        folder_server_relative_url: this.folderUrl.trim(),
        auth_mode: backendMode,
        sharing_url: backendMode === 'session' ? this.sharingUrl.trim() : null,
        client_id: backendMode === 'msal' ? this.clientId.trim() : null,
        tenant_host: backendMode === 'msal' ? this.tenantHost.trim() : null,
        user_hint: backendMode === 'msal' && this.userHint.trim() ? this.userHint.trim() : null,
        prune_local_files: this.pruneLocal,
        collection_name: this.collectionName().trim() || 'documents',
      })
      .subscribe({
        next: (job) => {
          this.syncEnqueuing.set(false);
          this.toast.success(`Sync queued (${job.job_id.slice(0, 8)}).`, 'SharePoint');
          this.prependJob(job);
          this.scheduleLivePoll();
        },
        error: (err) => {
          this.syncEnqueuing.set(false);
          const detail = err?.error?.detail || err?.message || 'Enqueue failed';
          this.toast.error(String(detail), 'SharePoint');
        },
      });
  }

  refreshJobs(): void {
    this.jobsLoading.set(true);
    this.api.listJobs(20).subscribe({
      next: (res) => {
        this.jobs.set(res.jobs || []);
        this.jobsLoading.set(false);
        if (this.jobs().some((j) => j.state === 'running')) {
          this.scheduleLivePoll();
        }
      },
      error: () => this.jobsLoading.set(false),
    });
  }

  private prependJob(job: SharePointJobSummary): void {
    this.jobs.update((list) => [job, ...list.filter((j) => j.job_id !== job.job_id)].slice(0, 20));
  }

  /** Live-poll running jobs every 2s until they all settle. Backed off
   * to 5s after 20 ticks to avoid hammering the API during long syncs
   * (Playwright captures can take minutes on large folders). */
  private scheduleLivePoll(tick = 0): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    const running = this.jobs().filter((j) => j.state === 'running');
    if (running.length === 0) return;
    const delay = tick < 20 ? 2000 : 5000;
    this.pollTimer = setTimeout(() => {
      const runningIds = this.jobs()
        .filter((j) => j.state === 'running')
        .map((j) => j.job_id);
      if (runningIds.length === 0) return;
      // One request per running job — usually just 1 at a time.
      Promise.all(
        runningIds.map(
          (id) =>
            new Promise<SharePointJobSummary | null>((resolve) =>
              this.api.getJob(id).subscribe({
                next: (j) => resolve(j),
                error: () => resolve(null),
              }),
            ),
        ),
      ).then((updated) => {
        const merged = new Map(this.jobs().map((j) => [j.job_id, j]));
        for (const j of updated) {
          if (j) merged.set(j.job_id, j);
        }
        this.jobs.set(Array.from(merged.values()));
        if (this.jobs().some((j) => j.state === 'running')) {
          this.scheduleLivePoll(tick + 1);
        }
      });
    }, delay);
  }

  jobBadgeClass(j: SharePointJobSummary): string {
    if (j.state === 'running') return 'bg-cyan-500/10 text-cyan-300 ring-cyan-500/20';
    if (j.status === 'completed') return 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20';
    if (j.status === 'login_required')
      return 'bg-amber-500/10 text-amber-300 ring-amber-500/20';
    return 'bg-red-500/10 text-red-300 ring-red-500/20';
  }

  jobBadgeIcon(j: SharePointJobSummary): string {
    if (j.state === 'running') return 'loader';
    if (j.status === 'completed') return 'check-circle-2';
    if (j.status === 'login_required') return 'alert-triangle';
    return 'x-circle';
  }

  jobBadgeLabel(j: SharePointJobSummary): string {
    if (j.state === 'running') return 'running';
    return j.status ?? 'unknown';
  }

  formatBytes(n: number): string {
    if (!n) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i += 1;
    }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  }
}
