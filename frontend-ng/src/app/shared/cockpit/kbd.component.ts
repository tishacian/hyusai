import { ChangeDetectionStrategy, Component } from '@angular/core';

/** Keyboard shortcut cap. Use as `<ck-kbd>⌘K</ck-kbd>`. */
@Component({
  selector: 'ck-kbd',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <kbd
      class="ck-mono"
      [style.display]="'inline-flex'"
      [style.alignItems]="'center'"
      [style.justifyContent]="'center'"
      [style.minWidth.px]="18"
      [style.padding]="'1px 5px'"
      [style.fontSize.px]="10"
      [style.lineHeight]="'1'"
      [style.color]="'var(--ck-fg-2)'"
      [style.background]="'var(--ck-bg-inset)'"
      [style.border]="'1px solid var(--ck-stroke-2)'"
      [style.borderRadius.px]="3"
      [style.boxShadow]="'inset 0 -1px 0 var(--ck-stroke-2)'"
    >
      <ng-content></ng-content>
    </kbd>
  `,
})
export class KbdComponent {}
