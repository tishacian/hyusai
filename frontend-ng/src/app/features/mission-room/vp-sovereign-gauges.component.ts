import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import type { VpSovereignIndicator } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-sovereign-gauges',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="vp-gauges" aria-label="Indicateurs souverains">
      @for (indicator of indicators; track indicator.label; let idx = $index) {
        <button
          type="button"
          class="gauge-card"
          [class]="toneClass(indicator.tone)"
          [style.--gauge-delay]="(idx * 80) + 'ms'"
          (click)="gaugeSelected.emit(indicator)"
        >
          <svg viewBox="0 0 88 88" aria-hidden="true">
            <circle class="track" cx="44" cy="44" r="34"></circle>
            <circle
              class="fill"
              cx="44"
              cy="44"
              r="34"
              [attr.stroke-dasharray]="gaugeArc(indicator)"
              [attr.stroke-dashoffset]="0"
            ></circle>
          </svg>
          <div class="gauge-copy">
            <span class="gauge-label">{{ indicator.label }}</span>
            <strong>{{ indicator.value }}{{ indicator.unit || '' }}</strong>
            <small>{{ indicator.trend || indicator.source }}</small>
          </div>
        </button>
      }
    </div>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .vp-gauges {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--mission-space-3);
        height: 100%;
      }
      .gauge-card {
        display: grid;
        grid-template-columns: 80px minmax(0, 1fr);
        gap: var(--mission-space-3);
        align-items: center;
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.62);
        width: 100%;
        color: inherit;
        text-align: left;
        appearance: none;
        font: inherit;
        cursor: pointer;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .gauge-card:hover {
        border-color: var(--sentinel-accent-muted);
        background: rgba(101, 214, 110, 0.04);
      }
      .gauge-card:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .gauge-card.critical { border-color: rgba(240, 100, 118, 0.34); }
      .gauge-card.elevated { border-color: rgba(241, 180, 90, 0.32); }
      .gauge-card.stable   { border-color: rgba(63, 209, 141, 0.28); }
      svg {
        width: 80px;
        height: 80px;
        transform: rotate(-90deg);
      }
      .track {
        fill: none;
        stroke: var(--mission-border-subtle);
        stroke-width: 7;
      }
      .fill {
        fill: none;
        stroke: var(--sentinel-accent);
        stroke-width: 7;
        stroke-linecap: round;
        animation: gauge-arc-in 600ms var(--mission-ease-out) both;
        animation-delay: var(--gauge-delay, 0ms);
      }
      .gauge-card.critical .fill { stroke: var(--mission-critical); }
      .gauge-card.elevated .fill { stroke: var(--mission-warning); }
      .gauge-card.stable   .fill { stroke: var(--mission-success); }
      @keyframes gauge-arc-in {
        from { stroke-dashoffset: 220; opacity: 0.6; }
        to   { stroke-dashoffset: 0;   opacity: 1; }
      }
      .gauge-copy { min-width: 0; }
      .gauge-label {
        display: block;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      .gauge-copy strong {
        display: block;
        margin-top: var(--mission-space-1);
        font-family: var(--mission-font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--mission-text-xl);
        font-weight: 600;
        line-height: 1;
        color: var(--mission-text-primary);
      }
      .gauge-copy small {
        display: block;
        margin-top: var(--mission-space-1);
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        line-height: 1.35;
      }
      @media (prefers-reduced-motion: reduce) {
        .fill { animation: none; }
      }
    `,
  ],
})
export class VpSovereignGaugesComponent {
  @Input() indicators: VpSovereignIndicator[] = [];
  @Output() gaugeSelected = new EventEmitter<VpSovereignIndicator>();

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'high') return 'elevated';
    if (normalized === 'stable') return 'stable';
    return 'monitoring';
  }

  gaugeArc(indicator: VpSovereignIndicator): string {
    const raw = typeof indicator.value === 'number' ? indicator.value : Number(indicator.value) || 0;
    const pct = Math.max(0, Math.min(100, raw > 100 ? raw / 100 : raw));
    const circumference = 2 * Math.PI * 34;
    const filled = (pct / 100) * circumference;
    return `${filled.toFixed(1)} ${circumference.toFixed(1)}`;
  }
}
