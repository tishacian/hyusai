import { Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe, NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import {
  WorkspaceMemberDetail,
  WorkspaceService,
  toggleWorkspaceAppEntitlement,
  type WorkspaceAppEntitlement,
  workspaceAppEntitlementOptions,
} from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';

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
              required
              class="flex-1 min-w-[220px] px-3 py-2 rounded bg-black/20 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 transition"
            />
            <select
              [(ngModel)]="inviteRole"
              name="role"
              class="workspace-select"
            >
              <option value="member">{{ i18n.t('workspace.role.member') }}</option>
              <option value="admin">{{ i18n.t('workspace.role.admin') }}</option>
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

        @if (loading()) {
          <div class="p-6 space-y-3">
            <app-skeleton height="56px" />
            <app-skeleton height="56px" />
            <app-skeleton height="56px" />
          </div>
        } @else if (members().length === 0) {
          <app-empty-state
            icon="users"
            [title]="i18n.t('workspace.members.empty.title')"
            [description]="i18n.t('workspace.members.empty.description')"
          />
        } @else {
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
                      [value]="m.role"
                      (change)="changeRole(m, $event)"
                      [disabled]="savingMember() === m.user_id"
                      class="workspace-select workspace-select-sm"
                    >
                      <option value="admin">{{ i18n.t('workspace.role.admin') }}</option>
                      <option value="member">{{ i18n.t('workspace.role.member') }}</option>
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
  readonly loading = signal(true);
  readonly inviting = signal(false);
  readonly savingMember = signal<string | null>(null);
  readonly pendingRemove = signal<WorkspaceMemberDetail | null>(null);
  readonly accessRoute = computed(() => {
    const slug = this.routeSlug() || this.workspaceService.currentSlug();
    return slug ? ['/workspace', slug, 'access'] : '/governance/access';
  });

  inviteEmail = '';
  inviteRole: 'admin' | 'member' = 'member';
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
    this.workspaceService.listMembers(slug).subscribe({
      next: (list) => {
        this.members.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.members.set([]);
      },
    });
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
    this.workspaceService.inviteMember(slug, email, this.inviteRole, appEntitlements).subscribe({
      next: (res) => {
        this.inviting.set(false);
        const role = this.roleName(this.inviteRole).toLocaleLowerCase();
        if (res?.invitation_email_sent) {
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
        this.inviteAppEntitlements = this.inviteAppOptions().map((app) => app.key);
        this.load(slug);
      },
      error: (err) => {
        this.inviting.set(false);
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

  changeRole(member: WorkspaceMemberDetail, ev: Event): void {
    const slug = this.routeSlug();
    if (!slug) return;
    const newRole = (ev.target as HTMLSelectElement).value as 'admin' | 'member';
    if (newRole === member.role) return;
    this.savingMember.set(member.user_id);
    this.workspaceService.updateMemberRole(slug, member.user_id, newRole).subscribe({
      next: () => {
        this.savingMember.set(null);
        this.toastr.success(
          this.i18n.t('workspace.members.toast.role', {
            name: member.email || member.username,
            role: this.roleName(newRole).toLocaleLowerCase(),
          }),
          this.i18n.t('workspace.members.toast.role_title'),
        );
        this.load(slug);
      },
      error: (err) => {
        this.savingMember.set(null);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.members.toast.role_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
      },
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
        return 'bg-amber-500/15 text-amber-400 border border-amber-500/30';
      case 'admin':
        return 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30';
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

  roleLabel(member: WorkspaceMemberDetail): string {
    if (this.isOwner(member)) return 'owner';
    if (this.isAdmin(member)) return 'admin';
    return 'member';
  }

  /** Role values come from the API — translate with a fallback to the raw value. */
  roleName(role: string): string {
    const key = 'workspace.role.' + role;
    const label = this.i18n.t(key);
    return label === key ? role : label;
  }

  isPending(member: WorkspaceMemberDetail): boolean {
    return member.status === 'pending';
  }
}
