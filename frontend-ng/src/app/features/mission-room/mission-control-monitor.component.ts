import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, type SafeResourceUrl } from '@angular/platform-browser';
import { ApiService } from '@app/core/api.service';
import type { VesselPosition } from '@app/core/maritime-tracking.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { WorkspaceMapComponent } from './workspace-map.component';

type TerrainMode = 'webcams' | 'maritime';

/** Demo port webcams — not always present in monitor.visual.sources (Abidjan.net only). */
const DEMO_PORT_WEBCAMS: Record<string, unknown>[] = [
  {
    id: 'apm-apapa-gate-1',
    name: 'APM Apapa Gate #1 · Port Vridi (demo)',
    description: 'Snapshot CCTV public APM Terminals Apapa — reference visuelle demo cargo Atlantic Trader.',
    source_url: '/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1',
    adapter: 'http_image',
    enabled: true,
    status: 'active',
    region: "Port d'Abidjan · Vridi",
    label_disclaimer: 'Reference visuelle demo Abidjan (source APM Apapa Lagos)',
    attribution: 'APM Terminals (Apapa) - snapshot public',
    metadata: {
      priority: -20,
      preview_url: '/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1',
      preferred_render: 'snapshot',
      kind: 'port_webcam',
      demo_badge: 'Port Vridi · cargo demo',
    },
  },
  {
    id: 'apm-apapa-gate-2',
    name: 'APM Apapa Gate #2 · Port Vridi (demo)',
    source_url: '/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-2',
    adapter: 'http_image',
    enabled: true,
    status: 'active',
    region: "Port d'Abidjan · Vridi",
    metadata: {
      priority: -19,
      preview_url: '/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-2',
      preferred_render: 'snapshot',
      kind: 'port_webcam',
    },
  },
  {
    id: 'paa-aerial-vue',
    name: 'PAA · vue aerienne (galerie officielle)',
    source_url: '/api/v1/mission-room/webcams/proxy?source_id=paa-aerial-vue',
    adapter: 'http_image',
    enabled: true,
    status: 'active',
    region: "Port d'Abidjan",
    metadata: {
      priority: -18,
      preview_url: '/api/v1/mission-room/webcams/proxy?source_id=paa-aerial-vue',
      preferred_render: 'snapshot',
      kind: 'port_webcam',
    },
  },
];

@Component({
  selector: 'app-mission-control-monitor',
  standalone: true,
  imports: [CommonModule, GlyphComponent, WorkspaceMapComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './mission-control-monitor.component.html',
  styleUrls: ['./mission-control-monitor.component.scss'],
})
export class MissionControlMonitorComponent implements OnInit, OnChanges, OnDestroy {
  private readonly sanitizer = inject(DomSanitizer);

  @Input() monitor: any | null = null;
  @Input() missionMap: any | null = null;
  @Input() selectedZone: any | null = null;
  @Input() mapCommandState: Record<string, unknown> | null = null;
  @Input() portWebcam: Record<string, unknown> | null = null;
  @Input() assistantName = 'AYA';
  @Input() captureImages: Record<string, string> = {};
  /** AIS vessel snapshot forwarded to the inner <app-workspace-map>. */
  @Input() vessels: VesselPosition[] | null = null;

  @Output() zoneSelected = new EventEmitter<any>();
  @Output() visualCapture = new EventEmitter<any>();
  @Output() assistantPrompt = new EventEmitter<string>();
  @Output() voiceRequest = new EventEmitter<void>();

  readonly abidjanClock = signal('');
  readonly visualSnapshotTick = signal(Date.now());
  readonly selectedVisualSourceId = signal<string | null>(null);
  readonly expandedVisualSourceId = signal<string | null>(null);
  readonly activePortWebcam = signal<any | null>(null);
  readonly activePortWebcamImageUrl = signal<string | null>(null);
  readonly mapVisualFocus = signal<Record<string, unknown> | null>(null);
  readonly activeEvidenceOverride = signal<any | null>(null);
  readonly visualPreviewFailures = signal<Record<string, true>>({});
  readonly selectedTerrainMode = signal<TerrainMode>('webcams');
  readonly decisionBannerOpen = signal(false);

  private readonly trustedVisualEmbeds = new Map<string, SafeResourceUrl>();
  private readonly api = inject(ApiService);
  private clockTimer: ReturnType<typeof setInterval> | null = null;
  private activePortWebcamObjectUrl: string | null = null;
  private readonly showWebcamListener = (event: Event) => {
    this.handleShowWebcamEvent(event as CustomEvent<Record<string, unknown>>);
  };

  ngOnInit(): void {
    this.refreshClock();
    this.clockTimer = setInterval(() => this.refreshClock(), 15_000);
    window.addEventListener('agentium:assistant-show-webcam', this.showWebcamListener);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['mapCommandState'] && this.hasMaritimeLayer(this.mapCommandState)) {
      this.selectedTerrainMode.set('maritime');
      this.activeEvidenceOverride.set(this.maritimeEvidence());
    }
    if (changes['portWebcam'] && this.portWebcam) {
      this.applyPortWebcamDetail(this.portWebcam);
    }
  }

  ngOnDestroy(): void {
    if (this.clockTimer) clearInterval(this.clockTimer);
    window.removeEventListener('agentium:assistant-show-webcam', this.showWebcamListener);
    if (this.activePortWebcamObjectUrl) URL.revokeObjectURL(this.activePortWebcamObjectUrl);
  }

  scenario(): any {
    return this.monitor?.scenario || {};
  }

  posture(): any {
    return this.monitor?.posture || {};
  }

  layers(): any[] {
    return this.monitor?.layers || [];
  }

  activeEvidence(): any {
    return this.activeEvidenceOverride()
      || this.monitor?.active_evidence
      || this.buildVisualEvidence(this.primaryVisualSource())
      || {};
  }

  activeEvidenceRefs(): any[] {
    return this.activeEvidence()?.evidence_refs || [];
  }

  activeEvidenceRows(): any[] {
    const evidence = this.activeEvidence();
    return [
      { label: 'Situation', value: evidence.observation || 'Preuve active en attente de selection.' },
      { label: 'Preuve', value: evidence.source_quality || 'Sources qualifiees' },
      { label: 'Decision', value: evidence.recommended_action || 'Qualifier puis arbitrer.' },
      { label: 'Deadline', value: evidence.decision_deadline || 'aujourd’hui' },
    ];
  }

  compactMissionFilters(): any[] {
    const layerCount = (key: string, fallback = 0) => Number(this.layers().find((layer) => layer.key === key)?.count ?? fallback);
    return [
      {
        label: 'Territoire',
        value: this.monitor?.zones?.length || 5,
        detail: 'Nord, Sud, Est, Ouest, Centre',
        kind: 'zone',
        zoneId: this.scenario()?.map_focus?.zone_id || 'zone-nord',
      },
      {
        label: 'Presse/Rumeurs',
        value: layerCount('open-intelligence', this.newsSignals().length || this.crossSignals().length),
        detail: 'Locale puis CEDEAO/Afrique/Monde',
        kind: 'signals',
      },
      {
        label: 'Flux terrain',
        value: (this.sourceHealth().active_sources || this.visualSources().length) + this.maritimeEvents().length,
        detail: this.selectedTerrainMode() === 'maritime' ? "Maritime / douanes" : this.selectedVisualLocationLabel(),
        kind: 'terrain',
      },
    ];
  }

  applyMissionFilter(filter: any): void {
    if (filter?.kind === 'terrain') {
      if (this.selectedTerrainMode() === 'maritime') {
        this.focusMaritimeEvidence();
      } else {
        const source = this.primaryVisualSource();
        if (source) this.selectVisualSource(source);
      }
      return;
    }
    if (filter?.kind === 'signals') {
      const signal = this.crossSignals().find((item) => item.type === 'press' || item.type === 'social') || this.crossSignals()[0];
      if (signal) this.focusSignal(signal);
      return;
    }
    const zoneId = filter?.zoneId;
    if (zoneId) {
      this.mapVisualFocus.set(null);
      const zone = (this.monitor?.zones || []).find((item: any) => item.id === zoneId);
      if (zone) this.activateZoneEvidence(zone);
    }
  }

  monitorMapState(): Record<string, unknown> | null {
    return this.mapVisualFocus()
      || this.activeEvidenceOverride()?.map_focus
      || this.mapCommandState
      || this.monitor?.active_evidence?.map_focus
      || null;
  }

  crossSignals(): any[] {
    return this.monitor?.cross_source_signals || [];
  }

  attentionItems(): any[] {
    return this.monitor?.attention_required || [];
  }

  decisionSentence(): any {
    return this.monitor?.decision_sentence || {
      text: 'Monsieur le Vice-Président, votre priorité absolue ce matin est la Zone Nord. Tout le reste peut attendre.',
      deadline: 'avant Conseil 15h00',
      generated_by: this.assistantName,
    };
  }

  territorialLiveStatus(): any[] {
    return this.monitor?.territorial_live_status || [];
  }

  decisionPackages(): any[] {
    return this.monitor?.executive_decision_packages || [];
  }

  primaryDecisionPackage(): any {
    return this.decisionPackages()[0] || null;
  }

  rumorTrace(): any {
    return this.monitor?.rumor_trace || this.monitor?.voice_context?.rumor_trace || null;
  }

  demoValueMetrics(): any[] {
    return this.monitor?.demo_value_metrics || [];
  }

  presentationBeats(): any[] {
    return this.monitor?.presentation_beats || this.monitor?.voice_context?.presentation_beats || [];
  }

  newsSignals(): any[] {
    return this.monitor?.news_signals || [];
  }

  maritimeIntelligence(): any {
    return this.monitor?.maritime || this.monitor?.news?.maritime_intelligence || {};
  }

  maritimeEvents(): any[] {
    return this.maritimeIntelligence()?.vessel_events || [];
  }

  primaryMaritimeEvent(): any | null {
    return this.maritimeEvents()[0] || null;
  }

  maritimePrompts(): string[] {
    return this.maritimeIntelligence()?.prompts || [
      "AYA, quel est le risque autour du port d'Abidjan ?",
      "AYA, relie cette actualite douanes au trafic maritime.",
    ];
  }

  maritimeEvidence(): any {
    const direct = this.maritimeIntelligence()?.active_evidence;
    if (direct) return direct;
    const observation = this.maritimeIntelligence()?.latest_observation || {};
    return {
      id: 'active-maritime-customs-watch',
      type: 'maritime',
      title: "Maritime / douanes · Port d'Abidjan",
      location: "Port autonome d'Abidjan / Golfe de Guinee",
      score: observation.score || 58,
      severity: observation.severity || 'monitoring',
      source_quality: 'RSS portuaire + veille maritime',
      observation: observation.summary || "Signal maritime a rapprocher des douanes, de la securite portuaire et de l'agenda economique.",
      recommended_action: observation.recommended_action || 'Verifier Port + Douanes avant communication publique.',
      decision_deadline: observation.decision_deadline || "aujourd'hui",
      evidence_refs: observation.evidence_refs || [],
      aya_context: observation.aya_context,
      map_focus: observation.map_focus,
    };
  }

  agendaItems(): any[] {
    return this.monitor?.agenda || [];
  }

  actionItems(): any[] {
    return this.monitor?.action_items || [];
  }

  voicePrompts(): string[] {
    const prompts = this.monitor?.voice_context?.prompts || [
      'AYA, donne-moi la synthese du scenario croise.',
      'AYA, ouvre la camera Pont General-de-Gaulle.',
      'AYA, filtre la carte sur Abidjan.',
    ];
    const maritime = this.maritimePrompts();
    const ordered = this.selectedTerrainMode() === 'maritime'
      ? [...maritime, ...prompts]
      : [...prompts.slice(0, 6), ...maritime.slice(0, 2)];
    return ordered.filter((prompt, index, all) => all.indexOf(prompt) === index).slice(0, 8);
  }

  sourceHealth(): any {
    return this.monitor?.visual?.source_health || {};
  }

  panelCount(region: string): number {
    return (this.monitor?.panel_layout || []).filter((panel: any) => panel.region === region && panel.visible !== false).length;
  }

  postureTone(level?: string | null): string {
    const normalized = String(level || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'high') return 'elevated';
    if (normalized === 'stable') return 'stable';
    return 'monitoring';
  }

  postureLabel(): string {
    const posture = this.posture();
    return `${posture.label || 'monitoring'} · ${posture.score || 0}/100`;
  }

  confidencePct(value?: number): string {
    const confidence = typeof value === 'number' ? value : 0.62;
    return `${Math.round(Math.max(0, Math.min(confidence, 1)) * 100)}%`;
  }

  visualSources(): any[] {
    const backend = [...(this.monitor?.visual?.sources || [])];
    const ids = new Set(backend.map((source) => source?.id).filter(Boolean));
    const injected = DEMO_PORT_WEBCAMS.filter((source) => !ids.has(source['id']));
    return [...injected, ...backend].sort((a, b) => this.visualPriority(a) - this.visualPriority(b));
  }

  isDemoPortWebcam(source: any): boolean {
    const id = String(source?.id || '');
    return id.startsWith('apm-apapa') || id.startsWith('paa-');
  }

  demoPortBadge(source: any): string | null {
    const badge = (source?.metadata || {}).demo_badge;
    if (typeof badge === 'string' && badge.trim()) return badge.trim();
    if (this.isDemoPortWebcam(source)) return 'Port Vridi · cargo demo';
    return null;
  }

  primaryVisualSource(): any | null {
    const sources = this.visualSources();
    const selectedId = this.selectedVisualSourceId();
    const selected = selectedId ? sources.find((source) => source.id === selectedId) : null;
    return selected || sources.find((source) => source.enabled && source.status === 'active') || sources[0] || null;
  }

  selectVisualSource(source: any): void {
    if (!source) return;
    this.selectedTerrainMode.set('webcams');
    if (source.id) this.selectedVisualSourceId.set(source.id);
    this.focusVisualSourceOnMap(source);
    const evidence = this.buildVisualEvidence(source);
    if (evidence) this.activeEvidenceOverride.set(evidence);
  }

  focusPrimaryVisualSource(): void {
    const source = this.primaryVisualSource();
    if (source) this.selectVisualSource(source);
  }

  openExpandedVisualSource(source: any): void {
    if (!source?.id) return;
    this.selectVisualSource(source);
    this.expandedVisualSourceId.set(source.id);
  }

  private handleShowWebcamEvent(event: CustomEvent<Record<string, unknown>>): void {
    this.applyPortWebcamDetail(event?.detail || {});
  }

  private applyPortWebcamDetail(detail: Record<string, unknown>): void {
    const sourceId = String(detail['source_id'] || '').trim();
    if (!sourceId) return;
    const known = this.visualSources().find((source) => source.id === sourceId);
    const proxyUrl = String(
      detail['proxy_url']
        || (known?.metadata || {}).preview_url
        || known?.source_url
        || `/api/v1/mission-room/webcams/proxy?source_id=${sourceId}`,
    );
    const name = String(detail['label'] || known?.name || sourceId);
    this.activePortWebcam.set({
      ...(known || {}),
      id: sourceId,
      name,
      proxy_url: proxyUrl,
      adapter: known?.adapter || 'http_image',
      source_url: known?.source_url || proxyUrl,
      attribution: detail['attribution'] || known?.attribution,
      label_disclaimer: detail['label_disclaimer'] || known?.label_disclaimer,
      metadata: {
        ...(known?.metadata || {}),
        preview_url: proxyUrl,
        preferred_render: 'snapshot',
      },
    });
    this.selectedVisualSourceId.set(sourceId);
    this.selectedTerrainMode.set('maritime');
    this.activeEvidenceOverride.set(this.maritimeEvidence());
    this.loadPortWebcamPreview(proxyUrl);
  }

  closeExpandedVisualSource(): void {
    this.expandedVisualSourceId.set(null);
  }

  setTerrainMode(mode: TerrainMode): void {
    this.selectedTerrainMode.set(mode);
    if (mode === 'maritime') {
      this.focusMaritimeEvidence();
      return;
    }
    this.activeEvidenceOverride.set(null);
    this.focusPrimaryVisualSource();
  }

  isTerrainMode(mode: TerrainMode): boolean {
    return this.selectedTerrainMode() === mode;
  }

  private hasMaritimeLayer(state: Record<string, unknown> | null): boolean {
    const layers = state?.['active_layers'];
    return Array.isArray(layers) && layers.map(String).includes('maritime-traffic');
  }

  toggleDecisionBanner(): void {
    this.decisionBannerOpen.set(!this.decisionBannerOpen());
  }

  focusMaritimeEvidence(): void {
    const evidence = this.maritimeEvidence();
    this.selectedTerrainMode.set('maritime');
    this.activeEvidenceOverride.set(evidence);
    this.mapVisualFocus.set(evidence.map_focus || {
      active_layers: ['territorial-risk', 'open-intelligence', 'visual-streams', 'maritime-traffic'],
      camera: { longitude: -4.0083, latitude: 5.2512, zoom: 9.15, duration_ms: 220 },
      focus_marker: {
        longitude: -4.0083,
        latitude: 5.2512,
        label: "Port d'Abidjan · maritime",
        zone_id: 'zone-sud',
        tone: 'maritime',
      },
    });
  }

  expandedVisualSource(): any | null {
    const sourceId = this.expandedVisualSourceId();
    return sourceId ? this.visualSources().find((source) => source.id === sourceId) || null : null;
  }

  isVisualSourceSelected(source: any): boolean {
    return this.primaryVisualSource()?.id === source.id;
  }

  visualEmbedUrl(source: any | null): SafeResourceUrl | null {
    if (!source) return null;
    const metadata = source.metadata || {};
    if (metadata.preferred_render === 'snapshot' || metadata.embed_status === 'unstable') return null;
    const rawUrl = this.visualMetadataUrl(source, 'embed_url') || this.visualMetadataUrl(source, 'player_url');
    const url = this.trustedVisualEmbedUrl(rawUrl);
    if (!url) return null;
    const cacheKey = `${source.id}:${url}`;
    const cached = this.trustedVisualEmbeds.get(cacheKey);
    if (cached) return cached;
    const trusted = this.sanitizer.bypassSecurityTrustResourceUrl(url);
    this.trustedVisualEmbeds.set(cacheKey, trusted);
    return trusted;
  }

  webcamPreviewUrl(source: any | null): string | null {
    if (!source || this.visualPreviewFailures()[source.id]) return null;
    const metadata = source.metadata || {};
    const preview = typeof metadata.preview_url === 'string' ? metadata.preview_url : '';
    const url = preview.startsWith('http://') || preview.startsWith('https://')
      ? preview
      : source.adapter === 'http_image' && source.source_url?.startsWith('http')
        ? source.source_url
        : '';
    if (url) return this.withSnapshotCacheBust(url);
    return null;
  }

  portWebcamPreviewUrl(source: any | null): string | null {
    if (!source) return null;
    const objectUrl = this.activePortWebcamImageUrl();
    if (objectUrl) return objectUrl;
    const direct = typeof source.proxy_url === 'string' ? source.proxy_url : '';
    if (direct) return this.withRelativeSnapshotCacheBust(direct);
    return this.webcamPreviewUrl(source);
  }

  visualSourcePageUrl(source: any | null): string | null {
    const url = this.visualMetadataUrl(source, 'source_page');
    return url.startsWith('https://') ? url : null;
  }

  visualStreamBadge(source: any | null): string {
    const metadata = source?.metadata || {};
    if (metadata.preferred_render === 'snapshot') return 'Image publique rafraichie · fallback stable';
    if (metadata.embed_status === 'unstable') return 'Embed video instable · aperçu prioritaire';
    return 'Flux public';
  }

  markVisualPreviewFailed(sourceId: string): void {
    if (!sourceId || this.visualPreviewFailures()[sourceId]) return;
    this.visualPreviewFailures.update((failures) => ({ ...failures, [sourceId]: true }));
  }

  latestVisualObservation(): any | null {
    return this.monitor?.visual?.latest_observation || this.monitor?.visual_observations?.[0] || null;
  }

  latestVisualCapture(): any | null {
    return (this.monitor?.visual?.captures || []).find((capture: any) => capture.status === 'analyzed' || capture.status === 'captured') || null;
  }

  visualCaptureImage(captureId: string): string | null {
    return this.captureImages[captureId] || null;
  }

  visualSourceDetail(source: any): string {
    const metadata = source?.metadata || {};
    const provider = typeof metadata.provider === 'string' ? metadata.provider : source?.adapter;
    const mode = typeof metadata.stream_kind === 'string'
      ? metadata.stream_kind.replace(/_/g, ' ')
      : typeof metadata.layer_kind === 'string'
        ? metadata.layer_kind.replace(/_/g, ' ')
        : source?.source_type;
    const refresh = Number(metadata.refresh_seconds || 0);
    const refreshLabel = refresh ? `maj ~${refresh}s` : `cadence ${source?.capture_cadence_minutes || 60} min`;
    return `${provider || 'source'} · ${mode || 'live'} · ${refreshLabel}`;
  }

  selectedVisualLocationLabel(): string {
    return this.visualLocationLabel(this.primaryVisualSource());
  }

  visualLocationLabel(source: any | null): string {
    const location = this.visualLocation(source);
    return location?.label || source?.region || 'Cote d’Ivoire';
  }

  visualSituationBrief(source: any | null): any[] {
    const observation = this.visualObservationFor(source);
    const score = Number(observation?.vigilance_score || source?.metadata?.default_vigilance_score || 42);
    const visualBrief = this.visualIntelligenceBrief();
    const summary = observation?.summary
      || `Vue publique ${this.visualLocationLabel(source)} disponible pour controle visuel sans dependance a l'embed Nest.`;
    const action = score >= 62
      ? 'Rapprocher cette vue des signaux presse et demander validation terrain.'
      : visualBrief?.recommended_next_step || "Maintenir en surveillance live et capturer un snapshot si l'actualite converge.";
    return [
      { label: 'Lecture', value: summary },
      { label: 'Position', value: this.visualLocationLabel(source) },
      { label: 'Qualite', value: this.visualSourceQualityLabel(source) },
      { label: 'Croisement', value: this.visualBriefingValue() },
      { label: 'Action', value: action },
    ];
  }

  visualIntelligenceBrief(): any {
    return this.monitor?.visual_intelligence_brief || this.monitor?.voice_context?.visual_intelligence_brief || {};
  }

  visualSourceQualityLabel(source: any | null): string {
    const metadata = source?.metadata || {};
    return metadata.resolution_label || this.visualIntelligenceBrief()?.source_quality?.label || 'Basse resolution publique';
  }

  visualSourceQualityDetail(source: any | null): string {
    const metadata = source?.metadata || {};
    return metadata.native_resolution_hint
      || this.visualIntelligenceBrief()?.source_quality?.native_resolution_hint
      || "Source publique utile pour contexte macro, insuffisante pour preuve detaillee.";
  }

  visualBriefingValue(): string {
    const brief = this.visualIntelligenceBrief();
    if (brief?.latest_reading?.available) return 'Observation exploitable dans le brief AYA.';
    return brief?.question_answered || 'Contexte visuel a croiser avant recommandation.';
  }

  visualTranscriptionValue(): string {
    return this.visualIntelligenceBrief()?.transcription?.label || 'Lecture visuelle, pas transcription audio';
  }

  activatePrompt(prompt: string): void {
    this.assistantPrompt.emit(prompt);
  }

  sendActiveEvidenceToAya(): void {
    const evidence = this.activeEvidence();
    const prompt = evidence?.aya_context?.prompt
      || `AYA, explique cette preuve active : ${evidence?.title || 'signal prioritaire'}.`;
    this.assistantPrompt.emit(prompt);
  }

  prepareActiveEvidenceArbitrage(): void {
    const evidence = this.activeEvidence();
    const prompt = `AYA, prepare un arbitrage VP pour ${evidence?.title || 'la preuve active'} avec option recommandee et deadline.`;
    this.assistantPrompt.emit(prompt);
  }

  activateDecisionPackage(pack: any): void {
    if (!pack) return;
    this.assistantPrompt.emit(`AYA, prepare le dossier de decision suivant : ${pack.title}. ${pack.decision}`);
  }

  focusSignal(signal: any): void {
    const zoneId = signal?.related_zone || this.scenario()?.map_focus?.zone_id;
    const zone = (this.monitor?.zones || []).find((item: any) => item.id === zoneId);
    this.mapVisualFocus.set(null);
    if (zone) this.zoneSelected.emit(zone);
    this.activeEvidenceOverride.set(this.buildSignalEvidence(signal));
  }

  handleZoneSelected(zone: any): void {
    this.activateZoneEvidence(zone);
  }

  handleMapEvidenceAction(event: any): void {
    const zone = event?.zone;
    if (event?.action === 'maritime') {
      this.selectedTerrainMode.set('maritime');
      const brief = zone?.popup_brief || {};
      this.activeEvidenceOverride.set({
        ...this.maritimeEvidence(),
        id: `maritime-${zone?.id || 'active'}`,
        title: brief.title || zone?.name || this.maritimeEvidence().title,
        score: brief.score || zone?.level || this.maritimeEvidence().score,
        severity: brief.severity || zone?.tone || this.maritimeEvidence().severity,
        observation: (brief.drivers || zone?.signals || [this.maritimeEvidence().observation]).filter(Boolean).join(' · '),
        recommended_action: brief.recommendation || this.maritimeEvidence().recommended_action,
        decision_deadline: brief.decision_deadline || this.maritimeEvidence().decision_deadline,
        map_focus: brief.map_focus || this.maritimeEvidence().map_focus,
      });
      if (brief.map_focus) this.mapVisualFocus.set(brief.map_focus);
      return;
    }
    if (zone) this.activateZoneEvidence(zone);
    if (event?.action === 'aya') {
      const prompt = zone?.popup_brief?.aya_context?.prompt || `AYA, donne-moi le brief operationnel pour ${zone?.name || 'la zone selectionnee'}.`;
      this.assistantPrompt.emit(prompt);
      return;
    }
    if (event?.action === 'arbitrage') this.prepareActiveEvidenceArbitrage();
  }

  focusAbidjan(): void {
    this.mapVisualFocus.set(null);
    const zone = (this.monitor?.zones || []).find((item: any) => String(item.name || '').toLowerCase().includes('abidjan'))
      || (this.monitor?.zones || []).find((item: any) => String(item.name || '').toLowerCase() === 'sud');
    if (zone) this.activateZoneEvidence(zone);
  }

  requestVoice(): void {
    this.voiceRequest.emit();
  }

  private refreshClock(): void {
    const value = new Intl.DateTimeFormat('fr-FR', {
      timeZone: 'Africa/Abidjan',
      weekday: 'short',
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date());
    this.abidjanClock.set(value.replace(',', ' ·'));
    this.visualSnapshotTick.set(Date.now());
  }

  private withSnapshotCacheBust(rawUrl: string): string {
    try {
      const url = new URL(rawUrl);
      url.searchParams.set('_mc', String(Math.floor(this.visualSnapshotTick() / 60_000)));
      return url.toString();
    } catch {
      return rawUrl;
    }
  }

  private withRelativeSnapshotCacheBust(rawUrl: string): string {
    if (!rawUrl) return '';
    if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
      return this.withSnapshotCacheBust(rawUrl);
    }
    const separator = rawUrl.includes('?') ? '&' : '?';
    return `${rawUrl}${separator}_mc=${Math.floor(this.visualSnapshotTick() / 60_000)}`;
  }

  private loadPortWebcamPreview(rawUrl: string): void {
    const path = rawUrl.startsWith('/api/v1') ? rawUrl.slice('/api/v1'.length) : rawUrl;
    if (!path.startsWith('/mission-room/webcams/proxy')) {
      this.activePortWebcamImageUrl.set(this.withRelativeSnapshotCacheBust(rawUrl));
      return;
    }
    this.api.getBlob(path).subscribe({
      next: (blob) => {
        if (this.activePortWebcamObjectUrl) URL.revokeObjectURL(this.activePortWebcamObjectUrl);
        this.activePortWebcamObjectUrl = URL.createObjectURL(blob);
        this.activePortWebcamImageUrl.set(this.activePortWebcamObjectUrl);
      },
      error: () => this.activePortWebcamImageUrl.set(this.withRelativeSnapshotCacheBust(rawUrl)),
    });
  }

  private visualPriority(source: any): number {
    const value = Number((source?.metadata || {}).priority);
    return Number.isFinite(value) ? value : 999;
  }

  private visualMetadataUrl(source: any, key: string): string {
    const value = (source?.metadata || {})[key];
    return typeof value === 'string' ? value : '';
  }

  private visualObservationFor(source: any | null): any | null {
    const observations = [
      ...(this.monitor?.visual?.observations || []),
      ...(this.monitor?.visual_observations || []),
    ];
    const sourceId = source?.id;
    return (sourceId ? observations.find((observation: any) => observation.source_id === sourceId) : null)
      || this.latestVisualObservation();
  }

  private activateZoneEvidence(zone: any): void {
    if (!zone) return;
    this.zoneSelected.emit(zone);
    const brief = zone.popup_brief || {};
    this.activeEvidenceOverride.set({
      id: `zone-${zone.id}`,
      type: 'zone',
      title: brief.title || `${zone.name} · brief operationnel`,
      location: zone.name,
      score: brief.score ?? zone.level,
      severity: brief.severity || zone.tone || 'monitoring',
      source_quality: (brief.sources || zone.sources || []).slice(0, 2).join(' · ') || 'Sources territoriales',
      observation: (brief.drivers || zone.signals || []).slice(0, 3).join(' · '),
      recommended_action: brief.recommendation || zone.recommendations?.[0] || 'Preparer arbitrage.',
      decision_deadline: brief.decision_deadline || 'aujourd’hui',
      evidence_refs: (brief.sources || zone.sources || []).map((source: string) => ({ type: 'source', id: source, label: source })),
      aya_context: brief.aya_context,
      map_focus: brief.map_focus,
    });
  }

  private buildSignalEvidence(signal: any): any {
    if (!signal) return {};
    return {
      id: `signal-${signal.id || 'active'}`,
      type: signal.type || 'signal',
      title: signal.label || 'Signal prioritaire',
      location: signal.related_zone || this.scenario()?.focus_zone || 'Cote d’Ivoire',
      score: signal.score || 0,
      severity: signal.severity || 'monitoring',
      source_quality: (signal.evidence_refs || []).map((item: any) => item.label).filter(Boolean).slice(0, 2).join(' · ') || 'Preuves corrélées',
      observation: signal.summary,
      recommended_action: signal.action_prompt,
      decision_deadline: signal.decision_deadline,
      evidence_refs: signal.evidence_refs || [],
      aya_context: signal.aya_context,
      map_focus: signal.map_focus,
    };
  }

  private buildVisualEvidence(source: any | null): any | null {
    if (!source) return null;
    const observation = this.visualObservationFor(source);
    const location = this.visualLocation(source);
    const brief = this.visualIntelligenceBrief();
    return {
      id: `visual-${source.id}`,
      type: 'webcam',
      title: source.name || 'Live webcam',
      location: this.visualLocationLabel(source),
      score: Number(observation?.vigilance_score || source?.metadata?.default_vigilance_score || 42),
      severity: 'monitoring',
      source_quality: this.visualSourceQualityLabel(source),
      observation: observation?.summary || `Vue publique ${this.visualLocationLabel(source)} disponible pour contexte terrain macro.`,
      recommended_action: brief?.recommended_next_step || "Capturer un snapshot et croiser avec presse, carte et agenda.",
      decision_deadline: 'avant prochain point cabinet',
      evidence_refs: [
        { type: 'webcam', id: source.id, label: source.name },
        { type: 'location', id: location?.zone_id, label: this.visualLocationLabel(source) },
      ],
      aya_context: {
        prompt: `AYA, analyse la webcam ${source.name} et croise-la avec presse, carte et agenda.`,
        answer_frame: 'Observation visuelle, limites source, correlation, action recommandee.',
        confidence: observation?.confidence || 0.62,
      },
      map_focus: location ? {
        camera: {
          longitude: location.longitude,
          latitude: location.latitude,
          zoom: location.zoom || 10.9,
          duration_ms: 220,
        },
        focus_marker: {
          longitude: location.longitude,
          latitude: location.latitude,
          label: location.label,
          zone_id: location.zone_id,
          tone: 'visual',
        },
        active_layers: ['territorial-risk', 'open-intelligence', 'visual-streams'],
        basemap: 'administrative',
      } : null,
    };
  }

  private visualLocation(source: any | null): { longitude: number; latitude: number; label: string; zone_id?: string; zoom?: number } | null {
    const metadata = source?.metadata || {};
    const location = metadata.map_location || metadata.location || {};
    const longitude = Number(location.longitude ?? metadata.longitude);
    const latitude = Number(location.latitude ?? metadata.latitude);
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return null;
    return {
      longitude,
      latitude,
      label: String(location.label || metadata.camera_label || source?.region || source?.name || 'Flux visuel'),
      zone_id: typeof location.zone_id === 'string' ? location.zone_id : metadata.zone_id,
      zoom: Number(location.zoom || metadata.map_zoom || 10.9),
    };
  }

  private focusVisualSourceOnMap(source: any): void {
    const location = this.visualLocation(source);
    if (!location) return;
    this.mapVisualFocus.set({
      camera: {
        longitude: location.longitude,
        latitude: location.latitude,
        zoom: location.zoom || 10.9,
        duration_ms: 220,
      },
      focus_marker: {
        longitude: location.longitude,
        latitude: location.latitude,
        label: location.label,
        zone_id: location.zone_id,
        tone: 'visual',
      },
    });
  }

  private trustedVisualEmbedUrl(rawUrl: string): string | null {
    const normalized = rawUrl.startsWith('//') ? `https:${rawUrl}` : rawUrl;
    try {
      const url = new URL(normalized);
      if (url.protocol !== 'https:' || url.hostname !== 'video.nest.com') return null;
      return url.toString();
    } catch {
      return null;
    }
  }
}
