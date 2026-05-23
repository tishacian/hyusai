import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit';
import { WorkspaceMapComponent } from './workspace-map.component';
import type { VpMapPreviewContext } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-map-preview',
  standalone: true,
  imports: [CommonModule, RouterLink, GlyphComponent, WorkspaceMapComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="map-preview-panel content-panel">
      <div class="panel-heading-row">
        <div>
          <span class="eyebrow">{{ context.label || 'Carte fusionnee' }}</span>
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
        <div class="map-canvas-wrap">
          <app-workspace-map
            [compact]="true"
            [previewMode]="true"
            [previewLayers]="context.geoPreview.active_layers || null"
            [zones]="$any(context.zones)"
            [map]="context.map"
            [mapSystem]="context.mapSystem"
            [selectedZoneId]="context.topZoneId"
          />
        </div>
        <aside class="zone-scores" aria-label="Scores par zone">
          @for (zone of context.geoPreview.zone_scores; track zone.name) {
            <article [class]="toneClass(zone.tone)">
              <span>{{ zone.name }}</span>
              <strong>{{ zone.score }}%</strong>
              @if (zone.trend) {
                <small>{{ zone.trend }}</small>
              }
            </article>
          }
        </aside>
      </div>
    </article>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .map-preview-panel {
        min-width: 0;
        height: 100%;
      }
      .panel-heading-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 10px;
      }
      .eyebrow {
        display: block;
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }
      h2 {
        margin: 4px 0 0;
        font-size: 16px;
      }
      .map-layout {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 132px;
        gap: 10px;
        align-items: stretch;
      }
      .map-canvas-wrap {
        min-height: 280px;
        height: 280px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        overflow: hidden;
      }
      .map-canvas-wrap app-workspace-map {
        display: block;
        height: 100%;
      }
      .zone-scores {
        display: grid;
        gap: 8px;
        align-content: start;
      }
      .zone-scores article {
        padding: 9px 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.58);
      }
      .zone-scores article.critical {
        border-color: rgba(240, 100, 118, 0.34);
        background: linear-gradient(135deg, var(--mission-danger-wash), rgba(4, 8, 13, 0.62));
      }
      .zone-scores article span {
        display: block;
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
      }
      .zone-scores strong {
        display: block;
        margin-top: 4px;
        font-size: 22px;
        line-height: 1;
      }
      .zone-scores small {
        display: block;
        margin-top: 4px;
        color: var(--mission-trust);
        font-family: var(--ck-font-mono);
        font-size: 10px;
      }
      .action-button {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 7px 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text);
        font-size: 12px;
        text-decoration: none;
        cursor: pointer;
      }
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
