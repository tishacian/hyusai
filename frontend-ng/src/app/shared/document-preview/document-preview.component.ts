import { HttpClient } from '@angular/common/http';
import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, ViewEncapsulation, computed, effect, inject, input, output, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Subscription } from 'rxjs';

import { NgxExtendedPdfViewerModule, NgxExtendedPdfViewerService, pdfDefaultOptions } from 'ngx-extended-pdf-viewer';

import { IconComponent } from '@app/shared/ui/icon.component';
import { HIGHLIGHT_ANCHOR_ID, cellMatchesNeedle, escapeText, highlightPlainText, markRangeInDom, normalizeNeedleForCells, pdfFindPhrase } from './highlight-text.util';

// pdf.js runtime assets are copied to /assets/pdfjs by angular.json. ngx only
// treats an assetsFolder containing "://" as absolute — a bare "assets/pdfjs"
// becomes "./assets/pdfjs", resolved against the CURRENT route, so it 404s on
// deep routes (e.g. /chat) and the worker/viewer never load (blank viewer).
// An absolute URL built from document.baseURI is route- and baseHref-safe.
pdfDefaultOptions.assetsFolder =
  typeof document !== 'undefined' ? new URL('assets/pdfjs', document.baseURI).href : 'assets/pdfjs';

interface RichDocumentPreview {
  kind: 'text' | 'html' | 'spreadsheet' | 'image' | 'pdf' | 'binary';
  filename: string;
  content_type: string;
  size_bytes: number;
  download_url: string;
  content?: string;
  rows?: string[][];
  sheet_name?: string;
  truncated?: boolean;
  reason?: string;
}

export interface DocumentPreviewViewChange {
  kind: 'text' | 'html' | 'spreadsheet' | 'image' | 'pdf' | 'binary';
  filename: string;
  page: number | null;
}

const RICH_PREVIEW_CACHE_LIMIT = 50;

@Component({
  selector: 'app-document-preview',
  standalone: true,
  imports: [IconComponent, NgTemplateOutlet, NgxExtendedPdfViewerModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  // Global so the highlight rules reach <mark> nodes injected via innerHTML.
  encapsulation: ViewEncapsulation.None,
  styles: [
    `
      .omnirag-hl {
        background: rgba(250, 204, 21, 0.92);
        color: #111827;
        border-radius: 2px;
        padding: 0 0.1em;
        box-shadow: 0 0 0 1px rgba(202, 138, 4, 0.55);
        scroll-margin: 25vh;
      }
      .omnirag-cell-hl {
        outline: 2px solid rgba(250, 204, 21, 0.95);
        outline-offset: -2px;
        background: rgba(250, 204, 21, 0.22) !important;
        scroll-margin: 25vh;
      }
    `,
  ],
  template: `
    @if (inline()) {
      @if (thumbnail()) {
        <!-- Thumbnail: neutral light frame — dark modal chrome clashes with white PDF pages. -->
        <div style="overflow:hidden; background:var(--ck-bg-inset, #e8ecf0);">
          <ng-container *ngTemplateOutlet="shell"></ng-container>
        </div>
      } @else {
        <div class="rounded-lg overflow-hidden bg-gray-950 text-white ring-1 ring-white/10">
          <ng-container *ngTemplateOutlet="shell"></ng-container>
        </div>
      }
    } @else if (open()) {
      <div class="fixed inset-0 z-[80] bg-black/55 backdrop-blur-sm flex items-center justify-center p-4">
        <section class="w-full max-w-5xl max-h-[88vh] rounded-lg overflow-hidden bg-gray-950 text-white ring-1 ring-white/10 shadow-2xl">
          <ng-container *ngTemplateOutlet="shell"></ng-container>
        </section>
      </div>
    }

    <ng-template #shell>
          @if (!inline()) {
            <header class="flex items-center justify-between gap-3 px-4 py-3 border-b border-white/10">
              <div class="min-w-0">
                <p class="text-[10px] uppercase tracking-[0.18em] text-cyan-300">{{ subtitle() || 'Document' }}</p>
                <h2 class="mt-0.5 truncate text-sm font-semibold">{{ title() || 'Preview' }}</h2>
                @if (normalizedPage(); as pageNo) {
                  <p class="mt-0.5 text-[10px] font-mono text-gray-400">Page {{ pageNo }}</p>
                }
              </div>
              <div class="flex items-center gap-2">
                @if (previewUrl()) {
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                    [disabled]="openingExternal() || !preview()"
                    (click)="openExternal()"
                  >
                    <app-icon [name]="openingExternal() ? 'loader-2' : 'external-link'" [size]="13" [class.animate-spin]="openingExternal()" />
                    Open
                  </button>
                }
                <button
                  type="button"
                  class="inline-flex items-center justify-center rounded p-2 text-gray-300 hover:bg-white/10 hover:text-white"
                  (click)="closed.emit()"
                  aria-label="Close preview"
                >
                  <app-icon name="x" [size]="16" />
                </button>
              </div>
            </header>
          }
          <div
            #scrollHost
            [class.bg-gray-900]="!thumbnail()"
            [class.overflow-auto]="!thumbnail()"
            [class.overflow-hidden]="thumbnail()"
            [style.height]="bodyHeight()"
            [style.pointerEvents]="thumbnail() ? 'none' : null"
            [style.background]="thumbnail() ? 'var(--ck-bg-inset, #e8ecf0)' : null"
          >
            @if (loading()) {
              <div
                class="flex h-full items-center justify-center"
                [class.gap-2]="!thumbnail()"
                [class.text-sm]="!thumbnail()"
                [class.text-gray-300]="!thumbnail()"
              >
                <app-icon name="loader-2" [size]="thumbnail() ? 14 : 16" class="animate-spin text-cyan-300" />
                @if (!thumbnail()) {
                  Loading preview...
                }
              </div>
            } @else if (error()) {
              <div class="flex h-full items-center justify-center p-6 text-center">
                <div class="max-w-md rounded bg-red-500/10 p-4 text-sm text-red-100 ring-1 ring-red-500/20">
                  {{ error() }}
                </div>
              </div>
            } @else if (preview(); as doc) {
              @if (htmlDoc(); as html) {
                <div class="relative h-full">
                  @if (doc.truncated) {
                    <span class="absolute right-3 top-3 z-10 rounded bg-yellow-500/90 px-2 py-0.5 text-[10px] font-semibold text-black shadow ring-1 ring-yellow-600/40">Truncated preview</span>
                  }
                  <iframe
                    class="block h-full w-full bg-white"
                    [attr.sandbox]="html.sandbox"
                    [srcdoc]="html.srcdoc"
                    title="HTML document preview"
                  ></iframe>
                </div>
              } @else if (doc.kind === 'text') {
                <pre class="min-h-full whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed text-gray-100" [innerHTML]="textHtml()"></pre>
              } @else if (doc.kind === 'spreadsheet') {
                <div class="p-4">
                  <div class="mb-3 flex flex-wrap items-center gap-2 text-xs text-gray-400">
                    <span>{{ doc.sheet_name || 'Sheet 1' }}</span>
                    @if (doc.truncated) {
                      <span class="rounded bg-yellow-500/10 px-2 py-0.5 text-yellow-100 ring-1 ring-yellow-500/20">Truncated preview</span>
                    }
                  </div>
                  <div class="overflow-auto rounded bg-black/20 ring-1 ring-white/10">
                    <table class="min-w-full border-collapse text-left text-xs text-gray-100">
                      <tbody>
                        @for (row of doc.rows || []; track $index; let ri = $index) {
                          <tr class="border-b border-white/10 last:border-b-0">
                            @for (cell of row; track $index) {
                              <td
                                class="max-w-[320px] border-r border-white/10 px-3 py-2 align-top last:border-r-0"
                                [class.omnirag-cell-hl]="sheetHl().hits.has(ri + ':' + $index)"
                                [attr.id]="sheetHl().first === ri + ':' + $index ? hlAnchorId : null"
                              >{{ cell }}</td>
                            }
                          </tr>
                        }
                      </tbody>
                    </table>
                  </div>
                </div>
              } @else if (doc.kind === 'image') {
                @if (objectUrl()) {
                  <div class="flex h-full items-center justify-center p-4">
                    <img [src]="objectUrl()!" [alt]="doc.filename" class="max-h-full max-w-full object-contain" />
                  </div>
                } @else {
                  <ng-container *ngTemplateOutlet="mediaPending"></ng-container>
                }
              } @else if (doc.kind === 'pdf') {
                @if (objectUrl(); as pdfUrl) {
                  <ngx-extended-pdf-viewer
                    [src]="pdfUrl"
                    [page]="normalizedPage() || 1"
                    [textLayer]="!thumbnail()"
                    [height]="bodyHeight()"
                    [showToolbar]="!thumbnail()"
                    [zoom]="thumbnail() ? 'page-fit' : 'auto'"
                    [backgroundColor]="thumbnail() ? '#e8ecf0' : '#0b1220'"
                    [showSidebarButton]="false"
                    [showOpenFileButton]="false"
                    [showPrintButton]="false"
                    [showDownloadButton]="false"
                    [showPropertiesButton]="false"
                    [showSecondaryToolbarButton]="false"
                    [showEditorButtons]="false"
                    [showStampEditor]="false"
                    [showDrawEditor]="false"
                    [showTextEditor]="false"
                    [showHighlightEditor]="false"
                    (pdfLoaded)="onPdfLoaded()"
                    (pageChange)="onPdfPageChange($event)"
                    (textLayerRendered)="onPdfTextLayer()"
                  />
                } @else {
                  <ng-container *ngTemplateOutlet="mediaPending"></ng-container>
                }
              } @else {
                <div class="flex h-full items-center justify-center p-6 text-center">
                  <div class="max-w-md rounded bg-white/5 p-4 text-sm text-gray-300 ring-1 ring-white/10">
                    Inline preview is not available for this file type.
                  </div>
                </div>
              }
            } @else {
              <div class="flex h-64 items-center justify-center text-sm text-gray-400">
                No preview available.
              </div>
            }
          </div>
    </ng-template>

    <ng-template #mediaPending>
      <div class="flex h-full items-center justify-center p-6 text-center">
        @if (mediaLoading()) {
          <div class="max-w-md rounded bg-white/5 p-4 text-sm text-gray-300 ring-1 ring-white/10">
            <app-icon name="loader-2" [size]="18" class="mx-auto mb-3 animate-spin text-cyan-300" />
            Loading inline document...
          </div>
        } @else if (mediaError()) {
          <div class="max-w-md rounded bg-yellow-500/10 p-4 text-sm text-yellow-100 ring-1 ring-yellow-500/20">
            {{ mediaError() }}
          </div>
        } @else {
          <div class="max-w-md rounded bg-white/5 p-4 text-sm text-gray-300 ring-1 ring-white/10">
            Inline preview is preparing.
          </div>
        }
      </div>
    </ng-template>
  `,
})
export class DocumentPreviewComponent {
  private static readonly previewCache = new Map<string, RichDocumentPreview>();
  private readonly destroyRef = inject(DestroyRef);
  private readonly http = inject(HttpClient);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly pdfFind = inject(NgxExtendedPdfViewerService);
  private loadSeq = 0;
  private currentPreviewUrl: string | null = null;
  private previewRequestSub: Subscription | null = null;
  private mediaRequestSub: Subscription | null = null;
  private pdfReady = false;
  private pdfLastFind = '';

  readonly open = input(false);
  /**
   * Embed the preview in place (no modal overlay/chrome) — used by La Scène to
   * show the live document "en scène". When inline, the preview loads whenever a
   * `previewUrl` is present, independent of `open`.
   */
  readonly inline = input(false);
  /**
   * Thumbnail mode (implies inline): a chromeless, non-interactive rendering of
   * the target page fitted to the box — used by La Scène film-strip tiles to
   * show a real document preview instead of a decorative placeholder.
   */
  readonly thumbnail = input(false);
  /** Body height in px for inline mode; modal keeps its 72vh viewport. */
  readonly heightPx = input<number | null>(null);
  readonly previewUrl = input<string | null>(null);
  readonly title = input('');
  readonly subtitle = input('');
  readonly page = input<number | null>(null);
  /** Chunk/snippet text to locate and highlight inside the rendered preview. */
  readonly highlight = input<string | null>(null);
  readonly closed = output<void>();
  readonly viewChanged = output<DocumentPreviewViewChange>();

  /** Exposed to the template for the spreadsheet scroll anchor. */
  readonly hlAnchorId = HIGHLIGHT_ANCHOR_ID;
  private readonly scrollHost = viewChild<ElementRef<HTMLElement>>('scrollHost');

  readonly loading = signal(false);
  readonly openingExternal = signal(false);
  readonly error = signal<string | null>(null);
  readonly mediaLoading = signal(false);
  readonly mediaError = signal<string | null>(null);
  readonly preview = signal<RichDocumentPreview | null>(null);
  readonly objectUrl = signal<string | null>(null);

  /** Scroll-host / pdf viewer height: fixed px inline, 72vh in the modal. */
  readonly bodyHeight = computed(() => {
    const px = this.heightPx();
    return px && px > 0 ? `${px}px` : '72vh';
  });

  readonly normalizedPage = computed(() => {
    const raw = this.page();
    if (raw === null || raw === undefined) return null;
    const value = typeof raw === 'number' ? raw : Number.parseInt(String(raw), 10);
    return Number.isFinite(value) && value > 0 ? value : null;
  });

  /** Escaped text content for the ``text`` preview, with the chunk marked. */
  readonly textHtml = computed<SafeHtml>(() => {
    const doc = this.preview();
    const content = doc?.kind === 'text' ? doc.content || '' : '';
    const marked = highlightPlainText(content, this.highlight());
    return this.sanitizer.bypassSecurityTrustHtml(marked ?? escapeText(content));
  });

  /** srcdoc + sandbox for the HTML preview, with the chunk marked + scrolled to. */
  readonly htmlDoc = computed<{ srcdoc: SafeHtml; sandbox: string } | null>(() => {
    const doc = this.preview();
    if (!doc || !this.isHtmlPreview(doc)) return null;
    const built = this.buildHtmlSrcdoc(doc, this.highlight());
    return {
      srcdoc: this.sanitizer.bypassSecurityTrustHtml(built.html),
      sandbox: built.scripted ? 'allow-scripts' : '',
    };
  });

  /** Spreadsheet cells (``row:col`` keys) that match the chunk, plus the first hit. */
  readonly sheetHl = computed<{ hits: Set<string>; first: string | null }>(() => {
    const doc = this.preview();
    const needle = normalizeNeedleForCells(this.highlight());
    const hits = new Set<string>();
    let first: string | null = null;
    if (doc?.kind === 'spreadsheet' && needle) {
      const rows = doc.rows || [];
      for (let r = 0; r < rows.length; r++) {
        const row = rows[r] || [];
        for (let c = 0; c < row.length; c++) {
          if (cellMatchesNeedle(row[c], needle)) {
            const key = r + ':' + c;
            hits.add(key);
            if (!first) first = key;
          }
        }
      }
    }
    return { hits, first };
  });

  readonly displayName = computed(() => this.preview()?.filename || this.title() || 'document');

  constructor() {
    this.destroyRef.onDestroy(() => this.clearPreview());
    effect(() => {
      const url = this.previewUrl();
      this.normalizedPage();
      this.highlight();
      const visible = this.open() || this.inline();
      if (!visible || !url) {
        this.clearPreview();
        return;
      }
      this.loadPreview(url);
    });
    // Scroll the highlighted passage into view once the preview DOM is painted.
    // (HTML previews self-scroll from inside their sandboxed iframe instead.)
    effect(() => {
      this.textHtml();
      this.htmlDoc();
      this.objectUrl();
      const sheetHit = this.sheetHl().first;
      if ((this.open() || this.inline()) && (this.preview() || sheetHit)) {
        setTimeout(() => this.scrollToHighlight(), 80);
      }
    });
    // Re-run the PDF find when the highlight changes on an ALREADY-loaded
    // document (e.g. review: switching between two sources of the same doc) —
    // loadPreview early-returns on same URL, so this is the only refresh path.
    effect(() => {
      const phrase = this.highlight();
      if (this.pdfReady && phrase) {
        this.pdfLastFind = '';
        this.runPdfFind();
      }
    });
  }

  private scrollToHighlight(): void {
    const host = this.scrollHost()?.nativeElement;
    if (!host) return;
    const target = host.querySelector('#' + HIGHLIGHT_ANCHOR_ID) as HTMLElement | null;
    target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  /** pdf.js has parsed the document — page nav is honoured, kick off the find. */
  onPdfLoaded(): void {
    this.pdfReady = true;
    this.pdfLastFind = '';
    this.runPdfFind();
    // Announce the effective landing page immediately (default 1): consumers
    // sync the active pin / visual context from `viewChanged`, and without this
    // a mark on an unnavigated PDF carries `page: null`.
    const doc = this.preview();
    if (doc) {
      this.viewChanged.emit({
        kind: doc.kind,
        filename: doc.filename,
        page: this.normalizedPage() || 1,
      });
    }
  }

  /** A page text layer is ready — (re)run the find so the highlight overlay shows. */
  onPdfTextLayer(): void {
    if (this.pdfReady) this.runPdfFind();
  }

  /**
   * Highlight the chunk inside the PDF via the pdf.js find controller. It both
   * marks every occurrence and scrolls the first one into view. Guarded by the
   * last phrase so repeated text-layer renders don't re-trigger the same search.
   */
  private runPdfFind(): void {
    if (!this.pdfReady) return;
    const phrase = pdfFindPhrase(this.highlight());
    if (!phrase || phrase === this.pdfLastFind) return;
    this.pdfLastFind = phrase;
    setTimeout(() => {
      try {
        this.pdfFind.find(phrase, { highlightAll: true, matchCase: false, findMultiple: false });
      } catch {
        /* viewer not ready yet — a later textLayerRendered will retry */
        this.pdfLastFind = '';
      }
    }, 120);
  }

  private makeNonce(): string {
    const c = (globalThis as { crypto?: Crypto }).crypto;
    if (c?.randomUUID) return c.randomUUID().replace(/-/g, '');
    if (c?.getRandomValues) {
      const bytes = c.getRandomValues(new Uint8Array(16));
      return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    }
    return 'hl' + this.loadSeq.toString(36);
  }

  openExternal(): void {
    const doc = this.preview();
    if (!doc?.download_url) return;
    this.openingExternal.set(true);
    this.http
      .get(this.withDisposition(doc.download_url, 'inline'), { responseType: 'blob' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          const objectUrl = URL.createObjectURL(blob);
          const targetUrl = doc.kind === 'pdf' ? this.pdfObjectUrl(objectUrl) : objectUrl;
          window.open(targetUrl, '_blank', 'noopener,noreferrer');
          window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
          this.openingExternal.set(false);
        },
        error: () => {
          this.openingExternal.set(false);
          this.error.set(`Unable to open ${this.displayName()}.`);
        },
      });
  }

  private loadPreview(url: string): void {
    // Same-URL early return — EXCEPT when the previous attempt left the binary
    // body missing (failed blob fetch): retry instead of showing a dead viewer.
    if (this.currentPreviewUrl === url && (this.loading() || this.preview())) {
      const kind = this.preview()?.kind;
      const needsBlob = kind === 'pdf' || kind === 'image';
      const blobMissing = needsBlob && !this.objectUrl() && !this.mediaLoading();
      if (!blobMissing && !this.mediaError()) return;
    }
    const seq = ++this.loadSeq;
    this.currentPreviewUrl = url;
    this.pdfReady = false;
    this.pdfLastFind = '';
    this.revokeObjectUrl();
    this.cancelInFlightRequests();
    this.loading.set(true);
    this.error.set(null);
    this.mediaLoading.set(false);
    this.mediaError.set(null);
    this.preview.set(null);
    const cached = DocumentPreviewComponent.previewCache.get(url);
    if (cached) {
      this.preview.set(cached);
      this.loading.set(false);
      if (cached.kind === 'image' || cached.kind === 'pdf') {
        this.loadPreviewBlob(cached, seq);
      }
      return;
    }
    this.previewRequestSub = this.http
      .get<RichDocumentPreview>(url)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (preview) => {
          if (seq !== this.loadSeq) return;
          this.rememberPreview(url, preview);
          this.preview.set(preview);
          this.loading.set(false);
          if (preview.kind === 'image' || preview.kind === 'pdf') {
            this.loadPreviewBlob(preview, seq);
          }
        },
        error: (err) => {
          if (seq !== this.loadSeq) return;
          this.loading.set(false);
          this.error.set(this.errorMessage(err));
        },
      });
  }

  private loadPreviewBlob(preview: RichDocumentPreview, seq: number): void {
    this.mediaRequestSub?.unsubscribe();
    this.mediaLoading.set(true);
    this.mediaError.set(null);
    this.mediaRequestSub = this.http
      .get(this.withDisposition(preview.download_url, 'inline'), { responseType: 'blob' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          if (seq !== this.loadSeq) return;
          const url = URL.createObjectURL(blob);
          this.objectUrl.set(url);
          this.mediaLoading.set(false);
        },
        error: (err) => {
          if (seq !== this.loadSeq) return;
          this.mediaLoading.set(false);
          this.mediaError.set(this.errorMessage(err));
        },
      });
  }

  private clearPreview(): void {
    ++this.loadSeq;
    this.currentPreviewUrl = null;
    this.pdfReady = false;
    this.pdfLastFind = '';
    this.cancelInFlightRequests();
    this.loading.set(false);
    this.mediaLoading.set(false);
    this.openingExternal.set(false);
    this.error.set(null);
    this.mediaError.set(null);
    this.preview.set(null);
    this.revokeObjectUrl();
  }

  private cancelInFlightRequests(): void {
    this.previewRequestSub?.unsubscribe();
    this.previewRequestSub = null;
    this.mediaRequestSub?.unsubscribe();
    this.mediaRequestSub = null;
  }

  private revokeObjectUrl(): void {
    const url = this.objectUrl();
    if (url) URL.revokeObjectURL(url);
    this.objectUrl.set(null);
  }

  private rememberPreview(url: string, preview: RichDocumentPreview): void {
    DocumentPreviewComponent.previewCache.set(url, preview);
    if (DocumentPreviewComponent.previewCache.size <= RICH_PREVIEW_CACHE_LIMIT) return;
    const oldest = DocumentPreviewComponent.previewCache.keys().next().value as string | undefined;
    if (oldest) DocumentPreviewComponent.previewCache.delete(oldest);
  }

  private isHtmlPreview(doc: RichDocumentPreview): boolean {
    if (doc.kind === 'html') return !!doc.content;
    const filename = (doc.filename || '').toLowerCase();
    const contentType = (doc.content_type || '').toLowerCase();
    return (
      doc.kind === 'text' &&
      !!doc.content &&
      (contentType.includes('html') || filename.endsWith('.html') || filename.endsWith('.htm'))
    );
  }

  private cspContent(scriptSrc: string): string {
    return `default-src 'none'; img-src data: blob: http: https:; style-src 'unsafe-inline'; font-src data:; script-src ${scriptSrc}; connect-src 'none';`;
  }

  private htmlChrome(scriptSrc: string): string {
    return `
      <meta charset="utf-8">
      <meta http-equiv="Content-Security-Policy" content="${this.cspContent(scriptSrc)}">
      <style>
        html, body { margin: 0; min-height: 100%; background: #f8fafc; color: #111827; font: 14px/1.55 Arial, Helvetica, sans-serif; }
        body { padding: 24px; box-sizing: border-box; }
        table { border-collapse: collapse; max-width: 100%; margin: 16px 0; background: white; }
        caption { padding: 8px 0; font-weight: 700; text-align: left; }
        th, td { border: 1px solid #cbd5e1; padding: 6px 8px; vertical-align: top; }
        th { background: #e2e8f0; font-weight: 700; }
        h1, h2, h3, h4 { color: #0f172a; line-height: 1.2; }
        a { color: #0369a1; }
        img { max-width: 100%; height: auto; }
        p { margin: 0 0 12px; }
        mark.omnirag-hl { background: #fde68a; color: #111827; border-radius: 2px; padding: 0 0.1em; box-shadow: 0 0 0 2px #fde68a; scroll-margin: 25vh; }
      </style>
    `;
  }

  private wrapHtml(raw: string, scriptSrc: string): string {
    const chrome = this.htmlChrome(scriptSrc);
    if (/<html[\s>]/i.test(raw)) {
      if (/<head[\s>]/i.test(raw)) {
        return raw.replace(/<head([^>]*)>/i, `<head$1>${chrome}`);
      }
      return raw.replace(/<html([^>]*)>/i, `<html$1><head>${chrome}</head>`);
    }
    return `<!doctype html><html><head>${chrome}</head><body>${raw}</body></html>`;
  }

  /**
   * Build the sandboxed HTML srcdoc. With no highlight (or no match) the
   * document stays fully locked down (``script-src 'none'``). When the chunk is
   * located we mark it, relax the CSP to a single nonce so ONLY our scroll
   * script may run (the document's own scripts still cannot), and report
   * ``scripted`` so the caller can grant the iframe ``allow-scripts``.
   */
  private buildHtmlSrcdoc(doc: RichDocumentPreview, highlight: string | null): { html: string; scripted: boolean } {
    const raw = doc.content || '';
    const locked = this.wrapHtml(raw, "'none'");
    if (!highlight) return { html: locked, scripted: false };

    try {
      const parsed = new DOMParser().parseFromString(locked, 'text/html');
      const body = parsed.body;
      if (!body || !markRangeInDom(body, highlight, parsed)) {
        return { html: locked, scripted: false };
      }
      const nonce = this.makeNonce();
      const meta = parsed.querySelector('meta[http-equiv="Content-Security-Policy" i]');
      meta?.setAttribute('content', this.cspContent(`'nonce-${nonce}'`));
      const script = parsed.createElement('script');
      script.setAttribute('nonce', nonce);
      script.textContent = `(function(){function g(){var e=document.getElementById('${HIGHLIGHT_ANCHOR_ID}');if(e){e.scrollIntoView({block:'center'});}}if(document.readyState!=='loading'){g();}else{document.addEventListener('DOMContentLoaded',g);}})();`;
      body.appendChild(script);
      return { html: '<!doctype html>' + parsed.documentElement.outerHTML, scripted: true };
    } catch {
      return { html: locked, scripted: false };
    }
  }

  private withDisposition(url: string, disposition: 'inline' | 'attachment'): string {
    const separator = url.includes('?') ? '&' : '?';
    return url.includes('disposition=') ? url : `${url}${separator}disposition=${disposition}`;
  }

  private pdfObjectUrl(url: string): string {
    const page = this.normalizedPage();
    return page ? `${url}#page=${page}` : url;
  }

  protected onPdfPageChange(page: unknown): void {
    const doc = this.preview();
    if (!doc) return;
    const pageNo =
      typeof page === 'number'
        ? page
        : Number.parseInt(String((page as { pageNumber?: unknown })?.pageNumber ?? page), 10);
    this.viewChanged.emit({
      kind: doc.kind,
      filename: doc.filename,
      page: Number.isFinite(pageNo) && pageNo > 0 ? pageNo : this.normalizedPage(),
    });
  }

  private errorMessage(err: unknown): string {
    const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
    if (typeof detail === 'string') return detail;
    return `Unable to load ${this.displayName()}.`;
  }
}
