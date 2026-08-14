import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkApiService } from './work-api.service';
import {
  launchHref,
  launchableApps,
  launcherDecision,
  preferredChannel,
  viewerRoles,
  type WorkChannel,
  type WorkExperience,
} from './work-catalog';

@Component({
  selector: 'app-work-launcher',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, EmptyStateComponent],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work">
      <header class="xp-work-bar">
        <div class="xp-work-brand">
          <h1>{{ i18n.t('experience.work.title') }}</h1>
        </div>
      </header>
      <main class="xp-work-main">
        @if (!loaded()) {
          <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('common.loading')" />
        } @else if (apps().length === 0) {
          <app-empty-state
            icon="layers"
            size="lg"
            [title]="i18n.t('experience.work.empty.title')"
            [description]="i18n.t('experience.work.empty.description')"
          />
        } @else {
          <div class="xp-work-grid">
            @for (app of apps(); track app.id) {
              <a class="xp-work-card" [routerLink]="launchHref(app)">
                <h2>{{ app.name }}</h2>
                <p>{{ patternLabel(app.pattern) }}</p>
                @if (statusOf(app); as status) {
                  <span class="xp-work-status" [class.xp-work-status-live]="status === 'live'">
                    {{ i18n.t(status === 'live' ? 'experience.work.status.live' : 'experience.work.status.pilot') }}
                  </span>
                }
              </a>
            }
          </div>
        }
      </main>
    </div>
  `,
})
export class WorkLauncherComponent {
  private readonly api = inject(WorkApiService);
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly loaded = signal(false);
  readonly apps = signal<WorkExperience[]>([]);
  readonly launchHref = launchHref;

  constructor() {
    const roles = viewerRoles(this.workspace.current()?.role_template, this.workspace.current()?.role);
    this.api.listExperiences().subscribe((rows) => {
      const openable = launchableApps(rows, roles);
      const decision = launcherDecision(openable);
      if (decision.kind === 'redirect') {
        void this.router.navigateByUrl(decision.href);
        return;
      }
      this.apps.set(openable);
      this.loaded.set(true);
    });
  }

  statusOf(app: WorkExperience): WorkChannel | null {
    return preferredChannel(
      app.deployments,
      viewerRoles(this.workspace.current()?.role_template, this.workspace.current()?.role),
    );
  }

  patternLabel(pattern: string): string {
    const key = `experience.work.pattern.${pattern}`;
    const label = this.i18n.t(key);
    return label === key ? pattern : label;
  }
}
