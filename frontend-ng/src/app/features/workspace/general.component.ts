import { Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import {
  WorkspaceDetail,
  WorkspaceMode,
  WorkspaceService,
  type SelectableWorkspaceMode,
} from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';
import { HelpTooltipComponent } from '@app/shared/cockpit';

const FIELD =
  'flex-1 px-3 py-2 rounded bg-black/20 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 transition';

@Component({
  selector: 'app-workspace-general',
  standalone: true,
  imports: [FormsModule, DatePipe, IconComponent, StatusPulseComponent, SkeletonComponent, HelpTooltipComponent],
  template: `
    <div class="space-y-6">
      <section class="ck-surface rounded-md p-6">
        <div class="flex items-start gap-3 mb-5">
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
            <app-icon name="settings" [size]="18" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-white">Identity</h2>
            <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
              The display name appears everywhere; the slug is a stable identifier used in URLs and API headers.
            </p>
          </div>
        </div>

        @if (detail(); as d) {
          <div class="space-y-4">
            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">
                Workspace name
              </label>
              <div class="flex gap-2">
                <input
                  [(ngModel)]="name"
                  name="name"
                  type="text"
                  [class]="field"
                  [disabled]="!canEdit()"
                />
                <button
                  type="button"
                  (click)="saveName()"
                  [disabled]="!dirty() || saving() || !canEdit()"
                  class="px-4 py-2 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-sm font-medium transition inline-flex items-center gap-1.5"
                >
                  <app-icon name="save" [size]="14" />
                  {{ saving() ? 'Saving…' : 'Save' }}
                </button>
              </div>
              @if (!canEdit()) {
                <p class="text-xs text-gray-500 mt-1">Only owners and admins can rename the workspace.</p>
              }
            </div>

            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">Slug</label>
              <div class="flex gap-2">
                <input
                  [value]="d.slug"
                  readonly
                  class="flex-1 px-3 py-2 rounded bg-black/40 border border-white/5 text-gray-300 font-mono text-sm"
                />
                <button
                  type="button"
                  (click)="copy(d.slug)"
                  class="px-3 py-2 bg-white/5 hover:bg-white/10 text-gray-200 rounded text-sm inline-flex items-center gap-1.5 transition"
                >
                  <app-icon [name]="copied() ? 'check' : 'copy'" [size]="14" />
                  {{ copied() ? 'Copied' : 'Copy' }}
                </button>
              </div>
              <p class="text-xs text-gray-500 mt-1">Slugs cannot be changed once created.</p>
            </div>
          </div>
        } @else {
          <div class="space-y-3">
            <app-skeleton height="40px" />
            <app-skeleton height="40px" />
          </div>
        }
      </section>

      @if (detail(); as d) {
        <section class="ck-surface rounded-md p-6">
          <div class="flex items-start gap-3 mb-4">
            <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
              <app-icon name="layers" [size]="18" />
            </div>
            <div class="flex-1">
              <h2 class="text-base font-semibold text-white flex items-center gap-2">
                Mode
                <ck-help id="workspace.mode.switch" />
              </h2>
              <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
                Progressive disclosure of menus and cockpit pages. Data never changes—only what you see. Switch at any time.
              </p>
            </div>
          </div>
          <div class="grid gap-3 md:grid-cols-3">
            @for (m of modes; track m.key) {
              <button
                type="button"
                (click)="setMode(m.key)"
                [disabled]="!canEdit() || savingMode()"
                [class.ring-2]="currentMode() === m.key"
                [class.ring-cyan-500]="currentMode() === m.key"
                [class.bg-cyan-500]="currentMode() === m.key"
                [class.bg-opacity-10]="currentMode() === m.key"
                class="text-left p-4 rounded-md border border-white/10 bg-white/5 hover:bg-white/10 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <div class="flex items-center gap-2 mb-2">
                  <app-icon [name]="m.icon" [size]="16" class="text-cyan-400" />
                  <span class="text-sm font-semibold text-white">{{ m.label }}</span>
                  @if (currentMode() === m.key) {
                    <span class="ml-auto text-[10px] uppercase tracking-wider text-cyan-400 font-mono">active</span>
                  }
                </div>
                <p class="text-xs text-gray-400 leading-relaxed">{{ m.description }}</p>
              </button>
            }
          </div>
          <div class="mt-4 pt-4 border-t border-white/10">
            <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between rounded-md bg-black/20 ring-1 ring-white/10 px-4 py-3">
              <div class="flex items-start gap-3">
                <div class="w-9 h-9 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/25">
                  <app-icon name="eye-off" [size]="16" />
                </div>
                <div>
                  <h3 class="text-sm font-semibold text-white">Demo-safe presentation</h3>
                  <p class="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
                    Hides provider and model implementation details in Chat, Systems, Resources and Presets while keeping the selected workspace mode active.
                  </p>
                </div>
              </div>
              <button
                type="button"
                (click)="setDemoSafe(!demoSafeMode())"
                [disabled]="!canEdit() || savingDemoSafe()"
                class="relative inline-flex h-8 w-16 shrink-0 items-center rounded-full ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed"
                [class.bg-cyan-500\\/25]="demoSafeMode()"
                [class.ring-cyan-400\\/60]="demoSafeMode()"
                [class.bg-white\\/5]="!demoSafeMode()"
                [class.ring-white\\/10]="!demoSafeMode()"
                [title]="demoSafeMode() ? 'Provider/model names are hidden' : 'Provider/model names are visible'"
              >
                <span
                  class="inline-block h-6 w-6 rounded-full bg-white shadow transition-transform"
                  [class.translate-x-9]="demoSafeMode()"
                  [class.translate-x-1]="!demoSafeMode()"
                ></span>
              </button>
            </div>
            <div class="mt-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between rounded-md bg-black/20 ring-1 ring-white/10 px-4 py-3">
              <div class="flex items-start gap-3">
                <div class="w-9 h-9 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/25">
                  <app-icon name="cloud-upload" [size]="16" />
                </div>
                <div>
                  <h3 class="text-sm font-semibold text-white">Document upload in chat</h3>
                  <p class="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
                    Allows drop-and-ask in the workspace chat: members can drop files to ground answers on them. Turn off to hide the chat dropzone.
                  </p>
                </div>
              </div>
              <button
                type="button"
                (click)="setChatUpload(!chatUploadEnabled())"
                [disabled]="!canEdit() || savingChatUpload()"
                class="relative inline-flex h-8 w-16 shrink-0 items-center rounded-full ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed"
                [class.bg-cyan-500\\/25]="chatUploadEnabled()"
                [class.ring-cyan-400\\/60]="chatUploadEnabled()"
                [class.bg-white\\/5]="!chatUploadEnabled()"
                [class.ring-white\\/10]="!chatUploadEnabled()"
                [title]="chatUploadEnabled() ? 'Drop-and-ask is enabled in chat' : 'Drop-and-ask is disabled in chat'"
              >
                <span
                  class="inline-block h-6 w-6 rounded-full bg-white shadow transition-transform"
                  [class.translate-x-9]="chatUploadEnabled()"
                  [class.translate-x-1]="!chatUploadEnabled()"
                ></span>
              </button>
            </div>
          </div>
          @if (!canEdit()) {
            <p class="text-xs text-gray-500 mt-3">Only owners and admins can change the workspace mode.</p>
          }
        </section>

        <section class="ck-surface rounded-md p-6">
          <div class="flex items-start gap-3 mb-4">
            <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
              <app-icon name="message-square" [size]="18" />
            </div>
            <div class="flex-1">
              <h2 class="text-base font-semibold text-white">Expert knowledge correction</h2>
              <p class="text-sm text-gray-400 mt-0.5 max-w-2xl">
                Lets reviewers correct or complete chat answers inline. Validated corrections become expert fiches that ground future answers.
              </p>
            </div>
          </div>
          <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between rounded-md bg-black/20 ring-1 ring-white/10 px-4 py-3">
            <div class="flex items-start gap-3">
              <div class="w-9 h-9 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/25">
                <app-icon name="message-square" [size]="16" />
              </div>
              <div>
                <h3 class="text-sm font-semibold text-white">Inline chat correction</h3>
                <p class="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
                  Shows the "Corriger / Compléter" action in chat for reviewers and admins, and enables the backend accept/publish path. Turn off to hide the CTA everywhere.
                </p>
              </div>
            </div>
            <button
              type="button"
              (click)="setExpertCorrection(!expertCorrectionEnabled())"
              [disabled]="!canEdit() || savingExpertCorrection()"
              class="relative inline-flex h-8 w-16 shrink-0 items-center rounded-full ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed"
              [class.bg-cyan-500\\/25]="expertCorrectionEnabled()"
              [class.ring-cyan-400\\/60]="expertCorrectionEnabled()"
              [class.bg-white\\/5]="!expertCorrectionEnabled()"
              [class.ring-white\\/10]="!expertCorrectionEnabled()"
              [title]="expertCorrectionEnabled() ? 'Inline chat correction is enabled' : 'Inline chat correction is disabled'"
            >
              <span
                class="inline-block h-6 w-6 rounded-full bg-white shadow transition-transform"
                [class.translate-x-9]="expertCorrectionEnabled()"
                [class.translate-x-1]="!expertCorrectionEnabled()"
              ></span>
            </button>
          </div>
          @if (expertCorrectionEnabled()) {
            <div class="mt-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between rounded-md bg-black/20 ring-1 ring-white/10 px-4 py-3">
              <div class="flex items-start gap-3">
                <div class="w-9 h-9 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/25">
                  <app-icon name="eye" [size]="16" />
                </div>
                <div>
                  <h3 class="text-sm font-semibold text-white">Require expert review</h3>
                  <p class="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
                    When on, corrections wait in review before publication. Turn off to auto-publish validated corrections immediately.
                  </p>
                </div>
              </div>
              <button
                type="button"
                (click)="setExpertReview(!expertReviewRequired())"
                [disabled]="!canEdit() || savingExpertReview()"
                class="relative inline-flex h-8 w-16 shrink-0 items-center rounded-full ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed"
                [class.bg-cyan-500\\/25]="expertReviewRequired()"
                [class.ring-cyan-400\\/60]="expertReviewRequired()"
                [class.bg-white\\/5]="!expertReviewRequired()"
                [class.ring-white\\/10]="!expertReviewRequired()"
                [title]="expertReviewRequired() ? 'Corrections require review before publication' : 'Corrections are auto-published'"
              >
                <span
                  class="inline-block h-6 w-6 rounded-full bg-white shadow transition-transform"
                  [class.translate-x-9]="expertReviewRequired()"
                  [class.translate-x-1]="!expertReviewRequired()"
                ></span>
              </button>
            </div>
          }
          @if (!canEdit()) {
            <p class="text-xs text-gray-500 mt-3">Only owners and admins can change expert correction settings.</p>
          }
        </section>

        <section class="ck-surface rounded-md p-6">
          <div class="flex items-start gap-3 mb-4">
            <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
              <app-icon name="panel-left" [size]="18" />
            </div>
            <div class="flex-1">
              <h2 class="text-base font-semibold text-white">Navigation profile</h2>
              <p class="text-sm text-gray-400 mt-0.5 max-w-2xl">
                Simplifies the workspace for business end users. Admins keep the full Agentium cockpit by default.
              </p>
            </div>
          </div>
          <div class="grid gap-3 md:grid-cols-2">
            <button
              type="button"
              (click)="setNavigationProfile(false)"
              [disabled]="!canEdit() || savingNavigationProfile()"
              [class.ring-2]="!navigationProfileEnabled()"
              [class.ring-cyan-500]="!navigationProfileEnabled()"
              [class.bg-cyan-500]="!navigationProfileEnabled()"
              [class.bg-opacity-10]="!navigationProfileEnabled()"
              class="text-left p-4 rounded-md border border-white/10 bg-white/5 hover:bg-white/10 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <div class="flex items-center gap-2 mb-2">
                <app-icon name="layout-dashboard" [size]="16" class="text-cyan-400" />
                <span class="text-sm font-semibold text-white">Standard</span>
                @if (!navigationProfileEnabled()) {
                  <span class="ml-auto text-[10px] uppercase tracking-wider text-cyan-400 font-mono">active</span>
                }
              </div>
              <p class="text-xs text-gray-400 leading-relaxed">Full cockpit: Systems, Runs, Observability, Governance and workspace tools.</p>
            </button>
            <button
              type="button"
              (click)="setNavigationProfile(true)"
              [disabled]="!canEdit() || savingNavigationProfile()"
              [class.ring-2]="navigationProfileEnabled()"
              [class.ring-cyan-500]="navigationProfileEnabled()"
              [class.bg-cyan-500]="navigationProfileEnabled()"
              [class.bg-opacity-10]="navigationProfileEnabled()"
              class="text-left p-4 rounded-md border border-white/10 bg-white/5 hover:bg-white/10 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <div class="flex items-center gap-2 mb-2">
                <app-icon name="message-square" [size]="16" class="text-cyan-400" />
                <span class="text-sm font-semibold text-white">Business end-user</span>
                @if (navigationProfileEnabled()) {
                  <span class="ml-auto text-[10px] uppercase tracking-wider text-cyan-400 font-mono">active</span>
                }
              </div>
              <p class="text-xs text-gray-400 leading-relaxed">Business users see only Recherche and Capture de connaissances.</p>
            </button>
          </div>
          @if (navigationProfileEnabled() && canEdit()) {
            <div class="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between rounded-md bg-black/20 ring-1 ring-white/10 px-4 py-3">
              <p class="text-xs text-gray-400 max-w-2xl">
                Preview shows the same mini-shell business users will see. The top bar contains a return button for admins.
              </p>
              <button
                type="button"
                (click)="previewBusinessNavigation()"
                class="inline-flex items-center gap-2 px-3 py-2 rounded bg-cyan-300 hover:bg-cyan-200 text-sm font-semibold text-black"
              >
                <app-icon name="eye" [size]="14" />
                Preview business shell
              </button>
            </div>
          }
          @if (!canEdit()) {
            <p class="text-xs text-gray-500 mt-3">Only owners and admins can change the navigation profile.</p>
          }
        </section>

        <section class="ck-surface rounded-md p-6">
          <h2 class="text-base font-semibold text-white mb-4 flex items-center gap-2">
            <app-icon name="info" [size]="16" class="text-cyan-400" />
            Metadata
          </h2>
          <dl class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Your role</dt>
              <dd class="text-white capitalize font-medium">{{ d.role }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Members</dt>
              <dd class="text-white font-medium">{{ d.member_count }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Created</dt>
              <dd class="text-white">{{ d.created_at | date: 'mediumDate' }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Status</dt>
              <dd>
                @if (d.is_active) {
                  <app-status-pulse tone="success" label="Active" />
                } @else {
                  <span class="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
                    <app-icon name="archive" [size]="11" />
                    Archived
                  </span>
                }
              </dd>
            </div>
          </dl>
        </section>
      }
    </div>
  `,
})
export class WorkspaceGeneralComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly navigationProfile = inject(NavigationProfileService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);

  protected readonly field = FIELD;

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  readonly detail = signal<WorkspaceDetail | null>(null);
  readonly saving = signal(false);
  readonly savingMode = signal(false);
  readonly savingDemoSafe = signal(false);
  readonly savingChatUpload = signal(false);
  readonly savingNavigationProfile = signal(false);
  readonly savingExpertCorrection = signal(false);
  readonly savingExpertReview = signal(false);
  readonly copied = signal(false);

  readonly modes: { key: SelectableWorkspaceMode; label: string; icon: string; description: string }[] = [
    {
      key: 'builder',
      label: 'Builder',
      icon: 'wrench',
      description: 'Focus on System Builder: capability, skills, context, policy. Hypervisor/ROI hidden.',
    },
    {
      key: 'operator',
      label: 'Operator',
      icon: 'activity',
      description: 'Daily operations: runs, decisions, steering. Portfolio KPIs reduced.',
    },
    {
      key: 'executive',
      label: 'Executive',
      icon: 'briefcase',
      description: 'Full portfolio view with Hypervisor, ROI, balance sheet and capability ranking.',
    },
  ];

  readonly currentMode = computed<WorkspaceMode>(
    () => (this.detail()?.mode as WorkspaceMode) || 'executive',
  );
  readonly demoSafeMode = computed(() => {
    const d = this.detail();
    if (!d) return false;
    return d.mode === 'demo' || this.demoSafeFromSettings(d.settings);
  });
  readonly navigationProfileEnabled = computed(() => {
    const settings = this.detail()?.settings || {};
    const profile = this.asRecord(settings['navigation_profile']);
    return profile['key'] === 'business_end_user';
  });

  /**
   * Drop-and-ask upload gating. Reads `settings.features.chat_document_upload`
   * (enabled by default; only an explicit `false` disables it).
   */
  readonly chatUploadEnabled = computed(() => {
    const features = this.detail()?.settings?.['features'] as
      | Record<string, unknown>
      | undefined;
    return features?.['chat_document_upload'] !== false;
  });

  /**
   * Per-workspace expert chat-correction toggle, read from the workspace
   * `settings.source_policy.expert_fiche_correction_enabled` (the same location
   * the chat CTA gate reads). Disabled unless explicitly `true`.
   */
  readonly expertCorrectionEnabled = computed(() => {
    const policy = this.asRecord(this.detail()?.settings?.['source_policy']);
    return policy['expert_fiche_correction_enabled'] === true;
  });

  /**
   * Whether expert corrections must be reviewed before publication. Reads
   * `settings.source_policy.expert_review_required`; defaults to `true` (review
   * required) to mirror the backend default when the key is absent.
   */
  readonly expertReviewRequired = computed(() => {
    const policy = this.asRecord(this.detail()?.settings?.['source_policy']);
    return 'expert_review_required' in policy ? policy['expert_review_required'] !== false : true;
  });

  name = '';

  readonly canEdit = computed(() => {
    const role = this.detail()?.role;
    const roleTemplate = this.detail()?.role_template;
    return role === 'owner' || role === 'admin' || roleTemplate === 'workspace_owner' || roleTemplate === 'workspace_admin';
  });

  readonly dirty = computed(() => {
    const d = this.detail();
    if (!d) return false;
    return this.name.trim() !== d.name && this.name.trim().length > 0;
  });

  constructor() {
    effect(() => {
      const slug = this.routeSlug();
      if (slug) this.load(slug);
    });
  }

  load(slug: string): void {
    this.workspaceService.getWorkspace(slug).subscribe({
      next: (d) => {
        this.detail.set(d);
        this.name = d.name;
      },
      error: (err) => this.toastr.error(err?.error?.detail || 'Failed to load workspace', 'Error'),
    });
  }

  saveName(): void {
    const d = this.detail();
    if (!d) return;
    const trimmed = this.name.trim();
    if (!trimmed) return;
    this.saving.set(true);
    this.workspaceService.renameWorkspace(d.slug, trimmed).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.detail.set(updated);
        this.name = updated.name;
        this.toastr.success(`Workspace renamed to "${updated.name}"`, 'Saved');
      },
      error: (err) => {
        this.saving.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to rename workspace', 'Error');
      },
    });
  }

  setMode(mode: SelectableWorkspaceMode): void {
    const d = this.detail();
    if (!d || !this.canEdit() || mode === this.currentMode()) return;
    this.savingMode.set(true);
    this.workspaceService.setMode(d.slug, mode).subscribe({
      next: (updated) => {
        this.savingMode.set(false);
        this.detail.set(updated);
        this.toastr.success(`Workspace mode set to "${mode}"`, 'Saved');
      },
      error: (err) => {
        this.savingMode.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to update mode', 'Error');
      },
    });
  }

  setDemoSafe(enabled: boolean): void {
    const d = this.detail();
    if (!d || !this.canEdit()) return;
    const settings = { ...(d.settings || {}) };
    const presentation = this.asRecord(settings['presentation']);
    settings['demo_safe'] = enabled;
    settings['presentation'] = {
      ...presentation,
      demo_safe: enabled,
      hide_provider_details: enabled,
    };
    this.savingDemoSafe.set(true);
    this.workspaceService.updateWorkspaceSettings(d.slug, settings).subscribe({
      next: (updated) => {
        this.savingDemoSafe.set(false);
        this.detail.set(updated);
        this.toastr.success(
          enabled ? 'Provider and model details are hidden.' : 'Provider and model details are visible.',
          'Saved',
        );
      },
      error: (err) => {
        this.savingDemoSafe.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to update presentation setting', 'Error');
      },
    });
  }

  setChatUpload(enabled: boolean): void {
    const d = this.detail();
    if (!d || !this.canEdit()) return;
    const settings = { ...(d.settings || {}) };
    const features = this.asRecord(settings['features']);
    settings['features'] = {
      ...features,
      chat_document_upload: enabled,
    };
    this.savingChatUpload.set(true);
    this.workspaceService.updateWorkspaceSettings(d.slug, settings).subscribe({
      next: (updated) => {
        this.savingChatUpload.set(false);
        this.detail.set(updated);
        this.toastr.success(
          enabled ? 'Document upload in chat is enabled.' : 'Document upload in chat is disabled.',
          'Saved',
        );
      },
      error: (err) => {
        this.savingChatUpload.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to update chat upload setting', 'Error');
      },
    });
  }

  setExpertCorrection(enabled: boolean): void {
    const d = this.detail();
    if (!d || !this.canEdit()) return;
    const settings = { ...(d.settings || {}) };
    settings['source_policy'] = {
      ...this.asRecord(settings['source_policy']),
      expert_fiche_correction_enabled: enabled,
    };
    this.savingExpertCorrection.set(true);
    this.workspaceService.updateWorkspaceSettings(d.slug, settings).subscribe({
      next: (updated) => {
        this.savingExpertCorrection.set(false);
        this.detail.set(updated);
        this.workspaceService.refreshCurrentWorkspace().subscribe();
        this.toastr.success(
          enabled ? 'Expert chat correction is enabled.' : 'Expert chat correction is disabled.',
          'Saved',
        );
      },
      error: (err) => {
        this.savingExpertCorrection.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to update expert correction setting', 'Error');
      },
    });
  }

  setExpertReview(required: boolean): void {
    const d = this.detail();
    if (!d || !this.canEdit()) return;
    const settings = { ...(d.settings || {}) };
    settings['source_policy'] = {
      ...this.asRecord(settings['source_policy']),
      expert_review_required: required,
    };
    this.savingExpertReview.set(true);
    this.workspaceService.updateWorkspaceSettings(d.slug, settings).subscribe({
      next: (updated) => {
        this.savingExpertReview.set(false);
        this.detail.set(updated);
        this.workspaceService.refreshCurrentWorkspace().subscribe();
        this.toastr.success(
          required ? 'Expert corrections now require review.' : 'Expert corrections are auto-published.',
          'Saved',
        );
      },
      error: (err) => {
        this.savingExpertReview.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to update review setting', 'Error');
      },
    });
  }

  setNavigationProfile(enabled: boolean): void {
    const d = this.detail();
    if (!d || !this.canEdit()) return;
    const settings = { ...(d.settings || {}) };
    if (enabled) {
      settings['navigation_profile'] = this.navigationProfile.businessProfileConfig(true);
    } else {
      delete settings['navigation_profile'];
      this.navigationProfile.setBusinessPreview(false);
    }
    this.savingNavigationProfile.set(true);
    this.workspaceService.updateWorkspaceSettings(d.slug, settings).subscribe({
      next: (updated) => {
        this.savingNavigationProfile.set(false);
        this.detail.set(updated);
        this.toastr.success(
          enabled ? 'Business navigation profile enabled.' : 'Standard navigation restored.',
          'Saved',
        );
      },
      error: (err) => {
        this.savingNavigationProfile.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to update navigation profile', 'Error');
      },
    });
  }

  previewBusinessNavigation(): void {
    this.navigationProfile.setBusinessPreview(true);
    this.router.navigateByUrl('/chat');
  }

  copy(slug: string): void {
    navigator.clipboard?.writeText(slug).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    });
  }

  private demoSafeFromSettings(settings?: Record<string, unknown>): boolean {
    if (!settings) return false;
    const presentation = this.asRecord(settings['presentation']);
    return (
      settings['demo_safe'] === true ||
      settings['demo_safe_mode'] === true ||
      settings['hide_provider_details'] === true ||
      presentation['demo_safe'] === true ||
      presentation['hide_provider_details'] === true
    );
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
  }
}
