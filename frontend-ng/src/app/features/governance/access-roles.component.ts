import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import {
  IamMatrix,
  IamMatrixPermission,
  IamSummary,
  RoleTemplate,
  WorkspaceMemberDetail,
  WorkspaceService,
  toggleWorkspaceAppEntitlement,
  type WorkspaceAppEntitlement,
  workspaceAppEntitlementOptions,
} from '@app/core/workspace.service';

@Component({
  selector: 'app-access-roles',
  standalone: true,
  imports: [FormsModule, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('governance.access.breadcrumb')"
      [title]="i18n.t('governance.access.title')"
      icon="shield-check"
      [subtitle]="i18n.t('governance.access.subtitle')"
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 text-gray-200 ring-1 ring-white/10 transition"
        (click)="load()"
      >
        <app-icon name="refresh-cw" [size]="14" /> {{ i18n.t('common.refresh') }}
      </button>
    </app-section-header>

    @if (error(); as message) {
      <div class="mb-4 rounded-md p-3 bg-red-500/10 ring-1 ring-red-400/25 text-sm text-red-100">
        {{ message }}
      </div>
    }

    @if (summary(); as iam) {
      <section class="grid xl:grid-cols-[minmax(0,1fr)_360px] gap-5">
        <div class="space-y-5">
          <section class="ck-surface rounded-md overflow-hidden">
            <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between gap-3">
              <div>
                <h3 class="text-sm font-semibold text-white">{{ i18n.t('governance.access.members.title') }}</h3>
                <p class="text-xs text-gray-500 mt-1">{{ iam.workspace.name }} · {{ iam.enforcement ? i18n.t('governance.access.enforcement.enforced') : i18n.t('governance.access.enforcement.dry_run') }}</p>
              </div>
              <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                {{ i18n.t('governance.access.members.count', { count: iam.members.length }) }}
              </span>
            </div>
            <div class="divide-y divide-white/5">
              @for (member of members(); track member.user_id) {
                <article class="px-5 py-4 hover:bg-white/[0.02] transition">
                  <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px_minmax(220px,1fr)_96px] lg:items-end">
                    <div class="min-w-0">
                      <div class="flex items-center gap-2">
                        <div class="h-8 w-8 shrink-0 rounded-full bg-white/[0.04] ring-1 ring-cyan-400/30 flex items-center justify-center text-xs font-semibold text-cyan-200">
                          {{ initial(member) }}
                        </div>
                        <div class="min-w-0">
                          <div class="truncate text-sm font-medium text-white">{{ member.email || member.username }}</div>
                          <div class="truncate text-[11px] text-gray-500">
                            {{ member.username }}
                            @if (member.is_current_user) {
                              · {{ i18n.t('governance.access.members.you') }}
                            }
                          </div>
                        </div>
                      </div>
                    </div>

                    <label class="block min-w-0">
                      <span class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1.5">{{ i18n.t('governance.access.members.role') }}</span>
                      @if (canEditMemberRole(member)) {
                        <span class="ag-select-wrap">
                          <select
                            class="ag-select"
                            [(ngModel)]="member.role_template"
                          >
                            @for (role of roleOptions; track role.value) {
                              <option [ngValue]="role.value" [disabled]="role.value === 'workspace_owner'">
                                {{ i18n.t(role.labelKey) }}
                              </option>
                            }
                          </select>
                          <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                        </span>
                      } @else {
                        <span
                          [class]="roleBadgeClass(memberRoleTemplate(member))"
                          [title]="memberRoleLockedReason(member)"
                        >
                          @if (memberRoleTemplate(member) === 'workspace_owner') {
                            <app-icon name="crown" [size]="12" />
                          } @else {
                            <app-icon name="shield-check" [size]="12" />
                          }
                          {{ roleLabel(memberRoleTemplate(member)) }}
                        </span>
                      }
                    </label>

                    <label class="block min-w-0">
                      <span class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1.5">{{ i18n.t('governance.access.members.labels') }}</span>
                      <input
                        class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60 disabled:opacity-50"
                        [disabled]="!canEditMemberLabels(member)"
                        [ngModel]="labelsText(member)"
                        (ngModelChange)="setLabels(member, $event)"
                        [placeholder]="i18n.t('governance.access.members.labels.placeholder')"
                      />
                    </label>

                    <button
                      type="button"
                      class="inline-flex h-10 items-center justify-center gap-1.5 rounded bg-cyan-500 hover:bg-cyan-400 text-sm font-semibold text-white disabled:opacity-40 disabled:hover:bg-cyan-500"
                      [disabled]="saving() || !canSaveMember(member)"
                      (click)="saveMember(member)"
                    >
                      <app-icon name="save" [size]="14" /> {{ i18n.t('common.save') }}
                    </button>
                  </div>
                  @if (!canEditMemberRole(member) && memberRoleTemplate(member) === 'workspace_owner') {
                    <p class="mt-2 pl-10 text-[11px] text-gray-500">{{ memberRoleLockedReason(member) }}</p>
                  }
                  @if (appEntitlementsEnabled()) {
                    <fieldset class="mt-3 rounded border border-white/[0.08] bg-black/10 px-3 py-2">
                      <legend class="px-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                        {{ i18n.t('governance.access.members.apps') }}
                      </legend>
                      <div class="flex flex-wrap gap-x-5 gap-y-2">
                        @for (app of appOptions(); track app.key) {
                          <label class="inline-flex items-center gap-2 text-xs text-gray-300">
                            <input
                              type="checkbox"
                              [checked]="memberHasApp(member, app.key)"
                              [disabled]="!canSaveMember(member)"
                              (change)="setMemberApp(member, app.key, $event)"
                              class="h-4 w-4 rounded border-white/20 bg-black/30 text-cyan-500 focus:ring-cyan-400/60 disabled:opacity-50"
                            />
                            {{ app.label }}
                          </label>
                        }
                      </div>
                    </fieldset>
                  }
                </article>
              }
            </div>
          </section>

          <section class="ck-surface rounded-md overflow-hidden">
            <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
              <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
                <app-icon name="table-properties" [size]="16" class="text-cyan-400" /> {{ i18n.t('governance.access.matrix.title') }}
              </h3>
              <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                {{ matrix()?.role_template || i18n.t('governance.access.matrix.subject') }}
              </span>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-white/5">
                    <th class="px-5 py-3 font-semibold">{{ i18n.t('governance.access.matrix.column.permission') }}</th>
                    @for (role of roleOptions; track role.value) {
                      <th class="px-5 py-3 font-semibold text-center">{{ i18n.t(role.shortKey) }}</th>
                    }
                  </tr>
                </thead>
                <tbody class="divide-y divide-white/5">
                  @for (row of matrixRows(); track row.resource_kind + ':' + row.action) {
                    <tr>
                      <td class="px-5 py-3">
                        <div class="text-white font-medium">{{ row.resource_kind }}.{{ row.action }}</div>
                        @if (row.conditions.length) {
                          <div class="text-[11px] text-gray-500">{{ row.conditions.join(' · ') }}</div>
                        }
                      </td>
                      @for (role of roleOptions; track role.value) {
                        <td class="px-5 py-3 text-center">
                          @if (row.roles.includes(role.value)) {
                            <app-icon name="check" [size]="16" class="text-emerald-400 inline" />
                          } @else {
                            <app-icon name="minus" [size]="16" class="text-gray-600 inline" />
                          }
                        </td>
                      }
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <aside class="space-y-5">
          <section class="ck-surface rounded-md p-5 border border-cyan-500/25 bg-cyan-500/[0.04]">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">{{ i18n.t('governance.access.capture.eyebrow') }}</p>
            <h3 class="text-sm font-semibold text-white mt-1">{{ i18n.t('governance.access.capture.title') }}</h3>
            <p class="mt-3 text-xs text-gray-400 leading-relaxed">
              {{ i18n.t('governance.access.capture.description') }}
              <span class="font-mono text-gray-200">expert_knowledge_capture</span>.
            </p>
            <div class="mt-3 flex flex-wrap gap-2 text-[10px] uppercase tracking-wider">
              <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">capture_session</span>
              <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">knowledge_proposal</span>
              <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">voice_runtime</span>
            </div>
          </section>

          <section class="ck-surface rounded-md p-5">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">{{ i18n.t('governance.access.config.eyebrow') }}</p>
                <h3 class="text-sm font-semibold text-white mt-1">{{ i18n.t('governance.access.config.title') }}</h3>
              </div>
              <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                v{{ iam.config.version }}
              </span>
            </div>
            <div class="mt-4 space-y-3">
              @for (flag of flagOptions; track flag.key) {
                <label class="flex items-start gap-3 rounded bg-black/20 border border-white/10 p-3">
                  <input
                    type="checkbox"
                    class="mt-1"
                    [ngModel]="flagValue(flag.key)"
                    (ngModelChange)="setFlag(flag.key, $event)"
                  />
                  <span>
                    <span class="block text-xs text-gray-100 font-medium">{{ i18n.t(flag.labelKey) }}</span>
                    <span class="block text-[11px] text-gray-500 mt-0.5">{{ i18n.t(flag.descriptionKey) }}</span>
                  </span>
                </label>
              }
            </div>
            <button
              type="button"
              class="mt-4 w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-cyan-500 hover:bg-cyan-400 text-sm font-semibold text-white disabled:opacity-50"
              [disabled]="saving()"
              (click)="saveFlags()"
            >
              <app-icon name="save" [size]="14" /> {{ i18n.t('governance.access.config.save') }}
            </button>
          </section>

          <section class="ck-surface rounded-md p-5">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">{{ i18n.t('governance.access.subject.eyebrow') }}</p>
            <h3 class="text-sm font-semibold text-white mt-1">{{ matrix()?.role_template || i18n.t('governance.access.subject.unknown') }}</h3>
            <p class="mt-3 text-xs text-gray-500 leading-relaxed">
              {{ i18n.t('governance.access.subject.description') }}
            </p>
          </section>
        </aside>
      </section>
    } @else {
      <section class="ck-surface rounded-md p-8 text-center text-gray-400">
        {{ loading() ? i18n.t('governance.access.loading') : i18n.t('governance.access.select_workspace') }}
      </section>
    }
  `,
  styles: [`
    .ag-select-wrap {
      position: relative;
      display: block;
    }
    .ag-select {
      width: 100%;
      height: 40px;
      appearance: none;
      -webkit-appearance: none;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(0,0,0,0.30);
      color: rgb(243 244 246);
      padding: 0 2.25rem 0 0.75rem;
      font-size: 0.875rem;
      outline: none;
      color-scheme: dark;
      transition: border-color 120ms, box-shadow 120ms, background 120ms;
    }
    .ag-select:focus {
      border-color: rgba(56,189,248,0.65);
      box-shadow: 0 0 0 2px rgba(56,189,248,0.18);
      background: rgba(0,0,0,0.38);
    }
    .ag-select-chevron {
      position: absolute;
      right: 0.75rem;
      top: 50%;
      transform: translateY(-50%);
      color: rgb(156 163 175);
      pointer-events: none;
    }
  `],
})
export class AccessRolesComponent implements OnInit {
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly summary = signal<IamSummary | null>(null);
  readonly matrix = signal<IamMatrix | null>(null);
  readonly members = signal<WorkspaceMemberDetail[]>([]);
  readonly roleFlags = signal<Record<string, boolean>>({});
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);

  readonly roleOptions: Array<{ value: RoleTemplate; labelKey: string; shortKey: string }> = [
    { value: 'workspace_viewer', labelKey: 'governance.access.role.workspace_viewer', shortKey: 'governance.access.role.short.workspace_viewer' },
    { value: 'workspace_contributor', labelKey: 'governance.access.role.workspace_contributor', shortKey: 'governance.access.role.short.workspace_contributor' },
    { value: 'workspace_reviewer', labelKey: 'governance.access.role.workspace_reviewer', shortKey: 'governance.access.role.short.workspace_reviewer' },
    { value: 'workspace_admin', labelKey: 'governance.access.role.workspace_admin', shortKey: 'governance.access.role.short.workspace_admin' },
    { value: 'workspace_owner', labelKey: 'governance.access.role.workspace_owner', shortKey: 'governance.access.role.short.workspace_owner' },
  ];

  readonly flagOptions = [
    {
      key: 'contributors_see_only_own_sessions',
      labelKey: 'governance.access.flag.contributors_see_only_own_sessions',
      descriptionKey: 'governance.access.flag.contributors_see_only_own_sessions.description',
    },
    {
      key: 'require_second_eye_for_ingestion',
      labelKey: 'governance.access.flag.require_second_eye_for_ingestion',
      descriptionKey: 'governance.access.flag.require_second_eye_for_ingestion.description',
    },
    {
      key: 'reviewers_inherit_contributor',
      labelKey: 'governance.access.flag.reviewers_inherit_contributor',
      descriptionKey: 'governance.access.flag.reviewers_inherit_contributor.description',
    },
  ];

  readonly currentWorkspace = computed(() => this.workspace.current());
  readonly appEntitlementsEnabled = this.workspace.appEntitlementsEnabled;
  readonly appOptions = computed(() => workspaceAppEntitlementOptions(
    this.workspace.current(),
    this.members().flatMap((member) => member.app_entitlements || []),
  ));

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.workspace.getIamSummary().subscribe({
      next: (summary) => {
        this.summary.set(summary);
        this.members.set(summary.members.map((member) => ({ ...member })));
        this.roleFlags.set({ ...summary.config.role_flags });
        this.loading.set(false);
      },
      error: () => {
        this.error.set(this.i18n.t('governance.access.error.load'));
        this.loading.set(false);
      },
    });
    this.workspace.getIamMatrix().subscribe({
      next: (matrix) => this.matrix.set(matrix),
      error: () => this.matrix.set(null),
    });
  }

  labelsText(member: WorkspaceMemberDetail): string {
    return (member.custom_labels || []).join(', ');
  }

  initial(member: WorkspaceMemberDetail): string {
    const src = member.email || member.username || '?';
    return src[0]?.toUpperCase() || '?';
  }

  memberRoleTemplate(member: WorkspaceMemberDetail): RoleTemplate {
    return (member.role_template || 'workspace_contributor') as RoleTemplate;
  }

  roleLabel(role: RoleTemplate): string {
    const option = this.roleOptions.find((item) => item.value === role);
    return this.i18n.t(option?.labelKey || 'governance.access.role.workspace_contributor');
  }

  roleBadgeClass(role: RoleTemplate): string {
    const base = 'inline-flex h-10 w-full items-center gap-1.5 rounded border px-3 text-sm font-medium';
    if (role === 'workspace_owner') return `${base} border-amber-500/30 bg-amber-500/10 text-amber-200`;
    if (role === 'workspace_admin') return `${base} border-cyan-400/30 bg-cyan-500/10 text-cyan-100`;
    if (role === 'workspace_reviewer') return `${base} border-sky-400/25 bg-sky-500/10 text-sky-100`;
    return `${base} border-white/10 bg-white/[0.03] text-gray-300`;
  }

  ownerCount(): number {
    return this.members().filter((member) => this.memberRoleTemplate(member) === 'workspace_owner').length;
  }

  subjectIsOwner(): boolean {
    return this.matrix()?.role_template === 'workspace_owner';
  }

  canEditMemberRole(member: WorkspaceMemberDetail): boolean {
    if (member.is_current_user) return false;
    const role = this.memberRoleTemplate(member);
    if (role !== 'workspace_owner') return true;
    return this.subjectIsOwner() && this.ownerCount() > 1;
  }

  canEditMemberLabels(member: WorkspaceMemberDetail): boolean {
    return this.memberRoleTemplate(member) !== 'workspace_owner' || this.canEditMemberRole(member);
  }

  canSaveMember(member: WorkspaceMemberDetail): boolean {
    if (member.is_current_user) return false;
    if (!this.canEditMemberLabels(member) && !this.canEditMemberRole(member)) return false;
    return this.memberRoleTemplate(member) !== 'workspace_owner';
  }

  memberRoleLockedReason(member: WorkspaceMemberDetail): string {
    if (member.is_current_user) return this.i18n.t('governance.access.role_locked.self');
    if (!this.subjectIsOwner()) return this.i18n.t('governance.access.role_locked.not_owner');
    return this.i18n.t('governance.access.role_locked.last_owner');
  }

  setLabels(member: WorkspaceMemberDetail, value: string): void {
    member.custom_labels = value
      .split(',')
      .map((label) => label.trim())
      .filter(Boolean);
  }

  memberHasApp(member: WorkspaceMemberDetail, app: WorkspaceAppEntitlement): boolean {
    return (member.app_entitlements || []).includes(app);
  }

  setMemberApp(
    member: WorkspaceMemberDetail,
    app: WorkspaceAppEntitlement,
    event: Event,
  ): void {
    const enabled = (event.target as HTMLInputElement).checked;
    member.app_entitlements = toggleWorkspaceAppEntitlement(
      member.app_entitlements,
      app,
      enabled,
      this.appOptions(),
    );
  }

  flagValue(key: string): boolean {
    return Boolean(this.roleFlags()[key]);
  }

  setFlag(key: string, value: boolean): void {
    this.roleFlags.update((flags) => ({ ...flags, [key]: value }));
  }

  saveFlags(): void {
    this.saving.set(true);
    this.workspace.patchIamConfig({ role_flags: this.roleFlags() }).subscribe({
      next: () => {
        this.saving.set(false);
        this.load();
      },
      error: () => {
        this.saving.set(false);
        this.error.set(this.i18n.t('governance.access.error.save_flags'));
      },
    });
  }

  saveMember(member: WorkspaceMemberDetail): void {
    const roleTemplate = (member.role_template || 'workspace_contributor') as RoleTemplate;
    if (roleTemplate === 'workspace_owner') {
      this.error.set(this.i18n.t('governance.access.error.owner_assignment'));
      return;
    }
    this.saving.set(true);
    const update = {
      role_template: roleTemplate,
      custom_labels: member.custom_labels || [],
      ...(this.appEntitlementsEnabled()
        ? { app_entitlements: member.app_entitlements || [] }
        : {}),
    };
    this.workspace
      .updateIamMember(member.user_id, update)
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.load();
        },
        error: () => {
          this.saving.set(false);
          this.error.set(this.i18n.t('governance.access.error.save_member'));
        },
      });
  }

  matrixRows(): IamMatrixPermission[] {
    const seen = new Set<string>();
    return (this.matrix()?.permissions || []).filter((row) => {
      const key = `${row.resource_kind}:${row.action}:${row.conditions.join('|')}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
}
