import { NgStyle, NgTemplateOutlet } from '@angular/common';
import { appearanceStyles } from '@app/core/brand-appearance';
import { AdoptionService } from '@app/core/adoption.service';
import { AdoptionJourneyComponent } from './adoption-journey.component';
import { WorkBarComponent } from './work-bar.component';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, ElementRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { NavLinkDirective } from '@app/shared/cockpit/nav-link.directive';
import { I18nService } from '@app/core/i18n.service';
import { focusAfterRoute, navigationFocusFromState } from '@app/core/route-focus';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkApiService, type WorkAutomationJob } from './work-api.service';
import {
  canEditExperience,
  catalogLaunchHref,
  isNawaLiveLaunch,
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
import {
  agePhrase,
  homeQueue,
  homeTiles,
  homeTitle,
  homeWaitingTotal,
  isPrToPoDecision,
  prToPoMeta,
  receiptPhrases,
  shortId,
  type HomeTile,
  type HomeWork,
  type Phrase,
  type QueueItem,
  type WorkHome,
} from './work-home.vm';

/** PR to PO decisions enriched with the L32 receipt: one Run read each, at most. */
const ENRICHED_DECISIONS = 3;

@Component({
  selector: 'app-work-launcher',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgStyle, NgTemplateOutlet, RouterLink, EmptyStateComponent, AdoptionJourneyComponent, WorkBarComponent, NavLinkDirective],
  styleUrls: ['./work.scss', './work-home.scss'],
  template: `
    <div class="xp-work xp-work-launcher" data-brand-scope [attr.data-theme]="theme.resolved()" [ngStyle]="brandStyles()">
      <app-work-bar
        [showSearch]="true"
        [searchQuery]="query()"
        [creatorHref]="canEdit() ? studioLink : null"
        creatorLabelKey="experience.work.studio"
        (searchChange)="query.set($event)"
      />
      <section class="xp-work-main xp-work-home" role="main" aria-labelledby="work-launcher-title">
        <p class="sr-only" role="status" aria-live="polite">{{ exitAnnouncement() }}</p>
        <div class="xp-home" [class.xp-home-ready]="state() !== 'loading'">
          <div class="xp-home-primary">
            <header class="xp-home-head">
              <p class="xp-home-eyebrow">{{ i18n.t('experience.work.home.eyebrow') }}</p>
              <h1 id="work-launcher-title">{{ titleText() }}</h1>
              @if (state() === 'ready' && !hasQuery() && home()) {
                <p class="xp-home-lede">
                  {{ i18n.t(waitingTotal() > 0 ? 'experience.work.home.lede.busy' : 'experience.work.home.lede.calm') }}
                </p>
              }
              @if (state() === 'ready' && hasQuery()) {
                <p class="xp-home-lede" aria-live="polite">
                  {{ i18n.t('experience.work.search.count', { n: items().length + jobs().length }) }}
                </p>
              }
            </header>

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
                @if (!hasQuery()) {
                  @if (tiles().length) {
                    <ul class="xp-home-tiles" role="list" [attr.aria-label]="i18n.t('experience.work.home.tiles')">
                      @for (tile of tiles(); track tile.id) {
                        <li>
                          @if (tile.target === 'apps') {
                            <a class="xp-home-tile" [routerLink]="[]" fragment="work-all-apps" (click)="revealApps($event)">
                              <ng-container [ngTemplateOutlet]="tileBody" [ngTemplateOutletContext]="{ $implicit: tile }" />
                            </a>
                          } @else if (tile.target && tile.target.kind === 'review') {
                            <a
                              class="xp-home-tile"
                              [class.xp-home-tile-lead]="tile.emphasis"
                              [navLink]="{ surface: 'review-queue', params: { decision: tile.target.decisionId } }"
                            >
                              <ng-container [ngTemplateOutlet]="tileBody" [ngTemplateOutletContext]="{ $implicit: tile }" />
                            </a>
                          } @else if (tile.target) {
                            <a class="xp-home-tile" [class.xp-home-tile-lead]="tile.emphasis" [routerLink]="tile.target.url">
                              <ng-container [ngTemplateOutlet]="tileBody" [ngTemplateOutletContext]="{ $implicit: tile }" />
                            </a>
                          } @else {
                            <div class="xp-home-tile xp-home-tile-static">
                              <ng-container [ngTemplateOutlet]="tileBody" [ngTemplateOutletContext]="{ $implicit: tile }" />
                            </div>
                          }
                        </li>
                      }
                    </ul>
                  }

                  <section class="xp-home-panel xp-home-queue" aria-labelledby="work-home-queue-title">
                    <div class="xp-home-panel-head">
                      <h2 id="work-home-queue-title">{{ i18n.t('experience.work.home.queue.title') }}</h2>
                    </div>
                    @if (homeState() === 'error') {
                      <div class="xp-home-note" role="alert">
                        <p>{{ i18n.t('experience.work.home.queue.unavailable') }}</p>
                        <button type="button" class="xp-work-btn" (click)="load()">{{ i18n.t('common.retry') }}</button>
                      </div>
                    } @else if (queue().length === 0) {
                      <p class="xp-home-note">{{ i18n.t('experience.work.home.queue.empty') }}</p>
                    } @else {
                      <ul class="xp-home-list" role="list">
                        @for (item of queue(); track item.id) {
                          <li class="xp-home-item" [attr.data-kind]="item.kind">
                            <span class="xp-home-type">
                              <svg class="xp-home-glyph" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
                                @switch (item.kind) {
                                  @case ('decision') { <path d="M8 1.5 14.5 8 8 14.5 1.5 8Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" /> }
                                  @case ('review') { <path d="M3 13h3l7-7-3-3-7 7Zm6-8 3 3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" /> }
                                  @default { <path d="M2.5 2.5h11v11h-11Zm2.5 5.5 2 2 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" /> }
                                }
                              </svg>
                              {{ i18n.t('experience.work.home.type.' + item.kind) }}
                            </span>
                            <div class="xp-home-item-body">
                              <p class="xp-home-item-title">{{ itemTitle(item) }}</p>
                              @if (itemMeta(item); as meta) {
                                @if (meta.length || (item.kind === 'review' && item.runId)) {
                                  <p class="xp-home-meta">
                                    @for (part of meta; track $index) {
                                      @if ($index > 0) { <span aria-hidden="true"> · </span> }<span>{{ part }}</span>
                                    }
                                    @if (item.kind === 'review' && item.runId) {
                                      @if (meta.length) { <span aria-hidden="true"> · </span> }<span class="xp-home-id">{{ short(item.runId) }}</span>
                                    }
                                  </p>
                                }
                              }
                            </div>
                            <span class="xp-home-chip" [attr.data-kind]="item.kind">{{ i18n.t('experience.work.home.status.' + item.kind) }}</span>
                            @if (item.target; as target) {
                              @if (target.kind === 'review') {
                                <a
                                  class="xp-home-action"
                                  [navLink]="{ surface: 'review-queue', params: { decision: target.decisionId } }"
                                  [attr.aria-label]="actionLabel(item)"
                                >{{ i18n.t('experience.work.home.action.' + item.kind) }}</a>
                              } @else {
                                <a class="xp-home-action" [routerLink]="target.url" [attr.aria-label]="actionLabel(item)">
                                  {{ i18n.t('experience.work.home.action.' + item.kind) }}
                                </a>
                              }
                            }
                          </li>
                        }
                      </ul>
                      @if (hiddenCount() > 0) {
                        <p class="xp-home-note xp-home-more">
                          {{ hiddenCount() === 1
                            ? i18n.t('experience.work.home.queue.more.one')
                            : i18n.t('experience.work.home.queue.more.many', { n: hiddenCount() }) }}
                        </p>
                      }
                    }
                  </section>
                }

                <section class="xp-home-apps" aria-labelledby="work-all-apps">
                  @if (!hasQuery()) {
                    <div class="xp-home-apps-head">
                      <h2 id="work-all-apps" tabindex="-1">{{ i18n.t('experience.work.home.all_apps') }}</h2>
                      @if (items().length) { <p class="xp-work-summary">{{ summaryText() }}</p> }
                    </div>
                  } @else {
                    <h2 id="work-all-apps" class="sr-only" tabindex="-1">{{ i18n.t('experience.work.home.all_apps') }}</h2>
                  }
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
                      <h3 class="xp-home-section-title" [id]="'work-section-' + section.id">
                        {{ sectionLabel(section.id) }}
                        <sup aria-hidden="true">{{ section.items.length }}</sup>
                        <span class="sr-only">({{ section.items.length }})</span>
                      </h3>
                      <div class="xp-work-grid">
                        @for (item of section.items; track item.experience.id) {
                          @if (isNawaLive(item)) {
                            <a
                              class="xp-work-card xp-work-card-nawa"
                              [href]="launchHref(item)"
                              target="_blank"
                              rel="noopener noreferrer"
                              [attr.aria-describedby]="'nawa-exit-' + item.experience.id"
                              (click)="openNawaLive($event, item)"
                            >
                              <div class="xp-work-card-head">
                                <span class="xp-work-app-icon" aria-hidden="true">{{ emblem(item) }}</span>
                                <span class="xp-work-pattern">{{ patternLabel(item.experience.pattern) }}</span>
                                <span class="xp-work-status" [class.xp-work-status-live]="item.channel === 'live'">
                                  {{ i18n.t(item.channel === 'live' ? 'experience.work.status.live' : 'experience.work.status.pilot') }}
                                </span>
                              </div>
                              <h4>{{ identity(item).name }}</h4>
                              <p>{{ identity(item).description || patternLabel(item.experience.pattern) }}</p>
                              <span class="xp-work-open">{{ i18n.t('experience.work.open_nawa') }}</span>
                              <span [id]="'nawa-exit-' + item.experience.id" class="xp-work-exit-preview" role="tooltip">
                                <strong>{{ i18n.t('experience.work.open_nawa.announce.title') }}</strong>
                                <p>{{ i18n.t('experience.work.open_nawa.announce.body') }}</p>
                              </span>
                            </a>
                          } @else {
                            <a class="xp-work-card" [routerLink]="launchHref(item)">
                              <div class="xp-work-card-head">
                                <span class="xp-work-app-icon" aria-hidden="true">{{ emblem(item) }}</span>
                                <span class="xp-work-pattern">{{ patternLabel(item.experience.pattern) }}</span>
                                <span class="xp-work-status" [class.xp-work-status-live]="item.channel === 'live'">
                                  {{ i18n.t(item.channel === 'live' ? 'experience.work.status.live' : 'experience.work.status.pilot') }}
                                </span>
                              </div>
                              <h4>{{ identity(item).name }}</h4>
                              <p>{{ identity(item).description || patternLabel(item.experience.pattern) }}</p>
                              <span class="xp-work-open">{{ i18n.t('experience.work.open') }} →</span>
                            </a>
                          }
                        }
                      </div>
                    </section>
                  }
                  @if (jobs().length > 0) {
                    <section class="xp-work-section" aria-labelledby="work-section-automate">
                      <h3 class="xp-home-section-title" id="work-section-automate">
                        {{ i18n.t('experience.work.section.automate') }}
                        <sup aria-hidden="true">{{ jobs().length }}</sup>
                        <span class="sr-only">({{ jobs().length }})</span>
                      </h3>
                      <div class="xp-work-automation">
                        @for (job of jobs(); track job.job.system_id) {
                          <a class="xp-work-automation-card" [routerLink]="['/work/automation', job.job.system_id]">
                            <h4>{{ job.job.name }}</h4>
                            <p>{{ job.objective.text || i18n.t('flow.automation.work.objective.absent') }}</p>
                            <span class="xp-work-open">{{ i18n.t('experience.work.open') }} →</span>
                          </a>
                        }
                      </div>
                    </section>
                  }
                </section>
              }
            }
          </div>

          @if (state() === 'ready' && !hasQuery()) {
            <div class="xp-home-rail">
              <section class="xp-home-panel xp-home-agents" aria-labelledby="work-home-agents-title">
                <h2 id="work-home-agents-title">{{ i18n.t('experience.work.home.agents.title') }}</h2>
                <p class="xp-home-rail-sub">{{ i18n.t('experience.work.home.agents.week') }}</p>
                @if (homeState() === 'error') {
                  <p class="xp-home-note">{{ i18n.t('experience.work.home.agents.unavailable') }}</p>
                } @else if (agentWork().length === 0) {
                  <div class="xp-home-empty">
                    <p class="xp-home-empty-title">{{ i18n.t('experience.work.home.agents.empty.title') }}</p>
                    <p>{{ i18n.t('experience.work.home.agents.empty.body') }}</p>
                    @if (items().length || jobs().length) {
                      <a class="xp-home-inline-link" [routerLink]="[]" fragment="work-all-apps" (click)="revealApps($event)">
                        {{ i18n.t('experience.work.home.agents.empty.action') }}
                      </a>
                    }
                  </div>
                } @else {
                  <ul class="xp-home-work" role="list">
                    @for (work of agentWork(); track work.run_id) {
                      <li>
                        <svg class="xp-home-ring" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">
                          <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="3.5" />
                        </svg>
                        <div class="xp-home-work-body">
                          <p class="xp-home-work-name">{{ workName(work) }}</p>
                          @if (receipt(work); as parts) {
                            @if (parts.length) { <p class="xp-home-meta">{{ parts.join(' · ') }}</p> }
                          }
                          <p class="xp-home-ref">
                            <span>{{ i18n.t('experience.work.home.agents.ref') }}</span>
                            <a
                              class="xp-home-id"
                              [navLink]="{ type: 'run', ref: work.run_id }"
                              [attr.aria-label]="i18n.t('experience.work.home.agents.ref_label', { id: short(work.run_id), app: workName(work) })"
                            >{{ short(work.run_id) }}</a>
                          </p>
                        </div>
                      </li>
                    }
                  </ul>
                }
              </section>
              @if (adoption.enabled()) {
                <app-adoption-journey [compact]="true" />
              }
            </div>
          }
        </div>
      </section>
    </div>

    <ng-template #tileBody let-tile>
      <span class="xp-home-tile-count">{{ tile.count }}</span>
      <span class="xp-home-tile-label">{{ phrase(tile.label) }}</span>
      @if (tileNote(tile); as note) {
        <span class="xp-home-tile-note">{{ note }}</span>
      }
    </ng-template>
  `,
})
export class WorkLauncherComponent {
  readonly adoption = inject(AdoptionService);
  private readonly api = inject(WorkApiService);
  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);
  readonly workspace = inject(WorkspaceService);
  readonly theme = inject(ThemeService);
  readonly brandStyles = computed(() => {
    const brand = this.workspace.current()?.settings?.['platform_brand'] as Record<string, unknown> | undefined;
    return appearanceStyles(brand?.['appearance'], this.theme.resolved());
  });
  readonly i18n = inject(I18nService);

  readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  readonly allItems = signal<WorkCatalogItem[]>([]);
  readonly allJobs = signal<WorkAutomationJob[]>([]);
  /** L33 — `null` until loaded, or when the home could not be read. */
  readonly home = signal<WorkHome | null>(null);
  readonly homeState = signal<'loading' | 'ready' | 'error'>('loading');
  /** L32 receipt parts for PR to PO decisions, by Run id. */
  readonly decisionMeta = signal<Record<string, Phrase[]>>({});
  readonly now = signal(Date.now());
  readonly query = signal('');
  readonly hasQuery = computed(() => this.query().trim().length > 0);
  readonly studioLink = studioHref(null);
  readonly launchHref = catalogLaunchHref;
  readonly isNawaLive = isNawaLiveLaunch;
  readonly short = shortId;
  readonly exitAnnouncement = signal('');
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

  readonly queue = computed(() => homeQueue(this.home()));
  readonly waitingTotal = computed(() => homeWaitingTotal(this.home()));
  readonly hiddenCount = computed(() => Math.max(0, this.waitingTotal() - this.queue().length));
  readonly agentWork = computed(() => this.home()?.agent_work?.items ?? []);
  readonly summary = computed(() => launcherSummary(this.items()));
  readonly tiles = computed((): HomeTile[] => {
    const catalogue = this.state() === 'ready' ? launcherSummary(this.allItems()) : null;
    return homeTiles(this.home(), catalogue, this.queue(), this.now());
  });

  /** Without the home payload, the L17 title still says what waits. */
  readonly titleModel = computed((): LauncherTitleModel =>
    launcherTitleModel(decisionSources(this.allItems(), this.allJobs())),
  );
  readonly titleText = computed(() => {
    if (this.home()) {
      const phrase = homeTitle(this.waitingTotal());
      return phrase ? this.phrase(phrase) : this.i18n.t('experience.work.apps');
    }
    const title = this.titleModel();
    if (title.kind === 'one_app') {
      return this.i18n.t('experience.work.decisions.title.app', { n: title.count, app: title.appName });
    }
    if (title.kind === 'many_apps') {
      return this.i18n.t('experience.work.decisions.title.apps', { n: title.count, k: title.appCount });
    }
    return this.i18n.t('experience.work.apps');
  });
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
    this.homeState.set('loading');
    forkJoin([this.api.listExperiences(), this.api.home()])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(([result, home]) => {
        this.now.set(Date.now());
        if (home.kind === 'ok') {
          this.home.set(home.body);
          this.homeState.set('ready');
        } else {
          this.home.set(null);
          this.homeState.set('error');
        }
        if (result.kind !== 'ok') {
          this.state.set('error');
          queueMicrotask(() => this.focusRouteTarget());
          return;
        }
        // One app and nothing waiting: go straight to it, as before L33.
        const idle = home.kind === 'ok' && homeWaitingTotal(home.body) === 0
          && !(home.body.agent_work?.items?.length);
        if (result.items.length === 1 && result.jobs.length === 0 && idle && !this.adoption.enabled()) {
          void this.router.navigateByUrl(catalogLaunchHref(result.items[0]!));
          return;
        }
        this.allItems.set(result.items);
        this.allJobs.set(result.jobs);
        this.state.set('ready');
        this.enrichDecisions();
        queueMicrotask(() => this.focusRouteTarget());
      });
  }

  /** PR to PO decisions carry the L32 receipt: amount, budget check, SAP reads. */
  private enrichDecisions(): void {
    const targets = this.queue().filter(isPrToPoDecision).slice(0, ENRICHED_DECISIONS);
    for (const item of targets) {
      if (!item.runId) continue;
      const runId = item.runId;
      this.api.run(runId).pipe(takeUntilDestroyed(this.destroyRef)).subscribe((run) => {
        const parts = prToPoMeta(run, this.i18n.locale());
        if (parts.length) this.decisionMeta.update((current) => ({ ...current, [runId]: parts }));
      });
    }
  }

  private focusRouteTarget(): void {
    focusAfterRoute(this.host.nativeElement, {
      focus: navigationFocusFromState(
        this.router.lastSuccessfulNavigation?.extras?.state
          ?? (globalThis.history?.state as Record<string, unknown> | null),
      ),
    });
  }

  phrase(value: Phrase): string {
    return this.i18n.t(value.key, value.params);
  }

  tileNote(tile: HomeTile): string | null {
    if (!tile.note) return null;
    if (tile.noteAge) return this.i18n.t(tile.note.key, { age: this.phrase(tile.noteAge) });
    return this.phrase(tile.note);
  }

  itemTitle(item: QueueItem): string {
    if (item.title) return item.title;
    if (item.kind === 'result') return item.source?.name || this.i18n.t('experience.work.home.result.title');
    return this.i18n.t(`experience.work.home.untitled.${item.kind}`);
  }

  itemMeta(item: QueueItem): string[] {
    const parts: string[] = [];
    const sourceName = item.source?.name?.trim();
    if (sourceName && !(item.kind === 'result' && !item.title)) parts.push(sourceName);
    if (item.kind === 'decision' && item.runId) {
      for (const phrase of this.decisionMeta()[item.runId] ?? []) parts.push(this.phrase(phrase));
    }
    if (item.kind === 'result') {
      for (const phrase of receiptPhrases(item.receipt, this.i18n.locale())) parts.push(this.phrase(phrase));
    }
    const age = agePhrase(item.at, this.now());
    if (age) {
      const key = item.kind === 'result' ? 'experience.work.home.finished' : 'experience.work.home.waiting';
      parts.push(this.i18n.t(key, { age: this.phrase(age) }));
    }
    return parts;
  }

  actionLabel(item: QueueItem): string {
    return this.i18n.t('experience.work.home.action.label', {
      action: this.i18n.t(`experience.work.home.action.${item.kind}`),
      title: this.itemTitle(item),
    });
  }

  workName(work: HomeWork): string {
    return work.source?.name?.trim() || this.i18n.t('experience.work.home.agents.untitled');
  }

  receipt(work: HomeWork): string[] {
    return receiptPhrases(work.receipt, this.i18n.locale()).map((phrase) => this.phrase(phrase));
  }

  /** In-page link to the catalogue: scroll there and move focus to its heading. */
  revealApps(event: Event): void {
    const heading = this.host.nativeElement.querySelector('#work-all-apps') as HTMLElement | null;
    if (!heading) return;
    event.preventDefault();
    heading.scrollIntoView({ block: 'start' });
    heading.focus({ preventScroll: true });
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

  /** Announce the leave-Work preview, then open Nawa in a new tab (L18 / n1). */
  openNawaLive(event: Event, item: WorkCatalogItem): void {
    event.preventDefault();
    this.exitAnnouncement.set(this.i18n.t('experience.work.open_nawa.announce.body'));
    const href = catalogLaunchHref(item);
    window.open(href, '_blank', 'noopener,noreferrer');
  }
}
