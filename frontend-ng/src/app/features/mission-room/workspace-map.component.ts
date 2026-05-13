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
  count: number;
  confidence: number;
  visible: boolean;
};

type BasemapOption = {
  key: string;
  label: string;
  description?: string;
  style?: Record<string, any>;
};

const CIV_OUTLINE = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { name: "Côte d'Ivoire" },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-8.58, 10.65],
          [-7.52, 10.38],
          [-6.22, 10.52],
          [-4.82, 10.13],
          [-3.36, 9.62],
          [-2.78, 8.55],
          [-2.86, 7.18],
          [-3.55, 5.74],
          [-4.42, 5.12],
          [-5.22, 4.74],
          [-6.22, 4.82],
          [-7.43, 4.42],
          [-8.15, 5.05],
          [-8.35, 6.44],
          [-8.48, 8.10],
          [-8.58, 10.65],
        ]],
      },
    },
  ],
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
      [class.is-fallback]="fallback"
      [class.basemap-administrative]="selectedBasemapKey === 'administrative'"
      [class.basemap-dark]="selectedBasemapKey === 'dark'"
      [class.basemap-contours]="selectedBasemapKey === 'contours'"
    >
      <div #mapCanvas class="maplibre-canvas" [class.hidden]="fallback"></div>

      <div class="map-frame-overlay">
        <div class="map-scanline"></div>
        <div class="map-compass">N</div>
        <div class="map-control-panel" (click)="$event.stopPropagation()">
          <header class="map-control-heading">
            <strong>Lecture carte</strong>
            <small>{{ activeLayerCount }} couches</small>
          </header>
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
            <div class="layer-list">
              @for (layer of layerControls; track layer.key) {
                <button
                  type="button"
                  class="layer-toggle"
                  [class.active]="isLayerActive(layer.key)"
                  [attr.aria-pressed]="isLayerActive(layer.key)"
                  (click)="toggleLayer(layer.key)"
                >
                  <i [class]="'tone-' + layer.tone"></i>
                  <strong>{{ layer.shortLabel }}</strong>
                  <small>{{ layer.count }} · {{ layer.confidence }}%</small>
                </button>
              }
            </div>
          </section>
        </div>
        <button type="button" class="map-reset" (click)="resetCountry(); $event.stopPropagation()">Recentrer Côte d’Ivoire</button>
        <div class="map-legend">
          <span><i class="stable"></i>stable</span>
          <span><i class="monitoring"></i>surveillance</span>
          <span><i class="elevated"></i>élevé</span>
          <span><i class="critical"></i>critique</span>
        </div>
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
        min-height: 620px;
        overflow: hidden;
        border: 1px solid rgba(91, 173, 218, 0.30);
        border-radius: 10px;
        background:
          radial-gradient(circle at 50% 42%, rgba(91, 173, 218, 0.14), transparent 36%),
          linear-gradient(135deg, rgba(4, 10, 16, 0.98), rgba(9, 17, 28, 0.96));
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
          inset 0 0 42px rgba(125, 211, 252, 0.04),
          inset 0 -28px 58px rgba(0, 0, 0, 0.18);
        z-index: 3;
      }

      .workspace-map::before {
        content: '';
        position: absolute;
        inset: 0;
        pointer-events: none;
        background-image:
          linear-gradient(rgba(125, 213, 255, 0.028) 1px, transparent 1px),
          linear-gradient(90deg, rgba(125, 213, 255, 0.024) 1px, transparent 1px);
        background-size: 42px 42px;
        mask-image: linear-gradient(180deg, rgba(0,0,0,0.56), transparent 86%);
        z-index: 2;
      }

      .workspace-map.compact {
        min-height: 260px;
        border-radius: 8px;
      }

      .workspace-map.compact .map-control-panel,
      .workspace-map.compact .map-reset,
      .workspace-map.compact .map-legend,
      .workspace-map.compact .map-compass {
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
        filter: saturate(1.06) contrast(1.08) brightness(0.98);
      }

      .workspace-map.basemap-dark .maplibre-canvas {
        filter: saturate(1.18) contrast(1.24) brightness(1.10);
      }

      .workspace-map.basemap-contours .maplibre-canvas {
        filter: saturate(0.85) contrast(1.32) brightness(1.18);
      }

      .map-frame-overlay {
        position: absolute;
        inset: 0;
        z-index: 4;
        pointer-events: none;
      }

      .map-scanline {
        position: absolute;
        left: 0;
        right: 0;
        top: 24%;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(125, 211, 252, 0.26), transparent);
        opacity: 0.24;
        animation: mapSweep 7s ease-in-out infinite;
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
        left: 14px;
        top: 14px;
        width: min(286px, calc(100% - 84px));
        display: grid;
        gap: 9px;
        padding: 11px;
        border: 1px solid rgba(132, 220, 255, 0.25);
        border-radius: 14px;
        background: rgba(2, 6, 10, 0.88);
        box-shadow: 0 22px 54px rgba(0, 0, 0, 0.42), inset 0 0 0 1px rgba(255,255,255,0.03);
        backdrop-filter: blur(16px) saturate(1.2);
        pointer-events: auto;
      }

      .map-control-heading {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding-bottom: 2px;
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
        border: 1px solid rgba(125, 211, 252, 0.14);
        background: rgba(11, 20, 31, 0.74);
        color: rgba(207, 239, 255, 0.70);
        font: 750 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.10em;
        text-transform: uppercase;
        cursor: pointer;
        transition: background 150ms ease, border-color 150ms ease, color 150ms ease, opacity 150ms ease;
      }

      .basemap-switch button.active,
      .map-reset:hover {
        border-color: rgba(125, 211, 252, 0.42);
        background: rgba(10, 34, 49, 0.82);
        color: rgba(232, 247, 255, 0.92);
        box-shadow: 0 0 18px rgba(91, 173, 218, 0.12);
      }

      .basemap-switch button:hover,
      .layer-toggle:hover {
        border-color: rgba(125, 211, 252, 0.56);
        color: rgba(245, 251, 255, 0.95);
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
        grid-template-areas: 'tone label' 'tone meta';
        column-gap: 8px;
        row-gap: 2px;
        align-items: center;
        padding: 9px 10px;
        border-radius: 10px;
        border: 1px solid rgba(125, 211, 252, 0.16);
        background: rgba(14, 24, 36, 0.82);
        color: rgba(232, 241, 255, 0.72);
        text-align: left;
        cursor: pointer;
      }

      .layer-toggle.active {
        border-color: rgba(132, 220, 255, 0.50);
        background: linear-gradient(135deg, rgba(18, 39, 58, 0.98), rgba(12, 23, 36, 0.94));
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04), 0 0 18px rgba(77, 195, 255, 0.10);
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
      .layer-toggle i.tone-cyan { background: #67e8f9; box-shadow: 0 0 12px rgba(103, 232, 249, 0.28); }
      .layer-toggle i.tone-green { background: #76dfa6; box-shadow: 0 0 12px rgba(118, 223, 166, 0.28); }
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

      .map-reset {
        position: absolute;
        top: 14px;
        right: 58px;
        z-index: 5;
        pointer-events: auto;
      }

      .map-legend {
        position: absolute;
        left: 50%;
        right: auto;
        bottom: 16px;
        top: auto;
        transform: translateX(-50%);
        z-index: 5;
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 11px;
        border: 1px solid rgba(125, 211, 252, 0.13);
        border-radius: 999px;
        background: rgba(2, 6, 10, 0.82);
        backdrop-filter: blur(12px);
      }

      .workspace-map.basemap-administrative .map-legend,
      .workspace-map.basemap-administrative .map-hud,
      .workspace-map.basemap-administrative .map-attribution {
        background: rgba(8, 18, 28, 0.86);
      }

      .map-legend span {
        display: flex;
        align-items: center;
        gap: 7px;
        color: rgba(213, 229, 242, 0.72);
        font-size: 11px;
        line-height: 1;
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
        border: 1px solid rgba(91, 173, 218, 0.26);
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
  @Output() zoneSelected = new EventEmitter<any>();
  @ViewChild('mapCanvas') private readonly mapCanvas?: ElementRef<HTMLDivElement>;

  fallback = false;
  selectedBasemapKey = 'administrative';

  private readonly cdr = inject(ChangeDetectorRef);
  private readonly activeLayerKeys = new Set<string>();
  private layerStateInitialized = false;
  private mapInstance: any;
  private deckOverlay: any;
  private deckLayersModule: any;

  get layerControls(): MapLayerControl[] {
    const catalog = this.mapSystem?.['layer_catalog'];
    if (Array.isArray(catalog) && catalog.length) {
      return catalog.map((layer: any) => ({
        key: String(layer.key || ''),
        label: String(layer.label || layer.key || ''),
        shortLabel: String(layer.short_label || layer.label || layer.key || ''),
        tone: String(layer.tone || 'cyan'),
        count: Number(layer.count || 0),
        confidence: Math.round(Number(layer.confidence || 0)),
        visible: layer.visible !== false,
      })).filter((layer) => layer.key);
    }
    return [
      { key: 'territorial-risk', label: 'Zones de vigilance', shortLabel: 'Zones', tone: 'cyan', count: this.zones.length, confidence: 78, visible: true },
      { key: 'open-intelligence', label: 'Signaux presse', shortLabel: 'Presse', tone: 'blue', count: 3, confidence: 72, visible: true },
      { key: 'strategic-projects', label: 'Projets sensibles', shortLabel: 'Projets', tone: 'green', count: 3, confidence: 69, visible: true },
      { key: 'agenda-windows', label: 'Agenda / fenêtres d’action', shortLabel: 'Agenda', tone: 'amber', count: 5, confidence: 81, visible: true },
      { key: 'visual-streams', label: 'Observations visuelles', shortLabel: 'Visuel', tone: 'violet', count: 1, confidence: 62, visible: true },
      { key: 'preventive-actions', label: 'Actions recommandées', shortLabel: 'Actions', tone: 'red', count: 4, confidence: 74, visible: true },
    ];
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
    if (changes['mapSystem']) {
      this.layerStateInitialized = false;
      this.syncStateFromMapPayload();
      this.applyCurrentBasemap();
    }
    if (changes['zones'] || changes['mapSystem']) {
      if (!this.layerStateInitialized) this.syncStateFromMapPayload();
      this.updateDeckLayers();
    }
    if (changes['mapState'] && this.mapState) {
      this.applyExternalMapState(this.mapState);
    }
    if (changes['selectedZoneId']) {
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
    this.zoneSelected.emit(zone);
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

  switchBasemap(key: string): void {
    if (this.selectedBasemapKey === key) return;
    this.selectedBasemapKey = key;
    this.applyCurrentBasemap();
    this.cdr.markForCheck();
  }

  resetCountry(): void {
    this.fitCountry(800);
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
        interactive: !this.compact,
        attributionControl: false,
      });
      this.deckOverlay = new overlayCtor({
        interleaved: false,
        layers: this.buildDeckLayers(),
      });
      this.mapInstance.on('load', () => {
        this.mapInstance.addControl(this.deckOverlay);
        this.fitCountry(0);
        setTimeout(() => {
          this.mapInstance?.resize?.();
          this.fitCountry(350);
        }, 80);
      });
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
    const activeLayers = Array.isArray(defaultState.active_layers)
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

  private currentBasemapStyle(): Record<string, any> | null {
    return this.basemapOptions.find((option) => option.key === this.selectedBasemapKey)?.style || null;
  }

  private applyCurrentBasemap(): void {
    if (!this.mapInstance) return;
    const style = this.currentBasemapStyle();
    if (!style) return;
    try {
      this.mapInstance.setStyle(style);
      this.mapInstance.once?.('styledata', () => {
        this.updateDeckLayers();
        this.focusSelectedZone();
      });
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
    const camera = state['camera'] as Record<string, any> | undefined;
    if (this.mapInstance && camera?.['longitude'] && camera?.['latitude']) {
      this.mapInstance.easeTo({
        center: [camera['longitude'], camera['latitude']],
        zoom: camera['zoom'] ?? (this.compact ? 5.15 : 6.0),
        pitch: 0,
        bearing: 0,
        duration: camera['duration_ms'] || 700,
      });
    }
    this.updateDeckLayers();
    this.cdr.markForCheck();
  }

  private updateDeckLayers(): void {
    if (!this.deckOverlay || !this.deckLayersModule) return;
    this.deckOverlay.setProps({ layers: this.buildDeckLayers() });
  }

  private fitCountry(duration = 800): void {
    if (!this.mapInstance) return;
    const bounds = this.mapSystem?.['renderer_config']?.bounds || [[-8.65, 4.2], [-2.45, 10.75]];
    try {
      this.mapInstance.fitBounds(bounds, {
        padding: this.compact
          ? { top: 20, right: 20, bottom: 20, left: 20 }
          : { top: 76, right: 78, bottom: 58, left: 326 },
        maxZoom: this.compact ? 5.55 : 6.85,
        pitch: 0,
        bearing: 0,
        duration,
      });
    } catch {
      const preset = this.mapSystem?.['default_map_state']?.camera || this.mapSystem?.['camera_presets']?.country;
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
    const adminBoundariesSource = this.mapSystem?.['admin_boundaries'];
    const citiesSource = this.mapSystem?.['cities'];
    const arcs = this.mapSystem?.['visual_effects']?.arc_links || [];
    const cityFeatures = (citiesSource?.features || []).filter((feature: any) => Number(feature.properties?.weight || 0) >= 70);
    const zoneMarkerFeatures = markersSource?.features || [];
    const selectedOrTopZoneMarkers = zoneMarkerFeatures.filter((feature: any, index: number) => {
      const zoneId = feature.properties?.zone_id;
      return zoneId === this.selectedZoneId || index === 0 || Number(feature.properties?.level || 0) >= 70;
    });
    const showTerritory = this.isLayerActive('territorial-risk');
    const showPresse = this.isLayerActive('open-intelligence');
    const showProjects = this.isLayerActive('strategic-projects');
    const showAgenda = this.isLayerActive('agenda-windows');
    const showVisual = this.isLayerActive('visual-streams');
    const showActions = this.isLayerActive('preventive-actions');
    const layers: any[] = [];

    layers.push(new GeoJsonLayer({
        id: 'sentinel-country-outline',
        data: CIV_OUTLINE,
        pickable: false,
        filled: true,
        stroked: true,
        getFillColor: [2, 11, 18, 96],
        getLineColor: [109, 214, 255, 232],
        lineWidthMinPixels: 3,
        parameters: { depthTest: false },
      }));

    layers.push(new GeoJsonLayer({
      id: 'sentinel-admin-boundaries',
      data: adminBoundariesSource,
      pickable: false,
      filled: true,
      stroked: true,
      getFillColor: [4, 16, 25, showTerritory ? 34 : 18],
      getLineColor: [116, 201, 240, showTerritory ? 148 : 82],
      lineWidthMinPixels: showTerritory ? 1.5 : 0.8,
      parameters: { depthTest: false },
    }));

    if (showAgenda || showActions) {
      layers.push(new GeoJsonLayer({
        id: 'sentinel-context-lines',
        data: contextLinesSource,
        pickable: false,
        filled: false,
        stroked: true,
        getLineColor: (feature: any) => feature.properties?.tone === 'watch' ? [255, 202, 68, 148] : [100, 220, 255, 132],
        getLineWidth: 12500,
        lineWidthMinPixels: 2.2,
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
        getFillColor: (feature: any) => this.deckColor(feature.properties?.tone, feature.properties?.id === this.selectedZoneId, showTerritory ? 156 : 94),
        getLineColor: (feature: any) => this.deckLineColor(feature.properties?.tone, feature.properties?.id === this.selectedZoneId),
        lineWidthMinPixels: 3.2,
        lineWidthMaxPixels: 6,
        parameters: { depthTest: false },
        onClick: (info: any) => this.emitDeckZone(info.object?.properties?.id),
      }));
    }

    if (showAgenda || showProjects || showActions) {
      layers.push(new ArcLayer({
        id: 'sentinel-arcs',
        data: arcs,
        getSourcePosition: (item: any) => item.source,
        getTargetPosition: (item: any) => item.target,
        getSourceColor: [95, 235, 166, 178],
        getTargetColor: (item: any) => this.deckColor(item.tone, false, 210),
        getWidth: (item: any) => Math.max(1.2, Math.round((item.level || 30) / 18)),
        parameters: { depthTest: false },
      }));
    }

    if (showPresse) {
      layers.push(new ScatterplotLayer({
        id: 'sentinel-context-marker-rings',
        data: contextMarkersSource?.features || [],
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getRadius: (feature: any) => Math.max(16000, (feature.properties?.weight || 40) * 320),
        getFillColor: [77, 195, 255, 30],
        getLineColor: [132, 220, 255, 150],
        lineWidthMinPixels: 1.4,
        parameters: { depthTest: false },
      }));
      layers.push(new ScatterplotLayer({
        id: 'sentinel-context-markers',
        data: contextMarkersSource?.features || [],
        pickable: false,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getRadius: (feature: any) => Math.max(6500, (feature.properties?.weight || 40) * 150),
        getFillColor: [102, 210, 255, 218],
        getLineColor: [245, 252, 255, 230],
        lineWidthMinPixels: 1.4,
        parameters: { depthTest: false },
      }));
    }

    if (showVisual || showTerritory || showActions) {
      layers.push(new ScatterplotLayer({
        id: 'sentinel-marker-rings',
        data: markersSource?.features || [],
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getRadius: (feature: any) => Math.max(22000, (feature.properties?.level || 20) * 620),
        getFillColor: (feature: any) => this.deckColor(feature.properties?.tone, feature.properties?.zone_id === this.selectedZoneId, 36),
        getLineColor: (feature: any) => this.deckLineColor(feature.properties?.tone, feature.properties?.zone_id === this.selectedZoneId, 170),
        lineWidthMinPixels: 1.2,
        parameters: { depthTest: false },
      }));
      layers.push(new ScatterplotLayer({
        id: 'sentinel-markers',
        data: markersSource?.features || [],
        pickable: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getRadius: (feature: any) => Math.max(10000, (feature.properties?.level || 20) * 340),
        getFillColor: (feature: any) => this.deckColor(feature.properties?.tone, feature.properties?.zone_id === this.selectedZoneId, 226),
        getLineColor: [250, 254, 255, 238],
        lineWidthMinPixels: 1.8,
        parameters: { depthTest: false },
        onClick: (info: any) => this.emitDeckZone(info.object?.properties?.zone_id),
      }));
    }

    layers.push(new TextLayer({
      id: 'sentinel-city-labels',
      data: cityFeatures,
      getPosition: (feature: any) => feature.geometry.coordinates,
      getText: (feature: any) => feature.properties?.name || '',
      getSize: this.compact ? 9 : 10,
      getColor: this.selectedBasemapKey === 'administrative' ? [18, 39, 54, 230] : [226, 239, 250, 218],
      getPixelOffset: [0, -12],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'bottom',
      fontSettings: { sdf: true },
      outlineColor: this.selectedBasemapKey === 'administrative' ? [250, 254, 255, 240] : [2, 6, 10, 238],
      outlineWidth: 3,
      billboard: true,
      parameters: { depthTest: false },
    }));

    if (showPresse) {
      layers.push(new TextLayer({
        id: 'sentinel-context-labels',
        data: contextMarkersSource?.features || [],
        getPosition: (feature: any) => feature.geometry.coordinates,
        getText: (feature: any) => feature.properties?.name || '',
        getSize: this.compact ? 10 : 12,
        getColor: [223, 240, 252, 215],
        getPixelOffset: [0, -16],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'bottom',
        fontSettings: { sdf: true },
        outlineColor: [4, 8, 13, 210],
        outlineWidth: 2,
        billboard: true,
        parameters: { depthTest: false },
      }));
    }

    if (showTerritory || showProjects || showActions) {
      layers.push(new TextLayer({
        id: 'sentinel-labels',
        data: selectedOrTopZoneMarkers,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getText: (feature: any) => feature.properties?.name || '',
        getSize: this.compact ? 11 : 14,
        getColor: this.selectedBasemapKey === 'administrative' ? [8, 28, 42, 245] : [246, 251, 255, 235],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        fontSettings: { sdf: true },
        outlineColor: this.selectedBasemapKey === 'administrative' ? [255, 255, 255, 235] : [4, 8, 13, 225],
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
      duration: preset.duration_ms || 650,
    });
    this.updateDeckLayers();
  }

  private emitDeckZone(zoneId: string | undefined): void {
    if (!zoneId) return;
    const zone = this.zones.find((item) => item.id === zoneId);
    if (zone) this.zoneSelected.emit(zone);
  }

  private deckColor(tone: string, selected = false, alpha = 120): number[] {
    const base = tone === 'critical' ? [255, 72, 86] : tone === 'watch' ? [255, 178, 47] : [72, 226, 132];
    return [...base, selected ? Math.max(alpha, 226) : alpha];
  }

  private deckLineColor(tone: string, selected = false, fallbackAlpha?: number): number[] {
    const alpha = fallbackAlpha ?? (selected ? 255 : 218);
    if (tone === 'critical') return [255, 132, 142, alpha];
    if (tone === 'watch') return [255, 220, 102, alpha];
    return [130, 255, 184, alpha];
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
