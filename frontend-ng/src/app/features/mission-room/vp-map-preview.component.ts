import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { GlyphComponent } from '@app/shared/cockpit';
import {
  MaritimeTrackingService,
  type MaritimeVesselsSnapshot,
  type VesselPosition,
} from '@app/core/maritime-tracking.service';
import { ApiService } from '@app/core/api.service';
import { WorkspaceMapComponent } from './workspace-map.component';
import type { VpMapPreviewContext, VpZoneScore } from './vp-cockpit.types';

type MaritimeVesselsResponse = MaritimeVesselsSnapshot;

interface WebcamCycleEntry {
  source_id: string;
  label?: string | null;
  proxy_url: string;
}

interface ActiveWebcam {
  source_id: string;
  proxy_url: string;
  label?: string | null;
  attribution?: string | null;
  label_disclaimer?: string | null;
  vessel_mmsi?: string | null;
  vessel_name?: string | null;
  cargo_id?: string | null;
  cycle: WebcamCycleEntry[];
  origin: 'manual' | 'auto_select';
}

const DEFAULT_WEBCAM_CYCLE: WebcamCycleEntry[] = [
  {
    source_id: 'apm-apapa-gate-1',
    label: 'APM Apapa Gate Cam #1 (demo Abidjan)',
    proxy_url: '/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1',
  },
  {
    source_id: 'apm-apapa-gate-2',
    label: 'APM Apapa Gate Cam #2 (demo Abidjan)',
    proxy_url: '/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-2',
  },
  {
    source_id: 'paa-aerial-vue',
    label: 'PAA - vue aerienne (galerie officielle)',
    proxy_url: '/api/v1/mission-room/webcams/proxy?source_id=paa-aerial-vue',
  },
  {
    source_id: 'paa-terminal-petrolier',
    label: 'PAA - terminal petrolier',
    proxy_url: '/api/v1/mission-room/webcams/proxy?source_id=paa-terminal-petrolier',
  },
];

const VESSEL_TYPE_COLORS: Record<string, string> = {
  cargo: '#22C55E',
  container: '#22C55E',
  tanker: '#F97316',
  roro: '#71B5F2',
  passenger: '#9D7CF0',
  fishing: '#94A4B6',
  tug: '#94A4B6',
  other: '#94A4B6',
};

const HIGHLIGHT_VIOLET = '#B488FF';
const DEFAULT_BBOX = '-4.25,5.05,-3.75,5.40';

type VesselZoomMode = 'country' | 'abidjan';

const COUNTRY_CAMERA = {
  longitude: -5.45,
  latitude: 7.52,
  zoom: 5.55,
  duration_ms: 420,
} as const;
const ABIDJAN_CAMERA = {
  longitude: -4.0,
  latitude: 5.25,
  zoom: 10.4,
  duration_ms: 460,
} as const;

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
        <div class="map-canvas-host">
          <div class="map-canvas-wrap" aria-label="Aperçu carte fusionnée">
            <app-workspace-map
              [compact]="true"
              [previewMode]="true"
              [previewLayers]="previewLayersWithMaritime()"
              [zones]="$any(context.zones)"
              [map]="context.map"
              [mapSystem]="context.mapSystem"
              [mapState]="previewMapState"
              [userSelectedZoom]="vesselZoomMode"
              [selectedZoneId]="context.topZoneId"
              [vessels]="vesselsEnabled && maritimeLayerVisible ? vessels : null"
              [highlightedVesselMmsi]="selectedVessel?.mmsi || null"
              (vesselSelected)="selectVessel($event)"
            />
          </div>

          @if (vesselsEnabled && vessels.length) {
            <div class="vessels-overlay-controls" aria-label="Contrôles couche maritime">
              <span class="vessel-count-chip" aria-live="polite">
                <span class="vessel-count-dot" aria-hidden="true"></span>
                {{ vessels.length }} navires AIS · Abidjan / Vridi
              </span>
              <button
                type="button"
                class="vessel-zoom-toggle"
                [attr.aria-pressed]="vesselZoomMode === 'abidjan'"
                [disabled]="!maritimeLayerVisible"
                (click)="toggleVesselZoom($event)"
              >
                @if (vesselZoomMode === 'country') {
                  Zoom Abidjan
                } @else {
                  Vue pays
                }
              </button>
            </div>
          }
        </div>
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
        @if (vesselsEnabled) {
          <button
            type="button"
            class="legend-item legend-toggle maritime"
            role="switch"
            [attr.aria-checked]="maritimeLayerVisible"
            [attr.aria-pressed]="maritimeLayerVisible"
            [class.is-on]="maritimeLayerVisible"
            (click)="toggleMaritimeLayer($event)"
          >
            <span class="legend-dot maritime-dot" aria-hidden="true"></span>
            Maritime · AIS · {{ vessels.length }} navires
          </button>
          <button
            type="button"
            class="legend-item port-webcam"
            aria-label="Ouvrir la webcam port demo APM Apapa"
            (click)="openDemoPortWebcam($event)"
          >
            <span class="legend-dot port-dot" aria-hidden="true"></span>
            Port Vridi · cargo demo
          </button>
        }
      </footer>

      @if (webcamDrawerOpen && activeWebcam) {
        <div class="webcam-drawer" role="dialog" aria-modal="true" aria-label="Webcam port plein écran">
          <button
            type="button"
            class="webcam-drawer-backdrop"
            aria-label="Fermer la vue webcam"
            (click)="closeWebcamDrawer()"
          ></button>
          <div class="webcam-drawer-card">
            <header class="webcam-drawer-head">
              <div>
                <span class="eyebrow">Vignette port plein écran</span>
                <h3>{{ activeWebcam.label || activeWebcam.source_id }}</h3>
              </div>
              <button
                type="button"
                class="webcam-drawer-close"
                aria-label="Fermer la webcam"
                (click)="closeWebcamDrawer()"
              >
                ×
              </button>
            </header>
            <img
              [src]="webcamDisplayUrl(activeWebcam)"
              [attr.alt]="activeWebcam.label || 'Snapshot webcam port'"
              class="webcam-drawer-image"
              referrerpolicy="no-referrer"
            />
            <footer class="webcam-drawer-foot">
              <small *ngIf="activeWebcam.label_disclaimer">{{ activeWebcam.label_disclaimer }}</small>
              <small *ngIf="activeWebcam.attribution">Attribution : {{ activeWebcam.attribution }}</small>
              <small *ngIf="activeWebcam.vessel_name">
                Référence vessel : {{ activeWebcam.vessel_name }}<ng-container *ngIf="activeWebcam.vessel_mmsi"> · MMSI {{ activeWebcam.vessel_mmsi }}</ng-container>
              </small>
            </footer>
          </div>
        </div>
      }

      @if (vesselsEnabled) {
        <aside
          class="vessels-info-strip"
          [class.has-error]="vesselError && !vessels.length"
          aria-label="Détail couche maritime AIS"
        >
          <header class="vessels-info-head">
            <div>
              <span class="eyebrow">Couche maritime · {{ vesselProviderLabel }}</span>
              <h3>Navires (AIS) · Abidjan / Vridi</h3>
            </div>
            <span class="vessels-meta" *ngIf="vesselsResponse">
              {{ vessels.length }}/{{ vesselsResponse.vessels?.length || 0 }} navires
            </span>
          </header>

          @if (vessels.length) {
            <ul class="vessel-legend" aria-label="Légende navires">
              <li [style.color]="vesselColor('cargo')"><span class="dot"></span>Cargo</li>
              <li [style.color]="vesselColor('tanker')"><span class="dot"></span>Tanker</li>
              <li [style.color]="vesselColor('roro')"><span class="dot"></span>Ro-Ro</li>
              <li [style.color]="vesselColor('passenger')"><span class="dot"></span>Passager</li>
              <li [style.color]="vesselColor('fishing')"><span class="dot"></span>Pêche</li>
              <li [style.color]="vesselColor('other')"><span class="dot"></span>Autre</li>
              <li class="highlighted" [style.color]="HIGHLIGHT_VIOLET"><span class="dot"></span>Cargo lié projet</li>
            </ul>

            @if (selectedVessel; as vessel) {
              <div class="vessel-tooltip" role="status">
                <strong>{{ vessel.name }}</strong>
                <span class="vessel-meta">MMSI {{ vessel.mmsi }}<ng-container *ngIf="vessel.imo"> · IMO {{ vessel.imo }}</ng-container></span>
                <span class="vessel-meta" *ngIf="vessel.destination">→ {{ vessel.destination }}<ng-container *ngIf="vessel.eta"> · ETA {{ vessel.eta }}</ng-container></span>
                <span class="vessel-meta tiny">{{ vesselProviderLabel }} · {{ vessel.vessel_type || 'navire' }}</span>
                @if (vessel.linked_cargo_id) {
                  <span class="aya-badge">Cargo lié au projet Centre Drones Napié</span>
                }
              </div>
            }

            @if (activeWebcam; as webcam) {
              <aside class="vessel-webcam" aria-label="Vignette webcam port">
                <header class="vessel-webcam-head">
                  <span class="eyebrow">
                    @if (webcam.origin === 'auto_select') {
                      Auto-sélection AYA · vignette port
                    } @else {
                      Vignette port (clic marker)
                    }
                  </span>
                  <button
                    type="button"
                    class="webcam-close"
                    aria-label="Fermer la vignette webcam"
                    (click)="closeWebcamVignette()"
                  >
                    ×
                  </button>
                </header>
                <button
                  type="button"
                  class="webcam-thumb-button"
                  aria-label="Ouvrir la webcam port en grand"
                  (click)="openWebcamDrawer()"
                >
                  <img
                    [src]="webcamDisplayUrl(webcam)"
                    [attr.alt]="webcam.label || 'Snapshot webcam port'"
                    class="webcam-thumb"
                    loading="lazy"
                    decoding="async"
                    referrerpolicy="no-referrer"
                  />
                  <span class="webcam-label">{{ webcam.label || 'Webcam port' }}</span>
                </button>
                <p class="webcam-disclaimer" *ngIf="webcam.label_disclaimer || webcam.attribution">
                  <ng-container *ngIf="webcam.label_disclaimer">{{ webcam.label_disclaimer }}</ng-container>
                  <ng-container *ngIf="webcam.attribution"> · {{ webcam.attribution }}</ng-container>
                </p>
                <div class="webcam-cycle" *ngIf="webcam.cycle.length > 1">
                  @for (entry of webcam.cycle; track entry.source_id) {
                    <button
                      type="button"
                      class="webcam-cycle-pill"
                      [class.active]="entry.source_id === webcam.source_id"
                      (click)="selectWebcamSource(entry)"
                    >
                      {{ entry.label || entry.source_id }}
                    </button>
                  }
                </div>
              </aside>
            }
          } @else {
            <div class="vessels-empty" role="status">
              <small>{{ vesselErrorMessage }}</small>
            </div>
          }
        </aside>
      }
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
        min-height: clamp(500px, 48vh, 640px);
        display: grid;
        grid-template-columns: minmax(0, 1fr) 144px;
        gap: var(--mission-space-3);
        align-items: stretch;
      }
      .map-canvas-wrap {
        min-height: 0;
        height: 100%;
        border: 1px solid rgba(62, 230, 138, 0.2);
        border-radius: 12px;
        overflow: hidden;
        padding: 0;
        width: 100%;
        background: var(--mission-inset);
        appearance: none;
        font: inherit;
        color: inherit;
        text-align: left;
        cursor: pointer;
        box-shadow: inset 0 1px 14px rgba(0, 0, 0, 0.32);
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          box-shadow var(--mission-dur-fast) var(--mission-ease-out);
      }
      .map-canvas-wrap:hover {
        border-color: rgba(62, 230, 138, 0.38);
        box-shadow:
          inset 0 1px 14px rgba(0, 0, 0, 0.32),
          0 0 0 1px rgba(62, 230, 138, 0.12);
      }
      .legend-item.port-webcam {
        border-color: rgba(62, 230, 138, 0.32);
        background: rgba(62, 230, 138, 0.08);
      }
      .legend-dot.port-dot {
        background: var(--sentinel-accent);
        box-shadow: 0 0 0 2px rgba(62, 230, 138, 0.24);
      }
      .map-canvas-wrap app-workspace-map {
        display: block;
        height: 100%;
      }
      .map-canvas-host {
        position: relative;
        min-width: 0;
        height: 100%;
        display: grid;
        grid-template-rows: 1fr;
      }
      .map-canvas-host > .map-canvas-wrap {
        grid-row: 1 / 2;
        grid-column: 1 / 2;
      }
      /*
       * Vessels are rendered natively by deck.gl inside <app-workspace-map>
       * (see WorkspaceMapComponent.buildDeckLayers), so they inherit
       * MapLibre's projection on pan/zoom/resize. Only the legend chip and
       * "Zoom Abidjan / Vue pays" toggle remain in this overlay-controls
       * row positioned absolutely on top of the map canvas.
       */
      .vessels-overlay-controls {
        position: absolute;
        left: 12px;
        top: 12px;
        z-index: 5;
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
        pointer-events: auto;
      }
      .vessel-count-chip {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        padding: 5px 11px;
        border-radius: 999px;
        border: 1px solid rgba(62, 230, 138, 0.28);
        background: rgba(10, 17, 24, 0.88);
        color: var(--mission-text-secondary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        backdrop-filter: blur(8px);
      }
      .vessel-count-dot {
        width: 7px;
        height: 7px;
        border-radius: 999px;
        background: var(--sentinel-accent);
        box-shadow: 0 0 0 0 rgba(101, 214, 110, 0.5);
        animation: vessel-live-pulse 2s ease-in-out infinite;
      }
      @keyframes vessel-live-pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(101, 214, 110, 0.45); }
        50% { box-shadow: 0 0 0 5px rgba(101, 214, 110, 0); }
      }
      .vessel-zoom-toggle {
        appearance: none;
        padding: 5px 11px;
        border-radius: 999px;
        border: 1px solid rgba(62, 230, 138, 0.22);
        background: rgba(10, 17, 24, 0.88);
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        cursor: pointer;
        backdrop-filter: blur(8px);
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .vessel-zoom-toggle:hover {
        border-color: rgba(62, 230, 138, 0.42);
        color: var(--mission-text-secondary);
      }
      .vessel-zoom-toggle[aria-pressed='true'] {
        border-color: rgba(62, 230, 138, 0.48);
        background: rgba(62, 230, 138, 0.14);
        color: var(--mission-text-primary);
      }
      .vessel-zoom-toggle:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .zone-scores {
        height: 100%;
        display: grid;
        gap: var(--mission-space-2);
        grid-auto-rows: minmax(0, 1fr);
        align-content: stretch;
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
        min-height: 0;
        display: grid;
        align-content: center;
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
      .legend-toggle {
        appearance: none;
        margin: 0;
        padding: 4px 9px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        background: rgba(4, 8, 13, 0.62);
        color: var(--mission-text-tertiary);
        font: inherit;
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        cursor: pointer;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .legend-toggle .maritime-dot { background: #B488FF; }
      .legend-toggle.maritime.is-on {
        border-color: rgba(180, 136, 255, 0.55);
        color: #d2c3ff;
        background: rgba(180, 136, 255, 0.14);
      }
      .legend-toggle:hover {
        border-color: rgba(180, 136, 255, 0.55);
      }
      .legend-toggle:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .legend-toggle:not(.is-on) .maritime-dot {
        opacity: 0.4;
      }
      .vessels-info-strip {
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: linear-gradient(180deg, rgba(8, 14, 20, 0.55), rgba(4, 8, 13, 0.32));
      }
      .vessels-info-strip.has-error { border-style: dashed; }
      .vessels-info-head {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: var(--mission-space-2);
      }
      .vessels-info-head h3 {
        margin: var(--mission-space-1) 0 0;
        font-size: var(--mission-text-sm);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
      }
      .vessels-meta {
        font-family: var(--mission-font-mono);
        font-size: 10px;
        color: var(--mission-text-tertiary);
      }
      .vessel-legend {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-wrap: wrap;
        gap: var(--mission-space-2) var(--mission-space-4);
        font-family: var(--mission-font-mono);
        font-size: 11px;
        color: var(--mission-text-tertiary);
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .vessel-legend li {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .vessel-legend .dot {
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-bottom: 10px solid currentColor;
        border-radius: 0;
        background: transparent !important;
        color: inherit;
      }
      .vessel-legend li {
        color: var(--mission-text-tertiary);
      }
      .vessel-legend li .dot {
        color: inherit;
        border-bottom-color: currentColor;
      }
      .vessel-legend .highlighted .dot {
        filter: drop-shadow(0 0 3px rgba(180, 136, 255, 0.75));
      }
      .vessel-tooltip {
        display: grid;
        gap: 2px;
        padding: var(--mission-space-2) var(--mission-space-3);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.78);
        border: 1px solid var(--mission-border);
        color: var(--mission-text-primary);
        font-size: var(--mission-text-xs);
      }
      .vessel-tooltip strong { font-size: var(--mission-text-sm); }
      .vessel-meta {
        font-family: var(--mission-font-mono);
        color: var(--mission-text-tertiary);
      }
      .vessel-meta.tiny { font-size: 10px; opacity: 0.78; }
      .aya-badge {
        margin-top: 4px;
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        background: rgba(180, 136, 255, 0.18);
        color: #d2c3ff;
        border: 1px solid rgba(180, 136, 255, 0.48);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        width: max-content;
      }
      .vessels-empty {
        padding: var(--mission-space-3);
        border-radius: var(--mission-radius-sm);
        border: 1px dashed var(--mission-border);
        text-align: center;
        color: var(--mission-text-tertiary);
      }
      .vessel-webcam {
        display: grid;
        gap: 6px;
        padding: var(--mission-space-2);
        border-radius: var(--mission-radius-sm);
        background: rgba(8, 14, 20, 0.78);
        border: 1px solid rgba(62, 230, 138, 0.38);
        box-shadow: 0 6px 18px rgba(8, 12, 18, 0.55);
      }
      .vessel-webcam-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 6px;
      }
      .vessel-webcam-head .eyebrow {
        color: var(--sentinel-accent);
      }
      .webcam-close,
      .webcam-drawer-close {
        appearance: none;
        background: transparent;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 999px;
        width: 22px;
        height: 22px;
        color: var(--mission-text-tertiary);
        font-size: 14px;
        line-height: 1;
        cursor: pointer;
      }
      .webcam-close:hover,
      .webcam-drawer-close:hover {
        border-color: var(--sentinel-accent-muted);
        color: var(--mission-text-primary);
      }
      .webcam-thumb-button {
        appearance: none;
        border: 1px solid rgba(255, 255, 255, 0.08);
        background: transparent;
        padding: 0;
        cursor: pointer;
        display: grid;
        gap: 4px;
        border-radius: var(--mission-radius-sm);
        overflow: hidden;
      }
      .webcam-thumb-button:hover {
        border-color: rgba(180, 136, 255, 0.55);
      }
      .webcam-thumb {
        width: 240px;
        height: 135px;
        object-fit: cover;
        display: block;
        background: rgba(4, 8, 13, 0.7);
      }
      .webcam-label {
        display: block;
        padding: 4px 6px;
        font-family: var(--mission-font-mono);
        font-size: 10px;
        text-align: left;
        color: var(--sentinel-accent);
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .webcam-disclaimer {
        margin: 0;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.04em;
      }
      .webcam-cycle {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
      }
      .webcam-cycle-pill {
        appearance: none;
        background: rgba(4, 8, 13, 0.62);
        color: var(--mission-text-tertiary);
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        padding: 3px 8px;
        font-family: var(--mission-font-mono);
        font-size: 10px;
        cursor: pointer;
      }
      .webcam-cycle-pill.active {
        color: #d2c3ff;
        background: rgba(180, 136, 255, 0.18);
        border-color: rgba(180, 136, 255, 0.55);
      }
      .webcam-cycle-pill:hover {
        border-color: rgba(180, 136, 255, 0.55);
      }
      .webcam-drawer {
        position: fixed;
        inset: 0;
        display: grid;
        place-items: center;
        padding: var(--mission-space-4);
        z-index: 30;
      }
      .webcam-drawer-backdrop {
        position: absolute;
        inset: 0;
        background: rgba(4, 8, 13, 0.78);
        border: 0;
        cursor: pointer;
      }
      .webcam-drawer-card {
        position: relative;
        max-width: 920px;
        width: 100%;
        background: var(--mission-inset);
        border: 1px solid rgba(180, 136, 255, 0.55);
        border-radius: var(--mission-radius-md);
        box-shadow: var(--mission-shadow-soft);
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-3);
      }
      .webcam-drawer-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: var(--mission-space-2);
      }
      .webcam-drawer-head h3 {
        margin: 4px 0 0;
        font-size: var(--mission-text-md);
        color: var(--mission-text-primary);
      }
      .webcam-drawer-image {
        width: 100%;
        max-height: 70vh;
        object-fit: contain;
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.7);
      }
      .webcam-drawer-foot {
        display: grid;
        gap: 2px;
        font-family: var(--mission-font-mono);
        font-size: 11px;
        color: var(--mission-text-tertiary);
      }
      @media (max-width: 900px) {
        .map-layout {
          min-height: auto;
          grid-template-columns: 1fr;
        }
        .map-canvas-host {
          min-height: 360px;
        }
        .zone-scores {
          height: auto;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          grid-auto-rows: auto;
        }
      }
    `,
  ],
})
export class VpMapPreviewComponent implements OnInit, OnDestroy {
  @Input() context: VpMapPreviewContext = {
    route: '/hypervisor/mission-room/strategie',
    label: 'Carte fusionnee',
    zones: [],
    map: null,
    mapSystem: null,
    geoPreview: { zone_scores: [] },
    topZoneId: null,
  };
  /**
   * Optional bbox `west,south,east,north`. Defaults to the Abidjan/Vridi
   * baseline window so the demo always renders something.
   */
  @Input() vesselsBbox: string = DEFAULT_BBOX;
  @Input() vesselsEnabled: boolean = true;
  @Output() openMap = new EventEmitter<void>();
  @Output() zoneSelected = new EventEmitter<VpZoneScore>();
  @Output() vesselSelected = new EventEmitter<VesselPosition>();

  vesselsResponse: MaritimeVesselsResponse | null = null;
  vessels: VesselPosition[] = [];
  vesselError = false;
  vesselErrorMessage = 'AIS indisponible — mode baseline démo';
  selectedVessel: VesselPosition | null = null;
  activeWebcam: ActiveWebcam | null = null;
  activeWebcamImageUrl: string | null = null;
  webcamDrawerOpen = false;
  webcamReloadKey = Date.now();
  vesselZoomMode: VesselZoomMode = 'country';
  previewMapState: Record<string, any> | null = null;
  /**
   * Local visibility flag for the maritime AIS overlay layer. Defaults
   * to ``true`` so the SENTINEL-CI demo opens with the 16 vessels
   * visible. The Vice Premier Ministre can toggle the layer off via the legend chip
   * "Maritime · AIS · n navires" without affecting the map zoom.
   */
  maritimeLayerVisible = true;
  readonly HIGHLIGHT_VIOLET = HIGHLIGHT_VIOLET;

  private readonly maritimeTracking = inject(MaritimeTrackingService);
  private readonly api = inject(ApiService);
  private readonly cdr = inject(ChangeDetectorRef);
  private vesselsSub: Subscription | null = null;
  private webcamLoadSub: Subscription | null = null;
  private activeWebcamObjectUrl: string | null = null;
  private readonly showWebcamListener = (event: Event) => {
    this.handleShowWebcamEvent(event as CustomEvent);
  };

  ngOnInit(): void {
    if (this.vesselsEnabled) {
      this.loadVessels();
    }
    window.addEventListener('agentium:assistant-show-webcam', this.showWebcamListener);
  }

  ngOnDestroy(): void {
    this.vesselsSub?.unsubscribe();
    this.webcamLoadSub?.unsubscribe();
    this.revokeActiveWebcamObjectUrl();
    window.removeEventListener('agentium:assistant-show-webcam', this.showWebcamListener);
  }

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

  /**
   * Make sure `maritime-traffic` is always part of the preview layers
   * advertised to the inner `<app-workspace-map>` so that the deck.gl
   * vessel layer can render. Without this the cockpit preview would
   * inherit the backend default (`visible: False`) and the 16 AIS
   * vessels would silently disappear from the map.
   */
  previewLayersWithMaritime(): string[] {
    const requested = this.context.geoPreview.active_layers || [];
    if (requested.includes('maritime-traffic')) return requested;
    return [...requested, 'maritime-traffic'];
  }

  vesselColor(kind?: string): string {
    return VESSEL_TYPE_COLORS[(kind || 'other').toLowerCase()] || VESSEL_TYPE_COLORS['other'];
  }

  toggleVesselZoom(event?: Event): void {
    event?.stopPropagation();
    event?.preventDefault();
    this.vesselZoomMode = this.vesselZoomMode === 'country' ? 'abidjan' : 'country';
    this.applyVesselZoomMode();
  }

  toggleMaritimeLayer(event?: Event): void {
    event?.stopPropagation();
    event?.preventDefault();
    this.maritimeLayerVisible = !this.maritimeLayerVisible;
    this.cdr.markForCheck();
  }

  private applyVesselZoomMode(): void {
    const camera = this.vesselZoomMode === 'abidjan' ? ABIDJAN_CAMERA : COUNTRY_CAMERA;
    this.previewMapState = { camera: { ...camera } };
    this.cdr.markForCheck();
  }

  openDemoPortWebcam(event?: Event): void {
    event?.stopPropagation();
    event?.preventDefault();
    const demoVessel = this.vessels.find(
      (vessel) =>
        vessel.mmsi === '627012345'
        || vessel.linked_cargo_id === 'cargo-abidjan-supply-001'
        || /atlantic trader/i.test(vessel.name || ''),
    );
    if (demoVessel) {
      this.selectVessel(demoVessel);
      return;
    }
    this.handleShowWebcamEvent({
      detail: {
        source_id: 'apm-apapa-gate-1',
        label: 'APM Apapa Gate Cam #1 (demo Abidjan)',
        cargo_id: 'cargo-abidjan-supply-001',
        vessel_mmsi: '627012345',
      },
    } as CustomEvent);
  }

  selectVessel(vessel: VesselPosition): void {
    this.selectedVessel = vessel;
    this.maritimeTracking.selectVessel(vessel);
    this.vesselSelected.emit(vessel);
    const sourceId =
      vessel.recommended_webcam_source_id ||
      (vessel.linked_cargo_id === 'cargo-abidjan-supply-001' || vessel.mmsi === '627012345'
        ? 'apm-apapa-gate-1'
        : undefined);
    if (sourceId) {
      const cycle = this.buildDefaultCycle(sourceId);
      const primary =
        cycle.find((entry) => entry.source_id === sourceId) || cycle[0];
      if (primary) {
        this.activeWebcam = {
          source_id: primary.source_id,
          proxy_url: primary.proxy_url,
          label: primary.label,
          attribution: this.attributionFor(primary.source_id),
          label_disclaimer: this.disclaimerFor(primary.source_id),
          vessel_mmsi: vessel.mmsi,
          vessel_name: vessel.name,
          cargo_id: vessel.linked_cargo_id || null,
          cycle,
          origin: 'manual',
        };
        this.webcamReloadKey = Date.now();
        this.loadWebcamPreview(primary.proxy_url);
        this.cdr.markForCheck();
      }
    }
  }

  selectWebcamSource(entry: WebcamCycleEntry): void {
    if (!this.activeWebcam) return;
    this.activeWebcam = {
      ...this.activeWebcam,
      source_id: entry.source_id,
      proxy_url: entry.proxy_url,
      label: entry.label || entry.source_id,
      attribution: this.attributionFor(entry.source_id) || this.activeWebcam.attribution,
      label_disclaimer:
        this.disclaimerFor(entry.source_id) || this.activeWebcam.label_disclaimer,
    };
    this.webcamReloadKey = Date.now();
    this.loadWebcamPreview(entry.proxy_url);
    this.cdr.markForCheck();
  }

  openWebcamDrawer(): void {
    if (!this.activeWebcam) return;
    this.webcamDrawerOpen = true;
    this.webcamReloadKey = Date.now();
    this.cdr.markForCheck();
  }

  closeWebcamDrawer(): void {
    this.webcamDrawerOpen = false;
    this.cdr.markForCheck();
  }

  closeWebcamVignette(): void {
    this.activeWebcam = null;
    this.activeWebcamImageUrl = null;
    this.revokeActiveWebcamObjectUrl();
    this.webcamDrawerOpen = false;
    this.cdr.markForCheck();
  }

  private handleShowWebcamEvent(event: CustomEvent): void {
    const detail = (event && event.detail) as
      | {
          source_id?: string;
          proxy_url?: string;
          label?: string | null;
          attribution?: string | null;
          label_disclaimer?: string | null;
          vessel_mmsi?: string | null;
          vessel_name?: string | null;
          cargo_id?: string | null;
          cycle?: WebcamCycleEntry[];
        }
      | undefined;
    if (!detail || !detail.source_id) return;
    const fallbackCycle = this.buildDefaultCycle(detail.source_id);
    const incomingCycle = (detail.cycle || []).filter(
      (entry) => entry && entry.source_id && entry.proxy_url,
    );
    const cycle = incomingCycle.length ? incomingCycle : fallbackCycle;
    const proxy_url =
      detail.proxy_url ||
      cycle.find((entry) => entry.source_id === detail.source_id)?.proxy_url ||
      `/api/v1/mission-room/webcams/proxy?source_id=${detail.source_id}`;
    this.activeWebcam = {
      source_id: detail.source_id,
      proxy_url,
      label: detail.label || cycle.find((entry) => entry.source_id === detail.source_id)?.label || null,
      attribution: detail.attribution || this.attributionFor(detail.source_id),
      label_disclaimer:
        detail.label_disclaimer || this.disclaimerFor(detail.source_id),
      vessel_mmsi: detail.vessel_mmsi || null,
      vessel_name: detail.vessel_name || null,
      cargo_id: detail.cargo_id || null,
      cycle,
      origin: 'auto_select',
    };
    this.webcamReloadKey = Date.now();
    this.loadWebcamPreview(proxy_url);
    this.cdr.markForCheck();
  }

  webcamDisplayUrl(webcam: ActiveWebcam): string {
    // Proxy URLs require JWT — never bind them directly to <img src>.
    return this.activeWebcamImageUrl || '';
  }

  private loadWebcamPreview(rawUrl: string): void {
    const path = rawUrl.startsWith('/api/v1') ? rawUrl.slice('/api/v1'.length) : rawUrl;
    if (!path.startsWith('/mission-room/webcams/proxy')) {
      this.revokeActiveWebcamObjectUrl();
      this.activeWebcamImageUrl = this.withRelativeSnapshotCacheBust(rawUrl);
      this.cdr.markForCheck();
      return;
    }
    if (this.webcamLoadSub) return;
    this.activeWebcamImageUrl = null;
    this.webcamLoadSub = this.api.getBlob(path).subscribe({
      next: (blob) => {
        this.webcamLoadSub = null;
        this.revokeActiveWebcamObjectUrl();
        this.activeWebcamObjectUrl = URL.createObjectURL(blob);
        this.activeWebcamImageUrl = this.activeWebcamObjectUrl;
        this.cdr.markForCheck();
      },
      error: () => {
        this.webcamLoadSub = null;
        this.revokeActiveWebcamObjectUrl();
        this.activeWebcamImageUrl = null;
        this.cdr.markForCheck();
      },
    });
  }

  private withRelativeSnapshotCacheBust(rawUrl: string): string {
    if (!rawUrl) return '';
    if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
      try {
        const url = new URL(rawUrl);
        url.searchParams.set('_mc', String(Math.floor(this.webcamReloadKey / 60_000)));
        return url.toString();
      } catch {
        return rawUrl;
      }
    }
    const separator = rawUrl.includes('?') ? '&' : '?';
    return `${rawUrl}${separator}_mc=${Math.floor(this.webcamReloadKey / 60_000)}`;
  }

  private revokeActiveWebcamObjectUrl(): void {
    if (!this.activeWebcamObjectUrl) return;
    URL.revokeObjectURL(this.activeWebcamObjectUrl);
    this.activeWebcamObjectUrl = null;
  }

  private buildDefaultCycle(primarySourceId: string): WebcamCycleEntry[] {
    const seen = new Set<string>();
    const ordered: WebcamCycleEntry[] = [];
    const primary = DEFAULT_WEBCAM_CYCLE.find((entry) => entry.source_id === primarySourceId);
    if (primary) {
      ordered.push(primary);
      seen.add(primary.source_id);
    } else if (primarySourceId) {
      ordered.push({
        source_id: primarySourceId,
        label: primarySourceId,
        proxy_url: `/api/v1/mission-room/webcams/proxy?source_id=${primarySourceId}`,
      });
      seen.add(primarySourceId);
    }
    for (const entry of DEFAULT_WEBCAM_CYCLE) {
      if (!seen.has(entry.source_id)) {
        ordered.push(entry);
        seen.add(entry.source_id);
      }
    }
    return ordered;
  }

  private attributionFor(sourceId: string): string {
    if (sourceId.startsWith('apm-apapa')) return 'APM Terminals (Apapa) - snapshot public';
    if (sourceId.startsWith('paa-')) return 'Port Autonome d\u0027Abidjan (PAA) - phototheque officielle';
    return '';
  }

  private disclaimerFor(sourceId: string): string {
    if (sourceId.startsWith('apm-apapa')) {
      return 'Référence visuelle — démo Abidjan (source : APM Terminals Apapa, Lagos)';
    }
    if (sourceId.startsWith('paa-')) {
      return 'Phototheque officielle PAA - reference visuelle (pas de live)';
    }
    return '';
  }

  get vesselProviderLabel(): string {
    if (!this.vesselsResponse) return 'AIS · baseline';
    const provider = this.vesselsResponse.provider || 'baseline';
    const source = this.vesselsResponse.source || 'baseline';
    if (source === 'baseline' && provider !== 'baseline') {
      return `AIS · ${provider} (fallback baseline)`;
    }
    return `AIS · ${provider}`;
  }

  private loadVessels(): void {
    this.vesselsSub?.unsubscribe();
    this.vesselsSub = this.maritimeTracking
      .getSnapshot(this.vesselsBbox || DEFAULT_BBOX, 50)
      .subscribe({
        next: (response) => {
          this.vesselsResponse = response;
          this.vesselError = false;
          this.vessels = (response.vessels || []).filter(
            (vessel) => Number.isFinite(Number(vessel?.lat)) && Number.isFinite(Number(vessel?.lon)),
          );
          if (!this.vessels.length) {
            this.vesselErrorMessage = 'AIS indisponible — mode baseline démo';
          }
          this.cdr.markForCheck();
        },
        error: () => {
          this.vesselError = true;
          this.vesselsResponse = null;
          this.vessels = [];
          this.vesselErrorMessage = 'AIS indisponible — mode baseline démo';
          this.cdr.markForCheck();
        },
      });
  }
}
