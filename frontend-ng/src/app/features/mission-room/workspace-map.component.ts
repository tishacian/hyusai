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
import type { VesselPosition } from '@app/core/maritime-tracking.service';

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

type OctocityCityMarker = {
  name: string;
  x: number;
  y: number;
  labelX?: number;
  labelY?: number;
  capital?: boolean;
};

type OctocityRiverPath = {
  name: string;
  d: string;
};

/** Color table used by both the deck.gl vessel layer and the legend. */
const VESSEL_TYPE_COLORS: Record<string, [number, number, number]> = {
  cargo: [34, 197, 94],
  container: [34, 197, 94],
  tanker: [249, 115, 22],
  roro: [113, 181, 242],
  passenger: [157, 124, 240],
  fishing: [148, 164, 182],
  tug: [148, 164, 182],
  other: [148, 164, 182],
};
/** Violet highlight reserved for vessels linked to a tracked project / cargo. */
const VESSEL_HIGHLIGHT_RGB: [number, number, number] = [180, 136, 255];
const ZONE_STROKE_RGB: [number, number, number] = [62, 230, 138];
const ZONE_STROKE_ALPHA = 89;
const VESSEL_ICON_MAPPING = {
  triangle: { x: 0, y: 0, width: 64, height: 64, mask: true, anchorY: 64 },
  diamond: { x: 64, y: 0, width: 64, height: 64, mask: true, anchorY: 32 },
} as const;
const ATLANTIC_TRADER_MMSI = '627012345';
const OCTOCITY_FRANCE_LAND_PATH = [
  'M282,58',
  'L346,75',
  'L392,59',
  'L452,100',
  'L478,156',
  'L542,190',
  'L516,260',
  'L560,316',
  'L518,380',
  'L484,438',
  'L418,466',
  'L354,448',
  'L306,478',
  'L248,432',
  'L196,410',
  'L178,346',
  'L116,288',
  'L150,236',
  'L118,170',
  'L184,122',
  'L226,76',
  'Z',
].join(' ');
const OCTOCITY_NEIGHBOUR_LAND_PATHS = [
  'M392,38 L680,38 L680,520 L534,520 L560,460 L604,394 L622,322 L590,238 L546,187 L476,156 L452,100 Z',
  'M40,424 L188,414 L306,478 L354,448 L470,486 L584,520 L40,520 Z',
  'M54,34 L178,42 L208,90 L166,128 L82,112 L42,76 Z',
];
const OCTOCITY_CORSICA_PATH = 'M532,454 C548,466 548,494 532,506 C514,494 510,466 532,454 Z';
const OCTOCITY_RIVERS: OctocityRiverPath[] = [
  { name: 'Seine', d: 'M276,118 C300,136 318,146 343,166 C364,184 382,197 405,210' },
  { name: 'Loire', d: 'M210,268 C260,260 308,276 350,302 C388,326 416,336 458,342' },
  { name: 'Garonne', d: 'M260,360 C286,388 314,408 340,424' },
  { name: 'Rhone', d: 'M442,310 C452,348 448,390 456,450' },
  { name: 'Rhine', d: 'M536,170 C526,212 528,252 520,292' },
];
const OCTOCITY_CITY_MARKERS: OctocityCityMarker[] = [
  { name: 'Paris', x: 343, y: 166, labelX: 353, labelY: 160, capital: true },
  { name: 'Lille', x: 382, y: 88, labelX: 392, labelY: 84 },
  { name: 'Rouen', x: 304, y: 142, labelX: 257, labelY: 136 },
  { name: 'Rennes', x: 214, y: 210, labelX: 164, labelY: 205 },
  { name: 'Nantes', x: 226, y: 272, labelX: 174, labelY: 274 },
  { name: 'Bordeaux', x: 262, y: 362, labelX: 206, labelY: 367 },
  { name: 'Toulouse', x: 330, y: 424, labelX: 270, labelY: 430 },
  { name: 'Montpellier', x: 408, y: 428, labelX: 418, labelY: 424 },
  { name: 'Marseille', x: 456, y: 450, labelX: 466, labelY: 457 },
  { name: 'Nice', x: 526, y: 428, labelX: 536, labelY: 424 },
  { name: 'Lyon', x: 442, y: 314, labelX: 452, labelY: 310 },
  { name: 'Dijon', x: 430, y: 240, labelX: 440, labelY: 236 },
  { name: 'Strasbourg', x: 532, y: 190, labelX: 542, labelY: 186 },
  { name: 'Brest', x: 140, y: 206, labelX: 96, labelY: 206 },
];
const EMPTY_FEATURE_COLLECTION = { type: 'FeatureCollection', features: [] } as const;
const OCTOCITY_CARTO_VOYAGER_STYLE = {
  version: 8,
  sources: {
    'carto-voyager-france': {
      type: 'raster',
      tiles: [
        'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
        'https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
        'https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
        'https://d.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
      ],
      tileSize: 256,
      attribution: 'OpenStreetMap contributors / CARTO',
    },
  },
  layers: [
    { id: 'octocity-background', type: 'background', paint: { 'background-color': '#dce6ea' } },
    {
      id: 'carto-voyager-france-base',
      type: 'raster',
      source: 'carto-voyager-france',
      paint: {
        'raster-opacity': 0.98,
        'raster-saturation': -0.04,
        'raster-contrast': 0.04,
      },
    },
  ],
};
const OCTOCITY_CARTO_DARK_STYLE = {
  version: 8,
  sources: {
    'carto-dark-france': {
      type: 'raster',
      tiles: [
        'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        'https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
      ],
      tileSize: 256,
      attribution: 'OpenStreetMap contributors / CARTO',
    },
  },
  layers: [
    { id: 'octocity-dark-background', type: 'background', paint: { 'background-color': '#060b10' } },
    {
      id: 'carto-dark-france-base',
      type: 'raster',
      source: 'carto-dark-france',
      paint: {
        'raster-opacity': 0.95,
        'raster-brightness-min': 0,
        'raster-brightness-max': 0.9,
        'raster-saturation': -0.12,
        'raster-contrast': 0.15,
      },
    },
  ],
};
const OCTOCITY_CONTEXT_CITIES = [
  { id: 'paris', name: 'Paris', coordinates: [2.3522, 48.8566], weight: 96, kind: 'coordination' },
  { id: 'lille', name: 'Lille', coordinates: [3.0573, 50.6292], weight: 78, kind: 'news_flow' },
  { id: 'rennes', name: 'Rennes', coordinates: [-1.6778, 48.1173], weight: 73, kind: 'field_ops' },
  { id: 'nantes', name: 'Nantes', coordinates: [-1.5536, 47.2184], weight: 82, kind: 'logistics' },
  { id: 'bordeaux', name: 'Bordeaux', coordinates: [-0.5792, 44.8378], weight: 77, kind: 'field_ops' },
  { id: 'toulouse', name: 'Toulouse', coordinates: [1.4442, 43.6047], weight: 74, kind: 'industry' },
  { id: 'lyon', name: 'Lyon', coordinates: [4.8357, 45.764], weight: 86, kind: 'operations' },
  { id: 'marseille', name: 'Marseille', coordinates: [5.3698, 43.2965], weight: 88, kind: 'port' },
  { id: 'nice', name: 'Nice', coordinates: [7.262, 43.7102], weight: 70, kind: 'field_ops' },
  { id: 'strasbourg', name: 'Strasbourg', coordinates: [7.7521, 48.5734], weight: 79, kind: 'coordination' },
];
const OCTOCITY_CITY_FEATURES = OCTOCITY_CONTEXT_CITIES.map((city) => ({
  type: 'Feature',
  id: `city-${city.id}`,
  geometry: { type: 'Point', coordinates: city.coordinates },
  properties: {
    name: city.name,
    scope: 'regional',
    weight: city.weight,
    kind: city.kind,
  },
}));
const OCTOCITY_MAP_SYSTEM = {
  renderer_config: {
    renderer: 'maplibre',
    default_basemap: 'administrative',
    style: OCTOCITY_CARTO_VOYAGER_STYLE,
    initial_view_state: {
      longitude: 2.25,
      latitude: 46.75,
      zoom: 6.32,
      pitch: 0,
      bearing: 0,
    },
    bounds: [[-5.3, 42.35], [8.1, 50.8]],
    attribution: 'Fond OSM/CARTO · France operating room · synthetic Agentium signals',
  },
  basemap_options: [
    { key: 'administrative', label: 'Real map', style: OCTOCITY_CARTO_VOYAGER_STYLE },
    { key: 'command', label: 'Command', style: OCTOCITY_CARTO_DARK_STYLE },
    { key: 'dark', label: 'Dark', style: OCTOCITY_CARTO_DARK_STYLE },
  ],
  default_map_state: {
    basemap: 'administrative',
    active_layers: ['open-intelligence', 'regional-context', 'preventive-actions', 'agenda-windows'],
    selected_zone: 'zone-nord',
    camera: { longitude: 2.25, latitude: 46.75, zoom: 6.32, pitch: 0, bearing: 0, duration_ms: 900 },
  },
  layer_registry: [
    { key: 'territorial-risk', label: 'Decision heatmap', short_label: 'Heatmap', tone: 'cyan', count: 5, confidence: 82, visible: true },
    { key: 'open-intelligence', label: 'News signals', short_label: 'News', tone: 'blue', count: 5, confidence: 76, visible: true },
    { key: 'regional-context', label: 'Coordination points', short_label: 'Coordination', tone: 'orange', count: 10, confidence: 74, visible: true },
    { key: 'agenda-windows', label: 'Executive windows', short_label: 'Agenda', tone: 'amber', count: 4, confidence: 84, visible: true },
    { key: 'preventive-actions', label: 'Recommended actions', short_label: 'Actions', tone: 'red', count: 4, confidence: 78, visible: true },
  ],
  country_boundary: EMPTY_FEATURE_COLLECTION,
  district_boundaries: EMPTY_FEATURE_COLLECTION,
  admin_boundaries: EMPTY_FEATURE_COLLECTION,
  cities: {
    type: 'FeatureCollection',
    features: OCTOCITY_CITY_FEATURES,
  },
  geojson_sources: {
    zones: EMPTY_FEATURE_COLLECTION,
    markers: {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', id: 'zone-nord-marker', geometry: { type: 'Point', coordinates: [2.35, 48.86] }, properties: { zone_id: 'zone-nord', name: 'Northern Arc', level: 72, tone: 'watch' } },
        { type: 'Feature', id: 'zone-ouest-marker', geometry: { type: 'Point', coordinates: [-1.55, 47.22] }, properties: { zone_id: 'zone-ouest', name: 'Atlantic Corridor', level: 61, tone: 'stable' } },
        { type: 'Feature', id: 'zone-centre-marker', geometry: { type: 'Point', coordinates: [3.08, 45.78] }, properties: { zone_id: 'zone-centre', name: 'Central Hub', level: 68, tone: 'watch' } },
        { type: 'Feature', id: 'zone-est-marker', geometry: { type: 'Point', coordinates: [7.75, 48.58] }, properties: { zone_id: 'zone-est', name: 'Rhine Interface', level: 58, tone: 'stable' } },
        { type: 'Feature', id: 'zone-sud-marker', geometry: { type: 'Point', coordinates: [5.37, 43.3] }, properties: { zone_id: 'zone-sud', name: 'Mediterranean Gate', level: 76, tone: 'critical' } },
      ],
    },
    context_markers: {
      type: 'FeatureCollection',
      features: [
        ...OCTOCITY_CITY_FEATURES,
      ],
    },
    context_lines: {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', id: 'line-paris-lyon', geometry: { type: 'LineString', coordinates: [[2.3522, 48.8566], [4.8357, 45.764]] }, properties: { name: 'Paris-Lyon decision axis', tone: 'regional' } },
        { type: 'Feature', id: 'line-lyon-marseille', geometry: { type: 'LineString', coordinates: [[4.8357, 45.764], [5.3698, 43.2965]] }, properties: { name: 'Rhone corridor', tone: 'watch' } },
        { type: 'Feature', id: 'line-paris-lille', geometry: { type: 'LineString', coordinates: [[2.3522, 48.8566], [3.0573, 50.6292]] }, properties: { name: 'Northern coordination link', tone: 'regional' } },
        { type: 'Feature', id: 'line-paris-strasbourg', geometry: { type: 'LineString', coordinates: [[2.3522, 48.8566], [7.7521, 48.5734]] }, properties: { name: 'Eastern interface link', tone: 'regional' } },
        { type: 'Feature', id: 'line-atlantic-paris', geometry: { type: 'LineString', coordinates: [[-1.5536, 47.2184], [2.3522, 48.8566]] }, properties: { name: 'Atlantic logistics link', tone: 'watch' } },
      ],
    },
    event_points: {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', id: 'news-paris-001', geometry: { type: 'Point', coordinates: [2.3522, 48.8566] }, properties: { name: 'Executive brief cluster', layer_key: 'open-intelligence', score: 72, source_kind: 'news_flow' } },
        { type: 'Feature', id: 'action-lyon-001', geometry: { type: 'Point', coordinates: [4.8357, 45.764] }, properties: { name: 'Human review queue', layer_key: 'preventive-actions', score: 68, source_kind: 'decision_queue' } },
        { type: 'Feature', id: 'news-marseille-001', geometry: { type: 'Point', coordinates: [5.3698, 43.2965] }, properties: { name: 'Port capacity watch', layer_key: 'open-intelligence', score: 76, source_kind: 'signal_cluster' } },
        { type: 'Feature', id: 'agenda-lille-001', geometry: { type: 'Point', coordinates: [3.0573, 50.6292] }, properties: { name: 'Cabinet slot', layer_key: 'agenda-windows', score: 66, source_kind: 'executive_calendar' } },
        { type: 'Feature', id: 'news-nantes-001', geometry: { type: 'Point', coordinates: [-1.5536, 47.2184] }, properties: { name: 'Logistics signal', layer_key: 'open-intelligence', score: 64, source_kind: 'field_digest' } },
        { type: 'Feature', id: 'action-strasbourg-001', geometry: { type: 'Point', coordinates: [7.7521, 48.5734] }, properties: { name: 'Coordination request', layer_key: 'preventive-actions', score: 62, source_kind: 'decision_queue' } },
      ],
    },
  },
  camera_presets: {
    country: { longitude: 2.25, latitude: 46.75, zoom: 6.32, pitch: 0, bearing: 0, duration_ms: 900 },
    'zone-nord': { longitude: 2.8, latitude: 48.55, zoom: 6.45, pitch: 0, bearing: 0, duration_ms: 850 },
    'zone-ouest': { longitude: -1.7, latitude: 46.3, zoom: 6.15, pitch: 0, bearing: 0, duration_ms: 850 },
    'zone-centre': { longitude: 3.25, latitude: 45.75, zoom: 6.45, pitch: 0, bearing: 0, duration_ms: 850 },
    'zone-est': { longitude: 6.5, latitude: 47.6, zoom: 6.2, pitch: 0, bearing: 0, duration_ms: 850 },
    'zone-sud': { longitude: 4.45, latitude: 43.35, zoom: 6.35, pitch: 0, bearing: 0, duration_ms: 850 },
  },
  visual_effects: {
    arc_links: [
      { source: [2.3522, 48.8566], target: [4.8357, 45.764], tone: 'watch', level: 68 },
      { source: [4.8357, 45.764], target: [5.3698, 43.2965], tone: 'critical', level: 76 },
      { source: [2.3522, 48.8566], target: [3.0573, 50.6292], tone: 'watch', level: 62 },
      { source: [-1.5536, 47.2184], target: [2.3522, 48.8566], tone: 'stable', level: 58 },
    ],
  },
};
const OCTOCITY_FRANCE_ZONES: MapZone[] = [
  {
    id: 'zone-nord',
    name: 'Northern Arc',
    level: 72,
    tone: 'watch',
    polygon: '265,62 383,72 444,140 410,222 312,212 235,158',
    centroid: { x: 338, y: 146 },
    popup_brief: {
      score: 72,
      severity: 'watch',
      drivers: ['Transport corridor variance', 'Public-service backlog', 'Regional signal cluster'],
      recommendation: 'Prepare an executive review before the next operating cycle.',
      sources: ['src-octocity-map-001', 'src-news-flow-014'],
    },
  },
  {
    id: 'zone-ouest',
    name: 'Atlantic Corridor',
    level: 61,
    tone: 'stable',
    polygon: '146,170 235,158 312,212 294,330 183,350 112,270',
    centroid: { x: 220, y: 257 },
    popup_brief: {
      score: 61,
      severity: 'stable',
      drivers: ['Harbor logistics normal', 'Energy alerts contained', 'Field reports updated'],
      recommendation: 'Keep monitoring and attach the latest field note to the briefing.',
      sources: ['src-map-atlantic-003', 'src-field-note-022'],
    },
  },
  {
    id: 'zone-centre',
    name: 'Central Hub',
    level: 68,
    tone: 'watch',
    polygon: '312,212 410,222 462,310 402,402 294,330',
    centroid: { x: 374, y: 302 },
    popup_brief: {
      score: 68,
      severity: 'watch',
      drivers: ['Decision queue rising', 'Cross-agency dependency', 'Budget arbitration pending'],
      recommendation: 'Route the item to human review with evidence links.',
      sources: ['src-decision-queue-007', 'src-budget-brief-005'],
    },
  },
  {
    id: 'zone-est',
    name: 'Rhine Interface',
    level: 58,
    tone: 'stable',
    polygon: '410,222 522,238 550,340 486,432 402,402 462,310',
    centroid: { x: 480, y: 326 },
    popup_brief: {
      score: 58,
      severity: 'stable',
      drivers: ['Industrial continuity green', 'Border flows nominal', 'No escalation signal'],
      recommendation: 'Maintain standard monitoring.',
      sources: ['src-industrial-012', 'src-flow-health-009'],
    },
  },
  {
    id: 'zone-sud',
    name: 'Mediterranean Gate',
    level: 76,
    tone: 'critical',
    polygon: '183,350 294,330 402,402 486,432 410,502 264,486 178,426',
    centroid: { x: 334, y: 424 },
    popup_brief: {
      score: 76,
      severity: 'elevated',
      drivers: ['Port capacity pressure', 'Weather-linked disruption', 'News-flow acceleration'],
      recommendation: 'Prepare a governed action proposal for the executive room.',
      sources: ['src-port-signal-018', 'src-weather-ops-004'],
    },
  },
];

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
              <strong>{{ mapLayersTitle }}</strong>
              <small>{{ activeLayerCount }} {{ mapLayersCountLabel }}</small>
            </button>
          </header>
          @if (controlsOpen) {
            <section class="control-section">
              <span>{{ basemapLabel }}</span>
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
              <span>{{ mapLayersCountLabel }}</span>
              <label class="layer-search">
                <span>{{ layerSearchLabel }}</span>
                <input type="search" [value]="layerSearch" (input)="setLayerSearch($any($event.target).value)" [placeholder]="layerSearchPlaceholder" />
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
                    <em>{{ layer.stateLabel || (isLayerActive(layer.key) ? 'visible' : hiddenLayerLabel) }} · {{ layer.freshness || 'source workspace' }}</em>
                  </button>
                }
              </div>
            </section>
          }
        </div>
        <button type="button" class="map-reset" (click)="resetCountry(); $event.stopPropagation()">{{ resetMapLabel }}</button>
        <div class="map-zoom-controls" (click)="$event.stopPropagation()">
          <button type="button" aria-label="Zoom avant" (click)="zoomIn()">+</button>
          <button type="button" aria-label="Zoom arrière" (click)="zoomOut()">−</button>
          <button type="button" aria-label="Vue pays" (click)="resetCountry()">⌂</button>
        </div>
        @if (!legendOpen && !isLayerActive('maritime-traffic') && !hasS3Legend()) {
          <button type="button" class="map-legend-toggle" (click)="toggleLegend(); $event.stopPropagation()">{{ levelsLabel }}</button>
        }
        @if (legendOpen || isLayerActive('maritime-traffic') || hasS3Legend()) {
          <div class="map-legend-bar">
            @if (legendOpen) {
              <div class="legend-section niveaux">
                <strong>{{ levelsLabel }}</strong>
                <span><i class="stable"></i>{{ stableLabel }}</span>
                <span><i class="monitoring"></i>{{ watchLabel }}</span>
                <span><i class="elevated"></i>{{ elevatedLabel }}</span>
                <span><i class="critical"></i>{{ criticalLabel }}</span>
              </div>
            }
            @if (isLayerActive('maritime-traffic') && !isOctocityMode) {
              <div class="legend-section maritime">
                <strong>Maritime</strong>
                <span><i class="corridor"></i>corridor</span>
                <span><i class="port"></i>ports</span>
                <span><i class="vessel-cargo"></i>cargo</span>
                <span><i class="vessel-tanker"></i>tanker</span>
                <button
                  type="button"
                  class="legend-port-webcam"
                  aria-label="Ouvrir la webcam port demo APM Apapa"
                  (click)="openDemoPortWebcam($event)"
                >
                  Port Vridi · cargo demo
                </button>
              </div>
            }
            @if (hasS3Legend()) {
              <div class="legend-section security">
                <strong>Sécurité</strong>
                <span><i class="s3-air"></i>ADS-B</span>
                <span><i class="s3-social"></i>social</span>
                <span><i class="s3-border"></i>frontière</span>
              </div>
            }
          </div>
        }
        @if (isLayerActive('maritime-traffic') && !isOctocityMode && !compact && !previewMode) {
          <div class="map-maritime-caption">Corridor maritime · Golfe de Guinée</div>
        }
        @if (briefOpen && selectedBriefZone(); as zone) {
          <article class="map-brief-popup" (click)="$event.stopPropagation()">
            <header>
              <span>{{ operationalBriefLabel }}</span>
              <button type="button" (click)="closeBrief()">{{ closeBriefLabel }}</button>
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
            <p>{{ zoneBrief(zone).recommendation || zone['recommendations']?.[0] || fallbackBriefRecommendation }}</p>
            <div class="brief-source-row">
              @for (source of zoneBriefSources(zone); track source) {
                <small>{{ source }}</small>
              }
            </div>
            <footer>
              <button type="button" (click)="emitEvidenceAction('arbitrage', zone)">{{ prepareReviewLabel }}</button>
              <button type="button" (click)="emitEvidenceAction('aya', zone)">{{ askAssistantLabel }}</button>
            </footer>
          </article>
        }
      </div>

      @if (fallback) {
        @if (isOctocityMode) {
          <svg class="fallback-map octocity-real-map" [attr.viewBox]="fallbackViewBox" role="img" aria-label="France operating map">
            <defs>
              <radialGradient id="octocitySeaGlow" cx="52%" cy="40%" r="75%">
                <stop offset="0%" stop-color="#07384a" />
                <stop offset="46%" stop-color="#052231" />
                <stop offset="100%" stop-color="#020912" />
              </radialGradient>
              <linearGradient id="octocityLand" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#234034" />
                <stop offset="48%" stop-color="#172a24" />
                <stop offset="100%" stop-color="#0d1715" />
              </linearGradient>
              <filter id="octocityMapShadow" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="10" stdDeviation="9" flood-color="#000000" flood-opacity="0.38" />
              </filter>
            </defs>
            <rect class="octocity-sea" x="40" y="24" width="620" height="520"></rect>
            <path class="octocity-bathymetry" d="M72,96 C166,138 220,178 274,246 C326,312 406,364 510,410"></path>
            <path class="octocity-bathymetry soft" d="M88,392 C160,352 226,344 296,372 C360,398 438,402 584,356"></path>
            <path class="octocity-bathymetry soft" d="M520,70 C548,142 562,208 548,292 C536,356 550,418 626,486"></path>
            @for (land of octocityNeighbourLandPaths; track land) {
              <path class="octocity-neighbour-land" [attr.d]="land"></path>
            }
            <path class="octocity-france-land" [attr.d]="octocityFranceLandPath" filter="url(#octocityMapShadow)"></path>
            <path class="octocity-coastline" [attr.d]="octocityFranceLandPath"></path>
            <path class="octocity-corsica" [attr.d]="octocityCorsicaPath" filter="url(#octocityMapShadow)"></path>
            @for (river of octocityRivers; track river.name) {
              <path class="octocity-river" [attr.d]="river.d"></path>
            }
            @for (zone of renderedZones; track zone.id) {
              <polygon
                class="octocity-zone"
                [attr.points]="zone.polygon"
                [attr.fill]="zoneFill(zone)"
                [attr.opacity]="selectedZoneId === zone.id ? 0.78 : 0.42"
                (click)="selectZone(zone)"
              ></polygon>
              <circle
                class="octocity-zone-pulse"
                [attr.cx]="zone.centroid.x"
                [attr.cy]="zone.centroid.y"
                [attr.r]="zonePulseRadius(zone)"
                [attr.fill]="zoneFill(zone)"
                opacity="0.18"
              ></circle>
              <text class="zone-label" [attr.x]="zone.centroid.x" [attr.y]="zone.centroid.y" text-anchor="middle">{{ zone.name }}</text>
            }
            @for (city of octocityCities; track city.name) {
              <g class="octocity-city" [class.capital]="city.capital">
                <circle class="octocity-city-halo" [attr.cx]="city.x" [attr.cy]="city.y" [attr.r]="city.capital ? 12 : 8"></circle>
                <circle class="octocity-city-dot" [attr.cx]="city.x" [attr.cy]="city.y" [attr.r]="city.capital ? 4.5 : 3.4"></circle>
                <text class="city-label" [attr.x]="city.labelX || city.x + 9" [attr.y]="city.labelY || city.y - 7">{{ city.name }}</text>
              </g>
            }
            <text class="sea-label atlantic" x="82" y="344">Atlantic Ocean</text>
            <text class="sea-label channel" x="168" y="92">English Channel</text>
            <text class="sea-label north" x="520" y="86">North Sea</text>
            <text class="sea-label med" x="405" y="504">Mediterranean Sea</text>
            <text class="map-scale-label" x="70" y="508">France operating room - live synthetic signals</text>
          </svg>
        } @else {
          <svg class="fallback-map" [attr.viewBox]="fallbackViewBox" role="img">
            @for (zone of renderedZones; track zone.id) {
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
      }

      <div class="map-hud">
        <span>{{ priorityHudLabel }}</span>
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
        border: 1px solid rgba(62, 230, 138, 0.22);
        border-radius: 12px;
        background:
          radial-gradient(circle at 58% 44%, rgba(101, 214, 110, 0.055), transparent 34%),
          linear-gradient(135deg, rgba(4, 8, 12, 0.98), rgba(9, 14, 20, 0.97));
        box-shadow:
          inset 0 1px 12px rgba(0, 0, 0, 0.28),
          inset 0 0 0 1px rgba(255,255,255,0.03),
          0 24px 70px rgba(0,0,0,0.22);
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
      .workspace-map.preview-mode .map-legend-bar,
      .workspace-map.preview-mode .map-legend-toggle,
      .workspace-map.preview-mode .map-maritime-caption,
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
      .workspace-map.compact .map-legend-bar,
      .workspace-map.compact .map-maritime-caption,
      .workspace-map.compact .map-compass,
      .workspace-map.preview-mode .map-control-panel,
      .workspace-map.preview-mode .map-reset,
      .workspace-map.preview-mode .map-legend-bar,
      .workspace-map.preview-mode .map-maritime-caption,
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
        filter: contrast(1.08) saturate(1.02) brightness(0.965);
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
        border: 1px solid rgba(62, 230, 138, 0.18);
        border-radius: 14px;
        background: rgba(10, 17, 24, 0.88);
        box-shadow: 0 18px 42px rgba(0, 0, 0, 0.40), inset 0 0 0 1px rgba(255,255,255,0.035);
        backdrop-filter: blur(12px) saturate(1.05);
        pointer-events: auto;
        z-index: 6;
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
        border: 1px solid rgba(62, 230, 138, 0.22);
        background: rgba(10, 17, 24, 0.88);
        color: rgba(196, 206, 218, 0.82);
        font: 750 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.10em;
        text-transform: uppercase;
        cursor: pointer;
        transition: background 150ms ease, border-color 150ms ease, color 150ms ease, opacity 150ms ease;
      }

      .basemap-switch button.active,
      .map-reset:hover {
        border-color: rgba(62, 230, 138, 0.48);
        background: rgba(62, 230, 138, 0.12);
        color: rgba(244, 247, 251, 0.96);
        box-shadow: 0 0 18px rgba(62, 230, 138, 0.14);
      }

      .basemap-switch button:hover,
      .layer-toggle:hover {
        border-color: rgba(62, 230, 138, 0.38);
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

      .map-legend-bar {
        position: absolute;
        left: 50%;
        bottom: 14px;
        transform: translateX(-50%);
        z-index: 5;
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        justify-content: center;
        gap: 14px 18px;
        max-width: calc(100% - 32px);
        padding: 10px 16px;
        border: 1px solid rgba(62, 230, 138, 0.16);
        border-radius: 999px;
        background: rgba(10, 17, 24, 0.85);
        backdrop-filter: blur(12px);
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.32);
        pointer-events: none;
      }

      .legend-section {
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
      }

      .legend-section + .legend-section {
        padding-left: 14px;
        border-left: 1px solid rgba(62, 230, 138, 0.14);
      }

      .legend-section strong {
        color: rgba(196, 206, 218, 0.78);
        font: 800 9px/1 var(--mission-mono, monospace);
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }

      .legend-section span {
        display: flex;
        align-items: center;
        gap: 6px;
        color: rgba(196, 206, 218, 0.72);
        font: 700 11px/1 var(--mission-mono, monospace);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        white-space: nowrap;
      }

      .legend-section i {
        display: inline-block;
        flex-shrink: 0;
      }

      .legend-section .stable { width: 8px; height: 8px; border-radius: 999px; background: #166534; box-shadow: 0 0 6px rgba(22, 101, 52, 0.5); }
      .legend-section .monitoring { width: 8px; height: 8px; border-radius: 999px; background: #f59e0b; box-shadow: 0 0 6px rgba(245, 158, 11, 0.4); }
      .legend-section .elevated { width: 8px; height: 8px; border-radius: 999px; background: #f97316; box-shadow: 0 0 6px rgba(249, 115, 22, 0.4); }
      .legend-section .critical { width: 8px; height: 8px; border-radius: 999px; background: #dc2626; box-shadow: 0 0 8px rgba(220, 38, 38, 0.55); }

      .legend-section.maritime .corridor {
        width: 18px;
        height: 2px;
        border-radius: 999px;
        background: linear-gradient(90deg, rgba(62, 230, 138, 0.25), rgba(62, 230, 138, 0.85));
      }
      .legend-section.maritime .port {
        width: 7px;
        height: 7px;
        transform: rotate(45deg);
        background: #f59e0b;
        border-radius: 1px;
      }
      .legend-section.maritime .vessel-cargo,
      .legend-section.maritime .vessel-tanker {
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-bottom: 10px solid #22c55e;
        background: transparent;
      }
      .legend-section.maritime .vessel-tanker {
        border-bottom-color: #f97316;
      }
      .legend-section.maritime .legend-port-webcam {
        margin-left: 0.35rem;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        border: 1px solid rgba(255, 160, 67, 0.45);
        background: rgba(255, 160, 67, 0.12);
        color: rgba(255, 220, 170, 0.95);
        font-size: 0.68rem;
        font-weight: 600;
        cursor: pointer;
        white-space: nowrap;
      }
      .legend-section.maritime .legend-port-webcam:hover {
        background: rgba(255, 160, 67, 0.22);
      }

      .legend-section.security .s3-air {
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-bottom: 10px solid var(--mission-warning);
        background: transparent;
      }
      .legend-section.security .s3-social {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--mission-info);
        box-shadow: 0 0 0 3px rgba(125, 211, 252, 0.18);
      }
      .legend-section.security .s3-border {
        width: 18px;
        height: 8px;
        border: 1px solid rgba(241, 180, 90, 0.78);
        border-radius: 3px;
        background: rgba(241, 180, 90, 0.18);
      }
      .map-maritime-caption {
        position: absolute;
        left: 50%;
        bottom: 58px;
        transform: translateX(-50%);
        z-index: 4;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(10, 17, 24, 0.72);
        color: rgba(196, 206, 218, 0.62);
        font: 700 10px/1 var(--mission-mono, monospace);
        letter-spacing: 0.12em;
        text-transform: uppercase;
        pointer-events: none;
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
      .workspace-map.basemap-contours .map-legend-bar,
      .workspace-map.basemap-contours .map-brief-popup,
      .workspace-map.basemap-contours .map-hud,
      .workspace-map.basemap-contours .map-attribution {
        background: rgba(6, 14, 22, 0.92);
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

      .fallback-map.octocity-real-map {
        display: block;
        width: 100%;
        height: 100%;
        padding: 0;
        background:
          radial-gradient(circle at 48% 44%, rgba(34, 211, 238, 0.10), transparent 34%),
          linear-gradient(135deg, rgba(3, 19, 31, 0.96), rgba(1, 8, 14, 0.98));
      }

      .octocity-real-map .octocity-sea {
        fill: url(#octocitySeaGlow);
      }

      .octocity-real-map .octocity-bathymetry {
        fill: none;
        stroke: rgba(96, 165, 250, 0.18);
        stroke-width: 1.1;
        stroke-dasharray: 7 9;
      }

      .octocity-real-map .octocity-bathymetry.soft {
        stroke: rgba(45, 212, 191, 0.13);
      }

      .octocity-real-map .octocity-neighbour-land {
        fill: rgba(20, 36, 31, 0.66);
        stroke: rgba(117, 150, 139, 0.24);
        stroke-width: 1;
      }

      .octocity-real-map .octocity-france-land,
      .octocity-real-map .octocity-corsica {
        fill: url(#octocityLand);
        stroke: rgba(193, 236, 214, 0.42);
        stroke-width: 1.7;
      }

      .octocity-real-map .octocity-coastline {
        fill: none;
        stroke: rgba(125, 211, 252, 0.42);
        stroke-width: 2.2;
        stroke-linejoin: round;
      }

      .octocity-real-map .octocity-river {
        fill: none;
        stroke: rgba(147, 197, 253, 0.58);
        stroke-width: 2.1;
        stroke-linecap: round;
        filter: drop-shadow(0 0 5px rgba(96, 165, 250, 0.34));
      }

      .octocity-real-map .octocity-zone {
        cursor: pointer;
        stroke: rgba(222, 248, 255, 0.78);
        stroke-width: 1.45;
        stroke-linejoin: round;
        mix-blend-mode: screen;
        filter: drop-shadow(0 0 9px rgba(34, 211, 238, 0.20));
      }

      .octocity-real-map .octocity-zone:hover {
        opacity: 0.84;
        filter: drop-shadow(0 0 15px rgba(103, 232, 249, 0.48));
      }

      .octocity-real-map .octocity-zone-pulse {
        pointer-events: none;
        animation: mapPulse 3.2s ease-in-out infinite;
        mix-blend-mode: screen;
      }

      .octocity-real-map .octocity-city-halo {
        fill: rgba(103, 232, 249, 0.16);
        stroke: rgba(103, 232, 249, 0.34);
        stroke-width: 1;
      }

      .octocity-real-map .octocity-city-dot {
        fill: rgba(231, 246, 255, 0.98);
        stroke: rgba(2, 6, 23, 0.96);
        stroke-width: 1.5;
        filter: drop-shadow(0 0 5px rgba(103, 232, 249, 0.52));
      }

      .octocity-real-map .octocity-city.capital .octocity-city-dot {
        fill: rgba(103, 232, 249, 1);
        stroke: rgba(7, 12, 19, 1);
      }

      .fallback-map.octocity-real-map .city-label {
        fill: rgba(241, 250, 255, 0.92);
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0;
        paint-order: stroke;
        stroke: rgba(1, 6, 12, 0.82);
        stroke-width: 3px;
      }

      .fallback-map.octocity-real-map .zone-label {
        fill: rgba(248, 250, 252, 0.95);
        font-size: 18px;
        font-weight: 800;
        letter-spacing: 0;
        paint-order: stroke;
        stroke: rgba(1, 3, 8, 0.92);
        stroke-width: 4.5px;
        filter: drop-shadow(0 0 8px rgba(0, 0, 0, 0.52));
      }

      .fallback-map.octocity-real-map .sea-label,
      .fallback-map.octocity-real-map .map-scale-label {
        fill: rgba(181, 216, 231, 0.56);
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        stroke: rgba(1, 6, 12, 0.55);
        stroke-width: 2px;
      }

      .fallback-map.octocity-real-map .sea-label.atlantic {
        transform: rotate(-22deg);
        transform-origin: 82px 344px;
      }

      .fallback-map.octocity-real-map .sea-label.channel {
        transform: rotate(-8deg);
        transform-origin: 168px 92px;
      }

      .fallback-map.octocity-real-map .sea-label.med {
        transform: rotate(-3deg);
        transform-origin: 405px 504px;
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
  @Input() assistantName = 'AYA';
  @Input() compact = false;
  @Input() previewMode = false;
  @Input() previewLayers: string[] | null = null;
  /**
   * AIS vessel positions to render on top of the basemap when the
   * `maritime-traffic` layer is active. Rendering is delegated to deck.gl
   * (IconLayer triangles) so positions inherit MapLibre's native Mercator
   * projection — no HTML overlay math, no drift on pan/zoom/resize.
   */
  @Input() vessels: VesselPosition[] | null = null;
  /** When set, only the vessel matching this MMSI is highlighted (halo + larger pin). */
  @Input() highlightedVesselMmsi: string | null = null;
  /**
   * When the cockpit preview user picks Abidjan zoom, skip automatic
   * national fitBounds from bootstrap / vessel layer refresh.
   */
  @Input() userSelectedZoom: 'abidjan' | 'country' | null = null;
  @Output() zoneSelected = new EventEmitter<any>();
  @Output() evidenceAction = new EventEmitter<{ action: string; zone: any }>();
  @Output() vesselSelected = new EventEmitter<VesselPosition>();
  /** Emitted when the user clicks the map background (not a zone or vessel). */
  @Output() mapBackgroundClick = new EventEmitter<void>();
  @ViewChild('mapCanvas') private readonly mapCanvas?: ElementRef<HTMLDivElement>;

  fallback = false;
  selectedBasemapKey = 'command';
  controlsOpen = false;
  legendOpen = true;
  briefOpen = false;
  layerSearch = '';
  readonly octocityFranceLandPath = OCTOCITY_FRANCE_LAND_PATH;
  readonly octocityNeighbourLandPaths = OCTOCITY_NEIGHBOUR_LAND_PATHS;
  readonly octocityCorsicaPath = OCTOCITY_CORSICA_PATH;
  readonly octocityRivers = OCTOCITY_RIVERS;
  readonly octocityCities = OCTOCITY_CITY_MARKERS;

  private readonly cdr = inject(ChangeDetectorRef);
  private readonly activeLayerKeys = new Set<string>();
  private layerStateInitialized = false;
  /**
   * Set to ``true`` the first time the user clicks the maritime-traffic
   * toggle. While this remains ``false``, an incoming vessel snapshot
   * auto-activates the layer so the navires AIS appear without a manual
   * toggle (SENTINEL-CI demo flow).
   */
  private userToggledMaritime = false;
  private mapInstance: any;
  private deckOverlay: any;
  private deckLayersModule: any;
  private vesselIconAtlas: string | null = null;
  private focusMarker: any | null = null;
  /** Applied on first map load when external state arrives before MapLibre init. */
  private pendingExternalMapState: Record<string, any> | null = null;
  private hoveredZoneId: string | null = null;
  private zonePulsePhase = 0;
  private atlanticPulsePhase = 0;
  private zonePulseTimer: ReturnType<typeof setInterval> | null = null;
  private atlanticPulseTimer: ReturnType<typeof setInterval> | null = null;

  get layerControls(): MapLayerControl[] {
    const mapSystem = this.effectiveMapSystem;
    const catalog = mapSystem?.['layer_registry'] || mapSystem?.['layer_catalog'];
    if (Array.isArray(catalog) && catalog.length) {
      const controls = catalog.map((layer: any) => ({
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
      return this.isOctocityMode ? controls.filter((layer) => layer.key !== 'maritime-traffic') : controls;
    }
    if (this.isOctocityMode) {
      return [
        { key: 'territorial-risk', label: 'Operating zones', shortLabel: 'Zones', tone: 'cyan', count: this.renderedZones.length, confidence: 82, visible: true },
        { key: 'open-intelligence', label: 'News signals', shortLabel: 'News', tone: 'blue', count: 3, confidence: 76, visible: true },
        { key: 'regional-context', label: 'European coordination', shortLabel: 'Coordination', tone: 'orange', count: 4, confidence: 74, visible: true },
        { key: 'strategic-projects', label: 'Strategic programs', shortLabel: 'Programs', tone: 'green', count: 3, confidence: 71, visible: true },
        { key: 'agenda-windows', label: 'Executive windows', shortLabel: 'Agenda', tone: 'amber', count: 5, confidence: 84, visible: true },
        { key: 'visual-streams', label: 'Field observations', shortLabel: 'Field', tone: 'violet', count: 2, confidence: 68, visible: true },
        { key: 'preventive-actions', label: 'Recommended actions', shortLabel: 'Actions', tone: 'red', count: 4, confidence: 78, visible: true },
      ];
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
    const options = this.effectiveMapSystem?.['basemap_options'];
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
    return this.renderedZones.find((zone) => zone.id === this.selectedZoneId)?.name || (this.isOctocityMode ? 'France' : 'Cote d’Ivoire');
  }

  get selectedZoneLevel(): number {
    return Math.round(this.renderedZones.find((zone) => zone.id === this.selectedZoneId)?.level || 58);
  }

  get mapAttribution(): string {
    if (this.isOctocityMode) return 'France operating room · synthetic Agentium map';
    return this.effectiveMapSystem?.['renderer_config']?.attribution || 'Couches Agentium workspace';
  }

  get resetMapLabel(): string {
    return this.isOctocityMode ? 'Recenter Octocity' : 'Recentrer Côte d’Ivoire';
  }

  get askAssistantLabel(): string {
    return this.isOctocityMode ? `Ask ${this.assistantName || 'OCTAVE'}` : 'Demander AYA';
  }

  get mapLayersTitle(): string {
    return this.isOctocityMode ? 'Map layers' : 'Couches carte';
  }

  get mapLayersCountLabel(): string {
    return this.isOctocityMode ? 'layers' : 'couches';
  }

  get basemapLabel(): string {
    return this.isOctocityMode ? 'Basemap' : 'Fond';
  }

  get layerSearchLabel(): string {
    return this.isOctocityMode ? 'Search' : 'Rechercher';
  }

  get layerSearchPlaceholder(): string {
    return this.isOctocityMode ? 'signal, news, agenda...' : 'navire, presse, agenda...';
  }

  get hiddenLayerLabel(): string {
    return this.isOctocityMode ? 'hidden' : 'masqué';
  }

  get levelsLabel(): string {
    return this.isOctocityMode ? 'Levels' : 'Niveaux';
  }

  get stableLabel(): string {
    return this.isOctocityMode ? 'stable' : 'stable';
  }

  get watchLabel(): string {
    return this.isOctocityMode ? 'watch' : 'surveillance';
  }

  get elevatedLabel(): string {
    return this.isOctocityMode ? 'elevated' : 'élevé';
  }

  get criticalLabel(): string {
    return this.isOctocityMode ? 'critical' : 'critique';
  }

  get closeBriefLabel(): string {
    return this.isOctocityMode ? 'Close' : 'Fermer';
  }

  get operationalBriefLabel(): string {
    return this.isOctocityMode ? 'Operational brief' : 'Brief operationnel';
  }

  get priorityHudLabel(): string {
    return this.isOctocityMode ? 'Priority signal' : 'Zone prioritaire';
  }

  get fallbackBriefRecommendation(): string {
    return this.isOctocityMode ? 'Qualify evidence, then prepare a governed review.' : 'Qualifier puis preparer arbitrage.';
  }

  get prepareReviewLabel(): string {
    return this.isOctocityMode ? 'Prepare review' : 'Preparer arbitrage';
  }

  get isOctocityMode(): boolean {
    return String(this.assistantName || '').toUpperCase() === 'OCTAVE';
  }

  get effectiveMapSystem(): Record<string, any> | null {
    return this.isOctocityMode ? OCTOCITY_MAP_SYSTEM : this.mapSystem;
  }

  get renderedZones(): MapZone[] {
    return this.isOctocityMode ? OCTOCITY_FRANCE_ZONES : this.zones;
  }

  get fallbackViewBox(): string {
    return this.isOctocityMode ? '40 24 620 520' : (this.map?.['view_box'] || '200 40 470 480');
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
    if (
      changes['zones']
      || changes['mapSystem']
      || changes['previewMode']
      || changes['previewLayers']
      || changes['vessels']
      || changes['highlightedVesselMmsi']
    ) {
      if (!this.layerStateInitialized) this.syncStateFromMapPayload();
      this.maybeAutoEnableMaritime();
      this.updateDeckLayers();
    }
    if (changes['mapState'] && this.mapState) {
      this.applyExternalMapState(this.mapState);
    }
    if (changes['userSelectedZoom'] && this.userSelectedZoom === 'abidjan' && this.mapState) {
      this.applyExternalMapState(this.mapState);
    }
    if (changes['selectedZoneId'] && !changes['selectedZoneId'].firstChange) {
      this.briefOpen = true;
      this.focusSelectedZone();
    }
  }

  ngOnDestroy(): void {
    if (this.zonePulseTimer) clearInterval(this.zonePulseTimer);
    if (this.atlanticPulseTimer) clearInterval(this.atlanticPulseTimer);
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
    return this.renderedZones.find((zone) => zone.id === this.selectedZoneId) || this.renderedZones[0] || null;
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
    if (zone.tone === 'critical') return '#dc2626';
    if (zone.tone === 'watch') return '#f59e0b';
    return '#166534';
  }

  zonePulseRadius(zone: MapZone): number {
    return zone.tone === 'critical' ? 38 : zone.tone === 'watch' ? 27 : 18;
  }

  isLayerActive(key: string): boolean {
    return this.activeLayerKeys.has(key);
  }

  hasS3Legend(): boolean {
    return this.isLayerActive('military-air')
      || this.isLayerActive('social-geo')
      || this.isLayerActive('border-tension');
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
    if (key === 'maritime-traffic') this.userToggledMaritime = true;
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
    const mapSystem = this.effectiveMapSystem;
    const renderer = mapSystem?.['renderer_config']?.renderer;
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
      const view = mapSystem?.['renderer_config']?.initial_view_state || {};
      this.mapInstance = new mapCtor({
        container: this.mapCanvas.nativeElement,
        style: this.currentBasemapStyle() || mapSystem?.['renderer_config']?.style || this.defaultStyle(),
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
      this.mapInstance.on('click', (event: { point?: { x: number; y: number } }) => {
        const point = event?.point;
        if (!point || !this.deckOverlay?.pickObject) {
          this.mapBackgroundClick.emit();
          return;
        }
        const picked = this.deckOverlay.pickObject({ x: point.x, y: point.y, radius: 6 });
        if (!picked?.object) this.mapBackgroundClick.emit();
      });
      this.mapInstance.on('load', () => {
        this.mapInstance.addControl(this.deckOverlay);
        this.finishMapBootstrap();
        this.startMapPulseAnimations();
      });
      this.mapInstance.on('moveend', () => this.updateDeckLayers());
      this.mapInstance.on('error', () => this.enableFallback());
    } catch {
      this.enableFallback();
    }
  }

  private syncStateFromMapPayload(): void {
    const mapSystem = this.effectiveMapSystem;
    const defaultState = mapSystem?.['default_map_state'] || {};
    const basemap = String(defaultState.basemap || mapSystem?.['renderer_config']?.default_basemap || 'administrative');
    if (this.isOctocityMode && !this.layerStateInitialized) {
      this.selectedBasemapKey = basemap;
    }
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

  /**
   * Ensures `maritime-traffic` is active whenever an AIS vessel snapshot
   * is supplied via the `vessels` Input, so the navires render without
   * requiring a manual toggle (SENTINEL-CI demo flow). Skipped once the
   * user has explicitly clicked the maritime toggle.
   */
  private maybeAutoEnableMaritime(): void {
    if (this.isOctocityMode) return;
    if (this.userToggledMaritime) return;
    if (!(this.vessels?.length || 0)) return;
    if (this.activeLayerKeys.has('maritime-traffic')) return;
    if (!this.layerControls.some((layer) => layer.key === 'maritime-traffic')) return;
    this.activeLayerKeys.add('maritime-traffic');
  }

  private resolvePreviewLayers(): string[] | null {
    if (!this.previewMode) return null;
    const requested = (this.previewLayers || []).filter(Boolean);
    if (requested.length) {
      return requested.map((key) => this.normalizePreviewLayerKey(key)).filter(Boolean) as string[];
    }
    const defaults = this.isOctocityMode
      ? ['territorial-risk', 'open-intelligence', 'regional-context', 'preventive-actions']
      : ['territorial-risk', 'open-intelligence', 'maritime-traffic'];
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

  private shouldPreserveUserZoom(): boolean {
    return this.userSelectedZoom === 'abidjan';
  }

  private finishMapBootstrap(): void {
    if (this.shouldPreserveUserZoom()) {
      const state = this.mapState || this.pendingExternalMapState;
      if (state) {
        this.applyExternalMapState(state);
      }
      this.mapInstance?.resize?.();
      this.updateDeckLayers();
      return;
    }
    this.fitCountry(0);
    setTimeout(() => {
      this.mapInstance?.resize?.();
      if (!this.shouldPreserveUserZoom()) {
        this.fitCountry(220);
      } else if (this.mapState || this.pendingExternalMapState) {
        this.applyExternalMapState(this.mapState || this.pendingExternalMapState!);
      }
    }, 80);
    this.mapInstance.once?.('idle', () => {
      this.mapInstance?.resize?.();
      if (!this.shouldPreserveUserZoom()) {
        this.fitCountry(0);
        return;
      }
      const state = this.mapState || this.pendingExternalMapState;
      if (state) {
        this.applyExternalMapState(state);
      }
    });
  }

  private applyExternalMapState(state: Record<string, any>): void {
    if (!this.mapInstance) {
      this.pendingExternalMapState = state;
      return;
    }
    this.pendingExternalMapState = null;
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
        duration: Math.max(0, Math.min(requestedDuration, 400)),
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
    if (!this.mapInstance || this.shouldPreserveUserZoom()) return;
    const mapSystem = this.effectiveMapSystem;
    const bounds = mapSystem?.['renderer_config']?.bounds || [[-8.65, 4.2], [-2.45, 10.75]];
    const preset = mapSystem?.['default_map_state']?.camera || mapSystem?.['camera_presets']?.country;
    if (this.isOctocityMode && preset) {
      const presetZoom = Number(preset.zoom ?? 6.08);
      this.mapInstance.easeTo({
        center: [preset.longitude, preset.latitude],
        zoom: this.compact ? 5.05 : presetZoom,
        pitch: 0,
        bearing: 0,
        duration,
      });
      return;
    }
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
    const { GeoJsonLayer, ScatterplotLayer, ArcLayer, TextLayer, IconLayer } = this.deckLayersModule;
    const mapSystem = this.effectiveMapSystem;
    const zonesSource = mapSystem?.['geojson_sources']?.zones;
    const markersSource = mapSystem?.['geojson_sources']?.markers;
    const contextMarkersSource = mapSystem?.['geojson_sources']?.context_markers;
    const contextLinesSource = mapSystem?.['geojson_sources']?.context_lines;
    const eventPointsSource = mapSystem?.['geojson_sources']?.event_points || mapSystem?.['event_points'];
    const maritimeAreaSource = mapSystem?.['geojson_sources']?.maritime_area;
    const maritimePointsSource = mapSystem?.['geojson_sources']?.maritime_points;
    const maritimeRoutesSource = mapSystem?.['geojson_sources']?.maritime_routes;
    const maritimeDensitySource = mapSystem?.['geojson_sources']?.maritime_density;
    const countryBoundarySource = mapSystem?.['country_boundary'];
    const districtBoundariesSource = mapSystem?.['district_boundaries'];
    const adminBoundariesSource = mapSystem?.['admin_boundaries'];
    const citiesSource = mapSystem?.['cities'];
    const arcs = mapSystem?.['visual_effects']?.arc_links || [];
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
    const showSocialGeo = this.isLayerActive('social-geo');
    const showMilitaryAir = this.isLayerActive('military-air');
    const showBorderTension = this.isLayerActive('border-tension');
    const socialGeoSource = mapSystem?.['geojson_sources']?.social_geo;
    const militaryAirSource = mapSystem?.['geojson_sources']?.military_air;
    const borderTensionSource = mapSystem?.['geojson_sources']?.border_tension;
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
        getLineColor: this.isLightBasemap() ? [14, 54, 75, 200] : [156, 222, 255, 170],
        lineWidthMinPixels: 1,
        parameters: { depthTest: false },
      }));

    layers.push(new GeoJsonLayer({
      id: 'sentinel-district-boundaries',
      data: districtBoundariesSource,
      pickable: false,
      filled: false,
      stroked: true,
      getFillColor: [0, 0, 0, 0],
      getLineColor: this.isLightBasemap() ? [26, 70, 91, 72] : [170, 224, 248, 52],
      lineWidthMinPixels: showTerritory ? 0 : 0.75,
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
        getFillColor: (feature: any) => {
          const zoneId = feature.properties?.id;
          const tone = feature.properties?.tone;
          const selected = zoneId === this.selectedZoneId;
          const hovered = zoneId === this.hoveredZoneId;
          return this.deckColor(tone, selected, hovered, zoneId);
        },
        getLineColor: (feature: any) => {
          const zoneId = feature.properties?.id;
          const tone = feature.properties?.tone;
          const selected = zoneId === this.selectedZoneId;
          const hovered = zoneId === this.hoveredZoneId;
          return this.deckLineColor(tone, selected, hovered);
        },
        lineWidthMinPixels: 0.75,
        lineWidthMaxPixels: selectedOrTopZoneMarkers.length ? 1.5 : 1.1,
        parameters: { depthTest: false },
        onClick: (info: any) => this.emitDeckZone(info.object?.properties?.id),
        onHover: (info: any) => {
          const nextId = info.object?.properties?.id || null;
          if (nextId === this.hoveredZoneId) return;
          this.hoveredZoneId = nextId;
          this.updateDeckLayers();
        },
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
          filled: false,
          stroked: true,
          getFillColor: [0, 0, 0, 0],
          getLineColor: this.maritimeAreaLineColor(),
          lineWidthMinPixels: 0.55,
          lineWidthMaxPixels: 0.85,
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
        getLineWidth: (feature: any) => feature.properties?.visual_role === 'port_approach' ? 2400 : 1800,
        lineWidthMinPixels: 0.75,
        lineWidthMaxPixels: 1.8,
        parameters: { depthTest: false },
      }));
      const maritimeFeatures = maritimePointsSource?.features || [];
      const portFeatures = maritimeFeatures.filter((feature: any) => feature.properties?.kind === 'port');
      layers.push(new IconLayer({
        id: 'sentinel-maritime-ports',
        data: portFeatures,
        pickable: true,
        iconAtlas: this.getVesselIconAtlas(),
        iconMapping: VESSEL_ICON_MAPPING,
        getIcon: () => 'diamond',
        getPosition: (feature: any) => feature.geometry.coordinates,
        getSize: this.compact ? 10 : 12,
        getColor: (feature: any) => this.maritimePointColor(feature, 230),
        sizeUnits: 'pixels',
        billboard: true,
        parameters: { depthTest: false },
        onClick: (info: any) => this.emitMaritimeEvidence(info.object),
      }));
      const maritimeLabelFeatures = portFeatures.slice(0, 2);
      layers.push(new TextLayer({
        id: 'sentinel-maritime-labels',
        data: maritimeLabelFeatures,
        getPosition: (feature: any) => feature.geometry.coordinates,
        getText: (feature: any) => (feature.properties?.name || '').toUpperCase(),
        getSize: this.compact ? 9 : 10,
        getColor: this.isLightBasemap() ? [10, 25, 38, 242] : [240, 250, 255, 244],
        getPixelOffset: [0, -16],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'bottom',
        fontSettings: { sdf: true },
        outlineColor: this.isLightBasemap() ? [250, 253, 255, 235] : [4, 8, 13, 242],
        outlineWidth: 3,
        billboard: true,
        parameters: { depthTest: false },
      }));

    }

    // ----------------------------------------------------------------------
    // S3 — Posture securitaire dual-axis deck layers.
    // border-tension is rendered first so its polygons sit beneath the
    // social-geo / military-air markers without occluding them.
    // ----------------------------------------------------------------------
    if (showBorderTension && borderTensionSource?.features?.length) {
      layers.push(new GeoJsonLayer({
        id: 'sentinel-border-tension',
        data: borderTensionSource,
        pickable: false,
        filled: true,
        stroked: true,
        getFillColor: (feature: any) =>
          feature.properties?.tone === 'watch' ? [241, 180, 90, 46] : [180, 195, 215, 36],
        getLineColor: (feature: any) =>
          feature.properties?.tone === 'watch' ? [241, 180, 90, 218] : [180, 195, 215, 170],
        lineWidthMinPixels: 1.15,
        lineWidthMaxPixels: 1.9,
        parameters: { depthTest: false },
      }));
    }
    if (showSocialGeo && socialGeoSource?.features?.length) {
      layers.push(new ScatterplotLayer({
        id: 'sentinel-social-geo',
        data: socialGeoSource.features,
        pickable: true,
        stroked: true,
        filled: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => {
          const engagement = Number(feature.properties?.engagement || 0);
          return Math.max(6, Math.min(20, Math.sqrt(engagement) / 3.6));
        },
        getFillColor: (feature: any) => {
          const sentiment = feature.properties?.sentiment;
          if (sentiment === 'positive') return [99, 209, 141, 220];
          if (sentiment === 'negative') return [240, 100, 118, 220];
          return [156, 196, 230, 200];
        },
        getLineColor: (feature: any) =>
          feature.properties?.kind === 'officiel' ? [255, 255, 255, 240] : [10, 25, 38, 180],
        lineWidthMinPixels: (feature: any) => (feature.properties?.kind === 'officiel' ? 1.9 : 0.9),
        parameters: { depthTest: false },
      }));
    }
    if (showMilitaryAir && militaryAirSource?.features?.length) {
      layers.push(new ScatterplotLayer({
        id: 'sentinel-military-air-halo',
        data: militaryAirSource.features,
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: (feature: any) => feature.geometry.coordinates,
        radiusUnits: 'pixels',
        getRadius: (feature: any) => feature.properties?.tone === 'watch' ? 19 : 15,
        getFillColor: (feature: any) =>
          feature.properties?.tone === 'watch' ? [241, 180, 90, 42] : [125, 211, 252, 30],
        getLineColor: (feature: any) =>
          feature.properties?.tone === 'watch' ? [241, 180, 90, 96] : [125, 211, 252, 72],
        lineWidthMinPixels: 1,
        parameters: { depthTest: false },
      }));
      layers.push(new IconLayer({
        id: 'sentinel-military-air',
        data: militaryAirSource.features,
        pickable: true,
        iconAtlas: this.getVesselIconAtlas(),
        iconMapping: VESSEL_ICON_MAPPING,
        getIcon: () => 'triangle',
        getPosition: (feature: any) => feature.geometry.coordinates,
        getAngle: (feature: any) => Number(feature.properties?.heading || 0),
        getSize: (feature: any) => feature.properties?.tone === 'watch'
          ? (this.compact ? 14 : 17)
          : (this.compact ? 12 : 15),
        getColor: (feature: any) =>
          feature.properties?.tone === 'watch' ? [241, 180, 90, 252] : [156, 196, 230, 236],
        sizeUnits: 'pixels',
        billboard: true,
        parameters: { depthTest: false },
      }));
      layers.push(new TextLayer({
        id: 'sentinel-military-air-labels',
        data: militaryAirSource.features.slice(0, this.compact ? 3 : 5),
        getPosition: (feature: any) => feature.geometry.coordinates,
        getText: (feature: any) => String(feature.properties?.callsign || feature.properties?.id || ''),
        getSize: this.compact ? 8 : 9,
        getColor: this.isLightBasemap() ? [10, 25, 38, 230] : [240, 250, 255, 232],
        getPixelOffset: [0, -17],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'bottom',
        fontSettings: { sdf: true, fontWeight: 700 },
        outlineColor: this.isLightBasemap() ? [255, 255, 255, 232] : [4, 8, 13, 232],
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
        getTargetColor: (item: any) => this.deckColor(item.tone, false, false, undefined, 40),
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
        getFillColor: (feature: any) => this.deckColor(
          feature.properties?.tone,
          feature.properties?.zone_id === this.selectedZoneId,
          feature.properties?.zone_id === this.hoveredZoneId,
          feature.properties?.zone_id,
          -18,
        ),
        getLineColor: (feature: any) => this.deckLineColor(
          feature.properties?.tone,
          feature.properties?.zone_id === this.selectedZoneId,
          feature.properties?.zone_id === this.hoveredZoneId,
        ),
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
        getFillColor: (feature: any) => this.deckColor(
          feature.properties?.tone,
          feature.properties?.zone_id === this.selectedZoneId,
          feature.properties?.zone_id === this.hoveredZoneId,
          feature.properties?.zone_id,
          80,
        ),
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
        getText: (feature: any) => (feature.properties?.name || '').toUpperCase(),
        getSize: this.compact ? 10 : 11,
        getColor: this.isLightBasemap() ? [8, 28, 42, 245] : [246, 251, 255, 238],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        fontSettings: { sdf: true, fontWeight: 700 },
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

    // Vessel pins must be the topmost pickable deck layers so clicks on
    // Atlantic Trader are not swallowed by zone polygons or Nord markers.
    if (showMaritime) {
      this.appendVesselDeckLayers(layers);
    }
    return layers;
  }

  private appendVesselDeckLayers(layers: any[]): void {
    const { IconLayer, TextLayer } = this.deckLayersModule || {};
    if (!IconLayer || !TextLayer) return;

    const vesselsRaw = (this.vessels || []).filter(
      (vessel) => Number.isFinite(Number(vessel?.lat)) && Number.isFinite(Number(vessel?.lon)),
    );
    const vesselsData = this.spreadVesselPositions(vesselsRaw);
    if (!vesselsData.length) return;

    const highlightedMmsi = this.highlightedVesselMmsi;
    const isVesselHighlighted = (vessel: VesselPosition) =>
      Boolean(
        (highlightedMmsi && vessel.mmsi === highlightedMmsi)
          || vessel.linked_cargo_id
          || vessel.highlight,
      );
    const atlanticTrader = vesselsData.find((vessel) => this.isAtlanticTrader(vessel));
    const vesselIconAtlas = this.getVesselIconAtlas();
    const highlightedVessels = vesselsData.filter(isVesselHighlighted);
    if (highlightedVessels.length) {
      layers.push(new IconLayer({
        id: 'sentinel-vessels-halo',
        data: highlightedVessels,
        pickable: false,
        iconAtlas: vesselIconAtlas,
        iconMapping: VESSEL_ICON_MAPPING,
        getIcon: () => 'triangle',
        getPosition: (vessel: VesselPosition & { displayLon: number; displayLat: number }) =>
          [vessel.displayLon, vessel.displayLat],
        getAngle: (vessel: VesselPosition) => this.vesselIconAngle(vessel),
        getSize: (vessel: VesselPosition) =>
          this.vesselIconSize(isVesselHighlighted(vessel)) + (this.isAtlanticTrader(vessel) ? this.atlanticHaloBoost() : 8),
        getColor: (vessel: VesselPosition) =>
          ([...VESSEL_HIGHLIGHT_RGB, this.isAtlanticTrader(vessel) ? this.atlanticHaloAlpha() : 68] as any),
        sizeUnits: 'pixels',
        billboard: true,
        parameters: { depthTest: false },
      }));
    }
    layers.push(new IconLayer({
      id: 'sentinel-vessels-icons',
      data: vesselsData,
      pickable: true,
      iconAtlas: vesselIconAtlas,
      iconMapping: VESSEL_ICON_MAPPING,
      getIcon: () => 'triangle',
      getPosition: (vessel: VesselPosition & { displayLon: number; displayLat: number }) =>
        [vessel.displayLon, vessel.displayLat],
      getAngle: (vessel: VesselPosition) => this.vesselIconAngle(vessel),
      getSize: (vessel: VesselPosition) => this.vesselIconSize(isVesselHighlighted(vessel)),
      getColor: (vessel: VesselPosition) =>
        isVesselHighlighted(vessel)
          ? ([...VESSEL_HIGHLIGHT_RGB, 255] as any)
          : ([...this.vesselColor(vessel), 255] as any),
      sizeUnits: 'pixels',
      billboard: true,
      parameters: { depthTest: false },
      onClick: (info: any) => this.handleVesselClick(info?.object as VesselPosition | undefined, info),
    }));
    const labelFeatures = [
      ...(atlanticTrader ? [atlanticTrader] : []),
      ...highlightedVessels.filter((vessel) => !this.isAtlanticTrader(vessel)).slice(0, 3),
    ];
    if (labelFeatures.length) {
      layers.push(new TextLayer({
        id: 'sentinel-vessels-labels',
        data: labelFeatures,
        pickable: true,
        getPosition: (vessel: VesselPosition & { displayLon: number; displayLat: number }) =>
          [vessel.displayLon, vessel.displayLat],
        getText: (vessel: VesselPosition) =>
          this.isAtlanticTrader(vessel) ? 'MV ATLANTIC TRADER' : (vessel.name || vessel.mmsi || ''),
        getSize: this.isAtlanticTrader(labelFeatures[0]) ? 11 : (this.compact ? 9 : 10),
        getColor: (vessel: VesselPosition) =>
          this.isAtlanticTrader(vessel)
            ? ([212, 195, 255, 245] as any)
            : (this.isLightBasemap() ? [12, 36, 50, 240] : [248, 252, 255, 238]),
        getPixelOffset: [0, -16],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'bottom',
        fontSettings: { sdf: true, fontWeight: 700 },
        outlineColor: this.isLightBasemap() ? [255, 255, 255, 232] : [4, 8, 13, 240],
        outlineWidth: 3,
        billboard: true,
        parameters: { depthTest: false },
        onClick: (info: any) => this.handleVesselClick(info?.object as VesselPosition | undefined, info),
      }));
    }
  }

  private focusSelectedZone(): void {
    if (!this.mapInstance) return;
    const mapSystem = this.effectiveMapSystem;
    const preset = this.compact
      ? mapSystem?.['camera_presets']?.country
      : mapSystem?.['camera_presets']?.[this.selectedZoneId || 'country'];
    if (!preset) return;
    this.mapInstance.easeTo({
      center: [preset.longitude, preset.latitude],
      zoom: this.compact ? 5.15 : preset.zoom,
      pitch: 0,
      bearing: 0,
      duration: Math.max(0, Math.min(Number(preset.duration_ms || 260), 400)),
    });
    this.updateDeckLayers();
  }

  private emitDeckZone(zoneId: string | undefined): void {
    if (!zoneId) return;
    const zone = this.renderedZones.find((item) => item.id === zoneId);
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

  private deckColor(tone: string, selected = false, hovered = false, zoneId?: string, alphaBoost = 0): number[] {
    let alpha = this.zoneFillAlpha(tone) + alphaBoost;
    if (this.isOctocityMode) alpha = Math.round(alpha * 0.58);
    if (zoneId === 'zone-nord' || (tone === 'critical' && zoneId !== 'zone-sud')) {
      const pulse = 0.88 + 0.12 * Math.sin(this.zonePulsePhase * Math.PI * 2);
      alpha = Math.round(alpha * pulse);
    }
    if (selected) alpha = Math.min(255, alpha + 36);
    if (hovered) alpha = Math.min(255, alpha + 28);
    return [...this.zoneFillRgb(tone), Math.max(0, Math.min(255, alpha))];
  }

  private deckLineColor(tone: string, selected = false, hovered = false): number[] {
    if (this.isOctocityMode) {
      if (tone === 'critical') return [220, 38, 38, selected ? 210 : hovered ? 180 : 132];
      if (tone === 'watch' || tone === 'elevated' || tone === 'monitoring') return [217, 119, 6, selected ? 190 : hovered ? 160 : 118];
      return [22, 101, 52, selected ? 170 : hovered ? 140 : 108];
    }
    if (tone === 'critical') {
      const glow = selected ? 255 : hovered ? 220 : 200;
      return [248, 113, 113, glow];
    }
    const alpha = selected ? 120 : hovered ? 105 : ZONE_STROKE_ALPHA;
    return [ZONE_STROKE_RGB[0], ZONE_STROKE_RGB[1], ZONE_STROKE_RGB[2], alpha];
  }

  private zoneFillRgb(tone: string): [number, number, number] {
    if (tone === 'critical') return [220, 38, 38];
    if (tone === 'watch' || tone === 'elevated' || tone === 'monitoring') return [245, 158, 11];
    return [22, 101, 52];
  }

  private zoneFillAlpha(tone: string): number {
    if (this.isOctocityMode) {
      if (tone === 'critical') return Math.round(0.17 * 255);
      if (tone === 'watch' || tone === 'elevated' || tone === 'monitoring') return Math.round(0.14 * 255);
      return Math.round(0.11 * 255);
    }
    if (tone === 'critical') return Math.round(0.28 * 255);
    if (tone === 'watch' || tone === 'elevated' || tone === 'monitoring') return Math.round(0.20 * 255);
    return Math.round(0.18 * 255);
  }

  private startMapPulseAnimations(): void {
    if (this.previewMode) return;
    if (this.zonePulseTimer) clearInterval(this.zonePulseTimer);
    if (this.atlanticPulseTimer) clearInterval(this.atlanticPulseTimer);
    this.zonePulseTimer = setInterval(() => {
      this.zonePulsePhase = (this.zonePulsePhase + 0.34) % 1;
      this.updateDeckLayers();
    }, 3000);
    this.atlanticPulseTimer = setInterval(() => {
      this.atlanticPulsePhase = (this.atlanticPulsePhase + 0.5) % 1;
      this.updateDeckLayers();
    }, 2000);
  }

  private isAtlanticTrader(vessel: VesselPosition): boolean {
    return vessel.mmsi === ATLANTIC_TRADER_MMSI || /atlantic trader/i.test(vessel.name || '');
  }

  private atlanticHaloAlpha(): number {
    return Math.round(52 + 36 * Math.sin(this.atlanticPulsePhase * Math.PI * 2));
  }

  private atlanticHaloBoost(): number {
    return Math.round(6 + 5 * Math.sin(this.atlanticPulsePhase * Math.PI * 2));
  }

  private vesselIconSize(highlighted: boolean): number {
    const zoom = Number(this.mapInstance?.getZoom?.() || 6);
    const base = Math.max(12, Math.min(22, 3.5 + zoom * 1.05));
    return highlighted ? base + 3 : base;
  }

  private spreadVesselPositions(
    vessels: VesselPosition[],
  ): Array<VesselPosition & { displayLon: number; displayLat: number }> {
    const cells = new Map<string, number>();
    return vessels.map((vessel) => {
      const lon = Number(vessel.lon);
      const lat = Number(vessel.lat);
      const key = `${lon.toFixed(3)},${lat.toFixed(3)}`;
      const index = cells.get(key) || 0;
      cells.set(key, index + 1);
      const angle = index * 1.15;
      const offset = index ? 0.0024 * index : 0;
      return {
        ...vessel,
        displayLon: lon + offset * Math.cos(angle),
        displayLat: lat + offset * Math.sin(angle),
      };
    });
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
    const role = String(feature?.properties?.visual_role || feature?.properties?.render_tone || '');
    const corridor = role === 'maritime_corridor' || role === 'maritime_approach';
    if (this.isLightBasemap()) {
      return corridor ? [22, 163, 74, 180] : [62, 230, 138, 150];
    }
    return corridor ? [62, 230, 138, 210] : [62, 230, 138, 140];
  }

  private maritimeAreaLineColor(): number[] {
    if (this.isLightBasemap()) return [62, 230, 138, 72];
    return [62, 230, 138, 68];
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

  private vesselColor(vessel: VesselPosition): [number, number, number] {
    const kind = String(vessel?.vessel_type || 'other').toLowerCase();
    return VESSEL_TYPE_COLORS[kind] || VESSEL_TYPE_COLORS['other'];
  }

  private vesselIconAngle(vessel: VesselPosition): number {
    const bearing = Number.isFinite(Number(vessel?.heading))
      ? Number(vessel.heading)
      : Number.isFinite(Number(vessel?.cog))
        ? Number(vessel.cog)
        : 0;
    return -bearing;
  }

  private getVesselIconAtlas(): string {
    if (this.vesselIconAtlas) return this.vesselIconAtlas;
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, 128, 64);
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.moveTo(32, 10);
      ctx.lineTo(54, 52);
      ctx.lineTo(10, 52);
      ctx.closePath();
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(96, 12);
      ctx.lineTo(108, 32);
      ctx.lineTo(96, 52);
      ctx.lineTo(84, 32);
      ctx.closePath();
      ctx.fill();
    }
    this.vesselIconAtlas = canvas.toDataURL();
    return this.vesselIconAtlas;
  }

  openDemoPortWebcam(event?: Event): void {
    event?.stopPropagation();
    event?.preventDefault();
    const demoVessel = (this.vessels || []).find(
      (vessel) =>
        this.isAtlanticTrader(vessel)
        || vessel.linked_cargo_id === 'cargo-abidjan-supply-001',
    );
    if (demoVessel) {
      this.handleVesselClick(demoVessel);
      return;
    }
    window.dispatchEvent(
      new CustomEvent('agentium:assistant-show-webcam', {
        detail: {
          source_id: 'apm-apapa-gate-1',
          label: 'APM Apapa Gate Cam #1 (demo Abidjan)',
          cargo_id: 'cargo-abidjan-supply-001',
          vessel_mmsi: ATLANTIC_TRADER_MMSI,
          vessel_name: 'MV ATLANTIC TRADER',
        },
      }),
    );
  }

  private handleVesselClick(vessel: VesselPosition | undefined, info?: { stopPropagation?: () => void }): void {
    if (!vessel) return;
    info?.stopPropagation?.();
    this.briefOpen = false;
    this.hoveredZoneId = null;
    this.vesselSelected.emit(vessel);
    this.cdr.markForCheck();
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
    const raw = info?.object;
    if (!raw) return null;
    if (raw.mmsi || raw.vessel_type) {
      const vessel = raw as VesselPosition;
      const speedKn = Number.isFinite(Number(vessel.sog)) ? `${Math.round(Number(vessel.sog))} kn` : '';
      const typeLabel = String(vessel.vessel_type || 'navire');
      const meta = [typeLabel, speedKn].filter(Boolean).join(' · ');
      return {
        html: `
          <div class="sentinel-map-tooltip vessel">
            <strong>${this.escapeTooltip(vessel.name || vessel.mmsi)}</strong>
            ${meta ? `<small>${this.escapeTooltip(meta)}</small>` : ''}
          </div>
        `,
        style: this.tooltipStyle(),
      };
    }
    const properties = raw.properties || raw;
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
      style: this.tooltipStyle(),
    };
  }

  private tooltipStyle(): Record<string, string | number> {
    return {
      backgroundColor: 'rgba(10, 17, 24, 0.94)',
      border: '1px solid rgba(62, 230, 138, 0.28)',
      borderRadius: '8px',
      boxShadow: '0 14px 28px rgba(0,0,0,0.38)',
      color: '#f4f7fb',
      fontFamily: 'var(--mission-font-mono, Inter, system-ui, sans-serif)',
      fontSize: '11px',
      maxWidth: '240px',
      padding: '8px 10px',
      pointerEvents: 'none',
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
