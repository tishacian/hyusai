import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, timer } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { I18nService, type Locale } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { type Run } from '@app/core/canonical-api.service';
import { ExperienceRuntimeHostComponent } from '../runtime/runtime-host.component';
import { ExperienceRuntimeService } from '../runtime/experience-runtime.service';
import {
  localizeDocument,
  rendererPinMatches,
  textFallback,
  type ExperienceDocument,
} from '../runtime/model';
import { WorkApiService } from './work-api.service';
import {
  canEditExperience,
  documentNeedsValidations,
  liveHref,
  pendingValidationOrigins,
  studioHref,
  workPageHref,
  workTheme,
  workLocales,
  type WorkResolve,
} from './work-catalog';

const VALIDATIONS = 'validations';
const POLL_MS = 8000;

@Component({
  selector: 'app-work-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, EmptyStateComponent, ExperienceRuntimeHostComponent],
  styleUrl: './work.scss',
  template: `
    <div
      class="xp-work"
      [attr.data-theme]="theme().mode"
      [style.--xp-app-accent]="theme().accent || null"
    >
      <header class="xp-work-bar">
        <div class="xp-work-brand">
          <a routerLink="/work">{{ i18n.t('experience.work.back') }}</a>
          <h1>{{ title() }}</h1>
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
          @if (locales().length > 1) {
            @for (locale of locales(); track locale) {
              <button
                type="button"
                class="xp-work-btn"
                [class.xp-work-btn-primary]="i18n.locale() === locale"
                (click)="i18n.setLocale(locale)"
              >
                {{ i18n.t(locale === 'fr' ? 'experience.work.lang.fr' : 'experience.work.lang.en') }}
              </button>
            }
          }
          @if (canEdit()) {
            <a class="xp-work-link" [routerLink]="studioLink()">{{ i18n.t('experience.work.edit_studio') }}</a>
          }
        </div>
      </header>
      <main class="xp-work-main">
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
                @if (pending().length === 0) {
                  <app-empty-state
                    icon="inbox"
                    size="md"
                    [title]="i18n.t('experience.work.validations.empty')"
                    [description]="leftover() ? i18n.t('experience.work.validations.leftover') : undefined"
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
                      <button type="button" class="xp-work-btn xp-work-btn-primary" (click)="decide(run, 'accept')">
                        {{ i18n.t('experience.work.validations.approve') }}
                      </button>
                      <button type="button" class="xp-work-btn" (click)="decide(run, 'reject')">
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
              <app-experience-runtime-host
                [document]="document()"
                [pageId]="activePage()"
                [experienceSlug]="slug()"
                mode="live"
              />
            }
          }
        }
      </main>
    </div>
  `,
})
export class WorkShellComponent {
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
  readonly rawDocument = signal<unknown>({ pages: [] });
  readonly document = computed<ExperienceDocument>(() =>
    localizeDocument(this.rawDocument(), this.i18n.locale()),
  );
  readonly theme = signal<{ mode: 'light' | 'dark'; accent: string }>({ mode: 'light', accent: '' });
  readonly activePage = signal<string | null>(null);
  readonly locales = signal<Locale[]>([]);
  readonly pending = signal<Run[]>([]);
  readonly reasons = signal<Record<string, string>>({});
  readonly reasonError = signal<string | null>(null);
  readonly leftover = signal(false);
  readonly showValidations = signal(false);
  readonly pinMismatch = signal(false);
  readonly experienceId = signal<string | null>(null);

  readonly canEdit = computed(() =>
    canEditExperience(this.workspace.current()?.role_template, this.workspace.isAdmin()),
  );

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

  studioLink(): string {
    return studioHref(this.experienceId());
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
    const note = (this.reasons()[run.id] ?? '').trim();
    if (action === 'reject' && !note) {
      this.reasonError.set(run.id);
      return;
    }
    this.api.decide(run.id, action, note).subscribe((updated) => {
      if (!updated) return;
      this.pending.update((rows) => rows.filter((item) => item.id !== run.id));
    });
  }

  private open(body: WorkResolve): void {
    const href = liveHref(body.release.theme) ?? liveHref(body.experience.theme);
    if (href && href !== `/work/${body.experience.slug}`) {
      void this.router.navigateByUrl(href);
      return;
    }
    this.experienceId.set(body.experience.id);
    const document = localizeDocument(body.release.pages, this.i18n.locale());
    this.title.set(body.experience.name);
    if (document.pages.length === 0) {
      this.state.set('unavailable');
      return;
    }
    if (!rendererPinMatches(body.release.renderer_version)) {
      this.pinMismatch.set(true);
      this.rawDocument.set(body.release.pages);
      this.state.set('unavailable');
      return;
    }
    const locales = workLocales(body.release.languages ?? body.experience.languages);
    if (locales.length === 1) this.i18n.setLocale(locales[0]!);
    const origins = pendingValidationOrigins(body.release.bindings_snapshot, body.experience.slug);
    const needsQueue = documentNeedsValidations(document.pages, body.experience.pattern);
    this.rawDocument.set(body.release.pages);
    this.theme.set(workTheme(body.release.theme ?? body.experience.theme));
    this.locales.set(locales);
    this.showValidations.set(needsQueue);
    this.leftover.set(needsQueue && origins.length === 0);
    this.state.set('ready');
    this.activateRequestedPage(true);
    this.watchValidations(origins, needsQueue);
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
    if (replaceInvalid && requested !== active) {
      void this.router.navigateByUrl(workPageHref(this.slug(), active), { replaceUrl: true });
    }
  }

  private watchValidations(origins: string[], needsQueue: boolean): void {
    this.validationWatch?.unsubscribe();
    this.validationWatch = null;
    if (!needsQueue && origins.length === 0) return;
    this.validationWatch = timer(0, POLL_MS)
      .pipe(
        switchMap(() => this.api.listPendingValidations(origins)),
        takeUntilDestroyed(this.destroy),
      )
      .subscribe((rows) => {
        const current = this.runtime.runs().find((run) => run.status === 'hitl_pending');
        const merged = [...rows];
        if (current?.status === 'hitl_pending' && !merged.some((item) => item.id === current.id)) {
          merged.unshift(current);
        }
        this.pending.set(merged);
        if (merged.length > 0) this.showValidations.set(true);
      });
  }

  private resetExperienceState(): void {
    this.validationWatch?.unsubscribe();
    this.validationWatch = null;
    this.runtime.reset();
    this.pending.set([]);
    this.reasons.set({});
    this.reasonError.set(null);
    this.showValidations.set(false);
    this.leftover.set(false);
    this.pinMismatch.set(false);
    this.experienceId.set(null);
    this.rawDocument.set({ pages: [] });
    this.activePage.set(null);
    this.locales.set([]);
    this.theme.set({ mode: 'light', accent: '' });
  }
}
