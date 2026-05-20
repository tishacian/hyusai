import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { TitleBarComponent } from './title-bar.component';
import { SideRailComponent } from './side-rail.component';
import { MiniRailComponent } from './mini-rail.component';
import { CommandBarComponent } from './command-bar.component';
import { CommandPaletteComponent } from './command-palette.component';
import { CkPanelHostComponent } from '@app/shared/cockpit/panel.component';
import { ChatOverlayComponent } from '@app/features/chat/chat-overlay.component';

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
    CkPanelHostComponent,
    ChatOverlayComponent,
  ],
  template: `
    <div
      [style.position]="'relative'"
      [style.height]="'100vh'"
      [style.display]="'grid'"
      [style.gridTemplateRows]="immersiveWorkspaceApp() ? '1fr' : '48px 1fr 28px'"
      [style.background]="'var(--ck-bg-base)'"
      [style.color]="'var(--ck-fg-1)'"
    >
      @if (!immersiveWorkspaceApp()) {
        <app-title-bar></app-title-bar>
      }

      <div [style.display]="'flex'" [style.minHeight]="'0'" [style.position]="'relative'">
        @if (!immersiveWorkspaceApp()) {
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
        <app-command-bar></app-command-bar>
      }
      <app-command-palette></app-command-palette>
      <app-panel-host></app-panel-host>
      <app-chat-overlay></app-chat-overlay>
    </div>
  `,
})
export class ShellComponent {
  private readonly workspaceService = inject(WorkspaceService);
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
  readonly immersiveWorkspaceApp = computed(() => {
    const workspace = this.workspaceService.current();
    const path = this.currentPath();
    if (/^\/workspace\/[^/]+\/chat$/.test(path)) {
      return true;
    }
    return (
      this.workspaceService.isDemoMode() &&
      path.startsWith('/hypervisor/mission-room') &&
      (workspace?.settings?.['workspace_app_shell'] as string | undefined) === 'immersive'
    );
  });

  constructor() {
    this.workspaceService.loadWorkspaces().subscribe(() => {
      const path = (this.router.url || '/').split('?')[0];
      if (this.workspaceService.isDemoMode() && (path === '/' || path === '/hypervisor')) {
        const defaultRoute =
          (this.workspaceService.current()?.settings?.['default_route'] as string | undefined) ||
          '/hypervisor/mission-room/cockpit';
        this.router.navigateByUrl(defaultRoute);
      }
    });
  }
}
