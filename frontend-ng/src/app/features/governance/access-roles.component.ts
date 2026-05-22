import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import {
  IamMatrix,
  IamMatrixPermission,
  IamSummary,
  RoleTemplate,
  WorkspaceMemberDetail,
  WorkspaceService,
} from '@app/core/workspace.service';

@Component({
  selector: 'app-access-roles',
  standalone: true,
  imports: [FormsModule, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Workspace · Access"
      title="Workspace IAM"
      icon="shield-check"
      subtitle="Workspace IAM templates, labels and effective Capture permissions."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 text-gray-200 ring-1 ring-white/10 transition"
        (click)="load()"
      >
        <app-icon name="refresh-cw" [size]="14" /> Refresh
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
          <section class="t-card t-elevated rounded-md overflow-hidden">
            <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between gap-3">
              <div>
                <h3 class="text-sm font-semibold text-white">Members</h3>
                <p class="text-xs text-gray-500 mt-1">{{ iam.workspace.name }} · {{ iam.enforcement ? 'enforced' : 'dry-run' }}</p>
              </div>
              <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                {{ iam.members.length }} members
              </span>
            </div>
            <div class="divide-y divide-white/5">
              @for (member of members(); track member.user_id) {
                <article class="px-5 py-4 hover:bg-white/[0.02] transition">
                  <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px_minmax(220px,1fr)_96px] lg:items-end">
                    <div class="min-w-0">
                      <div class="flex items-center gap-2">
                        <div class="h-8 w-8 shrink-0 rounded-full bg-white/[0.04] ring-1 ring-brand-400/30 flex items-center justify-center text-xs font-semibold text-brand-200">
                          {{ initial(member) }}
                        </div>
                        <div class="min-w-0">
                          <div class="truncate text-sm font-medium text-white">{{ member.email || member.username }}</div>
                          <div class="truncate text-[11px] text-gray-500">
                            {{ member.username }}
                            @if (member.is_current_user) {
                              · you
                            }
                          </div>
                        </div>
                      </div>
                    </div>

                    <label class="block min-w-0">
                      <span class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1.5">Role template</span>
                      @if (canEditMemberRole(member)) {
                        <span class="ag-select-wrap">
                          <select
                            class="ag-select"
                            [(ngModel)]="member.role_template"
                          >
                            @for (role of roleOptions; track role.value) {
                              <option [ngValue]="role.value" [disabled]="role.value === 'workspace_owner'">
                                {{ role.label }}
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
                      <span class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1.5">Labels</span>
                      <input
                        class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-400/60 disabled:opacity-50"
                        [disabled]="!canEditMemberLabels(member)"
                        [ngModel]="labelsText(member)"
                        (ngModelChange)="setLabels(member, $event)"
                        placeholder="domain:technical, pilot:true"
                      />
                    </label>

                    <button
                      type="button"
                      class="inline-flex h-10 items-center justify-center gap-1.5 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-40 disabled:hover:bg-brand-500"
                      [disabled]="saving() || !canSaveMember(member)"
                      (click)="saveMember(member)"
                    >
                      <app-icon name="save" [size]="14" /> Save
                    </button>
                  </div>
                  @if (!canEditMemberRole(member) && memberRoleTemplate(member) === 'workspace_owner') {
                    <p class="mt-2 pl-10 text-[11px] text-gray-500">{{ memberRoleLockedReason(member) }}</p>
                  }
                </article>
              }
            </div>
          </section>

          <section class="t-card t-elevated rounded-md overflow-hidden">
            <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
              <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
                <app-icon name="table-properties" [size]="16" class="text-brand-400" /> Effective Capture matrix
              </h3>
              <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                {{ matrix()?.role_template || 'subject' }}
              </span>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-white/5">
                    <th class="px-5 py-3 font-semibold">Permission</th>
                    @for (role of roleOptions; track role.value) {
                      <th class="px-5 py-3 font-semibold text-center">{{ role.short }}</th>
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
          <section class="t-card t-elevated rounded-md p-5 border border-brand-500/25 bg-brand-500/[0.04]">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Capability binding</p>
            <h3 class="text-sm font-semibold text-white mt-1">Expert Knowledge Capture</h3>
            <p class="mt-3 text-xs text-gray-400 leading-relaxed">
              This matrix drives the System Capture cockpit and the backend routes behind
              <span class="font-mono text-gray-200">expert_knowledge_capture</span>.
            </p>
            <div class="mt-3 flex flex-wrap gap-2 text-[10px] uppercase tracking-wider">
              <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">capture_session</span>
              <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">knowledge_proposal</span>
              <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">voice_runtime</span>
            </div>
          </section>

          <section class="t-card t-elevated rounded-md p-5">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">IAM config</p>
                <h3 class="text-sm font-semibold text-white mt-1">Workspace flags</h3>
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
                    <span class="block text-xs text-gray-100 font-medium">{{ flag.label }}</span>
                    <span class="block text-[11px] text-gray-500 mt-0.5">{{ flag.description }}</span>
                  </span>
                </label>
              }
            </div>
            <button
              type="button"
              class="mt-4 w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
              [disabled]="saving()"
              (click)="saveFlags()"
            >
              <app-icon name="save" [size]="14" /> Save flags
            </button>
          </section>

          <section class="t-card t-elevated rounded-md p-5">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Current subject</p>
            <h3 class="text-sm font-semibold text-white mt-1">{{ matrix()?.role_template || 'Unknown role' }}</h3>
            <p class="mt-3 text-xs text-gray-500 leading-relaxed">
              Buttons in Capture use this matrix for client-side affordances. The backend remains the authority and emits IAM deny audit rows.
            </p>
          </section>
        </aside>
      </section>
    } @else {
      <section class="t-card t-elevated rounded-md p-8 text-center text-gray-400">
        {{ loading() ? 'Loading IAM configuration...' : 'Select a workspace to inspect IAM.' }}
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

  readonly summary = signal<IamSummary | null>(null);
  readonly matrix = signal<IamMatrix | null>(null);
  readonly members = signal<WorkspaceMemberDetail[]>([]);
  readonly roleFlags = signal<Record<string, boolean>>({});
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);

  readonly roleOptions: Array<{ value: RoleTemplate; label: string; short: string }> = [
    { value: 'workspace_viewer', label: 'Viewer', short: 'Viewer' },
    { value: 'workspace_contributor', label: 'Contributor', short: 'Contrib.' },
    { value: 'workspace_reviewer', label: 'Reviewer', short: 'Reviewer' },
    { value: 'workspace_admin', label: 'Admin', short: 'Admin' },
    { value: 'workspace_owner', label: 'Owner', short: 'Owner' },
  ];

  readonly flagOptions = [
    {
      key: 'contributors_see_only_own_sessions',
      label: 'Contributors see only own sessions',
      description: 'Narrows Capture lists for contributors while reviewers and admins keep workspace scope.',
    },
    {
      key: 'require_second_eye_for_ingestion',
      label: 'Require second eye for ingestion',
      description: 'Prevents the author from triggering final ingestion approval when enabled.',
    },
    {
      key: 'reviewers_inherit_contributor',
      label: 'Reviewers inherit contributor',
      description: 'Lets reviewers create and execute their own capture sessions.',
    },
  ];

  readonly currentWorkspace = computed(() => this.workspace.current());

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
        this.error.set('Unable to load IAM summary. Admin role is required.');
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
    return this.roleOptions.find((item) => item.value === role)?.label || 'Contributor';
  }

  roleBadgeClass(role: RoleTemplate): string {
    const base = 'inline-flex h-10 w-full items-center gap-1.5 rounded border px-3 text-sm font-medium';
    if (role === 'workspace_owner') return `${base} border-amber-500/30 bg-amber-500/10 text-amber-200`;
    if (role === 'workspace_admin') return `${base} border-brand-400/30 bg-brand-500/10 text-brand-100`;
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
    if (member.is_current_user) return 'Your own owner role is managed through ownership transfer.';
    if (!this.subjectIsOwner()) return 'Only a workspace owner can change another owner role.';
    return 'At least one workspace owner must remain.';
  }

  setLabels(member: WorkspaceMemberDetail, value: string): void {
    member.custom_labels = value
      .split(',')
      .map((label) => label.trim())
      .filter(Boolean);
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
        this.error.set('Unable to save IAM flags.');
      },
    });
  }

  saveMember(member: WorkspaceMemberDetail): void {
    const roleTemplate = (member.role_template || 'workspace_contributor') as RoleTemplate;
    if (roleTemplate === 'workspace_owner') {
      this.error.set('Owner assignment is managed through ownership transfer.');
      return;
    }
    this.saving.set(true);
    this.workspace
      .updateIamMember(member.user_id, {
        role_template: roleTemplate,
        custom_labels: member.custom_labels || [],
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.load();
        },
        error: () => {
          this.saving.set(false);
          this.error.set('Unable to save member IAM settings.');
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
