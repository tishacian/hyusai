import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type CkTagTone = 'neutral' | 'pos' | 'neg' | 'cool' | 'violet' | 'warn';
export type CkTagVariant = 'soft' | 'outline' | 'solid';

/**
 * Mono ALL-CAPS tag — the cockpit grammar for status / category labels.
 * 6 tones × 3 variants. Renders as a small inline pill with 2×6 padding
 * and 9px mono type, matching the Tag primitive from
 * docs/mockups/primitives.jsx.
 */
@Component({
  selector: 'ck-tag',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="ck-mono"
      [style.display]="'inline-flex'"
      [style.alignItems]="'center'"
      [style.gap.px]="4"
      [style.padding]="'2px 6px'"
      [style.fontSize.px]="9"
      [style.lineHeight]="'1'"
      [style.letterSpacing]="'0.12em'"
      [style.textTransform]="'uppercase'"
      [style.fontWeight]="500"
      [style.borderRadius.px]="3"
      [style.color]="textColor"
      [style.background]="bg"
      [style.border]="border"
    >
      <ng-content></ng-content>
    </span>
  `,
})
export class TagComponent {
  @Input() tone: CkTagTone = 'neutral';
  @Input() variant: CkTagVariant = 'soft';

  private get color(): string {
    switch (this.tone) {
      case 'pos':    return 'var(--ck-signal-pos)';
      case 'neg':    return 'var(--ck-signal-neg)';
      case 'cool':   return 'var(--ck-signal-cool)';
      case 'violet': return 'var(--ck-signal-violet)';
      case 'warn':   return 'var(--ck-signal-warn)';
      case 'neutral':
      default:       return 'var(--ck-fg-3)';
    }
  }

  private get rgba(): string {
    switch (this.tone) {
      case 'pos':    return 'rgba(52,211,153,0.12)';
      case 'neg':    return 'rgba(239,90,111,0.14)';
      case 'cool':   return 'rgba(125,211,252,0.12)';
      case 'violet': return 'rgba(167,139,250,0.14)';
      case 'warn':   return 'rgba(245,184,74,0.12)';
      case 'neutral':
      default:       return 'rgba(255,255,255,0.04)';
    }
  }

  get textColor(): string {
    return this.variant === 'solid' ? '#05070a' : this.color;
  }

  get bg(): string {
    switch (this.variant) {
      case 'solid':   return this.color;
      case 'outline': return 'transparent';
      case 'soft':
      default:        return this.rgba;
    }
  }

  get border(): string {
    if (this.variant === 'outline') return `1px solid ${this.color}`;
    return '1px solid transparent';
  }
}
