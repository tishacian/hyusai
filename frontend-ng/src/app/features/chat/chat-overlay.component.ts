import { ChangeDetectionStrategy, Component, HostListener, computed, inject } from '@angular/core';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { ChatOverlayService } from './chat-overlay.service';
import { ChatWorkspaceComponent } from './chat-workspace.component';

/**
 * `ChatOverlayComponent` — shell-level side-panel that hosts the global
 * chat workspace. Mounted once inside `ShellComponent` so the chat is
 * reachable from any view without tearing down context.
 *
 * Lifecycle is driven by `ChatOverlayService`:
 *  - `open()` from the title-bar icon, the global ⌘J shortcut, or a
 *    command palette command → `isOpen.set(true)`.
 *  - `close()` from the panel close button, Escape (via `PanelHostService`)
 *    or another explicit call.
 *
 * The panel embeds `<app-chat-workspace [inline]="true">` in compact
 * layout: dropzone collapsible above the chat instead of the two-column
 * layout used on the full-screen `/chat` route.
 */
@Component({
  selector: 'app-chat-overlay',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkPanelComponent, ChatWorkspaceComponent],
  template: `
    <ck-panel
      [open]="overlay.isOpen()"
      (openChange)="onOpenChange($event)"
      position="side"
      eyebrow="Chat · ⌘J"
      [title]="title()"
      width="560px"
    >
      @if (overlay.isOpen()) {
        <app-chat-workspace
          [inline]="true"
          [startMode]="overlay.startMode()"
          [initialSystemId]="overlay.preselectedSystemId()"
          [initialContextId]="overlay.preselectedContextId()"
        />
      }
    </ck-panel>
  `,
  styles: [`
    :host { display: contents; }
    /* The ck-panel paints its own shell; we just make sure the workspace
       fills the entire panel body (which defaults to 18px padding).
       We override by pulling the workspace flush with the panel edges. */
    :host ::ng-deep ck-panel > div[role="complementary"] > div:last-child {
      padding: 0 !important;
    }
  `],
})
export class ChatOverlayComponent {
  readonly overlay = inject(ChatOverlayService);

  readonly title = computed<string>(() => {
    switch (this.overlay.startMode()) {
      case 'drop':   return 'Drop-and-ask';
      case 'system': return 'Chat with system';
      case 'quick':
      default:       return 'Ask a question';
    }
  });

  onOpenChange(open: boolean): void {
    if (!open) this.overlay.close();
  }

  /**
   * Global keyboard shortcut: ⌘J (macOS) / Ctrl+J (Linux/Windows).
   * We override the browser default (⌘J opens Downloads on Chrome) —
   * acceptable for an SPA since the overlay is a more productive use of
   * that shortcut for this surface.
   */
  @HostListener('window:keydown', ['$event'])
  onKey(ev: KeyboardEvent): void {
    const isMod = ev.metaKey || ev.ctrlKey;
    if (isMod && (ev.key === 'j' || ev.key === 'J')) {
      ev.preventDefault();
      this.overlay.toggle();
    }
  }
}
