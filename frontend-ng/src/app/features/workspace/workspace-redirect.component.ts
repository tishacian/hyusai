import { Component, effect, inject } from '@angular/core';
import { Router } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';

/**
 * Entry point for `/workspace` — redirects to the current workspace's settings page.
 */
@Component({
  selector: 'app-workspace-redirect',
  standalone: true,
  template: `
    <div class="flex items-center justify-center h-full">
      <div class="text-gray-500">Loading workspace…</div>
    </div>
  `,
})
export class WorkspaceRedirectComponent {
  private readonly workspaceService = inject(WorkspaceService);
  private readonly router = inject(Router);
  private readonly navigationTelemetry = inject(NavigationTelemetryService);

  constructor() {
    effect(() => {
      const current = this.workspaceService.current();
      if (current) {
        const resolvedRoute = `/workspace/${encodeURIComponent(current.slug)}/settings`;
        this.navigationTelemetry.registerRedirect({
          requestedRoute: this.router.url || '/workspace',
          resolvedRoute,
          owner: 'workspace_entrypoint',
          reason: 'workspace_settings_entrypoint',
        });
        this.router.navigateByUrl(resolvedRoute, { replaceUrl: true });
      }
    });

    if (this.workspaceService.workspaces().length === 0) {
      this.workspaceService.loadWorkspaces().subscribe();
    }
  }
}
