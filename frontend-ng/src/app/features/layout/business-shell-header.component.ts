import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { AuthStore } from '@app/store/auth.store';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { WorkspaceService } from '@app/core/workspace.service';
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
          <span class="business-cyan-title">{{ workspace.current()?.name || 'Agentium' }}</span>
          <span class="business-cyan-subtitle">Workspace métier</span>
        </div>
      </div>

      <nav class="business-nav" aria-label="Navigation métier">
        @if (navigation.businessSurfaceEnabled('chat')) {
          <a
            routerLink="/chat"
            routerLinkActive="business-nav-active"
            [routerLinkActiveOptions]="{ exact: true }"
            class="business-nav-link"
            title="Recherche"
            aria-label="Recherche"
          >
            <app-icon name="message-square" [size]="14" />
            <span class="business-nav-text business-nav-text-full">Recherche</span>
            <span class="business-nav-text business-nav-text-short">Recherche</span>
          </a>
        }
        @if (navigation.businessSurfaceEnabled('client360-pdr')) {
          <a
            routerLink="/client360"
            routerLinkActive="business-nav-active"
            class="business-nav-link"
            title="Client360 PDR"
            aria-label="Client360 PDR"
          >
            <app-icon name="target" [size]="14" />
            <span class="business-nav-text business-nav-text-full">Client360 PDR</span>
            <span class="business-nav-text business-nav-text-short">Client360</span>
          </a>
        }
        @if (navigation.businessSurfaceEnabled('knowledge-capture')) {
          <a
            routerLink="/knowledge/capture"
            routerLinkActive="business-nav-active"
            [routerLinkActiveOptions]="{ exact: true }"
            class="business-nav-link"
            title="Capture de connaissances"
            aria-label="Capture de connaissances"
          >
            <app-icon name="mic" [size]="14" />
            <span class="business-nav-text business-nav-text-full">Capture de connaissances</span>
            <span class="business-nav-text business-nav-text-short">Capture</span>
          </a>
        }
      </nav>

      <div class="business-actions">
        @if (navigation.effective().preview) {
          <button
            type="button"
            class="business-action"
            (click)="exitPreview()"
            title="Mode avancé"
            aria-label="Mode avancé"
          >
            <app-icon name="panel-left" [size]="13" />
            <span class="business-action-text">Mode avancé</span>
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
          <span class="sr-only">Workspace</span>
          <select
            [ngModel]="workspace.currentSlug()"
            (ngModelChange)="selectWorkspace($event)"
            title="Changer de workspace"
          >
            @for (ws of workspace.workspaces(); track ws.id) {
              <option [value]="ws.slug">{{ ws.name }}</option>
            }
          </select>
        </label>

        <a routerLink="/account/profile" class="business-account" title="Compte utilisateur">
          <span class="business-avatar">{{ initials() }}</span>
          <span class="business-email">{{ auth.email() || 'Compte' }}</span>
        </a>
      </div>
    </header>
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
  protected readonly workspace = inject(WorkspaceService);
  protected readonly navigation = inject(NavigationProfileService);
  protected readonly auth = inject(AuthStore);
  protected readonly theme = inject(ThemeService);
  protected readonly i18n = inject(I18nService);
  private readonly router = inject(Router);

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

  selectWorkspace(slug: string): void {
    if (!slug || slug === this.workspace.currentSlug()) return;
    this.workspace.switchWorkspace(slug);
    const route = this.navigation.businessShellActive()
      ? this.navigation.effective().defaultRoute
      : '/hypervisor';
    const currentPath = (this.router.url || '/').split('?')[0].split('#')[0];
    if (currentPath === route.split('?')[0].split('#')[0]) {
      // Angular reuses the current component on a same-URL navigation. A hard
      // reload is required here so no tenant-owned page state survives while
      // keeping the user on the same semantic surface.
      window.location.reload();
      return;
    }
    this.router.navigateByUrl(route);
  }

  exitPreview(): void {
    this.navigation.setBusinessPreview(false);
    this.router.navigateByUrl('/hypervisor');
  }
}
