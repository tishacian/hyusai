import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { I18nService } from '@app/core/i18n.service';
import { ConnectorChecksComponent } from '../connector-checks.component';
import { WriteOutcomeComponent } from '@app/shared/ui/write-outcome.component';
import { settleWrite, type WriteOutcome } from '@app/shared/ui/load-state';
import { ConnectorCapabilitiesComponent } from '../connector-capabilities.component';
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
import { CkBackLinkComponent } from '@app/shared/cockpit';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  SharePointAuthMode,
  SharePointSyncRequest,
  SharePointJobSummary,
  SharePointSessionStatus,
  SharepointApiService,
} from './sharepoint.service';
import { PageFrameComponent } from '@app/shared/cockpit/page-frame.component';

type UiMode = 'guest_link' | 'oauth';

@Component({
  selector: 'app-sharepoint-connector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ConnectorChecksComponent, WriteOutcomeComponent, ConnectorCapabilitiesComponent,
    PageFrameComponent,
    CommonModule,
    FormsModule,
    CkBackLinkComponent,
    IconComponent,
    SectionHeaderComponent,
    EmptyStateComponent,
  ],
  template: `
    <ck-page-frame [hasActions]="false">
    <app-section-header
      [breadcrumb]="i18n.t('connectors.title')"
      title="Microsoft SharePoint"
      icon="folder"
      [subtitle]="i18n.t('connectors.sharepoint.subtitle')"
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="refreshJobs()"
        [disabled]="jobsLoading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="jobsLoading()" />
        {{ i18n.t('connectors.sharepoint.copy.refresh_jobs') }}
      </button>
      <ck-back-link [fallback]="{ surface: 'resources' }" />
    </app-section-header>
    <app-connector-capabilities connector="sharepoint" />
    <app-connector-checks [configured]="sessionStatus()?.exists ?? null" [result]="connectionTest()" />
    <app-write-outcome [outcome]="writeOutcome()" [verifiable]="true" (verify)="verifyWrite()" />
    @if (sessionError()) { <p role="alert">{{ i18n.t('connectors.sharepoint.session_unavailable') }}</p> }



    <div class="grid grid-cols-1 xl:grid-cols-3 gap-5">
      <!-- Left: mode picker + configuration -->
      <div class="xl:col-span-2 space-y-5">
        <!-- Mode picker -->
        <section class="ck-surface t-elevated rounded-md p-5">
          <header class="flex items-center gap-2 mb-4">
            <h2 class="text-sm font-semibold text-white">{{ i18n.t('connectors.sharepoint.copy.authentication_mode') }}</h2>
            <span class="text-xs font-mono text-gray-500">{{ i18n.t('connectors.sharepoint.copy.one_per_session_key') }}</span>
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
                <span class="text-sm font-semibold text-white">{{ i18n.t('connectors.sharepoint.copy.standard_oauth') }}</span>
              </div>
              <p class="text-xs text-gray-400 leading-relaxed">
                {{ i18n.t('connectors.sharepoint.copy.client_it_registered_an_app_with') }} <span class="font-mono text-gray-300">Sites.Read.All</span>{{ i18n.t('connectors.sharepoint.copy.admin_consent_accepted_silent_refresh_no_recapture_needed') }}
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
                <span class="text-sm font-semibold text-white">{{ i18n.t('connectors.sharepoint.copy.guest_link_otp') }}</span>
              </div>
              <p class="text-xs text-gray-400 leading-relaxed">
                {{ i18n.t('connectors.sharepoint.copy.sharing_url_otp_mail_authenticator_capture_the_session_locally_upload_') }}
              </p>
            </button>
          </div>
        </section>

        <!-- Guest Link: session upload -->
        @if (uiMode() === 'guest_link') {
          <section class="ck-surface t-elevated rounded-md p-5">
            <header class="flex items-center justify-between gap-2 mb-3">
              <div>
                <h2 class="text-sm font-semibold text-white">{{ i18n.t('connectors.sharepoint.copy.session_guest_link') }}</h2>
                <p class="text-xs text-gray-400">
                  {{ i18n.t('connectors.sharepoint.copy.paste_the_json_produced_locally_by_the_agentium_connector_cli') }}
                </p>
              </div>
              @if (sessionStatus()?.exists) {
                <span class="inline-flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20">
                  <app-icon name="check-circle-2" [size]="10" /> {{ i18n.t('connectors.sharepoint.copy.cached') }}
                </span>
              } @else if (sessionKey()) {
                <span class="inline-flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/20">
                  <app-icon name="alert-triangle" [size]="10" /> {{ i18n.t('connectors.sharepoint.copy.no_session') }}
                </span>
              }
            </header>

            @if (hasShowcaseJob()) {
              <div class="mb-3 rounded-md bg-amber-500/10 ring-1 ring-amber-500/20 p-3">
                <div class="flex items-start gap-2">
                  <app-icon name="info" [size]="14" class="text-amber-300 mt-0.5" />
                  <div class="min-w-0">
                    <div class="text-xs font-semibold text-amber-200 uppercase tracking-wider">
                      {{ i18n.t('connectors.sharepoint.copy.showcase_demo_job_detected') }}
                    </div>
                    <p class="text-xs text-gray-300 mt-1">
                      {{ i18n.t('connectors.sharepoint.copy.recent_syncs_include') }} <span class="font-mono text-amber-200">showcase-guest-link</span>{{ i18n.t('connectors.sharepoint.copy.use_the_button_below_to_prefill_the_demo_session_key_a_real_sync_still') }}
                    </p>
                    <button
                      type="button"
                      (click)="prefillShowcaseSession()"
                      class="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-amber-500/15 hover:bg-amber-500/25 text-amber-100 text-xs ring-1 ring-amber-500/30 transition"
                    >
                      {{ i18n.t('connectors.sharepoint.copy.prefill_showcase_key') }}
                    </button>
                  </div>
                </div>
              </div>
            }

            <div class="rounded-md bg-black/30 ring-1 ring-white/10 p-3 mb-3">
              <p class="text-xs text-gray-400 font-mono leading-relaxed mb-2">
                {{ i18n.t('connectors.sharepoint.copy.on_your_local_machine') }}
              </p>
              <code class="block text-xs font-mono text-gray-200 whitespace-pre-wrap break-all">
                python scripts/sharepoint_connector_demo.py \\<br />
                &nbsp;&nbsp;--sharing-url "&lt;your sharing URL&gt;" \\<br />
                &nbsp;&nbsp;--folder "/sites/.../Shared Documents/&lt;folder&gt;" \\<br />
                &nbsp;&nbsp;--force-reauth --export-session
              </code>
            </div>

            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
              {{ i18n.t('connectors.sharepoint.copy.session_dict_json') }}
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
                {{ i18n.t(sessionUploading() ? 'connectors.sharepoint.uploading' : 'connectors.sharepoint.upload_session') }}
              </button>
              @if (sessionStatus()?.exists) {
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition"
                  (click)="forgetSession()"
                  [disabled]="sessionUploading()"
                >
                  <app-icon name="trash-2" [size]="14" /> {{ i18n.t('connectors.sharepoint.copy.forget_session') }}
                </button>
              }
            </div>
          </section>
        }

        <!-- Sync form -->
        <section class="ck-surface t-elevated rounded-md p-5">
          <header class="flex items-center gap-2 mb-4">
            <h2 class="text-sm font-semibold text-white">{{ i18n.t('connectors.sharepoint.copy.sync') }}</h2>
            <span class="text-xs font-mono text-gray-500">
              {{ i18n.t('connectors.sharepoint.copy.collection') }} <span class="text-cyan-300">{{ collectionName() || 'documents' }}</span>
            </span>
          </header>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="md:col-span-2">
              <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                {{ i18n.t('connectors.sharepoint.copy.session_key') }} <span class="text-red-400">*</span>
                <span class="text-xs text-gray-500 normal-case ml-1">
                  {{ i18n.t('connectors.sharepoint.copy.identifies_this_connector_within_your_workspace') }}
                </span>
              </label>
              <input
                type="text"
                [ngModel]="sessionKey()"
                (ngModelChange)="onSessionKeyChange($event)"
                name="session_key"
                placeholder="partage-externe-client"
                class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm"
              />
            </div>

            <div class="md:col-span-2">
              <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                {{ i18n.t('connectors.sharepoint.copy.folder_server_relative_url') }} <span class="text-red-400">*</span>
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
                <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  {{ i18n.t('connectors.sharepoint.copy.sharing_url') }} <span class="text-red-400">*</span>
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
                <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  {{ i18n.t('connectors.sharepoint.copy.client_id') }} <span class="text-red-400">*</span>
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
                <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  {{ i18n.t('connectors.sharepoint.copy.tenant_host') }} <span class="text-red-400">*</span>
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
                <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  {{ i18n.t('connectors.sharepoint.copy.user_hint') }}
                  <span class="text-xs text-gray-500 normal-case ml-1">
                    {{ i18n.t('connectors.sharepoint.copy.optional_account_to_prefill_on_interactive_login') }}
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
              <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                {{ i18n.t('connectors.sharepoint.copy.collection') }}
                <span class="text-xs text-gray-500 normal-case ml-1">{{ i18n.t('connectors.sharepoint.copy.rag_target') }}</span>
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
                {{ i18n.t('connectors.sharepoint.copy.prune_files_no_longer_present_remotely') }}
              </label>
            </div>
          </div>

          <div class="flex items-center gap-2 pt-4 mt-4 border-t border-white/5">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
              (click)="triggerSync()"
              [disabled]="!canTriggerSync() || syncEnqueuing() || writeOutcome()?.s === 'unknown'"
            >
              <app-icon name="play" [size]="14" />
              {{ i18n.t(syncEnqueuing() ? 'connectors.sharepoint.enqueuing' : 'connectors.sharepoint.sync_now') }}
            </button>
            <button type="button" class="ck-btn ck-btn-quiet" (click)="testConnection()" [disabled]="!canTriggerSync() || testing()">{{ i18n.t('connectors.test') }}</button>
            <span class="text-xs text-gray-500">{{ i18n.t('connectors.sharepoint.background') }}</span>
          </div>
        </section>
      </div>

      <!-- Right: jobs list -->
      <aside class="space-y-3">
        <div class="ck-surface t-elevated rounded-md overflow-hidden">
          <header class="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <div class="flex items-center gap-2">
              <app-icon name="history" [size]="14" class="text-gray-400" />
              <h2 class="text-sm font-semibold text-white">{{ i18n.t('connectors.sharepoint.copy.recent_syncs') }}</h2>
            </div>
            <span class="text-xs font-mono text-gray-500">{{ jobs().length }}</span>
          </header>

          @if (jobsLoading()) {
            <p role="status">{{ i18n.t('common.loading') }}</p>
          } @else if (jobsError()) {
            <p role="alert">{{ i18n.t('connectors.sharepoint.jobs_unavailable') }}</p>
          } @else if (jobs().length === 0) {
            <div class="p-8">
              <app-empty-state
                icon="inbox"
                [title]="i18n.t('connectors.sharepoint.no_syncs')"
                [description]="i18n.t('connectors.sharepoint.no_syncs_help')"
              />
            </div>
          } @else {
            <ul class="divide-y divide-white/5 max-h-[70vh] overflow-auto">
              @for (j of jobs(); track j.job_id) {
                <li class="p-3 text-[12px]">
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-xs font-mono text-gray-500 truncate" [title]="j.job_id">
                      {{ j.job_id.slice(0, 8) }}
                    </span>
                    <span
                      class="inline-flex items-center gap-1 text-xs font-mono px-1.5 py-0.5 rounded ring-1"
                      [ngClass]="jobBadgeClass(j)"
                    >
                      <app-icon [name]="jobBadgeIcon(j)" [size]="10" />
                      {{ jobBadgeLabel(j) }}
                    </span>
                    <span class="ml-auto text-xs font-mono text-gray-500">
                      {{ j.auth_mode === 'msal' ? 'OAuth' : 'Guest' }}
                    </span>
                  </div>
                  <div class="text-gray-200 font-mono text-xs truncate" [title]="j.folder_server_relative_url ?? ''">
                    {{ j.folder_server_relative_url }}
                  </div>
                  @if (j.state === 'running' || j.progress === 'ingesting') {
                    <div class="mt-1.5 text-xs text-cyan-300 font-mono">
                      <app-icon name="loader" [size]="10" class="inline-block animate-spin" />
                      {{ j.progress || 'running' }}
                    </div>
                  }
                  <div class="mt-1.5 flex items-center gap-3 text-xs text-gray-400 font-mono">
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
                    <div class="mt-2 text-xs text-amber-300 leading-relaxed">
                      <app-icon name="alert-triangle" [size]="10" />
                      {{ i18n.t('connectors.sharepoint.copy.session_expired_recapture_with_the_cli_and_re_upload_above') }}
                    </div>
                  }
                  @if (j.file_outcomes; as receipt) {
                    <details class="mt-3" data-testid="sharepoint-file-receipt">
                      <summary>{{ i18n.t('connectors.sharepoint.receipt') }}</summary>
                      <ul class="mt-2 space-y-2">
                        @for (file of receipt.items; track file.filename) {
                          <li class="break-words">{{ file.filename }} — {{ i18n.t('connectors.sharepoint.file.' + file.state) }}</li>
                        }
                      </ul>
                      @if (receipt.truncated) { <p>{{ i18n.t('connectors.sharepoint.receipt_truncated') }}</p> }
                    </details>
                  }
                  @if (j.error) {
                    <div class="mt-2 text-xs text-red-400 font-mono break-all">
                      {{ i18n.t('connectors.sharepoint.sync_failed') }}
                    </div>
                  }
                  <div class="mt-1 text-xs font-mono text-gray-600">
                    {{ j.updated_at }}
                  </div>
                </li>
              }
            </ul>
          }
        </div>

        <div class="ck-surface t-elevated rounded-md p-4 text-xs text-gray-400 leading-relaxed">
          <div class="flex items-center gap-1.5 mb-1.5">
            <app-icon name="info" [size]="12" class="text-cyan-400" />
            <span class="font-semibold text-gray-200">{{ i18n.t('connectors.sharepoint.copy.idempotent_syncs') }}</span>
          </div>
          {{ i18n.t('connectors.sharepoint.copy.each_sync_writes_a_manifest_under') }}
          <span class="font-mono text-gray-300">.sharepoint_manifest.json</span> {{ i18n.t('connectors.sharepoint.copy.next_to_the_downloaded_files_unchanged_files_are_skipped_on_subsequent') }}
        </div>
      </aside>
    </div>
    </ck-page-frame>
  `,
})
export class SharepointConnectorComponent implements OnInit, OnDestroy {
  /** Screen copy names the product by its brand in this workspace. */
  private readonly workspace = inject(WorkspaceService);
  protected readonly brand = this.workspace.brandName;
  private readonly context = new WorkspaceViewContext(this.workspace, () => this.resetWorkspace(), () => this.refreshJobs());
  private readonly api = inject(SharepointApiService);
  readonly i18n = inject(I18nService);
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
  readonly jobsError = signal(false);
  readonly sessionError = signal(false);
  readonly testing = signal(false);
  readonly connectionTest = signal<{ ok: boolean; status: string } | null>(null);
  readonly writeOutcome = signal<WriteOutcome | null>(null);
  private pendingSessionChange = false;
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

  readonly canTriggerSync = () => {
    if (!this.sessionKey().trim() || !this.folderUrl.trim()) return false;
    if (this.uiMode() === 'guest_link') {
      return !!this.sharingUrl.trim();
    }
    return !!this.clientId.trim() && !!this.tenantHost.trim();
  };

  ngOnInit(): void {
    this.refreshJobs();
  }

  ngOnDestroy(): void {
    this.context.destroy();
    if (this.pollTimer) clearTimeout(this.pollTimer);
    if (this.sessionDebounce) clearTimeout(this.sessionDebounce);
  }

  private resetWorkspace(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    if (this.sessionDebounce) clearTimeout(this.sessionDebounce);
    this.pollTimer = null; this.sessionDebounce = null;
    this.sessionKey.set(''); this.sessionJsonRaw.set(''); this.sessionStatus.set(null);
    this.folderUrl = ''; this.sharingUrl = ''; this.clientId = ''; this.tenantHost = ''; this.userHint = '';
    this.collectionName.set('documents'); this.pruneLocal = false;
    this.jobs.set([]); this.jobsLoading.set(false); this.jobsError.set(false); this.sessionError.set(false);
    this.sessionUploading.set(false); this.syncEnqueuing.set(false); this.testing.set(false);
    this.writeOutcome.set(null); this.connectionTest.set(null); this.pendingSessionChange = false;
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
    const request = this.context.captureRequest();
    this.api.getSessionStatus(key).subscribe({
      next: (res) => {
        if (!this.context.isCurrent(request) || key !== this.sessionKey().trim()) return;
        this.sessionStatus.set(res); this.sessionError.set(false);
        if (this.pendingSessionChange && this.writeOutcome()?.s === 'unknown') { this.writeOutcome.set(null); this.pendingSessionChange = false; }
      },
      error: () => { if (this.context.isCurrent(request) && key === this.sessionKey().trim()) { this.sessionStatus.set(null); this.sessionError.set(true); } },
    });
  }

  uploadSession(): void {
    if (!this.canUploadSession() || this.sessionUploading() || this.writeOutcome()?.s === 'unknown') return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(this.sessionJsonRaw());
    } catch {
      this.toast.error(this.i18n.t('connectors.sharepoint.invalid_json'), 'SharePoint');
      return;
    }
    this.sessionUploading.set(true);
    this.pendingSessionChange = true;
    const request = this.context.captureRequest();
    settleWrite(this.api.uploadSession(this.sessionKey().trim(), { session_dict: parsed })).subscribe(outcome => {
      if (!this.context.isCurrent(request)) return;
      this.writeOutcome.set(outcome); this.sessionUploading.set(outcome.s === 'sent');
      if (outcome.s === 'confirmed') {
        this.sessionJsonRaw.set(''); this.probeSession(); this.pendingSessionChange = false;
      }
    });
  }

  forgetSession(): void {
    const key = this.sessionKey().trim();
    if (!key || this.sessionUploading() || this.syncEnqueuing() || !window.confirm(this.i18n.t('connectors.sharepoint.forget_effect'))) return;
    this.pendingSessionChange = true;
    const request = this.context.captureRequest();
    settleWrite(this.api.deleteSession(key)).subscribe(outcome => {
      if (!this.context.isCurrent(request)) return;
      this.writeOutcome.set(outcome); this.sessionUploading.set(outcome.s === 'sent');
      if (outcome.s === 'confirmed') { this.sessionStatus.set(null); this.pendingSessionChange = false; }
    });
  }

  verifyWrite(): void {
    if (this.pendingSessionChange) this.probeSession();
    else this.refreshJobs();
  }

  private syncRequest(): SharePointSyncRequest {
    const backendMode: SharePointAuthMode = this.uiMode() === 'oauth' ? 'msal' : 'session';
    return {
      session_key: this.sessionKey().trim(), folder_server_relative_url: this.folderUrl.trim(),
      auth_mode: backendMode, sharing_url: backendMode === 'session' ? this.sharingUrl.trim() : null,
      client_id: backendMode === 'msal' ? this.clientId.trim() : null,
      tenant_host: backendMode === 'msal' ? this.tenantHost.trim() : null,
      user_hint: backendMode === 'msal' && this.userHint.trim() ? this.userHint.trim() : null,
      prune_local_files: this.pruneLocal, collection_name: this.collectionName().trim() || 'documents',
    };
  }

  testConnection(): void {
    if (!this.canTriggerSync() || this.testing()) return;
    this.testing.set(true); this.connectionTest.set(null);
    const request = this.context.captureRequest();
    this.api.testConnection(this.syncRequest()).subscribe({
      next: result => { if (this.context.isCurrent(request)) { this.connectionTest.set(result); this.testing.set(false); } },
      error: () => { if (this.context.isCurrent(request)) { this.connectionTest.set({ ok: false, status: 'unreachable' }); this.testing.set(false); } },
    });
  }

  triggerSync(): void {
    if (!this.canTriggerSync() || this.syncEnqueuing() || this.sessionUploading() || this.writeOutcome()?.s === 'unknown') return;
    this.syncEnqueuing.set(true);
    const request = this.context.captureRequest();
    settleWrite(this.api.enqueueSync(this.syncRequest()), { accepted: () => true }).subscribe(outcome => {
      if (!this.context.isCurrent(request)) return;
      this.writeOutcome.set(outcome); this.syncEnqueuing.set(outcome.s === 'sent');
      if (outcome.s === 'accepted') { this.prependJob(outcome.value); this.scheduleLivePoll(); }
    });
  }

  refreshJobs(): void {
    this.jobsLoading.set(true);
    this.jobsError.set(false);
    const request = this.context.captureRequest();
    this.api.listJobs(20).subscribe({
      next: (res) => {
        if (!this.context.isCurrent(request)) return;
        this.jobs.set(res.jobs || []);
        this.jobsLoading.set(false);
        if (!this.pendingSessionChange && this.writeOutcome()?.s === 'unknown') this.writeOutcome.set(null);
        if (this.jobs().some((j) => j.state === 'running')) {
          this.scheduleLivePoll();
        }
      },
      error: () => { if (this.context.isCurrent(request)) { this.jobsLoading.set(false); this.jobsError.set(true); } },
    });
  }

  private prependJob(job: SharePointJobSummary): void {
    this.jobs.update((list) => [job, ...list.filter((j) => j.job_id !== job.job_id)].slice(0, 20));
  }

  /** Live-poll running jobs every 2s until they all settle. Backed off
   * to 5s after 20 ticks to avoid hammering the API during long syncs
   * (Playwright captures can take minutes on large folders). */
  private scheduleLivePoll(tick = 0): void {
    const request = this.context.captureRequest();
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
        if (!this.context.isCurrent(request)) return;
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
