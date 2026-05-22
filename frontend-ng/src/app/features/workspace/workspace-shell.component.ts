import { Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';

interface TabItem {
  path: string;
  label: string;
  icon: string;
  description: string;
  ownerOnly?: boolean;
}

@Component({
  selector: 'app-workspace-shell',
  standalone: true,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    IconComponent,
    SectionHeaderComponent,
    StatusPulseComponent,
  ],
  template: `
    <div class="max-w-6xl mx-auto">
      @if (workspaceService.current(); as current) {
        <app-section-header
          breadcrumb="Workspace"
          [title]="current.name"
          icon="building-2"
          [subtitle]="'Slug · ' + current.slug + ' · Your role · ' + current.role"
        >
          <app-status-pulse tone="success" label="Active" />
        </app-section-header>
      } @else {
        <app-section-header breadcrumb="Workspace" title="Workspace" icon="building-2" />
      }

      <div class="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6 md:gap-8">
        <!-- Tabs sidebar -->
        <aside class="space-y-1">
          @for (tab of visibleTabs(); track tab.path) {
            <a
              [routerLink]="tab.path"
              routerLinkActive="bg-white/[0.04] text-white ring-1 ring-brand-400/35"
              [routerLinkActiveOptions]="{ exact: false }"
              class="block px-3 py-2.5 rounded-md border border-transparent text-sm text-gray-400 hover:text-white hover:bg-white/[0.03] transition"
            >
              <div class="flex items-center gap-2.5">
                <app-icon [name]="tab.icon" [size]="16" class="text-brand-400" />
                <span class="font-medium">{{ tab.label }}</span>
              </div>
              <div class="text-xs text-gray-500 mt-0.5 pl-6">{{ tab.description }}</div>
            </a>
          }
        </aside>

        <!-- Content -->
        <section class="min-w-0">
          <router-outlet />
        </section>
      </div>
    </div>
  `,
})
export class WorkspaceShellComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);

  private readonly routeSlug = toSignal(
    this.route.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  constructor() {
    effect(() => {
      const slug = this.routeSlug();
      if (!slug) return;
      const list = this.workspaceService.workspaces();
      if (list.length === 0) {
        this.workspaceService.loadWorkspaces().subscribe(() => {
          if (slug !== this.workspaceService.currentSlug()) {
            this.workspaceService.switchWorkspace(slug);
          }
        });
      } else if (slug !== this.workspaceService.currentSlug()) {
        this.workspaceService.switchWorkspace(slug);
      }
    });
  }

  readonly allTabs = signal<TabItem[]>([
    { path: 'settings', label: 'General', icon: 'settings', description: 'Name, identity, metadata' },
    {
      path: 'chat',
      label: 'Chat',
      icon: 'message-square',
      description: 'Expanded workspace assistant',
    },
    {
      path: 'chat-knowledge',
      label: 'Chat & Knowledge',
      icon: 'database',
      description: 'Knowledge scopes, chat defaults',
    },
    { path: 'members', label: 'Members', icon: 'users', description: 'Invite, roles, remove' },
    {
      path: 'access',
      label: 'Access & IAM',
      icon: 'shield-check',
      description: 'Role templates, labels, flags',
    },
    {
      path: 'danger',
      label: 'Danger zone',
      icon: 'shield-alert',
      description: 'Leave, transfer, delete',
    },
  ]);

  readonly visibleTabs = computed(() =>
    this.allTabs().filter((t) => !t.ownerOnly || this.workspaceService.isOwner())
  );
}
