import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
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
      [style.gridTemplateRows]="'48px 1fr 28px'"
      [style.background]="'var(--ck-bg-base)'"
      [style.color]="'var(--ck-fg-1)'"
    >
      <app-title-bar></app-title-bar>

      <div [style.display]="'flex'" [style.minHeight]="'0'" [style.position]="'relative'">
        <app-side-rail></app-side-rail>
        <app-mini-rail></app-mini-rail>
        <main
          [style.flex]="'1 1 auto'"
          [style.minWidth]="'0'"
          [style.overflow]="'auto'"
          [style.background]="'var(--ck-bg-base)'"
          class="ck-scroll"
        >
          <router-outlet />
        </main>
      </div>

      <app-command-bar></app-command-bar>
      <app-command-palette></app-command-palette>
      <app-panel-host></app-panel-host>
      <app-chat-overlay></app-chat-overlay>
    </div>
  `,
})
export class ShellComponent {
  private readonly workspaceService = inject(WorkspaceService);
  private readonly router = inject(Router);

  constructor() {
    this.workspaceService.loadWorkspaces().subscribe(() => {
      const path = (this.router.url || '/').split('?')[0];
      if (this.workspaceService.isDemoMode() && (path === '/' || path === '/hypervisor')) {
        this.router.navigateByUrl('/hypervisor/mission-room');
      }
    });
  }
}
