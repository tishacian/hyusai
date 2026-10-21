import { HttpClient } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, Input, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { captureWorkspaceRequest } from '@app/core/workspace-request-scope';
import type { WorkCatalogItem } from '@app/features/experience/work/work-catalog';
import { applicationRelease, type ApplicationRelease, type SpecializedApplication } from './specialized-app-version';

/** Product boundaries are visible in the application, alongside its actual use. */
@Component({
  selector: 'app-specialized-app-contract',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (application() === 'itsd') {
      <p class="app-contract" role="status" data-testid="specialized-execution-scope">{{ i18n.t(simulation ? 'experience.specialized.itsd.simulation' : 'experience.specialized.itsd.catalog') }}</p>
    }
    <details class="ck-surface app-contract" data-testid="specialized-app-contract">
      <summary>{{ i18n.t('experience.specialized.title') }}</summary>
      <dl>
        <dt>{{ i18n.t('experience.specialized.objective') }}</dt><dd>{{ text('objective') }}</dd>
        <dt>{{ i18n.t('experience.specialized.audience') }}</dt><dd>{{ text('audience') }}</dd>
        <dt>{{ i18n.t('experience.specialized.sources') }}</dt><dd>{{ text('sources') }}</dd>
        <dt>{{ i18n.t('experience.specialized.functions') }}</dt><dd>{{ text('functions') }}</dd>
        <dt>{{ i18n.t('experience.specialized.configure') }}</dt><dd>{{ text('configure') }}</dd>
        <dt>{{ i18n.t('experience.specialized.code') }}</dt><dd>{{ text('code') }}</dd>
        <dt>{{ i18n.t('experience.specialized.application_version') }}</dt>
        <dd data-testid="specialized-application-version" [attr.data-release-id]="release()?.id || null">
          @if (release(); as active) {
            {{ i18n.t('experience.specialized.application_release', { number: active.number, channel: i18n.t('experience.specialized.channel.' + active.channel) }) }}
          } @else {
            {{ i18n.t('experience.specialized.application_version_unknown') }}
          }
        </dd>
        <dt>{{ i18n.t('experience.specialized.version') }}</dt>
        <dd>{{ revision() || i18n.t('experience.specialized.version_unknown') }}</dd>
      </dl>
      <p>{{ text('limits') }}</p>
    </details>
  `,
  styles: [`
    .app-contract { margin: 12px 0; padding: 12px 16px; color: var(--ck-fg-2); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); overflow-wrap: anywhere; }
    summary { min-height: 32px; cursor: pointer; font-weight: 600; }
    summary:focus-visible { outline: 2px solid var(--ck-signal-cool); outline-offset: 3px; }
    dl { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(0, 3fr); gap: 8px 16px; }
    dt { color: var(--ck-fg-3); } dd { margin: 0; }
    p { margin-bottom: 0; }
    @media (max-width: 480px) { dl { grid-template-columns: 1fr; } dd { margin-bottom: 8px; } }
  `],
})
export class SpecializedAppContractComponent {
  readonly application = input.required<SpecializedApplication>();
  @Input() simulation = false;
  readonly i18n = inject(I18nService);
  readonly revision = signal<string | null>(null);
  readonly release = signal<ApplicationRelease | null>(null);
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);

  constructor() {
    this.http.get<{ revision?: string; revision_verified?: boolean }>('/api/v1/build-info')
      .pipe(takeUntilDestroyed()).subscribe({
        next: (build) => this.revision.set(build.revision_verified && /^[a-f0-9]{40}$/.test(build.revision ?? '') ? build.revision!.slice(0, 12) : null),
        error: () => this.revision.set(null),
      });
    effect((onCleanup) => {
      const application = this.application();
      const workspace = this.workspace.current();
      this.release.set(null);
      if (!workspace?.slug) return;
      const request = captureWorkspaceRequest(this.workspace);
      const subscription = this.http.get<{ experiences?: WorkCatalogItem[] }>('/api/v1/work', {
        headers: request.headers,
      }).subscribe({
        next: (catalogue) => {
          if (request.isCurrent()) this.release.set(applicationRelease(application, catalogue?.experiences));
        },
        error: () => {
          if (request.isCurrent()) this.release.set(null);
        },
      });
      onCleanup(() => subscription.unsubscribe());
    });
  }

  text(field: 'objective' | 'audience' | 'sources' | 'functions' | 'configure' | 'code' | 'limits'): string {
    return this.i18n.t(`experience.specialized.${this.application()}.${field}`);
  }
}
