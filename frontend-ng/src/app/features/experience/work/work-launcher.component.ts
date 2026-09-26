import { NgStyle } from '@angular/common';
import { appearanceStyles } from '@app/core/brand-appearance';
import { AdoptionService } from '@app/core/adoption.service';
import { AdoptionJourneyComponent } from './adoption-journey.component';
import { WorkBarComponent } from './work-bar.component';
import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { I18nService } from '@app/core/i18n.service';
import { focusAfterRoute, navigationFocusFromState } from '@app/core/route-focus';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkApiService, type WorkAutomationJob } from './work-api.service';
import {
  canEditExperience,
  catalogLaunchHref,
  studioHref,
  workEmblem,
  workIdentity,
  type WorkCatalogItem,
  type WorkIdentity,
} from './work-catalog';
import {
  decisionSources,
  groupLauncherApps,
  launcherSummary,
  launcherTitleModel,
  type LauncherSectionId,
  type LauncherTitleModel,
} from './work-launcher.vm';

@Component({
  selector: 'app-work-launcher',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgStyle, RouterLink, EmptyStateComponent, AdoptionJourneyComponent, WorkBarComponent],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work xp-work-launcher" data-brand-scope data-theme="light" [ngStyle]="brandStyles()">
      <app-work-bar
        [showSearch]="true"
        [searchQuery]="query()"
        [creatorHref]="canEdit() ? studioLink : null"
        creatorLabelKey="experience.work.studio"
        (searchChange)="query.set($event)"
      />
      <section class="xp-work-main xp-work-home" role="main" aria-labelledby="work-launcher-title">
        <div class="xp-work-intro">
          <div class="xp-work-intro-copy">
            <h1 id="work-launcher-title">{{ titleText() }}</h1>
            @if (titleModel(); as title) {
              @if (title.kind !== 'fixed') {
                <div class="xp-work-decision-cta">
                  <a class="xp-work-btn xp-work-btn-primary" [routerLink]="title.href">
                    {{ i18n.t('experience.work.decisions.treat') }}
                  </a>
                  <p>{{ i18n.t('experience.work.decisions.pause') }}</p>
                </div>
              }
            }
            @if (state() === 'ready' && !hasQuery()) {
              <p class="xp-work-summary">
                {{ summaryText() }}
              </p>
            }
            @if (state() === 'ready' && hasQuery()) {
              <p aria-live="polite">
                {{ i18n.t('experience.work.search.count', { n: items().length + jobs().length }) }}
              </p>
            }
          </div>
          @if (adoption.enabled()) {
            <app-adoption-journey [compact]="true" />
          }
        </div>

        @switch (state()) {
          @case ('loading') {
            <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('common.loading')" />
          }
          @case ('error') {
            <app-empty-state
              icon="alert-triangle"
              size="lg"
              [title]="i18n.t('experience.work.unavailable.title')"
              [description]="i18n.t('experience.work.unavailable.body')"
            >
              <button type="button" class="xp-work-btn" (click)="load()">{{ i18n.t('common.retry') }}</button>
            </app-empty-state>
          }
          @default {
            @if (items().length === 0 && jobs().length === 0) {
              <app-empty-state
                icon="layers"
                size="lg"
                [title]="i18n.t(hasQuery() ? 'experience.work.search.empty.title' : 'experience.work.empty.title')"
                [description]="i18n.t(hasQuery() ? 'experience.work.search.empty.description' : 'experience.work.empty.description')"
              >
                @if (hasQuery()) { <button type="button" class="xp-work-btn" (click)="query.set('')">{{ i18n.t('experience.adoption.clear') }}</button> }
                @if (canEdit() && !hasQuery()) {
                  <a class="xp-work-btn xp-work-btn-primary" [routerLink]="studioLink">
                    {{ i18n.t('experience.work.empty.create') }}
                  </a>
                }
              </app-empty-state>
            }
            @for (section of appSections(); track section.id) {
              <section class="xp-work-section" [attr.aria-labelledby]="'work-section-' + section.id">
                <h2 [id]="'work-section-' + section.id">
                  {{ sectionLabel(section.id) }}
                  <sup aria-hidden="true">{{ section.items.length }}</sup>
                  <span class="sr-only">({{ section.items.length }})</span>
                </h2>
                <div class="xp-work-grid">
                  @for (item of section.items; track item.experience.id) {
                    <a class="xp-work-card" [routerLink]="launchHref(item)">
                      <div class="xp-work-card-head">
                        <span class="xp-work-app-icon" aria-hidden="true">{{ emblem(item) }}</span>
                        <span class="xp-work-pattern">{{ patternLabel(item.experience.pattern) }}</span>
                        <span
                          class="xp-work-status"
                          [class.xp-work-status-live]="item.channel === 'live'"
                        >
                          {{ i18n.t(item.channel === 'live' ? 'experience.work.status.live' : 'experience.work.status.pilot') }}
                        </span>
                      </div>
                      <h3>{{ identity(item).name }}</h3>
                      <p>{{ identity(item).description || patternLabel(item.experience.pattern) }}</p>
                      <span class="xp-work-open">{{ i18n.t('experience.work.open') }} →</span>
                    </a>
                  }
                </div>
              </section>
            }
            @if (jobs().length > 0) {
              <section class="xp-work-section" aria-labelledby="work-section-automate">
                <h2 id="work-section-automate">
                  {{ i18n.t('experience.work.section.automate') }}
                  <sup aria-hidden="true">{{ jobs().length }}</sup>
                  <span class="sr-only">({{ jobs().length }})</span>
                </h2>
                <div class="xp-work-automation">
                  @for (job of jobs(); track job.job.system_id) {
                    <a class="xp-work-automation-card" [routerLink]="['/work/automation', job.job.system_id]">
                      <h3>{{ job.job.name }}</h3>
                      <p>{{ job.objective.text || i18n.t('flow.automation.work.objective.absent') }}</p>
                      <span class="xp-work-open">{{ i18n.t('experience.work.open') }} →</span>
                    </a>
                  }
                </div>
              </section>
            }
          }
        }
      </section>
    </div>
  `,
})
export class WorkLauncherComponent {
  readonly adoption = inject(AdoptionService);
  private readonly api = inject(WorkApiService);
  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);
  readonly workspace = inject(WorkspaceService);
  readonly brandStyles = computed(() => {
    const brand = this.workspace.current()?.settings?.['platform_brand'] as Record<string, unknown> | undefined;
    return appearanceStyles(brand?.['appearance'], 'light');
  });
  readonly i18n = inject(I18nService);

  readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  readonly allItems = signal<WorkCatalogItem[]>([]);
  readonly allJobs = signal<WorkAutomationJob[]>([]);
  readonly query = signal('');
  readonly hasQuery = computed(() => this.query().trim().length > 0);
  readonly studioLink = studioHref(null);
  readonly launchHref = catalogLaunchHref;
  readonly items = computed(() => {
    const query = this.query().trim().toLocaleLowerCase(this.i18n.locale());
    if (!query) return this.allItems();
    return this.allItems().filter((item) =>
      `${this.identity(item).name} ${this.identity(item).description} ${item.experience.pattern}`
        .toLocaleLowerCase(this.i18n.locale())
        .includes(query),
    );
  });
  readonly jobs = computed(() => {
    const query = this.query().trim().toLocaleLowerCase(this.i18n.locale());
    if (!query) return this.allJobs();
    return this.allJobs().filter((job) =>
      `${job.job.name ?? ''} ${job.objective.text ?? ''}`
        .toLocaleLowerCase(this.i18n.locale())
        .includes(query),
    );
  });
  readonly titleModel = computed((): LauncherTitleModel =>
    launcherTitleModel(decisionSources(this.allItems(), this.allJobs())),
  );
  readonly titleText = computed(() => {
    const title = this.titleModel();
    if (title.kind === 'one_app') {
      return this.i18n.t('experience.work.decisions.title.app', {
        n: title.count,
        app: title.appName,
      });
    }
    if (title.kind === 'many_apps') {
      return this.i18n.t('experience.work.decisions.title.apps', {
        n: title.count,
        k: title.appCount,
      });
    }
    return this.i18n.t('experience.work.apps');
  });
  readonly summary = computed(() => launcherSummary(this.items()));
  readonly summaryText = computed(() => {
    const { total, live, pilot } = this.summary();
    if (total === 0) return this.i18n.t('experience.work.apps');
    return this.i18n.t('experience.work.home.summary', { n: total, live, pilot });
  });
  readonly appSections = computed(() => groupLauncherApps(this.items()));

  readonly canEdit = computed(() =>
    this.workspace.experienceStudioV1Enabled()
    && canEditExperience(this.workspace.current()?.role_template, this.workspace.isAdmin()),
  );

  constructor() {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.api.listExperiences().subscribe((result) => {
      if (result.kind !== 'ok') {
        this.state.set('error');
        queueMicrotask(() => this.focusRouteTarget());
        return;
      }
      if (result.items.length === 1 && !this.adoption.enabled()) {
        void this.router.navigateByUrl(catalogLaunchHref(result.items[0]!));
        return;
      }
      this.allItems.set(result.items);
      this.allJobs.set(result.jobs);
      this.state.set('ready');
      queueMicrotask(() => this.focusRouteTarget());
    });
  }

  private focusRouteTarget(): void {
    focusAfterRoute(this.host.nativeElement, {
      focus: navigationFocusFromState(
        this.router.lastSuccessfulNavigation?.extras?.state
          ?? (globalThis.history?.state as Record<string, unknown> | null),
      ),
    });
  }

  identity(item: WorkCatalogItem): WorkIdentity {
    return workIdentity(item.experience, item.release);
  }

  emblem(item: WorkCatalogItem): string {
    return workEmblem(this.identity(item));
  }

  patternLabel(pattern: string): string {
    const key = `experience.work.pattern.${pattern}`;
    const label = this.i18n.t(key);
    return label === key ? this.i18n.t('experience.work.pattern.other') : label;
  }

  sectionLabel(id: LauncherSectionId): string {
    return this.i18n.t(`experience.work.section.${id}`);
  }
}
