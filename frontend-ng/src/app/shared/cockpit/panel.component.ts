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
  private readonly stack = signal<CkPanelRef[]>([]);
  readonly open = computed(() => this.stack().length > 0);
  readonly top = computed(() => {
    const s = this.stack();
    return s.length > 0 ? s[s.length - 1] : null;
  });

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
  imports: [GlyphComponent],
  template: `
    @if (open) {
      <div
        [attr.role]="position === 'floating' ? 'dialog' : 'complementary'"
        [attr.aria-modal]="position === 'floating' ? 'true' : null"
        [attr.aria-label]="title || 'Panel'"
        [style.position]="'fixed'"
        [style.top]="position === 'side' ? '0' : (position === 'bottom' ? 'auto' : '50%')"
        [style.right]="position === 'side' ? '0' : (position === 'bottom' ? '0' : '50%')"
        [style.bottom]="position === 'bottom' ? '0' : 'auto'"
        [style.left]="position === 'side' ? 'auto' : (position === 'bottom' ? '0' : '50%')"
        [style.transform]="position === 'floating' ? 'translate(50%, -50%)' : 'none'"
        [style.width]="position === 'side' ? width : (position === 'bottom' ? '100%' : width)"
        [style.height]="position === 'bottom' ? height : (position === 'side' ? '100vh' : 'auto')"
        [style.maxHeight]="position === 'floating' ? '80vh' : 'none'"
        [style.background]="'var(--ck-bg-1, #0a0e14)'"
        [style.borderLeft]="position === 'side' ? '1px solid var(--ck-stroke-2, rgba(255,255,255,0.08))' : 'none'"
        [style.borderTop]="position === 'bottom' ? '1px solid var(--ck-stroke-2, rgba(255,255,255,0.08))' : 'none'"
        [style.border]="position === 'floating' ? '1px solid var(--ck-stroke-2, rgba(255,255,255,0.08))' : 'initial'"
        [style.borderRadius.px]="position === 'floating' ? 10 : 0"
        [style.boxShadow]="'0 20px 60px rgba(0,0,0,0.5)'"
        [style.display]="'flex'"
        [style.flexDirection]="'column'"
        [style.zIndex]="40"
        [style.animation]="enterAnim"
      >
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
            [attr.aria-label]="'Close panel'"
            title="Close (Esc)"
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
          [style.background]="'rgba(0,0,0,0.45)'"
          [style.zIndex]="39"
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
  `],
})
export class CkPanelComponent implements OnInit, OnDestroy {
  private _open = false;
  @Input()
  set open(value: boolean) {
    if (value === this._open) return;
    this._open = value;
    this.syncRegistration();
  }
  get open(): boolean { return this._open; }
  @Output() openChange = new EventEmitter<boolean>();
  @Input() position: CkPanelPosition = 'side';
  @Input() title = '';
  @Input() eyebrow = '';
  @Input() width = '420px';
  @Input() height = '320px';

  private readonly panelHost = inject(PanelHostService);
  private readonly id = `ck-panel-${++panelCounter}`;
  private registered = false;

  ngOnInit(): void {
    this.syncRegistration();
  }

  ngOnDestroy(): void {
    if (this.registered) {
      this.panelHost.pop(this.id);
      this.registered = false;
    }
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
    const target = ev.target as HTMLElement | null;
    const tag = target?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (target?.isContentEditable) return;
    ev.preventDefault();
    this.panelHost.closeTop();
  }
}
