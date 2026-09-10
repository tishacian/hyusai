import { ChatOverlayService } from './features/chat/chat-overlay.service';
import { ChatOverlayComponent } from './features/chat/chat-overlay.component';
import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { FaviconService } from './core/favicon.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, ChatOverlayComponent],
  template: '<router-outlet /> @defer (on idle; when overlay.isOpen()) { <app-chat-overlay /> }',
})
export class AppComponent {
  readonly overlay = inject(ChatOverlayService);
  private readonly favicon = inject(FaviconService);

  constructor() {
    this.favicon.init();
  }
}
