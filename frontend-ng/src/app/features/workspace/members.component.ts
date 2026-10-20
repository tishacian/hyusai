import { Component, computed, effect, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { LOADING, settleRead, settleWrite, writeFailureCause, type LoadState } from '@app/shared/ui/load-state';
import { DatePipe, NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import {
  AvailableWorkspaceUser,
  WorkspaceMemberDetail,
  WorkspaceService,
  toggleWorkspaceAppEntitlement,
  type RoleTemplate,
  type WorkspaceAppEntitlement,
  workspaceAppEntitlementOptions,
} from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';

const INVITE_TEMPLATES: Array<{ id: RoleTemplate; labelKey: string; inviteable: boolean }> = [
  { id: 'workspace_viewer', labelKey: 'workspace.role.viewer', inviteable: true },
  { id: 'workspace_contributor', labelKey: 'workspace.role.contributor', inviteable: true },
  { id: 'workspace_reviewer', labelKey: 'workspace.role.reviewer', inviteable: true },
  { id: 'workspace_admin', labelKey: 'workspace.role.admin', inviteable: true },
  { id: 'workspace_owner', labelKey: 'workspace.role.owner', inviteable: false },
];

@Component({
  selector: 'app-workspace-members',
  standalone: true,
  imports: [
    FormsModule,
    DatePipe,
    NgClass,
    IconComponent,
    RouterLink,
    SkeletonComponent,
    EmptyStateComponent,
    ConfirmDialogComponent,
  ],
  template: `
    <div class="space-y-6">
      @if (canAdmin()) {
        <section class="ck-surface rounded-md p-5 border border-cyan-500/25 bg-cyan-500/[0.04]">
          <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div class="flex items-start gap-3">
              <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
                <app-icon name="shield-check" [size]="18" />
              </div>
              <div>
                <h2 class="text-base font-semibold text-white">{{ i18n.t('workspace.members.iam.title') }}</h2>
                <p class="text-sm text-gray-400 mt-0.5">
                  {{ i18n.t('workspace.members.iam.description') }}
                </p>
              </div>
            </div>
            <a
              [routerLink]="accessRoute()"
              class="inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-400 text-white transition"
            >
              <app-icon name="sliders-horizontal" [size]="14" />
              {{ i18n.t('workspace.members.iam.open') }}
            </a>
          </div>
        </section>

        <section class="ck-surface rounded-md p-6">
          <div class="flex items-start gap-3 mb-4">
            <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
              <app-icon name="user-plus" [size]="18" />
            </div>
            <div>
              <h2 class="text-base font-semibold text-white">{{ i18n.t('workspace.members.invite.title') }}</h2>
              <p class="text-sm text-gray-400 mt-0.5">
                {{ i18n.t('workspace.members.invite.description') }}
              </p>
            </div>
          </div>
          <form (ngSubmit)="invite()" class="flex flex-wrap gap-2">
            <input
              [(ngModel)]="inviteEmail"
              name="email"
              type="email"
              placeholder="user@company.com"
              list="workspace-existing-users"
              required
              (input)="searchExistingUsers()"
              class="flex-1 min-w-[220px] px-3 py-2 rounded bg-black/20 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 transition"
            />
            <datalist id="workspace-existing-users">
              @for (candidate of availableUsers(); track candidate.id) {
                <option [value]="candidate.email">{{ candidate.username }}</option>
              }
            </datalist>
            <select
              [(ngModel)]="inviteTemplate"
              name="role_template"
              class="workspace-select"
              data-testid="workspace-invite-role-template"
            >
              @for (template of inviteTemplates; track template.id) {
                <option [value]="template.id" [disabled]="!template.inviteable">
                  {{ i18n.t(template.labelKey) }}
                  @if (!template.inviteable) {
                    — {{ i18n.t('workspace.role.owner_transfer_only') }}
                  }
                </option>
              }
            </select>
            @if (appEntitlementsEnabled()) {
              <fieldset class="w-full rounded-md border border-white/10 bg-black/15 px-3 py-2">
                <legend class="px-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                  {{ i18n.t('workspace.members.invite.app_access') }}
                </legend>
                <div class="flex flex-wrap gap-x-5 gap-y-2">
                  @for (app of inviteAppOptions(); track app.key) {
                    <label class="inline-flex items-center gap-2 text-sm text-gray-200">
                      <input
                        type="checkbox"
                        [checked]="inviteHasApp(app.key)"
                        (change)="setInviteApp(app.key, $event)"
                        class="h-4 w-4 rounded border-white/20 bg-black/30 text-cyan-500 focus:ring-cyan-400/60"
                      />
                      {{ app.label }}
                    </label>
                  }
                </div>
              </fieldset>
            }
            <button
              type="submit"
              [disabled]="!inviteEmail.trim() || inviting()"
              class="px-4 py-2 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 text-white rounded text-sm font-medium transition inline-flex items-center gap-1.5"
            >
              <app-icon name="send" [size]="14" />
              {{ inviting() ? i18n.t('workspace.members.invite.inviting') : i18n.t('workspace.members.invite.cta') }}
            </button>
          </form>
        </section>
      }

      <section class="ck-surface rounded-md overflow-hidden">
        <div class="px-6 py-4 border-b border-white/5 flex items-center justify-between">
          <h2 class="text-base font-semibold text-white flex items-center gap-2">
            <app-icon name="users" [size]="16" class="text-cyan-400" />
            {{ i18n.t('workspace.members') }} <span class="text-gray-500 font-normal">· {{ members().length }}</span>
          </h2>
        </div>

        @if (membersState().s === 'loading' && members().length === 0) {
          <div class="p-6 space-y-3" role="status" [attr.aria-label]="i18n.t('common.loading')">
            <app-skeleton height="56px" />
            <app-skeleton height="56px" />
            <app-skeleton height="56px" />
          </div>
        } @else if (membersState().s === 'error' || membersState().s === 'denied') {
          <!-- A failed read is never shown as "no members"; the last list stays visible below it. -->
          <app-empty-state size="sm" [state]="membersState()" (retry)="reload()" />
        } @else if (membersState().s === 'empty') {
          <app-empty-state
            icon="users"
            [title]="i18n.t('workspace.members.empty.title')"
            [description]="i18n.t('workspace.members.empty.description')"
          />
        }
        @if (members().length > 0) {
          <div class="divide-y divide-white/5">
            @for (m of members(); track m.user_id) {
              <div class="px-6 py-4 flex items-center gap-4">
                <div
                  class="w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 text-cyan-100 bg-white/[0.04] ring-1 ring-cyan-400/30"
                >
                  {{ initial(m) }}
                </div>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="font-medium text-white truncate">
                      @if (m.first_name || m.last_name) {
                        {{ m.first_name }} {{ m.last_name }}
                      } @else {
                        {{ m.username }}
                      }
                    </span>
                    @if (m.is_current_user) {
                      <span class="text-[9px] px-1.5 py-0.5 bg-white/10 text-gray-300 rounded uppercase tracking-wider font-semibold">
                        {{ i18n.t('workspace.members.badge.you') }}
                      </span>
                    }
                    @if (isPending(m)) {
                      <span class="text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wider font-semibold inline-flex items-center gap-1 bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30">
                        <app-icon name="mail" [size]="9" />
                        {{ i18n.t('workspace.members.badge.pending') }}
                      </span>
                    } @else {
                      <span class="text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wider font-semibold inline-flex items-center gap-1 bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30">
                        <app-icon name="check" [size]="9" />
                        {{ i18n.t('workspace.status.active') }}
                      </span>
                    }
                  </div>
                  <div class="text-sm text-gray-400 truncate">{{ m.email }}</div>
                  @if (appEntitlementsEnabled()) {
                    <div class="mt-1 flex flex-wrap gap-1" [attr.aria-label]="i18n.t('workspace.members.invite.app_access')">
                      @for (app of memberAppOptions(m); track app.key) {
                        @if ((m.app_entitlements || []).includes(app.key)) {
                          <span class="rounded border border-cyan-400/20 bg-cyan-500/[0.07] px-1.5 py-0.5 text-[10px] text-cyan-200">
                            {{ app.label }}
                          </span>
                        }
                      }
                    </div>
                  }
                  <div class="text-xs text-gray-500 mt-0.5 inline-flex items-center gap-1">
                    <app-icon name="clock" [size]="11" />
                    @if (isPending(m)) {
                      {{ i18n.t('workspace.members.joined.invited', { date: (m.joined_at | date: 'mediumDate') || '' }) }}
                    } @else {
                      {{ i18n.t('workspace.members.joined.joined', { date: (m.joined_at | date: 'mediumDate') || '' }) }}
                    }
                  </div>
                </div>

                <div class="text-sm">
                  @if (canAdmin() && !isOwner(m) && !m.is_current_user) {
                    <select
                      [value]="memberTemplate(m)"
                      (change)="changeRole(m, $event)"
                      [disabled]="savingMember() === m.user_id"
                      class="workspace-select workspace-select-sm"
                      data-testid="workspace-member-role-template"
                    >
                      @for (template of editableTemplates; track template.id) {
                        <option [value]="template.id">{{ i18n.t(template.labelKey) }}</option>
                      }
                    </select>
                  } @else {
                    <span
                      class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full capitalize font-medium"
                      [ngClass]="roleBadgeClass(roleLabel(m))"
                    >
                      @if (isOwner(m)) {
                        <app-icon name="crown" [size]="11" />
                      } @else if (isAdmin(m)) {
                        <app-icon name="shield-check" [size]="11" />
                      } @else {
                        <app-icon name="user-round" [size]="11" />
                      }
                      {{ roleName(roleLabel(m)) }}
                    </span>
                  }
                </div>

                @if (canAdmin() && !isOwner(m) && !m.is_current_user) {
                  <button
                    type="button"
                    (click)="requestRemove(m)"
                    [disabled]="savingMember() === m.user_id"
                    class="text-red-400 hover:bg-red-500/10 p-2 rounded transition"
                    [title]="i18n.t('workspace.members.remove.tooltip')"
                  >
                    <app-icon name="trash-2" [size]="14" />
                  </button>
                }
              </div>
            }
          </div>
        }
      </section>
    </div>

    <app-confirm-dialog
      [open]="!!pendingRemove()"
      [title]="i18n.t('workspace.members.remove.confirm_title')"
      [description]="pendingRemove() ? i18n.t('workspace.members.remove.confirm_description', { name: pendingRemove()?.email || pendingRemove()?.username || '' }) : ''"
      [confirmLabel]="i18n.t('workspace.members.remove.confirm_cta')"
      tone="danger"
      icon="trash-2"
      (cancel)="pendingRemove.set(null)"
      (confirm)="confirmRemove()"
    />

    <!-- A role change is chosen, summarised, confirmed, then read back: the select alone sends nothing. -->
    <app-confirm-dialog
      [open]="!!pendingRole()"
      [title]="i18n.t('workspace.members.role_change.title')"
      [description]="roleChangeSummary()"
      [confirmLabel]="i18n.t('workspace.members.role_change.confirm')"
      icon="users"
      (cancel)="pendingRole.set(null)"
      (confirm)="confirmRoleChange()"
    />
  `,
  styles: [`
    .workspace-select {
      min-height: 40px;
      appearance: none;
      -webkit-appearance: none;
      border-radius: 6px;
      border: 1px solid rgba(255, 255, 255, 0.10);
      background-color: rgba(0, 0, 0, 0.26);
      color: rgb(243 244 246);
      padding: 0.5rem 2rem 0.5rem 0.75rem;
      font-size: 0.875rem;
      line-height: 1.25rem;
      color-scheme: dark;
      background-image:
        linear-gradient(45deg, transparent 50%, rgb(148 163 184) 50%),
        linear-gradient(135deg, rgb(148 163 184) 50%, transparent 50%);
      background-position:
        calc(100% - 15px) calc(50% - 2px),
        calc(100% - 10px) calc(50% - 2px);
      background-size: 5px 5px, 5px 5px;
      background-repeat: no-repeat;
    }
    .workspace-select-sm {
      min-height: 32px;
      padding-top: 0.25rem;
      padding-bottom: 0.25rem;
      font-size: 0.8125rem;
    }
    .workspace-select:focus {
      outline: none;
      border-color: rgba(56, 189, 248, 0.65);
      box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.16);
    }
  `],
})
export class WorkspaceMembersComponent {
  readonly i18n = inject(I18nService);
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly toastr = inject(ToastrService);

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  readonly members = signal<WorkspaceMemberDetail[]>([]);
  /** The members read, under the shared contract: a failure keeps the last list, never an empty one. */
  readonly membersState = signal<LoadState<WorkspaceMemberDetail[]>>(LOADING);
  /** A role picked in the select, waiting for confirmation; nothing is sent before it. */
  readonly pendingRole = signal<{ member: WorkspaceMemberDetail; from: RoleTemplate; to: RoleTemplate } | null>(null);
  readonly roleChangeSummary = computed(() => {
    const pending = this.pendingRole();
    if (!pending) return '';
    return this.i18n.t('workspace.members.role_change.summary', {
      name: pending.member.email || pending.member.username,
      from: this.roleName(pending.from),
      to: this.roleName(pending.to),
      effect: this.i18n.t(`workspace.members.role_change.effect.${pending.to}`),
    });
  });
  private readonly http = inject(HttpClient);
  readonly availableUsers = signal<AvailableWorkspaceUser[]>([]);
  readonly loading = signal(true);
  readonly inviting = signal(false);
  readonly savingMember = signal<string | null>(null);
  readonly pendingRemove = signal<WorkspaceMemberDetail | null>(null);
  readonly accessRoute = computed(() => {
    const slug = this.routeSlug() || this.workspaceService.currentSlug();
    return slug ? ['/workspace', slug, 'access'] : '/governance/access';
  });

  inviteEmail = '';
  inviteTemplate: RoleTemplate = 'workspace_contributor';
  readonly inviteTemplates = INVITE_TEMPLATES;
  readonly editableTemplates = INVITE_TEMPLATES.filter((item) => item.inviteable);
  inviteAppEntitlements: WorkspaceAppEntitlement[] = [];
  readonly inviteAppOptions = computed(() => workspaceAppEntitlementOptions(
    this.workspaceService.current(),
  ));
  readonly appEntitlementsEnabled = this.workspaceService.appEntitlementsEnabled;
  private inviteOptionsFingerprint = '';

  readonly canAdmin = computed(() => {
    return this.workspaceService.isAdmin();
  });

  constructor() {
    effect(() => {
      const options = this.inviteAppOptions();
      const fingerprint = `${this.workspaceService.current()?.id || ''}:${options.map((item) => item.key).join('|')}`;
      if (fingerprint === this.inviteOptionsFingerprint) return;
      this.inviteOptionsFingerprint = fingerprint;
      this.inviteAppEntitlements = options.map((item) => item.key);
    });
    effect(() => {
      const slug = this.routeSlug();
      if (slug) this.load(slug);
    });
  }

  load(slug: string): void {
    this.loading.set(true);
    settleRead(this.workspaceService.listMembers(slug), { previous: this.membersState() }).subscribe((state) => {
      if (this.routeSlug() !== slug) return;
      this.membersState.set(state);
      if (state.s === 'loading') return;
      this.loading.set(false);
      // Only a successful read replaces the list.
      if (state.s === 'ready') this.members.set(state.value);
      if (state.s === 'empty') this.members.set([]);
    });
  }

  reload(): void {
    const slug = this.routeSlug();
    if (slug) this.load(slug);
  }

  invite(): void {
    const slug = this.routeSlug();
    if (!slug) return;
    const email = this.inviteEmail.trim();
    if (!email) return;
    this.inviting.set(true);
    const appEntitlements = this.appEntitlementsEnabled()
      ? [...this.inviteAppEntitlements]
      : undefined;
    this.workspaceService.inviteMember(slug, email, this.inviteTemplate, appEntitlements).subscribe({
      next: (res) => {
        this.inviting.set(false);
        const role = this.roleName(this.inviteTemplate).toLocaleLowerCase();
        if (res?.action === 'unchanged') {
          this.toastr.info(
            this.i18n.t('workspace.members.toast.already', { email }),
            this.i18n.t('workspace.members.toast.already_title'),
          );
        } else if (res?.invitation_email_sent) {
          this.toastr.success(
            this.i18n.t('workspace.members.toast.invited', { email, role }),
            this.i18n.t('workspace.members.toast.invited_title'),
          );
        } else {
          this.toastr.success(
            this.i18n.t('workspace.members.toast.added', { email, role }),
            this.i18n.t('workspace.members.toast.added_title'),
          );
        }
        this.inviteEmail = '';
        this.availableUsers.set([]);
        this.inviteTemplate = 'workspace_contributor';
        this.inviteAppEntitlements = this.inviteAppOptions().map((app) => app.key);
        this.load(slug);
      },
      error: (err) => {
        this.inviting.set(false);
        this.availableUsers.set([]);
        if (err?.status === 409 && err?.error?.detail === 'User is already a member') {
          this.toastr.info(
            this.i18n.t('workspace.members.toast.already', { email }),
            this.i18n.t('workspace.members.toast.already_title'),
          );
          this.inviteEmail = '';
          this.load(slug);
          return;
        }
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.members.toast.invite_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
      },
    });
  }

  searchExistingUsers(): void {
    const slug = this.routeSlug();
    const query = this.inviteEmail.trim();
    if (!slug || query.length < 2) {
      this.availableUsers.set([]);
      return;
    }
    this.workspaceService.availableMembers(slug, query).subscribe({
      next: (users) => this.availableUsers.set(users),
      error: () => this.availableUsers.set([]),
    });
  }

  inviteHasApp(app: WorkspaceAppEntitlement): boolean {
    return this.inviteAppEntitlements.includes(app);
  }

  setInviteApp(app: WorkspaceAppEntitlement, event: Event): void {
    const enabled = (event.target as HTMLInputElement).checked;
    this.inviteAppEntitlements = toggleWorkspaceAppEntitlement(
      this.inviteAppEntitlements,
      app,
      enabled,
      this.inviteAppOptions(),
    );
  }

  memberAppOptions(member: WorkspaceMemberDetail) {
    return workspaceAppEntitlementOptions(
      this.workspaceService.current(),
      member.app_entitlements || [],
    );
  }

  /** Picking a role only opens the confirmation; the select returns to the current role. */
  changeRole(member: WorkspaceMemberDetail, ev: Event): void {
    const select = ev.target as HTMLSelectElement;
    const to = select.value as RoleTemplate;
    const from = this.memberTemplate(member);
    select.value = from;
    if (to === from || this.savingMember()) return;
    this.pendingRole.set({ member, from, to });
  }

  /**
   * Sends the change with the role the administrator saw: if another
   * administrator changed it meanwhile, the server answers 409 and nothing is
   * overwritten. The role shown afterwards is read back from the server.
   */
  confirmRoleChange(): void {
    const pending = this.pendingRole();
    const slug = this.routeSlug();
    if (!pending || !slug) return;
    this.pendingRole.set(null);
    const { member, from, to } = pending;
    const name = member.email || member.username;
    this.savingMember.set(member.user_id);
    settleWrite(this.http.patch(
      `/api/v1/auth/workspaces/${encodeURIComponent(slug)}/members/${encodeURIComponent(member.user_id)}`,
      { role_template: to, expected_role_template: from },
    )).subscribe((outcome) => {
      if (outcome.s === 'sent') return;
      if (outcome.s === 'confirmed' || outcome.s === 'accepted') {
        this.readBackRole(slug, member, to);
        return;
      }
      this.savingMember.set(null);
      if (outcome.s === 'failed' && outcome.status === 409) {
        this.toastr.warning(this.i18n.t('workspace.members.role_change.conflict', { name }), this.i18n.t('workspace.toast.error_title'));
      } else if (outcome.s === 'failed') {
        const cause = writeFailureCause(outcome);
        this.toastr.error(
          `${this.i18n.t('workspace.members.toast.role_failed')} ${this.i18n.t(cause.key, cause.params)}`,
          this.i18n.t('workspace.toast.error_title'),
        );
      } else {
        this.toastr.warning(this.i18n.t('state.write.unknown'), this.i18n.t('workspace.toast.error_title'));
      }
      // Whatever happened, show the roles as the server holds them now.
      this.load(slug);
    });
  }

  /** The role shown after a change comes from the server, for this very person. */
  private readBackRole(slug: string, member: WorkspaceMemberDetail, expected: RoleTemplate): void {
    const name = member.email || member.username;
    settleRead(this.workspaceService.listMembers(slug), { previous: this.membersState() }).subscribe((state) => {
      if (state.s === 'loading' || this.routeSlug() !== slug) return;
      this.savingMember.set(null);
      this.membersState.set(state);
      if (state.s !== 'ready') {
        this.toastr.warning(this.i18n.t('workspace.members.role_change.unread', { name }), this.i18n.t('workspace.members.toast.role_title'));
        return;
      }
      this.members.set(state.value);
      const current = state.value.find((row) => row.user_id === member.user_id);
      const effective = current ? this.memberTemplate(current) : null;
      if (effective === expected) {
        this.toastr.success(
          this.i18n.t('workspace.members.toast.role', { name, role: this.roleName(expected).toLocaleLowerCase() }),
          this.i18n.t('workspace.members.toast.role_title'),
        );
      } else {
        this.toastr.warning(
          this.i18n.t('workspace.members.role_change.differs', { name, role: effective ? this.roleName(effective) : '—' }),
          this.i18n.t('workspace.members.toast.role_title'),
        );
      }
    });
  }

  requestRemove(member: WorkspaceMemberDetail): void {
    this.pendingRemove.set(member);
  }

  confirmRemove(): void {
    const member = this.pendingRemove();
    const slug = this.routeSlug();
    if (!member || !slug) return;
    this.pendingRemove.set(null);
    const label = member.email || member.username;
    this.savingMember.set(member.user_id);
    this.workspaceService.removeMember(slug, member.user_id).subscribe({
      next: () => {
        this.savingMember.set(null);
        this.toastr.success(
          this.i18n.t('workspace.members.toast.removed', { name: label }),
          this.i18n.t('workspace.members.toast.removed_title'),
        );
        this.load(slug);
      },
      error: (err) => {
        this.savingMember.set(null);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.members.toast.remove_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
      },
    });
  }

  initial(m: WorkspaceMemberDetail): string {
    if (m.first_name) return m.first_name[0]?.toUpperCase() ?? '?';
    const src = m.email || m.username || '?';
    return src[0]?.toUpperCase() ?? '?';
  }

  roleBadgeClass(role: string): string {
    switch (role) {
      case 'owner':
      case 'workspace_owner':
        return 'bg-amber-500/15 text-amber-400 border border-amber-500/30';
      case 'admin':
      case 'workspace_admin':
        return 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30';
      case 'workspace_reviewer':
        return 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30';
      case 'workspace_viewer':
        return 'bg-white/5 text-gray-400 border border-white/10';
      default:
        return 'bg-white/5 text-gray-300 border border-white/10';
    }
  }

  isOwner(member: WorkspaceMemberDetail): boolean {
    return member.role === 'owner' || member.role_template === 'workspace_owner';
  }

  isAdmin(member: WorkspaceMemberDetail): boolean {
    return member.role === 'admin' || member.role_template === 'workspace_admin';
  }

  memberTemplate(member: WorkspaceMemberDetail): RoleTemplate {
    if (member.role_template === 'workspace_viewer'
      || member.role_template === 'workspace_contributor'
      || member.role_template === 'workspace_reviewer'
      || member.role_template === 'workspace_admin'
      || member.role_template === 'workspace_owner') {
      return member.role_template;
    }
    if (member.role === 'owner') return 'workspace_owner';
    if (member.role === 'admin') return 'workspace_admin';
    return 'workspace_contributor';
  }

  roleLabel(member: WorkspaceMemberDetail): string {
    return this.memberTemplate(member);
  }

  /** Role values come from the API — translate with a fallback to the raw value. */
  roleName(role: string): string {
    const templateKeys: Record<string, string> = {
      workspace_viewer: 'workspace.role.viewer',
      workspace_contributor: 'workspace.role.contributor',
      workspace_reviewer: 'workspace.role.reviewer',
      workspace_admin: 'workspace.role.admin',
      workspace_owner: 'workspace.role.owner',
      owner: 'workspace.role.owner',
      admin: 'workspace.role.admin',
      member: 'workspace.role.member',
    };
    const key = templateKeys[role] || ('workspace.role.' + role);
    const label = this.i18n.t(key);
    return label === key ? role : label;
  }

  isPending(member: WorkspaceMemberDetail): boolean {
    return member.status === 'pending';
  }
}
