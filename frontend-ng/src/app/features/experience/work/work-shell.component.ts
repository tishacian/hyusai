import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { timer } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { I18nService, type Locale } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { type Run } from '@app/core/canonical-api.service';
import { ExperienceRuntimeHostComponent } from '../runtime/runtime-host.component';
import { ExperienceRuntimeService } from '../runtime/experience-runtime.service';
import { parseDocument, rendererPinMatches, type ExperienceDocument } from '../runtime/model';
import { WorkApiService } from './work-api.service';
import {
  canEditExperience,
  documentNeedsValidations,
  liveHref,
  pendingValidationOrigins,
  studioHref,
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
    <div class="xp-work">
      <header class="xp-work-bar">
        <div class="xp-work-brand">
          <a routerLink="/work">{{ i18n.t('experience.work.back') }}</a>
          <h1>{{ title() }}</h1>
        </div>
        @if (state() === 'ready') {
          <nav class="xp-work-nav" [attr.aria-label]="i18n.t('experience.work.pages')">
            @for (page of document().pages; track page.id) {
              <button
                type="button"
                [attr.aria-current]="activePage() === page.id ? 'page' : null"
                (click)="activePage.set(page.id)"
              >
                {{ page.title }}
              </button>
            }
            @if (showValidations()) {
              <button
                type="button"
                [attr.aria-current]="activePage() === validationsPage ? 'page' : null"
                (click)="activePage.set(validationsPage)"
              >
                {{ i18n.t('experience.work.validations') }}
                @if (pending().length > 0) {
                  <span class="xp-work-badge">{{ pending().length }}</span>
                }
              </button>
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
                        [value]="reasons()[run.id] ?? ''"
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
              <app-experience-runtime-host [document]="document()" [pageId]="activePage()" />
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
  readonly i18n = inject(I18nService);

  readonly validationsPage = VALIDATIONS;
  readonly state = signal<'loading' | 'ready' | 'missing' | 'unavailable'>('loading');
  readonly title = signal('');
  readonly document = signal<ExperienceDocument>({ pages: [] });
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
    this.runtime.reset();
    const slug = this.route.snapshot.paramMap.get('slug') ?? '';
    this.api.resolve(slug).subscribe((result) => {
      if (result.kind !== 'ok') {
        this.state.set(result.kind);
        this.title.set(this.i18n.t('experience.work.title'));
        return;
      }
      this.open(result.body);
    });
  }

  studioLink(): string {
    return studioHref(this.experienceId());
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
    const document = parseDocument(body.release.pages);
    this.title.set(body.experience.name);
    if (document.pages.length === 0) {
      this.state.set('unavailable');
      return;
    }
    if (!rendererPinMatches(body.release.renderer_version)) {
      this.pinMismatch.set(true);
      this.document.set(document);
      this.state.set('unavailable');
      return;
    }
    const locales = workLocales(body.release.languages ?? body.experience.languages);
    if (locales.length === 1) this.i18n.setLocale(locales[0]!);
    const origins = pendingValidationOrigins(body.release.bindings_snapshot);
    const needsQueue = documentNeedsValidations(document.pages, body.experience.pattern);
    this.document.set(document);
    this.locales.set(locales);
    this.activePage.set(document.pages[0]!.id);
    this.showValidations.set(needsQueue);
    this.leftover.set(needsQueue && origins.length === 0);
    this.state.set('ready');
    this.watchValidations(origins, needsQueue);
  }

  private watchValidations(origins: string[], needsQueue: boolean): void {
    if (!needsQueue && origins.length === 0) return;
    timer(0, POLL_MS)
      .pipe(
        switchMap(() => this.api.listPendingValidations(origins)),
        takeUntilDestroyed(this.destroy),
      )
      .subscribe((rows) => {
        const current = this.runtime.run();
        const merged = [...rows];
        if (current?.status === 'hitl_pending' && !merged.some((item) => item.id === current.id)) {
          merged.unshift(current);
        }
        this.pending.set(merged);
        if (merged.length > 0) this.showValidations.set(true);
      });
  }
}
