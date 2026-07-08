import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { AuthStore } from '@app/store/auth.store';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';

@Component({
  selector: 'app-business-shell-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, RouterLinkActive, IconComponent],
  template: `
    <header class="business-header">
      <div class="business-brand">
        <img src="/assets/brand/agentium-mark.svg" alt="" width="24" height="24" />
        <div class="business-cyan-copy">
          <span class="business-cyan-title">{{ workspace.current()?.name || 'Agentium' }}</span>
          <span class="business-cyan-subtitle">Workspace métier</span>
        </div>
      </div>

      <nav class="business-nav" aria-label="Navigation métier">
        <a
          routerLink="/chat"
          routerLinkActive="business-nav-active"
          [routerLinkActiveOptions]="{ exact: true }"
          class="business-nav-link"
        >
          <app-icon name="message-square" [size]="14" />
          Recherche
        </a>
        <a
          routerLink="/client360"
          routerLinkActive="business-nav-active"
          class="business-nav-link"
        >
          <app-icon name="target" [size]="14" />
          Client360 PDR
        </a>
        <a
          routerLink="/knowledge/capture"
          routerLinkActive="business-nav-active"
          [routerLinkActiveOptions]="{ exact: true }"
          class="business-nav-link"
        >
          <app-icon name="mic" [size]="14" />
          Capture de connaissances
        </a>
      </nav>

      <div class="business-actions">
        @if (navigation.effective().preview) {
          <button type="button" class="business-action" (click)="exitPreview()">
            <app-icon name="panel-left" [size]="13" />
            Mode avancé
          </button>
        }

        <label class="business-workspace">
          <span class="sr-only">Workspace</span>
          <select
            [ngModel]="workspace.currentSlug()"
            (ngModelChange)="selectWorkspace($event)"
            title="Changer de workspace"
          >
            @for (ws of workspace.workspaces(); track ws.id) {
              <option [value]="ws.slug">{{ ws.name }}</option>
            }
          </select>
        </label>

        <a routerLink="/account/profile" class="business-account" title="Compte utilisateur">
          <span class="business-avatar">{{ initials() }}</span>
          <span class="business-email">{{ auth.email() || 'Compte' }}</span>
        </a>
      </div>
    </header>
  `,
  styles: [`
    :host { display: contents; }
    .business-header {
      position: relative;
      z-index: 40;
      display: grid;
      grid-template-columns: minmax(190px, 0.8fr) auto minmax(220px, 1fr);
      align-items: center;
      gap: 14px;
      min-width: 0;
      height: 52px;
      padding: 0 16px;
      border-bottom: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      background: rgba(7, 12, 20, 0.96);
      color: var(--ck-fg-1, #f5f8fc);
    }
    .business-brand,
    .business-nav,
    .business-actions,
    .business-action,
    .business-nav-link,
    .business-account {
      display: inline-flex;
      align-items: center;
      min-width: 0;
    }
    .business-brand { gap: 10px; }
    .business-brand img {
      display: block;
      border-radius: 6px;
      flex: 0 0 auto;
    }
    .business-cyan-copy {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .business-cyan-title {
      color: var(--ck-fg-1, #f5f8fc);
      font-size: 13px;
      font-weight: 720;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .business-cyan-subtitle {
      color: var(--ck-fg-4, rgba(177, 190, 210, 0.68));
      font: 700 9px/1 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0;
      text-transform: uppercase;
    }
    .business-nav {
      justify-self: center;
      gap: 6px;
      padding: 4px;
      border-radius: 9px;
      border: 1px solid rgba(148, 197, 229, 0.13);
      background: rgba(255, 255, 255, 0.035);
    }
    .business-nav-link,
    .business-action,
    .business-account {
      gap: 7px;
      min-height: 32px;
      border-radius: 7px;
      text-decoration: none;
      white-space: nowrap;
      transition: 140ms ease;
    }
    .business-nav-link {
      padding: 0 11px;
      color: rgba(226, 236, 248, 0.76);
      font-size: 12px;
      font-weight: 680;
    }
    .business-nav-link:hover,
    .business-nav-active {
      color: rgb(245, 248, 252);
      background: rgba(34, 211, 238, 0.10);
      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.18);
    }
    .business-actions {
      justify-self: end;
      justify-content: flex-end;
      gap: 8px;
    }
    .business-action {
      border: 1px solid rgba(103, 213, 246, 0.22);
      background: rgba(34, 211, 238, 0.08);
      color: rgb(207, 250, 254);
      padding: 0 10px;
      font-size: 11px;
      font-weight: 740;
      cursor: pointer;
    }
    .business-action:hover {
      border-color: rgba(103, 213, 246, 0.38);
      background: rgba(34, 211, 238, 0.14);
    }
    .business-workspace select {
      max-width: 180px;
      min-height: 32px;
      border-radius: 7px;
      border: 1px solid rgba(148, 197, 229, 0.13);
      background: rgba(255, 255, 255, 0.035);
      color: rgba(226, 236, 248, 0.82);
      color-scheme: dark;
      padding: 0 9px;
      font-size: 12px;
      font-weight: 650;
      outline: 0;
    }
    .business-account {
      max-width: 210px;
      color: rgba(226, 236, 248, 0.76);
      padding: 0 9px 0 4px;
      border: 1px solid rgba(148, 197, 229, 0.13);
      background: rgba(255, 255, 255, 0.025);
    }
    .business-account:hover {
      color: rgb(245, 248, 252);
      background: rgba(255, 255, 255, 0.055);
    }
    .business-avatar {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border-radius: 999px;
      color: var(--ck-on-signal, #051016);
      background: var(--ck-signal-cool, #67d5f6);
      font-size: 10px;
      font-weight: 760;
      flex: 0 0 auto;
    }
    .business-email {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 12px;
      font-weight: 620;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    @media (max-width: 860px) {
      .business-header {
        grid-template-columns: 1fr;
        grid-auto-rows: auto;
        height: auto;
        min-height: 52px;
        padding-block: 10px;
      }
      .business-nav,
      .business-actions {
        justify-self: stretch;
        overflow-x: auto;
      }
      .business-actions {
        justify-content: flex-start;
      }
    }
  `],
})
export class BusinessShellHeaderComponent {
  protected readonly workspace = inject(WorkspaceService);
  protected readonly navigation = inject(NavigationProfileService);
  protected readonly auth = inject(AuthStore);
  private readonly router = inject(Router);

  readonly initials = computed(() => {
    const email = this.auth.email() || '';
    const workspaceName = this.workspace.current()?.name || 'A';
    const source = email || workspaceName;
    return source
      .split(/[\s.@_-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'A';
  });

  selectWorkspace(slug: string): void {
    if (!slug || slug === this.workspace.currentSlug()) return;
    this.workspace.switchWorkspace(slug);
    const route = this.navigation.businessShellActive()
      ? this.navigation.effective().defaultRoute
      : '/hypervisor';
    this.router.navigateByUrl(route);
  }

  exitPreview(): void {
    this.navigation.setBusinessPreview(false);
    this.router.navigateByUrl('/hypervisor');
  }
}
