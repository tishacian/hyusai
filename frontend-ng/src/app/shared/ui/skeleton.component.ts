import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { NgClass } from '@angular/common';

@Component({
  selector: 'app-skeleton',
  standalone: true,
  imports: [NgClass],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="skeleton"
      [ngClass]="{
        'rounded-full': variant === 'avatar',
        'rounded-md': variant !== 'avatar'
      }"
      [style.width]="width"
      [style.height]="height"
    ></div>
  `,
})
export class SkeletonComponent {
  @Input() variant: 'line' | 'card' | 'avatar' = 'line';
  @Input() width: string = '100%';
  @Input() height: string = '12px';
}
