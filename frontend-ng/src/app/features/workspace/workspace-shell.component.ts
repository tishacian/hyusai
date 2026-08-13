import { Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';

interface TabItem {
  path: string;
  labelKey: string;
  icon: string;
  descriptionKey: string;
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
          [breadcrumb]="i18n.t('workspace.shell.breadcrumb')"
          [title]="current.name"
          icon="building-2"
          [subtitle]="i18n.t('workspace.shell.subtitle', { slug: current.slug, role: roleName(current.role) })"
        >
          <app-status-pulse tone="success" [label]="i18n.t('workspace.status.active')" />
        </app-section-header>
      } @else {
        <app-section-header
          [breadcrumb]="i18n.t('workspace.shell.breadcrumb')"
          [title]="i18n.t('workspace.shell.breadcrumb')"
          icon="building-2"
        />
      }

      <div class="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6 md:gap-8">
        <!-- Tabs sidebar -->
        <aside class="space-y-1">
          @for (tab of visibleTabs(); track tab.path) {
            <a
              [routerLink]="tab.path"
              routerLinkActive="bg-white/[0.04] text-white ring-1 ring-cyan-400/35"
              [routerLinkActiveOptions]="{ exact: false }"
              class="block px-3 py-2.5 rounded-md border border-transparent text-sm text-gray-400 hover:text-white hover:bg-white/[0.03] transition"
            >
              <div class="flex items-center gap-2.5">
                <app-icon [name]="tab.icon" [size]="16" class="text-cyan-400" />
                <span class="font-medium">{{ i18n.t(tab.labelKey) }}</span>
              </div>
              <div class="text-xs text-gray-500 mt-0.5 pl-6">{{ i18n.t(tab.descriptionKey) }}</div>
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
  readonly i18n = inject(I18nService);
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
    {
      path: 'settings',
      labelKey: 'workspace.general',
      icon: 'settings',
      descriptionKey: 'workspace.shell.tab.general.description',
    },
    {
      path: 'chat',
      labelKey: 'workspace.shell.tab.chat',
      icon: 'message-square',
      descriptionKey: 'workspace.shell.tab.chat.description',
    },
    {
      path: 'chat-knowledge',
      labelKey: 'workspace.chat_sources.title',
      icon: 'database',
      descriptionKey: 'workspace.shell.tab.chat_knowledge.description',
    },
    {
      path: 'members',
      labelKey: 'workspace.members',
      icon: 'users',
      descriptionKey: 'workspace.shell.tab.members.description',
    },
    {
      path: 'access',
      labelKey: 'workspace.shell.tab.access',
      icon: 'shield-check',
      descriptionKey: 'workspace.shell.tab.access.description',
    },
    {
      path: 'danger',
      labelKey: 'workspace.danger',
      icon: 'shield-alert',
      descriptionKey: 'workspace.shell.tab.danger.description',
    },
  ]);

  readonly visibleTabs = computed(() =>
    this.allTabs().filter((t) => !t.ownerOnly || this.workspaceService.isOwner())
  );

  /** Role values come from the API — translate with a fallback to the raw value. */
  roleName(role: string): string {
    const key = 'workspace.role.' + role;
    const label = this.i18n.t(key);
    return label === key ? role : label;
  }
}
