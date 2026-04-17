import { Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';

interface TabItem {
  path: string;
  label: string;
  icon: string;
  description: string;
  ownerOnly?: boolean;
}

/**
 * Workspace admin shell — displays tabs (General / Members / Danger zone) and a sidebar.
 * Child routes render in the main area.
 */
@Component({
  selector: 'app-workspace-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="max-w-6xl mx-auto">
      <!-- Header -->
      <header class="mb-8">
        <div class="flex items-center gap-3 mb-2">
          @if (workspaceService.current(); as current) {
            <div class="w-12 h-12 rounded-lg bg-brand-500 text-white flex items-center justify-center text-lg font-semibold">
              {{ initial(current.name) }}
            </div>
            <div>
              <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">
                {{ current.name }}
              </h1>
              <div class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                <span class="capitalize">{{ current.role }}</span>
                <span>·</span>
                <span class="font-mono text-xs">{{ current.slug }}</span>
              </div>
            </div>
          }
        </div>
      </header>

      <div class="grid grid-cols-[220px_1fr] gap-8">
        <!-- Sidebar tabs -->
        <aside class="space-y-1">
          @for (tab of visibleTabs(); track tab.path) {
            <a
              [routerLink]="tab.path"
              routerLinkActive="bg-brand-50 dark:bg-brand-500/10 text-brand-700 dark:text-brand-400 border-brand-500"
              [routerLinkActiveOptions]="{ exact: false }"
              class="block px-3 py-2.5 rounded-lg border-l-2 border-transparent text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
            >
              <div class="flex items-center gap-2">
                <span>{{ tab.icon }}</span>
                <span class="font-medium">{{ tab.label }}</span>
              </div>
              <div class="text-xs text-gray-500 dark:text-gray-500 mt-0.5 pl-6">
                {{ tab.description }}
              </div>
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
    { path: 'settings', label: 'General', icon: '⚙️', description: 'Name, identity, metadata' },
    { path: 'members', label: 'Members', icon: '👥', description: 'Invite, roles, remove' },
    {
      path: 'danger',
      label: 'Danger zone',
      icon: '⚠️',
      description: 'Leave, transfer, delete',
    },
  ]);

  readonly visibleTabs = computed(() =>
    this.allTabs().filter((t) => !t.ownerOnly || this.workspaceService.isOwner())
  );

  initial(name: string): string {
    const trimmed = (name || '').trim();
    if (!trimmed) return '?';
    const parts = trimmed.split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return trimmed.slice(0, 2).toUpperCase();
  }
}
