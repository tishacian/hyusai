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
import { WorkspaceSwitchService, type WorkspaceSwitchState } from '@app/core/workspace-switch.service';
import {
  COCKPIT_VERBS,
  cockpitVerbSections,
  matchAgentiumSurface,
  navigationLeafUrl,
  navigationRouteContext,
  navigationSectionNaming,
  navigationSurfaceUrl,
} from '@app/core/navigation.catalog';
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
 * Cockpit title bar (48px). Brand mark « A » in the 56px rail column, workspace
 * selector in the 208px sommaire column, then breadcrumb and right-side actions.
 * Tenant emblems stay off this chrome (ADR lot 2). Theme lives in the account menu.
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
      <div class="tb-brand" [attr.aria-label]="'Agentium'">
        <span class="tb-mark" aria-hidden="true">A</span>
      </div>

      <div class="tb-workspace-cell">
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
          >
            @if (workspaceService.current(); as ws) {
              <span class="tb-ws-emblem">{{ workspaceInitial(ws.name) }}</span>
              <span class="ck-mono tb-workspace-name">{{ ws.name }}</span>
            } @else {
              <span class="ck-mono tb-workspace-empty">{{ i18n.t('titlebar.workspace.none') }}</span>
            }
            <ck-glyph class="tb-workspace-arrow" name="arrow-down" [size]="10" color="var(--ck-fg-4)" />
          </button>

          @if (!workspaceMenuOpen() && switchNotice(); as notice) {
            <div class="tb-popover tb-ws-notice" role="status" data-testid="workspace-switch-notice">
              <p class="tb-ws-notice-title">{{ i18n.t('workspace.switch.done', { name: notice.name }) }}</p>
              <p class="tb-ws-notice-line">{{ notice.location }}</p>
              @if (notice.previous; as previous) {
                <button type="button" class="tb-ws-back" (click)="switchBack(previous.slug)">
                  {{ i18n.t('workspace.switch.back', { name: previous.name }) }}
                </button>
              }
            </div>
          }

          @if (workspaceMenuOpen()) {
            <div
              id="tb-workspace-popover"
              role="dialog"
              class="ck-scroll tb-popover"
              [attr.aria-label]="i18n.t('titlebar.workspaces')"
              data-testid="workspace-switcher-popover"
            >
              <div class="ck-label tb-popover-label">{{ i18n.t('titlebar.workspaces') }}</div>
              @for (ws of workspaceService.workspaces(); track ws.id) {
                <div class="tb-ws-item" [class.tb-ws-item-suspended]="!!suspendedFor(ws.slug)">
                  <button
                    type="button"
                    class="tb-ws-row"
                    (click)="selectWorkspace(ws.slug)"
                    [class.tb-ws-pending]="pendingFor(ws.slug)"
                    [class.tb-ws-current]="ws.slug === workspaceService.currentSlug()"
                    [attr.aria-busy]="pendingFor(ws.slug) ? 'true' : null"
                  >
                    <span class="tb-ws-emblem tb-ws-emblem-lg">{{ workspaceInitial(ws.name) }}</span>
                    <div class="tb-ws-meta">
                      <div class="tb-ws-meta-name">{{ ws.name }}</div>
                      <div class="ck-mono tb-ws-meta-role">{{ ws.role }}</div>
                    </div>
                    @if (pendingFor(ws.slug)) {
                      <span class="tb-ws-status"><app-icon name="loader-2" [size]="12" />{{ i18n.t('workspace.switch.opening') }}</span>
                    } @else if (suspendedFor(ws.slug)) {
                      <span class="tb-ws-status tb-ws-status-warn">{{ i18n.t('workspace.switch.suspended') }}</span>
                    } @else if (ws.slug === workspaceService.currentSlug()) {
                      <ck-glyph name="check" [size]="12" color="var(--ck-signal-cool)" />
                    }
                  </button>
                  @if (suspendedFor(ws.slug); as suspended) {
                    <p class="tb-ws-note" role="alert">{{ unsavedReason(suspended) }}</p>
                    <div class="tb-ws-actions">
                      <button type="button" class="tb-ws-action" (click)="stayHere()">{{ i18n.t('workspace.switch.stay') }}</button>
                      <button type="button" class="tb-ws-action tb-ws-action-discard" (click)="discardAndSwitch()">{{ i18n.t('workspace.switch.discard') }}</button>
                    </div>
                  } @else if (failedFor(ws.slug)) {
                    <p class="tb-ws-note" role="alert">{{ i18n.t('workspace.switch.failed') }}</p>
                  }
                </div>
              }
              <div class="ck-hairline-h tb-popover-rule"></div>
              @if (workspaceService.current(); as cur) {
                <button type="button" class="tb-popover-action" (click)="navigate(['/workspace', cur.slug, 'settings'])">
                  <ck-glyph name="sliders" [size]="12" />
                  <span class="ck-mono">{{ i18n.t('titlebar.workspace.settings') }}</span>
                </button>
              }
              @if (!showCreateForm()) {
                <button type="button" class="tb-popover-action tb-popover-action-accent" (click)="openCreateForm()">
                  <ck-glyph name="bolt" [size]="12" /> {{ i18n.t('titlebar.workspace.create') }}
                </button>
              } @else {
                <form class="tb-create-form" (ngSubmit)="createWorkspace()">
                  <input
                    [(ngModel)]="newWorkspaceName"
                    name="newWorkspaceName"
                    [placeholder]="i18n.t('titlebar.workspace.name_placeholder')"
                    autocomplete="off"
                  />
                  <button type="submit" [disabled]="!newWorkspaceName.trim() || creating()">
                    {{ creating() ? '…' : i18n.t('common.create') }}
                  </button>
                </form>
              }
            </div>
          }
        </div>

        @if (builderChip(); as chip) {
          <span
            class="tb-builder-chip"
            data-testid="titlebar-builder-chip"
            [title]="chip.tooltip"
            [attr.aria-label]="chip.label"
          >{{ chip.label }}</span>
        }
      </div>

      <div class="tb-breadcrumb">
        <app-semantic-zoom-breadcrumb />
      </div>

      <div class="tb-actions">
        @if (showWorkLink()) {
          <a
            class="ck-mono tb-work-link"
            [routerLink]="workHref"
            data-testid="titlebar-work-link"
          >{{ i18n.t('nav.work') }}</a>
        }

        <details class="tb-telemetry" data-testid="titlebar-diagnostics">
          <summary
            class="tb-telemetry-summary"
            [attr.aria-label]="i18n.t('titlebar.telemetry.details')"
          >
            <span class="ck-mono tb-telemetry-compact">{{ thrpt() }} {{ latency() }}</span>
            <ck-glyph name="arrow-down" [size]="10" color="var(--ck-fg-4)" />
          </summary>
          <div class="tb-telemetry-panel">
            <p class="ck-mono tb-telemetry-title">{{ i18n.t('titlebar.telemetry.panel_title') }}</p>
            <div class="tb-readouts">
              <ck-stat-readout [label]="i18n.t('titlebar.telemetry.throughput')" [value]="thrpt()" [tone]="hasTelemetry() ? 'cool' : 'neutral'" [size]="12" align="end" />
              <ck-stat-readout [label]="i18n.t('titlebar.telemetry.latency')" [value]="latency()" [tone]="hasTelemetry() ? 'pos' : 'neutral'" [size]="12" align="end" />
              <ck-stat-readout [label]="i18n.t('titlebar.telemetry.completed')" [value]="outputYield()" [tone]="hasTelemetry() ? 'cool' : 'neutral'" [size]="12" align="end" />
              <ck-live-dot [tone]="hasTelemetry() ? 'pos' : 'neutral'" [label]="hasTelemetry() ? 'Live' : 'Idle'" />
            </div>
            <p class="tb-telemetry-note">{{ i18n.t('titlebar.telemetry.note') }}</p>
            <a
              class="tb-telemetry-link"
              routerLink="/observability"
              [queryParams]="{ facet: 'traces' }"
              data-testid="titlebar-telemetry-traces"
              (click)="closeMenus()"
            >{{ i18n.t('titlebar.telemetry.open_traces') }}</a>
          </div>
        </details>

        <button
          type="button"
          class="tb-icon-action"
          data-testid="titlebar-help"
          [title]="i18n.t('titlebar.help')"
          [attr.aria-label]="i18n.t('titlebar.help')"
        >?</button>

        <button
          type="button"
          class="tb-chat-action"
          (click)="openChat()"
          [class.tb-chat-open]="chatOverlay.isOpen()"
          [title]="i18n.t('titlebar.chat.tooltip')"
          [attr.aria-label]="i18n.t('titlebar.chat')"
        >
          <app-icon name="message-square" [size]="14" />
          <span>{{ i18n.t('titlebar.chat') }} ⌘J</span>
        </button>

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
          >
            <span class="tb-avatar">{{ initials() }}</span>
            <ck-glyph name="arrow-down" [size]="10" color="var(--ck-fg-4)" />
          </button>

          @if (userMenuOpen()) {
            <div
              id="tb-user-popover"
              role="dialog"
              class="tb-popover tb-user-popover"
              [attr.aria-label]="i18n.t('titlebar.account')"
            >
              <div class="tb-user-head">
                <div class="tb-user-email">{{ authStore.email() || i18n.t('account.user_fallback') }}</div>
                <div class="ck-mono tb-user-role">{{ authStore.role() || i18n.t('account.role_fallback') }}</div>
              </div>
              <div class="ck-hairline-h tb-popover-rule"></div>
              <button type="button" class="ck-mono tb-account-item" (click)="navigate('/account/profile')">{{ i18n.t('account.profile') }}</button>
              <button type="button" class="ck-mono tb-account-item" (click)="navigate('/account/security')">{{ i18n.t('account.security') }}</button>
              <div class="ck-hairline-h tb-popover-rule"></div>
              <div class="tb-pref-block">
                <div class="ck-label">{{ i18n.t('account.locale') }}</div>
                <div class="tb-pref-row">
                  @for (lc of i18n.supported; track lc) {
                    <button
                      type="button"
                      class="ck-mono tb-pref-btn"
                      (click)="setLocale(lc)"
                      [class.tb-pref-active]="i18n.locale() === lc"
                    >{{ lc }}</button>
                  }
                </div>
              </div>
              <div class="tb-pref-block">
                <div class="ck-label">{{ i18n.t('account.theme') }}</div>
                <button
                  type="button"
                  class="tb-theme-btn"
                  data-testid="titlebar-theme-toggle"
                  (click)="cycleTheme()"
                  [title]="themeTooltip()"
                  [attr.aria-label]="themeTooltip()"
                >
                  <app-icon [name]="themeIcon()" [size]="14" />
                  <span>{{ themeTooltip() }}</span>
                </button>
              </div>
              <div class="ck-hairline-h tb-popover-rule"></div>
              <button type="button" class="ck-mono tb-account-item tb-account-signout" (click)="logout()">{{ i18n.t('account.signout') }}</button>
            </div>
          }
        </div>
      </div>
    </header>
  `,
  styles: [`
    :host {
      display: block;
      min-width: 0;
      max-width: 100%;
    }

    .tb {
      position: relative;
      z-index: 40;
      display: flex;
      align-items: center;
      height: 48px;
      padding: 0;
      gap: 0;
      min-width: 0;
      max-width: 100%;
      border-bottom: 1px solid var(--ck-stroke-2);
      background: var(--ck-bg-base);
      color: var(--ck-fg-1);
    }

    .tb :where(a, button, summary):focus-visible {
      outline: 2px solid var(--ck-primary);
      outline-offset: 2px;
    }

    .tb-brand {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 56px;
      min-width: 56px;
      flex: 0 0 56px;
      height: 100%;
      border-right: 1px solid var(--ck-stroke-2);
    }
    .tb-mark {
      font-family: var(--ck-font-sans);
      font-weight: 700;
      font-size: 18px;
      letter-spacing: -0.02em;
      color: var(--ck-primary);
      line-height: 1;
    }

    .tb-workspace-cell {
      position: relative;
      display: flex;
      align-items: center;
      gap: 8px;
      width: 208px;
      min-width: 208px;
      flex: 0 0 208px;
      height: 100%;
      padding: 0 10px;
      border-right: 1px solid var(--ck-stroke-2);
      box-sizing: border-box;
    }

    .tb-workspace {
      flex: 1 1 auto;
      min-width: 0;
    }
    .tb-workspace-toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      height: 28px;
      padding: 0 8px 0 4px;
      background: transparent;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 4px;
      color: var(--ck-fg-2);
      cursor: pointer;
    }
    .tb-workspace-toggle[aria-expanded='true'] {
      background: var(--ck-bg-panel-hi);
    }
    .tb-ws-emblem {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      flex: 0 0 20px;
      border-radius: 3px;
      font-size: 10px;
      font-weight: 600;
      color: var(--ck-fg-1);
      background: var(--ck-bg-panel);
      border: 1px solid var(--ck-stroke-2);
    }
    .tb-ws-emblem-lg {
      width: 22px;
      height: 22px;
      flex-basis: 22px;
    }
    .tb-workspace-name {
      flex: 1 1 auto;
      min-width: 0;
      font-size: 11px;
      letter-spacing: 0.04em;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--ck-fg-1);
      text-align: left;
    }
    .tb-workspace-empty {
      font-size: 10px;
      color: var(--ck-fg-3);
    }

    .tb-builder-chip {
      flex: 0 0 auto;
      max-width: 100%;
      padding: 3px 6px;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 3px;
      background: var(--ck-bg-panel);
      color: var(--ck-fg-2);
      font-family: var(--ck-font-mono);
      font-size: 9px;
      letter-spacing: 0.04em;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      cursor: default;
    }

    .tb-breadcrumb {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      padding: 0 12px;
    }

    .tb-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
      padding-right: 12px;
    }

    .tb-work-link {
      color: var(--ck-fg-2);
      font-size: 10px;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      text-decoration: none;
      white-space: nowrap;
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

    .tb-popover {
      position: absolute;
      top: calc(100% + 6px);
      left: 0;
      min-width: 280px;
      max-width: calc(100vw - 16px);
      max-height: 420px;
      overflow-y: auto;
      padding: 6px;
      background: var(--ck-bg-panel-hi);
      border: 1px solid var(--ck-stroke-3);
      border-radius: 6px;
      box-shadow: var(--ck-shadow-popover);
      z-index: 60;
    }
    .tb-user-popover {
      left: auto;
      right: 0;
      min-width: 240px;
    }
    .tb-popover-label { padding: 4px 8px 6px; }
    .tb-popover-rule { margin: 6px 4px; }
    .tb-popover-action {
      display: flex;
      align-items: center;
      gap: 6px;
      width: 100%;
      padding: 6px 8px;
      background: transparent;
      border: none;
      color: var(--ck-fg-2);
      font-size: 11px;
      cursor: pointer;
      text-align: left;
    }
    .tb-popover-action .ck-mono {
      text-transform: uppercase;
      letter-spacing: 0.10em;
    }
    .tb-popover-action-accent { color: var(--ck-signal-cool); }

    .tb-ws-row {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      padding: 6px 8px;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 4px;
      color: var(--ck-fg-1);
      cursor: pointer;
      text-align: left;
    }
    .tb-ws-current { background: color-mix(in srgb, var(--ck-signal-cool) 8%, transparent); }
    .tb-ws-meta { flex: 1 1 auto; min-width: 0; }
    .tb-ws-meta-name {
      font-size: 12px;
      color: var(--ck-fg-1);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tb-ws-meta-role {
      font-size: 9px;
      color: var(--ck-fg-4);
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }

    .tb-ws-item-suspended {
      margin: 2px 0;
      padding-bottom: 8px;
      border: 1px solid var(--ck-stroke-3);
      border-radius: 6px;
      background: var(--ck-bg-panel);
    }
    .tb-ws-pending { box-shadow: inset 2px 0 0 var(--ck-signal-cool); }
    .tb-ws-status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      flex: 0 0 auto;
      font-size: 11px;
      color: var(--ck-fg-3);
    }
    .tb-ws-status-warn { color: var(--ck-signal-warn); }
    .tb-ws-note {
      margin: 2px 8px 0;
      font-size: 12px;
      line-height: 16px;
      color: var(--ck-fg-2);
    }
    .tb-ws-actions {
      display: flex;
      gap: 6px;
      margin: 8px 8px 0;
    }
    .tb-ws-action {
      flex: 1 1 auto;
      height: 28px;
      padding: 0 10px;
      border: 1px solid var(--ck-stroke-3);
      border-radius: 4px;
      background: transparent;
      color: var(--ck-fg-1);
      font-size: 12px;
      cursor: pointer;
    }
    .tb-ws-action-discard {
      border-color: var(--ck-signal-neg);
      color: var(--ck-signal-neg);
    }
    .tb-ws-notice {
      z-index: 60;
      padding: 12px 14px;
      border: 1px solid var(--ck-stroke-3);
      border-radius: 6px;
      background: var(--ck-bg-panel-hi);
      box-shadow: var(--ck-shadow-popover);
    }
    .tb-ws-notice-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--ck-fg-1);
    }
    .tb-ws-notice-line {
      margin-top: 4px;
      font-size: 12px;
      color: var(--ck-fg-3);
    }
    .tb-ws-back {
      margin-top: 8px;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--ck-signal-cool);
      font-size: 12px;
      cursor: pointer;
    }

    .tb-create-form {
      display: flex;
      gap: 6px;
      padding: 6px 4px;
    }
    .tb-create-form input {
      flex: 1 1 auto;
      padding: 4px 8px;
      background: var(--ck-bg-inset);
      border: 1px solid var(--ck-stroke-2);
      border-radius: 3px;
      color: var(--ck-fg-1);
      font-size: 11px;
    }
    .tb-create-form button {
      padding: 4px 10px;
      background: var(--ck-signal-cool);
      color: var(--ck-on-signal);
      border: none;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
    }
    .tb-create-form button:disabled { opacity: 0.5; cursor: default; }

    .tb-telemetry { position: relative; flex: 0 0 auto; font-size: 12px; }
    .tb-telemetry-summary {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      border: 1px solid var(--ck-stroke-2);
      padding: 5px 8px;
      border-radius: 4px;
      list-style: none;
      color: var(--ck-fg-2);
    }
    .tb-telemetry-summary::-webkit-details-marker { display: none; }
    .tb-telemetry-compact {
      font-size: 11px;
      letter-spacing: 0.04em;
      color: var(--ck-fg-1);
      white-space: nowrap;
    }
    .tb-telemetry-panel {
      position: absolute;
      right: 0;
      top: calc(100% + 8px);
      z-index: 50;
      width: max-content;
      max-width: calc(100vw - 16px);
      padding: 16px;
      background: var(--ck-bg-panel);
      border: 1px solid var(--ck-stroke-2);
      border-radius: 6px;
      box-shadow: var(--ck-shadow-popover);
    }
    .tb-telemetry-title {
      margin: 0 0 12px;
      font-size: 10px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--ck-fg-3);
    }
    .tb-telemetry .tb-readouts { display: flex; flex-wrap: wrap; }
    .tb-telemetry-note {
      margin: 12px 0 0;
      max-width: 34ch;
      color: var(--ck-fg-3);
      font-size: 12px;
    }
    .tb-telemetry-link {
      display: inline-block;
      margin-top: 12px;
      color: var(--ck-signal-cool);
      font-size: 12px;
      text-decoration: none;
    }

    .tb-icon-action,
    .tb-chat-action,
    .tb-user-toggle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      height: 28px;
      background: transparent;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 4px;
      color: var(--ck-fg-2);
      cursor: pointer;
    }
    .tb-icon-action {
      width: 28px;
      font-family: var(--ck-font-mono);
      font-size: 13px;
      font-weight: 600;
    }
    .tb-chat-action {
      gap: 6px;
      padding: 0 10px;
      font-size: 12px;
      white-space: nowrap;
    }
    .tb-chat-open {
      background: var(--ck-bg-panel-hi);
      color: var(--ck-signal-cool);
    }
    .tb-user-toggle {
      gap: 6px;
      padding: 2px 8px 2px 2px;
    }
    .tb-user-toggle[aria-expanded='true'] { background: var(--ck-bg-panel-hi); }
    .tb-avatar {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      border-radius: 3px;
      font-size: 10px;
      font-weight: 600;
      color: var(--ck-fg-1);
      background: var(--ck-bg-panel);
      border: 1px solid var(--ck-stroke-2);
    }

    .tb-user-head { padding: 6px 8px; }
    .tb-user-email { font-size: 12px; color: var(--ck-fg-1); }
    .tb-user-role {
      margin-top: 2px;
      font-size: 9px;
      color: var(--ck-fg-4);
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }
    .tb-account-item {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      padding: 6px 8px;
      background: transparent;
      border: none;
      color: var(--ck-fg-2);
      font-size: 11px;
      text-align: left;
      cursor: pointer;
      text-transform: uppercase;
      letter-spacing: 0.10em;
    }
    .tb-account-signout { color: var(--ck-signal-neg); }
    .tb-pref-block { padding: 6px 8px 4px; }
    .tb-pref-block .ck-label { margin-bottom: 4px; }
    .tb-pref-row { display: flex; gap: 4px; }
    .tb-pref-btn {
      flex: 1 1 0;
      padding: 4px 6px;
      background: transparent;
      color: var(--ck-fg-2);
      border: 1px solid var(--ck-stroke-2);
      border-radius: 3px;
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      cursor: pointer;
    }
    .tb-pref-active {
      background: var(--ck-signal-cool);
      color: var(--ck-on-signal);
    }
    .tb-theme-btn {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      padding: 6px 8px;
      background: transparent;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 3px;
      color: var(--ck-fg-2);
      font-size: 11px;
      text-align: left;
      cursor: pointer;
    }

    @media (max-width: 1100px) {
      .tb-builder-chip { display: none; }
    }

    @media (max-width: 1000px) {
      .tb-telemetry { display: none; }
    }

    @media (max-width: 700px) {
      .tb-workspace-cell {
        width: auto;
        min-width: 0;
        flex: 0 0 auto;
        padding-inline: 6px;
      }
      .tb-breadcrumb,
      .tb-workspace-name,
      .tb-workspace-arrow,
      .tb-work-link {
        display: none;
      }
      .tb-workspace-toggle {
        width: 30px;
        padding-inline: 4px;
      }
      .tb-popover {
        position: fixed;
        inset: 54px 8px auto;
        width: auto;
        min-width: 0;
        max-width: none;
        left: 8px;
        right: 8px;
      }
      .tb-chat-action > span { display: none; }
      .tb-chat-action { width: 28px; padding: 0; }
      .tb-user-toggle { padding-right: 2px; }
      .tb-actions { padding-right: 8px; gap: 6px; }
    }
  `],
})
export class TitleBarComponent {
  protected readonly themeService = inject(ThemeService);
  protected readonly workspaceService = inject(WorkspaceService);
  protected readonly authStore = inject(AuthStore);
  protected readonly chatOverlay = inject(ChatOverlayService);
  protected readonly i18n = inject(I18nService);
  private readonly switcher = inject(WorkspaceSwitchService);
  /** « Vous êtes dans B — Zone › Surface · Revenir à A », once B is on screen. */
  protected readonly switchNotice = computed(() => {
    const state = this.switcher.state();
    if (state.phase !== 'switched') return null;
    const workspaces = this.workspaceService.workspaces();
    const previous = workspaces.find((workspace) => workspace.slug === state.previousSlug);
    return {
      name: workspaces.find((workspace) => workspace.slug === state.slug)?.name ?? state.slug,
      location: this.locationLabel(state.url),
      previous: previous ? { slug: previous.slug, name: previous.name } : null,
    };
  });
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

  readonly showWorkLink = computed(() => this.workspaceService.experienceV1Enabled());
  readonly workHref = navigationSurfaceUrl('work');

  /** Zones the builder mode hides from the rail (Impact + Améliorer today). */
  readonly builderHiddenZones = computed(() => {
    if (!this.workspaceService.isBuilderMode()) return [];
    return COCKPIT_VERBS.filter((verb) => verb.hiddenInModes?.includes('builder'));
  });

  readonly builderChip = computed(() => {
    const zones = this.builderHiddenZones();
    if (!zones.length) return null;
    this.i18n.locale();
    const names = zones.map((verb) => this.i18n.t(`experience.adoption.nav.${verb.key}`));
    return {
      label: this.i18n.t('titlebar.builder.chip', { count: zones.length }),
      tooltip: this.i18n.t('titlebar.builder.chip_tooltip', { zones: names.join(' · ') }),
    };
  });

  /** Account menu source: no /settings entry (workspace settings live under Administrer). */
  readonly accountMenuItems = ['profile', 'security', 'locale', 'theme', 'signout'] as const;

  readonly thrpt = computed(() => {
    const t = this.telemetry()?.throughput_rpm;
    return t == null ? '— /min' : `${t.toFixed(t < 10 ? 1 : 0)}/min`;
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
    this.closeWorkspaceMenu();
  }
  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.switcher.cancel()) {
      this.workspaceMenuOpen.set(false);
      this.focusWorkspaceToggle();
      return;
    }
    this.switcher.dismiss();
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
    this.closeWorkspaceMenu();
    const open = !this.userMenuOpen();
    this.userMenuOpen.set(open);
    if (open) this.focusPopover('tb-user-popover');
  }

  toggleWorkspaceMenu(ev: Event): void {
    ev.stopPropagation();
    this.userMenuOpen.set(false);
    if (this.workspaceMenuOpen()) {
      this.closeWorkspaceMenu();
      return;
    }
    this.switcher.dismiss();
    this.workspaceMenuOpen.set(true);
    this.focusPopover('tb-workspace-popover');
  }

  /** A switch in progress keeps the menu open; a suspended one is abandoned. */
  private closeWorkspaceMenu(): void {
    if (this.switcher.state().phase === 'pending') return;
    this.switcher.cancel();
    this.switcher.dismiss();
    this.workspaceMenuOpen.set(false);
  }

  private focusWorkspaceToggle(): void {
    queueMicrotask(() => globalThis.document?.getElementById('tb-workspace-toggle')?.focus());
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
    if (slug === this.workspaceService.currentSlug()) {
      this.closeWorkspaceMenu();
      return;
    }
    this.settle(await this.switcher.switch(slug));
  }

  async discardAndSwitch(): Promise<void> {
    this.settle(await this.switcher.discardAndSwitch());
  }

  stayHere(): void {
    this.switcher.cancel();
    this.workspaceMenuOpen.set(false);
    this.focusWorkspaceToggle();
  }

  async switchBack(slug: string): Promise<void> {
    this.workspaceMenuOpen.set(true);
    this.focusWorkspaceToggle();
    this.settle(await this.switcher.switch(slug));
  }

  protected pendingFor(slug: string): boolean {
    const state = this.switcher.state();
    return state.phase === 'pending' && state.slug === slug;
  }

  protected suspendedFor(slug: string): Extract<WorkspaceSwitchState, { phase: 'suspended' }> | null {
    const state = this.switcher.state();
    return state.phase === 'suspended' && state.slug === slug ? state : null;
  }

  protected failedFor(slug: string): boolean {
    const state = this.switcher.state();
    return state.phase === 'failed' && state.slug === slug;
  }

  protected unsavedReason({ label, count }: { label: string; count: number }): string {
    return this.i18n.t(
      count === 1 ? 'workspace.switch.unsaved_one' : 'workspace.switch.unsaved_other',
      { label, count },
    );
  }

  /** The menu closes only once B is on screen. */
  private settle(outcome: WorkspaceSwitchState): void {
    if (outcome.phase === 'switched') this.workspaceMenuOpen.set(false);
  }

  private locationLabel(url: string): string {
    const context = navigationRouteContext(url);
    const zone = this.i18n.t(`experience.adoption.nav.${context.lens}`);
    const surface = matchAgentiumSurface(context.path);
    const verb = COCKPIT_VERBS.find((item) => item.key === context.lens);
    const section = surface && verb
      ? cockpitVerbSections(verb, { experienceStudio: true }).find((item) => item.surfaceId === surface.id)
      : undefined;
    if (!section) return zone;
    const naming = navigationSectionNaming(section, url);
    const label = this.i18n.t(naming.i18nKey);
    return `${zone} › ${label === naming.i18nKey ? naming.label : label}`;
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
        this.toastr.success(
          this.i18n.t('titlebar.workspace.created.body', { name: ws.name }),
          this.i18n.t('titlebar.workspace.created.title'),
        );
        void this.switcher
          .switch(ws.slug, `/workspace/${encodeURIComponent(ws.slug)}/settings`)
          .then((outcome) => this.settle(outcome));
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
    void this.router.navigateByUrl(navigationLeafUrl('auth-signin'));
  }
}
