import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Centralised icon component. All icons come from Lucide (stroke-based,
 * tree-shakable). Register icon names in `icon-registry.ts` via `provideIcons`.
 *
 * Usage: `<app-icon name="layers" [size]="20" class="text-cyan-500" />`
 */
@Component({
  selector: 'app-icon',
  standalone: true,
  imports: [LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [
    `
      :host {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        line-height: 1;
      }
      :host ::ng-deep svg {
        width: 1em;
        height: 1em;
      }
    `,
  ],
  template: `
    <lucide-angular
      [name]="name"
      [size]="size"
      [strokeWidth]="strokeWidth"
      [style.width.px]="size"
      [style.height.px]="size"
      [attr.aria-hidden]="ariaLabel ? null : true"
      [attr.aria-label]="ariaLabel"
      [attr.role]="ariaLabel ? 'img' : null"
    ></lucide-angular>
  `,
})
export class IconComponent {
  @Input({ required: true }) set name(value: string) {
    this.iconName = this.normalizeIconName(value);
  }
  get name(): string {
    return this.iconName;
  }
  @Input() size: number = 18;
  @Input() strokeWidth: number = 1.75;
  @Input() ariaLabel: string | null = null;

  private iconName = 'sparkles';

  /** Legitimate single-letter Lucide icons that must not fall back to a glyph. */
  private static readonly SINGLE_CHAR_ICONS = new Set(['x']);

  private normalizeIconName(raw: string): string {
    const trimmed = (raw || 'sparkles').trim();
    if (!trimmed) return 'sparkles';
    const aliases: Record<string, string> = {
      pulse: 'activity',
      'check-circle': 'check-circle-2',
      Y: 'check-circle-2',
    };
    if (aliases[trimmed]) return aliases[trimmed];
    if (trimmed.length === 1 && !IconComponent.SINGLE_CHAR_ICONS.has(trimmed.toLowerCase())) {
      return 'sparkles';
    }
    return trimmed;
  }
}
