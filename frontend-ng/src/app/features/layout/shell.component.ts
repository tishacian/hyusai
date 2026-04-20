import { ChangeDetectionStrategy, Component, HostListener, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { AuthApiService } from '@app/core/auth-api.service';
import { AuthBootstrapService } from '@app/core/auth-bootstrap.service';
import { ThemeService } from '@app/core/theme.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';

interface NavItem {
  label: string;
  icon: string;
  route: string;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

interface Crumb {
  label: string;
  icon: string;
  route?: string | any[];
}

@Component({
  selector: 'app-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    FormsModule,
    IconComponent,
    StatusPulseComponent,
  ],
  template: `
    <div class="flex h-screen overflow-hidden relative">
      <!-- Sidebar -->
      <aside
        class="flex flex-col glass border-r border-white/5 transition-all duration-200 z-20 relative"
        [class.w-64]="!collapsed()"
        [class.w-[72px]]="collapsed()"
      >
        <!-- Brand -->
        <div class="flex items-center gap-2.5 px-4 py-4 border-b border-white/5">
          <div
            class="w-9 h-9 rounded-lg flex items-center justify-center text-white font-bold text-sm shrink-0 bg-gradient-to-br from-brand-400 via-brand-500 to-violet-500 shadow-glow-sm"
          >
            A
          </div>
          @if (!collapsed()) {
            <div class="min-w-0 flex-1">
              <div class="text-white font-semibold tracking-tight leading-tight">Agentium</div>
              <app-status-pulse tone="accent" label="Live" />
            </div>
          }
        </div>

        <!-- Workspace switcher -->
        @if (!collapsed()) {
          <div class="px-3 pt-3 pb-2 border-b border-white/5 relative" (click)="$event.stopPropagation()">
            <div class="text-[10px] text-gray-500 uppercase tracking-[0.14em] px-1 mb-1 font-semibold">
              Workspace
            </div>
            <button
              type="button"
              (click)="toggleWorkspaceMenu($event)"
              class="w-full flex items-center gap-2 px-2 py-2 rounded-md hover:bg-white/5 transition text-left ring-1 ring-transparent hover:ring-white/10"
            >
              @if (workspaceService.current(); as current) {
                <div
                  class="w-7 h-7 rounded-md text-white flex items-center justify-center text-xs font-semibold shrink-0 bg-gradient-to-br from-brand-500 to-violet-500"
                >
                  {{ workspaceInitial(current.name) }}
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-white truncate">{{ current.name }}</div>
                  <div class="text-[10px] text-gray-500 capitalize">{{ current.role }}</div>
                </div>
              } @else {
                <div class="w-7 h-7 rounded-md bg-gray-700 text-gray-400 flex items-center justify-center text-xs shrink-0">
                  <app-icon name="help-circle" [size]="14" />
                </div>
                <div class="flex-1 text-sm text-gray-400 truncate">No workspace</div>
              }
              <app-icon name="chevron-down" [size]="14" class="text-gray-500" />
            </button>

            @if (workspaceMenuOpen()) {
              <div
                class="absolute left-3 right-3 top-full mt-1 glass rounded-md shadow-elevated z-40 overflow-hidden border border-white/10"
              >
                <div class="px-3 py-2 text-[10px] text-gray-400 uppercase tracking-wider border-b border-white/5 font-semibold">
                  Switch workspace
                </div>
                <div class="max-h-60 overflow-y-auto">
                  @for (ws of workspaceService.workspaces(); track ws.id) {
                    <button
                      type="button"
                      (click)="selectWorkspace(ws.slug)"
                      class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/5 transition"
                    >
                      <div
                        class="w-6 h-6 rounded text-white flex items-center justify-center text-[11px] font-semibold shrink-0 bg-gradient-to-br from-brand-500 to-violet-500"
                      >
                        {{ workspaceInitial(ws.name) }}
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="text-sm text-white truncate">{{ ws.name }}</div>
                        <div class="text-[10px] text-gray-500 capitalize">{{ ws.role }}</div>
                      </div>
                      @if (ws.slug === workspaceService.currentSlug()) {
                        <app-icon name="check" [size]="14" class="text-brand-400" />
                      }
                    </button>
                  }
                </div>
                <div class="border-t border-white/5">
                  @if (!showCreateForm()) {
                    <button
                      type="button"
                      (click)="openCreateForm()"
                      class="w-full flex items-center gap-2 px-3 py-2 text-sm text-brand-400 hover:bg-white/5 transition"
                    >
                      <app-icon name="plus" [size]="14" /> Create workspace
                    </button>
                  } @else {
                    <form (ngSubmit)="createWorkspace()" class="p-2 space-y-2">
                      <input
                        #nameInput
                        [(ngModel)]="newWorkspaceName"
                        name="newWorkspaceName"
                        placeholder="Workspace name"
                        class="w-full px-2 py-1.5 text-sm bg-black/30 border border-white/10 rounded text-white placeholder-gray-500 focus:outline-none focus:border-brand-500/60 focus:ring-1 focus:ring-brand-500/40"
                        autocomplete="off"
                      />
                      <div class="flex gap-1">
                        <button
                          type="submit"
                          [disabled]="!newWorkspaceName.trim() || creating()"
                          class="flex-1 px-2 py-1 text-xs bg-brand-500 hover:bg-brand-600 text-white rounded disabled:opacity-50 transition"
                        >
                          {{ creating() ? 'Creating…' : 'Create' }}
                        </button>
                        <button
                          type="button"
                          (click)="cancelCreate()"
                          class="px-2 py-1 text-xs bg-white/5 hover:bg-white/10 text-gray-200 rounded"
                        >
                          Cancel
                        </button>
                      </div>
                    </form>
                  }
                </div>
              </div>
            }
          </div>
        }

        <!-- Nav -->
        <nav class="flex-1 py-3 overflow-y-auto">
          @for (group of navGroups; track group.title) {
            @if (!collapsed()) {
              <div class="px-4 pt-3 pb-1 text-[9px] uppercase tracking-[0.18em] text-gray-600 font-bold">
                {{ group.title }}
              </div>
            } @else {
              <div class="h-px bg-white/5 mx-3 my-2"></div>
            }
            @for (item of group.items; track item.route) {
              <a
                [routerLink]="item.route"
                routerLinkActive="text-white ring-1 ring-brand-500/30 bg-brand-500/10 shadow-glow-sm"
                class="flex items-center gap-3 px-3 py-2 mx-2 rounded-md hover:bg-white/5 hover:text-white transition text-sm text-gray-400"
                [title]="item.label"
              >
                <app-icon [name]="item.icon" [size]="18" class="shrink-0" />
                @if (!collapsed()) {
                  <span class="truncate">{{ item.label }}</span>
                }
              </a>
            }
          }
        </nav>

        <!-- Bottom controls -->
        <div class="border-t border-white/5 p-2 flex items-center justify-between gap-1">
          <button
            (click)="themeService.toggle()"
            class="p-2 rounded-md text-gray-400 hover:text-white hover:bg-white/5 transition"
            title="Toggle theme"
          >
            <app-icon [name]="themeService.isDark() ? 'sun' : 'moon'" [size]="16" />
          </button>
          <button
            (click)="collapsed.set(!collapsed())"
            class="p-2 rounded-md text-gray-400 hover:text-white hover:bg-white/5 transition"
            title="Toggle sidebar"
          >
            <app-icon name="panel-left" [size]="16" />
          </button>
          <button
            (click)="logout()"
            class="p-2 rounded-md text-gray-400 hover:text-red-400 hover:bg-white/5 transition"
            title="Sign out"
          >
            <app-icon name="log-out" [size]="16" />
          </button>
        </div>
      </aside>

      <!-- Main -->
      <main class="flex-1 flex flex-col overflow-hidden relative z-10">
        <!-- Header -->
        <header
          class="header-underline flex items-center justify-between px-6 py-3 glass border-b border-white/5 shrink-0 z-10 gap-4"
        >
          <!-- Breadcrumbs -->
          <nav aria-label="Breadcrumbs" class="flex items-center gap-1.5 text-xs text-gray-400 min-w-0">
            <a
              routerLink="/"
              class="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-white/5 hover:text-white transition"
              title="Home"
            >
              <app-icon name="layout-dashboard" [size]="14" class="text-brand-400" />
              <span class="font-medium hidden sm:inline">Platform</span>
            </a>
            @for (crumb of breadcrumbs(); track $index; let last = $last) {
              <app-icon name="chevron-right" [size]="12" class="opacity-40 shrink-0" />
              @if (crumb.route && !last) {
                <a
                  [routerLink]="crumb.route"
                  class="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-white/5 hover:text-white transition truncate"
                >
                  <app-icon [name]="crumb.icon" [size]="13" class="text-brand-400 shrink-0" />
                  <span class="truncate">{{ crumb.label }}</span>
                </a>
              } @else {
                <span class="flex items-center gap-1.5 px-2 py-1 text-gray-100 font-medium truncate">
                  <app-icon [name]="crumb.icon" [size]="13" class="text-brand-400 shrink-0" />
                  <span class="truncate">{{ crumb.label }}</span>
                </span>
              }
            }
          </nav>

          <!-- Right cluster -->
          <div class="flex items-center gap-2 shrink-0">
            <button
              type="button"
              class="p-2 rounded-md text-gray-400 hover:text-white hover:bg-white/5 transition"
              title="Notifications (coming soon)"
            >
              <app-icon name="bell" [size]="16" />
            </button>
            <div class="relative" (click)="$event.stopPropagation()">
              <button
                type="button"
                (click)="toggleUserMenu($event)"
                class="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/5 transition"
                [class.bg-white\\/5]="userMenuOpen()"
              >
                <div
                  class="w-8 h-8 rounded-full text-white font-semibold flex items-center justify-center text-sm bg-gradient-to-br from-brand-500 to-violet-500 shadow-glow-sm"
                >
                  {{ initials() }}
                </div>
                @if (authStore.email()) {
                  <span class="text-sm text-gray-200 hidden sm:inline max-w-[180px] truncate">
                    {{ authStore.email() }}
                  </span>
                }
                <app-icon name="chevron-down" [size]="14" class="text-gray-500" />
              </button>

              @if (userMenuOpen()) {
                <div
                  class="absolute right-0 mt-2 w-64 glass border border-white/10 rounded-md shadow-elevated z-50 overflow-hidden animate-fade-in"
                >
                  <div class="px-4 py-3 border-b border-white/5">
                    <div class="text-sm font-medium text-white truncate">
                      {{ authStore.email() || 'User' }}
                    </div>
                    <div class="text-xs text-gray-400 capitalize">
                      {{ authStore.role() || 'user' }}
                    </div>
                  </div>
                  <button
                    type="button"
                    (click)="navigate('/account/profile')"
                    class="w-full text-left flex items-center gap-2.5 px-4 py-2 text-sm text-gray-200 hover:bg-white/5 transition"
                  >
                    <app-icon name="user-round" [size]="15" class="text-gray-400" /> My profile
                  </button>
                  <button
                    type="button"
                    (click)="navigate('/account/security')"
                    class="w-full text-left flex items-center gap-2.5 px-4 py-2 text-sm text-gray-200 hover:bg-white/5 transition"
                  >
                    <app-icon name="shield" [size]="15" class="text-gray-400" /> Security
                  </button>
                  <button
                    type="button"
                    (click)="navigate('/account/sessions')"
                    class="w-full text-left flex items-center gap-2.5 px-4 py-2 text-sm text-gray-200 hover:bg-white/5 transition"
                  >
                    <app-icon name="monitor" [size]="15" class="text-gray-400" /> Sessions
                  </button>
                  @if (workspaceService.current(); as current) {
                    <button
                      type="button"
                      (click)="navigate(['/workspace', current.slug, 'settings'])"
                      class="w-full text-left flex items-center gap-2.5 px-4 py-2 text-sm text-gray-200 hover:bg-white/5 transition border-t border-white/5"
                    >
                      <app-icon name="settings" [size]="15" class="text-gray-400" /> Workspace settings
                    </button>
                  }
                  <button
                    type="button"
                    (click)="logout()"
                    class="w-full text-left flex items-center gap-2.5 px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 border-t border-white/5 transition"
                  >
                    <app-icon name="log-out" [size]="15" /> Sign out
                  </button>
                </div>
              }
            </div>
          </div>
        </header>

        <!-- Content -->
        <div class="flex-1 overflow-auto p-6 md:p-8">
          <router-outlet />
        </div>
      </main>
    </div>
  `,
})
export class ShellComponent {
  protected readonly themeService = inject(ThemeService);
  protected readonly workspaceService = inject(WorkspaceService);
  protected readonly authStore = inject(AuthStore);
  private readonly authBootstrap = inject(AuthBootstrapService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authApi = inject(AuthApiService);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);

  collapsed = signal(false);
  userMenuOpen = signal(false);
  workspaceMenuOpen = signal(false);
  showCreateForm = signal(false);
  newWorkspaceName = '';
  creating = signal(false);

  private readonly currentUrl = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly navGroups: NavGroup[] = [
    {
      title: 'Build',
      items: [
        { label: 'Systems', icon: 'layers', route: '/systems' },
        { label: 'Knowledge', icon: 'database', route: '/knowledge' },
        { label: 'Orchestration', icon: 'workflow', route: '/orchestration' },
        { label: 'Missions', icon: 'list-todo', route: '/tasks' },
      ],
    },
    {
      title: 'Measure',
      items: [
        { label: 'Intelligence', icon: 'newspaper', route: '/intelligence' },
        { label: 'Observability', icon: 'activity', route: '/observability' },
      ],
    },
    {
      title: 'Govern',
      items: [{ label: 'Governance', icon: 'shield-check', route: '/governance' }],
    },
    {
      title: 'Configure',
      items: [
        { label: 'Resources', icon: 'plug', route: '/resources' },
        { label: 'Settings', icon: 'sliders-horizontal', route: '/settings' },
      ],
    },
  ];

  readonly breadcrumbs = computed<Crumb[]>(() => {
    const url = this.currentUrl() || '/';
    const cleanUrl = url.split('?')[0].split('#')[0];
    const segments = cleanUrl.split('/').filter(Boolean);
    if (segments.length === 0) {
      return [{ label: 'Home', icon: 'home' }];
    }

    const first = segments[0];

    // Nav-based areas
    for (const g of this.navGroups) {
      for (const it of g.items) {
        if ('/' + first === it.route) {
          const crumbs: Crumb[] = [{ label: it.label, icon: it.icon, route: it.route }];
          if (segments.length > 1) {
            const secondLabel = this.prettifySegment(segments[1]);
            crumbs.push({ label: secondLabel, icon: 'chevron-right' });
          }
          return crumbs;
        }
      }
    }

    if (first === 'workspace') {
      const current = this.workspaceService.current();
      const crumbs: Crumb[] = [
        { label: current?.name || 'Workspace', icon: 'briefcase', route: current ? ['/workspace', current.slug, 'settings'] : '/systems' },
      ];
      if (segments.length >= 3) {
        const tab = segments[2];
        const tabMap: Record<string, { label: string; icon: string }> = {
          settings: { label: 'Settings', icon: 'settings' },
          members: { label: 'Members', icon: 'users' },
          danger: { label: 'Danger zone', icon: 'shield-alert' },
        };
        const t = tabMap[tab] ?? { label: this.prettifySegment(tab), icon: 'chevron-right' };
        crumbs.push({ label: t.label, icon: t.icon });
      }
      return crumbs;
    }

    if (first === 'account') {
      const crumbs: Crumb[] = [{ label: 'My account', icon: 'user-round', route: '/account/profile' }];
      if (segments.length >= 2) {
        const tabMap: Record<string, { label: string; icon: string }> = {
          profile: { label: 'Profile', icon: 'user-round' },
          password: { label: 'Password', icon: 'key-round' },
          security: { label: 'Security', icon: 'shield' },
          sessions: { label: 'Sessions', icon: 'monitor' },
          danger: { label: 'Danger zone', icon: 'shield-alert' },
        };
        const t = tabMap[segments[1]] ?? { label: this.prettifySegment(segments[1]), icon: 'chevron-right' };
        crumbs.push({ label: t.label, icon: t.icon });
      }
      return crumbs;
    }

    return [{ label: this.prettifySegment(first), icon: 'chevron-right' }];
  });

  private prettifySegment(seg: string): string {
    if (!seg) return '';
    if (seg.length > 24 && /^[0-9a-f-]+$/i.test(seg)) return seg.slice(0, 8) + '…';
    return seg
      .replace(/[-_]/g, ' ')
      .split(' ')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ');
  }

  @HostListener('document:click')
  closeMenus(): void {
    this.userMenuOpen.set(false);
    this.workspaceMenuOpen.set(false);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.userMenuOpen.set(false);
    this.workspaceMenuOpen.set(false);
  }

  toggleUserMenu(ev: Event): void {
    ev.stopPropagation();
    this.workspaceMenuOpen.set(false);
    this.userMenuOpen.update((v) => !v);
  }

  toggleWorkspaceMenu(ev: Event): void {
    ev.stopPropagation();
    this.userMenuOpen.set(false);
    this.workspaceMenuOpen.update((v) => !v);
  }

  navigate(target: string | any[]): void {
    this.userMenuOpen.set(false);
    this.workspaceMenuOpen.set(false);
    if (Array.isArray(target)) this.router.navigate(target);
    else this.router.navigateByUrl(target);
  }

  initials(): string {
    const email = this.authStore.email();
    if (!email) return '?';
    const local = email.split('@')[0];
    const parts = local.split(/[._-]/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return local.slice(0, 2).toUpperCase();
  }

  workspaceInitial(name: string): string {
    const trimmed = (name || '').trim();
    if (!trimmed) return '?';
    const parts = trimmed.split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return trimmed.slice(0, 2).toUpperCase();
  }

  constructor() {
    this.workspaceService.loadWorkspaces().subscribe();
  }

  selectWorkspace(slug: string): void {
    this.workspaceService.switchWorkspace(slug);
    this.workspaceMenuOpen.set(false);
    window.location.reload();
  }

  openCreateForm(): void {
    this.showCreateForm.set(true);
    this.newWorkspaceName = '';
  }

  createWorkspace(): void {
    const name = this.newWorkspaceName.trim();
    if (!name) return;
    this.creating.set(true);
    this.workspaceService.createWorkspace(name).subscribe({
      next: (ws) => {
        this.creating.set(false);
        this.newWorkspaceName = '';
        this.showCreateForm.set(false);
        this.workspaceService.switchWorkspace(ws.slug);
        this.workspaceMenuOpen.set(false);
        this.toastr.success(`"${ws.name}" ready to go`, 'Workspace created');
        this.router.navigate(['/workspace', ws.slug, 'settings']);
      },
      error: (err) => {
        this.creating.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to create workspace', 'Error');
      },
    });
  }

  cancelCreate(): void {
    this.showCreateForm.set(false);
    this.newWorkspaceName = '';
  }

  logout(): void {
    this.userMenuOpen.set(false);
    const refresh = this.tokenStorage.getRefreshToken();
    if (refresh) {
      this.authApi.logout(refresh).subscribe({ complete: () => this.finishLogout() });
    } else {
      this.finishLogout();
    }
  }

  private finishLogout(): void {
    this.tokenStorage.clear();
    this.authStore.clear();
    this.authBootstrap.markInvalid();
    this.router.navigate(['/auth/signin']);
  }
}
