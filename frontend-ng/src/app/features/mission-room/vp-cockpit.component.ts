import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { VpMapPreviewComponent } from './vp-map-preview.component';
import { VpArbitrationStripComponent } from './vp-arbitration-strip.component';
import { VpAyaPriorityBannerComponent } from './vp-aya-priority-banner.component';
import { VpPressPreviewComponent } from './vp-press-preview.component';
import { VpMacroIndicatorsComponent } from './vp-macro-indicators.component';
import type { VesselPosition } from '@app/core/maritime-tracking.service';
import type {
  VpArbitrationCard,
  VpAyaRecommendation,
  VpDirectiveOfDay,
  VpMapPreviewContext,
  VpPressPreviewItem,
  VpStatusBarItem,
  VpZoneScore,
} from './vp-cockpit.types';

@Component({
  selector: 'app-vp-cockpit',
  standalone: true,
  imports: [
    CommonModule,
    VpMapPreviewComponent,
    VpArbitrationStripComponent,
    VpAyaPriorityBannerComponent,
    VpPressPreviewComponent,
    VpMacroIndicatorsComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="vp-cockpit" aria-label="Cockpit Vice-Présidence">
      <section class="vp-block vp-block-status" aria-label="Posture nationale">
        <header class="vp-block-head">
          <span class="vp-block-eyebrow">Posture nationale</span>
          <h2 class="vp-block-title">État du jour</h2>
        </header>
        <div class="vp-status-bar">
          @for (item of orderedStatusBar(); track item.key) {
            <button
              type="button"
              class="status-chip"
              [class]="toneClass(item.tone)"
              [class.prominent]="isProminent(item)"
              [attr.aria-label]="item.label + ' : ' + item.value + (item.detail ? ' — ' + item.detail : '')"
              (click)="statusBarSelected.emit(item)"
            >
              @if (isProminent(item)) {
                <span class="status-chip-pulse" aria-hidden="true"></span>
              }
              <span class="status-chip-label">{{ item.label }}</span>
              <strong class="status-chip-value">{{ item.value }}</strong>
              @if (item.detail) {
                <small class="status-chip-detail">{{ item.detail }}</small>
              }
            </button>
          }
        </div>
      </section>

      <section class="vp-block vp-block-macro" aria-label="Indicateurs macro">
        <app-vp-macro-indicators />
      </section>

      <section class="vp-block vp-block-aya" aria-label="Priorité AYA">
        <app-vp-aya-priority-banner
          [assistantName]="assistantName"
          [directive]="directive"
          [recommendation]="ayaRecommendation"
          (voiceRequest)="voiceRequest.emit($event)"
          (voiceListen)="voiceListen.emit()"
          (briefingRequest)="briefingRequest.emit()"
        />
      </section>

      <section class="vp-block vp-block-terrain" aria-label="Carte et arbitrages">
        <app-vp-map-preview
          [context]="mapPreview"
          (openMap)="openMap.emit()"
          (zoneSelected)="mapZoneSelected.emit($event)"
          (vesselSelected)="mapVesselSelected.emit($event)"
        />
        <app-vp-arbitration-strip [cards]="arbitrationCards" (cardSelected)="arbitrationSelected.emit($event)" />
      </section>

      @if (securityPosture; as posture) {
        <section class="vp-block vp-block-security" aria-label="Posture securitaire dual-axis">
          <header class="vp-block-head">
            <span class="vp-block-eyebrow">Posture securitaire</span>
            <h2 class="vp-block-title">{{ posture.summary || 'Dual-axis interieur · exterieur' }}</h2>
            @if (postureNextCouncil(posture); as council) {
              <span class="vp-security-council" [attr.aria-label]="'Prochain conseil ' + council">{{ council }}</span>
            }
          </header>
          <div class="vp-security-grid">
            @for (axis of postureAxes(posture); track axis.key) {
              <article class="vp-security-card" [class]="'tone-' + (axis.tone || 'monitoring')">
                <header class="vp-security-card-head">
                  <span class="vp-security-card-axis">{{ axis.label }}</span>
                  <strong class="vp-security-card-level" [attr.data-tone]="axis.tone">{{ axis.level | uppercase }}</strong>
                </header>
                @if (axis.headline) {
                  <p class="vp-security-card-headline">{{ axis.headline }}</p>
                }
                @if (axis.signals?.length) {
                  <ul class="vp-security-card-signals" aria-label="Signaux">
                    @for (signal of (axis.signals || []).slice(0, 3); track signal.id) {
                      <li [class]="'tone-' + (signal.tone || 'monitoring')">
                        <span class="vp-security-signal-label">{{ signal.label }}</span>
                        @if (signal.summary) {
                          <small class="vp-security-signal-summary">{{ signal.summary }}</small>
                        }
                      </li>
                    }
                  </ul>
                }
              </article>
            }
          </div>
          <div class="vp-security-actions">
            <button type="button" class="vp-security-cta vp-security-cta-primary" (click)="securityPostureRequested.emit()">
              Posture securitaire complete
            </button>
            <button type="button" class="vp-security-cta" (click)="securityCommuniqueRequested.emit()">
              Préparer le communiqué Nord
            </button>
          </div>
        </section>
      }

      <section class="vp-block vp-block-press" aria-label="Alerte presse">
        <header class="vp-block-head">
          <span class="vp-block-eyebrow">Signal presse</span>
          <h2 class="vp-block-title">Alerte hero du matin</h2>
        </header>
        <app-vp-press-preview
          [items]="pressPreview.slice(0, 1)"
          [highlightId]="pressHighlightId"
          (itemSelected)="pressSelected.emit($event)"
        />
      </section>
    </div>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .vp-cockpit {
        display: grid;
        gap: var(--mission-space-5);
        padding: var(--mission-space-1) 0;
      }
      .vp-block {
        padding: var(--mission-space-5);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-lg);
        background: linear-gradient(180deg, rgba(8, 14, 20, 0.62), rgba(4, 8, 13, 0.42));
        box-shadow: var(--mission-shadow-soft);
      }
      .vp-block-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--mission-space-3);
        margin-bottom: var(--mission-space-4);
      }
      .vp-block-eyebrow {
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
        color: var(--mission-text-tertiary);
      }
      .vp-block-title {
        margin: 0;
        font-size: var(--mission-text-md);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
      }
      .vp-status-bar {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: var(--mission-space-3);
      }
      .status-chip {
        position: relative;
        padding: var(--mission-space-3) var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.58);
        width: 100%;
        color: inherit;
        text-align: left;
        appearance: none;
        font: inherit;
        cursor: pointer;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out),
          transform var(--mission-dur-fast) var(--mission-ease-out);
      }
      .status-chip:hover {
        border-color: var(--sentinel-accent-muted);
        background: rgba(101, 214, 110, 0.04);
      }
      .status-chip:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .status-chip:active { transform: translateY(1px); }
      .status-chip.critical { border-color: rgba(240, 100, 118, 0.34); }
      .status-chip.elevated { border-color: rgba(241, 180, 90, 0.32); }
      .status-chip.stable { border-color: rgba(63, 209, 141, 0.28); }
      .status-chip.prominent {
        background: linear-gradient(135deg, var(--mission-critical-soft), rgba(4, 8, 13, 0.62));
        border-color: rgba(240, 100, 118, 0.55);
        box-shadow: 0 0 0 1px rgba(240, 100, 118, 0.20), 0 0 18px rgba(240, 100, 118, 0.08);
      }
      .status-chip.prominent .status-chip-value { color: var(--mission-critical); }
      .status-chip-pulse {
        position: absolute;
        top: var(--mission-space-3);
        right: var(--mission-space-3);
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--mission-critical);
        box-shadow: 0 0 0 0 rgba(240, 100, 118, 0.55);
        animation: vp-pulse-critical 2.4s ease-in-out infinite;
      }
      @keyframes vp-pulse-critical {
        0%, 100% { box-shadow: 0 0 0 0 rgba(240, 100, 118, 0.55); }
        50%      { box-shadow: 0 0 0 7px rgba(240, 100, 118, 0); }
      }
      .status-chip-label {
        display: block;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      .status-chip-value {
        display: block;
        margin-top: var(--mission-space-1);
        font-size: var(--mission-text-lg);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: 1.05;
        color: var(--mission-text-primary);
      }
      .status-chip-detail {
        display: block;
        margin-top: var(--mission-space-1);
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
        line-height: 1.35;
      }
      .vp-block-terrain {
        display: grid;
        grid-template-columns: minmax(0, 1.45fr) minmax(280px, 1fr);
        gap: var(--mission-space-4);
        align-items: stretch;
        padding: 0;
        background: transparent;
        border: 0;
        box-shadow: none;
      }
      .vp-block-terrain > * {
        min-width: 0;
      }
      .vp-block-aya {
        padding: var(--mission-space-1);
        background: transparent;
        border: 0;
        box-shadow: none;
      }
      .vp-block-macro,
      .vp-block-press {
        padding: var(--mission-space-5);
      }
      .vp-block-security {
        display: grid;
        gap: var(--mission-space-4);
      }
      .vp-security-council {
        margin-left: auto;
        padding: var(--mission-space-1) var(--mission-space-3);
        border-radius: 999px;
        background: rgba(241, 180, 90, 0.12);
        border: 1px solid rgba(241, 180, 90, 0.32);
        color: var(--mission-text-secondary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      .vp-security-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--mission-space-4);
      }
      .vp-security-card {
        padding: var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.62);
        display: flex;
        flex-direction: column;
        gap: var(--mission-space-3);
        min-width: 0;
      }
      .vp-security-card.tone-watch { border-color: rgba(241, 180, 90, 0.42); }
      .vp-security-card.tone-elevated { border-color: rgba(241, 180, 90, 0.42); }
      .vp-security-card.tone-stable { border-color: rgba(63, 209, 141, 0.32); }
      .vp-security-card-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--mission-space-3);
      }
      .vp-security-card-axis {
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
        color: var(--mission-text-tertiary);
      }
      .vp-security-card-level {
        font-size: var(--mission-text-md);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
      }
      .vp-security-card-level[data-tone='watch'] { color: var(--mission-warning, #f1b45a); }
      .vp-security-card-level[data-tone='elevated'] { color: var(--mission-warning, #f1b45a); }
      .vp-security-card-level[data-tone='stable'] { color: var(--mission-success, #63d18d); }
      .vp-security-card-level[data-tone='critical'] { color: var(--mission-critical, #f06476); }
      .vp-security-card-headline {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: 1.45;
      }
      .vp-security-card-signals {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: var(--mission-space-2);
      }
      .vp-security-card-signals li {
        padding: var(--mission-space-2) var(--mission-space-3);
        border-left: 2px solid var(--mission-border);
        background: rgba(8, 14, 20, 0.52);
        border-radius: 4px;
      }
      .vp-security-card-signals li.tone-watch { border-left-color: rgba(241, 180, 90, 0.60); }
      .vp-security-card-signals li.tone-stable { border-left-color: rgba(63, 209, 141, 0.55); }
      .vp-security-card-signals li.tone-critical { border-left-color: rgba(240, 100, 118, 0.60); }
      .vp-security-signal-label {
        display: block;
        font-weight: 600;
        font-size: var(--mission-text-xs);
        color: var(--mission-text-primary);
      }
      .vp-security-signal-summary {
        display: block;
        margin-top: 2px;
        font-size: var(--mission-text-xs);
        color: var(--mission-text-tertiary);
        line-height: 1.35;
      }
      .vp-security-actions {
        display: flex;
        gap: var(--mission-space-3);
        flex-wrap: wrap;
      }
      .vp-security-cta {
        appearance: none;
        cursor: pointer;
        padding: var(--mission-space-2) var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.5);
        color: var(--mission-text-primary);
        font: inherit;
        font-size: var(--mission-text-xs);
        letter-spacing: var(--mission-tracking-tight);
        transition: border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .vp-security-cta:hover { border-color: var(--sentinel-accent-muted); background: rgba(101, 214, 110, 0.06); }
      .vp-security-cta:focus-visible { outline: 2px solid var(--sentinel-accent); outline-offset: 2px; }
      .vp-security-cta-primary { background: rgba(101, 214, 110, 0.10); border-color: rgba(101, 214, 110, 0.42); }
      @media (max-width: 1100px) {
        .vp-status-bar,
        .vp-block-terrain,
        .vp-security-grid {
          grid-template-columns: 1fr;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .status-chip-pulse { animation: none; }
      }
    `,
  ],
})
export class VpCockpitComponent {
  @Input() assistantName = 'AYA';
  @Input() statusBar: VpStatusBarItem[] = [];
  @Input() mapPreview: VpMapPreviewContext = {
    route: '/hypervisor/mission-room/strategie',
    label: 'Carte fusionnee',
    zones: [],
    map: null,
    mapSystem: null,
    geoPreview: { zone_scores: [] },
    topZoneId: null,
  };
  @Input() directive: VpDirectiveOfDay = { text: '' };
  @Input() ayaRecommendation: VpAyaRecommendation | null = null;
  @Input() arbitrationCards: VpArbitrationCard[] = [];
  @Input() pressPreview: VpPressPreviewItem[] = [];
  @Input() pressHighlightId: string | null = null;
  @Input() securityPosture: Record<string, any> | null = null;

  @Output() openMap = new EventEmitter<void>();
  @Output() mapZoneSelected = new EventEmitter<VpZoneScore>();
  @Output() mapVesselSelected = new EventEmitter<VesselPosition>();
  @Output() statusBarSelected = new EventEmitter<VpStatusBarItem>();
  @Output() arbitrationSelected = new EventEmitter<VpArbitrationCard>();
  @Output() pressSelected = new EventEmitter<VpPressPreviewItem>();
  @Output() voiceRequest = new EventEmitter<string | undefined>();
  @Output() voiceListen = new EventEmitter<void>();
  @Output() briefingRequest = new EventEmitter<void>();
  @Output() securityPostureRequested = new EventEmitter<void>();
  @Output() securityCommuniqueRequested = new EventEmitter<void>();

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'watch') return 'elevated';
    if (normalized === 'stable') return 'stable';
    return 'monitoring';
  }

  isProminent(item: VpStatusBarItem): boolean {
    const normalized = `${item.key} ${item.label} ${item.value} ${item.detail || ''}`.toLowerCase();
    if (normalized.includes('zone nord') || normalized.includes('tension nord')) return true;
    if (normalized.includes('nord') && this.toneClass(item.tone) === 'critical') return true;
    return false;
  }

  postureAxes(posture: Record<string, any> | null): Array<{ key: string; label: string; level: string; tone: string; headline?: string; signals?: any[] }> {
    if (!posture) return [];
    const axes: Array<{ key: string; label: string; level: string; tone: string; headline?: string; signals?: any[] }> = [];
    const interior = posture['interior'];
    if (interior) {
      axes.push({
        key: 'interior',
        label: interior.label || 'Intérieur',
        level: interior.level || 'monitoring',
        tone: interior.tone || 'monitoring',
        headline: interior.headline,
        signals: Array.isArray(interior.signals) ? interior.signals : [],
      });
    }
    const exterior = posture['exterior'];
    if (exterior) {
      axes.push({
        key: 'exterior',
        label: exterior.label || 'Extérieur',
        level: exterior.level || 'monitoring',
        tone: exterior.tone || 'monitoring',
        headline: exterior.headline,
        signals: Array.isArray(exterior.signals) ? exterior.signals : [],
      });
    }
    return axes;
  }

  postureNextCouncil(posture: Record<string, any> | null): string | null {
    const council = posture?.['next_council'];
    if (!council) return null;
    const time = council.time || '';
    const label = council.label || 'Prochain Conseil';
    return time ? `${time} — ${label}` : label;
  }

  orderedStatusBar(): VpStatusBarItem[] {
    const items = (this.statusBar || []).slice();
    const prominentIndex = items.findIndex((item) => this.isProminent(item));
    if (prominentIndex > 0) {
      const [prominent] = items.splice(prominentIndex, 1);
      items.unshift(prominent);
    }
    if (!items.some((item) => this.isProminent(item))) {
      items.unshift({
        key: 'tension-nord',
        label: 'Zone Nord',
        value: 'Tendue',
        detail: 'tension projet · cargo bloqué',
        tone: 'critical',
        drill_down: { view: 'strategie', zone: 'zone-nord', layers: 'threat,press' },
      } as VpStatusBarItem);
    }
    return items.slice(0, 3);
  }
}
