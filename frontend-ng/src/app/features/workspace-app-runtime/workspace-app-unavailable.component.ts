import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';

/**
 * Minimal fail-closed shell shown when Workspace App authority is enabled but
 * its bootstrap projection cannot be verified. It deliberately renders no
 * application, Mission Room or Agentium cockpit navigation.
 */
@Component({
  selector: 'app-workspace-app-unavailable',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <section class="unavailable" data-testid="workspace-app-unavailable">
      <div class="status" aria-hidden="true"></div>
      <p class="eyebrow">Workspace safety boundary</p>
      <h1>This workspace is temporarily unavailable</h1>
      <p class="explanation">
        Its application contract could not be verified. No workspace application has been opened.
        Refresh the verified workspace state or select another workspace.
      </p>

      <div class="actions">
        <button type="button" (click)="refresh()" [disabled]="refreshing()">
          {{ refreshing() ? 'Checking…' : 'Check again' }}
        </button>
        @if (isAdmin()) {
          <a routerLink="/workspace-app-repair" data-testid="workspace-app-repair-link">
            Open repair console
          </a>
        }
      </div>

      @if (alternatives().length) {
        <div class="alternatives" aria-label="Other workspaces">
          <p>Other workspaces</p>
          @for (workspace of alternatives(); track workspace.id) {
            <button type="button" class="workspace" (click)="selectWorkspace(workspace.slug)">
              {{ workspace.name }}
            </button>
          }
        </div>
      }
    </section>
  `,
  styles: [`
    :host {
      display: grid;
      min-height: 100dvh;
      place-items: center;
      background: var(--ck-bg-base);
      color: var(--ck-fg-1);
    }
    .unavailable {
      width: min(620px, calc(100vw - 40px));
      border: 1px solid var(--ck-stroke-2);
      border-radius: 8px;
      background: var(--ck-bg-panel);
      padding: 34px;
      box-shadow: 0 24px 80px rgba(0, 0, 0, .24);
    }
    .status {
      width: 10px;
      height: 10px;
      margin-bottom: 20px;
      border-radius: 50%;
      background: #e8a34a;
      box-shadow: 0 0 0 5px color-mix(in srgb, #e8a34a 16%, transparent);
    }
    .eyebrow, .alternatives > p {
      margin: 0;
      color: var(--ck-fg-3);
      font: 10px var(--ck-font-mono);
      letter-spacing: .1em;
      text-transform: uppercase;
    }
    h1 {
      margin: 8px 0 12px;
      font-size: clamp(24px, 4vw, 34px);
      font-weight: 650;
      letter-spacing: -.025em;
    }
    .explanation {
      max-width: 560px;
      margin: 0;
      color: var(--ck-fg-2);
      line-height: 1.6;
    }
    .actions, .alternatives {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-top: 24px;
    }
    button, a {
      min-height: 34px;
      border: 1px solid var(--ck-stroke-3);
      border-radius: 4px;
      padding: 7px 12px;
      background: var(--ck-bg-panel-hi);
      color: var(--ck-fg-1);
      font: 11px var(--ck-font-mono);
      text-decoration: none;
      cursor: pointer;
    }
    button:disabled { cursor: wait; opacity: .55; }
    button:hover:not(:disabled), a:hover { border-color: var(--ck-accent); }
    .alternatives {
      align-items: flex-start;
      border-top: 1px solid var(--ck-stroke-2);
      padding-top: 20px;
    }
    .alternatives > p { flex-basis: 100%; }
    .workspace { background: transparent; }
  `],
})
export class WorkspaceAppUnavailableComponent {
  private readonly workspace = inject(WorkspaceService);
  private readonly router = inject(Router);

  readonly refreshing = signal(false);
  readonly isAdmin = this.workspace.isAdmin;
  readonly alternatives = computed(() => this.workspace.workspaces().filter(
    (workspace) => workspace.slug !== this.workspace.currentSlug(),
  ));

  refresh(): void {
    if (this.refreshing()) return;
    this.refreshing.set(true);
    this.workspace.refreshCurrentWorkspace().pipe(
      finalize(() => this.refreshing.set(false)),
    ).subscribe(() => void this.router.navigateByUrl('/'));
  }

  selectWorkspace(slug: string): void {
    if (this.workspace.switchWorkspace(slug)) {
      void this.router.navigateByUrl('/');
    }
  }
}
