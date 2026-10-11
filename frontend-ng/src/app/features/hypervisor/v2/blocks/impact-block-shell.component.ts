import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import type { HypervisorBlockRef } from '../hypervisor-v2-views';

/** Shared inputs for the six generic Impact blocks. */
export type ImpactBlockInputs = Pick<
  HypervisorBlockRef,
  'type' | 'source' | 'title' | 'width' | 'settings' | 'exit'
>;

@Component({
  selector: 'app-impact-block-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article
      class="impact-block"
      [attr.data-testid]="'impact-block-' + type"
      [attr.data-block-type]="type"
      [attr.data-width]="width || 'full'"
    >
      @if (title) {
        <header class="impact-block-head">
          <h3 class="impact-block-title">{{ title }}</h3>
        </header>
      }
      <ng-content />
    </article>
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .impact-block {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 16px 0;
      border-top: 1px solid var(--ck-stroke-2);
    }
    .impact-block-head { display: flex; align-items: baseline; gap: 8px; }
    .impact-block-title {
      margin: 0;
      font-size: 14px;
      font-weight: 600;
      color: var(--ck-fg-1);
    }
    :host-context(.hv2-theme-presentation) .impact-block-title { font-size: 18px; }
  `],
})
export class ImpactBlockShellComponent {
  @Input({ required: true }) type!: string;
  @Input() title: string | null = null;
  @Input() width: string | null = null;
}
