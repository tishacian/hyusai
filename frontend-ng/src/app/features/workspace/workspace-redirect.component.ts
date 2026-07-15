import { Component } from '@angular/core';

/** Passive loading surface while the root navigation resolver handles `/workspace`. */
@Component({
  selector: 'app-workspace-redirect',
  standalone: true,
  template: `
    <div class="flex items-center justify-center h-full">
      <div class="text-gray-500">Loading workspace…</div>
    </div>
  `,
})
export class WorkspaceRedirectComponent {}
