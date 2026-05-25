import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import type { AssistantDraftOpenEffect } from '@app/core/assistant-effects.service';
import { GlyphComponent } from '@app/shared/cockpit';

interface CitedPassage {
  page?: number;
  text?: string;
  label?: string;
  bbox?: number[];
}

interface DraftPayload {
  kind?: string;
  mode?: string;
  target_type: string;
  target_id: string;
  subject?: string;
  recipient?: string;
  title?: string;
  body_markdown?: string;
  body?: string;
  page?: number;
  highlight?: string;
  citation?: string;
  download_url?: string;
  signed_url?: string;
  preview_url?: string;
  sources?: Array<string | { label?: string; title?: string; id?: string }>;
  metadata?: Record<string, unknown> & {
    document_url?: string;
    download_url?: string;
    pdf_url?: string;
    preview_url?: string;
    page?: number;
    total_pages?: number;
    citation?: string;
    cited_passages?: CitedPassage[];
    filename?: string;
  };
}

interface DraftValidationResponse {
  status: string;
  requires_validation?: boolean;
  sent?: boolean;
  title?: string;
  recipient?: string;
  subject?: string;
  body?: string;
  sources?: string[];
}

@Component({
  selector: 'app-assistant-draft-drawer',
  standalone: true,
  imports: [CommonModule, GlyphComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open()) {
      <div class="draft-backdrop" (click)="cancel()" aria-hidden="true"></div>
      <aside
        class="draft-drawer"
        [class.document-mode]="isDocumentPreview()"
        role="dialog"
        aria-label="Brouillon advisory"
      >
        <header>
          <div>
            <span class="eyebrow">{{ draftKind() }}</span>
            <h2>{{ draftTitle() }}</h2>
            @if (recipient()) {
              <p>{{ recipient() }}</p>
            }
          </div>
          <button type="button" class="icon-button" (click)="cancel()" aria-label="Fermer">
            <ck-glyph name="x" [size]="16" />
          </button>
        </header>

        @if (isDocumentPreview()) {
          <section class="doc-preview ck-scroll" aria-label="Aperçu document">
            @if (citedPassages().length) {
              <section class="doc-citation-preview ck-scroll" aria-label="Extraits cités par AYA">
                <span class="eyebrow">Aperçu document · extraits cités par AYA</span>
                @for (passage of citedPassages(); track $index) {
                  <article class="citation-page">
                    @if (passage.page) {
                      <strong>Page {{ passage.page }}</strong>
                    }
                    @if (passage.label) {
                      <em>{{ passage.label }}</em>
                    }
                    @if (passage.text) {
                      <p>« {{ passage.text }} »</p>
                    }
                  </article>
                }
                @if (downloadHref()) {
                  <p class="doc-citation-hint">
                    PDF complet disponible via « Télécharger ».
                  </p>
                }
              </section>
            } @else if (previewLoading()) {
              <p class="doc-fallback doc-loading">Chargement de l'aperçu PDF…</p>
            } @else if (documentUrl(); as url) {
              <iframe
                class="doc-frame"
                [src]="url"
                title="Aperçu document"
                loading="lazy"
              ></iframe>
            } @else {
              <p class="doc-fallback">
                {{ previewError() || "Aperçu indisponible — utilisez le bouton « Télécharger » pour ouvrir le document." }}
              </p>
            }
          </section>
        } @else {
          @if (subject()) {
            <div class="draft-subject">
              <span>Objet</span>
              <strong>{{ subject() }}</strong>
            </div>
          }

          <article class="draft-body ck-scroll">
            <pre>{{ bodyText() }}</pre>
          </article>

          @if (sourceLabels().length) {
            <section class="draft-sources">
              <span class="eyebrow">Sources</span>
              <ul>
                @for (source of sourceLabels(); track source) {
                  <li>{{ source }}</li>
                }
              </ul>
            </section>
          }
        }

        <footer>
          @if (isDocumentPreview()) {
            @if (downloadHref()) {
              <a
                class="action-button primary"
                [attr.href]="downloadHref()"
                [attr.download]="downloadFilename() || true"
                target="_blank"
                rel="noopener"
              >
                Télécharger
              </a>
            }
            <button type="button" class="action-button ghost" (click)="cancel()">
              Fermer
            </button>
          } @else {
            <button type="button" class="action-button primary" [disabled]="submitting()" (click)="validate()">
              Valider (advisory)
            </button>
            <button type="button" class="action-button" [disabled]="submitting()" (click)="modify()">
              Modifier
            </button>
            <button type="button" class="action-button ghost" (click)="cancel()">
              Annuler
            </button>
          }
        </footer>
      </aside>
    }
  `,
  styles: [
    `
      :host {
        display: contents;
        color: var(--mission-text-primary);
        font-family: var(--mission-font-body);
      }
      .draft-backdrop {
        position: fixed;
        inset: 0;
        z-index: 1200;
        background: rgba(2, 6, 10, 0.55);
        backdrop-filter: blur(6px);
        -webkit-backdrop-filter: blur(6px);
        animation: draft-fade var(--mission-dur-base) var(--mission-ease-out);
      }
      @keyframes draft-fade {
        from { opacity: 0; }
        to   { opacity: 1; }
      }
      .draft-drawer {
        position: fixed;
        top: 0;
        right: 0;
        z-index: 1201;
        width: min(480px, 100vw);
        height: 100vh;
        display: grid;
        grid-template-rows: auto auto 1fr auto auto;
        gap: var(--mission-space-3);
        padding: var(--mission-space-5) var(--mission-space-4);
        border-left: 1px solid var(--sentinel-accent-muted);
        background: rgba(5, 8, 12, 0.98);
        box-shadow: var(--mission-shadow-floating);
        animation: draft-slide-in var(--mission-dur-slow) var(--mission-ease-out);
      }
      .draft-drawer.document-mode {
        width: min(720px, 100vw);
        grid-template-rows: auto 1fr auto;
      }
      @keyframes draft-slide-in {
        from { transform: translateX(24px); opacity: 0; }
        to   { transform: translateX(0);    opacity: 1; }
      }
      .doc-preview {
        position: relative;
        min-height: 0;
        display: flex;
        flex-direction: column;
        gap: var(--mission-space-3);
        overflow: hidden;
      }
      .doc-frame {
        width: 100%;
        flex: 1 1 auto;
        min-height: 360px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: #fff;
      }
      .doc-fallback {
        margin: 0;
        padding: var(--mission-space-5);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-md);
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
      }
      .doc-loading {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 360px;
      }
      .doc-citation-preview {
        flex: 1 1 auto;
        min-height: 360px;
        padding: var(--mission-space-4);
        border: 1px solid rgba(241, 180, 90, 0.28);
        border-radius: var(--mission-radius-md);
        background: var(--mission-warning-soft);
        overflow: auto;
      }
      .doc-citation-preview > .eyebrow {
        color: var(--mission-warning);
      }
      .citation-page {
        margin-top: var(--mission-space-3);
        padding: var(--mission-space-3);
        border-left: 3px solid rgba(241, 180, 90, 0.55);
        background: rgba(241, 180, 90, 0.06);
        border-radius: var(--mission-radius-sm);
      }
      .citation-page strong {
        display: block;
        margin-bottom: var(--mission-space-1);
        font-family: var(--mission-font-mono);
        font-size: 11px;
        color: var(--mission-warning);
      }
      .citation-page em {
        display: block;
        margin-bottom: var(--mission-space-2);
        font-style: normal;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-xs);
      }
      .citation-page p {
        margin: 0;
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
        color: var(--mission-text-primary);
      }
      .doc-citation-hint {
        margin: var(--mission-space-3) 0 0;
        font-size: var(--mission-text-xs);
        color: var(--mission-text-tertiary);
        font-style: italic;
      }
      header, footer {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--mission-space-3);
      }
      footer { flex-wrap: wrap; }
      .eyebrow {
        display: block;
        color: var(--sentinel-accent);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      h2 {
        margin: var(--mission-space-1) 0 0;
        font-size: var(--mission-text-md);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: var(--mission-lh-tight);
      }
      header p {
        margin: var(--mission-space-1) 0 0;
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .icon-button {
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-secondary);
        padding: 6px;
        cursor: pointer;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          color var(--mission-dur-fast) var(--mission-ease-out);
      }
      .icon-button:hover {
        border-color: var(--sentinel-accent-muted);
        color: var(--mission-text-primary);
      }
      .icon-button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .draft-subject {
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: var(--mission-surface-1);
      }
      .draft-subject span {
        display: block;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
      }
      .draft-subject strong {
        display: block;
        margin-top: var(--mission-space-1);
        font-size: var(--mission-text-sm);
        line-height: 1.35;
      }
      .draft-body {
        min-height: 0;
        overflow: auto;
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: var(--mission-inset);
      }
      .draft-body pre {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-family: var(--mission-font-body);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
        color: var(--mission-text-primary);
      }
      .draft-sources ul {
        margin: var(--mission-space-2) 0 0;
        padding-left: var(--mission-space-5);
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-xs);
        line-height: var(--mission-lh-body);
      }
      .action-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 36px;
        padding: 8px var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: inherit;
        font: inherit;
        font-size: var(--mission-text-sm);
        cursor: pointer;
        text-decoration: none;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .action-button:hover { border-color: var(--sentinel-accent-muted); }
      .action-button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .action-button.primary {
        border-color: rgba(101, 214, 110, 0.42);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
        font-weight: 600;
      }
      .action-button.primary:hover:not(:disabled) {
        background: rgba(101, 214, 110, 0.18);
      }
      .action-button.ghost { background: transparent; }
      .action-button:disabled { opacity: 0.55; cursor: not-allowed; }
      @media (max-width: 760px) {
        .doc-citation-preview { max-height: 60vh; }
      }
      @media (prefers-reduced-motion: reduce) {
        .draft-drawer,
        .draft-backdrop { animation: none; }
      }
    `,
  ],
})
export class AssistantDraftDrawerComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);
  private readonly sanitizer = inject(DomSanitizer);

  readonly open = signal(false);
  readonly submitting = signal(false);
  readonly previewLoading = signal(false);
  readonly previewError = signal<string | null>(null);
  private readonly previewBlobUrl = signal<string | null>(null);

  /** PDF stubs below this size are treated as degraded placeholders. */
  private static readonly STUB_PDF_MAX_BYTES = 2048;
  private readonly payload = signal<DraftPayload | null>(null);

  readonly isDocumentPreview = computed(() => {
    const payload = this.payload();
    const kind = (payload?.kind || payload?.mode || '').toLowerCase();
    return kind === 'document_preview' || kind === 'preview' || kind === 'pdf_preview';
  });

  readonly documentUrl = computed<SafeResourceUrl | null>(() => {
    const blobUrl = this.previewBlobUrl();
    const href = blobUrl || this.rawDocumentHref();
    if (!href) return null;
    return this.sanitizer.bypassSecurityTrustResourceUrl(href);
  });

  readonly downloadHref = computed<string | null>(() => this.previewBlobUrl() || this.rawDocumentHref());

  readonly downloadFilename = computed<string | null>(() => {
    const meta = this.payload()?.metadata || {};
    return (meta.filename as string | undefined) || null;
  });

  readonly citedPassages = computed<CitedPassage[]>(() => {
    const payload = this.payload();
    if (!payload) return [];
    const meta = payload.metadata || {};
    const passages = (meta.cited_passages || []) as CitedPassage[];
    if (Array.isArray(passages) && passages.length) return passages;
    const page =
      typeof meta.page === 'number'
        ? meta.page
        : typeof payload.page === 'number'
          ? payload.page
          : undefined;
    const citation =
      (meta.citation as string | undefined)
      || payload.citation
      || payload.highlight;
    if (!page && !citation) return [];
    return [{ page, text: citation, label: payload.highlight }];
  });

  private readonly openListener = (event: Event) => {
    const detail = (event as CustomEvent<AssistantDraftOpenEffect>).detail;
    if (!detail?.target_id) return;
    const draftPayload = (detail.draft_payload || {}) as unknown as DraftPayload;
    this.payload.set({
      ...draftPayload,
      target_type: draftPayload.target_type || detail.target_type,
      target_id: draftPayload.target_id || detail.target_id,
    });
    this.open.set(true);
    this.loadDocumentPreview();
  };

  private rawDocumentHref(): string | null {
    const payload = this.payload();
    if (!payload) return null;
    const meta = payload.metadata || {};
    const base =
      payload.preview_url
      || payload.download_url
      || payload.signed_url
      || (meta.preview_url as string | undefined)
      || (meta.document_url as string | undefined)
      || (meta.pdf_url as string | undefined)
      || (meta.download_url as string | undefined);
    if (!base) return null;
    const page =
      typeof meta.page === 'number'
        ? meta.page
        : typeof payload.page === 'number'
          ? payload.page
          : undefined;
    if (page && !/[#?]/.test(base)) return `${base}#page=${page}`;
    return base;
  }

  private loadDocumentPreview(): void {
    this.revokePreviewBlobUrl();
    this.previewError.set(null);
    if (!this.isDocumentPreview()) {
      this.previewLoading.set(false);
      return;
    }
    const href = this.rawDocumentHref();
    if (!href) {
      if (!this.citedPassages().length) {
        this.previewError.set(
          'Aperçu indisponible — utilisez le bouton « Télécharger » pour ouvrir le document.',
        );
      }
      this.previewLoading.set(false);
      return;
    }
    // Always fetch the blob: it powers the authenticated "Télécharger" button
    // and, when citations are absent, the inline PDF iframe.
    const { path } = this.splitDocumentHref(href);
    const hasCitations = this.citedPassages().length > 0;
    this.previewLoading.set(!hasCitations);
    this.api.getBlob(path).subscribe({
      next: (blob) => {
        this.revokePreviewBlobUrl();
        if (this.shouldUseCitationPreview(blob)) {
          if (!hasCitations) {
            this.previewError.set(
              'Document PDF indisponible — utilisez le bouton « Télécharger » ou consultez les passages cités.',
            );
          }
          this.previewLoading.set(false);
          return;
        }
        // Blob URLs must not carry #page fragments — Chrome PDF viewer renders a blank frame.
        const objectUrl = URL.createObjectURL(blob);
        this.previewBlobUrl.set(objectUrl);
        this.previewLoading.set(false);
      },
      error: () => {
        this.previewLoading.set(false);
        if (!hasCitations) {
          this.previewError.set(
            'Aperçu indisponible — utilisez le bouton « Télécharger » pour ouvrir le document.',
          );
        }
      },
    });
  }

  private shouldUseCitationPreview(blob: Blob): boolean {
    if (blob.size < AssistantDraftDrawerComponent.STUB_PDF_MAX_BYTES) return true;
    const type = (blob.type || '').toLowerCase();
    if (type && type !== 'application/pdf' && type !== 'application/octet-stream') return true;
    return false;
  }

  private splitDocumentHref(href: string): { path: string; fragment: string } {
    const hashIdx = href.indexOf('#');
    const fragment = hashIdx >= 0 ? href.slice(hashIdx) : '';
    const withoutFragment = hashIdx >= 0 ? href.slice(0, hashIdx) : href;
    if (withoutFragment.startsWith('/api/v1')) {
      return { path: withoutFragment.slice('/api/v1'.length), fragment };
    }
    try {
      const parsed = new URL(withoutFragment, window.location.origin);
      if (parsed.pathname.startsWith('/api/v1')) {
        return { path: `${parsed.pathname.slice('/api/v1'.length)}${parsed.search}`, fragment };
      }
    } catch {
      // fall through
    }
    return { path: withoutFragment, fragment };
  }

  private revokePreviewBlobUrl(): void {
    const current = this.previewBlobUrl();
    if (current) {
      URL.revokeObjectURL(current.split('#')[0] ?? current);
    }
    this.previewBlobUrl.set(null);
  }

  ngOnInit(): void {
    window.addEventListener('agentium:assistant-draft-open', this.openListener);
  }

  ngOnDestroy(): void {
    window.removeEventListener('agentium:assistant-draft-open', this.openListener);
  }

  draftKind(): string {
    const payload = this.payload();
    return payload?.kind || payload?.target_type || 'Instruction advisory';
  }

  draftTitle(): string {
    const payload = this.payload();
    return payload?.title || payload?.subject || 'Brouillon AYA';
  }

  subject(): string | null {
    return this.payload()?.subject || null;
  }

  recipient(): string | null {
    return this.payload()?.recipient || null;
  }

  bodyText(): string {
    const payload = this.payload();
    return payload?.body_markdown || payload?.body || '';
  }

  sourceLabels(): string[] {
    const payload = this.payload();
    return (payload?.sources || []).map((source) => {
      if (typeof source === 'string') return source;
      return source.label || source.title || source.id || 'Source';
    });
  }

  validate(): void {
    const payload = this.payload();
    if (!payload) return;
    this.submitting.set(true);
    this.api
      .post<DraftValidationResponse>('/mission-room/actions/draft', {
        target_id: payload.target_id,
        target_type: payload.target_type,
        instruction_type: 'dircab_instruction',
        subject: payload.subject,
        recipient: payload.recipient,
        body: payload.body_markdown || payload.body,
        sources: this.sourceLabels(),
        metadata: payload.metadata || {},
      })
      .subscribe({
        next: (response) => {
          this.submitting.set(false);
          this.toast.success(response.title || 'Instruction advisory enregistree', 'Validation');
          this.cancel();
        },
        error: () => {
          this.submitting.set(false);
          this.toast.error('Validation advisory indisponible pour le moment.', 'Brouillon');
        },
      });
  }

  modify(): void {
    const payload = this.payload();
    if (!payload) return;
    window.dispatchEvent(
      new CustomEvent('agentium:assistant-navigate', {
        detail: {
          route: '/hypervisor/mission-room/cockpit',
          queryParams: { draft: payload.target_id },
        },
      }),
    );
    this.cancel();
  }

  cancel(): void {
    this.revokePreviewBlobUrl();
    this.previewLoading.set(false);
    this.previewError.set(null);
    this.open.set(false);
    this.payload.set(null);
    this.submitting.set(false);
  }
}
