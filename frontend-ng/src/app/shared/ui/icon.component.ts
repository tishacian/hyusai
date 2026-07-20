import { ChangeDetectionStrategy, Component, HostBinding, Input, inject } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { LucideAngularModule } from 'lucide-angular';
import { phosphorDuotoneBody } from './phosphor-registry';

export type IconSet = 'lucide' | 'phosphor';
export type PhosphorWeight = 'duotone';

/**
 * Centralised icon façade.
 *
 * - Lucide (default): stroke utility icons — actions, toolbars, dense UI.
 *   Register names in `icon-registry.ts` via `provideLucideIcons()`.
 * - Phosphor duotone (`set="phosphor"`): expressive identity icons for
 *   section heroes / brand moments. Curated bodies in `phosphor-registry.ts`.
 * - Cockpit chrome stays on `<ck-glyph>` — do not route those through here.
 *
 * Usage:
 *   `<app-icon name="save" [size]="14" />`
 *   `<app-icon name="layers" set="phosphor" [size]="18" />`
 *   `<app-icon name="ph:layers" [size]="18" />`  // shorthand → phosphor
 *
 * Missing Phosphor keys fall back to Lucide of the same name (no empty slot).
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
      :host.ck-icon--duotone ::ng-deep .ph-duotone-secondary {
        opacity: var(--ck-icon-duotone-secondary, 0.2);
      }
    `,
  ],
  template: `
    @if (usePhosphor()) {
      <svg
        [attr.width]="size"
        [attr.height]="size"
        viewBox="0 0 256 256"
        fill="currentColor"
        [style.width.px]="size"
        [style.height.px]="size"
        [attr.aria-hidden]="ariaLabel ? null : true"
        [attr.aria-label]="ariaLabel"
        [attr.role]="ariaLabel ? 'img' : null"
        [innerHTML]="phosphorSafeHtml()"
      ></svg>
    } @else {
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
    }
  `,
})
export class IconComponent {
  private readonly sanitizer = inject(DomSanitizer);

  @Input({ required: true }) set name(value: string) {
    this.applyName(value);
  }
  get name(): string {
    return this.iconName;
  }

  @Input() set set(value: IconSet) {
    this.explicitSet = value === 'phosphor' ? 'phosphor' : 'lucide';
    this.refreshPhosphor();
  }
  get set(): IconSet {
    return this.resolvedSet;
  }

  /** Only `duotone` is supported in v1. */
  @Input() weight: PhosphorWeight = 'duotone';

  @Input() size: number = 18;
  @Input() strokeWidth: number = 1.75;
  @Input() ariaLabel: string | null = null;

  @HostBinding('class.ck-icon--duotone')
  get duotoneHost(): boolean {
    return this.usePhosphor();
  }

  private iconName = 'sparkles';
  private explicitSet: IconSet | null = null;
  private prefixForcesPhosphor = false;
  private resolvedSet: IconSet = 'lucide';
  private phosphorBody: string | null = null;

  /** Legitimate single-letter Lucide icons that must not fall back to a glyph. */
  private static readonly SINGLE_CHAR_ICONS = new Set(['x']);

  usePhosphor(): boolean {
    return this.resolvedSet === 'phosphor' && !!this.phosphorBody;
  }

  phosphorSafeHtml(): SafeHtml {
    return this.sanitizer.bypassSecurityTrustHtml(this.phosphorBody ?? '');
  }

  private applyName(raw: string): void {
    let trimmed = (raw || 'sparkles').trim();
    this.prefixForcesPhosphor = false;
    if (trimmed.startsWith('ph:')) {
      this.prefixForcesPhosphor = true;
      trimmed = trimmed.slice(3).trim();
    }
    this.iconName = this.normalizeIconName(trimmed);
    this.refreshPhosphor();
  }

  private refreshPhosphor(): void {
    const wantPhosphor =
      this.explicitSet === 'phosphor' ||
      (this.explicitSet === null && this.prefixForcesPhosphor);
    if (!wantPhosphor) {
      this.resolvedSet = 'lucide';
      this.phosphorBody = null;
      return;
    }
    const body = phosphorDuotoneBody(this.iconName);
    if (body) {
      this.resolvedSet = 'phosphor';
      this.phosphorBody = body;
    } else {
      // Fallback: keep Lucide so identity remaps never blank out.
      this.resolvedSet = 'lucide';
      this.phosphorBody = null;
    }
  }

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
