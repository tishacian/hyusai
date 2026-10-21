import { ChangeDetectionStrategy, Component, computed, effect, inject, input, untracked } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService, type WorkspaceDetail } from '@app/core/workspace.service';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ExperienceActivationController } from './experience-activation.controller';
import { ExperienceActivationService } from './experience-activation.service';

/**
 * Administrator setting "Work and Studio" (plan lot 4, PL01). It says who the
 * change reaches before asking for confirmation, writes the single flag
 * through a compare-and-set, and only shows the state the server returns.
 */
@Component({
  selector: 'app-workspace-experience-activation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ConfirmDialogComponent, IconComponent],
  template: `
    <section class="ck-surface activation" aria-labelledby="experience-activation-title" data-testid="experience-activation">
      <header>
        <span class="emblem" aria-hidden="true"><app-icon name="layout-grid" [size]="18" /></span>
        <div>
          <h2 id="experience-activation-title">{{ i18n.t('experience.activation.title') }}</h2>
          <p class="lede">{{ i18n.t('experience.activation.description') }}</p>
        </div>
      </header>

      @if (!canEdit()) {
        <p class="line" data-testid="experience-activation-readonly">
          {{ i18n.t(memberViewEnabled() ? 'experience.activation.readonly.on' : 'experience.activation.readonly.off') }}
        </p>
      } @else {
        @switch (readState()) {
          @case ('loading') {
            <p class="line" role="status" data-testid="experience-activation-loading">
              {{ i18n.t('experience.activation.loading') }}
            </p>
          }
          @case ('error') {
            <div class="notice ck-tone-neg" role="alert" data-testid="experience-activation-read-error">
              <app-icon name="alert-triangle" [size]="16" aria-hidden="true" />
              <p>{{ i18n.t('experience.activation.read_error') }}</p>
              <button type="button" class="ck-btn ck-btn-quiet" (click)="load()">{{ i18n.t('common.retry') }}</button>
            </div>
          }
          @case ('loaded') {
            @if (state(); as s) {
              <div class="status-row">
                <span
                  class="badge"
                  [class.ck-tone-ok]="s.enabled"
                  [class.ck-tone-info]="!s.enabled"
                  data-testid="experience-activation-state"
                  [attr.data-enabled]="s.enabled"
                >
                  {{ i18n.t(s.enabled ? 'experience.activation.state.on' : 'experience.activation.state.off') }}
                </span>
                <span class="hint">{{ i18n.t('experience.activation.read_from_server') }}</span>
              </div>

              <div class="effect" data-testid="experience-activation-effect">
                <h3>{{ i18n.t(s.enabled ? 'experience.activation.effect.off_title' : 'experience.activation.effect.on_title') }}</h3>
                <ul>
                  @if (s.enabled) {
                    <li>{{ i18n.t('experience.activation.effect.off_members', { count: s.members.total }) }}</li>
                    <li>{{ i18n.t('experience.activation.effect.off_kept') }}</li>
                  } @else {
                    <li>{{ i18n.t('experience.activation.effect.on_members', { count: s.members.total }) }}</li>
                    <li>{{ i18n.t('experience.activation.effect.on_editors', { count: s.members.studio_editors }) }}</li>
                    <li>{{ i18n.t('experience.activation.effect.on_reviewers', { count: s.members.studio_reviewers }) }}</li>
                    <li>{{ i18n.t('experience.activation.effect.on_access') }}</li>
                  }
                </ul>
              </div>

              <div class="actions">
                <button
                  type="button"
                  class="ck-btn"
                  [class.ck-cta]="!s.enabled"
                  [class.ck-btn-quiet]="s.enabled"
                  [disabled]="locked()"
                  (click)="confirmOpen.set(true)"
                  data-testid="experience-activation-toggle"
                >
                  {{ i18n.t(s.enabled ? 'experience.activation.disable' : 'experience.activation.enable') }}
                </button>
                @if (outcome() === 'saving') {
                  <span class="hint" role="status">{{ i18n.t('experience.activation.saving') }}</span>
                }
              </div>
            }
          }
        }

        @switch (outcome()) {
          @case ('saved') {
            <p class="notice ck-tone-ok" role="status" data-testid="experience-activation-saved">
              {{ i18n.t(state()?.enabled ? 'experience.activation.saved_on' : 'experience.activation.saved_off') }}
            </p>
          }
          @case ('conflict') {
            <p class="notice ck-tone-warn" role="alert" data-testid="experience-activation-conflict">
              {{ i18n.t('experience.activation.conflict') }}
            </p>
          }
          @case ('refused') {
            <p class="notice ck-tone-neg" role="alert" data-testid="experience-activation-refused">
              {{ i18n.t('experience.activation.refused') }}
            </p>
          }
          @case ('failed') {
            <p class="notice ck-tone-neg" role="alert" data-testid="experience-activation-failed">
              {{ i18n.t('experience.activation.failed') }}
            </p>
          }
          @case ('unknown') {
            <div class="notice ck-tone-warn" role="alert" data-testid="experience-activation-unknown">
              <app-icon name="alert-triangle" [size]="16" aria-hidden="true" />
              <p>{{ i18n.t('experience.activation.unknown') }}</p>
              <button type="button" class="ck-btn ck-btn-quiet" (click)="load()">
                {{ i18n.t('experience.activation.verify') }}
              </button>
            </div>
          }
        }
      }
    </section>

    @if (state(); as s) {
      <app-confirm-dialog
        [open]="confirmOpen()"
        [title]="i18n.t(s.enabled ? 'experience.activation.confirm.off_title' : 'experience.activation.confirm.on_title')"
        [description]="confirmDescription()"
        [confirmLabel]="i18n.t(s.enabled ? 'experience.activation.disable' : 'experience.activation.enable')"
        [tone]="s.enabled ? 'danger' : 'brand'"
        icon="layout-grid"
        (confirm)="apply()"
        (cancel)="confirmOpen.set(false)"
      />
    }
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .activation { padding: var(--ck-space-6); border-radius: var(--ck-radius-md); color: var(--ck-fg-1); }
    header { display: flex; align-items: flex-start; gap: var(--ck-space-3); margin-bottom: var(--ck-space-4); }
    .emblem {
      display: inline-flex; align-items: center; justify-content: center; flex: none;
      width: 40px; height: 40px; border-radius: var(--ck-radius-md);
      color: var(--ck-status-info-fg); background: var(--ck-status-info-bg); border: 1px solid var(--ck-status-info-line);
    }
    h2 { margin: 0; font-size: 16px; font-weight: 600; font-family: var(--ck-font-display); }
    h3 { margin: 0 0 var(--ck-space-2); font-size: 14px; font-weight: 600; }
    .lede, .line, .hint { margin: var(--ck-space-1) 0 0; color: var(--ck-fg-3); font-size: 14px; line-height: 1.5; max-width: 72ch; }
    .hint { margin: 0; font-size: 12px; }
    .status-row, .actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--ck-space-3); }
    .badge { padding: var(--ck-space-1) var(--ck-space-2); border-radius: var(--ck-radius-sm); font-size: 12px; font-weight: 600; }
    .effect {
      margin: var(--ck-space-4) 0; padding: var(--ck-space-3) var(--ck-space-4);
      border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-panel-hi);
    }
    .effect ul { margin: 0; padding-left: var(--ck-space-6); color: var(--ck-fg-2); font-size: 14px; line-height: 1.6; }
    .notice {
      display: flex; flex-wrap: wrap; align-items: center; gap: var(--ck-space-2);
      margin: var(--ck-space-4) 0 0; padding: var(--ck-space-2) var(--ck-space-3);
      border-radius: var(--ck-radius-md); font-size: 14px;
    }
    .notice p { margin: 0; flex: 1 1 240px; }
  `],
})
export class WorkspaceExperienceActivationComponent {
  readonly i18n = inject(I18nService);
  private readonly workspaces = inject(WorkspaceService);

  readonly workspace = input.required<WorkspaceDetail>();
  readonly canEdit = input(false);

  readonly controller = new ExperienceActivationController(
    inject(ExperienceActivationService),
    () => this.workspace().slug,
    () => this.workspaces.refreshCurrentWorkspace().subscribe({ error: () => undefined }),
  );
  readonly readState = this.controller.readState;
  readonly state = this.controller.state;
  readonly outcome = this.controller.outcome;
  readonly confirmOpen = this.controller.confirmOpen;
  readonly locked = this.controller.locked;

  readonly memberViewEnabled = computed(() => {
    const features = this.workspace().settings?.['features'];
    return !!features && typeof features === 'object'
      && (features as Record<string, unknown>)['experience_v1'] === true;
  });

  readonly confirmDescription = computed(() => {
    const s = this.state();
    if (!s) return '';
    return s.enabled
      ? this.i18n.t('experience.activation.confirm.off_body', { count: s.members.total })
      : this.i18n.t('experience.activation.confirm.on_body', {
        count: s.members.total,
        editors: s.members.studio_editors,
        reviewers: s.members.studio_reviewers,
      });
  });

  constructor() {
    effect(() => {
      const slug = this.workspace().slug;
      const admin = this.canEdit();
      untracked(() => { if (admin) this.controller.open(slug); });
    });
  }

  load(): void { this.controller.load(); }
  apply(): void { this.controller.apply(); }
}
