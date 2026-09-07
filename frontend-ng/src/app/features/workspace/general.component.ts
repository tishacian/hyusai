import { Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
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
            <h2 class="text-base font-semibold text-white">{{ i18n.t('workspace.general.identity.title') }}</h2>
            <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
              {{ i18n.t('workspace.general.identity.description') }}
            </p>
          </div>
        </div>

        @if (detail(); as d) {
          <div class="space-y-4">
            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">
                {{ i18n.t('workspace.general.name.label') }}
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
                  {{ saving() ? i18n.t('workspace.saving') : i18n.t('common.save') }}
                </button>
              </div>
              @if (!canEdit()) {
                <p class="text-xs text-gray-500 mt-1">{{ i18n.t('workspace.general.name.admins_only') }}</p>
              }
            </div>

            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">{{ i18n.t('workspace.general.slug.label') }}</label>
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
                  {{ copied() ? i18n.t('common.copied') : i18n.t('common.copy') }}
                </button>
              </div>
              <p class="text-xs text-gray-500 mt-1">{{ i18n.t('workspace.general.slug.hint') }}</p>
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
                {{ i18n.t('workspace.general.mode.title') }}
                <ck-help id="workspace.mode.switch" />
              </h2>
              <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
                {{ i18n.t('workspace.general.mode.description') }}
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
                  <span class="text-sm font-semibold text-white">{{ i18n.t(m.labelKey) }}</span>
                  @if (currentMode() === m.key) {
                    <span class="ml-auto text-[10px] uppercase tracking-wider text-cyan-400 font-mono">{{ i18n.t('workspace.general.active_badge') }}</span>
                  }
                </div>
                <p class="text-xs text-gray-400 leading-relaxed">{{ i18n.t(m.descriptionKey) }}</p>
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
                  <h3 class="text-sm font-semibold text-white">{{ i18n.t('workspace.general.demo_safe.title') }}</h3>
                  <p class="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
                    {{ i18n.t('workspace.general.demo_safe.description') }}
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
                [title]="demoSafeMode() ? i18n.t('workspace.general.demo_safe.tooltip_on') : i18n.t('workspace.general.demo_safe.tooltip_off')"
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
                  <h3 class="text-sm font-semibold text-white">{{ i18n.t('workspace.general.chat_upload.title') }}</h3>
                  <p class="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
                    {{ i18n.t('workspace.general.chat_upload.description') }}
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
                [title]="chatUploadEnabled() ? i18n.t('workspace.general.chat_upload.tooltip_on') : i18n.t('workspace.general.chat_upload.tooltip_off')"
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
            <p class="text-xs text-gray-500 mt-3">{{ i18n.t('workspace.general.mode.admins_only') }}</p>
          }
        </section>

        <section class="ck-surface rounded-md p-6">
          <div class="flex items-start gap-3 mb-4">
            <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
              <app-icon name="message-square" [size]="18" />
            </div>
            <div class="flex-1">
              <h2 class="text-base font-semibold text-white">{{ i18n.t('workspace.general.expert.title') }}</h2>
              <p class="text-sm text-gray-400 mt-0.5 max-w-2xl">
                {{ i18n.t('workspace.general.expert.description') }}
              </p>
            </div>
          </div>
          <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between rounded-md bg-black/20 ring-1 ring-white/10 px-4 py-3">
            <div class="flex items-start gap-3">
              <div class="w-9 h-9 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/25">
                <app-icon name="message-square" [size]="16" />
              </div>
              <div>
                <h3 class="text-sm font-semibold text-white">{{ i18n.t('workspace.expert_correction.title') }}</h3>
                <p class="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
                  {{ i18n.t('workspace.expert_correction.description') }}
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
              [title]="expertCorrectionEnabled() ? i18n.t('workspace.general.expert.tooltip_on') : i18n.t('workspace.general.expert.tooltip_off')"
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
                  <h3 class="text-sm font-semibold text-white">{{ i18n.t('workspace.general.expert_review.title') }}</h3>
                  <p class="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
                    {{ i18n.t('workspace.general.expert_review.description') }}
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
                [title]="expertReviewRequired() ? i18n.t('workspace.general.expert_review.tooltip_on') : i18n.t('workspace.general.expert_review.tooltip_off')"
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
            <p class="text-xs text-gray-500 mt-3">{{ i18n.t('workspace.general.expert.admins_only') }}</p>
          }
        </section>

        <section class="ck-surface rounded-md p-6">
          <div class="flex items-start gap-3 mb-4">
            <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
              <app-icon name="panel-left" [size]="18" />
            </div>
            <div class="flex-1">
              <h2 class="text-base font-semibold text-white">{{ i18n.t('workspace.general.navigation.title') }}</h2>
              <p class="text-sm text-gray-400 mt-0.5 max-w-2xl">
                {{ i18n.t('workspace.general.navigation.description') }}
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
                <span class="text-sm font-semibold text-white">{{ i18n.t('workspace.general.navigation.standard.label') }}</span>
                @if (!navigationProfileEnabled()) {
                  <span class="ml-auto text-[10px] uppercase tracking-wider text-cyan-400 font-mono">{{ i18n.t('workspace.general.active_badge') }}</span>
                }
              </div>
              <p class="text-xs text-gray-400 leading-relaxed">{{ i18n.t('workspace.general.navigation.standard.description') }}</p>
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
                <span class="text-sm font-semibold text-white">{{ i18n.t('workspace.general.navigation.business.label') }}</span>
                @if (navigationProfileEnabled()) {
                  <span class="ml-auto text-[10px] uppercase tracking-wider text-cyan-400 font-mono">{{ i18n.t('workspace.general.active_badge') }}</span>
                }
              </div>
              <p class="text-xs text-gray-400 leading-relaxed">{{ i18n.t('workspace.general.navigation.business.description') }}</p>
            </button>
          </div>
          @if (navigationProfileEnabled() && canEdit()) {
            <div class="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between rounded-md bg-black/20 ring-1 ring-white/10 px-4 py-3">
              <p class="text-xs text-gray-400 max-w-2xl">
                {{ i18n.t('workspace.general.navigation.preview.description') }}
              </p>
              <button
                type="button"
                (click)="previewBusinessNavigation()"
                class="inline-flex items-center gap-2 px-3 py-2 rounded bg-cyan-300 hover:bg-cyan-200 text-sm font-semibold text-black"
              >
                <app-icon name="eye" [size]="14" />
                {{ i18n.t('workspace.general.navigation.preview.cta') }}
              </button>
            </div>
          }
          @if (!canEdit()) {
            <p class="text-xs text-gray-500 mt-3">{{ i18n.t('workspace.general.navigation.admins_only') }}</p>
          }
        </section>

        <section class="ck-surface rounded-md p-6">
          <h2 class="text-base font-semibold text-white mb-4 flex items-center gap-2">
            <app-icon name="info" [size]="16" class="text-cyan-400" />
            {{ i18n.t('workspace.general.metadata.title') }}
          </h2>
          <dl class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">{{ i18n.t('workspace.general.metadata.role') }}</dt>
              <dd class="text-white capitalize font-medium">{{ roleName(d.role) }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">{{ i18n.t('workspace.members') }}</dt>
              <dd class="text-white font-medium">{{ d.member_count }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">{{ i18n.t('workspace.general.metadata.created') }}</dt>
              <dd class="text-white">{{ d.created_at | date: 'mediumDate' }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">{{ i18n.t('workspace.general.metadata.status') }}</dt>
              <dd>
                @if (d.is_active) {
                  <app-status-pulse tone="success" [label]="i18n.t('workspace.status.active')" />
                } @else {
                  <span class="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
                    <app-icon name="archive" [size]="11" />
                    {{ i18n.t('workspace.status.archived') }}
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
  protected readonly i18n = inject(I18nService);
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly navigationProfile = inject(NavigationProfileService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
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

  readonly modes: { key: SelectableWorkspaceMode; labelKey: string; icon: string; descriptionKey: string }[] = [
    {
      key: 'builder',
      labelKey: 'workspace.general.mode.builder.label',
      icon: 'wrench',
      descriptionKey: 'workspace.general.mode.builder.description',
    },
    {
      key: 'operator',
      labelKey: 'workspace.general.mode.operator.label',
      icon: 'activity',
      descriptionKey: 'workspace.general.mode.operator.description',
    },
    {
      key: 'executive',
      labelKey: 'workspace.general.mode.executive.label',
      icon: 'briefcase',
      descriptionKey: 'workspace.general.mode.executive.description',
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
      error: (err) =>
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.general.toast.load_failed'),
          this.i18n.t('workspace.toast.error_title'),
        ),
    });
  }

  /** Role values come from the API — translate with a fallback to the raw value. */
  roleName(role: string): string {
    const key = 'workspace.role.' + role;
    const label = this.i18n.t(key);
    return label === key ? role : label;
  }

  private modeLabel(mode: SelectableWorkspaceMode): string {
    const key = 'workspace.general.mode.' + mode + '.label';
    const label = this.i18n.t(key);
    return label === key ? mode : label;
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
        this.toastr.success(
          this.i18n.t('workspace.general.toast.renamed', { name: updated.name }),
          this.i18n.t('workspace.toast.saved_title'),
        );
      },
      error: (err) => {
        this.saving.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.general.toast.rename_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
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
        this.toastr.success(
          this.i18n.t('workspace.general.toast.mode_set', { mode: this.modeLabel(mode) }),
          this.i18n.t('workspace.toast.saved_title'),
        );
      },
      error: (err) => {
        this.savingMode.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.general.toast.mode_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
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
          enabled
            ? this.i18n.t('workspace.general.toast.demo_safe_on')
            : this.i18n.t('workspace.general.toast.demo_safe_off'),
          this.i18n.t('workspace.toast.saved_title'),
        );
      },
      error: (err) => {
        this.savingDemoSafe.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.general.toast.demo_safe_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
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
          enabled
            ? this.i18n.t('workspace.general.toast.chat_upload_on')
            : this.i18n.t('workspace.general.toast.chat_upload_off'),
          this.i18n.t('workspace.toast.saved_title'),
        );
      },
      error: (err) => {
        this.savingChatUpload.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.general.toast.chat_upload_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
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
          enabled
            ? this.i18n.t('workspace.general.toast.expert_on')
            : this.i18n.t('workspace.general.toast.expert_off'),
          this.i18n.t('workspace.toast.saved_title'),
        );
      },
      error: (err) => {
        this.savingExpertCorrection.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.general.toast.expert_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
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
          required
            ? this.i18n.t('workspace.general.toast.review_on')
            : this.i18n.t('workspace.general.toast.review_off'),
          this.i18n.t('workspace.toast.saved_title'),
        );
      },
      error: (err) => {
        this.savingExpertReview.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.general.toast.review_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
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
          enabled
            ? this.i18n.t('workspace.general.toast.navigation_on')
            : this.i18n.t('workspace.general.toast.navigation_off'),
          this.i18n.t('workspace.toast.saved_title'),
        );
      },
      error: (err) => {
        this.savingNavigationProfile.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.general.toast.navigation_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
      },
    });
  }

  previewBusinessNavigation(): void {
    this.navigationProfile.setBusinessPreview(true);
    void this.router.navigateByUrl(this.navigation.surfaceUrl('chat'));
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
