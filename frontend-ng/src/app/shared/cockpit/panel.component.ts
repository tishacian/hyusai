import { DOCUMENT } from '@angular/common';
import { A11yModule } from '@angular/cdk/a11y';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Injectable,
  Input,
  OnDestroy,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { GlyphComponent } from './glyph.component';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { CK_PANEL_MAX_WIDTH, CK_PANEL_MIN_WIDTH, clampPanelWidth } from './panel-resize';

export type CkPanelPosition = 'side' | 'bottom' | 'floating';

export interface CkPanelRef {
  id: string;
  position: CkPanelPosition;
  close: () => void;
}

/**
 * `PanelHostService` — coordinates open `<ck-panel>` instances so only the
 * topmost one consumes Escape. Also lets feature code open panels via a
 * future imperative API (not used yet; kept minimal).
 */
@Injectable({ providedIn: 'root' })
export class PanelHostService {
  private readonly workspace = inject(WorkspaceService);
  private readonly stack = signal<CkPanelRef[]>([]);
  readonly open = computed(() => this.stack().length > 0);
  readonly top = computed(() => {
    const s = this.stack();
    return s.length > 0 ? s[s.length - 1] : null;
  });

  constructor() {
    this.workspace.registerContextReset(() => this.closeAll());
  }

  push(ref: CkPanelRef): void {
    this.stack.update((s) => [...s, ref]);
  }

  pop(id: string): void {
    this.stack.update((s) => s.filter((r) => r.id !== id));
  }

  /** Close the topmost panel (used by global Escape in the shell outlet). */
  closeTop(): void {
    const ref = this.top();
    if (ref) ref.close();
  }

  closeAll(): void {
    for (const ref of [...this.stack()].reverse()) ref.close();
    this.stack.set([]);
  }
}

let panelCounter = 0;

/**
 * `<ck-panel>` — contextual surface (side / bottom / floating) that enriches
 * the canvas without changing the page. Use for:
 *   - `side`     detail / edit / settings tied to the current object.
 *   - `bottom`   logs / timeline / traces.
 *   - `floating` quick actions / comparisons / simulations.
 *
 * Panels are **never** a replacement for a tab — they are transient,
 * opportunistic views. See docs/mental-model.md §5bis.6.
 *
 * Two-way binding:  `<ck-panel [(open)]="panelOpen" position="side" title="Settings">…</ck-panel>`
 * Close on `Escape` (topmost panel only, via `PanelHostService`).
 */
@Component({
  selector: 'ck-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, GlyphComponent],
  template: `
    @if (open) {
      <div
        [attr.role]="modal || position === 'floating' ? 'dialog' : 'complementary'"
        [attr.aria-modal]="modal || position === 'floating' ? 'true' : null"
        [attr.aria-label]="title || 'Panel'"
        [cdkTrapFocus]="modal || position === 'floating'"
        [cdkTrapFocusAutoCapture]="modal || position === 'floating'"
        [style.position]="'fixed'"
        [style.top]="position === 'side' ? '0' : (position === 'bottom' ? 'auto' : '50%')"
        [style.right]="position === 'side' ? '0' : (position === 'bottom' ? '0' : '50%')"
        [style.bottom]="position === 'bottom' ? '0' : 'auto'"
        [style.left]="position === 'side' ? 'auto' : (position === 'bottom' ? '0' : '50%')"
        [style.transform]="position === 'floating' ? 'translate(50%, -50%)' : 'none'"
        [style.width]="position === 'side' ? effectiveWidth : (position === 'bottom' ? '100%' : effectiveWidth)"
        [style.maxWidth]="'100vw'"
        [style.boxSizing]="'border-box'"
        [style.height]="position === 'bottom' ? height : (position === 'side' ? '100vh' : 'auto')"
        [style.maxHeight]="position === 'floating' ? '80vh' : 'none'"
        [style.background]="'var(--ck-bg-1, #0a0e14)'"
        [style.borderLeft]="position === 'side' ? '1px solid var(--ck-stroke-2, rgba(255,255,255,0.08))' : 'none'"
        [style.borderTop]="position === 'bottom' ? '1px solid var(--ck-stroke-2, rgba(255,255,255,0.08))' : 'none'"
        [style.border]="position === 'floating' ? '1px solid var(--ck-stroke-2, rgba(255,255,255,0.08))' : 'initial'"
        [style.borderRadius.px]="position === 'floating' ? 10 : 0"
        [style.boxShadow]="'var(--ck-shadow-panel)'"
        [style.display]="'flex'"
        [style.flexDirection]="'column'"
        [style.zIndex]="modal || position === 'floating' ? 1400 : 40"
        [style.animation]="enterAnim"
      >
        @if (resizable && position === 'side') {
          <button
            type="button"
            role="separator"
            class="panel-resize-handle"
            aria-orientation="vertical"
            [attr.aria-label]="i18n.t('chat.overlay.resize')"
            [attr.aria-valuemin]="CK_PANEL_MIN_WIDTH"
            [attr.aria-valuemax]="maxWidth"
            [attr.aria-valuenow]="manualWidth || parseWidth(width)"
            [title]="i18n.t('chat.overlay.resize')"
            (pointerdown)="startResize($event)"
            (keydown)="resizeFromKeyboard($event)"
          ></button>
        }
        <header
          [style.display]="'flex'"
          [style.alignItems]="'center'"
          [style.justifyContent]="'space-between'"
          [style.padding]="'14px 18px'"
          [style.borderBottom]="'1px solid var(--ck-stroke-2, rgba(255,255,255,0.06))'"
          [style.flexShrink]="0"
        >
          <div
            [style.display]="'flex'"
            [style.flexDirection]="'column'"
            [style.gap.px]="2"
          >
            @if (eyebrow) {
              <span
                class="ck-mono"
                [style.fontSize.px]="9"
                [style.letterSpacing]="'0.14em'"
                [style.textTransform]="'uppercase'"
                [style.color]="'var(--ck-fg-4)'"
              >
                {{ eyebrow }}
              </span>
            }
            <h2
              [style.fontSize.px]="14"
              [style.fontWeight]="600"
              [style.margin]="'0'"
              [style.color]="'var(--ck-fg-1)'"
            >
              {{ title }}
            </h2>
          </div>
          <button
            type="button"
            (click)="close()"
            [style.background]="'transparent'"
            [style.border]="'1px solid var(--ck-stroke-2, rgba(255,255,255,0.08))'"
            [style.borderRadius.px]="4"
            [style.padding]="'4px 6px'"
            [style.cursor]="'pointer'"
            [style.color]="'var(--ck-fg-3)'"
            [attr.aria-label]="i18n.t('common.close')"
            [title]="i18n.t('common.close')"
          >
            <ck-glyph name="x" [size]="12" color="currentColor" />
          </button>
        </header>
        <div
          [style.flex]="'1 1 auto'"
          [style.overflow]="'auto'"
          [style.padding]="'18px'"
        >
          <ng-content />
        </div>
      </div>
      @if (position === 'floating') {
        <div
          [style.position]="'fixed'"
          [style.inset]="'0'"
          [style.background]="'var(--ck-scrim)'"
          [style.zIndex]="1399"
          [style.animation]="'ckPanelFade 160ms var(--ck-ease-out, ease-out)'"
          (click)="close()"
          aria-hidden="true"
        ></div>
      }
    }
  `,
  styles: [`
    @keyframes ckPanelSlideRight {
      from { transform: translateX(100%); }
      to   { transform: translateX(0); }
    }
    @keyframes ckPanelSlideUp {
      from { transform: translateY(100%); }
      to   { transform: translateY(0); }
    }
    @keyframes ckPanelPop {
      from { transform: translate(50%, -50%) scale(0.96); opacity: 0; }
      to   { transform: translate(50%, -50%) scale(1); opacity: 1; }
    }
    @keyframes ckPanelFade {
      from { opacity: 0; }
      to   { opacity: 1; }
    }
    .panel-resize-handle {
      position: absolute;
      top: 0;
      bottom: 0;
      left: -6px;
      width: 13px;
      padding: 0;
      border: 0;
      background: transparent;
      cursor: ew-resize;
      touch-action: none;
      z-index: 2;
    }
    .panel-resize-handle::after {
      content: '';
      position: absolute;
      top: 50%;
      left: 5px;
      width: 3px;
      height: 52px;
      border-radius: 999px;
      background: var(--ck-stroke-2, rgba(255, 255, 255, 0.14));
      opacity: 0;
      transform: translateY(-50%);
      transition: opacity 140ms ease;
    }
    .panel-resize-handle:hover::after,
    .panel-resize-handle:focus-visible::after { opacity: 1; }
    .panel-resize-handle:focus-visible {
      outline: 2px solid var(--ck-signal-cool, #67d5f6);
      outline-offset: -2px;
    }
  `],
})
export class CkPanelComponent implements OnInit, OnDestroy {
  private _open = false;
  @Input()
  set open(value: boolean) {
    if (value === this._open) return;
    if (value) {
      this.previousFocus = this.document.activeElement instanceof HTMLElement
        ? this.document.activeElement
        : null;
    }
    this._open = value;
    this.syncRegistration();
    if (!value) this.restoreFocus();
  }
  get open(): boolean { return this._open; }
  @Output() openChange = new EventEmitter<boolean>();
  @Input() position: CkPanelPosition = 'side';
  @Input() title = '';
  @Input() eyebrow = '';
  @Input() width = '420px';
  @Input() height = '320px';
  @Input() modal = false;
  @Input() resizable = false;
  @Input() resizeStorageKey = '';

  readonly CK_PANEL_MIN_WIDTH = CK_PANEL_MIN_WIDTH;
  manualWidth = 0;
  private resizeStartX = 0;
  private resizeStartWidth = 0;

  private readonly panelHost = inject(PanelHostService);
  private readonly document = inject(DOCUMENT);
  readonly i18n = inject(I18nService);
  private readonly id = `ck-panel-${++panelCounter}`;
  private registered = false;
  private previousFocus: HTMLElement | null = null;

  ngOnInit(): void {
    this.restoreWidth();
    this.syncRegistration();
  }

  ngOnDestroy(): void {
    if (this.registered) {
      this.panelHost.pop(this.id);
      this.registered = false;
    }
    this.restoreFocus();
  }

  private syncRegistration(): void {
    if (this._open && !this.registered) {
      this.panelHost.push({
        id: this.id,
        position: this.position,
        close: () => this.close(),
      });
      this.registered = true;
    } else if (!this._open && this.registered) {
      this.panelHost.pop(this.id);
      this.registered = false;
    }
  }

  close(): void {
    if (!this._open) return;
    this._open = false;
    if (this.registered) {
      this.panelHost.pop(this.id);
      this.registered = false;
    }
    this.openChange.emit(false);
    this.restoreFocus();
  }

  private restoreFocus(): void {
    const target = this.previousFocus;
    this.previousFocus = null;
    if (!target) return;
    queueMicrotask(() => {
      if (target.isConnected) target.focus();
    });
  }

  get effectiveWidth(): string {
    if (this.resizable && this.manualWidth) return `${this.manualWidth}px`;
    return this.width;
  }

  get maxWidth(): number {
    const viewport = this.document.defaultView?.innerWidth || CK_PANEL_MAX_WIDTH;
    return Math.min(CK_PANEL_MAX_WIDTH, Math.round(viewport * 0.92));
  }

  parseWidth(value: string): number {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : CK_PANEL_MIN_WIDTH;
  }

  private restoreWidth(): void {
    if (!this.resizable || !this.resizeStorageKey) return;
    const stored = Number.parseInt(
      this.document.defaultView?.localStorage?.getItem(this.resizeStorageKey) || '',
      10,
    );
    if (Number.isFinite(stored)) {
      this.manualWidth = clampPanelWidth(stored, CK_PANEL_MIN_WIDTH, this.maxWidth);
    }
  }

  private saveWidth(): void {
    if (!this.resizeStorageKey || !this.manualWidth) return;
    try {
      this.document.defaultView?.localStorage?.setItem(
        this.resizeStorageKey,
        String(this.manualWidth),
      );
    } catch {
      // Storage is an enhancement; resizing still works for this session.
    }
  }

  startResize(event: PointerEvent): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const target = event.currentTarget as HTMLElement;
    this.resizeStartX = event.clientX;
    this.resizeStartWidth = this.manualWidth || this.parseWidth(this.width);
    target.setPointerCapture(event.pointerId);
    target.addEventListener('pointermove', this.onResizePointerMove);
    target.addEventListener('pointerup', this.onResizePointerUp);
    target.addEventListener('pointercancel', this.onResizePointerUp);
  }

  private readonly onResizePointerMove = (event: PointerEvent): void => {
    // The side panel is anchored right: moving left increases its width.
    this.manualWidth = clampPanelWidth(
      this.resizeStartWidth + this.resizeStartX - event.clientX,
      CK_PANEL_MIN_WIDTH,
      this.maxWidth,
    );
  };

  private readonly onResizePointerUp = (event: PointerEvent): void => {
    const target = event.currentTarget as HTMLElement;
    target.removeEventListener('pointermove', this.onResizePointerMove);
    target.removeEventListener('pointerup', this.onResizePointerUp);
    target.removeEventListener('pointercancel', this.onResizePointerUp);
    if (target.hasPointerCapture?.(event.pointerId)) target.releasePointerCapture(event.pointerId);
    this.saveWidth();
  };

  resizeFromKeyboard(event: KeyboardEvent): void {
    const current = this.manualWidth || this.parseWidth(this.width);
    const next = event.key === 'ArrowLeft' ? current + 32
      : event.key === 'ArrowRight' ? current - 32
      : event.key === 'Home' ? this.maxWidth
      : event.key === 'End' ? CK_PANEL_MIN_WIDTH
      : current;
    if (next === current) return;
    event.preventDefault();
    this.manualWidth = clampPanelWidth(next, CK_PANEL_MIN_WIDTH, this.maxWidth);
    this.saveWidth();
  }

  get enterAnim(): string {
    switch (this.position) {
      case 'side':     return 'ckPanelSlideRight 200ms var(--ck-ease-out, ease-out)';
      case 'bottom':   return 'ckPanelSlideUp 200ms var(--ck-ease-out, ease-out)';
      case 'floating': return 'ckPanelPop 180ms var(--ck-ease-out, ease-out)';
    }
  }
}

/**
 * `<app-panel-host>` — shell-level placeholder that owns the global Escape
 * handler so the topmost panel closes without each panel duplicating the
 * listener. Place once inside `ShellComponent`.
 */
@Component({
  selector: 'app-panel-host',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: ``,
})
export class CkPanelHostComponent {
  private readonly panelHost = inject(PanelHostService);

  @HostListener('window:keydown.escape', ['$event'])
  onEscape(ev: Event): void {
    if (!this.panelHost.open()) return;
    ev.preventDefault();
    this.panelHost.closeTop();
  }
}
