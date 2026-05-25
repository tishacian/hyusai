import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';

export interface TroopsTrack {
  id?: string;
  callsign?: string;
  kind?: string;
  operator?: string;
  altitude_ft?: number;
  heading?: number;
  speed_kt?: number;
  longitude?: number;
  latitude?: number;
  origin?: string;
  destination?: string;
  tone?: string;
}

export interface TroopsWatchZone {
  id?: string;
  name?: string;
  label?: string;
  tone?: string;
  centroid?: number[];
  summary?: string;
  source?: string;
  alert_level?: string;
  note?: string;
}

export interface TroopsCedeaoBase {
  id?: string;
  name?: string;
  label?: string;
  country?: string;
  tone?: string;
  longitude?: number;
  latitude?: number;
  role?: string;
  status?: string;
}

export interface TroopsSahelSnapshot {
  captured_at?: string;
  disclaimer?: string;
  theater_label?: string;
  tracks?: TroopsTrack[];
  watch_zones?: TroopsWatchZone[];
  cedeao_bases?: TroopsCedeaoBase[];
}

@Component({
  selector: 'app-vp-troops-theater-drawer',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open && snapshot) {
      <div class="troops-drawer-root" role="dialog" aria-modal="true" aria-label="Theatre Sahel">
        <button
          type="button"
          class="troops-drawer-backdrop"
          aria-label="Fermer le theatre Sahel"
          (click)="closed.emit()"
        ></button>
        <aside class="troops-drawer-panel">
          <header class="troops-drawer-head">
            <div class="troops-drawer-head-copy">
              <span class="risk-pill warn">advisory only</span>
              <small class="publisher-badge">ADS-B advisory</small>
              <h2>{{ snapshot.theater_label || 'Theatre Sahel' }}</h2>
              <p class="troops-drawer-summary">{{ snapshot.disclaimer || defaultDisclaimer }}</p>
            </div>
            <button
              type="button"
              class="troops-drawer-close"
              aria-label="Fermer"
              (click)="closed.emit()"
            >
              ×
            </button>
          </header>

          <div class="troops-drawer-body">
            <section class="troops-stats" aria-label="Indicateurs theatre">
              <article class="stat-card">
                <span class="stat-label">traces actives</span>
                <strong>{{ tracks().length }}</strong>
                <small>snapshot {{ capturedAtLabel() }}</small>
              </article>
              <article class="stat-card warn">
                <span class="stat-label">zones surveillance</span>
                <strong>{{ watchZones().length }}</strong>
                <small>OSINT public</small>
              </article>
              <article class="stat-card">
                <span class="stat-label">bases CEDEAO</span>
                <strong>{{ cedeaoBases().length }}</strong>
                <small>alerte standard</small>
              </article>
              <article class="stat-card">
                <span class="stat-label">altitude moy.</span>
                <strong>{{ averageAltitude() }}</strong>
                <small>ft (advisory)</small>
              </article>
            </section>

            <section class="troops-section">
              <span class="eyebrow">Trafic militaire (snapshot ADS-B)</span>
              @if (tracks().length) {
                <div class="track-table-wrap">
                  <table class="track-table">
                    <thead>
                      <tr>
                        <th scope="col">Callsign</th>
                        <th scope="col">Type</th>
                        <th scope="col">Route</th>
                        <th scope="col" class="num">Alt (ft)</th>
                        <th scope="col" class="num">Vit (kt)</th>
                        <th scope="col">Statut</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (track of tracks(); track track.id) {
                        <tr
                          tabindex="0"
                          [class.tone-watch]="track.tone === 'watch'"
                          [class.tone-stable]="track.tone === 'stable'"
                          (click)="trackSelected.emit(track)"
                          (keydown.enter)="trackSelected.emit(track)"
                          (keydown.space)="trackSelected.emit(track); $event.preventDefault()"
                        >
                          <td class="cs">{{ track.callsign || '—' }}</td>
                          <td>{{ track.kind || '—' }}</td>
                          <td class="route">
                            <span>{{ track.origin || '—' }}</span>
                            <em>→</em>
                            <span>{{ track.destination || '—' }}</span>
                          </td>
                          <td class="num">{{ track.altitude_ft ?? '—' }}</td>
                          <td class="num">{{ track.speed_kt ?? '—' }}</td>
                          <td>
                            <span class="status-chip" [class]="'tone-' + (track.tone || 'stable')">
                              {{ statusLabel(track.tone) }}
                            </span>
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
              } @else {
                <p class="empty">Pas de trace ADS-B dans le snapshot.</p>
              }
            </section>

            @if (watchZones().length) {
              <section class="troops-section">
                <span class="eyebrow">Zones de surveillance</span>
                <div class="zone-grid">
                  @for (zone of watchZones(); track zone.id) {
                    <article class="zone-card" [class]="'tone-' + (zone.tone || 'watch')">
                      <header>
                        <strong>{{ zone.name || zone.label || 'Zone' }}</strong>
                        <span class="zone-source">{{ zoneSource(zone) }}</span>
                      </header>
                      <p>{{ zone.summary || zone.note || '—' }}</p>
                      <footer>
                        <span class="status-chip" [class]="'tone-' + (zone.tone || 'watch')">
                          {{ alertLabel(zone) }}
                        </span>
                      </footer>
                    </article>
                  }
                </div>
              </section>
            }

            @if (cedeaoBases().length) {
              <section class="troops-section">
                <span class="eyebrow">Bases CEDEAO en alerte standard</span>
                <div class="base-grid">
                  @for (base of cedeaoBases(); track base.id) {
                    <article class="base-card" [class]="'tone-' + (base.tone || 'stable')">
                      <strong>{{ base.name || base.label || 'Base' }}</strong>
                      @if (base.country) {
                        <small>{{ base.country }}</small>
                      }
                      <p>{{ base.role || base.status || '—' }}</p>
                    </article>
                  }
                </div>
              </section>
            }
          </div>

          <footer class="troops-drawer-foot">
            <span class="foot-disclaimer">
              ADS-B public, advisory only · sources OSINT (ACLED-like, FlightRadar-like, OSINT public)
            </span>
            <button type="button" class="action-link muted" (click)="closed.emit()">
              Fermer
            </button>
          </footer>
        </aside>
      </div>
    }
  `,
  styles: [
    `
      :host { display: contents; }
      .troops-drawer-root {
        position: fixed;
        inset: 0;
        z-index: 1300;
        display: flex;
        justify-content: flex-end;
      }
      .troops-drawer-backdrop {
        position: absolute;
        inset: 0;
        border: 0;
        background: rgba(2, 6, 10, 0.62);
        backdrop-filter: blur(2px);
        cursor: pointer;
      }
      .troops-drawer-panel {
        position: relative;
        width: min(640px, 100vw);
        height: 100%;
        display: flex;
        flex-direction: column;
        border-left: 1px solid rgba(241, 180, 90, 0.32);
        background: rgba(4, 10, 14, 0.97);
        box-shadow: -16px 0 48px rgba(0, 0, 0, 0.45);
        animation: troops-drawer-in 200ms var(--mission-ease-out);
      }
      @keyframes troops-drawer-in {
        from { transform: translateX(16px); opacity: 0.6; }
        to   { transform: translateX(0);    opacity: 1; }
      }
      .troops-drawer-head {
        position: sticky;
        top: 0;
        z-index: 2;
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--mission-space-3);
        padding: var(--mission-space-5);
        border-bottom: 1px solid var(--mission-border);
        background: rgba(4, 10, 14, 0.97);
      }
      .troops-drawer-head-copy { min-width: 0; flex: 1 1 auto; }
      .troops-drawer-head h2 {
        margin: var(--mission-space-2) 0 0;
        font-size: var(--mission-text-lg);
        line-height: 1.3;
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
      }
      .troops-drawer-summary {
        margin: var(--mission-space-2) 0 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .troops-drawer-close {
        flex: 0 0 auto;
        width: 32px;
        height: 32px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-secondary);
        font-size: 22px;
        line-height: 1;
        cursor: pointer;
      }
      .troops-drawer-close:hover {
        border-color: var(--sentinel-accent-muted);
        color: var(--mission-text-primary);
      }
      .troops-drawer-close:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .troops-drawer-body {
        flex: 1 1 auto;
        overflow-y: auto;
        padding: var(--mission-space-5);
        display: grid;
        gap: var(--mission-space-5);
      }
      .eyebrow {
        display: block;
        margin-bottom: var(--mission-space-2);
        color: var(--mission-warning);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
      }

      .risk-pill {
        display: inline-flex;
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid var(--mission-border);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
        color: var(--mission-text-secondary);
      }
      .risk-pill.warn {
        border-color: rgba(241, 180, 90, 0.42);
        background: var(--mission-warning-soft);
        color: var(--mission-warning);
      }
      .publisher-badge {
        display: inline-block;
        margin-left: 6px;
        padding: 3px 8px;
        border: 1px solid rgba(151, 185, 164, 0.18);
        border-radius: 999px;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }

      .troops-stats {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: var(--mission-space-2);
      }
      .stat-card {
        display: grid;
        gap: 2px;
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
      }
      .stat-card.warn { border-color: rgba(241, 180, 90, 0.32); }
      .stat-card .stat-label {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
      }
      .stat-card strong {
        font-size: 22px;
        font-family: var(--mission-font-mono);
        font-variant-numeric: tabular-nums;
        color: var(--mission-text-primary);
      }
      .stat-card small {
        color: var(--mission-text-tertiary);
        font-size: 10px;
      }

      .troops-section {
        display: grid;
        gap: var(--mission-space-2);
      }
      .empty {
        margin: 0;
        padding: var(--mission-space-3);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-sm);
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-sm);
      }

      .track-table-wrap {
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
        overflow-x: auto;
      }
      .track-table {
        width: 100%;
        border-collapse: collapse;
        font-family: var(--mission-font-mono);
        font-size: 11px;
      }
      .track-table thead th {
        position: sticky;
        top: 0;
        background: rgba(8, 14, 18, 0.92);
        color: var(--mission-text-tertiary);
        text-align: left;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 500;
        padding: 8px 10px;
        border-bottom: 1px solid var(--mission-border);
      }
      .track-table tbody td {
        padding: 8px 10px;
        color: var(--mission-text-primary);
        border-bottom: 1px solid rgba(151, 185, 164, 0.06);
        white-space: nowrap;
      }
      .track-table tbody tr {
        cursor: pointer;
        transition: background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .track-table tbody tr:hover {
        background: rgba(241, 180, 90, 0.05);
      }
      .track-table tbody tr:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: -2px;
      }
      .track-table .num {
        text-align: right;
        font-variant-numeric: tabular-nums;
      }
      .track-table .cs {
        color: var(--sentinel-accent-strong);
      }
      .track-table .route {
        color: var(--mission-text-secondary);
      }
      .track-table .route em {
        margin: 0 4px;
        color: var(--mission-text-tertiary);
        font-style: normal;
      }

      .status-chip {
        display: inline-flex;
        padding: 2px 8px;
        border-radius: 999px;
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        border: 1px solid var(--mission-border);
        color: var(--mission-text-secondary);
      }
      .status-chip.tone-stable {
        border-color: rgba(63, 209, 141, 0.4);
        background: var(--mission-success-soft);
        color: var(--mission-success);
      }
      .status-chip.tone-watch {
        border-color: rgba(241, 180, 90, 0.4);
        background: var(--mission-warning-soft);
        color: var(--mission-warning);
      }
      .status-chip.tone-critical {
        border-color: rgba(240, 100, 118, 0.42);
        background: var(--mission-critical-soft);
        color: var(--mission-critical);
      }

      .zone-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: var(--mission-space-2);
      }
      .zone-card {
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-left-width: 3px;
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
      }
      .zone-card.tone-watch    { border-left-color: var(--mission-warning); }
      .zone-card.tone-stable   { border-left-color: var(--mission-success); }
      .zone-card.tone-critical { border-left-color: var(--mission-critical); }
      .zone-card header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--mission-space-2);
      }
      .zone-card strong {
        font-size: var(--mission-text-sm);
        color: var(--mission-text-primary);
      }
      .zone-card .zone-source {
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--mission-text-tertiary);
      }
      .zone-card p {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }

      .base-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: var(--mission-space-2);
      }
      .base-card {
        display: grid;
        gap: 4px;
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-left-width: 3px;
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
      }
      .base-card.tone-stable { border-left-color: var(--mission-success); }
      .base-card.tone-watch  { border-left-color: var(--mission-warning); }
      .base-card strong {
        font-size: var(--mission-text-sm);
        color: var(--mission-text-primary);
      }
      .base-card small {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .base-card p {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }

      .troops-drawer-foot {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--mission-space-3);
        padding: var(--mission-space-4) var(--mission-space-5);
        border-top: 1px solid var(--mission-border);
        background: rgba(4, 8, 13, 0.6);
      }
      .foot-disclaimer {
        flex: 1 1 auto;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
      }
      .action-link {
        display: inline-flex;
        align-items: center;
        min-height: 36px;
        padding: 8px 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-primary);
        font-size: var(--mission-text-sm);
        cursor: pointer;
      }
      .action-link.muted { background: transparent; color: var(--mission-text-secondary); }
      .action-link:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }

      @media (max-width: 540px) {
        .troops-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @media (prefers-reduced-motion: reduce) {
        .troops-drawer-panel { animation: none; }
      }
    `,
  ],
})
export class VpTroopsTheaterDrawerComponent {
  @Input() open = false;
  @Input() snapshot: TroopsSahelSnapshot | null = null;
  @Output() closed = new EventEmitter<void>();
  @Output() trackSelected = new EventEmitter<TroopsTrack>();

  readonly defaultDisclaimer =
    'ADS-B advisory only — snapshot scenario, aucune donnee operationnelle classifiee.';

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.open) this.closed.emit();
  }

  tracks(): TroopsTrack[] {
    return this.snapshot?.tracks || [];
  }

  watchZones(): TroopsWatchZone[] {
    return this.snapshot?.watch_zones || [];
  }

  cedeaoBases(): TroopsCedeaoBase[] {
    return this.snapshot?.cedeao_bases || [];
  }

  averageAltitude(): string {
    const tracks = this.tracks();
    const altitudes = tracks
      .map((t) => Number(t.altitude_ft))
      .filter((value) => Number.isFinite(value));
    if (!altitudes.length) return '—';
    const avg = Math.round(altitudes.reduce((a, b) => a + b, 0) / altitudes.length);
    return avg.toLocaleString('fr-FR');
  }

  capturedAtLabel(): string {
    const value = this.snapshot?.captured_at;
    if (!value) return '14h30';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '14h30';
    const hh = String(date.getHours()).padStart(2, '0');
    const mm = String(date.getMinutes()).padStart(2, '0');
    return `${hh}h${mm}`;
  }

  statusLabel(tone?: string): string {
    const key = (tone || 'stable').toLowerCase();
    if (key === 'watch') return 'A suivre';
    if (key === 'critical') return 'Tendu';
    return 'Stable';
  }

  zoneSource(zone: TroopsWatchZone): string {
    if (zone.source) return zone.source;
    return 'OSINT public';
  }

  alertLabel(zone: TroopsWatchZone): string {
    if (zone.alert_level) return zone.alert_level;
    const tone = (zone.tone || 'watch').toLowerCase();
    if (tone === 'critical') return 'Niveau eleve';
    if (tone === 'stable')   return 'Niveau standard';
    return 'A suivre';
  }
}
