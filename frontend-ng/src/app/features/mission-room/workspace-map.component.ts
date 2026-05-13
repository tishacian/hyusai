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

@Component({
  selector: 'app-workspace-map',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="workspace-map" [class.compact]="compact" [class.is-fallback]="fallback">
      <div #mapCanvas class="maplibre-canvas" [class.hidden]="fallback"></div>

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
        <span>{{ mapSystem?.['renderer_config']?.['renderer'] || 'maplibre' }}</span>
        <strong>{{ selectedZoneLabel }}</strong>
      </div>
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
        min-height: 540px;
        overflow: hidden;
        border: 1px solid rgba(91, 173, 218, 0.24);
        border-radius: 10px;
        background:
          radial-gradient(circle at 52% 42%, rgba(91, 173, 218, 0.18), transparent 28%),
          linear-gradient(135deg, rgba(4, 8, 13, 0.96), rgba(12, 17, 26, 0.94));
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03), 0 24px 70px rgba(0,0,0,0.22);
      }

      .workspace-map::before {
        content: '';
        position: absolute;
        inset: 0;
        pointer-events: none;
        background-image:
          linear-gradient(rgba(125, 213, 255, 0.055) 1px, transparent 1px),
          linear-gradient(90deg, rgba(125, 213, 255, 0.045) 1px, transparent 1px);
        background-size: 42px 42px;
        mask-image: linear-gradient(180deg, rgba(0,0,0,0.75), transparent 82%);
        z-index: 2;
      }

      .workspace-map.compact {
        min-height: 260px;
        border-radius: 8px;
      }

      .maplibre-canvas,
      .fallback-map {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
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
        border: 1px solid rgba(91, 173, 218, 0.26);
        border-radius: 999px;
        background: rgba(7, 12, 19, 0.78);
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

      @keyframes mapPulse {
        0%, 100% { transform: scale(0.96); opacity: 0.18; }
        50% { transform: scale(1.08); opacity: 0.34; }
      }
    `,
  ],
})
export class WorkspaceMapComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input() zones: MapZone[] = [];
  @Input() map: Record<string, any> | null = null;
  @Input() mapSystem: Record<string, any> | null = null;
  @Input() selectedZoneId: string | null = null;
  @Input() compact = false;
  @Output() zoneSelected = new EventEmitter<any>();
  @ViewChild('mapCanvas') private readonly mapCanvas?: ElementRef<HTMLDivElement>;

  fallback = false;

  private readonly cdr = inject(ChangeDetectorRef);
  private mapInstance: any;
  private deckOverlay: any;
  private deckLayersModule: any;

  get selectedZoneLabel(): string {
    return this.zones.find((zone) => zone.id === this.selectedZoneId)?.name || 'Cote d’Ivoire';
  }

  ngAfterViewInit(): void {
    void this.bootstrapRenderer();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['zones'] || changes['mapSystem']) {
      this.updateDeckLayers();
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

  private async bootstrapRenderer(): Promise<void> {
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
        style: this.mapSystem?.['renderer_config']?.style || this.defaultStyle(),
        center: [view.longitude ?? -5.45, view.latitude ?? 7.58],
        zoom: view.zoom ?? (this.compact ? 4.9 : 5.7),
        pitch: this.compact ? 18 : (view.pitch ?? 38),
        bearing: view.bearing ?? -7,
        interactive: !this.compact,
        attributionControl: false,
      });
      this.deckOverlay = new overlayCtor({
        interleaved: false,
        layers: this.buildDeckLayers(),
      });
      this.mapInstance.on('load', () => {
        this.mapInstance.addControl(this.deckOverlay);
        this.focusSelectedZone();
      });
      this.mapInstance.on('error', () => this.enableFallback());
    } catch {
      this.enableFallback();
    }
  }

  private updateDeckLayers(): void {
    if (!this.deckOverlay || !this.deckLayersModule) return;
    this.deckOverlay.setProps({ layers: this.buildDeckLayers() });
  }

  private buildDeckLayers(): any[] {
    if (!this.deckLayersModule) return [];
    const { GeoJsonLayer, ScatterplotLayer, ArcLayer, TextLayer } = this.deckLayersModule;
    const zonesSource = this.mapSystem?.['geojson_sources']?.zones;
    const markersSource = this.mapSystem?.['geojson_sources']?.markers;
    const arcs = this.mapSystem?.['visual_effects']?.arc_links || [];
    return [
      new GeoJsonLayer({
        id: 'sentinel-zones',
        data: zonesSource,
        pickable: true,
        filled: true,
        stroked: true,
        getFillColor: (feature: any) => this.deckColor(feature.properties?.tone, feature.properties?.id === this.selectedZoneId),
        getLineColor: [170, 220, 255, 130],
        lineWidthMinPixels: 1,
        onClick: (info: any) => this.emitDeckZone(info.object?.properties?.id),
      }),
      new ArcLayer({
        id: 'sentinel-arcs',
        data: arcs,
        getSourcePosition: (item: any) => item.source,
        getTargetPosition: (item: any) => item.target,
        getSourceColor: [111, 216, 155, 130],
        getTargetColor: (item: any) => this.deckColor(item.tone, false, 170),
        getWidth: (item: any) => Math.max(1, Math.round((item.level || 30) / 22)),
      }),
      new ScatterplotLayer({
        id: 'sentinel-markers',
        data: markersSource?.features || [],
        pickable: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getRadius: (feature: any) => Math.max(22000, (feature.properties?.level || 20) * 900),
        getFillColor: (feature: any) => this.deckColor(feature.properties?.tone, feature.properties?.zone_id === this.selectedZoneId, 115),
        getLineColor: [210, 240, 255, 150],
        lineWidthMinPixels: 1,
        onClick: (info: any) => this.emitDeckZone(info.object?.properties?.zone_id),
      }),
      new TextLayer({
        id: 'sentinel-labels',
        data: markersSource?.features || [],
        getPosition: (feature: any) => feature.geometry.coordinates,
        getText: (feature: any) => feature.properties?.name || '',
        getSize: this.compact ? 12 : 15,
        getColor: [232, 241, 255, 220],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        billboard: true,
      }),
    ];
  }

  private focusSelectedZone(): void {
    if (!this.mapInstance || !this.selectedZoneId) return;
    const preset = this.mapSystem?.['camera_presets']?.[this.selectedZoneId];
    if (!preset) return;
    this.mapInstance.easeTo({
      center: [preset.longitude, preset.latitude],
      zoom: this.compact ? Math.min(5.6, preset.zoom ?? 5.6) : preset.zoom,
      pitch: this.compact ? 18 : preset.pitch,
      bearing: preset.bearing,
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
    const base = tone === 'critical' ? [239, 111, 125] : tone === 'watch' ? [237, 199, 101] : [105, 216, 155];
    return [...base, selected ? 210 : alpha];
  }

  private enableFallback(): void {
    this.fallback = true;
    this.cdr.markForCheck();
  }

  private defaultStyle(): Record<string, any> {
    return {
      version: 8,
      sources: {},
      layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#05080d' } }],
    };
  }
}
