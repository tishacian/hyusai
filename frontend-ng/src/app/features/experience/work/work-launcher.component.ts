import { NgStyle } from '@angular/common';
import { ThemeService } from '@app/core/theme.service';
import { appearanceStyles } from '@app/core/brand-appearance';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { NavLinkDirective } from '@app/shared/cockpit';
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

@Component({
  selector: 'app-work-launcher',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgStyle, RouterLink, EmptyStateComponent, AdoptionJourneyComponent, NavLinkDirective, WorkBarComponent],
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
          <div>
            <p class="xp-work-eyebrow">{{ i18n.t('experience.work.title') }}</p>
            <h1 id="work-launcher-title">{{ i18n.t('experience.work.welcome') }}</h1>
            @if (state() === 'ready') {
              <p [attr.aria-live]="hasQuery() ? 'polite' : null">
                {{ i18n.t(
                  hasQuery() ? 'experience.work.search.count' : 'experience.work.home.count',
                  { n: items().length }
                ) }}
              </p>
            }
          </div>
        </div>

        @if (adoption.enabled()) {
          <nav class="adoption-work-links" [attr.aria-label]="i18n.t('experience.adoption.help')">
            @if (!profile.effective().active || profile.isBusinessAllowedPath('/knowledge')) {<a [navLink]="{surface:'knowledge'}">{{i18n.t('experience.adoption.documents')}}</a>}
            @if (!profile.effective().active || profile.isBusinessAllowedPath('/steering/review-queue')) {<a [navLink]="{surface:'review-queue',lens:'steer'}">{{i18n.t('experience.adoption.tasks')}}</a>}
            <a [navLink]="{leaf:'help-guide',params:{guideId:'start'}}">{{i18n.t('experience.adoption.help')}}</a>
          </nav>
          @if (!adoption.progress()?.dismissed) { <app-adoption-journey /> }
          @else { <a [routerLink]="['/work','getting-started']">{{ i18n.t('experience.adoption.resume') }}</a> }
        }
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
            @if (items().length > 0) {
              <div class="xp-work-grid">
                @for (item of items(); track item.experience.id) {
                  <a class="xp-work-card" [routerLink]="launchHref(item)">
                    <div class="xp-work-card-head">
                      <span class="xp-work-app-icon" aria-hidden="true">{{ emblem(item) }}</span>
                      <span
                        class="xp-work-status"
                        [class.xp-work-status-live]="item.channel === 'live'"
                      >
                        {{ i18n.t(item.channel === 'live' ? 'experience.work.status.live' : 'experience.work.status.pilot') }}
                      </span>
                    </div>
                    <h2>{{ identity(item).name }}</h2>
                    <p>{{ identity(item).description || patternLabel(item.experience.pattern) }}</p>
                    <span class="xp-work-open">{{ i18n.t('experience.work.open') }} →</span>
                  </a>
                }
              </div>
            }
            @if (jobs().length > 0) {
              <h2>{{ i18n.t('experience.work.automation.section') }}</h2>
              <div class="xp-work-automation">
                @for (job of jobs(); track job.job.system_id) {
                  <a class="xp-work-automation-card" [routerLink]="['/work/automation', job.job.system_id]">
                    <h2>{{ job.job.name }}</h2>
                    <p>{{ job.objective.text || i18n.t('flow.automation.work.objective.absent') }}</p>
                    <span class="xp-work-open">{{ i18n.t('experience.work.open') }} →</span>
                  </a>
                }
              </div>
            }
          }
        }
      </section>
    </div>
  `,
})
export class WorkLauncherComponent {
  readonly adoption = inject(AdoptionService);
  readonly profile = inject(NavigationProfileService);
  private readonly api = inject(WorkApiService);
  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);
  readonly workspace = inject(WorkspaceService);
  readonly theme = inject(ThemeService);
  readonly brandStyles = computed(() => {
    const brand = this.workspace.current()?.settings?.['platform_brand'] as Record<string, unknown> | undefined;
    return appearanceStyles(brand?.['appearance'], 'light');
  });
  readonly i18n = inject(I18nService);

  readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  readonly allItems = signal<WorkCatalogItem[]>([]);
  readonly jobs = signal<WorkAutomationJob[]>([]);
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
      this.jobs.set(result.jobs);
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
}
