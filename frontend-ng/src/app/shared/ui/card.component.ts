import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';
import { NgClass } from '@angular/common';

export type CardVariant = 'default' | 'elevated' | 'ck-surface' | 'gradient-border';

/**
 * Canonical surface card. Use for every grouped content block in the UI.
 * Variants map to the legacy design system.
 */
@Component({
  selector: 'app-card',
  standalone: true,
  imports: [NgClass],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div [ngClass]="classes()" [class.p-5]="padded" [attr.data-accent]="accent ? '' : null">
      <ng-content />
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
      }
      .ck-surface[data-accent] {
        border-left: 3px solid var(--accent);
        background: linear-gradient(135deg, var(--bg-card) 0%, var(--accent-soft) 100%);
      }
    `,
  ],
})
export class CardComponent {
  @Input() variant: CardVariant = 'default';
  @Input() padded: boolean = true;
  /** Add a 3px cyan left border and subtle gradient background. */
  @Input() accent: boolean = false;
  @Input() hoverLift: boolean = false;
  @Input() clickable: boolean = false;

  protected readonly classes = computed(() => {
    const base = ['ck-surface', 'rounded-md'];
    if (this.variant === 'elevated') base.push('t-elevated');
    if (this.variant === 'ck-surface') base.push('ck-surface');
    if (this.variant === 'gradient-border') base.push('ring-1', 'ring-cyan-500/30');
    if (this.hoverLift) base.push('transition-transform', 'hover:-translate-y-0.5');
    if (this.clickable) base.push('cursor-pointer');
    return base.join(' ');
  });
}
