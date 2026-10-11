import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
  TemplateRef,
  ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Overlay, type OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { Subscription } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  filePath,
  isUnavailableStatus,
  passageQuery,
  previewPath,
  sourceStep,
  workSourceView,
  type CitedPassageResponse,
  type WorkSourcePreview,
  type WorkSourceRef,
  type WorkSourceState,
} from './work-source';

/**
 * L36 — « Sources lisibles sur place »: the cited source, read beside the
 * answer in Work. The document, its type, page and collection; the cited
 * passage in full, marked and labelled, framed by the text around it; the
 * page itself when the original exists; previous / next across the answer's
 * sources. A source the member can no longer read says so and shows nothing.
 *
 * Escape and focus return belong to the host (the chat panel), which closes
 * the panel and gives focus back to the citation that opened it.
 */
@Component({
  selector: 'app-work-source-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DocumentPreviewComponent, IconComponent],
  template: `
    <aside class="wsrc" #scroller [class.wsrc--enter]="animate()" [attr.aria-labelledby]="ids.heading" data-testid="work-source-panel">
      <p class="wsrc-sr" aria-live="polite">{{ announcement() }}</p>
      <header class="wsrc-head">
        <div class="wsrc-bar">
          <p class="wsrc-step" data-testid="work-source-step">
            {{ i18n.t('experience.work.sources.step', { n: step().n, total: step().total }) }}
            @if (current() && !current()!.cited) {
              <span class="wsrc-tag">· {{ i18n.t('experience.work.sources.read_not_cited') }}</span>
            }
          </p>
          <div class="wsrc-actions">
            @if (step().total > 1) {
              <button
                type="button"
                class="wsrc-icon"
                data-testid="work-source-previous"
                [attr.aria-label]="i18n.t('experience.work.sources.previous')"
                [title]="i18n.t('experience.work.sources.previous')"
                [attr.aria-disabled]="step().previous === null ? 'true' : null"
                (click)="go(step().previous)"
              ><app-icon name="chevron-left" [size]="16" /></button>
              <button
                type="button"
                class="wsrc-icon"
                data-testid="work-source-next"
                [attr.aria-label]="i18n.t('experience.work.sources.next')"
                [title]="i18n.t('experience.work.sources.next')"
                [attr.aria-disabled]="step().next === null ? 'true' : null"
                (click)="go(step().next)"
              ><app-icon name="chevron-right" [size]="16" /></button>
            }
            <button
              type="button"
              class="wsrc-icon"
              data-testid="work-source-close"
              [attr.aria-label]="i18n.t('experience.work.sources.close')"
              [title]="i18n.t('experience.work.sources.close')"
              (click)="closed.emit($event.detail > 0)"
            ><app-icon name="x" [size]="16" /></button>
          </div>
        </div>
        <h3 class="wsrc-title" [id]="ids.heading" tabindex="-1" #heading>{{ current()?.title }}</h3>
        @if (metaLine(); as meta) {
          <p class="wsrc-meta" data-testid="work-source-meta">{{ meta }}</p>
        }
      </header>

      @switch (state().status) {
        @case ('loading') {
          <p class="wsrc-note" role="status">{{ i18n.t('experience.work.sources.loading') }}</p>
        }
        @case ('unavailable') {
          <div class="wsrc-gone" role="status" data-testid="work-source-unavailable">
            <app-icon name="lock" [size]="16" class="wsrc-gone-icon" />
            <div>
              <p class="wsrc-gone-title">{{ i18n.t('experience.work.sources.unavailable.title') }}</p>
              <p class="wsrc-gone-body">{{ i18n.t('experience.work.sources.unavailable.body') }}</p>
            </div>
          </div>
        }
        @case ('ready') {
          @if (view(); as v) {
            <section class="wsrc-passage" [attr.aria-labelledby]="ids.passage">
              @if (v.before) {
                <p class="wsrc-context" data-testid="work-source-before"><span class="wsrc-sr">{{ i18n.t('experience.work.sources.before') }} : </span>… {{ v.before }}</p>
              }
              <p class="wsrc-label" [id]="ids.passage">{{ i18n.t('experience.work.sources.passage') }}</p>
              @if (v.passage) {
                <!-- One line: the passage is pre-wrap, template spaces would show. -->
                <blockquote class="wsrc-cited"><mark class="wsrc-mark" data-testid="work-source-mark">{{ v.passage }}</mark></blockquote>
              } @else {
                <p class="wsrc-note">{{ i18n.t('experience.work.sources.no_passage') }}</p>
              }
              @if (v.after) {
                <p class="wsrc-context" data-testid="work-source-after"><span class="wsrc-sr">{{ i18n.t('experience.work.sources.after') }} : </span>{{ v.after }} …</p>
              }
              @if (v.truncated) {
                <p class="wsrc-note">{{ i18n.t('experience.work.sources.truncated') }}</p>
              }
              @if (v.unverified) {
                <p class="wsrc-note" data-testid="work-source-unverified">{{ i18n.t('experience.work.sources.unverified') }}</p>
              }
            </section>

            <section class="wsrc-page" [attr.aria-labelledby]="ids.page">
              <div class="wsrc-page-head">
                <p class="wsrc-label" [id]="ids.page">
                  {{ v.page ? i18n.t('experience.work.sources.page_title', { page: v.page }) : i18n.t('experience.work.sources.preview_title') }}
                </p>
                @if (v.preview) {
                  <button type="button" class="wsrc-enlarge" #enlarge data-testid="work-source-enlarge" (click)="openReader()">
                    <app-icon name="maximize" [size]="14" />
                    {{ i18n.t('experience.work.sources.enlarge') }}
                  </button>
                }
              </div>
              @if (v.preview; as preview) {
                <div class="wsrc-preview" data-testid="work-source-preview">
                  @if (!readerOpen()) {
                    <app-document-preview
                      [inline]="true"
                      [contained]="true"
                      [toolbar]="false"
                      pageBackground="var(--ck-bg-inset)"
                      [heightPx]="320"
                      [previewUrl]="previewUrl(preview)"
                      [page]="preview.page"
                      [highlight]="preview.highlight"
                      [title]="v.title"
                    />
                    <!-- The page itself opens the reader (the button above is its keyboard way). -->
                    <div class="wsrc-page-hit" aria-hidden="true" (click)="openReader()"></div>
                  } @else {
                    <!-- One PDF viewer at a time: the reader holds it while open. -->
                    <div class="wsrc-page-held"></div>
                  }
                </div>
                <button type="button" class="wsrc-open" data-testid="work-source-open" [disabled]="opening()" (click)="openDocument(preview)">
                  <app-icon name="external-link" [size]="14" />
                  {{ i18n.t('experience.work.sources.open') }}
                  <span class="wsrc-sr">{{ i18n.t('experience.work.sources.open_hint') }}</span>
                </button>
                @if (openFailed()) {
                  <p class="wsrc-note" role="alert">{{ i18n.t('experience.work.sources.open_failed') }}</p>
                }
              } @else {
                <p class="wsrc-note" data-testid="work-source-no-preview">{{ i18n.t('experience.work.sources.no_preview') }}</p>
              }
            </section>
          }
        }
      }
    </aside>

    <ng-template #reader>
      @if (view(); as v) {
        @if (v.preview; as preview) {
          <app-document-preview
            [open]="true"
            [reader]="true"
            [toolbar]="false"
            pageBackground="var(--ck-bg-inset)"
            [previewUrl]="previewUrl(preview)"
            [page]="preview.page"
            [highlight]="preview.highlight"
            [title]="v.page ? i18n.t('experience.work.sources.reader_title', { title: v.title, page: v.page }) : v.title"
            (closed)="closeReader()"
          />
        }
      }
    </ng-template>
  `,
  styles: [`
    :host { display: block; height: 100%; min-height: 0; }
    .wsrc {
      display: flex;
      flex-direction: column;
      gap: 16px;
      height: 100%;
      min-height: 0;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 0 16px 16px;
      background: var(--ck-bg-base);
      color: var(--ck-fg-1);
      font-family: var(--ck-font-sans);
    }
    /* Opened by a pointer only: 8 px and opacity, settled in under 200 ms. */
    .wsrc--enter { animation: wsrc-in 180ms var(--ck-ease-out) both; }
    @keyframes wsrc-in {
      from { opacity: 0; transform: var(--wsrc-from, translateX(8px)); }
      to { opacity: 1; transform: none; }
    }
    /* As a sheet it rises instead of sliding in from the side. */
    @container (max-width: 760px) {
      .wsrc { --wsrc-from: translateY(8px); }
    }
    @media (prefers-reduced-motion: reduce) {
      .wsrc--enter { animation: none; }
    }
    /* The document, where it sits and the way out stay in view while the page scrolls. */
    .wsrc-head {
      position: sticky;
      top: 0;
      z-index: 1;
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 16px 0 12px;
      border-bottom: 1px solid var(--ck-stroke-2);
      background: var(--ck-bg-base);
    }
    .wsrc-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .wsrc-step { margin: 0; font-size: 12px; font-weight: 600; color: var(--ck-fg-2); font-variant-numeric: tabular-nums; }
    .wsrc-tag { font-weight: 500; color: var(--ck-fg-3); }
    .wsrc-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
    .wsrc-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 4px;
      background: transparent;
      color: var(--ck-fg-2);
      cursor: pointer;
    }
    .wsrc-icon:hover:not([aria-disabled='true']) { color: var(--ck-fg-1); border-color: var(--ck-stroke-hot); }
    .wsrc-icon[aria-disabled='true'] { opacity: .45; cursor: default; }
    .wsrc-title { margin: 4px 0 0; font-size: 15px; font-weight: 600; line-height: 1.35; overflow-wrap: anywhere; }
    .wsrc-title:focus { outline: none; }
    .wsrc-title:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; border-radius: 2px; }
    .wsrc-meta { margin: 0; font-size: 13px; color: var(--ck-fg-3); }
    .wsrc-passage, .wsrc-page { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    .wsrc-label { margin: 0; font-size: 12px; font-weight: 600; color: var(--ck-fg-2); }
    .wsrc-context {
      margin: 0;
      font-size: 13px;
      line-height: 1.6;
      color: var(--ck-fg-3);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .wsrc-cited {
      margin: 0;
      padding: 10px 12px;
      border-left: 3px solid var(--ck-primary);
      border-radius: 0 4px 4px 0;
      background: var(--ck-bg-inset);
      font-size: 14px;
      line-height: 1.65;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .wsrc-mark {
      background: color-mix(in oklab, var(--ck-primary) 18%, transparent);
      color: var(--ck-fg-1);
      border-radius: 2px;
      padding: 0 1px;
      box-decoration-break: clone;
      -webkit-box-decoration-break: clone;
    }
    .wsrc-note { margin: 0; font-size: 13px; line-height: 1.5; color: var(--ck-fg-3); }
    .wsrc-page-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .wsrc-enlarge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      padding: 0 8px;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 4px;
      background: transparent;
      color: var(--ck-fg-1);
      font: 600 12px/1.2 var(--ck-font-sans);
      cursor: pointer;
    }
    .wsrc-enlarge:hover { border-color: var(--ck-stroke-hot); }
    .wsrc-enlarge:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .wsrc-preview { position: relative; border: 1px solid var(--ck-stroke-2); border-radius: 6px; overflow: hidden; }
    .wsrc-page-hit { position: absolute; inset: 0; cursor: zoom-in; }
    .wsrc-page-held { height: 320px; background: var(--ck-bg-inset); }
    .wsrc-open {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      align-self: flex-start;
      min-height: 32px;
      padding: 0 12px;
      border: 1px solid var(--ck-stroke-3, var(--ck-stroke-2));
      border-radius: 4px;
      background: transparent;
      color: var(--ck-fg-1);
      font: 600 13px/1.2 var(--ck-font-sans);
      cursor: pointer;
    }
    .wsrc-open:hover:not(:disabled) { border-color: var(--ck-stroke-hot); }
    .wsrc-open:disabled { opacity: .55; cursor: default; }
    .wsrc-icon:focus-visible, .wsrc-open:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .wsrc-gone {
      display: flex;
      gap: 10px;
      padding: 12px 14px;
      border: 1px dashed var(--ck-stroke-3, var(--ck-stroke-2));
      border-radius: 6px;
      background: var(--ck-bg-inset);
    }
    .wsrc-gone-icon { margin-top: 2px; color: var(--ck-fg-2); flex-shrink: 0; }
    .wsrc-gone-title { margin: 0 0 4px; font-size: 14px; font-weight: 600; color: var(--ck-fg-1); }
    .wsrc-gone-body { margin: 0; font-size: 13px; line-height: 1.5; color: var(--ck-fg-3); }
    .wsrc-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
  `],
})
export class WorkSourcePanelComponent {
  protected readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly http = inject(HttpClient);
  private readonly injector = inject(Injector);
  private readonly destroyRef = inject(DestroyRef);

  /** Every source of the answer, in citation order. */
  readonly sources = input.required<WorkSourceRef[]>();
  /** 1-based number of the source shown. */
  readonly selected = input.required<number>();
  readonly animate = input(false);
  /** Bumped by the host on each opening: focus lands on the document name. */
  readonly focusToken = input(0);

  readonly selectedChange = output<number>();
  /** `true` when a pointer closed it. */
  readonly closed = output<boolean>();

  private static nextId = 0;
  private readonly uid = ++WorkSourcePanelComponent.nextId;
  readonly ids = {
    heading: `work-source-title-${this.uid}`,
    passage: `work-source-passage-${this.uid}`,
    page: `work-source-page-${this.uid}`,
  };
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');
  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  /** Previous / next keep focus on their button: the new source is announced instead. */
  readonly announcement = signal('');
  private shown: number | null = null;

  readonly step = computed(() => sourceStep(this.selected(), this.sources().length));
  readonly current = computed<WorkSourceRef | null>(() => this.sources()[this.step().n - 1] ?? null);

  private readonly states = signal<ReadonlyMap<string, WorkSourceState>>(new Map());
  readonly state = computed<WorkSourceState>(() => {
    const ref = this.current();
    return (ref && this.states().get(this.keyOf(ref))) || { status: 'loading' };
  });
  readonly view = computed(() => {
    const state = this.state();
    return state.status === 'ready' ? state.view : null;
  });
  readonly metaLine = computed(() => {
    const ref = this.current();
    if (!ref) return null;
    const view = this.view();
    const unavailable = this.state().status === 'unavailable';
    // An unreadable source keeps only what the answer itself named.
    const kind = unavailable ? null : view?.kind;
    const page = view?.page ?? ref.page;
    const collection = unavailable ? ref.collectionLabel ?? ref.collection : view?.collection ?? ref.collectionLabel ?? ref.collection;
    return [kind, page ? this.i18n.t('experience.work.sources.page', { page }) : null, collection]
      .filter(Boolean)
      .join(' · ') || null;
  });

  readonly opening = signal(false);
  readonly openFailed = signal(false);

  /** « Agrandir la page »: the cited page at reading size, in a dialog over Work. */
  readonly readerOpen = signal(false);
  private readonly overlay = inject(Overlay);
  private readonly viewContainer = inject(ViewContainerRef);
  private readonly readerTemplate = viewChild<TemplateRef<unknown>>('reader');
  private readonly enlargeButton = viewChild<ElementRef<HTMLButtonElement>>('enlarge');
  private readerRef: OverlayRef | null = null;
  private readonly requests = new Map<string, Subscription>();

  constructor() {
    effect(() => {
      const ref = this.current();
      const total = this.sources().length;
      if (!ref) return;
      untracked(() => {
        this.load(ref, total);
        if (this.shown !== null && this.shown !== ref.n) {
          this.announcement.set(`${this.i18n.t('experience.work.sources.step', { n: ref.n, total })} · ${ref.title}`);
          // A new source reads from its top.
          afterNextRender(() => this.scroller()?.nativeElement.scrollTo({ top: 0 }), { injector: this.injector });
        }
        this.shown = ref.n;
      });
    });
    effect(() => {
      if (!this.focusToken()) return;
      afterNextRender(() => this.heading()?.nativeElement.focus(), { injector: this.injector });
    });
    this.destroyRef.onDestroy(() => {
      this.requests.forEach((request) => request.unsubscribe());
      this.readerRef?.dispose();
    });
  }

  /**
   * The dialog lives at the body (a CDK overlay): the chat around the panel
   * is a size container, which would otherwise hold a fixed dialog inside it.
   */
  openReader(): void {
    const template = this.readerTemplate();
    if (!template || this.readerRef) return;
    // One PDF viewer at a time: the column preview steps aside first.
    this.readerOpen.set(true);
    afterNextRender(() => {
      if (this.readerRef || !this.readerOpen()) return;
      this.readerRef = this.overlay.create({
        positionStrategy: this.overlay.position().global(),
        scrollStrategy: this.overlay.scrollStrategies.block(),
      });
      this.readerRef.attach(new TemplatePortal(template, this.viewContainer));
    }, { injector: this.injector });
  }

  closeReader(): void {
    this.readerRef?.dispose();
    this.readerRef = null;
    this.readerOpen.set(false);
    // Back where the reader was asked for (after the focus trap lets go).
    globalThis.setTimeout?.(() => this.enlargeButton()?.nativeElement.focus(), 0);
  }

  go(n: number | null): void {
    if (n === null) return;
    this.openFailed.set(false);
    this.selectedChange.emit(n);
  }

  previewUrl(preview: WorkSourcePreview): string {
    return `${this.api.base}${previewPath(preview)}`;
  }

  /** The original in a new tab, read with the member's session (never a Cockpit page). */
  openDocument(preview: WorkSourcePreview): void {
    this.openFailed.set(false);
    this.opening.set(true);
    // Opened inside the click so the browser does not block it; filled once the file is here.
    const tab = typeof window !== 'undefined' ? window.open('', '_blank') : null;
    this.http
      .get(`${this.api.base}${filePath(preview)}`, { responseType: 'blob' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          const url = URL.createObjectURL(blob);
          const target = preview.page && blob.type === 'application/pdf' ? `${url}#page=${preview.page}` : url;
          if (tab) {
            tab.opener = null;
            tab.location.href = target;
          } else {
            window.open(target, '_blank', 'noopener');
          }
          window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
          this.opening.set(false);
        },
        error: () => {
          tab?.close();
          this.opening.set(false);
          this.openFailed.set(true);
        },
      });
  }

  private keyOf(ref: WorkSourceRef): string {
    return [ref.n, ref.documentId, ref.collection, ref.chunkIndex, ref.page].join('|');
  }

  private setState(key: string, state: WorkSourceState): void {
    this.states.update((current) => new Map(current).set(key, state));
  }

  private load(ref: WorkSourceRef, total: number): void {
    const key = this.keyOf(ref);
    if (this.states().has(key) || this.requests.has(key)) return;
    const query = passageQuery(ref);
    if (!query) {
      // Nothing to ask the server: the passage is the one the answer received, as is.
      this.setState(key, { status: 'ready', view: { ...workSourceView(ref, total, null), unverified: false } });
      return;
    }
    const request = this.api
      .get<CitedPassageResponse>(`/documents/${encodeURIComponent(ref.documentId!)}/passage`, query)
      .subscribe({
        next: (response) => {
          this.requests.delete(key);
          this.setState(key, { status: 'ready', view: workSourceView(ref, total, response) });
        },
        error: (error: unknown) => {
          this.requests.delete(key);
          const status = error instanceof HttpErrorResponse ? error.status : (error as { status?: number })?.status;
          this.setState(
            key,
            isUnavailableStatus(status) ? { status: 'unavailable' } : { status: 'ready', view: workSourceView(ref, total, null) },
          );
        },
      });
    this.requests.set(key, request);
  }
}
