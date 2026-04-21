import { ChangeDetectionStrategy, Component, HostListener, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { AuthApiService } from '@app/core/auth-api.service';
import { AuthBootstrapService } from '@app/core/auth-bootstrap.service';
import { ThemeService } from '@app/core/theme.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { GlyphComponent, LiveDotComponent, StatReadoutComponent } from '@app/shared/cockpit';
import { SemanticZoomBreadcrumbComponent } from './semantic-zoom-breadcrumb.component';

/**
 * Cockpit title bar (48px tall). Hosts the brand mark, the semantic zoom
 * breadcrumb, the live readouts (THRPT/LATENCY/YIELD), the LIVE pulse, the
 * theme toggle and the workspace + user menus.
 */
@Component({
  selector: 'app-title-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    GlyphComponent,
    LiveDotComponent,
    StatReadoutComponent,
    SemanticZoomBreadcrumbComponent,
  ],
  template: `
    <header
      [style.position]="'relative'"
      [style.zIndex]="40"
      [style.height.px]="48"
      [style.display]="'flex'"
      [style.alignItems]="'center'"
      [style.padding]="'0 14px'"
      [style.background]="'var(--ck-bg-base)'"
      [style.borderBottom]="'1px solid var(--ck-stroke-2)'"
      [style.color]="'var(--ck-fg-1)'"
      [style.gap.px]="14"
    >
      <!-- Brand cluster -->
      <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="10" [style.flex]="'0 0 auto'">
        <span [style.color]="'var(--ck-signal-cool)'">
          <ck-glyph name="brand" [size]="22" />
        </span>
        <div [style.display]="'flex'" [style.flexDirection]="'column'" [style.lineHeight]="'1'">
          <span
            [style.fontFamily]="'var(--ck-font-sans)'"
            [style.fontWeight]="600"
            [style.fontSize.px]="14"
            [style.letterSpacing]="'-0.01em'"
            [style.color]="'var(--ck-fg-1)'"
          >Agentium</span>
          <span
            class="ck-mono"
            [style.fontSize.px]="9"
            [style.letterSpacing]="'0.16em'"
            [style.textTransform]="'uppercase'"
            [style.marginTop.px]="2"
            [style.color]="'var(--ck-fg-4)'"
          >OS · v0.4.0</span>
        </div>
      </div>

      <span class="ck-hairline-v" [style.height.px]="22" [style.flex]="'0 0 auto'"></span>

      <!-- Semantic zoom breadcrumb -->
      <div [style.flex]="'1 1 auto'" [style.minWidth]="'0'" [style.overflow]="'hidden'">
        <app-semantic-zoom-breadcrumb />
      </div>

      <!-- Readouts -->
      <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="18" [style.flex]="'0 0 auto'">
        <ck-stat-readout label="THRPT"   [value]="thrpt()"   [tone]="'cool'"   [size]="12" align="end" />
        <ck-stat-readout label="LATENCY" [value]="latency()" [tone]="'pos'"    [size]="12" align="end" />
        <ck-stat-readout label="YIELD"   [value]="outputYield()" [tone]="'violet'" [size]="12" align="end" />
        <ck-live-dot tone="pos" label="Live" />
      </div>

      <span class="ck-hairline-v" [style.height.px]="22" [style.flex]="'0 0 auto'"></span>

      <!-- Theme cycle: light → dark → system → … -->
      <button
        type="button"
        (click)="cycleTheme()"
        [style.background]="'transparent'"
        [style.border]="'1px solid var(--ck-stroke-2)'"
        [style.borderRadius.px]="4"
        [style.height.px]="28"
        [style.width.px]="28"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.justifyContent]="'center'"
        [style.color]="'var(--ck-fg-2)'"
        [style.cursor]="'pointer'"
        [title]="themeTooltip()"
      >
        <ck-glyph [name]="themeGlyph()" [size]="14" />
      </button>

      <!-- Workspace switcher -->
      <div [style.position]="'relative'" (click)="$event.stopPropagation()">
        <button
          type="button"
          (click)="toggleWorkspaceMenu($event)"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="8"
          [style.padding]="'0 10px 0 6px'"
          [style.height.px]="28"
          [style.background]="workspaceMenuOpen() ? 'var(--ck-bg-panel-hi)' : 'transparent'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="4"
          [style.color]="'var(--ck-fg-2)'"
          [style.cursor]="'pointer'"
          [title]="workspaceService.current()?.name || 'Workspace'"
        >
          @if (workspaceService.current(); as ws) {
            <span
              [style.display]="'inline-flex'"
              [style.alignItems]="'center'"
              [style.justifyContent]="'center'"
              [style.width.px]="20"
              [style.height.px]="20"
              [style.borderRadius.px]="3"
              [style.fontSize.px]="10"
              [style.fontWeight]="600"
              [style.color]="'var(--ck-bg-base)'"
              [style.background]="'var(--ck-signal-cool)'"
            >{{ workspaceInitial(ws.name) }}</span>
            <span
              class="ck-mono"
              [style.fontSize.px]="11"
              [style.letterSpacing]="'0.04em'"
              [style.maxWidth.px]="160"
              [style.overflow]="'hidden'"
              [style.textOverflow]="'ellipsis'"
              [style.whiteSpace]="'nowrap'"
              [style.color]="'var(--ck-fg-1)'"
            >{{ ws.name }}</span>
          } @else {
            <span class="ck-mono" [style.fontSize.px]="10" [style.color]="'var(--ck-fg-3)'">No workspace</span>
          }
          <ck-glyph name="arrow-down" [size]="10" color="var(--ck-fg-4)" />
        </button>

        @if (workspaceMenuOpen()) {
          <div
            [style.position]="'absolute'"
            [style.top]="'calc(100% + 6px)'"
            [style.right]="'0'"
            [style.minWidth.px]="280"
            [style.maxHeight.px]="420"
            [style.overflowY]="'auto'"
            [style.background]="'var(--ck-bg-panel-hi)'"
            [style.border]="'1px solid var(--ck-stroke-3)'"
            [style.borderRadius.px]="6"
            [style.boxShadow]="'0 18px 40px rgba(0,0,0,0.45)'"
            [style.zIndex]="60"
            [style.padding]="'6px'"
            class="ck-scroll"
          >
            <div class="ck-label" [style.padding]="'4px 8px 6px'">Workspaces</div>
            @for (ws of workspaceService.workspaces(); track ws.id) {
              <button
                type="button"
                (click)="selectWorkspace(ws.slug)"
                [style.display]="'flex'"
                [style.alignItems]="'center'"
                [style.gap.px]="8"
                [style.width]="'100%'"
                [style.padding]="'6px 8px'"
                [style.background]="ws.slug === workspaceService.currentSlug() ? 'rgba(125,211,252,0.06)' : 'transparent'"
                [style.border]="'1px solid transparent'"
                [style.borderRadius.px]="4"
                [style.color]="'var(--ck-fg-1)'"
                [style.cursor]="'pointer'"
                [style.textAlign]="'left'"
              >
                <span
                  [style.display]="'inline-flex'"
                  [style.alignItems]="'center'"
                  [style.justifyContent]="'center'"
                  [style.width.px]="22"
                  [style.height.px]="22"
                  [style.borderRadius.px]="3"
                  [style.fontSize.px]="10"
                  [style.fontWeight]="600"
                  [style.color]="'var(--ck-bg-base)'"
                  [style.background]="'var(--ck-signal-cool)'"
                >{{ workspaceInitial(ws.name) }}</span>
                <div [style.flex]="'1 1 auto'" [style.minWidth]="'0'">
                  <div [style.fontSize.px]="12" [style.color]="'var(--ck-fg-1)'" [style.overflow]="'hidden'" [style.textOverflow]="'ellipsis'" [style.whiteSpace]="'nowrap'">{{ ws.name }}</div>
                  <div class="ck-mono" [style.fontSize.px]="9" [style.color]="'var(--ck-fg-4)'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.12em'">{{ ws.role }}</div>
                </div>
                @if (ws.slug === workspaceService.currentSlug()) {
                  <ck-glyph name="check" [size]="12" color="var(--ck-signal-cool)" />
                }
              </button>
            }
            <div class="ck-hairline-h" [style.margin]="'6px 4px'"></div>
            @if (!showCreateForm()) {
              <button
                type="button"
                (click)="openCreateForm()"
                [style.display]="'flex'"
                [style.alignItems]="'center'"
                [style.gap.px]="6"
                [style.width]="'100%'"
                [style.padding]="'6px 8px'"
                [style.background]="'transparent'"
                [style.border]="'none'"
                [style.color]="'var(--ck-signal-cool)'"
                [style.fontSize.px]="11"
                [style.cursor]="'pointer'"
                [style.textAlign]="'left'"
              >
                <ck-glyph name="bolt" [size]="12" /> New workspace
              </button>
            } @else {
              <form (ngSubmit)="createWorkspace()" [style.padding]="'6px 4px'" [style.display]="'flex'" [style.gap.px]="6">
                <input
                  [(ngModel)]="newWorkspaceName"
                  name="newWorkspaceName"
                  placeholder="Workspace name"
                  [style.flex]="'1 1 auto'"
                  [style.padding]="'4px 8px'"
                  [style.background]="'var(--ck-bg-inset)'"
                  [style.border]="'1px solid var(--ck-stroke-2)'"
                  [style.borderRadius.px]="3"
                  [style.color]="'var(--ck-fg-1)'"
                  [style.fontSize.px]="11"
                  autocomplete="off"
                />
                <button
                  type="submit"
                  [disabled]="!newWorkspaceName.trim() || creating()"
                  [style.padding]="'4px 10px'"
                  [style.background]="'var(--ck-signal-cool)'"
                  [style.color]="'var(--ck-bg-base)'"
                  [style.border]="'none'"
                  [style.borderRadius.px]="3"
                  [style.fontSize.px]="11"
                  [style.fontWeight]="600"
                  [style.cursor]="'pointer'"
                >{{ creating() ? '…' : 'Create' }}</button>
              </form>
            }
          </div>
        }
      </div>

      <!-- User menu -->
      <div [style.position]="'relative'" (click)="$event.stopPropagation()">
        <button
          type="button"
          (click)="toggleUserMenu($event)"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="6"
          [style.padding]="'2px 8px 2px 2px'"
          [style.height.px]="28"
          [style.background]="userMenuOpen() ? 'var(--ck-bg-panel-hi)' : 'transparent'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="4"
          [style.color]="'var(--ck-fg-2)'"
          [style.cursor]="'pointer'"
        >
          <span
            [style.display]="'inline-flex'"
            [style.alignItems]="'center'"
            [style.justifyContent]="'center'"
            [style.width.px]="22"
            [style.height.px]="22"
            [style.borderRadius]="'50%'"
            [style.fontSize.px]="10"
            [style.fontWeight]="600"
            [style.color]="'var(--ck-bg-base)'"
            [style.background]="'var(--ck-signal-violet)'"
          >{{ initials() }}</span>
          <ck-glyph name="arrow-down" [size]="10" color="var(--ck-fg-4)" />
        </button>

        @if (userMenuOpen()) {
          <div
            [style.position]="'absolute'"
            [style.top]="'calc(100% + 6px)'"
            [style.right]="'0'"
            [style.minWidth.px]="240"
            [style.background]="'var(--ck-bg-panel-hi)'"
            [style.border]="'1px solid var(--ck-stroke-3)'"
            [style.borderRadius.px]="6"
            [style.boxShadow]="'0 18px 40px rgba(0,0,0,0.45)'"
            [style.zIndex]="60"
            [style.padding]="'6px'"
          >
            <div [style.padding]="'6px 8px'">
              <div [style.fontSize.px]="12" [style.color]="'var(--ck-fg-1)'">{{ authStore.email() || 'User' }}</div>
              <div class="ck-mono" [style.fontSize.px]="9" [style.color]="'var(--ck-fg-4)'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.12em'" [style.marginTop.px]="2">{{ authStore.role() || 'user' }}</div>
            </div>
            <div class="ck-hairline-h" [style.margin]="'4px 4px'"></div>
            <button type="button" (click)="navigate('/account/profile')" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-fg-2)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">My profile</button>
            <button type="button" (click)="navigate('/account/security')" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-fg-2)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">Security</button>
            <button type="button" (click)="navigate('/settings')" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-fg-2)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">Preferences</button>
            @if (workspaceService.current(); as cur) {
              <button type="button" (click)="navigate(['/workspace', cur.slug, 'settings'])" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-fg-2)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">Workspace settings</button>
            }
            <div class="ck-hairline-h" [style.margin]="'4px 4px'"></div>
            <button type="button" (click)="logout()" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-signal-neg)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">Sign out</button>
          </div>
        }
      </div>
    </header>
  `,
})
export class TitleBarComponent {
  protected readonly themeService = inject(ThemeService);
  protected readonly workspaceService = inject(WorkspaceService);
  protected readonly authStore = inject(AuthStore);
  private readonly authBootstrap = inject(AuthBootstrapService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authApi = inject(AuthApiService);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);

  userMenuOpen = signal(false);
  workspaceMenuOpen = signal(false);
  showCreateForm = signal(false);
  newWorkspaceName = '';
  creating = signal(false);

  readonly thrpt   = computed(() => '127 r/m');
  readonly latency = computed(() => '342 ms');
  readonly outputYield = computed(() => '94.2%');

  readonly themeGlyph = computed(() => {
    const mode = this.themeService.mode();
    if (mode === 'light') return 'crosshair' as const;
    if (mode === 'dark') return 'pulse' as const;
    return 'orbit' as const;
  });

  readonly themeTooltip = computed(() => {
    const mode = this.themeService.mode();
    if (mode === 'light') return 'Theme: Light  (click → Dark)';
    if (mode === 'dark')  return 'Theme: Dark  (click → System)';
    return 'Theme: System  (click → Light)';
  });

  cycleTheme(): void {
    const m = this.themeService.mode();
    if (m === 'light') this.themeService.setMode('dark');
    else if (m === 'dark') this.themeService.setMode('system');
    else this.themeService.setMode('light');
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
