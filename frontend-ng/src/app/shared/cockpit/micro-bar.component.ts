import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type CkSignalTone = 'pos' | 'neg' | 'warn' | 'cool' | 'violet' | 'neutral';

/**
 * Tiny progress bar — 80×4 by default — with optional glow. Matches the
 * MicroBar primitive from docs/mockups/primitives.jsx. Used for capacity,
 * confidence, headroom indicators inside cockpit tables.
 */
@Component({
  selector: 'ck-micro-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      [style.display]="'inline-block'"
      [style.width.px]="width"
      [style.height.px]="height"
      [style.borderRadius.px]="height / 2"
      [style.background]="'var(--ck-stroke-2)'"
      [style.position]="'relative'"
      [style.overflow]="'hidden'"
    >
      <span
        [style.position]="'absolute'"
        [style.left]="'0'"
        [style.top]="'0'"
        [style.bottom]="'0'"
        [style.width.%]="clamped"
        [style.background]="toneVar"
        [style.borderRadius.px]="height / 2"
        [style.boxShadow]="glow ? '0 0 8px ' + toneVar : null"
        [style.transition]="'width 240ms var(--ck-ease-out)'"
      ></span>
    </span>
  `,
})
export class MicroBarComponent {
  @Input() width = 80;
  @Input() height = 4;
  @Input() value = 0;
  @Input() max = 100;
  @Input() glow = true;
  @Input() tone: CkSignalTone = 'cool';

  get clamped(): number {
    const v = this.max === 0 ? 0 : (this.value / this.max) * 100;
    return Math.max(0, Math.min(100, v));
  }

  get toneVar(): string {
    switch (this.tone) {
      case 'pos':     return 'var(--ck-signal-pos)';
      case 'neg':     return 'var(--ck-signal-neg)';
      case 'warn':    return 'var(--ck-signal-warn)';
      case 'violet':  return 'var(--ck-signal-violet)';
      case 'neutral': return 'var(--ck-fg-3)';
      case 'cool':
      default:        return 'var(--ck-signal-cool)';
    }
  }
}
