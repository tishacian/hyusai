import { Component, HostListener, inject, signal } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive, Router } from '@angular/router';
import { AuthApiService } from '@app/core/auth-api.service';
import { ThemeService } from '@app/core/theme.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';

interface NavItem {
  label: string;
  icon: string;
  route: string;
}

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="flex h-screen overflow-hidden">
      <!-- Sidebar -->
      <aside
        class="flex flex-col bg-gray-900 text-gray-300 transition-all duration-200"
        [class.w-64]="!collapsed()"
        [class.w-16]="collapsed()"
      >
        <!-- Logo -->
        <div class="flex items-center gap-2 px-4 py-5 border-b border-gray-800">
          <div class="w-8 h-8 bg-brand-500 rounded-lg flex items-center justify-center text-white font-bold text-sm shrink-0">A</div>
          @if (!collapsed()) {
            <span class="text-white font-semibold tracking-tight">Agentium</span>
          }
        </div>

        <!-- Nav -->
        <nav class="flex-1 py-4 space-y-1 overflow-y-auto">
          @for (item of navItems; track item.route) {
            <a
              [routerLink]="item.route"
              routerLinkActive="bg-brand-500/20 text-white"
              class="flex items-center gap-3 px-4 py-2 mx-2 rounded-lg hover:bg-white/5 transition text-sm"
              [title]="item.label"
            >
              <span class="text-lg shrink-0">{{ item.icon }}</span>
              @if (!collapsed()) {
                <span>{{ item.label }}</span>
              }
            </a>
          }
        </nav>

        <!-- Workspace picker -->
        @if (!collapsed() && workspaceService.current()) {
          <div class="px-4 py-3 border-t border-gray-800">
            <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Workspace</div>
            <div class="text-sm text-white truncate">{{ workspaceService.current()!.name }}</div>
          </div>
        }

        <!-- Bottom controls -->
        <div class="border-t border-gray-800 p-3 flex items-center justify-between">
          <button (click)="themeService.toggle()" class="p-1.5 rounded hover:bg-white/10 transition" title="Toggle theme">
            {{ themeService.isDark() ? '☀️' : '🌙' }}
          </button>
          <button (click)="collapsed.set(!collapsed())" class="p-1.5 rounded hover:bg-white/10 transition text-xs" title="Toggle sidebar">
            {{ collapsed() ? '→' : '←' }}
          </button>
          <button (click)="logout()" class="p-1.5 rounded hover:bg-white/10 transition" title="Logout">
            🚪
          </button>
        </div>
      </aside>

      <!-- Main -->
      <main class="flex-1 flex flex-col overflow-hidden bg-gray-50 dark:bg-gray-950">
        <!-- Header -->
        <header class="flex items-center justify-between px-6 py-3 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 shrink-0">
          <h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">Agentium</h2>
          <div class="flex items-center gap-3">
            <div class="relative" (click)="$event.stopPropagation()">
              <button
                type="button"
                (click)="userMenuOpen.set(!userMenuOpen())"
                class="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition"
              >
                <div class="w-8 h-8 rounded-full bg-brand-500 text-white font-semibold flex items-center justify-center text-sm">
                  {{ initials() }}
                </div>
                @if (authStore.email()) {
                  <span class="text-sm text-gray-700 dark:text-gray-200 hidden sm:inline">{{ authStore.email() }}</span>
                }
                <span class="text-xs text-gray-400">▾</span>
              </button>

              @if (userMenuOpen()) {
                <div
                  class="absolute right-0 mt-2 w-56 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 overflow-hidden"
                >
                  <div class="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
                    <div class="text-sm font-medium text-gray-900 dark:text-white truncate">{{ authStore.email() || 'User' }}</div>
                    <div class="text-xs text-gray-500 dark:text-gray-400 capitalize">{{ authStore.role() || 'user' }}</div>
                  </div>
                  <a
                    routerLink="/account"
                    (click)="userMenuOpen.set(false)"
                    class="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                  >
                    <span>👤</span> My account
                  </a>
                  <a
                    routerLink="/workspace/settings"
                    (click)="userMenuOpen.set(false)"
                    class="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                  >
                    <span>⚙️</span> Workspace settings
                  </a>
                  <button
                    type="button"
                    (click)="logout()"
                    class="w-full text-left flex items-center gap-2 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 border-t border-gray-100 dark:border-gray-700"
                  >
                    <span>🚪</span> Sign out
                  </button>
                </div>
              }
            </div>
          </div>
        </header>

        <!-- Content -->
        <div class="flex-1 overflow-auto p-6">
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
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authApi = inject(AuthApiService);
  private readonly router = inject(Router);

  collapsed = signal(false);
  userMenuOpen = signal(false);

  @HostListener('document:click')
  closeUserMenu(): void {
    this.userMenuOpen.set(false);
  }

  initials(): string {
    const email = this.authStore.email();
    if (!email) return '?';
    const local = email.split('@')[0];
    const parts = local.split(/[._-]/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return local.slice(0, 2).toUpperCase();
  }

  navItems: NavItem[] = [
    { label: 'Systems', icon: '🤖', route: '/systems' },
    { label: 'Knowledge', icon: '📚', route: '/knowledge' },
    { label: 'Orchestration', icon: '🔀', route: '/orchestration' },
    { label: 'Intelligence', icon: '📡', route: '/intelligence' },
    { label: 'Observability', icon: '📊', route: '/observability' },
    { label: 'Governance', icon: '🛡️', route: '/governance' },
    { label: 'Workspace', icon: '⚙️', route: '/workspace' },
  ];

  constructor() {
    this.workspaceService.loadWorkspaces();
  }

  logout(): void {
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
    this.router.navigate(['/auth/signin']);
  }
}
