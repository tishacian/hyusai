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
      @for (indicator of indicators; track indicator.label) {
        <article [class]="toneClass(indicator.tone)">
          <svg viewBox="0 0 88 88" aria-hidden="true">
            <circle class="track" cx="44" cy="44" r="34"></circle>
            <circle
              class="fill"
              cx="44"
              cy="44"
              r="34"
              [attr.stroke-dasharray]="gaugeArc(indicator)"
            ></circle>
          </svg>
          <div class="gauge-copy">
            <strong>{{ indicator.value }}{{ indicator.unit || '' }}</strong>
            <span>{{ indicator.label }}</span>
            <small>{{ indicator.trend || indicator.source }}</small>
          </div>
        </article>
      }
    </div>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .vp-gauges {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        height: 100%;
      }
      article {
        display: grid;
        grid-template-columns: 72px minmax(0, 1fr);
        gap: 8px;
        align-items: center;
        padding: 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.62);
      }
      article.critical { border-color: rgba(240, 100, 118, 0.34); }
      article.elevated { border-color: rgba(241, 180, 90, 0.32); }
      article.stable { border-color: rgba(63, 209, 141, 0.28); }
      svg {
        width: 72px;
        height: 72px;
        transform: rotate(-90deg);
      }
      .track {
        fill: none;
        stroke: rgba(148, 163, 184, 0.12);
        stroke-width: 7;
      }
      .fill {
        fill: none;
        stroke: var(--mission-accent);
        stroke-width: 7;
        stroke-linecap: round;
        transition: stroke-dasharray 0.4s ease;
      }
      article.critical .fill { stroke: var(--mission-danger); }
      article.elevated .fill { stroke: var(--mission-warn); }
      article.stable .fill { stroke: var(--mission-trust); }
      .gauge-copy strong {
        display: block;
        font-size: 20px;
        font-weight: 700;
        line-height: 1.1;
        color: var(--mission-text);
      }
      .gauge-copy span {
        display: block;
        margin-top: 4px;
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .gauge-copy small {
        display: block;
        margin-top: 4px;
        color: var(--mission-text-faint);
        font-size: 10px;
        line-height: 1.35;
      }
    `,
  ],
})
export class VpSovereignGaugesComponent {
  @Input() indicators: VpSovereignIndicator[] = [];

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
