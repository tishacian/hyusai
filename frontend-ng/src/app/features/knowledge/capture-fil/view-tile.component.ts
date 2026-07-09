import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import type { CapturePinnedView, CaptureViewReference } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { toneVar, viewLocation, viewTitle, viewTone } from './capture-presentation';

type TilePiece = CapturePinnedView | CaptureViewReference;
type TileSize = 'sm' | 'md' | 'xl';

/**
 * Clean thumbnail card for a document view (page / slide / image). No real
 * asset — a soft tinted surface + centered document/image glyph + mono caption,
 * tinted to the piece. The report inspector renders the live document instead;
 * La Scène uses these tiles for the film strip (and the fallback active view).
 */
@Component({
  selector: 'app-capture-view-tile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    @let piece = view;
    @if (piece) {
      <button
        type="button"
        [title]="(piece.title ?? piece.filename ?? '') + ' · ' + location()"
        (click)="picked.emit()"
        [style.cursor]="clickable ? 'pointer' : 'default'"
        [style.position]="'relative'"
        [style.width]="'100%'"
        [style.aspectRatio]="'4 / 3'"
        [style.background]="'var(--ck-bg-inset)'"
        [style.border]="'1px solid ' + (active ? tint() : 'var(--ck-stroke-2)')"
        [style.borderRadius]="'var(--ck-radius-md)'"
        [style.overflow]="'hidden'"
        [style.opacity]="dim ? 0.5 : 1"
        [style.boxShadow]="active ? '0 0 0 1px ' + tint() + ', 0 0 22px color-mix(in oklab, ' + tint() + ' 28%, transparent)' : 'none'"
        [style.padding]="'0'"
        [style.transition]="'opacity var(--ck-dur-med) var(--ck-ease-out), box-shadow var(--ck-dur-med)'"
      >
        <!-- clean page-like surface: a soft tinted wash instead of the hatched
             "fake text" stripes that read as an unfinished placeholder. -->
        <span
          [style.position]="'absolute'"
          [style.inset]="'0'"
          [style.background]="'linear-gradient(155deg, color-mix(in oklab, ' + tint() + ' 13%, var(--ck-bg-panel)) 0%, var(--ck-bg-inset) 64%)'"
        ></span>
        <!-- centered document / image mark as the thumbnail's visual -->
        <span
          [style.position]="'absolute'"
          [style.inset]="'0'"
          [style.display]="'grid'"
          [style.placeItems]="'center'"
          [style.paddingBottom.px]="16"
          [style.color]="tint()"
          [style.opacity]="0.6"
        >
          <ck-glyph [name]="isImage() ? 'cube' : 'ledger'" [size]="size === 'sm' ? 22 : 34" color="currentColor" />
        </span>
        @if (active) {
          <span
            [style.position]="'absolute'"
            [style.top.px]="6"
            [style.right.px]="6"
            [style.display]="'inline-flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="4"
            [style.padding]="'2px 6px'"
            [style.borderRadius]="'999px'"
            [style.background]="'var(--ck-bg-void)'"
            [style.border]="'1px solid ' + tint()"
          >
            <span class="ck-live-dot" [style.width.px]="5" [style.height.px]="5" [style.background]="tint()"></span>
            <span class="ck-mono" [style.fontSize.px]="8.5" [style.letterSpacing]="'0.1em'" [style.color]="tint()" [style.fontWeight]="700">
              EN SCÈNE
            </span>
          </span>
        }
        <span
          [style.position]="'absolute'"
          [style.left]="'0'"
          [style.right]="'0'"
          [style.bottom]="'0'"
          [style.padding]="'7px 9px'"
          [style.background]="'linear-gradient(0deg, var(--ck-bg-void) 30%, transparent)'"
          [style.display]="'flex'"
          [style.flexDirection]="'column'"
          [style.gap.px]="2"
        >
          <span class="ck-mono" [style.fontSize.px]="10.5" [style.color]="'var(--ck-fg-1)'" [style.fontWeight]="600" [style.lineHeight]="1.15">
            {{ title() }}
          </span>
          <span class="ck-mono" [style.fontSize.px]="9" [style.color]="'var(--ck-fg-4)'" [style.letterSpacing]="'0.04em'">
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
  @Output() picked = new EventEmitter<void>();

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
