import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { PageFrameComponent } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  parseAccessFeature,
  parseAccessReason,
  safeReturnPath,
  type AccessFeature,
  type AccessReason,
} from './access-state.model';

const ICONS: Record<AccessReason, string> = {
  disabled: 'zap-off',
  forbidden: 'lock',
  not_found: 'compass',
  unverifiable: 'alert-triangle',
};

const HOME_PATH = '/';

const ROLE_TEMPLATES = new Set([
  'workspace_viewer',
  'workspace_contributor',
  'workspace_reviewer',
  'workspace_admin',
  'workspace_owner',
]);

/**
 * Why a destination is closed, and who can act (plan lot 4, PL02). Four
 * cases chosen by what the server said; an object the user may not see reads
 * as not found. The page never redirects on its own.
 */
@Component({
  selector: 'app-access-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrameComponent, IconComponent, RouterLink],
  template: `
    <ck-page-frame [eyebrow]="i18n.t('experience.access.eyebrow')" [title]="title()">
      <section
        class="access"
        data-testid="access-state"
        [attr.data-reason]="reason()"
        [attr.data-feature]="feature()"
        aria-labelledby="access-state-body"
      >
        <span class="emblem ck-tone-info" [class.ck-tone-warn]="reason() === 'unverifiable'" aria-hidden="true">
          <app-icon [name]="icon()" [size]="20" />
        </span>
        <div class="body">
          <p id="access-state-body" class="lede">{{ body() }}</p>

          @switch (reason()) {
            @case ('disabled') {
              <p class="who" data-testid="access-state-who">{{ i18n.t('experience.access.disabled.who') }}</p>
            }
            @case ('forbidden') {
              <p class="who" data-testid="access-state-role">
                {{ i18n.t('experience.access.forbidden.role', { role: roleLabel() }) }}
              </p>
              <p class="who">{{ i18n.t(feature() === 'studio' ? 'experience.access.forbidden.needed_studio' : 'experience.access.forbidden.needed') }}</p>
            }
            @case ('unverifiable') {
              @if (retryFailed()) {
                <p class="who" role="alert" data-testid="access-state-retry-failed">{{ i18n.t('experience.access.unverifiable.still') }}</p>
              }
            }
          }

          @if (from(); as path) {
            <p class="address">
              <span>{{ i18n.t('experience.access.requested') }}</span>
              <code>{{ path }}</code>
            </p>
          }

          <div class="actions">
            @if (reason() === 'unverifiable') {
              <button
                type="button"
                class="ck-btn ck-cta"
                [disabled]="retrying()"
                (click)="retry()"
                data-testid="access-state-retry"
              >
                {{ i18n.t(retrying() ? 'experience.access.unverifiable.retrying' : 'common.retry') }}
              </button>
            }
            @if (reason() === 'disabled' && isAdmin() && settingsLink(); as link) {
              <a class="ck-btn ck-cta" [routerLink]="link" data-testid="access-state-settings">
                {{ i18n.t('experience.access.disabled.open_settings') }}
              </a>
            }
            <a class="ck-btn ck-btn-quiet" [routerLink]="homeLink" data-testid="access-state-home">
              {{ i18n.t('experience.access.home') }}
            </a>
          </div>
        </div>
      </section>
    </ck-page-frame>
  `,
  styles: [`
    :host { display: block; }
    .access {
      display: flex; align-items: flex-start; gap: var(--ck-space-4);
      max-width: 720px; padding: var(--ck-space-6);
      border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-panel);
    }
    .emblem {
      display: inline-flex; align-items: center; justify-content: center; flex: none;
      width: 40px; height: 40px; border-radius: var(--ck-radius-md);
    }
    .body { min-width: 0; flex: 1; }
    .lede { margin: 0; color: var(--ck-fg-1); font-size: 16px; line-height: 1.5; }
    .who { margin: var(--ck-space-2) 0 0; color: var(--ck-fg-2); font-size: 14px; line-height: 1.5; }
    .address { display: flex; flex-wrap: wrap; gap: var(--ck-space-2); margin: var(--ck-space-4) 0 0; color: var(--ck-fg-3); font-size: 12px; }
    .address code { font-family: var(--ck-font-mono); color: var(--ck-fg-2); overflow-wrap: anywhere; }
    .actions { display: flex; flex-wrap: wrap; gap: var(--ck-space-3); margin-top: var(--ck-space-6); }
    @media (max-width: 480px) {
      .access { flex-direction: column; padding: var(--ck-space-4); }
    }
  `],
})
export class AccessStateComponent {
  readonly i18n = inject(I18nService);
  private readonly workspace = inject(WorkspaceService);
  private readonly router = inject(Router);
  private readonly params = toSignal(inject(ActivatedRoute).queryParamMap, { requireSync: true });

  readonly reason = computed<AccessReason>(() => parseAccessReason(this.params().get('reason')));
  readonly feature = computed<AccessFeature | null>(() => parseAccessFeature(this.params().get('feature')));
  readonly from = computed(() => safeReturnPath(this.params().get('from')));
  readonly icon = computed(() => ICONS[this.reason()]);
  readonly isAdmin = this.workspace.isAdmin;
  /** The workspace home, which the shell resolves per profile; not a catalog surface. */
  readonly homeLink = HOME_PATH;
  readonly retrying = signal(false);
  readonly retryFailed = signal(false);

  readonly title = computed(() => this.i18n.t(`experience.access.${this.caseKey()}.title`));
  readonly body = computed(() => this.i18n.t(`experience.access.${this.caseKey()}.body`));

  readonly roleLabel = computed(() => {
    const current = this.workspace.current();
    const template = current?.role_template ?? '';
    if (ROLE_TEMPLATES.has(template)) return this.i18n.t(`governance.access.role.${template}`);
    return this.i18n.t('experience.access.forbidden.role_unknown');
  });

  readonly settingsLink = computed(() => {
    const slug = this.workspace.currentSlug();
    return slug ? ['/workspace', slug, 'settings'] : null;
  });

  /** `disabled` and `forbidden` read differently for Work and for the Studio. */
  private caseKey(): string {
    const reason = this.reason();
    if (reason === 'disabled') return this.feature() === 'studio' ? 'disabled_studio' : 'disabled';
    return reason;
  }

  retry(): void {
    if (this.retrying()) return;
    this.retrying.set(true);
    this.retryFailed.set(false);
    this.workspace.loadWorkspaces(true).subscribe({
      next: () => {
        this.retrying.set(false);
        void this.router.navigateByUrl(this.from() ?? HOME_PATH);
      },
      error: () => {
        this.retrying.set(false);
        this.retryFailed.set(true);
      },
    });
  }
}
