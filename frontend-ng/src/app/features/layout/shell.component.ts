import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { TitleBarComponent } from './title-bar.component';
import { SideRailComponent } from './side-rail.component';
import { CommandBarComponent } from './command-bar.component';
import { CommandPaletteComponent } from './command-palette.component';

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
    CommandBarComponent,
    CommandPaletteComponent,
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
    </div>
  `,
})
export class ShellComponent {
  private readonly workspaceService = inject(WorkspaceService);

  constructor() {
    this.workspaceService.loadWorkspaces().subscribe();
  }
}
