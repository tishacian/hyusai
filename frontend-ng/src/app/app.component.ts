import { ChatOverlayService } from './features/chat/chat-overlay.service';
import { ChatOverlayComponent } from './features/chat/chat-overlay.component';
import { HelpOverlayService } from './features/help/help-overlay.service';
import { HelpPanelComponent } from './features/help/help-panel.component';
import { CkPanelHostComponent } from './shared/cockpit/panel-host';
import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { FaviconService } from './core/favicon.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, ChatOverlayComponent, HelpPanelComponent, CkPanelHostComponent],
  template: `
    <router-outlet />
    <app-panel-host />
    @defer (on idle; when overlay.isOpen()) { <app-chat-overlay /> }
    @defer (on idle; when help.isOpen()) { <app-help-panel /> }
  `,
})
export class AppComponent {
  readonly overlay = inject(ChatOverlayService);
  readonly help = inject(HelpOverlayService);
  private readonly favicon = inject(FaviconService);

  constructor() {
    this.favicon.init();
  }
}
