import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  ViewChild,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';

type MapZone = {
  id: string;
  name: string;
  level: number;
  tone: string;
  polygon: string;
  centroid: { x: number; y: number };
  [key: string]: any;
};

type MapLayerControl = {
  key: string;
  label: string;
  shortLabel: string;
  tone: string;
  group?: string;
  icon?: string;
  status?: string;
  stateLabel?: string;
  freshness?: string;
  freshnessAt?: string;
  failureReason?: string | null;
  sourceKind?: string;
  count: number;
  confidence: number;
  visible: boolean;
  defaultVisible?: boolean;
};

type BasemapOption = {
  key: string;
  label: string;
  description?: string;
  style?: Record<string, any> | string;
};

@Component({
  selector: 'app-workspace-map',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="workspace-map"
      [class.compact]="compact"
      [class.preview-mode]="previewMode"
      [class.is-fallback]="fallback"
      [class.basemap-administrative]="selectedBasemapKey === 'administrative'"
      [class.basemap-command]="selectedBasemapKey === 'command'"
      [class.basemap-dark]="selectedBasemapKey === 'dark'"
      [class.basemap-contours]="selectedBasemapKey === 'contours'"
    >
      <div #mapCanvas class="maplibre-canvas" [class.hidden]="fallback"></div>

      <div class="map-frame-overlay">
        <div class="map-scanline"></div>
        <div class="map-compass">N</div>
        <div class="map-control-panel" [class.collapsed]="!controlsOpen" (click)="$event.stopPropagation()">
          <header class="map-control-heading">
            <button type="button" class="map-control-toggle" (click)="toggleControls()">
              <strong>Couches carte</strong>
              <small>{{ activeLayerCount }} couches</small>
            </button>
          </header>
          @if (controlsOpen) {
            <section class="control-section">
              <span>Fond</span>
              <div class="basemap-switch">
                @for (basemap of basemapOptions; track basemap.key) {
                  <button
                    type="button"
                    [class.active]="selectedBasemapKey === basemap.key"
                    [attr.aria-pressed]="selectedBasemapKey === basemap.key"
                    (click)="switchBasemap(basemap.key)"
                  >
                    {{ basemap.label }}
                  </button>
                }
              </div>
            </section>

            <section class="control-section">
              <span>Couches</span>
              <label class="layer-search">
                <span>Rechercher</span>
                <input type="search" [value]="layerSearch" (input)="setLayerSearch($any($event.target).value)" placeholder="navire, presse, agenda..." />
              </label>
              <div class="layer-list">
                @for (layer of filteredLayerControls; track layer.key) {
                  <button
                    type="button"
                    class="layer-toggle"
                    [class.active]="isLayerActive(layer.key)"
                    [attr.aria-pressed]="isLayerActive(layer.key)"
                    (click)="toggleLayer(layer.key)"
                  >
                    <i [class]="'tone-' + layer.tone"></i>
                    <strong>{{ layer.shortLabel }}</strong>
                    <small>{{ layer.group || 'Source' }} · {{ layer.count }} · {{ layer.confidence }}%</small>
                    <em>{{ layer.stateLabel || (isLayerActive(layer.key) ? 'visible' : 'masqué') }} · {{ layer.freshness || 'source workspace' }}</em>
                  </button>
                }
              </div>
            </section>
          }
        </div>
        <button type="button" class="map-reset" (click)="resetCountry(); $event.stopPropagation()">Recentrer Côte d’Ivoire</button>
        <div class="map-zoom-controls" (click)="$event.stopPropagation()">
          <button type="button" aria-label="Zoom avant" (click)="zoomIn()">+</button>
          <button type="button" aria-label="Zoom arrière" (click)="zoomOut()">−</button>
          <button type="button" aria-label="Vue pays" (click)="resetCountry()">⌂</button>
        </div>
        @if (!legendOpen) {
          <button type="button" class="map-legend-toggle" (click)="toggleLegend(); $event.stopPropagation()">Niveaux</button>
        }
        @if (legendOpen) {
          <div class="map-legend">
            <strong>Niveaux</strong>
            <span><i class="stable"></i>stable</span>
            <span><i class="monitoring"></i>surveillance</span>
            <span><i class="elevated"></i>élevé</span>
            <span><i class="critical"></i>critique</span>
          </div>
        }
        @if (isLayerActive('maritime-traffic')) {
          <div class="map-maritime-legend">
            <strong>Maritime</strong>
            <span><i class="corridor"></i>corridor</span>
            <span><i class="port"></i>ports</span>
            <span><i class="density"></i>densité</span>
            <span><i class="alert"></i>alerte</span>
          </div>
        }
        @if (briefOpen && selectedBriefZone(); as zone) {
          <article class="map-brief-popup" (click)="$event.stopPropagation()">
            <header>
              <span>Brief operationnel</span>
              <button type="button" (click)="closeBrief()">Fermer</button>
            </header>
            <strong>{{ zone.name }}</strong>
            <div class="brief-score">
              <b>{{ zoneBrief(zone).score || zone.level }}%</b>
              <small>{{ zoneBrief(zone).severity || zone.tone }}</small>
            </div>
            <div class="brief-drivers">
              @for (driver of zoneBriefDrivers(zone); track driver) {
                <span>{{ driver }}</span>
              }
            </div>
            <p>{{ zoneBrief(zone).recommendation || zone['recommendations']?.[0] || 'Qualifier puis preparer arbitrage.' }}</p>
            <div class="brief-source-row">
              @for (source of zoneBriefSources(zone); track source) {
                <small>{{ source }}</small>
              }
            </div>
            <footer>
              <button type="button" (click)="emitEvidenceAction('arbitrage', zone)">Preparer arbitrage</button>
              <button type="button" (click)="emitEvidenceAction('aya', zone)">Demander AYA</button>
            </footer>
          </article>
        }
      </div>

      @if (fallback) {
        <svg class="fallback-map" [attr.viewBox]="map?.['view_box'] || '200 40 470 480'" role="img">
          @for (zone of zones; track zone.id) {
            <polygon
              [attr.points]="zone.polygon"
              [attr.fill]="zoneFill(zone)"
              [attr.opacity]="selectedZoneId === zone.id ? 0.94 : 0.60"
              (click)="selectZone(zone)"
            ></polygon>
            <circle
              [attr.cx]="zone.centroid.x"
              [attr.cy]="zone.centroid.y"
              [attr.r]="zonePulseRadius(zone)"
              [attr.fill]="zoneFill(zone)"
              opacity="0.25"
            ></circle>
            <text [attr.x]="zone.centroid.x" [attr.y]="zone.centroid.y" text-anchor="middle">{{ zone.name }}</text>
          }
        </svg>
      }

      <div class="map-hud">
        <span>Zone prioritaire</span>
        <strong>{{ selectedZoneLabel }}</strong>
        <em>{{ selectedZoneLevel }}%</em>
      </div>

      <div class="map-attribution">{{ mapAttribution }}</div>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        min-width: 0;
      }

      .workspace-map {
        position: relative;
        min-height: 360px;
        height: 100%;
        overflow: hidden;
        border: 1px solid rgba(101, 214, 110, 0.28);
        border-radius: 10px;
        background:
          radial-gradient(circle at 58% 44%, rgba(101, 214, 110, 0.055), transparent 34%),
          linear-gradient(135deg, rgba(4, 8, 12, 0.98), rgba(9, 14, 20, 0.97));
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03), 0 24px 70px rgba(0,0,0,0.22);
      }

      .workspace-map::after {
        content: '';
        position: absolute;
        inset: 18px;
        pointer-events: none;
        border-radius: 12px;
        border: 1px solid rgba(125, 211, 252, 0.07);
        box-shadow:
          inset 0 0 22px rgba(101, 214, 110, 0.025),
          inset 0 -12px 24px rgba(0, 0, 0, 0.06);
        z-index: 3;
      }

      .workspace-map::before {
        content: '';
        position: absolute;
        inset: 0;
        pointer-events: none;
        background-image:
          linear-gradient(rgba(125, 213, 255, 0.018) 1px, transparent 1px),
          linear-gradient(90deg, rgba(125, 213, 255, 0.016) 1px, transparent 1px);
        background-size: 54px 54px;
        mask-image: linear-gradient(180deg, rgba(0,0,0,0.22), transparent 84%);
        z-index: 2;
      }

      .workspace-map.basemap-administrative::before {
        opacity: 0.10;
      }

      .workspace-map.basemap-administrative::after {
        border-color: rgba(20, 80, 114, 0.20);
        box-shadow: inset 0 0 28px rgba(8, 20, 32, 0.08);
      }

      .workspace-map.compact {
        min-height: 260px;
        border-radius: 8px;
      }

      .workspace-map.preview-mode {
        min-height: 100%;
        height: 100%;
        pointer-events: none;
      }

      .workspace-map.preview-mode .map-control-panel,
      .workspace-map.preview-mode .map-reset,
      .workspace-map.preview-mode .map-legend,
      .workspace-map.preview-mode .map-legend-toggle,
      .workspace-map.preview-mode .map-maritime-legend,
      .workspace-map.preview-mode .map-compass,
      .workspace-map.preview-mode .map-zoom-controls,
      .workspace-map.preview-mode .map-hud,
      .workspace-map.preview-mode .map-brief {
        display: none !important;
      }

      .workspace-map.preview-mode {
        min-height: 100%;
        height: 100%;
        pointer-events: none;
      }

      .workspace-map.compact .map-control-panel,
      .workspace-map.compact .map-reset,
      .workspace-map.compact .map-legend,
      .workspace-map.compact .map-maritime-legend,
      .workspace-map.compact .map-compass,
      .workspace-map.preview-mode .map-control-panel,
      .workspace-map.preview-mode .map-reset,
      .workspace-map.preview-mode .map-legend,
      .workspace-map.preview-mode .map-maritime-legend,
      .workspace-map.preview-mode .map-compass,
      .workspace-map.preview-mode .map-zoom-controls,
      .workspace-map.preview-mode .map-brief-popup {
        display: none;
      }

      .workspace-map.compact .map-hud {
        left: 12px;
        bottom: 12px;
        padding: 7px 9px;
      }

      .maplibre-canvas,
      .fallback-map {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
      }

      .maplibre-canvas {
        z-index: 1;
        filter: none;
      }

      .workspace-map.basemap-administrative .maplibre-canvas {
        filter: contrast(1.02) saturate(0.92) brightness(0.99);
      }

      .workspace-map.basemap-command .maplibre-canvas {
        filter: contrast(1.12) brightness(0.96) saturate(0.86);
      }

      .workspace-map.basemap-dark .maplibre-canvas {
        filter: none;
      }

      .workspace-map.basemap-contours .maplibre-canvas {
        filter: contrast(1.01) saturate(0.86) brightness(0.98);
      }

      .map-frame-overlay {
        position: absolute;
        inset: 0;
        z-index: 4;
        pointer-events: none;
      }

      .map-scanline {
        display: none;
      }

      .map-compass {
        position: absolute;
        right: 16px;
        top: 16px;
        width: 34px;
        height: 34px;
        display: grid;
        place-items: center;
        border-radius: 999px;
        border: 1px solid rgba(148, 197, 229, 0.18);
        background: rgba(7, 12, 19, 0.72);
        color: rgba(232, 241, 255, 0.72);
        font: 800 11px/1 var(--mission-mono, monospace);
        letter-spacing: 0.08em;
      }

      .map-control-panel {
        position: absolute;
        left: 16px;
        top: 16px;
        width: min(286px, calc(100% - 92px));
        display: grid;
        gap: 9px;
        padding: 11px;
        border: 1px solid rgba(148, 197, 229, 0.22);
        border-radius: 14px;
        background: rgba(2, 5, 8, 0.92);
        box-shadow: 0 18px 42px rgba(0, 0, 0, 0.40), inset 0 0 0 1px rgba(255,255,255,0.035);
        backdrop-filter: blur(10px) saturate(1.05);
        pointer-events: auto;
      }

      .map-control-panel.collapsed {
        width: min(210px, calc(100% - 92px));
        gap: 0;
        padding: 0;
        border-radius: 10px;
        background: rgba(2, 5, 8, 0.82);
      }

      .map-control-heading {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding-bottom: 2px;
      }

      .map-control-panel.collapsed .map-control-heading {
        padding-bottom: 0;
      }

      .map-control-toggle {
        width: 100%;
        min-height: 38px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 9px 11px;
        border: 0;
        border-radius: 10px;
        background: transparent;
        text-align: left;
        cursor: pointer;
      }

      .map-control-toggle:hover {
        background: rgba(148, 197, 229, 0.08);
      }

      .map-control-heading strong {
        color: rgba(245, 251, 255, 0.94);
        font-size: 13px;
        line-height: 1;
      }

      .map-control-heading small {
        color: rgba(148, 197, 229, 0.78);
        font: 750 10px/1 var(--mission-mono, monospace);
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      .control-section {
        display: grid;
        gap: 8px;
      }

      .control-section > span {
        color: rgba(148, 197, 229, 0.82);
        font: 800 10px/1 var(--mission-mono, monospace);
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }

      .basemap-switch {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }

      .basemap-switch button,
      .map-reset {
        min-height: 31px;
        padding: 7px 10px;
        border-radius: 999px;
        border: 1px solid rgba(148, 197, 229, 0.18);
        background: rgba(11, 20, 31, 0.88);
        color: rgba(207, 239, 255, 0.70);
        font: 750 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.10em;
        text-transform: uppercase;
        cursor: pointer;
        transition: background 150ms ease, border-color 150ms ease, color 150ms ease, opacity 150ms ease;
      }

      .basemap-switch button.active,
      .map-reset:hover {
        border-color: rgba(148, 197, 229, 0.54);
        background: rgba(10, 34, 49, 0.82);
        color: rgba(232, 247, 255, 0.92);
        box-shadow: 0 0 18px rgba(79, 178, 229, 0.13);
      }

      .basemap-switch button:hover,
      .layer-toggle:hover {
        border-color: rgba(148, 197, 229, 0.56);
        color: rgba(245, 251, 255, 0.95);
      }

      .layer-search {
        min-width: 0;
        display: grid;
        grid-template-columns: 1fr;
        gap: 5px;
      }

      .layer-search span {
        color: rgba(148, 197, 229, 0.70);
        font: 800 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }

      .layer-search input {
        width: 100%;
        min-height: 34px;
        border: 1px solid rgba(148, 197, 229, 0.18);
        border-radius: 10px;
        background: rgba(6, 12, 19, 0.92);
        color: rgba(245, 251, 255, 0.90);
        font-size: 12px;
        padding: 7px 10px;
        outline: none;
      }

      .layer-search input:focus {
        border-color: rgba(148, 197, 229, 0.52);
        box-shadow: 0 0 0 2px rgba(79, 178, 229, 0.10);
      }

      .layer-list {
        display: grid;
        grid-template-columns: 1fr;
        gap: 6px;
        max-height: 286px;
        overflow: auto;
        padding-right: 2px;
      }

      .layer-toggle {
        min-width: 0;
        display: grid;
        grid-template-columns: 9px minmax(0, 1fr);
        grid-template-areas: 'tone label' 'tone meta' 'tone fresh';
        column-gap: 8px;
        row-gap: 2px;
        align-items: center;
        padding: 9px 10px;
        border-radius: 10px;
        border: 1px solid rgba(148, 197, 229, 0.18);
        background: rgba(14, 24, 36, 0.92);
        color: rgba(232, 241, 255, 0.72);
        text-align: left;
        cursor: pointer;
      }

      .layer-toggle.active {
        border-color: rgba(148, 197, 229, 0.50);
        background: linear-gradient(135deg, rgba(18, 39, 58, 0.98), rgba(12, 23, 36, 0.94));
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04), 0 0 18px rgba(79, 178, 229, 0.10);
      }

      .layer-toggle:not(.active) {
        opacity: 0.58;
      }

      .layer-toggle:not(.active) i {
        box-shadow: none;
      }

      .layer-toggle i {
        grid-area: tone;
        width: 8px;
        height: 30px;
        border-radius: 999px;
        background: #88d7ff;
        box-shadow: 0 0 12px rgba(136, 215, 255, 0.28);
      }

      .layer-toggle i.tone-amber { background: #f1ce71; box-shadow: 0 0 12px rgba(241, 206, 113, 0.28); }
      .layer-toggle i.tone-blue { background: #8fd2ff; box-shadow: 0 0 12px rgba(143, 210, 255, 0.28); }
      .layer-toggle i.tone-cyan { background: #65d66e; box-shadow: 0 0 12px rgba(101, 214, 110, 0.28); }
      .layer-toggle i.tone-green { background: #76dfa6; box-shadow: 0 0 12px rgba(118, 223, 166, 0.28); }
      .layer-toggle i.tone-orange { background: #f28c38; box-shadow: 0 0 12px rgba(242, 140, 56, 0.28); }
      .layer-toggle i.tone-red { background: #f27f8b; box-shadow: 0 0 12px rgba(242, 127, 139, 0.28); }
      .layer-toggle i.tone-violet { background: #b9a5ff; box-shadow: 0 0 12px rgba(185, 165, 255, 0.28); }

      .layer-toggle strong {
        grid-area: label;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        color: rgba(245, 251, 255, 0.90);
        font-size: 12px;
        line-height: 1.1;
        white-space: nowrap;
      }

      .layer-toggle small {
        grid-area: meta;
        color: rgba(172, 192, 212, 0.70);
        font: 700 10px/1.2 var(--mission-mono, monospace);
      }

      .layer-toggle em {
        grid-area: fresh;
        font-style: normal;
        color: rgba(148, 197, 229, 0.62);
        font: 700 9px/1.2 var(--mission-mono, monospace);
      }

      .map-reset {
        position: absolute;
        top: 14px;
        right: 62px;
        z-index: 5;
        pointer-events: auto;
      }

      .map-zoom-controls {
        position: absolute;
        right: 16px;
        top: 58px;
        z-index: 5;
        display: grid;
        border: 1px solid rgba(101, 214, 110, 0.15);
        border-radius: 8px;
        overflow: hidden;
        background: rgba(2, 6, 10, 0.82);
        pointer-events: auto;
        backdrop-filter: blur(10px);
      }

      .map-zoom-controls button {
        width: 36px;
        height: 34px;
        border: 0;
        border-bottom: 1px solid rgba(101, 214, 110, 0.12);
        background: transparent;
        color: rgba(238, 247, 255, 0.86);
        font: 800 16px/1 var(--mission-mono, monospace);
        cursor: pointer;
      }

      .map-zoom-controls button:last-child {
        border-bottom: 0;
        font-size: 12px;
      }

      .map-zoom-controls button:hover {
        background: rgba(101, 214, 110, 0.12);
      }

      .map-legend {
        position: absolute;
        left: 50%;
        right: auto;
        bottom: 56px;
        top: auto;
        transform: translateX(-50%);
        z-index: 5;
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 11px;
        border: 1px solid rgba(148, 197, 229, 0.16);
        border-radius: 999px;
        background: rgba(2, 6, 10, 0.94);
        backdrop-filter: blur(8px);
      }

      .map-legend-toggle {
        position: absolute;
        left: 50%;
        bottom: 16px;
        z-index: 5;
        transform: translateX(-50%);
        min-height: 28px;
        padding: 7px 11px;
        border: 1px solid rgba(148, 197, 229, 0.18);
        border-radius: 999px;
        background: rgba(2, 6, 10, 0.88);
        color: rgba(148, 197, 229, 0.86);
        font: 800 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.14em;
        text-transform: uppercase;
        cursor: pointer;
        pointer-events: auto;
        backdrop-filter: blur(8px);
      }

      .map-legend-toggle.active,
      .map-legend-toggle:hover {
        border-color: rgba(148, 197, 229, 0.34);
        color: rgba(245, 251, 255, 0.92);
      }

      .workspace-map.basemap-contours .map-control-panel,
      .workspace-map.basemap-contours .map-legend,
      .workspace-map.basemap-contours .map-brief-popup,
      .workspace-map.basemap-contours .map-hud,
      .workspace-map.basemap-contours .map-attribution {
        background: rgba(6, 14, 22, 0.92);
      }

      .map-legend span {
        display: flex;
        align-items: center;
        gap: 7px;
        color: rgba(213, 229, 242, 0.72);
        font-size: 11px;
        line-height: 1;
      }

      .map-legend strong {
        color: rgba(148, 197, 229, 0.86);
        font: 800 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }

      .map-legend i {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        display: inline-block;
      }

      .map-legend .stable { background: #76dfa6; }
      .map-legend .monitoring { background: #8fd2ff; }
      .map-legend .elevated { background: #f1ce71; }
      .map-legend .critical { background: #f27f8b; }

      .map-maritime-legend {
        position: absolute;
        right: 18px;
        bottom: 58px;
        z-index: 5;
        display: flex;
        align-items: center;
        gap: 10px;
        max-width: calc(100% - 36px);
        padding: 8px 11px;
        border: 1px solid rgba(80, 184, 238, 0.20);
        border-radius: 999px;
        background: rgba(2, 6, 10, 0.92);
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.22);
        backdrop-filter: blur(8px);
        pointer-events: none;
      }

      .map-maritime-legend strong {
        color: rgba(148, 197, 229, 0.86);
        font: 800 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }

      .map-maritime-legend span {
        display: flex;
        align-items: center;
        gap: 6px;
        color: rgba(213, 229, 242, 0.72);
        font-size: 11px;
        line-height: 1;
        white-space: nowrap;
      }

      .map-maritime-legend i {
        width: 18px;
        height: 3px;
        display: inline-block;
        border-radius: 999px;
      }

      .map-maritime-legend .corridor { background: #65cdf5; }
      .map-maritime-legend .port {
        width: 8px;
        height: 8px;
        background: #ffb15f;
      }
      .map-maritime-legend .density {
        width: 10px;
        height: 10px;
        background: rgba(103, 206, 255, 0.46);
        box-shadow: 0 0 0 5px rgba(103, 206, 255, 0.12);
      }
      .map-maritime-legend .alert {
        width: 8px;
        height: 8px;
        background: #ff7f67;
        box-shadow: 0 0 0 5px rgba(255, 127, 103, 0.14);
      }

      .map-brief-popup {
        position: absolute;
        right: 64px;
        top: 108px;
        z-index: 6;
        width: min(330px, calc(100% - 94px));
        display: grid;
        gap: 9px;
        padding: 12px;
        border: 1px solid rgba(101, 214, 110, 0.26);
        border-radius: 12px;
        background: rgba(2, 6, 10, 0.90);
        box-shadow: 0 22px 54px rgba(0, 0, 0, 0.42);
        backdrop-filter: blur(12px);
        pointer-events: auto;
      }

      .map-brief-popup header,
      .map-brief-popup footer,
      .brief-score,
      .brief-source-row {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .map-brief-popup header,
      .map-brief-popup footer {
        justify-content: space-between;
      }

      .map-brief-popup header span,
      .brief-score small {
        color: rgba(148, 197, 229, 0.84);
        font: 800 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }

      .map-brief-popup > strong {
        color: rgba(245, 251, 255, 0.96);
        font-size: 18px;
        line-height: 1.1;
      }

      .brief-score b {
        color: #f28c38;
        font: 850 22px/1 var(--mission-mono, monospace);
      }

      .brief-drivers {
        display: grid;
        gap: 5px;
      }

      .brief-drivers span {
        padding-left: 9px;
        border-left: 2px solid rgba(101, 214, 110, 0.48);
        color: rgba(232, 241, 255, 0.82);
        font-size: 12px;
        line-height: 1.28;
      }

      .map-brief-popup p {
        margin: 0;
        color: rgba(213, 229, 242, 0.78);
        font-size: 12px;
        line-height: 1.35;
      }

      .brief-source-row {
        flex-wrap: wrap;
      }

      .brief-source-row small {
        max-width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        padding: 4px 6px;
        border: 1px solid rgba(148, 197, 229, 0.13);
        border-radius: 999px;
        color: rgba(172, 192, 212, 0.70);
      }

      .map-brief-popup button {
        min-height: 26px;
        padding: 5px 8px;
        border: 1px solid rgba(101, 214, 110, 0.20);
        border-radius: 6px;
        background: rgba(11, 20, 31, 0.86);
        color: rgba(232, 241, 255, 0.82);
        font: 750 10px/1 var(--mission-mono, monospace);
        cursor: pointer;
      }

      .map-brief-popup button:hover {
        border-color: rgba(242, 140, 56, 0.45);
        color: #f28c38;
      }

      .maplibre-canvas.hidden {
        display: none;
      }

      .fallback-map {
        padding: 16px;
        box-sizing: border-box;
      }

      .fallback-map polygon {
        cursor: pointer;
        stroke: rgba(180, 221, 255, 0.72);
        stroke-width: 1.4;
        filter: drop-shadow(0 0 8px rgba(91, 173, 218, 0.22));
        transition: opacity 160ms ease, filter 160ms ease;
      }

      .fallback-map polygon:hover {
        opacity: 0.95;
        filter: drop-shadow(0 0 14px rgba(125, 213, 255, 0.44));
      }

      .fallback-map circle {
        pointer-events: none;
        animation: mapPulse 3.2s ease-in-out infinite;
      }

      .fallback-map text {
        pointer-events: none;
        fill: rgba(232, 241, 255, 0.88);
        font-size: 18px;
        font-weight: 700;
        paint-order: stroke;
        stroke: rgba(3, 6, 10, 0.85);
        stroke-width: 4px;
      }

      .map-hud {
        position: absolute;
        left: 16px;
        bottom: 16px;
        z-index: 5;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 10px;
        border: 1px solid rgba(101, 214, 110, 0.24);
        border-radius: 999px;
        background: rgba(2, 6, 10, 0.88);
        color: rgba(232, 241, 255, 0.88);
        backdrop-filter: blur(12px);
      }

      .map-hud span {
        color: rgba(148, 197, 229, 0.82);
        font: 700 10px/1 var(--mission-mono, monospace);
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }

      .map-hud strong {
        font-weight: 700;
      }

      .map-hud em {
        font-style: normal;
        font: 750 11px/1 var(--mission-mono, monospace);
        color: #f1ce71;
      }

      .map-attribution {
        position: absolute;
        right: 14px;
        bottom: 13px;
        z-index: 5;
        max-width: min(58%, 420px);
        padding: 5px 8px;
        border-radius: 999px;
        background: rgba(2, 6, 10, 0.82);
        color: rgba(184, 203, 218, 0.58);
        font-size: 10px;
        line-height: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        backdrop-filter: blur(10px);
      }

      .workspace-map.compact .map-attribution {
        display: none;
      }

      @keyframes mapPulse {
        0%, 100% { transform: scale(0.96); opacity: 0.18; }
        50% { transform: scale(1.08); opacity: 0.34; }
      }

      @keyframes mapSweep {
        0%, 100% { transform: translateY(0); opacity: 0.18; }
        50% { transform: translateY(210px); opacity: 0.62; }
      }
    `,
  ],
})
export class WorkspaceMapComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input() zones: MapZone[] = [];
  @Input() map: Record<string, any> | null = null;
  @Input() mapSystem: Record<string, any> | null = null;
  @Input() mapState: Record<string, any> | null = null;
  @Input() selectedZoneId: string | null = null;
  @Input() compact = false;
  @Input() previewMode = false;
  @Input() previewLayers: string[] | null = null;
  @Output() zoneSelected = new EventEmitter<any>();
  @Output() evidenceAction = new EventEmitter<{ action: string; zone: any }>();
  @ViewChild('mapCanvas') private readonly mapCanvas?: ElementRef<HTMLDivElement>;

  fallback = false;
  selectedBasemapKey = 'command';
  controlsOpen = false;
  legendOpen = true;
  briefOpen = false;
  layerSearch = '';

  private readonly cdr = inject(ChangeDetectorRef);
  private readonly activeLayerKeys = new Set<string>();
  private layerStateInitialized = false;
  private mapInstance: any;
  private deckOverlay: any;
  private deckLayersModule: any;
  private focusMarker: any | null = null;

  get layerControls(): MapLayerControl[] {
    const catalog = this.mapSystem?.['layer_registry'] || this.mapSystem?.['layer_catalog'];
    if (Array.isArray(catalog) && catalog.length) {
      return catalog.map((layer: any) => ({
        key: String(layer.key || ''),
        label: String(layer.label || layer.key || ''),
        shortLabel: String(layer.short_label || layer.label || layer.key || ''),
        tone: String(layer.tone || 'cyan'),
        group: layer.group ? String(layer.group) : undefined,
        icon: layer.icon ? String(layer.icon) : undefined,
        status: layer.status ? String(layer.status) : undefined,
        stateLabel: layer.state_label ? String(layer.state_label) : undefined,
        freshness: layer.freshness ? String(layer.freshness) : undefined,
        freshnessAt: layer.freshness_at ? String(layer.freshness_at) : undefined,
        failureReason: layer.failure_reason ? String(layer.failure_reason) : null,
        sourceKind: layer.source_kind ? String(layer.source_kind) : undefined,
        count: Number(layer.count || 0),
        confidence: Math.round(Number(layer.confidence || 0)),
        visible: layer.visible !== false,
        defaultVisible: layer.default_visible !== false,
      })).filter((layer) => layer.key);
    }
    return [
      { key: 'territorial-risk', label: 'Zones de vigilance', shortLabel: 'Zones', tone: 'cyan', count: this.zones.length, confidence: 78, visible: true },
      { key: 'open-intelligence', label: 'Signaux presse', shortLabel: 'Presse', tone: 'blue', count: 3, confidence: 72, visible: true },
      { key: 'regional-context', label: 'Contexte CEDEAO', shortLabel: 'Region', tone: 'orange', count: 6, confidence: 74, visible: true },
      { key: 'strategic-projects', label: 'Projets sensibles', shortLabel: 'Projets', tone: 'green', count: 3, confidence: 69, visible: true },
      { key: 'agenda-windows', label: 'Agenda / fenêtres d’action', shortLabel: 'Agenda', tone: 'amber', count: 5, confidence: 81, visible: true },
      { key: 'visual-streams', label: 'Observations visuelles', shortLabel: 'Visuel', tone: 'violet', count: 1, confidence: 62, visible: true },
      { key: 'maritime-traffic', label: 'Maritime / douanes', shortLabel: 'Maritime', tone: 'blue', count: 5, confidence: 66, visible: false },
      { key: 'preventive-actions', label: 'Actions recommandées', shortLabel: 'Actions', tone: 'red', count: 4, confidence: 74, visible: true },
    ];
  }

  get filteredLayerControls(): MapLayerControl[] {
    const query = this.layerSearch.trim().toLowerCase();
    if (!query) return this.layerControls;
    return this.layerControls.filter((layer) => {
      const haystack = `${layer.key} ${layer.label} ${layer.shortLabel} ${layer.group || ''} ${layer.sourceKind || ''}`.toLowerCase();
      return haystack.includes(query);
    });
  }

  get activeLayerCount(): number {
    return this.activeLayerKeys.size;
  }

  get basemapOptions(): BasemapOption[] {
    const options = this.mapSystem?.['basemap_options'];
    if (Array.isArray(options) && options.length) {
      return options.map((item: any) => ({
        key: String(item.key || ''),
        label: String(item.label || item.key || ''),
        description: item.description,
        style: item.style,
      })).filter((item) => item.key);
    }
    return [
      { key: 'command', label: 'Commandement', style: this.defaultStyle('#151719') },
      { key: 'administrative', label: 'Administratif', style: this.defaultStyle('#12202b') },
      { key: 'dark', label: 'Sombre', style: this.defaultStyle('#05080d') },
      { key: 'contours', label: 'Contours', style: this.defaultStyle('#071018') },
    ];
  }

  get selectedZoneLabel(): string {
    return this.zones.find((zone) => zone.id === this.selectedZoneId)?.name || 'Cote d’Ivoire';
  }

  get selectedZoneLevel(): number {
    return Math.round(this.zones.find((zone) => zone.id === this.selectedZoneId)?.level || 58);
  }

  get mapAttribution(): string {
    return this.mapSystem?.['renderer_config']?.attribution || 'Couches Agentium workspace';
  }

  ngAfterViewInit(): void {
    void this.bootstrapRenderer();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['mapSystem'] || changes['previewMode'] || changes['previewLayers']) {
      this.layerStateInitialized = false;
      this.syncStateFromMapPayload();
      this.applyCurrentBasemap();
    }
    if (changes['zones'] || changes['mapSystem'] || changes['previewMode'] || changes['previewLayers']) {
      if (!this.layerStateInitialized) this.syncStateFromMapPayload();
      this.updateDeckLayers();
    }
    if (changes['mapState'] && this.mapState) {
      this.applyExternalMapState(this.mapState);
    }
    if (changes['selectedZoneId'] && !changes['selectedZoneId'].firstChange) {
      this.briefOpen = true;
      this.focusSelectedZone();
    }
  }

  ngOnDestroy(): void {
    try {
      this.deckOverlay?.finalize?.();
      this.mapInstance?.remove?.();
    } catch {
      // Renderer teardown must never break route changes.
    }
  }

  selectZone(zone: MapZone): void {
    if (this.previewMode) return;
    this.briefOpen = true;
    this.zoneSelected.emit(zone);
  }

  selectedBriefZone(): MapZone | null {
    return this.zones.find((zone) => zone.id === this.selectedZoneId) || this.zones[0] || null;
  }

  zoneBrief(zone: MapZone): any {
    return zone?.['popup_brief'] || {};
  }

  zoneBriefDrivers(zone: MapZone): string[] {
    return (this.zoneBrief(zone).drivers || zone?.['signals'] || []).slice(0, 3);
  }

  zoneBriefSources(zone: MapZone): string[] {
    return (this.zoneBrief(zone).sources || zone?.['sources'] || []).slice(0, 3);
  }

  closeBrief(): void {
    this.briefOpen = false;
    this.cdr.markForCheck();
  }

  emitEvidenceAction(action: string, zone: MapZone): void {
    this.briefOpen = true;
    this.evidenceAction.emit({ action, zone });
  }

  zoneFill(zone: MapZone): string {
    if (zone.tone === 'critical') return '#ef6f7d';
    if (zone.tone === 'watch') return '#edc765';
    return '#69d89b';
  }

  zonePulseRadius(zone: MapZone): number {
    return zone.tone === 'critical' ? 38 : zone.tone === 'watch' ? 27 : 18;
  }

  isLayerActive(key: string): boolean {
    return this.activeLayerKeys.has(key);
  }

  toggleControls(): void {
    this.controlsOpen = !this.controlsOpen;
    this.cdr.markForCheck();
  }

  toggleLegend(): void {
    this.legendOpen = !this.legendOpen;
    this.cdr.markForCheck();
  }

  toggleLayer(key: string): void {
    if (this.activeLayerKeys.has(key)) {
      if (this.activeLayerKeys.size <= 1) return;
      this.activeLayerKeys.delete(key);
    } else {
      this.activeLayerKeys.add(key);
    }
    this.updateDeckLayers();
    this.cdr.markForCheck();
  }

  setLayerSearch(value: string): void {
    this.layerSearch = value || '';
    this.cdr.markForCheck();
  }

  switchBasemap(key: string): void {
    if (this.selectedBasemapKey === key) return;
    this.selectedBasemapKey = key;
    this.applyCurrentBasemap();
    this.cdr.markForCheck();
  }

  resetCountry(): void {
    this.focusMarker = null;
    this.fitCountry(260);
  }

  zoomIn(): void {
    this.mapInstance?.zoomIn?.({ duration: 260 });
  }

  zoomOut(): void {
    this.mapInstance?.zoomOut?.({ duration: 260 });
  }

  private async bootstrapRenderer(): Promise<void> {
    this.syncStateFromMapPayload();
    const renderer = this.mapSystem?.['renderer_config']?.renderer;
    if (renderer && renderer !== 'maplibre') {
      this.enableFallback();
      return;
    }
    if (!this.mapCanvas?.nativeElement) {
      this.enableFallback();
      return;
    }
    try {
      const maplibre = await import('maplibre-gl');
      const deckMapbox = await import('@deck.gl/mapbox');
      this.deckLayersModule = await import('@deck.gl/layers');
      const mapCtor = (maplibre as any).Map || (maplibre as any).default?.Map;
      const overlayCtor = (deckMapbox as any).MapboxOverlay;
      const view = this.mapSystem?.['renderer_config']?.initial_view_state || {};
      this.mapInstance = new mapCtor({
        container: this.mapCanvas.nativeElement,
        style: this.currentBasemapStyle() || this.mapSystem?.['renderer_config']?.style || this.defaultStyle(),
        center: [view.longitude ?? -5.45, view.latitude ?? 7.58],
        zoom: view.zoom ?? (this.compact ? 4.9 : 5.7),
        pitch: this.compact ? 0 : (view.pitch ?? 0),
        bearing: view.bearing ?? 0,
        minZoom: this.compact ? 3.2 : 0.6,
        maxZoom: 13.5,
        interactive: !(this.compact || this.previewMode),
        attributionControl: false,
      });
      this.deckOverlay = new overlayCtor({
        interleaved: false,
        layers: this.buildDeckLayers(),
        getTooltip: (info: any) => this.deckTooltip(info),
      });
      this.mapInstance.on('load', () => {
        this.mapInstance.addControl(this.deckOverlay);
        this.fitCountry(0);
        setTimeout(() => {
          this.mapInstance?.resize?.();
          this.fitCountry(220);
        }, 80);
        this.mapInstance.once?.('idle', () => {
          this.mapInstance?.resize?.();
          this.fitCountry(0);
        });
      });
      this.mapInstance.on('moveend', () => this.updateDeckLayers());
      this.mapInstance.on('error', () => this.enableFallback());
    } catch {
      this.enableFallback();
    }
  }

  private syncStateFromMapPayload(): void {
    const defaultState = this.mapSystem?.['default_map_state'] || {};
    const basemap = String(defaultState.basemap || this.mapSystem?.['renderer_config']?.default_basemap || 'administrative');
    if (!this.basemapOptions.some((option) => option.key === this.selectedBasemapKey)) {
      this.selectedBasemapKey = basemap;
    } else if (!this.selectedBasemapKey) {
      this.selectedBasemapKey = basemap;
    }
    if (this.layerStateInitialized) return;
    const previewLayers = this.resolvePreviewLayers();
    const activeLayers = previewLayers?.length
      ? previewLayers
      : Array.isArray(defaultState.active_layers)
        ? defaultState.active_layers
        : this.layerControls.filter((layer) => layer.visible).map((layer) => layer.key);
    this.activeLayerKeys.clear();
    for (const key of activeLayers) {
      if (this.layerControls.some((layer) => layer.key === key)) {
        this.activeLayerKeys.add(key);
      }
    }
    if (!this.activeLayerKeys.size) {
      for (const layer of this.layerControls.filter((item) => item.visible)) this.activeLayerKeys.add(layer.key);
    }
    this.layerStateInitialized = true;
  }

  private resolvePreviewLayers(): string[] | null {
    if (!this.previewMode) return null;
    const requested = (this.previewLayers || []).filter(Boolean);
    if (requested.length) {
      return requested.map((key) => this.normalizePreviewLayerKey(key)).filter(Boolean) as string[];
    }
    const defaults = ['territorial-risk', 'open-intelligence', 'maritime-traffic'];
    return defaults.filter((key) => this.layerControls.some((layer) => layer.key === key));
  }

  private normalizePreviewLayerKey(key: string): string | null {
    const aliases: Record<string, string> = {
      threat: 'territorial-risk',
      press: 'open-intelligence',
      maritime: 'maritime-traffic',
      projects: 'strategic-projects',
    };
    const normalized = aliases[key] || key;
    return this.layerControls.some((layer) => layer.key === normalized) ? normalized : null;
  }

  private currentBasemapStyle(): Record<string, any> | string | null {
    return this.basemapOptions.find((option) => option.key === this.selectedBasemapKey)?.style || null;
  }

  private applyCurrentBasemap(): void {
    if (!this.mapInstance) return;
    const style = this.currentBasemapStyle();
    if (!style) return;
    const currentCenter = this.mapInstance.getCenter?.();
    const currentZoom = this.mapInstance.getZoom?.();
    const currentPitch = this.mapInstance.getPitch?.() ?? 0;
    const currentBearing = this.mapInstance.getBearing?.() ?? 0;
    const restoreCamera = () => {
      if (
        currentCenter
        && Number.isFinite(Number(currentCenter.lng))
        && Number.isFinite(Number(currentCenter.lat))
        && Number.isFinite(Number(currentZoom))
      ) {
        this.mapInstance?.jumpTo?.({
          center: [Number(currentCenter.lng), Number(currentCenter.lat)],
          zoom: Number(currentZoom),
          pitch: Number(currentPitch),
          bearing: Number(currentBearing),
        });
      }
      this.updateDeckLayers();
    };
    try {
      this.mapInstance.setStyle(style);
      this.mapInstance.once?.('styledata', restoreCamera);
      this.mapInstance.once?.('idle', restoreCamera);
    } catch {
      this.enableFallback();
    }
  }

  private applyExternalMapState(state: Record<string, any>): void {
    const activeLayers = Array.isArray(state['active_layers']) ? state['active_layers'].map(String) : [];
    if (activeLayers.length) {
      this.activeLayerKeys.clear();
      for (const key of activeLayers) {
        if (this.layerControls.some((layer) => layer.key === key)) this.activeLayerKeys.add(key);
      }
      this.layerStateInitialized = true;
    }
    const basemap = String(state['basemap'] || '');
    if (basemap && this.basemapOptions.some((option) => option.key === basemap)) {
      this.selectedBasemapKey = basemap;
      this.applyCurrentBasemap();
    }
    this.focusMarker = this.normalizeFocusMarker(state['focus_marker']);
    const camera = state['camera'] as Record<string, any> | undefined;
    if (
      this.mapInstance
      && Number.isFinite(Number(camera?.['longitude']))
      && Number.isFinite(Number(camera?.['latitude']))
    ) {
      const requestedDuration = Number(camera?.['duration_ms'] ?? 260);
      this.mapInstance.easeTo({
        center: [Number(camera?.['longitude']), Number(camera?.['latitude'])],
        zoom: camera?.['zoom'] ?? (this.compact ? 5.15 : 6.0),
        pitch: 0,
        bearing: 0,
        duration: Math.max(0, Math.min(requestedDuration, 320)),
      });
    }
    this.updateDeckLayers();
    this.cdr.markForCheck();
  }

  private updateDeckLayers(): void {
    if (!this.deckOverlay || !this.deckLayersModule) return;
    this.deckOverlay.setProps({ layers: this.buildDeckLayers(), getTooltip: (info: any) => this.deckTooltip(info) });
  }

  private normalizeFocusMarker(rawMarker: any): any | null {
    if (!rawMarker) return null;
    const longitude = Number(rawMarker.longitude);
    const latitude = Number(rawMarker.latitude);
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return null;
    return {
      longitude,
      latitude,
      label: String(rawMarker.label || 'Vue active'),
      zone_id: rawMarker.zone_id,
      tone: rawMarker.tone || 'visual',
    };
  }

  private fitCountry(duration = 320): void {
    if (!this.mapInstance) return;
    const bounds = this.mapSystem?.['renderer_config']?.bounds || [[-8.65, 4.2], [-2.45, 10.75]];
    const preset = this.mapSystem?.['default_map_state']?.camera || this.mapSystem?.['camera_presets']?.country;
    try {
      this.mapInstance.fitBounds(bounds, {
        padding: this.compact
          ? { top: 20, right: 20, bottom: 20, left: 20 }
          : { top: 48, right: 48, bottom: 64, left: 48 },
        maxZoom: this.compact ? 5.55 : 6.28,
        pitch: 0,
        bearing: 0,
        duration,
      });
    } catch {
      this.mapInstance.easeTo({
        center: [preset?.longitude ?? -5.45, preset?.latitude ?? 7.52],
        zoom: preset?.zoom ?? (this.compact ? 5.15 : 6.45),
        pitch: 0,
        bearing: 0,
        duration,
      });
    }
  }

  private buildDeckLayers(): any[] {
    if (!this.deckLayersModule) return [];
    const { GeoJsonLayer, ScatterplotLayer, ArcLayer, TextLayer } = this.deckLayersModule;
    const zonesSource = this.mapSystem?.['geojson_sources']?.zones;
    const markersSource = this.mapSystem?.['geojson_sources']?.markers;
    const contextMarkersSource = this.mapSystem?.['geojson_sources']?.context_markers;
    const contextLinesSource = this.mapSystem?.['geojson_sources']?.context_lines;
    const eventPointsSource = this.mapSystem?.['geojson_sources']?.event_points || this.mapSystem?.['event_points'];
    const maritimeAreaSource = this.mapSystem?.['geojson_sources']?.maritime_area;
    const maritimePointsSource = this.mapSystem?.['geojson_sources']?.maritime_points;
    const maritimeRoutesSource = this.mapSystem?.['geojson_sources']?.maritime_routes;
    const maritimeDensitySource = this.mapSystem?.['geojson_sources']?.maritime_density;
    const countryBoundarySource = this.mapSystem?.['country_boundary'];
    const districtBoundariesSource = this.mapSystem?.['district_boundaries'];
    const adminBoundariesSource = this.mapSystem?.['admin_boundaries'];
    const citiesSource = this.mapSystem?.['cities'];
    const arcs = this.mapSystem?.['visual_effects']?.arc_links || [];
    const currentZoom = Number(this.mapInstance?.getZoom?.() || 0);
    const allCityFeatures = citiesSource?.features || [];
    const zoneMarkerFeatures = markersSource?.features || [];
    const selectedOrTopZoneMarkers = zoneMarkerFeatures.filter((feature: any, index: number) => {
      const zoneId = feature.properties?.zone_id;
      return zoneId === this.selectedZoneId || (!this.selectedZoneId && index === 0);
    });
    const showCityLabels = currentZoom >= (this.compact ? 5.95 : 5.55);
    const showTerritory = this.isLayerActive('territorial-risk');
    const showPresse = this.isLayerActive('open-intelligence');
    const showRegional = this.isLayerActive('regional-context');
    const showProjects = this.isLayerActive('strategic-projects');
    const showAgenda = this.isLayerActive('agenda-windows');
    const showVisual = this.isLayerActive('visual-streams');
    const showMaritime = this.isLayerActive('maritime-traffic');
    const showActions = this.isLayerActive('preventive-actions');
    const eventFeatures = eventPointsSource?.features || [];
    const cityFeatures = allCityFeatures
      .filter((feature: any) => {
        const weight = Number(feature.properties?.weight || 0);
        const regional = feature.properties?.scope === 'regional';
        return regional ? showRegional && weight >= 72 : weight >= (this.compact ? 80 : 72);
      })
      .slice(0, this.compact ? 5 : 8);
    const zoneMarkerDisplayFeatures = (showVisual || showActions)
      ? zoneMarkerFeatures
      : selectedOrTopZoneMarkers;
    const layers: any[] = [];

    layers.push(new GeoJsonLayer({
      id: 'sentinel-country-fill',
      data: countryBoundarySource,
      pickable: false,
      filled: true,
      stroked: false,
      getFillColor: this.countryFillColor(),
      parameters: { depthTest: false },
    }));

    layers.push(new GeoJsonLayer({
        id: 'sentinel-country-outline',
        data: countryBoundarySource,
        pickable: false,
        filled: false,
        stroked: true,
        getFillColor: [0, 0, 0, 0],
        getLineColor: this.isLightBasemap() ? [14, 54, 75, 245] : [156, 222, 255, 238],
        lineWidthMinPixels: 2.4,
        parameters: { depthTest: false },
      }));

    layers.push(new GeoJsonLayer({
      id: 'sentinel-district-boundaries',
      data: districtBoundariesSource,
      pickable: false,
      filled: false,
      stroked: true,
      getFillColor: [0, 0, 0, 0],
      getLineColor: this.isLightBasemap() ? [26, 70, 91, 118] : [170, 224, 248, 98],
      lineWidthMinPixels: 0.95,
      parameters: { depthTest: false },
    }));

    if (currentZoom >= 7.15 && showTerritory) {
      layers.push(new GeoJsonLayer({
        id: 'sentinel-admin-boundaries',
        data: adminBoundariesSource,
        pickable: false,
        filled: false,
        stroked: true,
        getFillColor: [0, 0, 0, 0],
        getLineColor: this.isLightBasemap() ? [30, 76, 96, 72] : [190, 226, 241, 58],
        lineWidthMinPixels: 0.55,
        parameters: { depthTest: false },
      }));
    }

    if (showTerritory || showProjects || showActions) {
      layers.push(new GeoJsonLayer({
        id: 'sentinel-zones',
        data: zonesSource,
        pickable: true,
        filled: true,
        stroked: true,
        getFillColor: (feature: any) => this.deckColor(
          feature.properties?.tone,
          feature.properties?.id === this.selectedZoneId,
          feature.properties?.id === this.selectedZoneId ? 126 : (showTerritory ? 62 : 30),
        ),
        getLineColor: (feature: any) => this.deckLineColor(
          feature.properties?.tone,
          feature.properties?.id === this.selectedZoneId,
          feature.properties?.id === this.selectedZoneId ? 236 : 158,
        ),
        lineWidthMinPixels: 1.25,
        lineWidthMaxPixels: 3.4,
        parameters: { depthTest: false },
        onClick: (info: any) => this.emitDeckZone(info.object?.properties?.id),
      }));
    }

    if (showAgenda || showActions || showRegional) {
      layers.push(new GeoJsonLayer({
        id: 'sentinel-context-lines',
        data: contextLinesSource,
        pickable: false,
        filled: false,
        stroked: true,
        getLineColor: (feature: any) => this.contextLineColor(feature.properties?.tone),
        getLineWidth: (feature: any) => feature.properties?.tone === 'regional' ? 3600 : 3000,
        lineWidthMinPixels: 0.85,
        lineWidthMaxPixels: 2.2,
        parameters: { depthTest: false },
      }));
    }

    if (showMaritime) {
      if (maritimeAreaSource?.features?.length) {
        layers.push(new GeoJsonLayer({
          id: 'sentinel-maritime-operating-area',
          data: maritimeAreaSource,
          pickable: false,
          filled: true,
          stroked: true,
          getFillColor: this.maritimeAreaFillColor(),
          getLineColor: this.maritimeAreaLineColor(),
          lineWidthMinPixels: 0.75,
          lineWidthMaxPixels: 1.6,
          parameters: { depthTest: false },
        }));
      }
      const densityFeatures = maritimeDensitySource?.features || [];
      if (densityFeatures.length) {
        layers.push(new ScatterplotLayer({
          id: 'sentinel-maritime-density',
          data: densityFeatures,
          pickable: false,
          stroked: false,
          filled: true,
          getPosition: (feature: any) => feature.geometry.coordinates,
          radiusUnits: 'meters',
          getRadius: (feature: any) => Math.max(9000, Math.min(28000, (feature.properties?.score || 52) * 330)),
          getFillColor: (feature: any) => this.maritimeDensityColor(feature),
          parameters: { depthTest: false },
        }));
      }
      layers.push(new GeoJsonLayer({
        id: 'sentinel-maritime-routes',
        data: maritimeRoutesSource,
        pickable: false,
        filled: false,
        stroked: true,
        getLineColor: (feature: any) => this.maritimeRouteColor(feature),
        getLineWidth: (feature: any) => feature.properties?.visual_role === 'port_approach' ? 2800 : 2200,
        lineWidthMinPixels: 0.95,
        lineWidthMaxPixels: 2.35,
        parameters: { depthTest: false },
      }));
      const maritimeFeatures = maritimePointsSource?.features || [];
      layers.push(new ScatterplotLayer({
        id: 'sentinel-maritime-rings',
        data: maritimeFeatures,
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => Math.max(10, Math.min(25, (feature.properties?.score || feature.properties?.weight || 48) / 3.4)),
        getFillColor: (feature: any) => this.maritimePointColor(feature, 26),
        getLineColor: (feature: any) => this.maritimePointColor(feature, 174),
        lineWidthMinPixels: 1.25,
        parameters: { depthTest: false },
      }));
      layers.push(new ScatterplotLayer({
        id: 'sentinel-maritime-points',
        data: maritimeFeatures,
        pickable: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => feature.properties?.kind === 'port' ? 7 : 5.6,
        getFillColor: (feature: any) => this.maritimePointColor(feature, 238),
        getLineColor: (feature: any) => this.isLightBasemap() ? [8, 26, 38, 228] : [245, 252, 255, 230],
        lineWidthMinPixels: 1.45,
        parameters: { depthTest: false },
        onClick: (info: any) => this.emitMaritimeEvidence(info.object),
      }));
      const maritimeLabelFeatures = maritimeFeatures.filter((feature: any) => feature.properties?.kind === 'port').slice(0, 2);
      layers.push(new TextLayer({
        id: 'sentinel-maritime-labels',
        data: maritimeLabelFeatures,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getText: (feature: any) => feature.properties?.name || '',
        getSize: this.compact ? 9 : 11,
        getColor: this.isLightBasemap() ? [10, 25, 38, 242] : [240, 250, 255, 244],
        getPixelOffset: [0, -25],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'bottom',
        fontSettings: { sdf: true },
        outlineColor: this.isLightBasemap() ? [250, 253, 255, 235] : [4, 8, 13, 242],
        outlineWidth: 3,
        billboard: true,
        parameters: { depthTest: false },
      }));
    }

    const visibleEventPoints = eventFeatures.filter((feature: any) => {
      const layerKey = feature.properties?.layer_key;
      if (layerKey === 'open-intelligence') return showPresse;
      if (layerKey === 'strategic-projects') return showProjects;
      if (layerKey === 'agenda-windows') return showAgenda;
      if (layerKey === 'visual-streams') return showVisual;
      if (layerKey === 'preventive-actions') return showActions;
      return false;
    });
    if (visibleEventPoints.length) {
      layers.push(new ScatterplotLayer({
        id: 'sentinel-source-event-halos',
        data: visibleEventPoints,
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => Math.max(12, Math.min(24, Number(feature.properties?.score || 48) / 3.2)),
        getFillColor: (feature: any) => this.eventLayerColor(feature.properties?.layer_key, 34),
        getLineColor: (feature: any) => this.eventLayerColor(feature.properties?.layer_key, 176),
        lineWidthMinPixels: 1.25,
        parameters: { depthTest: false },
      }));
      layers.push(new ScatterplotLayer({
        id: 'sentinel-source-events',
        data: visibleEventPoints,
        pickable: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => Math.max(4, Math.min(8, Number(feature.properties?.score || 48) / 10)),
        getFillColor: (feature: any) => this.eventLayerColor(feature.properties?.layer_key, 232),
        getLineColor: [250, 254, 255, 238],
        lineWidthMinPixels: 1.4,
        parameters: { depthTest: false },
        onClick: (info: any) => this.emitEventEvidence(info.object),
      }));
    }

    if (showAgenda || showActions) {
      layers.push(new ArcLayer({
        id: 'sentinel-arcs',
        data: arcs,
        getSourcePosition: (item: any) => item.source,
        getTargetPosition: (item: any) => item.target,
        getSourceColor: [95, 235, 166, 178],
        getTargetColor: (item: any) => this.deckColor(item.tone, false, 210),
        getWidth: (item: any) => Math.max(1, Math.round((item.level || 30) / 24)),
        parameters: { depthTest: false },
      }));
    }

    if (showRegional) {
      layers.push(new ScatterplotLayer({
        id: 'sentinel-context-marker-rings',
        data: this.contextMarkerFeatures(contextMarkersSource?.features || [], false, showRegional),
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => Math.max(9, Math.min(20, (feature.properties?.weight || 40) / 5)),
        getFillColor: (feature: any) => this.contextMarkerFill(feature),
        getLineColor: (feature: any) => this.contextMarkerLine(feature),
        lineWidthMinPixels: 1.4,
        parameters: { depthTest: false },
      }));
      layers.push(new ScatterplotLayer({
        id: 'sentinel-context-markers',
        data: this.contextMarkerFeatures(contextMarkersSource?.features || [], false, showRegional),
        pickable: false,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => Math.max(3.5, Math.min(8, (feature.properties?.weight || 40) / 13)),
        getFillColor: (feature: any) => feature.properties?.scope === 'regional' ? [242, 140, 56, 224] : [118, 214, 255, 220],
        getLineColor: [245, 252, 255, 230],
        lineWidthMinPixels: 1.4,
        parameters: { depthTest: false },
      }));
    }

    if (showVisual || showTerritory || showActions) {
      layers.push(new ScatterplotLayer({
        id: 'sentinel-marker-rings',
        data: zoneMarkerDisplayFeatures,
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => Math.max(14, Math.min(28, (feature.properties?.level || 20) / 3.2)),
        getFillColor: (feature: any) => this.deckColor(feature.properties?.tone, feature.properties?.zone_id === this.selectedZoneId, 24),
        getLineColor: (feature: any) => this.deckLineColor(feature.properties?.tone, feature.properties?.zone_id === this.selectedZoneId, 170),
        lineWidthMinPixels: 1.2,
        parameters: { depthTest: false },
      }));
      layers.push(new ScatterplotLayer({
        id: 'sentinel-markers',
        data: zoneMarkerDisplayFeatures,
        pickable: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => Math.max(5, Math.min(12, (feature.properties?.level || 20) / 8)),
        getFillColor: (feature: any) => this.deckColor(feature.properties?.tone, feature.properties?.zone_id === this.selectedZoneId, 226),
        getLineColor: [250, 254, 255, 238],
        lineWidthMinPixels: 1.8,
        parameters: { depthTest: false },
        onClick: (info: any) => this.emitDeckZone(info.object?.properties?.zone_id),
      }));
    }

    if (showCityLabels) {
      layers.push(new TextLayer({
        id: 'sentinel-city-labels',
        data: cityFeatures,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getText: (feature: any) => feature.properties?.name || '',
        getSize: this.compact ? 9 : 11,
        getColor: this.isLightBasemap() ? [18, 39, 54, 232] : [245, 250, 255, 234],
        getPixelOffset: [0, -12],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'bottom',
        fontSettings: { sdf: true },
        outlineColor: this.isLightBasemap() ? [250, 254, 255, 246] : [3, 6, 10, 248],
        outlineWidth: 3,
        billboard: true,
        parameters: { depthTest: false },
      }));
    }

    if ((showTerritory || showProjects || showActions) && selectedOrTopZoneMarkers.length) {
      layers.push(new TextLayer({
        id: 'sentinel-labels',
        data: selectedOrTopZoneMarkers,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getText: (feature: any) => feature.properties?.name || '',
        getSize: this.compact ? 10 : 12,
        getColor: this.isLightBasemap() ? [8, 28, 42, 245] : [246, 251, 255, 238],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        fontSettings: { sdf: true },
        outlineColor: this.isLightBasemap() ? [255, 255, 255, 235] : [4, 8, 13, 232],
        outlineWidth: 3,
        billboard: true,
        parameters: { depthTest: false },
      }));
    }
    if (this.focusMarker) {
      const markerData = [this.focusMarker];
      layers.push(new ScatterplotLayer({
        id: 'sentinel-focus-marker-ring',
        data: markerData,
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: (item: any) => [item.longitude, item.latitude],
        radiusUnits: 'pixels',
        getRadius: 24,
        getFillColor: [255, 155, 74, 42],
        getLineColor: [255, 155, 74, 235],
        lineWidthMinPixels: 2,
        parameters: { depthTest: false },
      }));
      layers.push(new ScatterplotLayer({
        id: 'sentinel-focus-marker-core',
        data: markerData,
        pickable: false,
        getPosition: (item: any) => [item.longitude, item.latitude],
        radiusUnits: 'pixels',
        getRadius: 7,
        getFillColor: [66, 217, 155, 238],
        getLineColor: [245, 252, 255, 238],
        lineWidthMinPixels: 1.5,
        parameters: { depthTest: false },
      }));
      layers.push(new TextLayer({
        id: 'sentinel-focus-marker-label',
        data: markerData,
        getPosition: (item: any) => [item.longitude, item.latitude],
        getText: (item: any) => item.label || 'Vue active',
        getSize: 11,
        getColor: [255, 255, 255, 245],
        getPixelOffset: [0, -28],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'bottom',
        fontSettings: { sdf: true },
        outlineColor: [4, 8, 13, 240],
        outlineWidth: 3,
        billboard: true,
        parameters: { depthTest: false },
      }));
    }
    return layers;
  }

  private focusSelectedZone(): void {
    if (!this.mapInstance) return;
    const preset = this.compact
      ? this.mapSystem?.['camera_presets']?.country
      : this.mapSystem?.['camera_presets']?.[this.selectedZoneId || 'country'];
    if (!preset) return;
    this.mapInstance.easeTo({
      center: [preset.longitude, preset.latitude],
      zoom: this.compact ? 5.15 : preset.zoom,
      pitch: 0,
      bearing: 0,
      duration: Math.max(0, Math.min(Number(preset.duration_ms || 260), 320)),
    });
    this.updateDeckLayers();
  }

  private emitDeckZone(zoneId: string | undefined): void {
    if (!zoneId) return;
    const zone = this.zones.find((item) => item.id === zoneId);
    if (zone) this.selectZone(zone);
  }

  private emitMaritimeEvidence(feature: any): void {
    if (!feature?.properties) return;
    const properties = feature.properties;
    const longitude = Number(feature.geometry?.coordinates?.[0] ?? -4.0083);
    const latitude = Number(feature.geometry?.coordinates?.[1] ?? 5.2512);
    this.evidenceAction.emit({
      action: 'maritime',
      zone: {
        id: properties.id || 'maritime-evidence',
        name: properties.name || 'Maritime / douanes',
        level: Number(properties.weight || 58),
        tone: properties.tone || 'monitoring',
        sources: properties.source_refs || [],
        signals: [properties.summary].filter(Boolean),
        popup_brief: {
          title: properties.name || 'Maritime / douanes',
          score: Number(properties.weight || 58),
          severity: properties.tone || 'monitoring',
          drivers: [properties.summary, properties.domain, properties.location].filter(Boolean).slice(0, 3),
          sources: properties.source_refs || [],
          recommendation: properties.recommended_action || 'Relier le signal maritime aux douanes avant arbitrage.',
          decision_deadline: properties.decision_deadline || "aujourd'hui",
          cta: 'Preparer arbitrage',
          map_focus: {
            active_layers: ['territorial-risk', 'open-intelligence', 'visual-streams', 'maritime-traffic'],
            camera: { longitude, latitude, zoom: 9.15, duration_ms: 220 },
            focus_marker: {
              longitude,
              latitude,
              label: properties.name || 'Maritime / douanes',
              zone_id: 'zone-sud',
              tone: 'maritime',
            },
          },
        },
      },
    });
  }

  private emitEventEvidence(feature: any): void {
    if (!feature?.properties) return;
    const properties = feature.properties;
    const longitude = Number(feature.geometry?.coordinates?.[0] ?? -5.75);
    const latitude = Number(feature.geometry?.coordinates?.[1] ?? 7.95);
    this.evidenceAction.emit({
      action: String(properties.layer_key || 'source'),
      zone: {
        id: properties.zone_id || properties.id || 'map-source',
        name: properties.zone_name || properties.title || 'Source qualifiée',
        level: Number(properties.score || 52),
        tone: properties.tone || 'monitoring',
        sources: [properties.source_label].filter(Boolean),
        signals: [properties.summary].filter(Boolean),
        popup_brief: {
          title: properties.title || 'Source qualifiée',
          score: Number(properties.score || 52),
          severity: properties.tone || 'monitoring',
          drivers: [properties.summary, properties.source_kind, properties.zone_name].filter(Boolean).slice(0, 3),
          sources: [properties.source_label].filter(Boolean),
          recommendation: 'Rapprocher cette source des décisions en cours avant arbitrage.',
          decision_deadline: "aujourd'hui",
          cta: 'Ouvrir dossier source',
          map_focus: {
            active_layers: Array.from(this.activeLayerKeys),
            camera: { longitude, latitude, zoom: 8.1, duration_ms: 220 },
            focus_marker: {
              longitude,
              latitude,
              label: properties.title || 'Source qualifiée',
              zone_id: properties.zone_id,
              tone: properties.layer_key || 'source',
            },
          },
        },
      },
    });
  }

  private deckColor(tone: string, selected = false, alpha = 120): number[] {
    const base = tone === 'critical' ? [255, 68, 82] : tone === 'watch' ? [250, 176, 34] : [58, 218, 128];
    return [...base, selected ? Math.max(alpha, 174) : alpha];
  }

  private deckLineColor(tone: string, selected = false, fallbackAlpha?: number): number[] {
    const alpha = fallbackAlpha ?? (selected ? 255 : 186);
    if (tone === 'critical') return [255, 104, 116, alpha];
    if (tone === 'watch') return [255, 210, 82, alpha];
    return [104, 238, 164, alpha];
  }

  private countryFillColor(): number[] {
    if (this.selectedBasemapKey === 'command') return [2, 9, 13, 38];
    if (this.selectedBasemapKey === 'dark') return [2, 9, 13, 92];
    if (this.selectedBasemapKey === 'contours') return [255, 255, 255, 22];
    return [255, 255, 255, 18];
  }

  private contextLineColor(tone: string): number[] {
    if (tone === 'regional') return [180, 190, 202, 82];
    if (tone === 'watch') return [237, 204, 118, 88];
    return [124, 196, 222, 80];
  }

  private contextMarkerFeatures(features: any[], showPresse: boolean, showRegional: boolean): any[] {
    return features.filter((feature) => {
      const regional = feature.properties?.scope === 'regional';
      return regional ? showRegional : showPresse;
    });
  }

  private contextMarkerFill(feature: any): number[] {
    return feature.properties?.scope === 'regional' ? [242, 140, 56, 30] : [112, 207, 255, 26];
  }

  private contextMarkerLine(feature: any): number[] {
    return feature.properties?.scope === 'regional' ? [255, 176, 94, 146] : [148, 222, 255, 138];
  }

  private eventLayerColor(layerKey: string, alpha = 220): number[] {
    if (layerKey === 'strategic-projects') return [118, 223, 166, alpha];
    if (layerKey === 'agenda-windows') return [241, 206, 113, alpha];
    if (layerKey === 'visual-streams') return [185, 165, 255, alpha];
    if (layerKey === 'preventive-actions') return [242, 127, 139, alpha];
    if (layerKey === 'maritime-traffic') return [77, 189, 236, alpha];
    return [143, 210, 255, alpha];
  }

  private maritimeRouteColor(feature: any): number[] {
    const status = String(feature?.properties?.status || '');
    const role = String(feature?.properties?.visual_role || feature?.properties?.render_tone || '');
    const approach = role === 'port_approach' || role === 'maritime_approach' || status === 'watch';
    if (this.isLightBasemap()) {
      return approach ? [0, 132, 178, 214] : [12, 103, 158, 172];
    }
    return approach ? [42, 219, 246, 220] : [100, 207, 255, 180];
  }

  private maritimeAreaFillColor(): number[] {
    if (this.isLightBasemap()) return [42, 159, 211, 42];
    return [22, 137, 198, 48];
  }

  private maritimeAreaLineColor(): number[] {
    if (this.isLightBasemap()) return [8, 110, 165, 132];
    return [88, 218, 255, 130];
  }

  private maritimeDensityColor(feature: any): number[] {
    const props = feature?.properties || {};
    const status = String(props.status || props.severity || props.tone || '');
    const role = String(props.visual_role || props.render_tone || '');
    const score = Number(props.score || 0);
    const elevated = role === 'density_elevated' || status === 'elevated' || status === 'congestion' || score >= 65;
    if (this.isLightBasemap()) {
      return elevated ? [255, 174, 66, 56] : [31, 151, 204, 42];
    }
    return elevated ? [255, 184, 82, 66] : [96, 204, 255, 48];
  }

  private maritimePointColor(feature: any, alpha = 220): number[] {
    const props = feature?.properties || {};
    const kind = String(props.kind || '');
    const status = String(props.status || props.severity || '');
    if (kind === 'port') {
      return props.id === 'port-abidjan' ? [255, 160, 67, alpha] : [92, 218, 160, alpha];
    }
    if (kind === 'disruption' || status === 'congestion' || status === 'critical') return [255, 127, 103, alpha];
    if (status === 'watch' || status === 'elevated') return [255, 188, 90, Math.min(alpha, 218)];
    if (status === 'unknown') return [176, 188, 202, Math.min(alpha, 205)];
    return [88, 199, 245, alpha];
  }

  private isLightBasemap(): boolean {
    return this.selectedBasemapKey === 'administrative' || this.selectedBasemapKey === 'contours';
  }

  private deckTooltip(info: any): any {
    const properties = info?.object?.properties || info?.object;
    if (!properties) return null;
    const title = properties.title || properties.name || properties.zone_name || properties.label;
    if (!title) return null;
    const summary = properties.summary || properties.role || properties.kind || properties.source_label || '';
    const rawConfidence = Number(properties.confidence);
    const confidence = properties.confidence !== undefined
      ? `Confiance ${Math.round(rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence)}%`
      : '';
    const score = properties.score || properties.level ? `Score ${properties.score || properties.level}` : '';
    const source = properties.source_kind || properties.source || properties.layer_key || '';
    const meta = [score, confidence, source].filter(Boolean).join(' · ');
    return {
      html: `
        <div class="sentinel-map-tooltip">
          <strong>${this.escapeTooltip(title)}</strong>
          ${summary ? `<p>${this.escapeTooltip(summary)}</p>` : ''}
          ${meta ? `<small>${this.escapeTooltip(meta)}</small>` : ''}
        </div>
      `,
      style: {
        backgroundColor: 'rgba(5, 10, 15, 0.94)',
        border: '1px solid rgba(141, 214, 255, 0.42)',
        borderRadius: '10px',
        boxShadow: '0 18px 34px rgba(0,0,0,0.35)',
        color: '#f7fbff',
        fontFamily: 'Inter, system-ui, sans-serif',
        maxWidth: '320px',
        padding: '12px 14px',
        pointerEvents: 'none',
      },
    };
  }

  private escapeTooltip(value: any): string {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  private enableFallback(): void {
    this.fallback = true;
    this.cdr.markForCheck();
  }

  private defaultStyle(background = '#05080d'): Record<string, any> {
    return {
      version: 8,
      sources: {},
      layers: [{ id: 'background', type: 'background', paint: { 'background-color': background } }],
    };
  }
}
