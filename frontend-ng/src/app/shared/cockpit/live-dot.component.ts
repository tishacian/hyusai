import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type CkLiveTone = 'pos' | 'cool' | 'violet' | 'warn' | 'neg' | 'neutral';

/**
 * Animated pulsing live indicator. Double box-shadow (close + far) for the
 * "Living Organism" touch — the glow breathes around the dot rather than
 * being a thin halo. Optional label rendered to the right.
 */
@Component({
  selector: 'ck-live-dot',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      [style.display]="'inline-flex'"
      [style.alignItems]="'center'"
      [style.gap.px]="6"
    >
      <span class="ck-live-dot" [class.cool]="tone==='cool'" [class.violet]="tone==='violet'" [class.warn]="tone==='warn'" [class.neg]="tone==='neg'" [class.neutral]="tone==='neutral'"></span>
      @if (label) {
        <span
          [style.fontSize.px]="11"
          [style.color]="'var(--ck-fg-3)'"
        >{{ label }}</span>
      }
    </span>
  `,
})
export class LiveDotComponent {
  @Input() tone: CkLiveTone = 'pos';
  @Input() label = '';
}
