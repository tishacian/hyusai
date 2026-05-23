import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit';
import { WorkspaceMapComponent } from './workspace-map.component';
import type { VpMapPreviewContext, VpZoneScore } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-map-preview',
  standalone: true,
  imports: [CommonModule, RouterLink, GlyphComponent, WorkspaceMapComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="map-preview-panel">
      <div class="panel-heading-row">
        <div>
          <span class="eyebrow">{{ context.label || 'Carte fusionnée' }}</span>
          <h2>Territoire et signaux</h2>
        </div>
        <a
          [routerLink]="context.route || '/hypervisor/mission-room/strategie'"
          [queryParams]="mapQueryParams()"
          class="action-button compact"
          (click)="openMap.emit()"
        >
          <ck-glyph name="sliders" [size]="14" />
          <span>Ouvrir carte</span>
        </a>
      </div>
      <div class="map-layout">
        <button
          type="button"
          class="map-canvas-wrap"
          aria-label="Ouvrir la carte fusionnée"
          (click)="openMap.emit()"
        >
          <app-workspace-map
            [compact]="true"
            [previewMode]="true"
            [previewLayers]="context.geoPreview.active_layers || null"
            [zones]="$any(context.zones)"
            [map]="context.map"
            [mapSystem]="context.mapSystem"
            [selectedZoneId]="context.topZoneId"
          />
        </button>
        <aside class="zone-scores" aria-label="Scores par zone">
          @if (!context.geoPreview.zone_scores.length) {
            <div class="zone-empty" role="status">
              <small>Scores en cours de collecte…</small>
            </div>
          }
          @for (zone of context.geoPreview.zone_scores; track zone.id || zone.name) {
            <button
              type="button"
              class="zone-score"
              [class]="toneClass(zone.tone)"
              (click)="zoneSelected.emit(zone)"
            >
              <span class="zone-name">{{ zone.name }}</span>
              <strong>{{ zone.score }}%</strong>
              @if (zone.trend) {
                <small>{{ zone.trend }}</small>
              }
            </button>
          }
        </aside>
      </div>
      <footer class="map-legend" aria-label="Légende carte">
        <span class="legend-item critical"><span class="legend-dot"></span>Tendu</span>
        <span class="legend-item elevated"><span class="legend-dot"></span>Surveillance</span>
        <span class="legend-item stable"><span class="legend-dot"></span>Stable</span>
      </footer>
    </article>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; height: 100%; }
      .map-preview-panel {
        min-width: 0;
        height: 100%;
        display: grid;
        grid-template-rows: auto 1fr auto;
        gap: var(--mission-space-3);
        padding: var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-lg);
        background: linear-gradient(180deg, rgba(8, 14, 20, 0.62), rgba(4, 8, 13, 0.42));
        box-shadow: var(--mission-shadow-soft);
      }
      .panel-heading-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--mission-space-3);
      }
      .eyebrow {
        display: block;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      h2 {
        margin: var(--mission-space-1) 0 0;
        font-size: var(--mission-text-md);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: var(--mission-lh-tight);
        color: var(--mission-text-primary);
      }
      .map-layout {
        min-height: 0;
        display: grid;
        grid-template-columns: minmax(0, 1fr) 144px;
        gap: var(--mission-space-3);
        align-items: stretch;
      }
      .map-canvas-wrap {
        min-height: 280px;
        height: 100%;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        overflow: hidden;
        padding: 0;
        width: 100%;
        background: var(--mission-inset);
        appearance: none;
        font: inherit;
        color: inherit;
        text-align: left;
        cursor: pointer;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          box-shadow var(--mission-dur-fast) var(--mission-ease-out);
      }
      .map-canvas-wrap:hover {
        border-color: var(--sentinel-accent-muted);
        box-shadow: 0 0 0 1px rgba(101, 214, 110, 0.18);
      }
      .map-canvas-wrap:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .map-canvas-wrap app-workspace-map {
        display: block;
        height: 100%;
      }
      .zone-scores {
        display: grid;
        gap: var(--mission-space-2);
        align-content: start;
      }
      .zone-empty {
        padding: var(--mission-space-3);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-sm);
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
        text-align: center;
      }
      .zone-score {
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.58);
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
      .zone-score:hover {
        border-color: var(--sentinel-accent-muted);
        background: rgba(101, 214, 110, 0.04);
      }
      .zone-score:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .zone-score.critical {
        border-color: rgba(240, 100, 118, 0.34);
        background: linear-gradient(135deg, var(--mission-critical-soft), rgba(4, 8, 13, 0.62));
      }
      .zone-score.elevated {
        border-color: rgba(241, 180, 90, 0.32);
      }
      .zone-name {
        display: block;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
      }
      .zone-score strong {
        display: block;
        margin-top: var(--mission-space-1);
        font-family: var(--mission-font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--mission-text-lg);
        font-weight: 600;
        line-height: 1;
        color: var(--mission-text-primary);
      }
      .zone-score small {
        display: block;
        margin-top: var(--mission-space-1);
        color: var(--mission-success);
        font-family: var(--mission-font-mono);
        font-size: 10px;
      }
      .zone-score.critical small { color: var(--mission-critical); }
      .zone-score.elevated small { color: var(--mission-warning); }
      .action-button {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 7px 11px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-primary);
        font-size: var(--mission-text-xs);
        text-decoration: none;
        cursor: pointer;
        transition: border-color var(--mission-dur-fast) var(--mission-ease-out);
      }
      .action-button:hover { border-color: var(--sentinel-accent-muted); }
      .action-button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .map-legend {
        display: flex;
        flex-wrap: wrap;
        gap: var(--mission-space-3);
        padding-top: var(--mission-space-1);
        border-top: 1px dashed var(--mission-border);
      }
      .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--mission-text-tertiary);
      }
      .legend-dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--mission-success);
      }
      .legend-item.elevated .legend-dot { background: var(--mission-warning); }
      .legend-item.critical .legend-dot { background: var(--mission-critical); }
      @media (max-width: 900px) {
        .map-layout { grid-template-columns: 1fr; }
        .zone-scores { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
    `,
  ],
})
export class VpMapPreviewComponent {
  @Input() context: VpMapPreviewContext = {
    route: '/hypervisor/mission-room/strategie',
    label: 'Carte fusionnee',
    zones: [],
    map: null,
    mapSystem: null,
    geoPreview: { zone_scores: [] },
    topZoneId: null,
  };
  @Output() openMap = new EventEmitter<void>();
  @Output() zoneSelected = new EventEmitter<VpZoneScore>();

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'watch') return 'elevated';
    return 'stable';
  }

  mapQueryParams(): Record<string, string> {
    const layers = this.context.geoPreview.active_layers || [];
    const params: Record<string, string> = {};
    if (layers.length) params['layers'] = layers.join(',');
    if (this.context.geoPreview.top_zone_id) params['zone'] = this.context.geoPreview.top_zone_id;
    return params;
  }
}
