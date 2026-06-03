import { HttpClient } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

import { IconComponent } from '@app/shared/ui/icon.component';

interface RichDocumentPreview {
  kind: 'text' | 'spreadsheet' | 'image' | 'pdf' | 'binary';
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

@Component({
  selector: 'app-document-preview',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open()) {
      <div class="fixed inset-0 z-[80] bg-black/55 backdrop-blur-sm flex items-center justify-center p-4">
        <section class="w-full max-w-5xl max-h-[88vh] rounded-lg overflow-hidden bg-gray-950 text-white ring-1 ring-white/10 shadow-2xl">
          <header class="flex items-center justify-between gap-3 px-4 py-3 border-b border-white/10">
            <div class="min-w-0">
              <p class="text-[10px] uppercase tracking-[0.18em] text-cyan-300">{{ subtitle() || 'Document' }}</p>
              <h2 class="mt-0.5 truncate text-sm font-semibold">{{ title() || 'Preview' }}</h2>
            </div>
            <div class="flex items-center gap-2">
              @if (previewUrl()) {
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                  [disabled]="openingExternal()"
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
              @if (doc.kind === 'text') {
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
              } @else if (doc.kind === 'image' && objectUrl()) {
                <div class="flex h-full items-center justify-center p-4">
                  <img [src]="objectUrl()!" [alt]="doc.filename" class="max-h-full max-w-full object-contain" />
                </div>
              } @else if (doc.kind === 'pdf' && safeObjectUrl()) {
                <iframe
                  class="block h-full w-full bg-white"
                  [src]="safeObjectUrl()!"
                  title="Document preview"
                ></iframe>
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
  `,
})
export class DocumentPreviewComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly http = inject(HttpClient);
  private readonly sanitizer = inject(DomSanitizer);
  private loadSeq = 0;

  readonly open = input(false);
  readonly previewUrl = input<string | null>(null);
  readonly title = input('');
  readonly subtitle = input('');
  readonly closed = output<void>();

  readonly loading = signal(false);
  readonly openingExternal = signal(false);
  readonly error = signal<string | null>(null);
  readonly preview = signal<RichDocumentPreview | null>(null);
  readonly objectUrl = signal<string | null>(null);
  readonly safeObjectUrl = signal<SafeResourceUrl | null>(null);

  readonly displayName = computed(() => this.preview()?.filename || this.title() || 'document');

  constructor() {
    this.destroyRef.onDestroy(() => this.clearPreview());
    effect(() => {
      const url = this.previewUrl();
      if (!this.open() || !url) {
        this.clearPreview();
        return;
      }
      this.loadPreview(url);
    });
  }

  openExternal(): void {
    const doc = this.preview();
    const url = doc?.download_url || this.previewUrl();
    if (!url) return;
    this.openingExternal.set(true);
    this.http
      .get(this.withDisposition(url, 'inline'), { responseType: 'blob' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          const objectUrl = URL.createObjectURL(blob);
          window.open(objectUrl, '_blank', 'noopener,noreferrer');
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
    const seq = ++this.loadSeq;
    this.revokeObjectUrl();
    this.loading.set(true);
    this.error.set(null);
    this.preview.set(null);
    this.http
      .get<RichDocumentPreview>(url)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (preview) => {
          if (seq !== this.loadSeq) return;
          this.preview.set(preview);
          if (preview.kind === 'image' || preview.kind === 'pdf') {
            this.loadPreviewBlob(preview, seq);
          } else {
            this.loading.set(false);
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
    this.http
      .get(this.withDisposition(preview.download_url, 'inline'), { responseType: 'blob' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          if (seq !== this.loadSeq) return;
          const url = URL.createObjectURL(blob);
          this.objectUrl.set(url);
          this.safeObjectUrl.set(preview.kind === 'pdf' ? this.sanitizer.bypassSecurityTrustResourceUrl(url) : null);
          this.loading.set(false);
        },
        error: (err) => {
          if (seq !== this.loadSeq) return;
          this.loading.set(false);
          this.error.set(this.errorMessage(err));
        },
      });
  }

  private clearPreview(): void {
    ++this.loadSeq;
    this.loading.set(false);
    this.openingExternal.set(false);
    this.error.set(null);
    this.preview.set(null);
    this.revokeObjectUrl();
  }

  private revokeObjectUrl(): void {
    const url = this.objectUrl();
    if (url) URL.revokeObjectURL(url);
    this.objectUrl.set(null);
    this.safeObjectUrl.set(null);
  }

  private withDisposition(url: string, disposition: 'inline' | 'attachment'): string {
    const separator = url.includes('?') ? '&' : '?';
    return url.includes('disposition=') ? url : `${url}${separator}disposition=${disposition}`;
  }

  private errorMessage(err: unknown): string {
    const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
    if (typeof detail === 'string') return detail;
    return `Unable to load ${this.displayName()}.`;
  }
}
