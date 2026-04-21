import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

/**
 * Standard cockpit page frame — provides the section header (eyebrow, title,
 * description) above whatever content is projected. Pages that need a
 * specific layout skip this and roll their own (e.g. Hypervisor).
 */
@Component({
  selector: 'ck-page-frame',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      [style.padding]="'24px 32px 48px'"
      [style.maxWidth.px]="1480"
      [style.margin]="'0 auto'"
    >
      @if (eyebrow || title) {
        <header [style.marginBottom.px]="20">
          @if (eyebrow) {
            <div class="ck-label" [style.color]="'var(--ck-signal-cool)'" [style.marginBottom.px]="6">{{ eyebrow }}</div>
          }
          <div [style.display]="'flex'" [style.alignItems]="'baseline'" [style.gap.px]="12">
            <h1
              [style.fontFamily]="'var(--ck-font-sans)'"
              [style.fontSize.px]="28"
              [style.fontWeight]="500"
              [style.letterSpacing]="'-0.02em'"
              [style.color]="'var(--ck-fg-1)'"
              [style.margin]="'0'"
            >{{ title }}</h1>
            @if (status) {
              <span class="ck-mono" [style.fontSize.px]="10" [style.letterSpacing]="'0.14em'" [style.textTransform]="'uppercase'" [style.color]="'var(--ck-fg-4)'">{{ status }}</span>
            }
          </div>
          @if (description) {
            <p [style.maxWidth.ch]="78" [style.marginTop.px]="8" [style.color]="'var(--ck-fg-3)'" [style.fontSize.px]="13" [style.lineHeight]="1.6">{{ description }}</p>
          }
        </header>
      }
      <ng-content></ng-content>
    </section>
  `,
})
export class PageFrameComponent {
  @Input() eyebrow = '';
  @Input() title = '';
  @Input() description = '';
  @Input() status = '';
}
