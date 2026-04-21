import { Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { WorkspaceService } from '@app/core/workspace.service';

interface Capability {
  key: string;
  label: string;
  description: string;
  icon: string;
}

interface Role {
  key: string;
  label: string;
  icon: string;
  tone: string;
  tagline: string;
}

@Component({
  selector: 'app-access-roles',
  standalone: true,
  imports: [RouterLink, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Govern"
      title="Access & Roles"
      icon="shield-check"
      subtitle="Who can do what inside this workspace."
    >
      @if (membersLink(); as link) {
        <a
          [routerLink]="link"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
        >
          <app-icon name="users" [size]="14" /> Manage members
        </a>
      } @else {
        <span
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-400 ring-1 ring-white/10"
          title="Select a workspace first"
        >
          <app-icon name="users" [size]="14" /> Manage members
        </span>
      }
    </app-section-header>

    <div class="mb-5 rounded-md p-3 bg-amber-500/5 ring-1 ring-amber-500/25 flex items-start gap-3">
      <app-icon name="info" [size]="14" class="text-amber-400 mt-0.5 shrink-0" />
      <p class="text-[11px] text-amber-200/80 leading-relaxed flex-1">
        Built-in roles are enforced server-side. Dynamic role creation and per-capability customisation
        are coming with the RBAC release — this page stays read-only until then.
      </p>
    </div>

    <!-- Role overview -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      @for (r of roles; track r.key) {
        <div class="t-card t-elevated rounded-md p-5 relative overflow-hidden">
          <div
            class="w-10 h-10 rounded-md flex items-center justify-center mb-3 ring-1"
            [class.bg-amber-500\\/15]="r.tone === 'amber'"
            [class.ring-amber-500\\/30]="r.tone === 'amber'"
            [class.text-amber-400]="r.tone === 'amber'"
            [class.bg-brand-500\\/15]="r.tone === 'brand'"
            [class.ring-brand-500\\/30]="r.tone === 'brand'"
            [class.text-brand-400]="r.tone === 'brand'"
            [class.bg-gray-500\\/15]="r.tone === 'gray'"
            [class.ring-gray-500\\/30]="r.tone === 'gray'"
            [class.text-gray-300]="r.tone === 'gray'"
          >
            <app-icon [name]="r.icon" [size]="18" />
          </div>
          <h3 class="text-base font-semibold text-white">{{ r.label }}</h3>
          <p class="text-xs text-gray-400 mt-1">{{ r.tagline }}</p>
        </div>
      }
    </div>

    <!-- Matrix -->
    <section class="t-card t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="table-properties" [size]="16" class="text-brand-400" /> Capability matrix
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          Built-in roles
        </span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-white/5">
              <th class="px-5 py-3 font-semibold">Capability</th>
              @for (r of roles; track r.key) {
                <th class="px-5 py-3 font-semibold text-center">{{ r.label }}</th>
              }
            </tr>
          </thead>
          <tbody class="divide-y divide-white/5">
            @for (cap of capabilities; track cap.key) {
              <tr class="hover:bg-white/[0.02] transition">
                <td class="px-5 py-3">
                  <div class="flex items-start gap-2">
                    <app-icon [name]="cap.icon" [size]="14" class="text-brand-400 mt-0.5" />
                    <div>
                      <div class="text-white font-medium">{{ cap.label }}</div>
                      <div class="text-[11px] text-gray-500">{{ cap.description }}</div>
                    </div>
                  </div>
                </td>
                @for (r of roles; track r.key) {
                  <td class="px-5 py-3 text-center">
                    @if (matrix[cap.key][r.key]) {
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

    <div class="mt-5 flex items-center gap-2 text-xs text-gray-500">
      <app-icon name="info" [size]="12" />
      Custom roles are planned for a future release. For now, members map to one of the three built-in roles.
    </div>
  `,
})
export class AccessRolesComponent {
  private readonly workspace = inject(WorkspaceService);

  readonly membersLink = computed<unknown[] | null>(() => {
    const current = this.workspace.current();
    return current ? ['/workspace', current.slug, 'members'] : null;
  });

  readonly roles: Role[] = [
    { key: 'owner', label: 'Owner', icon: 'crown', tone: 'amber', tagline: 'Full control, including billing and deletion.' },
    { key: 'admin', label: 'Admin', icon: 'shield-check', tone: 'brand', tagline: 'Manage members, systems and knowledge.' },
    { key: 'member', label: 'Member', icon: 'user-round', tone: 'gray', tagline: 'Run systems and consume results.' },
  ];

  readonly capabilities: Capability[] = [
    { key: 'workspace.settings', label: 'Update workspace settings', icon: 'settings', description: 'Name, slug, metadata' },
    { key: 'workspace.delete', label: 'Delete workspace', icon: 'trash-2', description: 'Archive and purge the entire workspace' },
    { key: 'members.invite', label: 'Invite members', icon: 'user-plus', description: 'Add people by email' },
    { key: 'members.roles', label: 'Change roles', icon: 'key-round', description: 'Promote or demote other members' },
    { key: 'members.remove', label: 'Remove members', icon: 'user-x', description: 'Revoke workspace access' },
    { key: 'systems.create', label: 'Create systems', icon: 'layers', description: 'New AI systems' },
    { key: 'systems.edit', label: 'Edit systems', icon: 'settings-2', description: 'Configure prompts, models, guardrails' },
    { key: 'systems.run', label: 'Run systems', icon: 'play', description: 'Chat & API calls' },
    { key: 'knowledge.upload', label: 'Upload knowledge', icon: 'cloud-upload', description: 'Ingest documents' },
    { key: 'knowledge.delete', label: 'Delete knowledge', icon: 'trash-2', description: 'Remove collections and chunks' },
    { key: 'audit.view', label: 'View audit logs', icon: 'scroll-text', description: 'Inspect workspace activity' },
  ];

  readonly matrix: Record<string, Record<string, boolean>> = {
    'workspace.settings': { owner: true, admin: true, member: false },
    'workspace.delete': { owner: true, admin: false, member: false },
    'members.invite': { owner: true, admin: true, member: false },
    'members.roles': { owner: true, admin: true, member: false },
    'members.remove': { owner: true, admin: true, member: false },
    'systems.create': { owner: true, admin: true, member: false },
    'systems.edit': { owner: true, admin: true, member: false },
    'systems.run': { owner: true, admin: true, member: true },
    'knowledge.upload': { owner: true, admin: true, member: true },
    'knowledge.delete': { owner: true, admin: true, member: false },
    'audit.view': { owner: true, admin: true, member: false },
  };
}
