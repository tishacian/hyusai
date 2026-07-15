import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
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
import { ChatOverlayComponent } from '@app/features/chat/chat-overlay.component';
import { AssistantDraftDrawerComponent } from '@app/features/chat/assistant-draft-drawer.component';
import { missionRoomUsesImmersiveShell } from '@app/features/mission-room/mission-room.extension';

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
    RouterOutlet,
    TitleBarComponent,
    SideRailComponent,
    MiniRailComponent,
    CommandBarComponent,
    CommandPaletteComponent,
    BusinessShellHeaderComponent,
    CkPanelHostComponent,
    ChatOverlayComponent,
    AssistantDraftDrawerComponent,
  ],
  template: `
    <div
      [attr.data-theme]="businessShell() ? theme.businessResolved() : null"
      [style.position]="'fixed'"
      [style.inset]="'0'"
      [style.height]="'100dvh'"
      [style.overflow]="'hidden'"
      [style.display]="'grid'"
      [style.gridTemplateRows]="immersiveWorkspaceApp() ? '1fr' : (businessShell() ? '52px 1fr' : '48px 1fr 28px')"
      [style.background]="'var(--ck-bg-base)'"
      [style.color]="'var(--ck-fg-1)'"
    >
      @if (businessShell()) {
        <app-business-shell-header></app-business-shell-header>
      } @else if (!immersiveWorkspaceApp()) {
        <app-title-bar></app-title-bar>
      }

      <div [style.display]="'flex'" [style.minHeight]="'0'" [style.position]="'relative'">
        @if (!immersiveWorkspaceApp() && !businessShell()) {
          <app-side-rail></app-side-rail>
          <app-mini-rail></app-mini-rail>
        }
        <main
          [style.flex]="'1 1 auto'"
          [style.minWidth]="'0'"
          [style.overflow]="immersiveWorkspaceApp() ? 'hidden' : 'auto'"
          [style.background]="'var(--ck-bg-base)'"
          class="ck-scroll"
        >
          <router-outlet />
        </main>
      </div>

      @if (!immersiveWorkspaceApp()) {
        @if (!businessShell()) {
          <app-command-bar></app-command-bar>
        }
      }
      @if (!businessShell()) {
        <app-command-palette></app-command-palette>
      }
      <app-panel-host></app-panel-host>
      <app-chat-overlay></app-chat-overlay>
      <app-assistant-draft-drawer></app-assistant-draft-drawer>
    </div>
  `,
})
export class ShellComponent {
  private readonly workspaceService = inject(WorkspaceService);
  private readonly navigationProfile = inject(NavigationProfileService);
  private readonly navigationTelemetry = inject(NavigationTelemetryService);
  protected readonly theme = inject(ThemeService);
  private readonly router = inject(Router);
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly currentPath = computed(() => (this.url() || '/').split('?')[0]);
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
}
