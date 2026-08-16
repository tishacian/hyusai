import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

/**
 * Standard cockpit page frame — provides the section header (eyebrow, title,
 * description, optional actions slot) above whatever content is projected.
 * Pages that need a specific layout skip this and roll their own (e.g.
 * Hypervisor).
 *
 * Content projection slots:
 *   - `<… titleHelp>` sits right after the title — where a `<ck-help>` on the
 *     screen's main concept belongs (first occurrence of a lexicon term)
 *   - `<… actions>`  right-aligned action buttons beside the title row
 *   - `<… sub>`      bleeds below the header (tab row, sub-nav)
 *   - default        main body
 */
@Component({
  selector: 'ck-page-frame',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="ck-page-frame"
    >
      @if (eyebrow || title || hasActions) {
        <header [style.marginBottom.px]="20">
          <div
            [style.display]="'flex'"
            [style.alignItems]="'flex-end'"
            [style.justifyContent]="'space-between'"
            [style.gap.px]="16"
            [style.flexWrap]="'wrap'"
          >
            <div [style.minWidth.px]="0" [style.flex]="'1 1 auto'">
              @if (eyebrow) {
                <div class="ck-label" [style.color]="'var(--ck-signal-cool)'" [style.marginBottom.px]="6">{{ eyebrow }}</div>
              }
              <div class="ck-page-title" [style.display]="'flex'" [style.alignItems]="'baseline'" [style.gap.px]="12">
                <h1
                  tabindex="-1"
                  [style.fontFamily]="'var(--ck-font-sans)'"
                  [style.fontSize.px]="28"
                  [style.fontWeight]="500"
                  [style.letterSpacing]="'0'"
                  [style.color]="'var(--ck-fg-1)'"
                  [style.margin]="'0'"
                >{{ title }}</h1>
                <ng-content select="[titleHelp]"></ng-content>
                @if (status) {
                  <span class="ck-mono" [style.fontSize.px]="10" [style.letterSpacing]="'0.14em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-4)'">{{ status }}</span>
                }
              </div>
              @if (description) {
                <p [style.maxWidth.ch]="78" [style.marginTop.px]="8" [style.color]="'var(--ck-fg-3)'" [style.fontSize.px]="13" [style.lineHeight]="1.6">{{ description }}</p>
              }
            </div>
            <div
              class="ck-page-actions"
              [style.display]="'inline-flex'"
              [style.alignItems]="'center'"
              [style.gap.px]="8"
              [style.flex]="'0 0 auto'"
            >
              <ng-content select="[actions]"></ng-content>
            </div>
          </div>
          <ng-content select="[sub]"></ng-content>
        </header>
      }
      <ng-content></ng-content>
    </section>
  `,
  styles: [`
    .ck-page-frame {
      max-width: 1480px;
      margin: 0 auto;
      padding: 24px 32px 48px;
    }

    .ck-page-title {
      min-width: 0;
      flex-wrap: wrap;
    }

    .ck-page-title h1 {
      overflow-wrap: anywhere;
    }

    @media (max-width: 640px) {
      .ck-page-frame {
        padding: 18px 14px 32px;
      }

      .ck-page-title h1 {
        font-size: 24px !important;
      }

      .ck-page-actions {
        max-width: 100%;
        flex-wrap: wrap;
      }
    }
  `],
})
export class PageFrameComponent {
  @Input() eyebrow = '';
  @Input() title = '';
  @Input() description = '';
  @Input() status = '';
  /** Unused at runtime — kept so templates stay explicit when projecting actions. */
  @Input() hasActions = true;
}
