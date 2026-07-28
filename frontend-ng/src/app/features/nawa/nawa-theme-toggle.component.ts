import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import { ThemeService, type BusinessTheme } from '@app/core/theme.service';

const GLYPHS: Record<BusinessTheme, CkGlyphName> = {
  light: 'crosshair',
  dark: 'pulse',
  system: 'orbit',
};

const LABELS: Record<BusinessTheme, string> = {
  system: 'Auto',
  light: 'Light',
  dark: 'Dark',
};

const NEXT: Record<BusinessTheme, BusinessTheme> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
};

/**
 * Theme control for the WE surfaces. It drives the shared business-shell
 * preference rather than a private one, so an operator who picked light in one
 * business app finds light in this one — the cockpit stays pinned to dark
 * either way.
 *
 * The button styles itself from the inherited `--nawa-*` custom properties
 * instead of importing the feature stylesheet, which would otherwise apply the
 * full-viewport host rules to this button.
 */
@Component({
  selector: 'app-nawa-theme-toggle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <button type="button" (click)="cycle()" [title]="tooltip()" [attr.aria-label]="tooltip()">
      <ck-glyph [name]="glyph()" [size]="12" />
      {{ label() }}
    </button>
  `,
  styles: [
    `
      :host {
        display: inline-flex;
      }

      button {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        min-height: 30px;
        padding: 0 11px;
        border-radius: 7px;
        border: 1px solid var(--nawa-line-strong);
        background: transparent;
        color: var(--nawa-fg-dim);
        font-size: 11.5px;
        font-weight: 650;
        font-family: inherit;
        cursor: pointer;
        transition: 140ms ease;
      }

      button:hover {
        border-color: var(--nawa-accent-line);
        background: var(--nawa-surface-2);
        color: var(--nawa-fg);
      }
    `,
  ],
})
export class NawaThemeToggleComponent {
  private readonly theme = inject(ThemeService);

  protected readonly glyph = computed<CkGlyphName>(() => GLYPHS[this.theme.businessTheme()]);
  protected readonly label = computed(() => LABELS[this.theme.businessTheme()]);
  protected readonly tooltip = computed(() => {
    const current = this.theme.businessTheme();
    return `Theme: ${LABELS[current]} · click → ${LABELS[NEXT[current]]}`;
  });

  protected cycle(): void {
    this.theme.cycleBusinessTheme();
  }
}
