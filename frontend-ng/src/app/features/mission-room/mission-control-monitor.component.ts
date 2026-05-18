import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnDestroy, OnInit, Output, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, type SafeResourceUrl } from '@angular/platform-browser';
import { Subscription } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { VoiceSessionConnection, VoiceSessionEvent, VoiceSessionService } from '@app/core/voice-session.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { WorkspaceMapComponent } from './workspace-map.component';

type VoiceState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking' | 'error';

@Component({
  selector: 'app-mission-control-monitor',
  standalone: true,
  imports: [CommonModule, GlyphComponent, WorkspaceMapComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './mission-control-monitor.component.html',
  styleUrls: ['./mission-control-monitor.component.scss'],
})
export class MissionControlMonitorComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly voiceSession = inject(VoiceSessionService);

  @Input() monitor: any | null = null;
  @Input() missionMap: any | null = null;
  @Input() selectedZone: any | null = null;
  @Input() mapCommandState: Record<string, unknown> | null = null;
  @Input() assistantName = 'AYA';
  @Input() captureImages: Record<string, string> = {};

  @Output() zoneSelected = new EventEmitter<any>();
  @Output() visualCapture = new EventEmitter<any>();
  @Output() assistantPrompt = new EventEmitter<string>();

  readonly abidjanClock = signal('');
  readonly visualSnapshotTick = signal(Date.now());
  readonly selectedVisualSourceId = signal<string | null>(null);
  readonly expandedVisualSourceId = signal<string | null>(null);
  readonly mapVisualFocus = signal<Record<string, unknown> | null>(null);
  readonly visualPreviewFailures = signal<Record<string, true>>({});
  readonly voiceState = signal<VoiceState>('idle');
  readonly voiceTranscript = signal('');
  readonly voiceAnswer = signal('');
  readonly voiceNotice = signal('Pret pour consigne vocale');

  private readonly trustedVisualEmbeds = new Map<string, SafeResourceUrl>();
  private clockTimer: ReturnType<typeof setInterval> | null = null;
  private voiceConnection: VoiceSessionConnection | null = null;
  private voiceSubscription: Subscription | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private mediaStream: MediaStream | null = null;
  private voiceTurnId: string | null = null;
  private pendingVoiceFrames: Promise<void>[] = [];
  private activeAudio: HTMLAudioElement | null = null;
  private activeAudioUrl: string | null = null;
  private speechSubscription: Subscription | null = null;
  private voiceFallbackTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnInit(): void {
    this.refreshClock();
    this.clockTimer = setInterval(() => this.refreshClock(), 15_000);
  }

  ngOnDestroy(): void {
    if (this.clockTimer) clearInterval(this.clockTimer);
    this.stopVoiceSession();
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

  compactMissionFilters(): any[] {
    const layerCount = (key: string, fallback = 0) => Number(this.layers().find((layer) => layer.key === key)?.count ?? fallback);
    return [
      {
        label: 'Territoire CI',
        value: this.monitor?.zones?.length || 5,
        detail: 'Nord, Sud, Est, Ouest, Centre',
        kind: 'zone',
        zoneId: this.scenario()?.map_focus?.zone_id || 'zone-nord',
      },
      {
        label: 'Presse & rumeurs',
        value: layerCount('open-intelligence', this.newsSignals().length || this.crossSignals().length),
        detail: 'Locale puis CEDEAO/Afrique/Monde',
        kind: 'signals',
      },
      {
        label: 'Flux visuels',
        value: this.sourceHealth().active_sources || this.visualSources().length,
        detail: this.selectedVisualLocationLabel(),
        kind: 'visual',
      },
    ];
  }

  applyMissionFilter(filter: any): void {
    if (filter?.kind === 'visual') {
      const source = this.primaryVisualSource();
      if (source) this.selectVisualSource(source);
      return;
    }
    const zoneId = filter?.zoneId;
    if (zoneId) {
      this.mapVisualFocus.set(null);
      const zone = (this.monitor?.zones || []).find((item: any) => item.id === zoneId);
      if (zone) this.zoneSelected.emit(zone);
    }
  }

  monitorMapState(): Record<string, unknown> | null {
    return this.mapVisualFocus() || this.mapCommandState;
  }

  crossSignals(): any[] {
    return this.monitor?.cross_source_signals || [];
  }

  attentionItems(): any[] {
    return this.monitor?.attention_required || [];
  }

  decisionSentence(): any {
    return this.monitor?.decision_sentence || {
      text: 'M. le Vice-Président, votre priorité absolue ce matin est la Zone Nord. Tout le reste peut attendre.',
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

  agendaItems(): any[] {
    return this.monitor?.agenda || [];
  }

  actionItems(): any[] {
    return this.monitor?.action_items || [];
  }

  voicePrompts(): string[] {
    return this.monitor?.voice_context?.prompts || [
      'AYA, donne-moi la synthese du scenario croise.',
      'AYA, ouvre la camera Pont General-de-Gaulle.',
      'AYA, filtre la carte sur Abidjan.',
    ];
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
    return [...(this.monitor?.visual?.sources || [])].sort((a, b) => this.visualPriority(a) - this.visualPriority(b));
  }

  primaryVisualSource(): any | null {
    const sources = this.visualSources();
    const selectedId = this.selectedVisualSourceId();
    const selected = selectedId ? sources.find((source) => source.id === selectedId) : null;
    return selected || sources.find((source) => source.enabled && source.status === 'active') || sources[0] || null;
  }

  selectVisualSource(source: any): void {
    if (!source) return;
    if (source.id) this.selectedVisualSourceId.set(source.id);
    this.focusVisualSourceOnMap(source);
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

  closeExpandedVisualSource(): void {
    this.expandedVisualSourceId.set(null);
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
    const summary = observation?.summary
      || `Vue publique ${this.visualLocationLabel(source)} disponible pour controle visuel sans dependance a l'embed Nest.`;
    const action = score >= 62
      ? 'Rapprocher cette vue des signaux presse et demander validation terrain.'
      : "Maintenir en surveillance live et capturer un snapshot si l'actualite converge.";
    return [
      { label: 'Lecture', value: summary },
      { label: 'Position', value: this.visualLocationLabel(source) },
      { label: 'Action', value: action },
    ];
  }

  activatePrompt(prompt: string): void {
    this.assistantPrompt.emit(prompt);
  }

  activateDecisionPackage(pack: any): void {
    if (!pack) return;
    this.voiceAnswer.set(`${pack.decision} Option recommandee : ${pack.recommended_option}. Echeance : ${pack.deadline}.`);
    this.assistantPrompt.emit(`AYA, prepare le dossier de decision suivant : ${pack.title}. ${pack.decision}`);
  }

  focusSignal(signal: any): void {
    const zoneId = signal?.related_zone || this.scenario()?.map_focus?.zone_id;
    const zone = (this.monitor?.zones || []).find((item: any) => item.id === zoneId);
    this.mapVisualFocus.set(null);
    if (zone) this.zoneSelected.emit(zone);
    if (signal?.summary) {
      this.voiceAnswer.set(`${signal.label || 'Signal prioritaire'} : ${signal.summary}`);
    }
  }

  focusAbidjan(): void {
    this.mapVisualFocus.set(null);
    const zone = (this.monitor?.zones || []).find((item: any) => String(item.name || '').toLowerCase().includes('abidjan'))
      || (this.monitor?.zones || []).find((item: any) => String(item.name || '').toLowerCase() === 'sud');
    if (zone) this.zoneSelected.emit(zone);
  }

  async toggleVoice(): Promise<void> {
    if (this.voiceState() === 'listening') {
      await this.finishVoiceTurn();
      return;
    }
    if (this.voiceState() === 'connecting' || this.voiceState() === 'thinking' || this.voiceState() === 'speaking') {
      this.stopVoiceSession();
      return;
    }
    await this.startVoiceSession();
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

  private async startVoiceSession(): Promise<void> {
    this.voiceState.set('connecting');
    this.voiceNotice.set('Ouverture du canal voix AYA');
    this.voiceTranscript.set('');
    try {
      const sessionId = `sentinel-ci-mission-control-${Date.now()}`;
      this.voiceTurnId = crypto.randomUUID?.() || sessionId;
      this.voiceConnection = this.voiceSession.open(sessionId);
      this.voiceSubscription = this.voiceConnection.events$.subscribe((event) => this.handleVoiceEvent(event));
      this.voiceConnection.start({
        runtime: 'cascade_openai',
        provider: 'cascade_openai',
        transport: 'backend_ws',
        language: 'fr',
        output_language: 'fr',
        capability: 'voice2voice_interaction',
        context_id: this.monitor?.workspace?.id || 'sentinel-ci',
        mode: 'conversation_only',
        codec: { input: 'webm', channels: 1 },
        tandem_oracle: true,
      });
      this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = this.preferredMimeType();
      this.mediaRecorder = mimeType
        ? new MediaRecorder(this.mediaStream, { mimeType })
        : new MediaRecorder(this.mediaStream);
      this.mediaRecorder.ondataavailable = (event) => {
        if (!event.data?.size || !this.voiceConnection) return;
        const send = this.voiceConnection.sendAudioFrame(event.data, {
          turn_id: this.voiceTurnId,
          content_type: event.data.type || mimeType || 'audio/webm',
        }).catch(() => {
          this.voiceNotice.set("Une trame audio n'a pas ete envoyee ; nouvelle tentative possible.");
        });
        this.pendingVoiceFrames.push(send);
        void send.finally(() => {
          this.pendingVoiceFrames = this.pendingVoiceFrames.filter((item) => item !== send);
        });
      };
      this.mediaRecorder.start(1000);
      this.voiceState.set('listening');
      this.voiceNotice.set('AYA ecoute la Mission Control Room. Cliquez pour envoyer.');
    } catch {
      this.voiceState.set('error');
      this.voiceNotice.set('Micro ou canal voix indisponible. Bascule texte ouverte.');
      this.stopVoiceSession();
      this.assistantPrompt.emit('AYA, donne-moi la synthese du scenario croise.');
    }
  }

  private async finishVoiceTurn(): Promise<void> {
    this.voiceState.set('thinking');
    this.voiceNotice.set('AYA analyse et prepare une reponse vocale');
    await this.flushRecorder();
    await Promise.allSettled(this.pendingVoiceFrames);
    this.pendingVoiceFrames = [];
    this.stopMediaTracks();
    if (this.voiceConnection && this.voiceTurnId) {
      this.voiceConnection.endpoint({ turn_id: this.voiceTurnId });
      this.armVoiceFallback();
    } else {
      this.voiceState.set('error');
      this.voiceNotice.set('Canal voix indisponible. Bascule texte ouverte.');
      this.assistantPrompt.emit('AYA, quelle est la situation prioritaire maintenant ?');
    }
  }

  private flushRecorder(): Promise<void> {
    const recorder = this.mediaRecorder;
    this.mediaRecorder = null;
    if (!recorder || recorder.state === 'inactive') return Promise.resolve();
    return new Promise((resolve) => {
      recorder.addEventListener('stop', () => resolve(), { once: true });
      try {
        recorder.requestData();
      } catch {
        // Some browsers do not support requestData after rapid start/stop.
      }
      recorder.stop();
    });
  }

  private stopMediaTracks(): void {
    this.mediaStream?.getTracks().forEach((track) => track.stop());
    this.mediaStream = null;
  }

  private stopVoiceSession(): void {
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    this.mediaRecorder = null;
    this.stopMediaTracks();
    this.stopSpeech();
    this.clearVoiceFallback();
    this.voiceConnection?.close();
    this.voiceConnection = null;
    this.voiceSubscription?.unsubscribe();
    this.voiceSubscription = null;
    this.voiceTurnId = null;
    this.pendingVoiceFrames = [];
    if (this.voiceState() !== 'error') {
      this.voiceState.set('idle');
      this.voiceNotice.set('Pret pour consigne vocale');
    }
  }

  private handleVoiceEvent(event: VoiceSessionEvent): void {
    const payload = event.payload || {};
    if (event.type === 'session.ready') {
      this.voiceNotice.set('Canal voix pret');
      return;
    }
    if (event.type === 'text.partial' || event.type === 'text.final') {
      const text = String(payload['text'] || '').trim();
      if (text) this.voiceTranscript.set(text);
      if (event.type === 'text.final' && text) {
        this.clearVoiceFallback();
        this.applyVoiceCommand(text);
        this.speakSovereignAnswer(this.sovereignVoiceAnswer(text));
      }
      return;
    }
    if (event.type === 'prompt.next') {
      const text = String(payload['text'] || '').trim();
      if (text) this.voiceAnswer.set(text);
      return;
    }
    if (event.type === 'audio.out') {
      this.playAudioPayload(payload);
      return;
    }
    if (event.type === 'oracle.action') {
      const text = String(payload['prompt'] || payload['text'] || '').trim();
      if (text) this.applyVoiceCommand(text);
      return;
    }
    if (event.type === 'session.error') {
      if (this.voiceState() === 'thinking') {
        this.speakSovereignAnswer(this.sovereignVoiceAnswer(this.voiceTranscript() || 'situation nord'));
      } else {
        this.voiceState.set('error');
        this.voiceNotice.set(String(payload['message'] || 'Canal voix indisponible'));
      }
    }
  }

  private applyVoiceCommand(text: string): void {
    const lower = text.toLowerCase();
    if (lower.includes('pont') || lower.includes('camera') || lower.includes('webcam')) {
      const source = this.visualSources().find((item) => String(item.name || '').toLowerCase().includes('pont'))
        || this.visualSources()[0];
      if (source) this.selectVisualSource(source);
    }
    if (lower.includes('abidjan') || lower.includes('carte')) this.focusAbidjan();
  }

  private sovereignVoiceAnswer(text: string): string {
    const lower = text.toLowerCase();
    const demoAnswer = String(this.monitor?.voice_demo_script?.answer || this.monitor?.voice_context?.demo_script?.answer || '');
    if (lower.includes('nord') && demoAnswer) return demoAnswer;
    if (lower.includes('ambassadeur') || lower.includes('france')) {
      return "Le dejeuner avec l'Ambassadeur de France est dans 1 heure 44. La fiche est prete : cooperation France Cote d'Ivoire, perception presse et suivi des projets frontaliers. Je recommande de valider la position publique avant le dejeuner.";
    }
    if (lower.includes('rumeur') || lower.includes('origine')) {
      const rumor = this.rumorTrace();
      return `${rumor?.headline || 'Rumeur prioritaire sous verification'}. Origine : ${rumor?.origin || 'canaux publics et signalements terrain'}. ${rumor?.aya_sentence || rumor?.recommended_action || 'Verifier la source primaire, preparer un message de compassion et coordonner une presence institutionnelle.'}`;
    }
    if (lower.includes('dossier') || lower.includes('decision') || lower.includes('décision') || lower.includes('arbitrage')) {
      const pack = this.primaryDecisionPackage();
      if (pack) return `${pack.title}. ${pack.decision} Je recommande : ${pack.recommended_option}. Echeance : ${pack.deadline}, responsable : ${pack.owner}.`;
    }
    if (lower.includes('que dois-je faire') || lower.includes('priorite') || lower.includes('priorité')) {
      return `${this.decisionSentence().text} Trois actions sont prêtes : réponse presse avant 14 heures, arbitrage Zone Nord avant 15 heures, fiche Ambassadeur France ouverte pour le déjeuner.`;
    }
    return `${this.decisionSentence().text} Je filtre le reste : un article exige votre attention, la Zone Nord attend arbitrage, et la fiche Ambassadeur France est prête.`;
  }

  private speakSovereignAnswer(text: string): void {
    if (!text) return;
    this.clearVoiceFallback();
    this.voiceAnswer.set(text);
    this.voiceState.set('speaking');
    this.voiceNotice.set('AYA repond');
    this.speechSubscription?.unsubscribe();
    this.speechSubscription = this.api.synthesizeSpeech(text.slice(0, 600), 'nova', 'cascade_openai').subscribe({
      next: (blob) => this.playAudioBlob(blob),
      error: () => {
        this.voiceState.set('error');
        this.voiceNotice.set('Synthese vocale indisponible. Reponse ouverte en texte.');
        this.assistantPrompt.emit(text);
        this.stopVoiceSession();
      },
    });
  }

  private playAudioPayload(payload: Record<string, any>): void {
    const audioBase64 = String(payload['audio_base64'] || '');
    if (!audioBase64) return;
    const binary = atob(audioBase64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    this.playAudioBlob(new Blob([bytes], { type: String(payload['content_type'] || 'audio/mpeg') }));
  }

  private playAudioBlob(blob: Blob): void {
    this.stopSpeech();
    const url = URL.createObjectURL(blob);
    this.activeAudioUrl = url;
    const audio = new Audio(url);
    this.activeAudio = audio;
    audio.onended = () => {
      this.voiceState.set('idle');
      this.voiceNotice.set('Pret pour consigne vocale');
      this.closeVoiceTransport();
      this.stopSpeech();
    };
    audio.onerror = () => {
      this.voiceState.set('error');
      this.voiceNotice.set('Lecture audio bloquee par le navigateur. Reponse ouverte en texte.');
      this.assistantPrompt.emit(this.voiceAnswer());
      this.closeVoiceTransport();
      this.stopSpeech();
    };
    void audio.play().catch(() => {
      this.voiceState.set('error');
      this.voiceNotice.set('Lecture audio bloquee par le navigateur. Reponse ouverte en texte.');
      this.assistantPrompt.emit(this.voiceAnswer());
      this.closeVoiceTransport();
      this.stopSpeech();
    });
  }

  private stopSpeech(): void {
    this.speechSubscription?.unsubscribe();
    this.speechSubscription = null;
    this.activeAudio?.pause();
    this.activeAudio = null;
    if (this.activeAudioUrl) URL.revokeObjectURL(this.activeAudioUrl);
    this.activeAudioUrl = null;
  }

  private closeVoiceTransport(): void {
    this.clearVoiceFallback();
    this.voiceConnection?.close();
    this.voiceConnection = null;
    this.voiceSubscription?.unsubscribe();
    this.voiceSubscription = null;
    this.voiceTurnId = null;
  }

  private preferredMimeType(): string {
    for (const candidate of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']) {
      if (MediaRecorder.isTypeSupported(candidate)) return candidate;
    }
    return '';
  }

  private armVoiceFallback(): void {
    this.clearVoiceFallback();
    const targetLatency = Number(this.monitor?.voice_demo_script?.target_latency_s || this.monitor?.voice_context?.demo_script?.target_latency_s || 6);
    const delayMs = Math.max(4, Math.min(targetLatency, 8)) * 1000;
    this.voiceFallbackTimer = setTimeout(() => {
      if (this.voiceState() !== 'thinking') return;
      this.speakSovereignAnswer(this.sovereignVoiceAnswer(this.voiceTranscript() || 'situation nord'));
    }, delayMs);
  }

  private clearVoiceFallback(): void {
    if (!this.voiceFallbackTimer) return;
    clearTimeout(this.voiceFallbackTimer);
    this.voiceFallbackTimer = null;
  }
}
