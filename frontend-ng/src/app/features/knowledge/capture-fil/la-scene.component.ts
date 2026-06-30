import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService, type CapturePinnedView, type CaptureSessionDocument } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import { CaptureEngine } from './capture-engine';
import { ViewTileComponent } from './view-tile.component';
import { documentToPinnedView, viewTitle } from './capture-presentation';

/**
 * La Scène (Phase 2 / D3) — one active piece "EN SCÈNE" (enlarged) plus a
 * horizontal film strip of the other pinned pieces. The focused view is what
 * the deictic pointing references (it feeds the engine's `visual_context`).
 * Clicking a strip thumbnail brings it on scene.
 */
@Component({
  selector: 'app-la-scene',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, ViewTileComponent, DocumentPreviewComponent],
  template: `
    <section
      class="ck-surface"
      style="border-radius:8px; padding:16px 16px 12px; display:flex; flex-direction:column; gap:12px; min-height:200px;"
    >
      <div style="display:flex; align-items:center; gap:8px; position:relative;">
        <ck-glyph name="layers" [size]="13" color="var(--ck-fg-3)" />
        <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
          La Scène · {{ engine.scene().length }} pièce{{ engine.scene().length > 1 ? 's' : '' }}
        </span>
        <div style="margin-left:auto; display:flex; align-items:center; gap:8px;">
          @if (active(); as a) {
            @if (previewUrlFor(a)) {
              <button
                type="button"
                class="ck-mono"
                (click)="openPreview(a)"
                title="Voir le document en grand"
                style="border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-3); cursor:pointer; font-size:10px; border-radius:var(--ck-radius-sm); padding:3px 7px; display:inline-flex; align-items:center; gap:4px;"
              >
                <ck-glyph name="layers" [size]="10" color="currentColor" /> voir
              </button>
            }
            <button
              type="button"
              class="ck-mono"
              (click)="engine.markActiveView()"
              title="Marquer cette pièce dans le fil"
              style="border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-3); cursor:pointer; font-size:10px; border-radius:var(--ck-radius-sm); padding:3px 7px; display:inline-flex; align-items:center; gap:4px;"
            >
              <ck-glyph name="crosshair" [size]="10" color="currentColor" /> marquer dans le fil
            </button>
            <button
              type="button"
              class="ck-mono"
              (click)="engine.unpinView(a.key)"
              title="Retirer de la scène"
              style="border:none; background:transparent; color:var(--ck-fg-4); cursor:pointer; font-size:10px; display:inline-flex; align-items:center; gap:4px;"
            >
              <ck-glyph name="x" [size]="10" color="currentColor" /> retirer
            </button>
          }
          <label
            class="ck-mono"
            title="Ajouter une pièce à montrer (elle est mise en scène)"
            style="border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-3); cursor:pointer; font-size:10px; border-radius:var(--ck-radius-sm); padding:3px 7px; display:inline-flex; align-items:center; gap:4px;"
            [style.opacity]="uploading() ? 0.6 : 1"
          >
            <ck-glyph name="bolt" [size]="10" color="currentColor" /> {{ uploading() ? 'ajout…' : 'ajouter' }}
            <input type="file" multiple (change)="onUpload($event)" [disabled]="uploading()" style="display:none;" />
          </label>
          @if (pinnable().length > 0) {
            <button
              type="button"
              class="ck-mono"
              (click)="picking.set(!picking())"
              style="border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-3); cursor:pointer; font-size:10px; border-radius:var(--ck-radius-sm); padding:3px 7px; display:inline-flex; align-items:center; gap:4px;"
            >
              <ck-glyph name="layers" [size]="10" color="currentColor" /> épingler
            </button>
          }
        </div>
        @if (picking()) {
          <div
            class="ck-scroll"
            style="position:absolute; top:calc(100% + 4px); right:0; z-index:20; min-width:200px; max-height:220px; overflow-y:auto; padding:4px; background:var(--ck-bg-panel-hi); border:1px solid var(--ck-stroke-3); border-radius:var(--ck-radius-md); box-shadow:var(--ck-shadow-card);"
          >
            @for (doc of pinnable(); track doc.document_id || doc.filename || $index) {
              <button
                type="button"
                (click)="pin(doc)"
                style="display:flex; align-items:center; gap:8px; width:100%; text-align:left; padding:7px 9px; border:none; background:transparent; border-radius:var(--ck-radius-sm); cursor:pointer; color:var(--ck-fg-2);"
              >
                <ck-glyph name="ledger" [size]="13" color="var(--ck-fg-4)" />
                <span class="ck-mono" style="font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                  {{ doc.filename || doc.title || 'document' }}
                </span>
              </button>
            }
          </div>
        }
      </div>

      @if (active(); as a) {
        <div style="display:flex; justify-content:center;">
          <div style="width:100%; max-width:320px;">
            <app-capture-view-tile
              [view]="a"
              size="xl"
              [active]="true"
              [clickable]="!!previewUrlFor(a)"
              (picked)="openPreview(a)"
            />
          </div>
        </div>
      } @else {
        <div
          style="min-height:120px; border:1px dashed var(--ck-stroke-3); border-radius:var(--ck-radius-md); display:grid; place-items:center; color:var(--ck-fg-5); font-size:12px; text-align:center; padding:12px;"
        >
          Aucune pièce montrée — épinglez un document pour le mettre « en scène ».
        </div>
      }

      @if (engine.scene().length > 0) {
        <div class="ck-scroll" style="display:flex; gap:8px; overflow-x:auto; padding-bottom:4px;">
          @for (piece of engine.scene(); track piece.key) {
            <div style="flex:none; width:84px;">
              <app-capture-view-tile
                [view]="piece"
                size="sm"
                [active]="piece.key === engine.activeViewKey()"
                [dim]="piece.key !== engine.activeViewKey()"
                [clickable]="true"
                (picked)="engine.focusView(piece.key)"
              />
            </div>
          }
        </div>
      }
    </section>

    <app-document-preview
      [open]="previewOpen()"
      [previewUrl]="previewUrl()"
      [title]="previewTitle()"
      [subtitle]="'Pièce montrée'"
      [page]="previewPage()"
      (closed)="previewOpen.set(false)"
    />
  `,
})
export class LaSceneComponent {
  protected readonly engine = inject(CaptureEngine);
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly active = this.engine.activeView;
  protected readonly picking = signal(false);
  protected readonly uploading = signal(false);

  // ---- real document preview (rich-preview modal, auth-aware) -------------
  protected readonly previewOpen = signal(false);
  protected readonly previewUrl = signal<string | null>(null);
  protected readonly previewTitle = signal('');
  protected readonly previewPage = signal<number | null>(null);

  /**
   * Build the auth-aware `rich-preview` URL for a pinned piece (the modal fetches
   * it via HttpClient so the bearer token rides along). Falls back to the
   * session-level collection when the piece itself carries none.
   */
  protected previewUrlFor(view: CapturePinnedView): string | null {
    const documentId = view.document_id;
    const collection = view.collection ?? this.engine.documentsCollection();
    if (!documentId || !collection) return null;
    let url =
      `${this.api.base}/documents/${encodeURIComponent(documentId)}/rich-preview` +
      `?collection_name=${encodeURIComponent(collection)}`;
    if (view.filename) url += `&filename=${encodeURIComponent(view.filename)}`;
    return url;
  }

  protected openPreview(view: CapturePinnedView): void {
    const url = this.previewUrlFor(view);
    if (!url) return;
    this.previewUrl.set(url);
    this.previewTitle.set(viewTitle(view));
    this.previewPage.set(view.page ?? null);
    this.previewOpen.set(true);
  }

  /** Documents attached to the session that aren't already on scene. */
  protected readonly pinnable = computed<CaptureSessionDocument[]>(() => {
    const pinnedKeys = new Set(this.engine.scene().map((p) => p.key));
    return this.engine
      .documents()
      .filter((doc) => !pinnedKeys.has(documentToPinnedView(doc).key));
  });

  protected pin(doc: CaptureSessionDocument): void {
    this.engine.pinView(documentToPinnedView(doc));
    this.picking.set(false);
  }

  /**
   * Upload pieces **during** the session (not only at plan time): the freshly
   * added documents are auto-pinned to La Scène so the expert can point at them
   * right away.
   */
  protected onUpload(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = input.files;
    const sessionId = this.engine.sessionId();
    if (!files || !files.length || !sessionId) return;
    const beforeKeys = new Set(this.engine.documents().map((d) => documentToPinnedView(d).key));
    this.uploading.set(true);
    this.api
      .uploadCaptureDocuments(sessionId, files)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: async () => {
          await this.engine.loadDocuments();
          for (const doc of this.engine.documents()) {
            const view = documentToPinnedView(doc);
            if (!beforeKeys.has(view.key)) this.engine.pinView(view);
          }
          this.uploading.set(false);
          input.value = '';
        },
        error: () => {
          this.uploading.set(false);
        },
      });
  }
}
