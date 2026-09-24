import { ChangeDetectionStrategy, Component, HostListener, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { AuthStore } from '@app/store/auth.store';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceSwitchService } from '@app/core/workspace-switch.service';
import { ThemeService } from '@app/core/theme.service';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';

@Component({
  selector: 'app-business-shell-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, RouterLinkActive, IconComponent, GlyphComponent],
  template: `
    <header class="business-header">
      <div class="business-brand">
        <img src="/assets/brand/agentium-mark.svg" alt="" width="24" height="24" />
        <div class="business-cyan-copy">
          <span class="business-cyan-title">{{ workspace.current()?.name || brand() }}</span>
          <span class="business-cyan-subtitle">{{ i18n.t('workspace.business.subtitle') }}</span>
        </div>
      </div>

      <nav class="business-nav" [attr.aria-label]="i18n.t('workspace.business.nav')">
        @if (navigation.businessSurfaceEnabled('chat')) {
          <a
            routerLink="/chat"
            routerLinkActive="business-nav-active"
            ariaCurrentWhenActive="page"
            [routerLinkActiveOptions]="{ exact: true }"
            class="business-nav-link"
            [title]="i18n.t('workspace.business.search')"
            [attr.aria-label]="i18n.t('workspace.business.search')"
          >
            <app-icon name="message-square" set="phosphor" [size]="14" />
            <span class="business-nav-text business-nav-text-full">{{
              i18n.t('workspace.business.search')
            }}</span>
            <span class="business-nav-text business-nav-text-short">{{
              i18n.t('workspace.business.search')
            }}</span>
          </a>
        }
        @if (navigation.businessSurfaceEnabled('client360-pdr')) {
          <a
            routerLink="/client360"
            routerLinkActive="business-nav-active"
            ariaCurrentWhenActive="page"
            class="business-nav-link"
            [title]="i18n.t('workspace.business.client360')"
            [attr.aria-label]="i18n.t('workspace.business.client360')"
          >
            <app-icon name="target" set="phosphor" [size]="14" />
            <span class="business-nav-text business-nav-text-full">{{
              i18n.t('workspace.business.client360')
            }}</span>
            <span class="business-nav-text business-nav-text-short">{{
              i18n.t('workspace.business.client360_short')
            }}</span>
          </a>
        }
        @if (navigation.businessSurfaceEnabled('knowledge-capture')) {
          <a
            routerLink="/knowledge/capture"
            routerLinkActive="business-nav-active"
            ariaCurrentWhenActive="page"
            [routerLinkActiveOptions]="{ exact: true }"
            class="business-nav-link"
            [title]="i18n.t('nav.capture')"
            [attr.aria-label]="i18n.t('nav.capture')"
          >
            <app-icon name="mic" set="phosphor" [size]="14" />
            <span class="business-nav-text business-nav-text-full">{{ i18n.t('nav.capture') }}</span>
            <span class="business-nav-text business-nav-text-short">{{
              i18n.t('workspace.business.capture_short')
            }}</span>
          </a>
        }
        @if (navigation.businessSurfaceEnabled('fse-reports')) {
          <a
            routerLink="/knowledge/interventions"
            routerLinkActive="business-nav-active"
            ariaCurrentWhenActive="page"
            [routerLinkActiveOptions]="{ exact: true }"
            class="business-nav-link"
            [title]="i18n.t('workspace.business.fse')"
            [attr.aria-label]="i18n.t('workspace.business.fse')"
          >
            <app-icon name="file-text" set="phosphor" [size]="14" />
            <span class="business-nav-text business-nav-text-full">{{
              i18n.t('workspace.business.fse_short')
            }}</span>
            <span class="business-nav-text business-nav-text-short">{{
              i18n.t('workspace.business.fse_abbr')
            }}</span>
          </a>
        }
      </nav>

      <div class="business-actions">
        @if (navigation.effective().preview) {
          <button
            type="button"
            class="business-action"
            (click)="exitPreview()"
            [title]="i18n.t('workspace.business.advanced')"
            [attr.aria-label]="i18n.t('workspace.business.advanced')"
          >
            <app-icon name="panel-left" [size]="13" />
            <span class="business-action-text">{{ i18n.t('workspace.business.advanced') }}</span>
          </button>
        }

        <button
          type="button"
          class="business-theme-toggle"
          (click)="cycleTheme()"
          [title]="themeTooltip()"
          [attr.aria-label]="themeTooltip()"
        >
          <ck-glyph [name]="themeGlyph()" [size]="14" />
        </button>

        <label class="business-workspace">
          <span class="sr-only">{{ i18n.t('titlebar.workspace') }}</span>
          <select
            #workspaceSelect
            [ngModel]="workspace.currentSlug()"
            (ngModelChange)="selectWorkspace($event, workspaceSelect)"
            [attr.aria-busy]="switchState().phase === 'pending' ? 'true' : null"
            [title]="i18n.t('workspace.business.switch')"
          >
            @for (ws of workspace.workspaces(); track ws.id) {
              <option [value]="ws.slug">{{ ws.name }}</option>
            }
          </select>
        </label>

        <a
          routerLink="/account/profile"
          class="business-account"
          [title]="i18n.t('workspace.business.account')"
        >
          <span class="business-avatar">{{ initials() }}</span>
          <span class="business-email">{{ auth.email() || i18n.t('titlebar.account') }}</span>
        </a>
      </div>
    </header>

    @if (switchState(); as state) {
      @if (state.phase === 'pending') {
        <p class="business-switch" role="status">
          {{ i18n.t('workspace.switch.opening_named', { name: workspaceName(state.slug) }) }}
        </p>
      } @else if (state.phase === 'suspended') {
        <div class="business-switch" role="alert" (click)="$event.stopPropagation()">
          <p class="business-switch-title">{{ i18n.t('workspace.switch.suspended_title') }}</p>
          <p>{{ unsavedReason(state) }}</p>
          <div class="business-switch-actions">
            <button type="button" (click)="stayHere()">{{ i18n.t('workspace.switch.stay') }}</button>
            <button type="button" class="business-switch-discard" (click)="discardAndSwitch()">
              {{ i18n.t('workspace.switch.discard') }}
            </button>
          </div>
        </div>
      } @else if (state.phase === 'failed') {
        <p class="business-switch" role="alert">{{ i18n.t('workspace.switch.failed') }}</p>
      } @else if (state.phase === 'switched') {
        <div class="business-switch" role="status" (click)="$event.stopPropagation()">
          <p class="business-switch-title">{{ i18n.t('workspace.switch.done', { name: workspaceName(state.slug) }) }}</p>
          @if (state.previousSlug; as previous) {
            <button type="button" class="business-switch-back" (click)="switchBack(previous)">
              {{ i18n.t('workspace.switch.back', { name: workspaceName(previous) }) }}
            </button>
          }
        </div>
      }
    }
  `,
  styles: [`
    :host { display: contents; }
    .business-header {
      position: relative;
      z-index: 40;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, auto) minmax(0, 1fr);
      align-items: center;
      gap: 12px;
      min-width: 0;
      height: 52px;
      padding: 0 16px;
      border-bottom: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      background: var(--ck-bg-base);
      color: var(--ck-fg-1, #f5f8fc);
      overflow: hidden;
    }
    .business-brand,
    .business-nav,
    .business-actions,
    .business-action,
    .business-nav-link,
    .business-account {
      display: inline-flex;
      align-items: center;
      min-width: 0;
    }
    .business-brand { gap: 10px; flex: 0 1 auto; }
    .business-brand img {
      display: block;
      border-radius: 6px;
      flex: 0 0 auto;
    }
    .business-cyan-copy {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .business-cyan-title {
      color: var(--ck-fg-1, #f5f8fc);
      font-size: 13px;
      font-weight: 720;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .business-cyan-subtitle {
      color: var(--ck-fg-4, rgba(177, 190, 210, 0.68));
      font: 700 9px/1 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0;
      text-transform: uppercase;
    }
    .business-nav {
      justify-self: center;
      gap: 6px;
      padding: 4px;
      border-radius: 9px;
      border: 1px solid var(--ck-stroke-2);
      background: var(--ck-tint-faint);
      min-width: 0;
      max-width: min(100%, 560px);
      flex-shrink: 1;
    }
    .business-nav-text-short { display: none; }
    .business-nav-link,
    .business-action,
    .business-account {
      gap: 7px;
      min-height: 32px;
      border-radius: 7px;
      text-decoration: none;
      white-space: nowrap;
      transition: 140ms ease;
    }
    .business-nav-link {
      padding: 0 11px;
      color: var(--ck-fg-2);
      font-size: 12px;
      font-weight: 680;
    }
    .business-nav-link:hover,
    .business-nav-active {
      color: var(--ck-signal-cool);
      background: var(--ck-tint-soft);
      box-shadow: inset 0 0 0 1px var(--ck-stroke-hot);
    }
    .business-actions {
      justify-self: end;
      justify-content: flex-end;
      gap: 8px;
      min-width: 0;
      flex-shrink: 0;
    }
    .business-action {
      border: 1px solid var(--ck-stroke-hot);
      background: var(--ck-tint-faint);
      color: var(--ck-signal-cool);
      padding: 0 10px;
      font-size: 11px;
      font-weight: 740;
      cursor: pointer;
    }
    .business-action:hover {
      border-color: var(--ck-stroke-hot);
      background: var(--ck-tint-soft);
    }
    .business-theme-toggle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      flex: 0 0 auto;
      border-radius: 4px;
      border: 1px solid var(--ck-stroke-2);
      background: transparent;
      color: var(--ck-fg-2);
      cursor: pointer;
      transition: 140ms ease;
    }
    .business-theme-toggle:hover {
      border-color: var(--ck-stroke-3);
      background: var(--ck-tint-faint);
      color: var(--ck-fg-1);
    }
    .business-workspace select {
      max-width: 180px;
      min-height: 32px;
      border-radius: 7px;
      border: 1px solid var(--ck-stroke-2);
      background: var(--ck-bg-inset);
      color: var(--ck-fg-2);
      color-scheme: dark;
      padding: 0 9px;
      font-size: 12px;
      font-weight: 650;
      outline: 0;
    }
    :host-context([data-theme="light"]) .business-workspace select {
      color-scheme: light;
    }
    .business-switch {
      position: fixed;
      top: 58px;
      right: 16px;
      z-index: 60;
      display: grid;
      gap: 8px;
      max-width: min(320px, calc(100vw - 32px));
      padding: 12px 14px;
      border: 1px solid var(--ck-stroke-3);
      border-radius: 6px;
      background: var(--ck-bg-panel-hi);
      box-shadow: var(--ck-shadow-popover);
      color: var(--ck-fg-2);
      font-size: 12px;
      line-height: 16px;
    }
    .business-switch-title {
      color: var(--ck-fg-1);
      font-size: 13px;
      font-weight: 600;
    }
    .business-switch-actions {
      display: flex;
      gap: 6px;
    }
    .business-switch-actions button {
      flex: 1 1 auto;
      min-height: 28px;
      padding: 0 10px;
      border: 1px solid var(--ck-stroke-3);
      border-radius: 4px;
      background: transparent;
      color: var(--ck-fg-1);
      cursor: pointer;
    }
    .business-switch-actions .business-switch-discard {
      border-color: var(--ck-signal-neg);
      color: var(--ck-signal-neg);
    }
    .business-switch-back {
      justify-self: start;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--ck-signal-cool);
      cursor: pointer;
    }
    .business-account {
      max-width: 210px;
      color: var(--ck-fg-2);
      padding: 0 9px 0 4px;
      border: 1px solid var(--ck-stroke-2);
      background: var(--ck-tint-faint);
    }
    .business-account:hover {
      color: var(--ck-fg-1);
      background: var(--ck-tint-soft);
    }
    .business-avatar {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border-radius: 999px;
      color: var(--ck-on-signal, #051016);
      background: var(--ck-signal-cool, #67d5f6);
      font-size: 10px;
      font-weight: 760;
      flex: 0 0 auto;
    }
    .business-email {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 12px;
      font-weight: 620;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    /* Compact: short nav labels + trim low-priority chrome before overlap. */
    @media (max-width: 1560px) {
      .business-nav-text-full,
      .business-action-text,
      .business-email,
      .business-cyan-subtitle {
        display: none;
      }
      .business-nav-text-short { display: inline; }
      .business-nav-link,
      .business-action {
        gap: 0;
        padding: 0 9px;
      }
      .business-workspace select {
        max-width: 128px;
      }
      .business-account {
        max-width: none;
        padding: 0 4px;
      }
    }
    /* Tighter: icon-only tabs — full labels need ~1580px with actions visible. */
    @media (max-width: 1180px) {
      .business-nav-text-short {
        display: none;
      }
      .business-nav-link {
        padding: 0 9px;
      }
    }
    @media (max-width: 860px) {
      .business-header {
        grid-template-columns: 1fr;
        grid-auto-rows: auto;
        height: auto;
        min-height: 52px;
        padding-block: 10px;
      }
      .business-nav,
      .business-actions {
        justify-self: stretch;
        overflow-x: auto;
      }
      .business-actions {
        justify-content: flex-start;
      }
    }
  `],
})
export class BusinessShellHeaderComponent {
  /** Screen copy names the product by its brand in this workspace. */
  protected readonly brand = inject(WorkspaceService).brandName;
  protected readonly workspace = inject(WorkspaceService);
  protected readonly navigation = inject(NavigationProfileService);
  protected readonly auth = inject(AuthStore);
  protected readonly theme = inject(ThemeService);
  protected readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly switcher = inject(WorkspaceSwitchService);
  protected readonly switchState = this.switcher.state;

  private static readonly THEME_GLYPHS: Record<'system' | 'light' | 'dark', CkGlyphName> = {
    light: 'crosshair',
    dark: 'pulse',
    system: 'orbit',
  };

  readonly themeGlyph = computed<CkGlyphName>(
    () => BusinessShellHeaderComponent.THEME_GLYPHS[this.theme.businessTheme()],
  );

  readonly themeTooltip = computed(() => {
    // Read the locale signal so the tooltip re-renders on locale flip.
    this.i18n.locale();
    return this.i18n.t(`titlebar.theme.${this.theme.businessTheme()}`);
  });

  cycleTheme(): void {
    this.theme.cycleBusinessTheme();
  }

  readonly initials = computed(() => {
    const email = this.auth.email() || '';
    const workspaceName = this.workspace.current()?.name || 'A';
    const source = email || workspaceName;
    return source
      .split(/[\s.@_-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'A';
  });

  /** A native select already shows the choice: put it back unless B is on screen. */
  async selectWorkspace(slug: string, select: HTMLSelectElement): Promise<void> {
    const outcome = await this.switcher.switch(slug);
    if (outcome.phase !== 'switched') select.value = this.workspace.currentSlug() ?? '';
  }

  stayHere(): void {
    this.switcher.cancel();
  }

  discardAndSwitch(): void {
    void this.switcher.discardAndSwitch();
  }

  switchBack(slug: string): void {
    void this.switcher.switch(slug);
  }

  @HostListener('document:click')
  dismissSwitch(): void {
    if (this.switchState().phase === 'pending') return;
    this.switcher.cancel();
    this.switcher.dismiss();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (!this.switcher.cancel()) this.switcher.dismiss();
  }

  protected workspaceName(slug: string): string {
    return this.workspace.workspaces().find((workspace) => workspace.slug === slug)?.name ?? slug;
  }

  protected unsavedReason({ label, count }: { label: string; count: number }): string {
    return this.i18n.t(
      count === 1 ? 'workspace.switch.unsaved_one' : 'workspace.switch.unsaved_other',
      { label, count },
    );
  }

  exitPreview(): void {
    this.navigation.setBusinessPreview(false);
    this.router.navigateByUrl('/hypervisor');
  }
}
