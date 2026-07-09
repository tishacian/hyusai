import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import type { CapturePinnedView, CaptureViewReference } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import { toneVar, viewLocation, viewTitle, viewTone } from './capture-presentation';

type TilePiece = CapturePinnedView | CaptureViewReference;
type TileSize = 'sm' | 'md' | 'xl';

/**
 * Thumbnail card for a document view (page / slide / image): a media box (real
 * chromeless preview when a `previewUrl` is given, else a tinted glyph card)
 * above a SOLID caption footer. Keeping the title/page out of the image (rather
 * than overlaid) guarantees legible contrast whatever the thumbnail shows.
 * La Scène uses these tiles for the film strip (and the fallback active view).
 */
@Component({
  selector: 'app-capture-view-tile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, DocumentPreviewComponent],
  template: `
    @let piece = view;
    @if (piece) {
      <button
        type="button"
        [title]="(piece.title ?? piece.filename ?? '') + ' · ' + location()"
        (click)="picked.emit()"
        [style.cursor]="clickable ? 'pointer' : 'default'"
        [style.display]="'flex'"
        [style.flexDirection]="'column'"
        [style.width]="'100%'"
        [style.background]="'var(--ck-bg-panel)'"
        [style.border]="'1px solid ' + (active ? tint() : 'var(--ck-stroke-2)')"
        [style.borderRadius]="'var(--ck-radius-md)'"
        [style.overflow]="'hidden'"
        [style.opacity]="dim ? 0.5 : 1"
        [style.boxShadow]="active ? '0 0 0 1px ' + tint() + ', 0 0 22px color-mix(in oklab, ' + tint() + ' 28%, transparent)' : 'none'"
        [style.padding]="'0'"
        [style.transition]="'opacity var(--ck-dur-med) var(--ck-ease-out), box-shadow var(--ck-dur-med)'"
      >
        <!-- media box: real preview or tinted fallback; the caption lives in a
             solid footer below so its contrast never depends on the page bg. -->
        <span
          [style.position]="'relative'"
          [style.display]="'block'"
          [style.width]="'100%'"
          [style.aspectRatio]="previewUrl ? null : '4 / 3'"
          [style.height.px]="previewUrl ? heightPx() : null"
          [style.background]="'var(--ck-bg-inset)'"
          [style.overflow]="'hidden'"
        >
          @if (previewUrl) {
            <app-document-preview
              [style.position]="'absolute'"
              [style.inset]="'0'"
              [style.display]="'block'"
              [inline]="true"
              [thumbnail]="true"
              [previewUrl]="previewUrl"
              [page]="page ?? null"
              [heightPx]="heightPx()"
            />
          } @else {
            <span
              [style.position]="'absolute'"
              [style.inset]="'0'"
              [style.background]="'linear-gradient(155deg, color-mix(in oklab, ' + tint() + ' 13%, var(--ck-bg-panel)) 0%, var(--ck-bg-inset) 64%)'"
            ></span>
            <span
              [style.position]="'absolute'"
              [style.inset]="'0'"
              [style.display]="'grid'"
              [style.placeItems]="'center'"
              [style.color]="tint()"
              [style.opacity]="0.6"
            >
              <ck-glyph [name]="isImage() ? 'cube' : 'ledger'" [size]="size === 'sm' ? 22 : 34" color="currentColor" />
            </span>
          }
          @if (active) {
            <span
              [style.position]="'absolute'"
              [style.top.px]="5"
              [style.right.px]="5"
              [style.display]="'inline-flex'"
              [style.alignItems]="'center'"
              [style.gap.px]="4"
              [style.padding]="'2px 7px'"
              [style.borderRadius]="'999px'"
              [style.background]="'color-mix(in oklab, var(--ck-bg-void) 88%, transparent)'"
              [style.border]="'1px solid ' + tint()"
              [style.boxShadow]="'0 1px 6px color-mix(in oklab, var(--ck-bg-void) 55%, transparent)'"
            >
              <span class="ck-live-dot" [style.width.px]="5" [style.height.px]="5" [style.background]="tint()"></span>
              <span class="ck-mono" [style.fontSize.px]="8.5" [style.letterSpacing]="'0.1em'" [style.color]="tint()" [style.fontWeight]="700">
                EN SCÈNE
              </span>
            </span>
          }
        </span>

        <!-- solid caption footer: title/page never overlap the preview -->
        <span
          [style.flex]="'none'"
          [style.padding]="'6px 9px'"
          [style.borderTop]="'1px solid var(--ck-stroke-2)'"
          [style.background]="active ? 'color-mix(in oklab, ' + tint() + ' 6%, var(--ck-bg-panel))' : 'var(--ck-bg-panel)'"
          [style.borderLeft]="active ? '3px solid ' + tint() : '3px solid transparent'"
          [style.display]="'flex'"
          [style.flexDirection]="'column'"
          [style.gap.px]="2"
          [style.textAlign]="'left'"
        >
          <span
            class="ck-mono"
            [style.fontSize.px]="10.5"
            [style.color]="'var(--ck-fg-1)'"
            [style.fontWeight]="650"
            [style.lineHeight]="1.2"
            [style.overflow]="'hidden'"
            [style.textOverflow]="'ellipsis'"
            [style.whiteSpace]="'nowrap'"
          >
            {{ title() }}
          </span>
          <span class="ck-mono" [style.fontSize.px]="9.5" [style.color]="'var(--ck-fg-2)'" [style.fontWeight]="600" [style.letterSpacing]="'0.04em'">
            {{ location() }}
          </span>
        </span>
      </button>
    }
  `,
})
export class ViewTileComponent {
  @Input() view?: TilePiece;
  @Input() size: TileSize = 'md';
  @Input() active = false;
  @Input() dim = false;
  @Input() clickable = false;
  /** Auth-aware rich-preview URL — when set, renders a real thumbnail. */
  @Input() previewUrl?: string | null;
  /** Page to render in the thumbnail (PDF). */
  @Input() page?: number | null;
  @Output() picked = new EventEmitter<void>();

  /** Fixed thumbnail box height per size (definite height for the PDF viewer). */
  protected heightPx(): number {
    return this.size === 'xl' ? 300 : this.size === 'md' ? 168 : 104;
  }

  protected tint(): string {
    return this.view ? toneVar(viewTone(this.view)) : 'var(--ck-signal-cool)';
  }
  protected title(): string {
    return this.view ? viewTitle(this.view) : 'Pièce';
  }
  protected location(): string {
    return this.view ? viewLocation(this.view) : '';
  }
  protected isImage(): boolean {
    return !!this.view && this.view.image_index != null;
  }
}
