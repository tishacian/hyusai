import { appearanceLogo, appearanceStyles, brandAppearance, type BrandAppearance } from '@app/core/brand-appearance';
import { AdoptionService } from '@app/core/adoption.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { NgComponentOutlet, NgStyle } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink, type UrlTree } from '@angular/router';
import { Subscription, timer } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { NavLinkDirective } from '@app/shared/cockpit';
import { I18nService, type Locale } from '@app/core/i18n.service';
import { navigationSurfaceUrl } from '@app/core/navigation.catalog';
import { canEditExperienceStudio } from '../experience-access';
import { WorkspaceService } from '@app/core/workspace.service';
import { type Run } from '@app/core/canonical-api.service';
import { ExperienceRuntimeService } from '../runtime/experience-runtime.service';
import {
  textFallback,
  type ExperienceDocument,
} from '../runtime/model';
import {
  experienceRenderer,
  type CertifiedExperienceRenderer,
} from '../runtime/renderer-registry';
import { WorkApiService } from './work-api.service';
import {
  canEditExperience,
  documentNeedsValidations,
  isInternalWorkHref,
  liveHref,
  studioHref,
  workPageHref,
  workTheme,
  workLocales,
  workEmblem,
  workIdentity,
  type WorkResolve,
} from './work-catalog';

const VALIDATIONS = 'validations';
const POLL_MS = 8000;

@Component({
  selector: 'app-work-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgStyle, RouterLink, NgComponentOutlet, EmptyStateComponent, NavLinkDirective],
  styleUrl: './work.scss',
  template: `
    <div
      class="xp-work"
      data-brand-scope
      [ngStyle]="brandStyles()"
      [attr.data-theme]="theme().mode"
      [style.--xp-app-accent]="appearance().accent || theme().accent || null"
      [style.--xp-on-accent]="brandStyles()['--xp-on-accent'] || theme().onAccent || null"
    >
      <header class="xp-work-bar">
        <div class="xp-work-brand-cluster">
          @if (brandLogo()) { <img class="xp-work-brand-image" [src]="brandLogo()" alt="" /> } @else { <span class="xp-work-app-icon" aria-hidden="true">{{ emblem() }}</span> }
          <div class="xp-work-brand">
            <a routerLink="/work">{{ i18n.t('experience.work.back') }}</a>
            <h1 id="work-app-title">{{ title() }}</h1>
            @if (description()) { <p>{{ description() }}</p> }
          </div>
        </div>
        @if (state() === 'ready') {
          <nav class="xp-work-nav" [attr.aria-label]="i18n.t('experience.work.pages')">
            @for (page of document().pages; track page.id) {
              <a
                [routerLink]="pageHref(page.id)"
                [attr.aria-current]="activePage() === page.id ? 'page' : null"
              >
                {{ pageTitle(page.title) }}
              </a>
            }
            @if (showValidations()) {
              <a
                [routerLink]="pageHref(validationsPage)"
                [attr.aria-current]="activePage() === validationsPage ? 'page' : null"
              >
                {{ i18n.t('experience.work.validations') }}
                @if (pending().length > 0) {
                  <span class="xp-work-badge">{{ pending().length }}</span>
                }
              </a>
            }
          </nav>
        }
        <div class="xp-work-actions">
          @if (adoption.enabled()) { <button type="button" class="xp-work-btn" (click)="companion.open({ pilot: true })">{{ i18n.t('experience.adoption.companion') }}</button> }
          @if (locales().length > 1) {
            <span class="xp-work-locales" role="group" [attr.aria-label]="i18n.t('experience.work.lang.label')">
              @for (locale of locales(); track locale) {
                <button
                  type="button"
                  class="xp-work-btn"
                  [attr.aria-pressed]="i18n.locale() === locale"
                  [class.xp-work-btn-primary]="i18n.locale() === locale"
                  (click)="i18n.setLocale(locale)"
                >
                  {{ i18n.t(locale === 'fr' ? 'experience.work.lang.fr' : 'experience.work.lang.en') }}
                </button>
              }
            </span>
          }
          @if (showCockpitLink()) {
            <a class="xp-work-link" [routerLink]="cockpitHref()">{{ i18n.t('nav.cockpit') }}</a>
            @if (adoption.enabled()) {
              @for (id of boundSystemIds(); track id) {
                <a class="xp-work-link" [navLink]="{ type: 'system', ref: id, lens: 'build', facet: 'design' }">{{ i18n.t('experience.adoption.inspect_design') }}</a>
              }
              <a class="xp-work-link" [navLink]="{ leaf: 'help-guide', ref: 'systems' }">{{ i18n.t('experience.adoption.build_guide') }}</a>
            }
          }
          @if (canEdit()) {
            <a class="xp-work-link" [routerLink]="studioLink()">{{ i18n.t('experience.work.edit_studio') }}</a>
          }
        </div>
      </header>
      <section
        #workMain
        class="xp-work-main"
        role="main"
        tabindex="-1"
        aria-labelledby="work-app-title"
        [attr.aria-busy]="state() === 'loading'"
      >
        <p class="sr-only" role="status" aria-live="polite">{{ announcement() }}</p>
        @switch (state()) {
          @case ('loading') {
            <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('common.loading')" />
          }
          @case ('missing') {
            <app-empty-state
              icon="layers"
              size="lg"
              [title]="i18n.t('experience.work.not_found.title')"
              [description]="i18n.t('experience.work.not_found.description')"
            />
          }
          @case ('unavailable') {
            <app-empty-state
              icon="alert-triangle"
              size="lg"
              [title]="i18n.t(pinMismatch() ? 'experience.work.pin.title' : 'experience.work.unavailable.title')"
              [description]="i18n.t(pinMismatch() ? 'experience.work.pin.body' : 'experience.work.unavailable.body')"
            >
              @if (canEdit()) {
                <a class="xp-work-link" [routerLink]="studioLink()">{{ i18n.t('experience.work.repair') }}</a>
              }
            </app-empty-state>
          }
          @default {
            @if (activePage() === validationsPage) {
              <section class="xp-work-hitl" [attr.aria-label]="i18n.t('experience.work.validations')">
                @if (decisionError()) {
                  <p class="xp-work-note" role="alert">{{ i18n.t('experience.work.validations.error') }}</p>
                }
                @if (validationState() === 'error') {
                  <div class="xp-work-note" role="alert">
                    <p>{{ i18n.t('experience.work.validations.load_error') }}</p>
                    <button type="button" class="xp-work-btn" (click)="retryValidations()">
                      {{ i18n.t('common.retry') }}
                    </button>
                  </div>
                } @else if (validationState() === 'loading' && pending().length === 0) {
                  <p class="xp-work-note" role="status">{{ i18n.t('experience.work.validations.loading') }}</p>
                } @else if (pending().length === 0) {
                  <app-empty-state
                    icon="inbox"
                    size="md"
                    [title]="i18n.t('experience.work.validations.empty')"
                  />
                }
                @for (run of pending(); track run.id) {
                  <article>
                    <h3>{{ run.hitl?.decision_title || run.hitl?.prompt || i18n.t('experience.work.validations.item') }}</h3>
                    @if (run.hitl?.prompt && run.hitl?.decision_title) {
                      <p>{{ run.hitl?.prompt }}</p>
                    }
                    <label>
                      {{ i18n.t('experience.work.validations.reason') }}
                      <textarea
                        [value]="reasons()[run.id]"
                        (input)="setReason(run.id, reasonValue($event))"
                      ></textarea>
                    </label>
                    <div class="xp-work-hitl-actions">
                      <button
                        type="button"
                        class="xp-work-btn xp-work-btn-primary"
                        [disabled]="decisionBusy().has(run.id)"
                        (click)="decide(run, 'accept')"
                      >
                        {{ i18n.t('experience.work.validations.approve') }}
                      </button>
                      <button
                        type="button"
                        class="xp-work-btn"
                        [disabled]="decisionBusy().has(run.id)"
                        (click)="decide(run, 'reject')"
                      >
                        {{ i18n.t('experience.work.validations.refuse') }}
                      </button>
                    </div>
                    @if (reasonError() === run.id) {
                      <p class="xp-work-note" role="alert">{{ i18n.t('experience.work.validations.reason_required') }}</p>
                    }
                  </article>
                }
              </section>
            } @else {
              @if (renderer(); as selectedRenderer) {
                <ng-container
                  [ngComponentOutlet]="selectedRenderer.host"
                  [ngComponentOutletInputs]="runtimeInputs()"
                />
              }
            }
          }
        }
      </section>
    </div>
  `,
})
export class WorkShellComponent {
  readonly adoption = inject(AdoptionService);
  readonly companion = inject(ChatOverlayService);
  @ViewChild('workMain') private workMain?: ElementRef<HTMLElement>;
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(WorkApiService);
  private readonly runtime = inject(ExperienceRuntimeService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);
  private validationWatch: Subscription | null = null;
  readonly i18n = inject(I18nService);

  readonly validationsPage = VALIDATIONS;
  readonly slug = signal('');
  private readonly requestedPage = signal<string | null>(null);
  readonly state = signal<'loading' | 'ready' | 'missing' | 'unavailable'>('loading');
  readonly title = signal('');
  readonly description = signal('');
  readonly emblem = signal('A');
  readonly renderer = signal<CertifiedExperienceRenderer | null>(null);
  readonly rawDocument = signal<unknown>({ pages: [] });
  readonly document = computed<ExperienceDocument>(() => {
    const renderer = this.renderer();
    return renderer
      ? renderer.localizeDocument(this.rawDocument(), this.i18n.locale())
      : { pages: [] };
  });
  readonly runtimeInputs = computed<Record<string, unknown>>(() => ({
    document: this.document(),
    pageId: this.activePage(),
    experienceSlug: this.slug(),
    mode: 'live',
  }));
  readonly theme = signal<{ mode: 'light' | 'dark'; accent: string; onAccent: string }>({
    mode: 'light',
    accent: '',
    onAccent: '',
  });
  readonly appearance = signal<BrandAppearance>({});
  readonly brandStyles = computed(() => appearanceStyles(this.appearance(), this.theme().mode));
  readonly brandLogo = computed(() => appearanceLogo(this.appearance(), this.theme().mode));
  readonly activePage = signal<string | null>(null);
  readonly locales = signal<Locale[]>([]);
  readonly pending = signal<Run[]>([]);
  readonly validationState = signal<'idle' | 'loading' | 'ready' | 'error'>('idle');
  readonly reasons = signal<Record<string, string>>({});
  readonly reasonError = signal<string | null>(null);
  readonly showValidations = signal(false);
  readonly pinMismatch = signal(false);
  readonly experienceId = signal<string | null>(null);
  readonly releaseId = signal<string | null>(null);
  readonly releaseNumber = signal<number | null>(null);
  readonly boundSystemIds = signal<string[]>([]);
  readonly announcement = signal('');
  readonly decisionBusy = signal<ReadonlySet<string>>(new Set());
  readonly decisionError = signal(false);

  readonly canEdit = computed(() =>
    this.workspace.experienceStudioV1Enabled()
    && canEditExperience(this.workspace.current()?.role_template, this.workspace.isAdmin()),
  );

  readonly showCockpitLink = computed(() => {
    const current = this.workspace.current();
    return canEditExperienceStudio(current?.role_template, current?.role, this.workspace.isAdmin())
      || canEditExperience(current?.role_template, this.workspace.isAdmin());
  });

  cockpitHref(): string {
    return this.workspace.mode() === 'builder'
      ? navigationSurfaceUrl('create')
      : navigationSurfaceUrl('hypervisor');
  }

  constructor() {
    let generation = 0;
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      const slug = params.get('slug') ?? '';
      this.requestedPage.set(params.get('pageId'));
      if (slug === this.slug() && this.state() === 'ready') {
        this.activateRequestedPage(true);
        return;
      }
      this.resetExperienceState();
      this.slug.set(slug);
      this.state.set('loading');
      const request = ++generation;
      this.api.resolve(slug).subscribe((result) => {
        if (request !== generation) return;
        if (result.kind !== 'ok') {
          this.state.set(result.kind);
          this.title.set(this.i18n.t('experience.work.title'));
          return;
        }
        this.open(result.body);
      });
    });
  }

  studioLink(): UrlTree {
    const requested = this.activePage() ?? this.requestedPage();
    const pageId = requested === VALIDATIONS ? null : requested;
    const returnTo = this.slug()
      ? workPageHref(this.slug(), requested)
      : null;
    return this.router.parseUrl(studioHref(this.experienceId(), pageId, returnTo, this.releaseId(), this.releaseNumber()));
  }

  pageHref(pageId: string): string {
    return workPageHref(this.slug(), pageId);
  }

  pageTitle(title: ExperienceDocument['pages'][number]['title']): string {
    return textFallback(title);
  }

  reasonValue(event: Event): string {
    return (event.target as HTMLTextAreaElement).value;
  }

  setReason(runId: string, value: string): void {
    this.reasons.update((current) => ({ ...current, [runId]: value }));
    if (this.reasonError() === runId) this.reasonError.set(null);
  }

  decide(run: Run, action: 'accept' | 'reject'): void {
    if (this.decisionBusy().has(run.id)) return;
    const note = (this.reasons()[run.id] ?? '').trim();
    if (action === 'reject' && !note) {
      this.reasonError.set(run.id);
      return;
    }
    const title = run.hitl?.decision_title || run.hitl?.prompt || this.i18n.t('experience.work.validations.item');
    this.decisionBusy.update((current) => new Set([...current, run.id]));
    this.decisionError.set(false);
    this.api.decide(run, action, note).subscribe((updated) => {
      this.decisionBusy.update((current) => {
        const next = new Set(current);
        next.delete(run.id);
        return next;
      });
      if (!updated) {
        this.decisionError.set(true);
        this.announcement.set(this.i18n.t('experience.work.validations.error'));
        return;
      }
      this.runtime.resumeAfterDecision(updated);
      this.pending.update((rows) => rows.filter((item) => item.id !== run.id));
      this.announcement.set(
        this.i18n.t(
          action === 'accept'
            ? 'experience.work.validations.approved'
            : 'experience.work.validations.refused',
          { title },
        ),
      );
      queueMicrotask(() => {
        const next = this.workMain?.nativeElement.querySelector<HTMLElement>('.xp-work-hitl article button');
        (next ?? this.workMain?.nativeElement)?.focus();
      });
    });
  }

  private open(body: WorkResolve): void {
    this.boundSystemIds.set([...new Set((body.release.bindings_snapshot || [])
      .map(binding => binding['system_id']).filter((id): id is string => typeof id === 'string' && !!id))]);
    this.experienceId.set(body.experience.id);
    this.releaseId.set(body.release.id);
    this.releaseNumber.set(body.release.release_number ?? null);
    const identity = workIdentity(body.experience, body.release);
    this.title.set(identity.name);
    this.description.set(identity.description);
    this.emblem.set(workEmblem(identity));
    const renderer = experienceRenderer(body.release.renderer_version);
    if (!renderer) {
      this.pinMismatch.set(true);
      this.rawDocument.set(body.release.pages);
      this.state.set('unavailable');
      return;
    }
    const href = liveHref(body.release.theme) ?? liveHref(body.experience.theme);
    if (href && !isInternalWorkHref(href, body.experience.slug)) {
      void this.router.navigateByUrl(href);
      return;
    }
    const document = renderer.localizeDocument(body.release.pages, this.i18n.locale());
    if (document.pages.length === 0) {
      this.state.set('unavailable');
      return;
    }
    const locales = workLocales(body.release.languages ?? body.experience.languages);
    if (locales.length === 1) this.i18n.setLocale(locales[0]!);
    const needsQueue = documentNeedsValidations(document.pages, body.experience.pattern);
    this.renderer.set(renderer);
    this.rawDocument.set(body.release.pages);
    this.theme.set(workTheme(body.release.theme ?? body.experience.theme));
    this.appearance.set(brandAppearance((body.release.theme ?? body.experience.theme)?.['appearance']));
    this.locales.set(locales);
    this.showValidations.set(needsQueue);
    this.state.set('ready');
    this.activateRequestedPage(true);
    this.watchValidations(body.experience.slug, needsQueue);
  }

  private activateRequestedPage(replaceInvalid: boolean): void {
    const requested = this.requestedPage();
    const pages = this.document().pages;
    const first = pages[0]?.id;
    if (!first) return;
    const active =
      requested === VALIDATIONS && this.showValidations()
        ? VALIDATIONS
        : pages.some((page) => page.id === requested)
          ? requested!
          : first;
    this.activePage.set(active);
    const page = pages.find((item) => item.id === active);
    this.announcement.set(
      active === VALIDATIONS
        ? this.i18n.t('experience.work.validations')
        : page ? this.pageTitle(page.title) : '',
    );
    queueMicrotask(() => this.workMain?.nativeElement.focus());
    if (replaceInvalid && requested !== active) {
      void this.router.navigateByUrl(workPageHref(this.slug(), active), { replaceUrl: true });
    }
  }

  private watchValidations(slug: string, needsQueue: boolean): void {
    this.validationWatch?.unsubscribe();
    this.validationWatch = null;
    if (!needsQueue) {
      this.validationState.set('idle');
      return;
    }
    this.validationState.set('loading');
    this.validationWatch = timer(0, POLL_MS)
      .pipe(
        switchMap(() => this.api.listPendingValidations(slug)),
        takeUntilDestroyed(this.destroy),
      )
      .subscribe((result) => {
        if (result.kind !== 'ok') {
          this.validationState.set('error');
          return;
        }
        this.pending.set(result.items);
        this.validationState.set('ready');
        if (result.items.length > 0) this.showValidations.set(true);
      });
  }

  retryValidations(): void {
    if (!this.slug() || !this.showValidations()) return;
    this.watchValidations(this.slug(), true);
  }

  private resetExperienceState(): void {
    this.boundSystemIds.set([]);
    this.validationWatch?.unsubscribe();
    this.validationWatch = null;
    this.runtime.reset();
    this.pending.set([]);
    this.validationState.set('idle');
    this.reasons.set({});
    this.reasonError.set(null);
    this.announcement.set('');
    this.decisionBusy.set(new Set());
    this.decisionError.set(false);
    this.showValidations.set(false);
    this.pinMismatch.set(false);
    this.experienceId.set(null);
    this.releaseId.set(null);
    this.releaseNumber.set(null);
    this.description.set('');
    this.emblem.set('A');
    this.renderer.set(null);
    this.rawDocument.set({ pages: [] });
    this.activePage.set(null);
    this.locales.set([]);
    this.theme.set({ mode: 'light', accent: '', onAccent: '' });
    this.appearance.set({});
  }
}
