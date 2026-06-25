import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import type { CaptureSessionDocument } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine } from './capture-engine';
import { ViewTileComponent } from './view-tile.component';
import { documentToPinnedView } from './capture-presentation';

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
  imports: [GlyphComponent, ViewTileComponent],
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
            <app-capture-view-tile [view]="a" size="xl" [active]="true" />
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
  `,
})
export class LaSceneComponent {
  protected readonly engine = inject(CaptureEngine);
  protected readonly active = this.engine.activeView;
  protected readonly picking = signal(false);

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
}
