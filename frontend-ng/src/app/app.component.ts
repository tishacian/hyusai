import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { FaviconService } from './core/favicon.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  template: '<router-outlet />',
})
export class AppComponent {
  private readonly favicon = inject(FaviconService);

  constructor() {
    this.favicon.init();
  }
}
