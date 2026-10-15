import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { brandPath } from './brand-registry';
import { IconComponent } from './icon.component';

/**
 * Monochrome brand logo for a connector or provider card.
 *
 * The path comes from the generated Simple Icons registry and is bound as an
 * attribute, never as HTML, so a logo cannot carry markup. It takes the text
 * colour, which keeps the Tokens v2 cards sober in both themes. An unknown
 * brand renders the Lucide `fallback` instead of an empty slot.
 *
 * Kept apart from `<app-icon>` so the registry only ships with the pages that
 * show brands, not with every bundle that uses an icon.
 */
@Component({
  selector: 'app-brand-icon',
  standalone: true,
  imports: [IconComponent],
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
    `,
  ],
  template: `
    @if (path; as d) {
      <svg
        viewBox="0 0 24 24"
        fill="currentColor"
        [attr.width]="size"
        [attr.height]="size"
        [style.width.px]="size"
        [style.height.px]="size"
        [attr.aria-hidden]="ariaLabel ? null : true"
        [attr.aria-label]="ariaLabel"
        [attr.role]="ariaLabel ? 'img' : null"
        [attr.data-brand]="name"
      >
        <path [attr.d]="d" />
      </svg>
    } @else {
      <app-icon [name]="fallback" [size]="size" [ariaLabel]="ariaLabel" />
    }
  `,
})
export class BrandIconComponent {
  @Input() name: string | null = null;
  @Input() fallback = 'plug';
  @Input() size = 20;
  @Input() ariaLabel: string | null = null;

  get path(): string | null {
    return this.name ? brandPath(this.name) : null;
  }
}
