import { HttpClient } from '@angular/common/http';
import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { Subscription } from 'rxjs';

import { IconComponent } from '@app/shared/ui/icon.component';

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

const RICH_PREVIEW_CACHE_LIMIT = 50;

@Component({
  selector: 'app-document-preview',
  standalone: true,
  imports: [IconComponent, NgTemplateOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open()) {
      <div class="fixed inset-0 z-[80] bg-black/55 backdrop-blur-sm flex items-center justify-center p-4">
        <section class="w-full max-w-5xl max-h-[88vh] rounded-lg overflow-hidden bg-gray-950 text-white ring-1 ring-white/10 shadow-2xl">
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
          <div class="h-[72vh] overflow-auto bg-gray-900">
            @if (loading()) {
              <div class="flex h-full items-center justify-center gap-2 text-sm text-gray-300">
                <app-icon name="loader-2" [size]="16" class="animate-spin text-cyan-300" />
                Loading preview...
              </div>
            } @else if (error()) {
              <div class="flex h-full items-center justify-center p-6 text-center">
                <div class="max-w-md rounded bg-red-500/10 p-4 text-sm text-red-100 ring-1 ring-red-500/20">
                  {{ error() }}
                </div>
              </div>
            } @else if (preview(); as doc) {
              @if (htmlSrcdoc()) {
                <div class="relative h-full">
                  @if (doc.truncated) {
                    <span class="absolute right-3 top-3 z-10 rounded bg-yellow-500/90 px-2 py-0.5 text-[10px] font-semibold text-black shadow ring-1 ring-yellow-600/40">Truncated preview</span>
                  }
                  <iframe
                    class="block h-full w-full bg-white"
                    sandbox=""
                    [srcdoc]="htmlSrcdoc()!"
                    title="HTML document preview"
                  ></iframe>
                </div>
              } @else if (doc.kind === 'text') {
                <pre class="min-h-full whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed text-gray-100">{{ doc.content || '' }}</pre>
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
                        @for (row of doc.rows || []; track $index) {
                          <tr class="border-b border-white/10 last:border-b-0">
                            @for (cell of row; track $index) {
                              <td class="max-w-[320px] border-r border-white/10 px-3 py-2 align-top last:border-r-0">{{ cell }}</td>
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
                @if (safeObjectUrl()) {
                  <iframe
                    class="block h-full w-full bg-white"
                    [src]="safeObjectUrl()!"
                    title="Document preview"
                  ></iframe>
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
        </section>
      </div>
    }

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
  private loadSeq = 0;
  private currentPreviewUrl: string | null = null;
  private previewRequestSub: Subscription | null = null;
  private mediaRequestSub: Subscription | null = null;

  readonly open = input(false);
  readonly previewUrl = input<string | null>(null);
  readonly title = input('');
  readonly subtitle = input('');
  readonly page = input<number | null>(null);
  readonly closed = output<void>();

  readonly loading = signal(false);
  readonly openingExternal = signal(false);
  readonly error = signal<string | null>(null);
  readonly mediaLoading = signal(false);
  readonly mediaError = signal<string | null>(null);
  readonly preview = signal<RichDocumentPreview | null>(null);
  readonly objectUrl = signal<string | null>(null);
  readonly safeObjectUrl = signal<SafeResourceUrl | null>(null);
  readonly htmlSrcdoc = computed(() => {
    const doc = this.preview();
    if (!doc || !this.isHtmlPreview(doc)) return null;
    return this.buildHtmlSrcdoc(doc);
  });
  readonly normalizedPage = computed(() => {
    const raw = this.page();
    if (raw === null || raw === undefined) return null;
    const value = typeof raw === 'number' ? raw : Number.parseInt(String(raw), 10);
    return Number.isFinite(value) && value > 0 ? value : null;
  });

  readonly displayName = computed(() => this.preview()?.filename || this.title() || 'document');

  constructor() {
    this.destroyRef.onDestroy(() => this.clearPreview());
    effect(() => {
      const url = this.previewUrl();
      this.normalizedPage();
      if (!this.open() || !url) {
        this.clearPreview();
        return;
      }
      this.loadPreview(url);
      this.applyPdfPageAnchor();
    });
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
    if (this.currentPreviewUrl === url && (this.loading() || this.preview())) return;
    const seq = ++this.loadSeq;
    this.currentPreviewUrl = url;
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

  private applyPdfPageAnchor(): void {
    const preview = this.preview();
    const objectUrl = this.objectUrl();
    if (!preview || preview.kind !== 'pdf' || !objectUrl) return;
    this.safeObjectUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(this.pdfObjectUrl(objectUrl)));
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
          this.safeObjectUrl.set(preview.kind === 'pdf' ? this.sanitizer.bypassSecurityTrustResourceUrl(this.pdfObjectUrl(url)) : null);
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
    this.safeObjectUrl.set(null);
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

  private buildHtmlSrcdoc(doc: RichDocumentPreview): string {
    const raw = doc.content || '';
    const chrome = `
      <meta charset="utf-8">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob: http: https:; style-src 'unsafe-inline'; font-src data:; script-src 'none'; connect-src 'none';">
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
      </style>
    `;
    if (/<html[\s>]/i.test(raw)) {
      if (/<head[\s>]/i.test(raw)) {
        return raw.replace(/<head([^>]*)>/i, `<head$1>${chrome}`);
      }
      return raw.replace(/<html([^>]*)>/i, `<html$1><head>${chrome}</head>`);
    }
    return `<!doctype html><html><head>${chrome}</head><body>${raw}</body></html>`;
  }

  private withDisposition(url: string, disposition: 'inline' | 'attachment'): string {
    const separator = url.includes('?') ? '&' : '?';
    return url.includes('disposition=') ? url : `${url}${separator}disposition=${disposition}`;
  }

  private pdfObjectUrl(url: string): string {
    const page = this.normalizedPage();
    return page ? `${url}#page=${page}` : url;
  }

  private errorMessage(err: unknown): string {
    const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
    if (typeof detail === 'string') return detail;
    return `Unable to load ${this.displayName()}.`;
  }
}
