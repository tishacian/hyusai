import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Input,
  computed,
  inject,
  signal,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import type { CapturePinnedView, CaptureViewReference } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine } from './capture-engine';
import { refToPinnedView, toneVar, viewLocation, viewTitle, viewTone } from './capture-presentation';

type AnchorDisplay = 'pending' | 'confirmed' | 'lowconf' | 'discarded';

/** Ghost auto-confirm window (D2 / sim.jsx HYBRID_CONFIRM). */
const HYBRID_CONFIRM_MS = 4200;

/**
 * AnchorChip (Phase 3 / D2) — the inline deictic anchor rendered in Le Fil.
 * Four states:
 *  - `pending`   ghost: dashed neutral border, 2 s breathing, 4200 ms auto-confirm
 *                countdown (purely client-side — zero backend cost);
 *  - `confirmed` solid, tinted to the piece, check glyph;
 *  - `lowconf`   amber dashed when confidence < 0.7 (ambiguous deictic);
 *  - `discarded` struck-through, neutral, reversible.
 *
 * Only corrections (`discard` / `rebind`) and the explicit lowconf `OK` hit the
 * backend via {@link CaptureEngine.updateView}; the ghost countdown does not.
 * Honours `prefers-reduced-motion`.
 */
@Component({
  selector: 'app-anchor-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    @let v = view;
    @if (v) {
      @switch (display()) {
        @case ('discarded') {
          <span
            class="ck-mono"
            style="display:inline-flex; align-items:center; gap:6px; font-size:12px; color:var(--ck-fg-5); text-decoration:line-through; opacity:0.62;"
          >
            <ck-glyph name="crosshair" [size]="12" color="currentColor" />
            {{ i18n.t('capture.anchor.cancelled', { title: title }) }}
            <button
              type="button"
              class="ck-mono"
              (click)="restore()"
              style="text-decoration:none; border:none; background:transparent; color:var(--ck-fg-4); cursor:pointer; font-size:10px;"
            >
              {{ i18n.t('capture.anchor.restore') }}
            </button>
          </span>
        }
        @default {
          <span style="display:inline-flex; flex-direction:column; gap:6px; max-width:480px;">
            <button
              type="button"
              class="anc-pill"
              [class.anc-breathe]="display() === 'pending'"
              (click)="focusPiece()"
              [title]="i18n.t('capture.anchor.restage')"
              style="appearance:none; cursor:pointer; display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:999px; align-self:flex-start; color:var(--ck-fg-1); font-family:var(--ck-font-sans);"
              [style.background]="ghostly() ? 'transparent' : tintMix"
              [style.border]="'1px ' + (ghostly() ? 'dashed' : 'solid') + ' ' + edgeColor()"
            >
              <ck-glyph name="crosshair" [size]="13" [color]="accent()" />
              <span style="font-size:12.5px; font-weight:600;">{{ title }}</span>
              <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ location }}</span>
              @if (display() === 'confirmed') {
                <ck-glyph name="check" [size]="12" [color]="tint" />
              }
            </button>

            @if (display() === 'pending' && !rebinding()) {
              <span style="display:inline-flex; align-items:center; gap:8px; padding-left:4px; flex-wrap:wrap;">
                <span class="ck-mono" style="font-size:10.5px; color:var(--ck-fg-4);">
                  {{ i18n.t('capture.anchor.auto_confirm', { seconds: secondsLeft() }) }}
                </span>
                <button type="button" class="anc-btn" (click)="confirm()" [style.--anc-accent]="'var(--ck-signal-pos)'">
                  <ck-glyph name="check" [size]="11" color="currentColor" /> {{ i18n.t('capture.anchor.confirm') }}
                </button>
                <button type="button" class="anc-btn" (click)="startRebind()">
                  <ck-glyph name="crosshair" [size]="11" color="currentColor" /> {{ i18n.t('capture.anchor.rebind') }}
                </button>
                <button type="button" class="anc-btn" (click)="discard()" [style.--anc-accent]="'var(--ck-signal-neg)'">
                  <ck-glyph name="x" [size]="11" color="currentColor" />
                </button>
              </span>
            }

            @if (display() === 'lowconf' && !rebinding()) {
              <span style="display:inline-flex; align-items:center; gap:8px; padding-left:4px; flex-wrap:wrap;">
                <span class="ck-mono" style="font-size:10.5px; color:var(--ck-signal-warn);">
                  {{ phrase
                    ? i18n.t('capture.anchor.uncertain_phrase', { phrase: phrase })
                    : i18n.t('capture.anchor.uncertain') }}
                </span>
                <button type="button" class="anc-btn" (click)="startRebind()" [style.--anc-accent]="'var(--ck-signal-warn)'">
                  <ck-glyph name="crosshair" [size]="11" color="currentColor" /> {{ i18n.t('capture.anchor.correct') }}
                </button>
                <button type="button" class="anc-btn" (click)="accept()">
                  <ck-glyph name="check" [size]="11" color="currentColor" /> OK
                </button>
              </span>
            }

            @if (rebinding()) {
              <span style="display:flex; flex-wrap:wrap; gap:6px; padding-left:4px; align-items:center;">
                <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ i18n.t('capture.anchor.rebind_to') }}</span>
                @for (piece of engine.scene(); track piece.key) {
                  <button
                    type="button"
                    class="anc-btn"
                    (click)="rebind(piece)"
                    [style.--anc-accent]="piece.key === activeKey ? 'var(--ck-signal-cool)' : null"
                  >
                    {{ pieceLabel(piece) }}
                  </button>
                }
                @if (engine.scene().length === 0) {
                  <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-5);">{{ i18n.t('capture.scene.empty_short') }}</span>
                }
                <button type="button" class="anc-btn" (click)="cancelRebind()">
                  <ck-glyph name="x" [size]="11" color="currentColor" />
                </button>
              </span>
            }
          </span>
        }
      }
    }
  `,
  styles: [
    `
      @keyframes anc-breathe {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.55; }
      }
      .anc-breathe {
        animation: anc-breathe 2s var(--ck-ease-in-out) infinite;
      }
      .anc-btn {
        appearance: none;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-family: var(--ck-font-sans);
        font-size: 11px;
        font-weight: 550;
        padding: 3px 8px;
        border-radius: var(--ck-radius-sm);
        cursor: pointer;
        border: 1px solid var(--anc-accent, var(--ck-stroke-2));
        background: transparent;
        color: var(--anc-accent, var(--ck-fg-2));
        transition: background var(--ck-dur-fast) var(--ck-ease-out);
      }
      .anc-btn:hover {
        background: var(--ck-tint-soft);
      }
      @media (prefers-reduced-motion: reduce) {
        .anc-breathe { animation: none; }
      }
    `,
  ],
})
export class AnchorChipComponent {
  readonly i18n = inject(I18nService);
  protected readonly engine = inject(CaptureEngine);
  private readonly destroyRef = inject(DestroyRef);

  private readonly viewSig = signal<CaptureViewReference | undefined>(undefined);
  /** The journaled deictic reference this chip represents. */
  @Input()
  set view(value: CaptureViewReference | undefined) {
    this.viewSig.set(value);
    if (value && this.ghost() === null) this.initGhost(value);
    // A backend correction (lowconf/discard/confirm) ends the ghost phase.
    if (value && (value.status === 'lowconf' || value.status === 'discarded')) {
      this.clearGhost();
    }
  }
  get view(): CaptureViewReference | undefined {
    return this.viewSig();
  }

  private readonly ghost = signal<boolean | null>(null);
  protected readonly secondsLeft = signal(Math.ceil(HYBRID_CONFIRM_MS / 1000));
  protected readonly rebinding = signal(false);
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    this.destroyRef.onDestroy(() => this.stopTimer());
  }

  protected get title(): string {
    const v = this.viewSig();
    const fallback = this.i18n.t('capture.piece.fallback');
    return v ? viewTitle(v, fallback) : fallback;
  }
  protected get location(): string {
    const v = this.viewSig();
    return v
      ? viewLocation(v, (index) => this.i18n.t('capture.view.snapshot', { index }))
      : '';
  }
  protected get phrase(): string {
    const v = this.viewSig();
    return v?.statement ?? v?.trigger_phrase ?? '';
  }
  protected get tint(): string {
    const v = this.viewSig();
    return v ? toneVar(viewTone(v)) : 'var(--ck-signal-cool)';
  }
  protected get tintMix(): string {
    return `color-mix(in oklab, ${this.tint} 12%, transparent)`;
  }
  protected get activeKey(): string | null {
    return this.engine.activeViewKey();
  }

  protected readonly display = computed<AnchorDisplay>(() => {
    const v = this.viewSig();
    if (!v) return 'pending';
    if (v.status === 'discarded') return 'discarded';
    const ambiguous = v.status === 'lowconf' || (v.confidence != null && v.confidence < 0.7);
    if (ambiguous) return 'lowconf';
    if (this.ghost()) return 'pending';
    return 'confirmed';
  });

  protected ghostly(): boolean {
    const d = this.display();
    return d === 'pending' || d === 'lowconf';
  }

  protected accent(): string {
    const d = this.display();
    if (d === 'lowconf') return 'var(--ck-signal-warn)';
    if (d === 'pending') return 'var(--ck-fg-3)';
    return this.tint;
  }

  protected edgeColor(): string {
    const d = this.display();
    if (d === 'lowconf') return 'var(--ck-signal-warn)';
    if (d === 'pending') return 'var(--ck-fg-3)';
    return `color-mix(in oklab, ${this.tint} 60%, transparent)`;
  }

  protected pieceLabel(piece: CapturePinnedView): string {
    return piece.title ?? piece.filename ?? this.i18n.t('capture.piece.fallback');
  }

  /**
   * Clicking the pill brings the referenced piece back "EN SCÈNE": focus the
   * matching pin when it's still on scene, otherwise re-pin it from the anchor
   * (without re-journaling a view — this is navigation, not a new mark).
   */
  protected focusPiece(): void {
    const v = this.viewSig();
    if (!v) return;
    const match = this.engine.scene().find(
      (p) =>
        (v.document_id && p.document_id === v.document_id) ||
        (!v.document_id && v.filename && p.filename === v.filename),
    );
    if (match) {
      this.engine.focusView(match.key);
      if (v.page != null) this.engine.setActiveViewPage(v.page);
      return;
    }
    this.engine.pinView(refToPinnedView(v), { record: false });
  }

  protected confirm(): void {
    this.clearGhost();
    const id = this.eventId();
    if (id) this.engine.confirmAnchorLocal(id);
  }

  /** Accept an ambiguous (lowconf) association — persists confidence=1 (T0.3). */
  protected accept(): void {
    this.clearGhost();
    const id = this.eventId();
    if (id) void this.engine.updateView(id, { action: 'confirm' });
  }

  protected discard(): void {
    this.clearGhost();
    const id = this.eventId();
    if (id) void this.engine.updateView(id, { action: 'discard' });
  }

  protected restore(): void {
    const id = this.eventId();
    if (id) void this.engine.updateView(id, { action: 'confirm' });
  }

  protected startRebind(): void {
    this.clearGhost();
    this.rebinding.set(true);
  }

  protected cancelRebind(): void {
    this.rebinding.set(false);
  }

  protected rebind(piece: CapturePinnedView): void {
    this.rebinding.set(false);
    this.engine.focusView(piece.key);
    const id = this.eventId();
    if (!id) return;
    // If the target piece is the one currently shown, prefer the LIVE page from
    // the active pin (kept in sync by the inline/modal preview) over the strip
    // pin's possibly stale page snapshot.
    const activePin = this.engine.activeView();
    const livePage =
      activePin && activePin.key === piece.key && activePin.page != null
        ? activePin.page
        : piece.page;
    void this.engine.updateView(id, {
      action: 'rebind',
      document_id: piece.document_id,
      page: livePage,
      slide: piece.slide,
      image_index: piece.image_index,
    });
  }

  private eventId(): string | null {
    const v = this.viewSig();
    return v?.event_id ?? v?.turn_id ?? null;
  }

  private initGhost(view: CaptureViewReference): void {
    const ambiguous = view.status === 'lowconf' || (view.confidence != null && view.confidence < 0.7);
    if (view.status === 'discarded' || ambiguous) {
      this.ghost.set(false);
      return;
    }
    this.ghost.set(true);
    const startedAt = Date.now();
    const tick = () => {
      const remaining = Math.max(0, HYBRID_CONFIRM_MS - (Date.now() - startedAt));
      this.secondsLeft.set(Math.ceil(remaining / 1000));
      if (remaining <= 0) this.confirm();
    };
    tick();
    this.timer = setInterval(tick, 200);
  }

  private clearGhost(): void {
    this.stopTimer();
    this.ghost.set(false);
  }

  private stopTimer(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
