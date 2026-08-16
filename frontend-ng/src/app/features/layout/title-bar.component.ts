import { ChangeDetectionStrategy, Component, DestroyRef, HostListener, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { Subscription, timer } from 'rxjs';
import { AuthApiService } from '@app/core/auth-api.service';
import { AuthBootstrapService } from '@app/core/auth-bootstrap.service';
import { ApiService } from '@app/core/api.service';
import { ThemeService, type ThemeMode } from '@app/core/theme.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { platformBrand } from '@app/core/platform-brand';
import { I18nService, type Locale } from '@app/core/i18n.service';
import { AuthStore } from '@app/store/auth.store';
import { GlyphComponent, LiveDotComponent, StatReadoutComponent } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SemanticZoomBreadcrumbComponent } from './semantic-zoom-breadcrumb.component';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';

/** Sun, moon and screen: the same three glyphs as every other theme switch. */
const THEME_ICONS: Record<ThemeMode, string> = {
  system: 'monitor',
  light: 'sun',
  dark: 'moon',
};

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
    IconComponent,
    RouterLink,
    SemanticZoomBreadcrumbComponent,
  ],
  template: `
    <header class="tb">
      <!-- Brand cluster. A white-labelled workspace carries its own identity
           here and the emblem returns to its business app; the platform
           navigation and its vocabulary are unchanged either way. -->
      @if (brand(); as tenant) {
        <!-- A tenant emblem is a wordmark: it already says the name, so the copy
             beside it must not repeat it. The label lives in the alt text and
             the browser tab instead. -->
        @if (tenant.home; as home) {
          <a class="tb-brand" [routerLink]="home" [title]="tenant.label">
            <img
              class="tb-emblem-brand"
              [class.tb-emblem-keyed]="emblemIsKeyed()"
              [src]="emblem()"
              [alt]="tenant.label"
            />
            <span class="ck-mono tb-brand-line">OS · v0.4.0</span>
          </a>
        } @else {
          <div class="tb-brand">
            <img
              class="tb-emblem-brand"
              [class.tb-emblem-keyed]="emblemIsKeyed()"
              [src]="emblem()"
              [alt]="tenant.label"
            />
            <span class="ck-mono tb-brand-line">OS · v0.4.0</span>
          </div>
        }
      } @else {
        <div class="tb-brand">
          <img class="tb-emblem" src="/assets/brand/agentium-mark.svg" alt="" width="26" height="26" />
          <span class="tb-brand-copy">
            <span class="tb-brand-name">Agentium</span>
            <span class="ck-mono tb-brand-line">OS · v0.4.0</span>
          </span>
        </div>
      }

      <span class="ck-hairline-v tb-divider tb-divider-brand" [style.height.px]="22" [style.flex]="'0 0 auto'"></span>

      <!-- Semantic zoom breadcrumb -->
      <div class="tb-breadcrumb">
        <app-semantic-zoom-breadcrumb />
      </div>

      <!-- Readouts -->
      <div class="tb-readouts">
        <ck-stat-readout label="THRPT"   [value]="thrpt()"   [tone]="hasTelemetry() ? 'cool' : 'neutral'"   [size]="12" align="end" />
        <ck-stat-readout label="LATENCY" [value]="latency()" [tone]="hasTelemetry() ? 'pos' : 'neutral'"    [size]="12" align="end" />
        <ck-stat-readout label="YIELD"   [value]="outputYield()" [tone]="hasTelemetry() ? 'violet' : 'neutral'" [size]="12" align="end" />
        <ck-live-dot [tone]="hasTelemetry() ? 'pos' : 'neutral'" [label]="hasTelemetry() ? 'Live' : 'Idle'" />
      </div>

      <span class="ck-hairline-v tb-divider tb-divider-telemetry" [style.height.px]="22" [style.flex]="'0 0 auto'"></span>

      <!-- Chat overlay trigger (Vague D / D0) — omnipresent chat entry
           point. Matches ⌘J global shortcut so operators never wonder
           where the playground went: icon stays in view on every route. -->
      <button
        type="button"
        class="tb-icon-action"
        (click)="openChat()"
        [style.background]="chatOverlay.isOpen() ? 'var(--ck-bg-panel-hi)' : 'transparent'"
        [style.border]="'1px solid var(--ck-stroke-2)'"
        [style.borderRadius.px]="4"
        [style.height.px]="28"
        [style.width.px]="28"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.justifyContent]="'center'"
        [style.color]="chatOverlay.isOpen() ? 'var(--ck-signal-cool)' : 'var(--ck-fg-2)'"
        [style.cursor]="'pointer'"
        [title]="i18n.t('titlebar.chat.tooltip')"
        [attr.aria-label]="i18n.t('titlebar.chat')"
      >
        <app-icon name="message-square" [size]="14" />
      </button>

      <!-- Theme switch: cycles system → light → dark. -->
      <button
        type="button"
        class="tb-icon-action"
        data-testid="titlebar-theme-toggle"
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
        [attr.aria-label]="themeTooltip()"
      >
        <app-icon [name]="themeIcon()" [size]="14" />
      </button>

      <!-- Workspace switcher -->
      <div class="tb-menu tb-workspace" (click)="$event.stopPropagation()">
        <button
          id="tb-workspace-toggle"
          type="button"
          class="tb-workspace-toggle"
          data-testid="workspace-switcher-toggle"
          (click)="toggleWorkspaceMenu($event)"
          [attr.aria-label]="i18n.t('titlebar.workspace') + ' · ' + (workspaceService.current()?.name || i18n.t('titlebar.workspace.none'))"
          [attr.aria-expanded]="workspaceMenuOpen()"
          aria-haspopup="dialog"
          aria-controls="tb-workspace-popover"
          (keydown.arrowdown)="openWorkspaceMenu($event)"
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
          [title]="workspaceService.current()?.name || i18n.t('titlebar.workspace')"
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
              [style.color]="'var(--ck-on-signal)'"
              [style.background]="'var(--ck-signal-cool)'"
            >{{ workspaceInitial(ws.name) }}</span>
            <span
              class="ck-mono tb-workspace-name"
              [style.fontSize.px]="11"
              [style.letterSpacing]="'0.04em'"
              [style.maxWidth.px]="160"
              [style.overflow]="'hidden'"
              [style.textOverflow]="'ellipsis'"
              [style.whiteSpace]="'nowrap'"
              [style.color]="'var(--ck-fg-1)'"
            >{{ ws.name }}</span>
          } @else {
            <span class="ck-mono" [style.fontSize.px]="10" [style.color]="'var(--ck-fg-3)'">{{ i18n.t('titlebar.workspace.none') }}</span>
          }
          <ck-glyph class="tb-workspace-arrow" name="arrow-down" [size]="10" color="var(--ck-fg-4)" />
        </button>

        @if (workspaceMenuOpen()) {
          <div
            id="tb-workspace-popover"
            role="dialog"
            [attr.aria-label]="i18n.t('titlebar.workspaces')"
            [style.maxHeight.px]="420"
            [style.overflowY]="'auto'"
            [style.background]="'var(--ck-bg-panel-hi)'"
            [style.border]="'1px solid var(--ck-stroke-3)'"
            [style.borderRadius.px]="6"
            [style.boxShadow]="'var(--ck-shadow-popover)'"
            [style.zIndex]="60"
            [style.padding]="'6px'"
            data-testid="workspace-switcher-popover"
            class="ck-scroll tb-popover"
          >
            <div class="ck-label" [style.padding]="'4px 8px 6px'">{{ i18n.t('titlebar.workspaces') }}</div>
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
                  [style.color]="'var(--ck-on-signal)'"
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
            @if (workspaceService.current(); as cur) {
              <button
                type="button"
                (click)="navigate(['/workspace', cur.slug, 'settings'])"
                [style.display]="'flex'"
                [style.alignItems]="'center'"
                [style.gap.px]="6"
                [style.width]="'100%'"
                [style.padding]="'6px 8px'"
                [style.background]="'transparent'"
                [style.border]="'none'"
                [style.color]="'var(--ck-fg-2)'"
                [style.fontSize.px]="11"
                [style.cursor]="'pointer'"
                [style.textAlign]="'left'"
              >
                <ck-glyph name="sliders" [size]="12" />
                <span class="ck-mono" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">
                  {{ i18n.t('titlebar.workspace.settings') }}
                </span>
              </button>
            }
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
                <ck-glyph name="bolt" [size]="12" /> {{ i18n.t('titlebar.workspace.create') }}
              </button>
            } @else {
              <form (ngSubmit)="createWorkspace()" [style.padding]="'6px 4px'" [style.display]="'flex'" [style.gap.px]="6">
                <input
                  [(ngModel)]="newWorkspaceName"
                  name="newWorkspaceName"
                  [placeholder]="i18n.t('titlebar.workspace.name_placeholder')"
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
                  [style.color]="'var(--ck-on-signal)'"
                  [style.border]="'none'"
                  [style.borderRadius.px]="3"
                  [style.fontSize.px]="11"
                  [style.fontWeight]="600"
                  [style.cursor]="'pointer'"
                >{{ creating() ? '…' : i18n.t('common.create') }}</button>
              </form>
            }
          </div>
        }
      </div>

      <!-- User menu -->
      <div class="tb-menu" (click)="$event.stopPropagation()">
        <button
          id="tb-user-toggle"
          type="button"
          class="tb-user-toggle"
          (click)="toggleUserMenu($event)"
          [attr.aria-label]="i18n.t('titlebar.account') + ' · ' + (authStore.email() || initials())"
          [attr.aria-expanded]="userMenuOpen()"
          aria-haspopup="dialog"
          aria-controls="tb-user-popover"
          (keydown.arrowdown)="openUserMenu($event)"
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
            [style.color]="'var(--ck-on-signal)'"
            [style.background]="'var(--ck-signal-violet)'"
          >{{ initials() }}</span>
          <ck-glyph name="arrow-down" [size]="10" color="var(--ck-fg-4)" />
        </button>

        @if (userMenuOpen()) {
          <div
            id="tb-user-popover"
            role="dialog"
            [attr.aria-label]="i18n.t('titlebar.account')"
            [style.position]="'absolute'"
            [style.top]="'calc(100% + 6px)'"
            [style.right]="'0'"
            [style.minWidth.px]="240"
            [style.background]="'var(--ck-bg-panel-hi)'"
            [style.border]="'1px solid var(--ck-stroke-3)'"
            [style.borderRadius.px]="6"
            [style.boxShadow]="'var(--ck-shadow-popover)'"
            [style.zIndex]="60"
            [style.padding]="'6px'"
          >
            <div [style.padding]="'6px 8px'">
              <div [style.fontSize.px]="12" [style.color]="'var(--ck-fg-1)'">{{ authStore.email() || i18n.t('account.user_fallback') }}</div>
              <div class="ck-mono" [style.fontSize.px]="9" [style.color]="'var(--ck-fg-4)'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.12em'" [style.marginTop.px]="2">{{ authStore.role() || i18n.t('account.role_fallback') }}</div>
            </div>
            <div class="ck-hairline-h" [style.margin]="'4px 4px'"></div>
            <button type="button" (click)="navigate('/account/profile')" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-fg-2)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">{{ i18n.t('account.profile') }}</button>
            <button type="button" (click)="navigate('/account/security')" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-fg-2)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">{{ i18n.t('account.security') }}</button>
            <button type="button" (click)="navigate('/settings')" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-fg-2)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">{{ i18n.t('nav.settings') }}</button>
            <div class="ck-hairline-h" [style.margin]="'4px 4px'"></div>
            <!-- Locale switcher (Vague D / D3). Live swap, no reload. -->
            <div [style.padding]="'6px 8px 4px'">
              <div class="ck-label" [style.marginBottom.px]="4">{{ i18n.t('account.locale') }}</div>
              <div [style.display]="'flex'" [style.gap.px]="4">
                @for (lc of i18n.supported; track lc) {
                  <button
                    type="button"
                    (click)="setLocale(lc)"
                    class="ck-mono"
                    [style.flex]="'1 1 0'"
                    [style.padding]="'4px 6px'"
                    [style.background]="i18n.locale() === lc ? 'var(--ck-signal-cool)' : 'transparent'"
                    [style.color]="i18n.locale() === lc ? 'var(--ck-on-signal)' : 'var(--ck-fg-2)'"
                    [style.border]="'1px solid var(--ck-stroke-2)'"
                    [style.borderRadius.px]="3"
                    [style.fontSize.px]="10"
                    [style.fontWeight]="600"
                    [style.textTransform]="'uppercase'"
                    [style.letterSpacing]="'0.12em'"
                    [style.cursor]="'pointer'"
                  >{{ lc }}</button>
                }
              </div>
            </div>
            <div class="ck-hairline-h" [style.margin]="'4px 4px'"></div>
            <button type="button" (click)="logout()" class="ck-mono" [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8" [style.width]="'100%'" [style.padding]="'6px 8px'" [style.background]="'transparent'" [style.border]="'none'" [style.color]="'var(--ck-signal-neg)'" [style.fontSize.px]="11" [style.textAlign]="'left'" [style.cursor]="'pointer'" [style.textTransform]="'uppercase'" [style.letterSpacing]="'0.10em'">{{ i18n.t('account.signout') }}</button>
          </div>
        }
      </div>
    </header>
  `,
  styles: [`
    .tb {
      position: relative;
      z-index: 40;
      display: flex;
      align-items: center;
      height: 48px;
      padding: 0 14px;
      gap: 14px;
      border-bottom: 1px solid var(--ck-stroke-2);
      background: var(--ck-bg-base);
      color: var(--ck-fg-1);
    }

    .tb-breadcrumb {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
    }

    .tb-readouts {
      display: flex;
      align-items: center;
      gap: 18px;
      flex: 0 0 auto;
    }

    .tb-menu {
      position: relative;
      flex: 0 0 auto;
    }

    .tb :where(a, button):focus-visible {
      outline: 2px solid var(--ck-signal-cool);
      outline-offset: 2px;
    }

    .tb-brand {
      display: flex;
      align-items: center;
      gap: 10px;
      flex: 0 0 auto;
      text-decoration: none;
      color: inherit;
    }
    .tb-emblem {
      display: block;
      border-radius: 6px;
    }
    /* Height-constrained, never squared: a customer wordmark is wide. The radius
       softens the opaque corners of a logo shipped without an alpha channel. */
    .tb-emblem-brand {
      display: block;
      height: 26px;
      width: auto;
      border-radius: 4px;
    }
    /* A tenant that declared a light variant keyed its artwork out; there are no
       opaque corners left to soften, and rounding them would clip the wordmark. */
    .tb-emblem-keyed {
      border-radius: 0;
    }
    .tb-brand-copy {
      display: flex;
      flex-direction: column;
      line-height: 1;
    }
    .tb-brand-name {
      font-family: var(--ck-font-sans);
      font-weight: 600;
      font-size: 14px;
      letter-spacing: -0.01em;
      color: var(--ck-fg-1);
    }
    .tb-brand-line {
      font-size: 9px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      margin-top: 2px;
      color: var(--ck-fg-4);
    }

    .tb-popover {
      position: absolute;
      top: calc(100% + 6px);
      right: 0;
      min-width: 280px;
      max-width: calc(100vw - 16px);
    }

    @media (max-width: 1000px) {
      .tb-readouts,
      .tb-divider-telemetry {
        display: none;
      }
    }

    @media (max-width: 700px) {
      .tb {
        gap: 6px;
        padding-inline: 8px;
      }

      .tb-divider,
      .tb-breadcrumb,
      .tb-workspace-name,
      .tb-workspace-arrow {
        display: none;
      }

      .tb-brand {
        min-width: 0;
        margin-right: auto;
      }

      .tb-emblem-brand {
        max-width: 84px;
        object-fit: contain;
      }

      .tb-workspace-toggle {
        width: 30px;
        padding-inline: 4px !important;
      }

      .tb-popover {
        position: fixed;
        inset: 54px 8px auto;
        width: auto;
        min-width: 0;
        max-width: none;
      }

      .tb-user-toggle {
        padding-right: 2px !important;
      }
    }

    @media (max-width: 380px) {
      .tb-brand-copy .tb-brand-line,
      .tb-brand > .tb-brand-line {
        display: none;
      }

      .tb-emblem-brand {
        max-width: 64px;
      }
    }
  `],
})
export class TitleBarComponent {
  protected readonly themeService = inject(ThemeService);
  protected readonly workspaceService = inject(WorkspaceService);
  /** Tenant identity for this chrome, when the workspace declares one. */
  protected readonly brand = computed(() =>
    platformBrand(this.workspaceService.current()?.settings),
  );
  /**
   * The artwork actually on screen. A tenant may declare a second file for
   * light surfaces; absent it, the single emblem serves both themes. Reading
   * the resolved theme signal makes the swap follow the toggle, no reload.
   */
  private readonly emblemChoice = computed(() => {
    const tenant = this.brand();
    if (!tenant) return { src: null, keyed: false };
    const keyed = this.themeService.resolved() === 'light' && !!tenant.emblemLight;
    return { src: keyed ? tenant.emblemLight : tenant.emblem, keyed };
  });
  protected readonly emblem = computed(() => this.emblemChoice().src);
  /** True only while the declared light variant is the one being shown. */
  protected readonly emblemIsKeyed = computed(() => this.emblemChoice().keyed);
  protected readonly authStore = inject(AuthStore);
  protected readonly chatOverlay = inject(ChatOverlayService);
  protected readonly i18n = inject(I18nService);
  private readonly authBootstrap = inject(AuthBootstrapService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authApi = inject(AuthApiService);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private telemetryRequest: Subscription | null = null;
  private telemetryPolling: Subscription | null = null;
  private unregisterWorkspaceReset: (() => void) | null = null;
  private destroyed = false;

  openChat(): void {
    if (this.chatOverlay.isOpen()) {
      this.chatOverlay.close();
      return;
    }
    // Open the overlay immediately so the panel snaps into view and the
    // chat workspace can render its skeleton; refresh the workspace
    // payload in the background. The previous implementation awaited the
    // workspace HTTP round-trip before flipping ``isOpen``, which added a
    // perceived 300-800ms delay on every AYA panel toggle (bug demo-eve).
    this.chatOverlay.open({ mode: 'quick' });
    this.workspaceService.refreshCurrentWorkspace().subscribe({
      next: () => undefined,
      error: () => undefined,
    });
  }

  userMenuOpen = signal(false);
  workspaceMenuOpen = signal(false);
  showCreateForm = signal(false);
  newWorkspaceName = '';
  creating = signal(false);

  readonly telemetry = signal<{
    throughput_rpm: number | null;
    latency_ms: number | null;
    yield_pct: number | null;
    runs_count?: number;
  } | null>(null);

  readonly hasTelemetry = computed(() => (this.telemetry()?.runs_count ?? 0) > 0);

  readonly thrpt = computed(() => {
    const t = this.telemetry()?.throughput_rpm;
    return t == null ? '— r/m' : `${t.toFixed(t < 10 ? 1 : 0)} r/m`;
  });
  readonly latency = computed(() => {
    const l = this.telemetry()?.latency_ms;
    return l == null ? '— ms' : `${Math.round(l)} ms`;
  });
  readonly outputYield = computed(() => {
    const y = this.telemetry()?.yield_pct;
    return y == null ? '—' : `${y.toFixed(1)}%`;
  });

  constructor() {
    this.unregisterWorkspaceReset = this.workspaceService.registerContextReset((transition) => {
      this.resetTelemetry();
      queueMicrotask(() => {
        if (
          this.destroyed ||
          this.workspaceService.contextEpoch() !== transition.nextEpoch
        ) {
          return;
        }
        this.refreshTelemetry();
      });
    });
    this.telemetryPolling = timer(0, 30_000).subscribe(() => this.refreshTelemetry());
    this.destroyRef.onDestroy(() => {
      this.destroyed = true;
      this.unregisterWorkspaceReset?.();
      this.unregisterWorkspaceReset = null;
      this.telemetryPolling?.unsubscribe();
      this.telemetryPolling = null;
      this.resetTelemetry();
    });
  }

  private refreshTelemetry(): void {
    if (this.destroyed) return;
    this.telemetryRequest?.unsubscribe();
    this.telemetryRequest = null;
    const scope = this.workspaceService.captureRequestScope();
    if (!scope.workspaceSlug) {
      this.telemetry.set(null);
      return;
    }
    const request = this.api
      .get<{
        throughput_rpm: number | null;
        latency_ms: number | null;
        yield_pct: number | null;
        runs_count?: number;
      }>('/telemetry/live', undefined, { workspaceSlug: scope.workspaceSlug })
      .subscribe({
        next: (t) => {
          if (this.workspaceService.isRequestScopeCurrent(scope)) this.telemetry.set(t);
        },
        error: () => {
          if (!this.workspaceService.isRequestScopeCurrent(scope)) return;
          this.telemetry.set({
            throughput_rpm: null,
            latency_ms: null,
            yield_pct: null,
            runs_count: 0,
          });
        },
      });
    this.telemetryRequest = request.closed ? null : request;
  }

  private resetTelemetry(): void {
    this.telemetryRequest?.unsubscribe();
    this.telemetryRequest = null;
    this.telemetry.set(null);
  }

  readonly themeIcon = computed(() => THEME_ICONS[this.themeService.mode()]);

  readonly themeTooltip = computed(() => {
    const mode = this.themeService.mode();
    // Read the i18n locale signal so the tooltip re-renders on flip.
    this.i18n.locale();
    return this.i18n.t(`titlebar.theme.${mode}`);
  });

  cycleTheme(): void {
    this.themeService.cycle();
  }

  setLocale(locale: Locale): void {
    this.i18n.setLocale(locale);
  }

  @HostListener('document:click')
  closeMenus(): void {
    this.userMenuOpen.set(false);
    this.workspaceMenuOpen.set(false);
  }
  @HostListener('document:keydown.escape')
  onEscape(): void {
    const restoreId = this.workspaceMenuOpen()
      ? 'tb-workspace-toggle'
      : this.userMenuOpen()
        ? 'tb-user-toggle'
        : null;
    this.userMenuOpen.set(false);
    this.workspaceMenuOpen.set(false);
    if (restoreId) queueMicrotask(() => document.getElementById(restoreId)?.focus());
  }

  toggleUserMenu(ev: Event): void {
    ev.stopPropagation();
    this.workspaceMenuOpen.set(false);
    const open = !this.userMenuOpen();
    this.userMenuOpen.set(open);
    if (open) this.focusPopover('tb-user-popover');
  }

  toggleWorkspaceMenu(ev: Event): void {
    ev.stopPropagation();
    this.userMenuOpen.set(false);
    const open = !this.workspaceMenuOpen();
    this.workspaceMenuOpen.set(open);
    if (open) this.focusPopover('tb-workspace-popover');
  }

  openUserMenu(ev: Event): void {
    ev.preventDefault();
    if (!this.userMenuOpen()) this.toggleUserMenu(ev);
  }

  openWorkspaceMenu(ev: Event): void {
    ev.preventDefault();
    if (!this.workspaceMenuOpen()) this.toggleWorkspaceMenu(ev);
  }

  private focusPopover(id: string): void {
    queueMicrotask(() => {
      document.getElementById(id)?.querySelector<HTMLElement>('button, input, [tabindex]:not([tabindex="-1"])')?.focus();
    });
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

  async selectWorkspace(slug: string): Promise<void> {
    this.workspaceMenuOpen.set(false);
    await this.activateWorkspace(slug, '/');
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
        this.workspaceMenuOpen.set(false);
        this.toastr.success(
          this.i18n.t('titlebar.workspace.created.body', { name: ws.name }),
          this.i18n.t('titlebar.workspace.created.title'),
        );
        void this.activateWorkspace(ws.slug, `/workspace/${encodeURIComponent(ws.slug)}/settings`);
      },
      error: () => {
        this.creating.set(false);
        this.toastr.error(
          this.i18n.t('titlebar.workspace.create_error.body'),
          this.i18n.t('titlebar.workspace.create_error.title'),
        );
      },
    });
  }

  private async activateWorkspace(slug: string, destination: string): Promise<boolean> {
    if (
      !slug
      || slug === this.workspaceService.currentSlug()
      || !this.workspaceService.workspaces().some((workspace) => workspace.slug === slug)
    ) {
      return false;
    }
    // CanDeactivate runs while the old workspace is still the sole active
    // context. Only a successful exit may publish the next tenant.
    const leftCurrentWorkspace = await this.router.navigateByUrl('/hypervisor', { replaceUrl: true });
    if (!leftCurrentWorkspace || !this.workspaceService.switchWorkspace(slug)) return false;
    return this.router.navigateByUrl(destination, { replaceUrl: true });
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
