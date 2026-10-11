import {
  AfterViewChecked,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Input,
  inject,
} from '@angular/core';

import { placeTooltip } from './chart-interact';

export interface CkChartTipLine {
  label: string;
  value: string;
}

@Component({
  selector: 'ck-chart-tip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open) {
      <div
        #box
        class="ck-chart-tip"
        role="tooltip"
        data-testid="ck-chart-tip"
        [style.left.px]="left"
        [style.top.px]="top"
      >
        @if (title) {
          <div class="ck-chart-tip-title">{{ title }}</div>
        }
        @for (line of lines; track $index) {
          <div class="ck-chart-tip-row">
            @if (line.label) {
              <span class="ck-chart-tip-label">{{ line.label }}</span>
            }
            <span class="ck-chart-tip-value ck-tnum">{{ line.value }}</span>
          </div>
        }
      </div>
    }
  `,
  styles: [`
    :host { position: absolute; inset: 0; pointer-events: none; z-index: 4; }
    .ck-chart-tip {
      position: absolute;
      min-width: 92px;
      max-width: 240px;
      padding: 7px 9px;
      background: var(--ck-bg-panel);
      border: 1px solid var(--ck-stroke-2);
      border-radius: var(--radius-sm, 4px);
      color: var(--ck-fg-1);
      opacity: 1;
    }
    @media (prefers-reduced-motion: no-preference) {
      .ck-chart-tip {
        opacity: 0;
        animation: ckTipIn 120ms var(--ck-ease-out, ease-out) forwards;
      }
    }
    .ck-chart-tip-title {
      font-family: var(--ck-font-sans);
      font-size: 12px;
      font-weight: 600;
      line-height: 1.3;
      margin: 0 0 4px;
    }
    .ck-chart-tip-row {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      line-height: 1.35;
    }
    /* Labels are names (systems, units): sans, never monospace. Figures stay tabular. */
    .ck-chart-tip-label {
      font-family: var(--ck-font-sans); font-size: 11px; line-height: 1.35; color: var(--ck-fg-3);
      min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .ck-chart-tip-value {
      font-family: var(--ck-font-sans); font-size: 12px; color: var(--ck-fg-1);
      font-variant-numeric: tabular-nums; white-space: nowrap;
    }
    @keyframes ckTipIn { to { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) {
      .ck-chart-tip { animation: none; opacity: 1; }
    }
  `],
})
export class CkChartTipComponent implements AfterViewChecked {
  private readonly host = inject(ElementRef<HTMLElement>);

  @Input() open = false;
  @Input() title = '';
  @Input() lines: readonly CkChartTipLine[] = [];
  @Input() x = 0;
  @Input() y = 0;

  left = 0;
  top = 0;

  ngAfterViewChecked(): void {
    if (!this.open) return;
    const box = this.host.nativeElement.querySelector('.ck-chart-tip');
    if (!(box instanceof HTMLElement)) return;
    const parent = this.host.nativeElement.offsetParent ?? this.host.nativeElement;
    const placed = placeTooltip(
      { x: this.x, y: this.y },
      { w: box.offsetWidth, h: box.offsetHeight },
      { w: parent.clientWidth, h: parent.clientHeight },
    );
    if (placed.x !== this.left || placed.y !== this.top) {
      this.left = placed.x;
      this.top = placed.y;
      box.style.left = `${placed.x}px`;
      box.style.top = `${placed.y}px`;
    }
  }
}
