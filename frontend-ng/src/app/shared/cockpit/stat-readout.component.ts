import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type CkReadoutTone = 'neutral' | 'pos' | 'neg' | 'cool' | 'violet' | 'warn';
export type CkReadoutAlign = 'start' | 'end';

/**
 * Reproduces the StatusReadout / StatReadout pattern from
 * docs/mockups/primitives.jsx — a label-over-value stack with mono ALL-CAPS
 * label, semantically coloured tabular-numerics value and optional delta.
 *
 * Used by the title bar (THRPT/LATENCY/YIELD) and by every Hypervisor /
 * Steering surface to keep the readout grammar consistent.
 */
@Component({
  selector: 'ck-stat-readout',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      [style.display]="'flex'"
      [style.flexDirection]="'column'"
      [style.gap.px]="2"
      [style.alignItems]="align === 'end' ? 'flex-end' : 'flex-start'"
    >
      <span
        class="ck-mono"
        [style.fontSize.px]="9"
        [style.letterSpacing]="'0.14em'"
        [style.textTransform]="'uppercase'"
        [style.color]="'var(--ck-fg-4)'"
      >{{ label }}</span>
      <span
        class="ck-mono ck-tnum"
        [style.fontSize.px]="size"
        [style.fontWeight]="500"
        [style.letterSpacing]="'-0.01em'"
        [style.color]="toneColor"
        [style.lineHeight]="'1'"
      >{{ value }}</span>
      @if (delta !== null && delta !== undefined && delta !== '') {
        <span
          class="ck-mono ck-tnum"
          [style.fontSize.px]="9"
          [style.color]="deltaColor"
        >{{ delta }}</span>
      }
    </div>
  `,
})
export class StatReadoutComponent {
  @Input() label = '';
  @Input() value: string | number = '—';
  @Input() delta: string | number | null = null;
  @Input() tone: CkReadoutTone = 'neutral';
  @Input() deltaTone: CkReadoutTone | null = null;
  @Input() size = 14;
  @Input() align: CkReadoutAlign = 'start';

  get toneColor(): string {
    return resolveTone(this.tone, 'var(--ck-fg-1)');
  }

  get deltaColor(): string {
    return resolveTone(this.deltaTone ?? this.tone, 'var(--ck-fg-3)');
  }
}

function resolveTone(tone: CkReadoutTone, fallback: string): string {
  switch (tone) {
    case 'pos':    return 'var(--ck-signal-pos)';
    case 'neg':    return 'var(--ck-signal-neg)';
    case 'cool':   return 'var(--ck-signal-cool)';
    case 'violet': return 'var(--ck-signal-violet)';
    case 'warn':   return 'var(--ck-signal-warn)';
    case 'neutral':
    default:       return fallback;
  }
}
