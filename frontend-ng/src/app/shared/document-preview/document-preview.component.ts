import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';

import { IconComponent } from '@app/shared/ui/icon.component';

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
                <a
                  class="inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                  [href]="previewUrl()!"
                  target="_blank"
                  rel="noreferrer"
                >
                  <app-icon name="external-link" [size]="13" />
                  Open
                </a>
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
          <div class="bg-gray-900">
            @if (previewUrl()) {
              <iframe
                class="block h-[72vh] w-full bg-white"
                [src]="safePreviewUrl()"
                title="Document preview"
              ></iframe>
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
  private readonly sanitizer = inject(DomSanitizer);

  readonly open = input(false);
  readonly previewUrl = input<string | null>(null);
  readonly title = input('');
  readonly subtitle = input('');
  readonly closed = output<void>();

  readonly safePreviewUrl = computed(() =>
    this.sanitizer.bypassSecurityTrustResourceUrl(this.previewUrl() || 'about:blank'),
  );
}
