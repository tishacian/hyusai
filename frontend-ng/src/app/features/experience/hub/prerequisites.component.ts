import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Observable, map } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { canReleaseExperienceStudio } from '../experience-access';
import { selectAutomationSkill } from './automation-draft.model';
import { StartApiService } from './start-api.service';
import { PREREQUISITES, countState, type PrerequisiteId, type PrerequisiteState } from './start.model';

const ICON: Record<PrerequisiteState, string> = {
  loading: 'loader',
  ok: 'check-circle',
  missing: 'circle',
  error: 'alert-triangle',
};

/**
 * What this workspace already has to go from nothing to an application, read
 * from the server (plan lot 4, US08). Each missing piece names where it is
 * resolved; a failed read says "unknown" and can be retried, never "missing".
 */
@Component({
  selector: 'app-start-prerequisites',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, NavLinkDirective, RouterLink],
  template: `
    <section class="prereq" aria-labelledby="prereq-title" data-testid="start-prerequisites">
      <h2 id="prereq-title">{{ i18n.t('experience.start.prereq.title') }}</h2>
      <p class="lede">{{ i18n.t('experience.start.prereq.lede') }}</p>
      <ul>
        @for (id of ids; track id) {
          <li [attr.data-testid]="'prereq-' + id" [attr.data-state]="state(id)">
            <span class="mark" [class]="'mark is-' + state(id)" aria-hidden="true">
              <app-icon [name]="icon(id)" [size]="16" />
            </span>
            <div class="text">
              <p class="label">
                {{ i18n.t('experience.start.prereq.' + id + '.label') }}
                <span class="sr-only">{{ i18n.t('experience.start.prereq.state.' + state(id)) }}</span>
              </p>
              <p class="detail">{{ detail(id) }}</p>
              @switch (state(id)) {
                @case ('error') {
                  <button type="button" class="ck-btn ck-btn-quiet ck-btn--sm" (click)="reload(id)">
                    {{ i18n.t('common.retry') }}
                  </button>
                }
                @case ('missing') {
                  @switch (id) {
                    @case ('work') {
                      @if (isAdmin() && settingsLink(); as link) {
                        <a class="ck-btn ck-btn-quiet ck-btn--sm" [routerLink]="link">{{ i18n.t('experience.start.prereq.work.fix') }}</a>
                      }
                    }
                    @case ('model') {
                      <a class="ck-btn ck-btn-quiet ck-btn--sm" [navLink]="{ surface: 'resources' }">
                        {{ i18n.t(modelPortalOpen() ? 'experience.start.prereq.model.fix' : 'experience.start.prereq.model.fix_portal') }}
                      </a>
                    }
                    @case ('collection') {
                      <a class="ck-btn ck-btn-quiet ck-btn--sm" [navLink]="{ surface: 'knowledge' }">{{ i18n.t('experience.start.prereq.collection.fix') }}</a>
                    }
                    @case ('system') {
                      <a class="ck-btn ck-btn-quiet ck-btn--sm" [navLink]="{ surface: 'systems' }">{{ i18n.t('experience.start.prereq.system.fix') }}</a>
                    }
                  }
                }
              }
            </div>
          </li>
        }
      </ul>
    </section>
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .prereq { padding: var(--ck-space-4); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-panel); }
    h2 { margin: 0; font-size: 16px; font-weight: 600; color: var(--ck-fg-1); }
    .lede { margin: var(--ck-space-1) 0 var(--ck-space-3); font-size: 13px; color: var(--ck-fg-3); line-height: 1.5; }
    ul { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--ck-space-3); }
    li { display: flex; gap: var(--ck-space-3); align-items: flex-start; }
    .mark { flex: none; display: inline-flex; width: 24px; height: 24px; align-items: center; justify-content: center; border-radius: var(--ck-radius-sm); }
    .mark.is-ok { color: var(--ck-status-ok-fg); background: var(--ck-status-ok-bg); }
    .mark.is-missing { color: var(--ck-status-warn-fg); background: var(--ck-status-warn-bg); }
    .mark.is-error { color: var(--ck-status-neg-fg); background: var(--ck-status-neg-bg); }
    .mark.is-loading { color: var(--ck-fg-3); background: var(--ck-bg-panel-hi); }
    .text { min-width: 0; display: grid; gap: var(--ck-space-1); justify-items: start; }
    .label { margin: 0; font-size: 14px; font-weight: 600; color: var(--ck-fg-1); }
    .detail { margin: 0; font-size: 13px; color: var(--ck-fg-2); line-height: 1.5; }
    .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  `],
})
export class StartPrerequisitesComponent {
  readonly i18n = inject(I18nService);
  private readonly workspace = inject(WorkspaceService);
  private readonly api = inject(StartApiService);

  readonly ids = PREREQUISITES;
  readonly isAdmin = this.workspace.isAdmin;
  readonly modelPortalOpen = this.workspace.modelPortalEnabled;
  readonly settingsLink = computed(() => {
    const slug = this.workspace.currentSlug();
    return slug ? ['/workspace', slug, 'settings'] : null;
  });

  private readonly counts = signal<Partial<Record<'model' | 'collection' | 'system', number>>>({});
  private readonly failed = signal<Partial<Record<'model' | 'collection' | 'system', boolean>>>({});

  readonly states = computed<Record<PrerequisiteId, PrerequisiteState>>(() => {
    const counts = this.counts();
    const failed = this.failed();
    const current = this.workspace.current();
    return {
      work: this.workspace.experienceV1Enabled() ? 'ok' : 'missing',
      model: countState(counts.model ?? null, !!failed.model),
      collection: countState(counts.collection ?? null, !!failed.collection),
      system: countState(counts.system ?? null, !!failed.system),
      publish: canReleaseExperienceStudio(current?.role_template, current?.role, this.workspace.isAdmin()) ? 'ok' : 'missing',
    };
  });

  constructor() {
    this.reload('model');
    this.reload('collection');
    this.reload('system');
  }

  state(id: PrerequisiteId): PrerequisiteState {
    return this.states()[id];
  }

  icon(id: PrerequisiteId): string {
    return ICON[this.state(id)];
  }

  detail(id: PrerequisiteId): string {
    const state = this.state(id);
    if (state === 'loading') return this.i18n.t('experience.start.prereq.state.loading');
    if (state === 'error') return this.i18n.t('experience.start.prereq.unknown');
    if (id === 'model' && state === 'missing' && !this.modelPortalOpen()) {
      return this.i18n.t('experience.start.prereq.model.missing_portal');
    }
    if (id === 'work' && state === 'missing' && !this.isAdmin()) {
      return this.i18n.t('experience.start.prereq.work.missing_member');
    }
    const count = id === 'collection' || id === 'system' ? this.counts()[id] ?? 0 : 0;
    return this.i18n.t(`experience.start.prereq.${id}.${state}`, { count });
  }

  reload(id: PrerequisiteId): void {
    if (id !== 'model' && id !== 'collection' && id !== 'system') return;
    const scope = this.workspace.captureRequestScope();
    const slug = scope.workspaceSlug;
    this.counts.update((rows) => { const next = { ...rows }; delete next[id]; return next; });
    this.failed.update((rows) => ({ ...rows, [id]: false }));
    const request: Observable<number> = id === 'model'
      ? this.api.skills(slug).pipe(map((skills) => (selectAutomationSkill(skills) ? 1 : 0)))
      : id === 'collection'
        ? this.api.collectionCount(slug)
        : this.api.publishedSystemCount(slug);
    request.subscribe({
      next: (value) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.counts.update((rows) => ({ ...rows, [id]: value }));
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.failed.update((rows) => ({ ...rows, [id]: true }));
      },
    });
  }
}
