import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnDestroy, OnInit, Output, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, type SafeResourceUrl } from '@angular/platform-browser';
import { Subscription } from 'rxjs';
import { VoiceSessionConnection, VoiceSessionEvent, VoiceSessionService } from '@app/core/voice-session.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { WorkspaceMapComponent } from './workspace-map.component';

type VoiceState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'error';

@Component({
  selector: 'app-mission-control-monitor',
  standalone: true,
  imports: [CommonModule, GlyphComponent, WorkspaceMapComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './mission-control-monitor.component.html',
  styleUrls: ['./mission-control-monitor.component.scss'],
})
export class MissionControlMonitorComponent implements OnInit, OnDestroy {
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
  readonly selectedVisualSourceId = signal<string | null>(null);
  readonly visualPreviewFailures = signal<Record<string, true>>({});
  readonly voiceState = signal<VoiceState>('idle');
  readonly voiceTranscript = signal('');
  readonly voiceNotice = signal('Pret pour consigne vocale');

  private readonly trustedVisualEmbeds = new Map<string, SafeResourceUrl>();
  private clockTimer: ReturnType<typeof setInterval> | null = null;
  private voiceConnection: VoiceSessionConnection | null = null;
  private voiceSubscription: Subscription | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private mediaStream: MediaStream | null = null;
  private voiceTurnId: string | null = null;

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

  crossSignals(): any[] {
    return this.monitor?.cross_source_signals || [];
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
    if (source?.id) this.selectedVisualSourceId.set(source.id);
  }

  isVisualSourceSelected(source: any): boolean {
    return this.primaryVisualSource()?.id === source.id;
  }

  visualEmbedUrl(source: any | null): SafeResourceUrl | null {
    if (!source) return null;
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
    if (preview.startsWith('http://') || preview.startsWith('https://')) return preview;
    if (source.adapter === 'http_image' && source.source_url?.startsWith('http')) return source.source_url;
    return null;
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

  activatePrompt(prompt: string): void {
    this.assistantPrompt.emit(prompt);
  }

  focusSignal(signal: any): void {
    const zoneId = signal?.related_zone || this.scenario()?.map_focus?.zone_id;
    const zone = (this.monitor?.zones || []).find((item: any) => item.id === zoneId);
    if (zone) this.zoneSelected.emit(zone);
    this.assistantPrompt.emit(signal?.action_prompt || 'AYA, donne-moi une lecture operationnelle de ce signal.');
  }

  focusAbidjan(): void {
    const zone = (this.monitor?.zones || []).find((item: any) => String(item.name || '').toLowerCase().includes('abidjan'));
    if (zone) this.zoneSelected.emit(zone);
  }

  async toggleVoice(): Promise<void> {
    if (this.voiceState() === 'listening' || this.voiceState() === 'connecting') {
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
  }

  private visualPriority(source: any): number {
    const value = Number((source?.metadata || {}).priority);
    return Number.isFinite(value) ? value : 999;
  }

  private visualMetadataUrl(source: any, key: string): string {
    const value = (source?.metadata || {})[key];
    return typeof value === 'string' ? value : '';
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
        void this.voiceConnection.sendAudioFrame(event.data, {
          turn_id: this.voiceTurnId,
          content_type: event.data.type || mimeType || 'audio/webm',
        });
      };
      this.mediaRecorder.start(1000);
      this.voiceState.set('listening');
      this.voiceNotice.set('AYA ecoute la Mission Control Room');
    } catch {
      this.voiceState.set('error');
      this.voiceNotice.set('Micro ou canal voix indisponible. Bascule texte ouverte.');
      this.stopVoiceSession(false);
      this.assistantPrompt.emit('AYA, donne-moi la synthese du scenario croise.');
    }
  }

  private stopVoiceSession(endpoint = true): void {
    if (endpoint && this.voiceConnection && this.voiceTurnId) {
      this.voiceConnection.endpoint({ turn_id: this.voiceTurnId });
    }
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    this.mediaRecorder = null;
    this.mediaStream?.getTracks().forEach((track) => track.stop());
    this.mediaStream = null;
    this.voiceConnection?.close();
    this.voiceConnection = null;
    this.voiceSubscription?.unsubscribe();
    this.voiceSubscription = null;
    this.voiceTurnId = null;
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
      if (event.type === 'text.final' && text) this.applyVoiceCommand(text);
      return;
    }
    if (event.type === 'oracle.action') {
      const text = String(payload['prompt'] || payload['text'] || '').trim();
      if (text) this.applyVoiceCommand(text);
      return;
    }
    if (event.type === 'session.error') {
      this.voiceState.set('error');
      this.voiceNotice.set(String(payload['message'] || 'Canal voix indisponible'));
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
    this.assistantPrompt.emit(text);
  }

  private preferredMimeType(): string {
    for (const candidate of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']) {
      if (MediaRecorder.isTypeSupported(candidate)) return candidate;
    }
    return '';
  }
}
