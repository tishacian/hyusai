import { NgStyle } from '@angular/common';
import { appearanceStyles } from '@app/core/brand-appearance';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import { ThemeService } from '@app/core/theme.service';
import { TitleBarComponent } from './title-bar.component';
import { SideRailComponent } from './side-rail.component';
import { MiniRailComponent } from './mini-rail.component';
import { CommandBarComponent } from './command-bar.component';
import { CommandPaletteComponent } from './command-palette.component';
import { BusinessShellHeaderComponent } from './business-shell-header.component';
import { CkPanelHostComponent } from '@app/shared/cockpit/panel.component';
import { AssistantDraftDrawerComponent } from '@app/features/chat/assistant-draft-drawer.component';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { missionRoomUsesImmersiveShell } from '@app/features/mission-room/mission-room.extension';
import { I18nService } from '@app/core/i18n.service';

/**
 * Cockpit shell — assembles the title bar, side rail and command bar
 * around the routed content. The chrome is fixed-pitch (48 / 56 / 28 px)
 * to keep the cockpit grid stable across views.
 */
@Component({
  selector: 'app-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgStyle,
    RouterOutlet,
    TitleBarComponent,
    SideRailComponent,
    MiniRailComponent,
    CommandBarComponent,
    CommandPaletteComponent,
    BusinessShellHeaderComponent,
    CkPanelHostComponent,
    AssistantDraftDrawerComponent,
  ],
  template: `
    <div
      [attr.data-brand-scope]="immersiveWorkspaceApp() ? null : ''"
      [attr.data-theme]="immersiveWorkspaceApp() ? null : theme.resolved()"
      [ngStyle]="brandStyles()"
      [attr.data-workspace-app-state]="workspaceAppUnavailable() ? 'unavailable' : null"
      [attr.data-workspace-app-brand]="workspaceAppBranding()"
      [style.position]="'fixed'"
      [style.inset]="'0'"
      [style.height]="'100dvh'"
      [style.overflow]="'hidden'"
      [style.display]="'grid'"
      [style.gridTemplateColumns]="'minmax(0, 1fr)'"
      [style.minWidth]="'0'"
      [style.maxWidth]="'100%'"
      [style.gridTemplateRows]="workspaceAppUnavailable() || immersiveWorkspaceApp() ? '1fr' : (businessShell() ? 'auto minmax(0, 1fr)' : '48px 1fr 28px')"
      [style.background]="'var(--ck-bg-base)'"
      [style.color]="'var(--ck-fg-1)'"
    >
      <a class="shell-skip-link" href="#main-content">{{ i18n.t('nav.skip_to_content') }}</a>
      @if (workspaceAppUnavailable()) {
        <main id="main-content" #mainContent tabindex="-1" [style.minHeight]="'0'" [style.overflow]="'auto'" class="ck-scroll shell-main">
          <router-outlet (activate)="onRouteActivate(mainContent)" />
        </main>
      } @else {
        @if (businessShell()) {
          <app-business-shell-header
            [attr.inert]="chromeInert() ? '' : null"
            [attr.aria-hidden]="chromeInert() ? 'true' : null"
          ></app-business-shell-header>
        } @else if (!immersiveWorkspaceApp()) {
          <app-title-bar
            class="shell-title-bar"
            [attr.inert]="chromeInert() ? '' : null"
            [attr.aria-hidden]="chromeInert() ? 'true' : null"
          ></app-title-bar>
        }

        <div
          class="shell-body"
          [class.shell-body-with-rails]="!immersiveWorkspaceApp() && !businessShell()"
          [style.minHeight]="'0'"
          [style.minWidth]="'0'"
          [style.position]="'relative'"
        >
          @if (!immersiveWorkspaceApp() && !businessShell()) {
            <app-side-rail
              class="shell-side-rail"
              [attr.inert]="chromeInert() ? '' : null"
              [attr.aria-hidden]="chromeInert() ? 'true' : null"
            ></app-side-rail>
            <app-mini-rail
              class="shell-mini-rail"
              [attr.inert]="chromeInert() ? '' : null"
              [attr.aria-hidden]="chromeInert() ? 'true' : null"
            ></app-mini-rail>
          }
          <main
            id="main-content"
            #mainContent
            tabindex="-1"
            class="ck-scroll shell-main"
            [attr.inert]="mainInert() ? '' : null"
            [attr.aria-hidden]="mainInert() ? 'true' : null"
            [style.flex]="'1 1 auto'"
            [style.minWidth]="'0'"
            [style.overflow]="immersiveWorkspaceApp() ? 'hidden' : 'auto'"
            [style.background]="'var(--ck-bg-base)'"
          >
            <router-outlet (activate)="onRouteActivate(mainContent)" />
          </main>
        </div>

        @if (!immersiveWorkspaceApp() && !businessShell()) {
          <app-command-bar
            [attr.inert]="chromeInert() ? '' : null"
            [attr.aria-hidden]="chromeInert() ? 'true' : null"
          ></app-command-bar>
        }
        @if (!businessShell()) {
          <app-command-palette
            [attr.inert]="chromeInert() ? '' : null"
            [attr.aria-hidden]="chromeInert() ? 'true' : null"
          ></app-command-palette>
        }
        <app-panel-host
          [attr.inert]="chromeInert() ? '' : null"
          [attr.aria-hidden]="chromeInert() ? 'true' : null"
        ></app-panel-host>
        <app-assistant-draft-drawer
          [attr.inert]="chromeInert() ? '' : null"
          [attr.aria-hidden]="chromeInert() ? 'true' : null"
        ></app-assistant-draft-drawer>
      }
      <span class="shell-route-status" role="status" aria-live="polite" aria-atomic="true">
        {{ routeAnnouncement() }}
      </span>
    </div>
  `,
  styles: [`
    /* The shell is a fixed viewport. Without minmax(0, 1fr) the implicit
       column sizes to min-content, wide pages grow past the window, and
       overflow:hidden (plus body overflow-x:hidden) clips with no scrollbar. */
    .shell-body {
      display: flex;
      min-width: 0;
      max-width: 100%;
    }

    .shell-title-bar,
    app-command-bar {
      min-width: 0;
      max-width: 100%;
    }

    .shell-main {
      min-width: 0;
    }

    .shell-main:focus {
      outline: none;
    }

    .shell-skip-link {
      position: fixed;
      z-index: 2000;
      inset: 8px auto auto 8px;
      padding: 8px 12px;
      border: 2px solid var(--ck-signal-cool);
      border-radius: var(--ck-radius-md);
      background: var(--ck-bg-panel-hi);
      color: var(--ck-fg-1);
      transform: translateY(calc(-100% - 16px));
    }
    .shell-skip-link:focus { transform: translateY(0); }

    .shell-route-status {
      position: fixed;
      width: 1px;
      height: 1px;
      margin: -1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }

    @media (max-width: 700px) {
      .shell-body-with-rails {
        display: grid;
        grid-template-columns: 56px minmax(0, 1fr);
        grid-template-rows: auto minmax(0, 1fr);
      }

      .shell-body-with-rails .shell-side-rail {
        grid-column: 1;
        grid-row: 1 / 3;
      }

      .shell-body-with-rails .shell-main {
        grid-column: 2;
        grid-row: 2;
      }
    }
  `],
})
export class ShellComponent {
  readonly i18n = inject(I18nService);
  private readonly workspaceService = inject(WorkspaceService);
  private readonly navigationProfile = inject(NavigationProfileService);
  private readonly navigationTelemetry = inject(NavigationTelemetryService);
  protected readonly theme = inject(ThemeService);
  readonly brandStyles = computed(() => {
    if (this.immersiveWorkspaceApp()) return {};
    const brand = this.workspaceService.current()?.settings?.['platform_brand'] as Record<string, unknown> | undefined;
    return appearanceStyles(brand?.['appearance'], this.theme.resolved());
  });
  private readonly chatOverlay = inject(ChatOverlayService);
  private readonly router = inject(Router);
  readonly routeAnnouncement = signal('');
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly currentPath = computed(() => (this.url() || '/').split('?')[0]);
  readonly routeOverlayOpen = computed(() => this.currentPath().startsWith('/create/apps/'));
  readonly chromeInert = computed(() => this.routeOverlayOpen() || this.chatOverlay.blocksPage());
  readonly mainInert = computed(() => this.chatOverlay.blocksPage());
  readonly workspaceAppUnavailable = this.navigationProfile.workspaceAppUnavailable;
  readonly workspaceAppBranding = computed(() => {
    const runtime = this.workspaceService.current()?.workspace_app_runtime;
    if (runtime?.enabled !== true || runtime.valid !== true || !runtime.experience) {
      return null;
    }
    const namespaces = runtime.experience.branding_namespaces
      .filter((value) => typeof value === 'string' && value.trim().length > 0);
    return namespaces.length > 0 ? [...new Set(namespaces)].join(',') : null;
  });
  readonly businessShell = computed(() =>
    this.navigationProfile.businessShellActive() && !this.immersiveWorkspaceApp(),
  );
  readonly immersiveWorkspaceApp = computed(() => {
    const workspace = this.workspaceService.current();
    const path = this.currentPath();
    if (/^\/workspace\/[^/]+\/chat$/.test(path)) {
      return true;
    }
    return missionRoomUsesImmersiveShell(workspace, path);
  });

  constructor() {
    // The guard establishes the workspace before the shell is activated. This
    // call only releases an initial deferred audit event; it never resolves or
    // initiates navigation.
    this.navigationTelemetry.flushDeferred();
  }

  onRouteActivate(main: HTMLElement): void {
    queueMicrotask(() => {
      const heading = main.querySelector<HTMLElement>('h1');
      if (heading) {
        if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
        heading.focus({ preventScroll: true });
      } else {
        main.focus({ preventScroll: true });
      }
      this.routeAnnouncement.set(heading?.textContent?.trim() || document.title || this.currentPath());
    });
  }
}
