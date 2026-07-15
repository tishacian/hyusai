import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { forkJoin, of, Subscription } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import {
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { AssistantEffectsService, type AssistantNavigateEffect, type AssistantProposeEffect } from '@app/core/assistant-effects.service';
import { MaritimeTrackingService, type VesselPosition } from '@app/core/maritime-tracking.service';
import { WorkspaceExperienceShadowService } from '@app/core/workspace-experience-shadow.service';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import { MissionControlMonitorComponent } from './mission-control-monitor.component';
import {
  OCTOCITY_MISSION_ROOM_PROFILE,
  missionRoomExtensionState,
} from './mission-room.extension';
import { WorkspaceMapComponent } from './workspace-map.component';
import { VpCockpitComponent } from './vp-cockpit.component';
import { VpPressArticleDrawerComponent, type PressArticleDetail } from './vp-press-article-drawer.component';
import { VpTroopsTheaterDrawerComponent } from './vp-troops-theater-drawer.component';
import { VpRumorTraceTimelineComponent } from './vp-rumor-trace-timeline.component';
import type {
  VpAgendaTimeline,
  VpAgendaTimelineEvent,
  VpArbitrationCard,
  VpDrillDown,
  VpIntelligenceFeed,
  VpMapPreviewContext,
  VpOptionCompare,
  VpPressPreviewItem,
  VpSovereignIndicator,
  VpStatusBarItem,
  VpZoneScore,
} from './vp-cockpit.types';

type MissionView =
  | 'cockpit'
  | 'monitor'
  | 'briefing'
  | 'pilotage'
  | 'agenda'
  | 'messages'
  | 'bibliotheque'
  | 'projets'
  | 'presse'
  | 'reputation'
  | 'securite'
  | 'veille'
  | 'decisions'
  | 'strategie'
  | 'recherche'
  | 'assistant';

interface WorkspaceContinuationContext {
  scope: WorkspaceRequestScope;
  generation: number;
}

interface WorkspaceMeta {
  id: string;
  slug: string;
  name: string;
}

interface SourceRef {
  id: string;
  label: string;
  kind: string;
  confidence: number;
  age: string;
}

interface MissionNavigationItem {
  key: MissionView;
  label: string;
  glyph: CkGlyphName;
  route: string;
  api: string;
  object: string;
  workbench: string;
  system_id?: string | null;
  system_name?: string | null;
}

interface MissionBrand {
  label?: string;
  lines?: string[];
  emblem?: string;
  style?: string;
}

interface MissionNavigation {
  workspace: WorkspaceMeta;
  app: {
    label: string;
    assistant_label: string;
    shell: string;
    default_route: string;
    default_view: MissionView;
    profile?: string;
    brand?: MissionBrand;
  };
  items: MissionNavigationItem[];
  exit_routes: { label: string; route: string }[];
}

interface Priority {
  id: string;
  kind: string;
  title: string;
  summary: string;
  deadline: string;
  sources: string[];
  tone: string;
}

interface AttentionRequiredItem {
  id?: string;
  rank?: number;
  title: string;
  sentence?: string;
  summary?: string;
  deadline?: string;
  status?: string;
  action_label?: string;
  tone?: string;
  kind?: string;
  next_step?: string;
  action_route?: string;
  draft_target_type?: string;
  draft_recipient?: string;
}

interface AgendaSubItem {
  id?: string;
  title: string;
  order?: number;
  priority?: string;
  owner_proposer?: string;
  source?: string;
  source_label?: string;
  decision_required?: boolean;
  notes?: string;
}

interface AgendaPendingPatch {
  event_id?: string;
  agenda_items?: AgendaSubItem[];
  proposed_at?: string;
  proposed_via?: string;
}

interface AgendaItem {
  id?: string;
  date?: string;
  time: string;
  end_time?: string;
  title: string;
  location: string;
  tone: string;
  description?: string;
  participants?: string[];
  priority?: string;
  status?: string;
  category?: string;
  source_label?: string;
  metadata?: {
    agenda_items?: AgendaSubItem[];
    workspace?: string;
    [key: string]: unknown;
  };
}

interface MessageItem {
  id: string;
  from: string;
  subject: string;
  time: string;
  priority: string;
  summary: string;
  sources: string[];
}

interface Project {
  id: string;
  name: string;
  weather: 'red' | 'orange' | 'green';
  progress: number;
  expected: number;
  delay_days: number;
  owner: string;
  cause: string;
  risk: string;
  options: string[];
  scenario_options?: ScenarioOption[];
  active_action?: ActionItem;
  sources: string[];
}

interface MapZone {
  id: string;
  zone_id?: string;
  name: string;
  level: number;
  tone: string;
  centroid: { x: number; y: number };
  polygon: string;
  signals: string[];
  recommendations: string[];
  drivers?: string[];
  scenario_options?: ScenarioOption[];
  score?: { score: number; level_label: string; drivers?: string[]; computed_at?: string };
  recommended_windows?: RecommendedWindow[];
  active_action?: ActionItem;
  sources: string[];
}

interface ScenarioOption {
  id: string;
  label: string;
  summary: string;
  impact: string;
  confidence: number;
  confidence_label?: string;
  cost_score?: number;
  impact_score?: number;
  time_sensitivity?: number;
  risk_reduction?: number;
  decision_score?: number;
  rank?: number;
  rationale?: string;
  recommended?: boolean;
}

interface RecommendedWindow {
  label: string;
  start: string;
  end: string;
  why: string;
  zone?: string;
  target_id?: string;
}

interface NewsSignal {
  id: string;
  article_id?: string;
  title: string;
  risk_level: string;
  sentiment: string;
  summary: string;
  source: string;
  source_name?: string | null;
  source_category?: string | null;
  sources: string[];
  zone?: string;
  geo_tier?: string;
  geography_tier?: string;
  viewpoint?: string;
  origin?: string;
  rumor_origin?: string;
  velocity?: string;
  badges?: string[];
  impact_ci?: string;
  impact_international?: string;
  why_it_matters?: string;
  recommended_action?: string;
  briefing_value?: string;
  confidence?: number;
  source_count?: number;
  domain?: string;
  source_type?: string;
  tags?: string[];
  evidence_refs?: { type?: string; id?: string; label?: string }[];
  aya_context?: Record<string, unknown>;
  url?: string | null;
  run_id?: string | null;
  entities?: string[];
  published_at?: string | null;
}

interface NewsSourceHealth {
  active_feeds: number;
  total_articles: number;
  analyzed: number;
  high_risk: number;
  last_run_id?: string | null;
  last_run_status?: string;
  last_updated?: string | null;
  coverage_label?: string;
  live_news_used?: boolean;
  source_entities?: string[];
  geography_order?: string[];
}

interface NewsGeographicPriority {
  key: string;
  label: string;
  priority: number;
  description: string;
  feed_count: number;
  signal_count: number;
  sources?: string[];
  focus?: string[];
}

interface NewsViewpoint {
  key: string;
  label: string;
  feed_count: number;
  signal_count: number;
  sources?: string[];
  brief?: string;
}

interface SocialListeningChannel {
  key: string;
  label: string;
  coverage: number;
  status: string;
}

interface RumorOrigin {
  label?: string;
  origin?: string;
  zone?: string;
  confidence?: number;
  recommended_action?: string;
}

interface SocialListeningPayload {
  status: string;
  policy: string;
  channels: SocialListeningChannel[];
  signals: NewsSignal[];
  rumor_origins: RumorOrigin[];
}

interface NewsBriefingNote {
  headline: string;
  bullets: string[];
  talking_points: string[];
  decisions_expected: string[];
}

interface MaritimeIntelligence {
  status: string;
  provider: string;
  source_url: string;
  source_policy?: string;
  focus_area: string;
  source_quality?: { label?: string; limitations?: string };
  ports?: { id: string; name: string; location?: string; score?: number; tone?: string; role?: string }[];
  vessel_events?: {
    id: string;
    title: string;
    location: string;
    score?: number;
    severity?: string;
    domain?: string;
    summary?: string;
    recommended_action?: string;
    decision_deadline?: string;
  }[];
  customs_links?: { id: string; label: string; domain?: string; summary?: string; recommended_action?: string }[];
  signals?: NewsSignal[];
  feeds?: { name: string; url: string; category?: string; source_type?: string }[];
  latest_observation?: Record<string, any>;
  active_evidence?: Record<string, any>;
  briefing_value?: string;
  aya_context?: Record<string, unknown>;
  prompts?: string[];
}

interface DecisionItem {
  id: string;
  title: string;
  status: string;
  risk: string;
  recommendation: string;
  target_id: string;
  target_type: string;
  sources: string[];
}

interface LibraryItem {
  id: string;
  title: string;
  kind: string;
  collection: string;
  summary: string;
  sources: string[];
}

interface MissionCockpit {
  workspace: WorkspaceMeta;
  title: string;
  date_label: string;
  briefing_status: string;
  decision_sentence?: {
    label?: string;
    text: string;
    deadline?: string;
    generated_by?: string;
  };
  attention_required?: AttentionRequiredItem[];
  sixty_second_cockpit?: {
    urgences?: AttentionRequiredItem[];
    agenda_focus?: AgendaItem[];
    menace?: { label?: string; score?: number; tone?: string; deadline?: string };
    reputation?: { score?: number; delta?: number; sentence?: string };
  };
  priorities: Priority[];
  kpis: Record<string, number | string>;
  threat_trend: number[];
  communications_flow: { hour: string; institutional: number; press: number }[];
  agenda: AgendaItem[];
  zones: { name: string; level: number; tone: string }[];
  reputation: {
    score: number;
    delta: number;
    trend: number[];
    summary?: string;
    period_label?: string;
    aya_sentence?: string;
    items?: Array<{
      id: string;
      kind?: string;
      tone?: string;
      title: string;
      summary?: string;
      source_label?: string;
      source_id?: string;
      url?: string;
      sentiment?: string;
      engagement?: number;
      linked_attention_id?: string;
    }>;
  };
  media_sources: { label: string; coverage: number; count: number }[];
  latest_alerts: NewsSignal[];
  keywords: { label: string; count: number; delta: number }[];
  assistant_prompts: string[];
  messages: MessageItem[];
  decision_focus: DecisionItem[];
  press_intelligence?: NewsSourceHealth;
  situation_monitor?: {
    route: string;
    posture: StrategicPosture;
    top_zones: MapZone[];
    visual?: VisualObservation | null;
    source_freshness?: Record<string, string>;
  };
  decision_posture?: {
    label?: string;
    score?: number;
    sentence?: string;
    modes?: { key: string; label: string; goal?: string }[];
    axes?: {
      key: string;
      label: string;
      status?: string;
      score?: number;
      why?: string;
      action?: string;
      deadline?: string;
    }[];
  };
  source_freshness?: {
    status?: string;
    items?: {
      key: string;
      label: string;
      state?: string;
      freshness?: string;
      count?: number;
      confidence?: number;
    }[];
  };
  monitoring_layers?: {
    key?: string;
    label?: string;
    name?: string;
    count?: number;
    freshness?: string;
    confidence?: number;
    source_kind?: string;
    visible?: boolean;
  }[];
  evidence_graph_summary?: {
    node_count?: number;
    edge_count?: number;
    route?: string;
    collection_slug?: string;
    top_relationships?: string[];
  };
  scenario_modes?: { key: string; label: string; goal?: string }[];
  territorial_live_status?: { zone: string; level: string; bars: number; summary: string; tone: string }[];
  executive_decision_packages?: Record<string, any>[];
  visual_summary?: VisualSourceHealth;
  strategic_posture?: StrategicPosture;
  what_changed?: string[];
  vp_status_bar?: { key: string; label: string; value: string; detail?: string; tone?: string }[];
  security_posture?: Record<string, any> | null;
  social_snapshot?: Record<string, any> | null;
  troops_sahel?: Record<string, any> | null;
  rumor_frontier_trace?: Record<string, any> | null;
  security_documents?: {
    id: string;
    title: string;
    kind: string;
    collection: string;
    summary: string;
    sources: string[];
  }[];
  directive_of_day?: {
    label?: string;
    text: string;
    deadline?: string;
    generated_by?: string;
    window?: string;
    primary_cta?: string;
    voice_cta?: string;
  };
  fused_map_preview?: {
    route: string;
    label: string;
    question: string;
    top_zone?: MapZone;
    zones: MapZone[];
    layers: { key: string; label: string; count: number; tone: string; visible: boolean }[];
    heatmap: { label: string; score: number; tone: string }[];
    source_label: string;
    geo_preview?: VpMapPreviewContext['geoPreview'];
  };
  agenda_day?: {
    label: string;
    next_event?: AgendaItem | null;
    events: AgendaItem[];
    available_window?: { label: string; time: string; reason: string };
  };
  aya_recommendation?: {
    assistant: string;
    voice_first: boolean;
    prompt: string;
    answer: string;
    target_latency_s: number;
    cta_primary: string;
    cta_secondary: string;
    decision_package?: Record<string, any>;
  };
  decision_queue?: {
    id: string;
    label: string;
    title: string;
    decision: string;
    recommended_option: string;
    why_now: string;
    deadline: string;
    owner: string;
    confidence: number;
    status: string;
    tone: string;
    sources: string[];
    cta: string;
    email_draft_ready?: boolean;
    validation_required?: boolean;
  }[];
  geographic_signal_tiers?: { key: string; label: string; count: number; top_signal?: string | null; signals: NewsSignal[] }[];
  sovereign_indicators?: {
    label: string;
    value: number | string;
    unit?: string;
    source?: string;
    confidence?: string;
    trend?: string;
    tone?: string;
  }[];
  arbitration_cards?: VpArbitrationCard[];
  intelligence_feeds?: VpIntelligenceFeed[];
  press_preview?: VpPressPreviewItem[];
  agenda_timeline?: VpAgendaTimeline;
  demo_narrative?: {
    scenario_id?: string;
    steps?: { phase?: string; focus_widget?: string; prompt?: string; anchor?: string }[];
    economic_hook?: { title?: string; cross_sources?: string[]; cta_route?: string };
  };
  layout?: {
    variant?: string;
    demo_strata?: Record<string, number>;
    widgets?: { id: string; stratum: string; span?: string }[];
  };
  sources: SourceRef[];
}

interface BriefingSection {
  id: string;
  title: string;
  content: string;
  sources: string[];
}

interface MissionBriefing {
  title: string;
  generated_at: string;
  sections: BriefingSection[];
  actions: { id: string; label: string; target: string }[];
  sources: SourceRef[];
}

interface MissionProjects {
  summary: { total: number; red: number; orange: number; green: number };
  projects: Project[];
  sources: SourceRef[];
}

interface MissionMap {
  question: string;
  map_system?: {
    id: string;
    slug: string;
    name: string;
    layers?: { key: string; label: string; visible: boolean }[];
    renderer_config?: Record<string, any>;
    geojson_sources?: Record<string, any>;
    camera_presets?: Record<string, any>;
    visual_effects?: Record<string, any>;
  };
  map: { country: string; view_box: string; projection: string; accuracy: string };
  zones: MapZone[];
  recommended_windows?: RecommendedWindow[];
  score_summary?: { critical: number; watch: number; stable: number; top_zone?: MapZone | null };
  sources: SourceRef[];
}

interface StrategicPosture {
  label: string;
  score: number;
  trend: string;
  summary: string;
  drivers?: { kind: string; label: string; score: number }[];
}

interface VisualSourceHealth {
  active_sources: number;
  total_sources: number;
  captures: number;
  observations: number;
  last_capture_at?: string | null;
  coverage_label: string;
}

interface VisualSource {
  id: string;
  name: string;
  description: string;
  source_url: string;
  source_type: string;
  adapter: string;
  region: string;
  status: string;
  enabled: boolean;
  capture_cadence_minutes: number;
  policy: Record<string, unknown>;
  metadata: Record<string, unknown>;
  last_captured_at?: string | null;
}

interface VisualCapture {
  id: string;
  source_id: string;
  job_id?: string | null;
  status: string;
  object_key: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  width?: number | null;
  height?: number | null;
  error?: string | null;
  metadata: Record<string, unknown>;
  captured_at?: string | null;
}

interface VisualObservation {
  id: string;
  source_id: string;
  capture_id: string;
  summary: string;
  tags: string[];
  confidence: number;
  vigilance_score: number;
  level_label: string;
  source_refs: string[];
  provider?: string | null;
  model?: string | null;
  metadata: Record<string, unknown>;
  created_at?: string | null;
}

interface VisualDashboard {
  connector: { id: string; label: string; status: string; mode: string; policy?: string };
  source_health: VisualSourceHealth;
  posture: StrategicPosture;
  sources: VisualSource[];
  captures: VisualCapture[];
  observations: VisualObservation[];
  latest_observation?: VisualObservation | null;
}

interface MissionMonitor {
  workspace: WorkspaceMeta;
  title: string;
  summary: string;
  posture: StrategicPosture;
  layers: { key: string; label: string; enabled: boolean; count: number }[];
  map: { country: string; view_box: string; projection: string; accuracy: string };
  map_system?: MissionMap['map_system'];
  zones: MapZone[];
  top_zones: MapZone[];
  visual: VisualDashboard;
  maritime?: MaritimeIntelligence;
  visual_observations: VisualObservation[];
  forecasts: { id: string; title: string; summary: string; level: string; horizon: string; confidence: number }[];
  news_signals: NewsSignal[];
  source_freshness: Record<string, string>;
  sources: SourceRef[];
}

interface MissionNews {
  summary: string;
  signals: NewsSignal[];
  all_signals?: NewsSignal[];
  executive_alerts?: NewsSignal[];
  briefing_note?: NewsBriefingNote;
  source_health?: NewsSourceHealth;
  media_sources?: { label: string; coverage: number; count: number }[];
  geographic_priority?: NewsGeographicPriority[];
  geo_sections?: { key: string; label: string; description: string; count: number; signals: NewsSignal[] }[];
  viewpoints?: NewsViewpoint[];
  social_listening?: SocialListeningPayload;
  maritime_intelligence?: MaritimeIntelligence;
  analysis_link?: { system_id?: string | null; run_id?: string | null; label?: string };
  sources: SourceRef[];
}

interface MissionTimeline {
  agenda: AgendaItem[];
  action_items?: ActionItem[];
  messages: MessageItem[];
  summary: string;
  calendar?: {
    connector: { id: string; label: string; mode: string; status: string; write_policy: string };
    count: number;
    conflicts: CalendarConflict[];
    free_slots: { start: string; end: string; label?: string; duration_min?: number }[];
    available_windows?: { start: string; end: string; label?: string; duration_min?: number }[];
    recommended_moves?: CalendarMove[];
    decision_deadlines?: CalendarDeadline[];
    conflict_score?: number;
    status?: string;
    next_event?: AgendaItem | null;
    summary: string;
  };
  conflicts?: CalendarConflict[];
  recommended_moves?: CalendarMove[];
  decision_deadlines?: CalendarDeadline[];
  sources: SourceRef[];
}

interface CalendarConflict {
  type?: string;
  severity?: string;
  event_ids: string[];
  action_id?: string;
  label: string;
  reason?: string;
  suggestion?: string;
}

interface CalendarMove {
  event_id: string;
  title: string;
  from: string;
  to: string;
  duration_min?: number;
  why?: string;
  severity?: string;
}

interface CalendarDeadline {
  action_id: string;
  title: string;
  priority: string;
  due_label?: string;
  suggested_window?: { start: string; end: string; label?: string; duration_min?: number } | null;
}

interface MissionDecisions {
  decisions: DecisionItem[];
  action_items?: ActionItem[];
  action_summary?: {
    count: number;
    active: number;
    critical: number;
    completed: number;
    cancelled: number;
    next_due?: ActionItem | null;
    write_policy?: string;
  };
  scenario_options?: ScenarioOption[];
  policy: Record<string, unknown>;
  sources: SourceRef[];
}

interface ActionItem {
  id: string;
  title: string;
  description: string;
  target_kind: string;
  target_id: string;
  target_label: string;
  priority: string;
  status: string;
  due_at?: string | null;
  due_label?: string;
  owner_label: string;
  source_kind: string;
  source_id: string;
  confidence: string;
  recommended_window?: RecommendedWindow;
  scenario_options?: ScenarioOption[];
}

interface MissionLibrary {
  items: LibraryItem[];
  collections: string[];
  sources: SourceRef[];
}

interface SearchResult {
  id: string;
  title: string;
  kind: string;
  summary: string;
  sources: string[];
}

interface MissionSearch {
  query: string;
  results: SearchResult[];
  total: number;
  sources: SourceRef[];
}

interface DraftInstruction {
  status: string;
  requires_validation: boolean;
  sent: boolean;
  title: string;
  recipient: string;
  subject?: string;
  deadline?: string;
  body: string;
  sources: string[];
  control: Record<string, unknown>;
}

interface MeetingDecisionLogEntry {
  id: string;
  title: string;
  chosen_option: string;
  rationale?: string;
  decided_at?: string;
  decided_at_label?: string;
  event_id?: string;
  event_title?: string;
}

interface MeetingDecisionsLogResponse {
  decisions?: Array<{
    id?: string;
    agenda_item_ref?: string;
    agenda_item_title?: string;
    title?: string;
    chosen_option?: string;
    rationale?: string;
    decided_at?: string;
    calendar_event_id?: string;
    event_id?: string;
    event_title?: string;
  }>;
}

@Component({
  selector: 'app-mission-metric-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="metric-card" [class]="tone">
      <span>{{ label }}</span>
      <strong>{{ value }}</strong>
      <small>{{ caption }}</small>
    </article>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .metric-card {
        font-family: var(--ck-font-sans);
        min-height: 100px;
        padding: 15px;
        border: 1px solid var(--mission-border, var(--ck-stroke-2));
        background: var(--mission-panel, var(--ck-bg-panel));
        border-radius: var(--mission-radius, 8px);
        box-shadow: var(--mission-shadow-card, none);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-width: 0;
        position: relative;
        overflow: hidden;
      }
      .metric-card::before {
        content: '';
        position: absolute;
        inset: 0 0 auto;
        height: 2px;
        background: var(--mission-accent-muted, rgba(125, 211, 252, 0.28));
        opacity: 0.74;
      }
      .metric-card span {
        color: var(--mission-text-muted, var(--ck-fg-3));
        font-family: var(--ck-font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.13em;
      }
      .metric-card strong {
        font-family: var(--ck-font-mono);
        font-variant-numeric: tabular-nums;
        color: var(--mission-text, var(--ck-fg-1));
        font-size: 27px;
        font-weight: 600;
        line-height: 1;
        letter-spacing: 0;
      }
      .metric-card small {
        color: var(--mission-text-faint, var(--ck-fg-4));
        font-size: 12px;
        overflow-wrap: anywhere;
      }
      .metric-card.critical::before { background: var(--mission-danger, var(--ck-signal-neg)); }
      .metric-card.watch::before { background: var(--mission-warn, var(--ck-signal-warn)); }
      .metric-card.good::before { background: var(--mission-trust, var(--ck-signal-pos)); }
      .metric-card.info::before { background: var(--mission-accent, var(--ck-signal-cool)); }
      .metric-card.critical strong { color: var(--mission-danger, var(--ck-signal-neg)); }
      .metric-card.watch strong { color: var(--mission-warn, var(--ck-signal-warn)); }
      .metric-card.good strong { color: var(--mission-trust, var(--ck-signal-pos)); }
      .metric-card.info strong { color: var(--mission-accent, var(--ck-signal-cool)); }
    `,
  ],
})
export class MissionMetricCardComponent {
  @Input({ required: true }) label = '';
  @Input({ required: true }) value: string | number = '-';
  @Input() caption = '';
  @Input() tone: 'critical' | 'watch' | 'good' | 'info' | '' = '';
}

@Component({
  selector: 'app-mission-chart-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="chart-panel" [class.tall]="tall">
      <div class="chart-head">
        <div>
          <span>{{ eyebrow }}</span>
          <h2>{{ title }}</h2>
        </div>
        @if (value) {
          <strong>{{ value }}</strong>
        }
      </div>
      <ng-content />
    </section>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .chart-panel {
        font-family: var(--ck-font-sans);
        min-height: 220px;
        height: 100%;
        padding: 16px;
        border: 1px solid var(--mission-border, var(--ck-stroke-2));
        border-radius: var(--mission-radius, 8px);
        background: var(--mission-panel, var(--ck-bg-panel));
        box-shadow: var(--mission-shadow-card, none);
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-width: 0;
        overflow: hidden;
      }
      .chart-panel.tall { min-height: 300px; }
      .chart-head {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
      }
      .chart-head span {
        color: var(--mission-text-faint, var(--ck-fg-4));
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
      }
      .chart-head h2 {
        margin: 5px 0 0;
        color: var(--mission-text, var(--ck-fg-1));
        font-size: 18px;
        font-weight: 650;
        letter-spacing: 0;
      }
      .chart-head strong {
        font-family: var(--ck-font-mono);
        font-variant-numeric: tabular-nums;
        color: var(--mission-trust, var(--ck-signal-pos));
        font-size: 22px;
        font-weight: 600;
      }
    `,
  ],
})
export class MissionChartPanelComponent {
  @Input() eyebrow = '';
  @Input() title = '';
  @Input() value = '';
  @Input() tall = false;
}

@Component({
  selector: 'app-mission-source-pill',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<button type="button" class="source-pill">{{ label }}</button>`,
  styles: [
    `
      :host { display: inline-flex; min-width: 0; }
      .source-pill {
        max-width: 100%;
        border: 1px solid var(--mission-border-strong, var(--ck-stroke-hot));
        border-radius: 999px;
        background: var(--mission-accent-wash, rgba(125, 211, 252, 0.08));
        color: var(--mission-accent, var(--ck-signal-cool));
        padding: 5px 8px;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        cursor: pointer;
      }
    `,
  ],
})
export class MissionSourcePillComponent {
  @Input() label = '';
}

@Component({
  selector: 'app-mission-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive, GlyphComponent],
  template: `
    <aside class="mission-rail" [class.agentium-brand]="brandStyle === 'agentium'" [attr.aria-label]="'Navigation ' + brandLabel">
      <div class="rail-brand" [attr.aria-label]="brandLabel">
        <img
          class="brand-emblem"
          [src]="brandEmblem"
          alt=""
          width="54"
          height="54"
          aria-hidden="true"
        />
        <div class="brand-wordmark">
          <strong>{{ brandLabel }}</strong>
          @for (line of brandLines; track line) {
            <span>{{ line }}</span>
          }
        </div>
      </div>

      <button
        type="button"
        class="assistant-badge"
        [class.listening]="ayaState === 'listening'"
        (click)="assistantRequest.emit()"
        [attr.aria-label]="assistantOpenLabel"
      >
        <span class="assistant-avatar">{{ assistantName }}</span>
        <div>
          <strong>{{ assistantName }}</strong>
          <small>{{ ayaStateLabel }}</small>
        </div>
      </button>

      <a class="rail-search" routerLink="/hypervisor/mission-room/recherche" [attr.aria-label]="searchAriaLabel">
        <ck-glyph name="zoom-in" [size]="12" />
        <span>{{ searchLabel }}</span>
      </a>

      <nav class="mission-nav">
        <span class="rail-section-label">{{ railSectionLabel }}</span>
        @for (item of visibleItems(); track item.key) {
          <a
            [routerLink]="item.route"
            routerLinkActive="active"
            class="mission-nav-item"
            [attr.aria-current]="activeView === item.key ? 'page' : null"
          >
            <ck-glyph [name]="item.glyph" [size]="14" />
            <span>{{ railLabel(item) }}</span>
            @if (navBadge(item.key); as count) {
              <em class="nav-badge">{{ count }}</em>
            }
          </a>
        }
      </nav>

      <div class="rail-spacer"></div>

      <div class="rail-clock">
        <strong>{{ abidjanClockTime() }}</strong>
        <span>{{ abidjanClockDate() }} · {{ timezoneLabel }}</span>
      </div>
      <nav class="rail-tools" [attr.aria-label]="operatorToolsLabel">
        <a [routerLink]="adminRoute">Admin</a>
        <a routerLink="/systems">OS</a>
      </nav>
    </aside>
  `,
  styles: [
    `
      :host { display: block; min-height: 0; }
      .mission-rail {
        font-family: var(--ck-font-sans);
        width: 220px;
        height: 100%;
        padding: 14px 14px 12px;
        background: var(--mission-rail-bg, var(--ck-bg-base));
        border-right: 1px solid var(--mission-border, var(--ck-stroke-2));
        display: flex;
        flex-direction: column;
        gap: 10px;
        min-height: 0;
        overflow: hidden;
      }
      .rail-brand {
        display: grid;
        grid-template-columns: 54px minmax(0, 1fr);
        align-items: center;
        gap: 10px;
        min-height: 58px;
        min-width: 0;
      }
      .brand-emblem {
        display: block;
        width: 54px;
        height: 54px;
        object-fit: contain;
        filter:
          drop-shadow(0 14px 22px rgba(0, 0, 0, 0.52))
          drop-shadow(0 0 12px rgba(64, 220, 152, 0.16));
      }
      .mission-rail.agentium-brand .brand-emblem {
        filter:
          drop-shadow(0 14px 22px rgba(0, 0, 0, 0.52))
          drop-shadow(0 0 18px rgba(125, 211, 252, 0.26));
      }
      .brand-wordmark {
        display: grid;
        gap: 2px;
        min-width: 0;
      }
      .brand-wordmark strong {
        display: block;
        color: var(--mission-text, var(--ck-fg-1));
        font-family: var(--ck-font-mono);
        font-size: 14px;
        font-weight: 800;
        line-height: 1.05;
        letter-spacing: 0;
        white-space: nowrap;
      }
      .brand-wordmark span {
        display: block;
        color: var(--mission-muted, var(--ck-fg-3));
        font-family: var(--ck-font-mono);
        font-size: 8px;
        font-weight: 700;
        line-height: 1.15;
        letter-spacing: 0;
      }
      .assistant-badge {
        display: flex;
        align-items: center;
        gap: 14px;
        width: 100%;
        padding: 14px 12px;
        border: 1px solid rgba(242, 140, 56, 0.24);
        border-radius: var(--mission-radius, 8px);
        background:
          linear-gradient(135deg, rgba(242, 140, 56, 0.12), rgba(101, 214, 110, 0.06)),
          var(--mission-panel-hi, var(--ck-bg-panel-hi));
        appearance: none;
        font: inherit;
        color: inherit;
        text-align: left;
        cursor: pointer;
      }
      .assistant-badge.listening {
        border-color: rgba(101, 214, 110, 0.34);
        box-shadow: inset 3px 0 0 var(--mission-trust);
      }
      .assistant-badge:hover {
        border-color: rgba(242, 140, 56, 0.38);
        box-shadow: inset 3px 0 0 var(--mission-orange, #f28c38);
      }
      .assistant-avatar {
        width: 52px;
        height: 52px;
        border-radius: 16px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--mission-orange, #f28c38);
        font-family: var(--ck-font-mono);
        font-size: 13px;
        font-weight: 850;
        letter-spacing: 0;
        background: rgba(8, 13, 17, 0.72);
        border: 1px solid rgba(242, 140, 56, 0.32);
        box-shadow: inset 0 0 18px rgba(242, 140, 56, 0.08);
        flex-shrink: 0;
      }
      .assistant-badge strong {
        display: block;
        color: var(--mission-text, var(--ck-fg-1));
        font-family: var(--ck-font-mono);
        font-size: 13px;
        letter-spacing: 0;
      }
      .assistant-badge small {
        display: block;
        margin-top: 2px;
        color: var(--mission-text-muted, var(--ck-fg-3));
        font-size: 11px;
      }
      .rail-search,
      .mission-nav-item {
        display: flex;
        align-items: center;
        gap: 8px;
        min-height: 31px;
        padding: 7px 9px;
        border-radius: var(--mission-radius-sm, 7px);
        color: var(--mission-text-soft, var(--ck-fg-2));
        text-decoration: none;
        font-size: 12.5px;
        min-width: 0;
      }
      .rail-search {
        border: 1px solid var(--mission-border, var(--ck-stroke-2));
        background: var(--mission-inset, var(--ck-bg-inset));
        color: var(--mission-text-faint, var(--ck-fg-4));
      }
      .rail-search span,
      .mission-nav-item span {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .mission-nav {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-height: 0;
        overflow: auto;
        padding-right: 2px;
      }
      .mission-nav::-webkit-scrollbar { width: 0; height: 0; }
      .rail-section-label {
        display: block;
        padding: 2px 9px 4px;
        color: var(--mission-text-faint, var(--ck-fg-4));
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0;
        text-transform: uppercase;
      }
      .mission-nav-item.active,
      .mission-nav-item:hover,
      .rail-tools a:hover {
        background: var(--mission-panel-hi, var(--ck-bg-panel-hi));
        color: var(--mission-text, var(--ck-fg-1));
      }
      .mission-nav-item.active {
        color: var(--mission-accent, var(--ck-signal-cool));
        box-shadow: inset 3px 0 0 var(--mission-accent, var(--ck-signal-cool));
      }
      .nav-badge {
        margin-left: auto;
        min-width: 18px;
        height: 18px;
        padding: 0 5px;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: rgba(240, 100, 118, 0.18);
        border: 1px solid rgba(240, 100, 118, 0.34);
        color: var(--mission-danger);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        font-style: normal;
        font-weight: 700;
      }
      .rail-spacer { flex: 1 1 auto; min-height: 4px; }
      .rail-summary {
        padding: 9px 10px;
        border: 1px solid var(--mission-border, var(--ck-stroke-2));
        border-radius: var(--mission-radius, 8px);
        color: var(--mission-accent, var(--ck-signal-cool));
        background: var(--mission-panel-hi, var(--ck-bg-panel-hi));
      }
      .rail-summary span,
      .rail-clock span {
        display: block;
        color: var(--mission-text-faint, var(--ck-fg-4));
        font-size: 10.5px;
      }
      .rail-summary strong {
        display: block;
        margin-top: 2px;
        color: var(--mission-text, var(--ck-fg-1));
        font-size: 12px;
      }
      .rail-summary small {
        display: block;
        margin-top: 2px;
        color: var(--mission-orange, #f28c38);
        font-size: 10.5px;
      }
      .rail-tools {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .rail-tools a {
        min-width: 0;
        flex: 1 1 0;
        padding: 6px 8px;
        border-radius: var(--mission-radius-sm, 7px);
        color: var(--mission-text-faint, var(--ck-fg-4));
        text-align: center;
        text-decoration: none;
        font-size: 10.5px;
      }
      .rail-clock strong {
        display: block;
        font-family: var(--ck-font-mono);
        font-variant-numeric: tabular-nums;
        color: var(--mission-text, var(--ck-fg-1));
        font-size: 21px;
        font-weight: 500;
        letter-spacing: -0.01em;
      }
      @media (max-height: 820px) {
        .mission-rail { padding-top: 10px; gap: 8px; }
        .rail-brand { grid-template-columns: 44px minmax(0, 1fr); min-height: 46px; gap: 8px; }
        .brand-emblem { width: 44px; height: 44px; }
        .brand-wordmark strong { font-size: 12px; }
        .brand-wordmark span { font-size: 7px; }
        .assistant-badge { padding: 7px; }
        .assistant-avatar { width: 32px; height: 32px; border-radius: 10px; }
        .assistant-badge small { display: none; }
        .rail-search,
        .mission-nav-item { min-height: 29px; padding-block: 6px; }
        .rail-summary { display: none; }
        .rail-clock strong { font-size: 18px; }
        .rail-clock span { font-size: 9.5px; }
      }
    `,
  ],
})
export class MissionRailComponent {
  @Input() items: MissionNavigationItem[] = [];
  @Input() activeView: MissionView = 'cockpit';
  @Input() adminRoute = '/workspace';
  @Input() assistantName = 'AYA';
  @Input() brandLabel = 'SENTINEL-CI';
  @Input() brandLines: string[] = ['REPUBLIQUE DE', "COTE D'IVOIRE"];
  @Input() brandEmblem = '/assets/brand/sentinel-ci-emblem.png?v=20260518-1';
  @Input() brandStyle = 'sentinel';
  @Input() timezoneLabel = 'Abidjan UTC+0';
  @Input() ayaState: 'listening' | 'ready' = 'ready';
  @Input() ayaStateLabel = 'Briefing pret';
  @Input() alertBadges: Partial<Record<MissionView, number>> = {};
  @Output() assistantRequest = new EventEmitter<void>();

  private readonly clockTimeZone = 'Africa/Abidjan';
  private readonly clockNow = signal(new Date());
  private clockTimer: number | null = null;
  private readonly primaryRailKeys: MissionView[] = [
    'cockpit',
    'strategie',
    'securite',
    'reputation',
    'agenda',
    'presse',
    'decisions',
  ];
  private readonly railLabelOverrides: Partial<Record<MissionView, string>> = {
    cockpit: 'Cockpit',
    strategie: 'Carte',
    securite: 'Sécurité',
    reputation: 'Reputation',
    presse: 'Presse',
    decisions: 'Arbitrages',
  };
  private readonly agentiumRailLabelOverrides: Partial<Record<MissionView, string>> = {
    cockpit: 'Cockpit',
    strategie: 'Map',
    securite: 'Security',
    reputation: 'Reputation',
    agenda: 'Agenda',
    presse: 'News',
    decisions: 'Reviews',
  };
  private readonly timeFormatter = new Intl.DateTimeFormat('fr-FR', {
    timeZone: this.clockTimeZone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  private readonly frenchDateFormatter = new Intl.DateTimeFormat('fr-FR', {
    timeZone: this.clockTimeZone,
    weekday: 'long',
    day: '2-digit',
    month: 'long',
  });
  private readonly englishDateFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: this.clockTimeZone,
    weekday: 'long',
    day: '2-digit',
    month: 'long',
  });

  readonly abidjanClockTime = computed(() => this.timeFormatter.format(this.clockNow()));
  readonly abidjanClockDate = computed(() => {
    const formatter = this.isAgentiumBrand() ? this.englishDateFormatter : this.frenchDateFormatter;
    return this.capitalizeClockLabel(formatter.format(this.clockNow()));
  });

  get assistantOpenLabel(): string {
    return this.isAgentiumBrand() ? `Open ${this.assistantName}` : `Ouvrir ${this.assistantName}`;
  }

  get searchLabel(): string {
    return this.isAgentiumBrand() ? 'Search dossier' : 'Recherche dossier';
  }

  get searchAriaLabel(): string {
    return this.isAgentiumBrand() ? `Search a ${this.brandLabel} dossier` : `Rechercher un dossier ${this.brandLabel}`;
  }

  get railSectionLabel(): string {
    return this.isAgentiumBrand() ? 'Mission path' : 'Parcours Mission';
  }

  get operatorToolsLabel(): string {
    return this.isAgentiumBrand() ? 'Operator tools' : 'Outils operateur';
  }

  ngOnInit(): void {
    this.clockTimer = window.setInterval(() => this.clockNow.set(new Date()), 30_000);
  }

  ngOnDestroy(): void {
    if (this.clockTimer !== null) {
      window.clearInterval(this.clockTimer);
      this.clockTimer = null;
    }
  }

  private capitalizeClockLabel(label: string): string {
    return label ? label.charAt(0).toUpperCase() + label.slice(1) : label;
  }

  visibleItems(): MissionNavigationItem[] {
    const byKey = new Map(this.items.map((item) => [item.key, item]));
    return this.primaryRailKeys.map((key) => byKey.get(key)).filter((item): item is MissionNavigationItem => !!item);
  }

  railLabel(item: MissionNavigationItem): string {
    const overrides = this.isAgentiumBrand() ? this.agentiumRailLabelOverrides : this.railLabelOverrides;
    return overrides[item.key] || item.label;
  }

  navBadge(key: MissionView): number | null {
    const count = this.alertBadges[key];
    return count && count > 0 ? count : null;
  }

  private isAgentiumBrand(): boolean {
    return this.brandStyle === 'agentium' || String(this.assistantName || '').toUpperCase() === 'OCTAVE';
  }
}

@Component({
  selector: 'app-mission-room',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    GlyphComponent,
    MissionRailComponent,
    MissionChartPanelComponent,
    MissionSourcePillComponent,
    MissionControlMonitorComponent,
    WorkspaceMapComponent,
    VpCockpitComponent,
    VpPressArticleDrawerComponent,
    VpTroopsTheaterDrawerComponent,
    VpRumorTraceTimelineComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="mission-shell" [class.agentium-theme]="missionBrandStyle() === 'agentium'">
      <app-mission-rail
        [items]="navigation()?.items || fallbackNav"
        [activeView]="currentView()"
        [adminRoute]="adminRoute()"
        [assistantName]="assistantName()"
        [brandLabel]="missionBrandLabel()"
        [brandLines]="missionBrandLines()"
        [brandEmblem]="missionBrandEmblem()"
        [brandStyle]="missionBrandStyle()"
        [timezoneLabel]="missionTimezoneLabel()"
        [ayaState]="ayaRailState()"
        [ayaStateLabel]="ayaRailStateLabel()"
        [alertBadges]="railAlertBadges()"
        (assistantRequest)="openAssistant()"
      />

      <main class="mission-main ck-scroll">
        @if (loading()) {
          <div class="loading-panel">
            <span class="dots"></span>
            <strong>Chargement de {{ missionBrandLabel() }}</strong>
          </div>
        } @else {
          @if (currentView() === 'cockpit') {
            <header class="mission-hero">
              <div class="hero-copy">
                <div class="hero-meta">
                  <span class="eyebrow">{{ missionRoomRoleLabel() }}</span>
                  <span class="hero-status">{{ cockpit()?.briefing_status || 'Briefing pret' }}</span>
                </div>
                <h1>{{ missionRoomHeroTitle() }}</h1>
                <p>
                  <span>{{ missionRoomDateLabel() }}</span>
                  <span class="hero-dot"></span>
                  <span>{{ missionRoomVisionLabel() }}</span>
                </p>
              </div>
              <div class="hero-actions">
                <button type="button" class="action-button primary" (click)="openDrillDownView('decisions', 'package-zone-nord')">
                  <ck-glyph name="ledger" [size]="15" />
                  <span>Arbitrages</span>
                </button>
                <button type="button" class="action-button" (click)="openAssistant()">
                  <ck-glyph name="crosshair" [size]="15" />
                  <span>{{ assistantName() }}</span>
                </button>
              </div>
            </header>
          }

          @switch (currentView()) {
            @case ('cockpit') { <ng-container *ngTemplateOutlet="cockpitView"></ng-container> }
            @case ('agenda') { <ng-container *ngTemplateOutlet="timelineView"></ng-container> }
            @case ('presse') { <ng-container *ngTemplateOutlet="newsView"></ng-container> }
            @case ('decisions') { <ng-container *ngTemplateOutlet="decisionsView"></ng-container> }
            @case ('strategie') { <ng-container *ngTemplateOutlet="mapView"></ng-container> }
            @case ('recherche') { <ng-container *ngTemplateOutlet="searchView"></ng-container> }
            @case ('reputation') { <ng-container *ngTemplateOutlet="reputationView"></ng-container> }
            @case ('securite') { <ng-container *ngTemplateOutlet="securiteView"></ng-container> }
            @default { <ng-container *ngTemplateOutlet="cockpitView"></ng-container> }
          }
        }
      </main>

      @if (videoDemoOctaveChat()) {
        <aside class="video-octave-chat" aria-label="OCTAVE video chat demo">
          <header>
            <span>OCTAVE command surface</span>
            <strong>60-second cockpit briefing</strong>
          </header>
          <div class="video-octave-thread">
            <div class="video-octave-message user">
              <span>Executive</span>
              <p>OCTAVE, give me the 60-second cockpit briefing in English.</p>
            </div>
            <div class="video-octave-message assistant">
              <span>OCTAVE</span>
              <p>
                Map posture is stable with two watch signals: a logistics corridor variance near Nantes and an executive review queue near Lyon.
              </p>
              <p>
                News-flow analysis confirms the signal with independent sources; the concrete systems involved are Cartography, News Lab, Security Watch and Knowledge Capture.
              </p>
              <p>
                Before review, one governance rule is missing: the expert escalation threshold. Capture it now, then route the next run with full lineage.
              </p>
            </div>
          </div>
          <footer>
            <span>Sources linked</span>
            <i>map · news-flow · systems · memory</i>
            <button type="button" class="action-button primary">Capture expert rule</button>
          </footer>
        </aside>
      }
    </section>

    <app-vp-press-article-drawer
      [open]="!!selectedPressArticle()"
      [article]="selectedPressArticleDetail()"
      [newsLabRoute]="systemRouteFor('veille')"
      [configRoute]="pressConfigRoute()"
      (closed)="closePressArticle()"
    />

    <ng-template #cockpitView>
      <app-vp-cockpit
        [assistantName]="assistantName()"
        [statusBar]="vpStatusBar()"
        [mapPreview]="vpMapPreviewContext()"
        [directive]="directiveOfDay()"
        [ayaRecommendation]="ayaRecommendation()"
        [arbitrationCards]="arbitrationCards()"
        [pressPreview]="pressPreview()"
        [pressHighlightId]="pressHighlightId()"
        [securityPosture]="securityPosture()"
        [focusTarget]="s3FocusTarget()"
        (openMap)="openDrillDownView('strategie', vpMapPreviewContext().geoPreview.top_zone_id || undefined)"
        (mapZoneSelected)="openMapZoneDrillDown($event)"
        (mapVesselSelected)="openCockpitVesselDrillDown($event)"
        (statusBarSelected)="openStatusBarDrillDown($event)"
        (arbitrationSelected)="openArbitrationFromCockpit($event)"
        (pressSelected)="openPressPreviewItem($event)"
        (voiceRequest)="openAssistantVoice($event)"
        (voiceListen)="openAssistantVoice('AYA, lis le briefing souverain en 60 secondes.')"
        (briefingRequest)="openZoneNordDossier()"
        (securityPostureRequested)="openAssistant('AYA, montre-moi la posture sécuritaire du jour.')"
        (securityCommuniqueRequested)="openAssistant('AYA, prépare un communiqué de sécurité sur la rumeur Nord.')"
      />
    </ng-template>

    <ng-template #briefingView>
      <section class="two-column">
        <article class="content-panel span-2">
          <span class="eyebrow">Briefing quotidien</span>
          <h2>{{ briefing()?.title }}</h2>
          <p>Synthese du jour, sources visibles et decisions preparees pour validation.</p>
        </article>
        @for (section of briefing()?.sections || []; track section.id) {
          <article class="content-panel">
            <h3>{{ section.title }}</h3>
            <p>{{ section.content }}</p>
            <div class="source-row">
              @for (source of section.sources; track source) {
                <app-mission-source-pill [label]="sourceLabel(source)" (click)="showSource(source)" />
              }
            </div>
          </article>
        }
        @if (zoneNorthOptionCompare(); as compare) {
          <article class="content-panel span-2 option-compare-panel" [attr.id]="compareAnchor()">
            <div class="panel-heading-row">
              <div>
                <span class="eyebrow">Zone Nord · arbitrage</span>
                <h3>{{ compare.title }}</h3>
                @if (compare.subtitle) {
                  <p>{{ compare.subtitle }}</p>
                }
              </div>
              <span class="status-pill elevated">Comparaison A/B</span>
            </div>
            <div class="option-compare-head">
              <span>{{ compare.option_a_label }}</span>
              <span>{{ compare.option_b_label }}</span>
            </div>
            @for (metric of compare.metrics; track metric.key) {
              <div class="option-compare-row">
                <label>{{ metric.label }}</label>
                <div class="compare-bars">
                  <i [style.width.%]="metric.option_a" [class.recommended]="compare.recommended === 'a'"></i>
                  <i [style.width.%]="metric.option_b" [class.recommended]="compare.recommended === 'b'"></i>
                </div>
                <small>{{ metric.option_a }} / {{ metric.option_b }}</small>
              </div>
            }
            <div class="card-actions">
              <button type="button" class="inline-action" (click)="openAssistant('AYA, explique pourquoi l option B est recommandee pour la Zone Nord.')">
                Expliquer l option recommandee
              </button>
              <button type="button" class="inline-action" (click)="createDraft('package-zone-nord', 'decision')">
                Valider option B (audit)
              </button>
            </div>
          </article>
        }
        <article class="content-panel span-2 project-risk-brief">
          <div class="panel-heading-row">
            <div>
              <span class="eyebrow">Risques projets</span>
              <h3>Impact direct sur les decisions du jour</h3>
            </div>
            <a routerLink="/hypervisor/mission-room/decisions" class="action-button compact">
              <ck-glyph name="check" [size]="14" />
              <span>Arbitrer</span>
            </a>
          </div>
          <div class="project-risk-grid">
            @for (project of projectDecisionRisks(); track project.id) {
              <article [class]="project.weather">
                <strong>{{ project.name }}</strong>
                <span>{{ project.weather }} · {{ project.progress }}% vs {{ project.expected }}%</span>
                <small>{{ project.risk }}</small>
              </article>
            }
          </div>
        </article>
        <article class="content-panel action-panel">
          <h3>Actions proposees</h3>
          @for (action of briefing()?.actions || []; track action.id) {
            <button type="button" class="inline-action" (click)="createDraft(action.target, action.target.startsWith('zone') ? 'zone' : 'project')">
              <ck-glyph name="ledger" [size]="14" />
              <span>{{ action.label }}</span>
            </button>
          }
        </article>
      </section>
    </ng-template>

    <ng-template #projectsView>
      <section class="two-column">
        <article class="content-panel">
          <span class="eyebrow">Pilotage projets</span>
          <h2>Portefeuille strategique</h2>
          <div class="project-summary">
            <span class="red">{{ projects()?.summary?.red || 0 }} rouge</span>
            <span class="orange">{{ projects()?.summary?.orange || 0 }} orange</span>
            <span class="green">{{ projects()?.summary?.green || 0 }} vert</span>
          </div>
          <div class="project-list">
            @for (project of projects()?.projects || []; track project.id) {
              <button type="button" [class.active]="selectedProject()?.id === project.id" (click)="selectProject(project)">
                <strong>{{ project.name }}</strong>
                <span [class]="project.weather">{{ project.weather }}</span>
                <small>{{ project.progress }}% vs {{ project.expected }}%</small>
              </button>
            }
          </div>
        </article>
        <article class="content-panel selected-detail">
          @if (selectedProject(); as project) {
            <span class="eyebrow">Projet selectionne</span>
            <h2>{{ project.name }}</h2>
            <p>{{ project.risk }}</p>
            <dl>
              <div><dt>Responsable</dt><dd>{{ project.owner }}</dd></div>
              <div><dt>Retard</dt><dd>{{ project.delay_days }} jours</dd></div>
              <div><dt>Cause probable</dt><dd>{{ project.cause }}</dd></div>
            </dl>
            <div class="option-list">
              @for (option of project.options; track option) {
                <span>{{ option }}</span>
              }
            </div>
            @if (project.scenario_options?.length) {
              <h3>Scenarios d'arbitrage</h3>
              <div class="scenario-grid">
                @for (option of project.scenario_options || []; track option.id) {
                  <article [class.recommended]="option.recommended">
                    <strong>{{ option.label }}</strong>
                    <span>{{ option.decision_score || confidencePct(option.confidence) }}</span>
                    <p>{{ option.summary }}</p>
                    <small>{{ option.impact }}</small>
                    <div class="scenario-metrics">
                      <i>impact {{ option.impact_score ?? '—' }}</i>
                      <i>effort {{ option.cost_score ?? '—' }}</i>
                      <i>conf. {{ confidencePct(option.confidence) }}</i>
                    </div>
                  </article>
                }
              </div>
            }
            @if (project.active_action) {
              <div class="action-linked">
                <span>Action active</span>
                <strong>{{ project.active_action.title }}</strong>
                <small>{{ project.active_action.owner_label }} · {{ project.active_action.due_label }}</small>
              </div>
            }
            <button type="button" class="action-button wide" (click)="draftForProject(project)">
              <ck-glyph name="ledger" [size]="15" />
              <span>Creer instruction Directeur de cabinet</span>
            </button>
            <button type="button" class="action-button wide" (click)="createActionForProject(project)">
              <ck-glyph name="check" [size]="15" />
              <span>Ajouter action cabinet</span>
            </button>
          }
        </article>
      </section>
    </ng-template>

    <ng-template #timelineView>
      <section class="agenda-workbench">
        <article class="content-panel span-2 agenda-command">
          <div>
            <span class="eyebrow">Agenda ministeriel</span>
            <h2>Canal agenda institutionnel habilite</h2>
            <p>{{ timeline()?.summary }}</p>
          </div>
          <div class="agenda-status-grid">
            <article>
              <span>Connecteur</span>
              <strong>{{ calendarConnectorLabel() }}</strong>
              <small>{{ timeline()?.calendar?.connector?.mode || 'internal_shared' }}</small>
            </article>
            <article>
              <span>Rendez-vous</span>
              <strong>{{ timeline()?.calendar?.count || (timeline()?.agenda?.length || 0) }}</strong>
              <small>{{ agendaDayLabel() }}</small>
            </article>
            <article>
              <span>Conflits</span>
              <strong>{{ timeline()?.calendar?.conflicts?.length || 0 }}</strong>
              <small>arbitrage cabinet</small>
            </article>
            <article>
              <span>Disponible</span>
              <strong>{{ timeline()?.calendar?.free_slots?.[0]?.start || '—' }}</strong>
              <small>{{ timeline()?.calendar?.free_slots?.[0]?.end || 'aucun creneau' }}</small>
            </article>
          </div>
          <div class="linked-action-strip">
            @for (item of timeline()?.action_items || []; track item.id) {
              <button type="button" (click)="goToDecisions()">
                <span [class]="item.priority">{{ item.priority }}</span>
                <strong>{{ item.title }}</strong>
                <small>{{ item.due_label }} · {{ item.owner_label }}</small>
              </button>
            }
          </div>
          @if ((timeline()?.calendar?.conflicts?.length || 0) > 0 || (timeline()?.calendar?.recommended_moves?.length || 0) > 0) {
            <div class="calendar-intelligence">
              @for (conflict of timeline()?.calendar?.conflicts || []; track conflict.label) {
                <article>
                  <span [class]="conflict.severity || 'medium'">{{ conflict.severity || 'watch' }}</span>
                  <strong>{{ conflict.label }}</strong>
                  <small>{{ conflict.reason || conflict.suggestion }}</small>
                </article>
              }
              @for (move of timeline()?.calendar?.recommended_moves || []; track move.event_id + move.to) {
                <article class="move">
                  <span>move</span>
                  <strong>{{ move.title }}</strong>
                  <small>{{ move.from }} → {{ move.to }} · {{ move.why }}</small>
                </article>
              }
            </div>
          }
        </article>

        <article class="content-panel agenda-timeline-panel">
          <div class="panel-heading-row">
            <div>
              <span class="eyebrow">Journee</span>
              <h2>{{ agendaDayLabel() }}</h2>
            </div>
            <button type="button" class="action-button compact" (click)="openAssistant('Resume mon agenda et signale les arbitrages avant reunion.')">
              <ck-glyph name="bolt" [size]="14" />
              <span>Synthese {{ assistantName() }}</span>
            </button>
          </div>
          <div class="week-strip">
            @for (day of agendaWeekDays(); track day.label) {
              <span [class.active]="day.active">
                {{ day.label }}
                <b>{{ day.count }}</b>
              </span>
            }
          </div>
          <ol class="agenda-list agenda-events">
            @for (item of timeline()?.agenda || []; track item.id || item.time) {
              <li [class]="item.tone" [class.active]="selectedAgendaEvent()?.id === item.id">
                <button type="button" (click)="selectAgendaEvent(item)">
                  <time>{{ item.time }}<small>{{ item.end_time }}</small></time>
                  <div>
                    <strong>{{ item.title }}</strong>
                    <span>{{ item.location }}</span>
                    @if (item.description) { <p>{{ item.description }}</p> }
                  </div>
                  <i>{{ item.priority || 'medium' }}</i>
                </button>
              </li>
            }
          </ol>
        </article>

        <aside class="content-panel agenda-detail-panel">
          @if (selectedAgendaEvent(); as event) {
            <span class="eyebrow">Detail evenement</span>
            <h2>{{ event.title }}</h2>
            <p>{{ event.description || 'Evenement consolide depuis le canal agenda institutionnel habilite.' }}</p>

            @if (agendaPendingPatch(); as pending) {
              <div class="agenda-pending-banner" role="status" aria-live="polite">
                <div class="agenda-pending-copy">
                  <span class="eyebrow">Modification ODJ proposee · {{ assistantName() }}</span>
                  <strong>{{ agendaPendingPatchTitle() }}</strong>
                  <p>{{ pending.agenda_items?.length || 0 }} point(s) en attente de validation.</p>
                </div>
                <div class="agenda-pending-actions">
                  <button
                    type="button"
                    class="action-button primary compact"
                    [disabled]="agendaPatchSubmitting()"
                    (click)="confirmAgendaPendingPatch()"
                  >
                    Valider modification
                  </button>
                  <button
                    type="button"
                    class="action-button compact"
                    [disabled]="agendaPatchSubmitting()"
                    (click)="rejectAgendaPendingPatch()"
                  >
                    Rejeter
                  </button>
                </div>
              </div>
            }

            <dl>
              <div><dt>Horaire</dt><dd>{{ event.time }} - {{ event.end_time || '—' }}</dd></div>
              <div><dt>Lieu</dt><dd>{{ event.location || 'A confirmer' }}</dd></div>
              <div><dt>Priorite</dt><dd>{{ event.priority || 'medium' }}</dd></div>
              <div><dt>Participants</dt><dd>{{ (event.participants || ['Cabinet']).join(', ') }}</dd></div>
            </dl>

            <section class="agenda-odj">
              <div class="agenda-odj-head">
                <span class="eyebrow">Ordre du jour</span>
                <button type="button" class="ghost-link" (click)="addAgendaSubItem()">+ Point</button>
              </div>
              @if (agendaSubItems(event).length) {
                <ol class="agenda-odj-list">
                  @for (item of agendaSubItems(event); track item.id || item.title; let idx = $index) {
                    <li>
                      <input
                        type="text"
                        [value]="item.title"
                        (change)="updateAgendaSubItem(idx, $any($event.target).value)"
                        aria-label="Intitulé du point"
                      />
                      <span class="agenda-odj-meta">
                        <small class="agenda-source-badge" [class]="agendaSubItemSourceClass(item)">
                          {{ agendaSubItemSourceLabel(item) }}
                        </small>
                        @if (item.decision_required) {
                          <small class="agenda-decision-pill">décision requise</small>
                        }
                      </span>
                      <button
                        type="button"
                        class="ghost-icon"
                        (click)="removeAgendaSubItem(idx)"
                        aria-label="Supprimer le point"
                      >
                        ×
                      </button>
                    </li>
                  }
                </ol>
              } @else {
                <p class="empty-line">Aucun point structuré. Ajoutez un point ou demandez à {{ assistantName() }} de pré-remplir l'ordre du jour.</p>
              }
            </section>

            <div class="agenda-actions">
              <button type="button" (click)="moveSelectedAgendaEvent(-15)">
                <ck-glyph name="arrow-down" [size]="13" />
                <span>-15 min</span>
              </button>
              <button type="button" (click)="moveSelectedAgendaEvent(15)">
                <ck-glyph name="arrow-right" [size]="13" />
                <span>+15 min</span>
              </button>
              <button type="button" class="danger" (click)="cancelSelectedAgendaEvent()">
                <ck-glyph name="x" [size]="13" />
                <span>Annuler</span>
              </button>
            </div>

            <button
              type="button"
              class="action-button wide primary meeting-cta"
              [disabled]="!event.id"
              (click)="startMeeting(event)"
            >
              <ck-glyph name="bolt" [size]="14" />
              <span>Démarrer la réunion</span>
            </button>
          }

          <div class="agenda-form">
            <span class="eyebrow">Ajout rapide</span>
            <input [(ngModel)]="newAgendaTitle" type="text" placeholder="Objet de la reunion" />
            <input [(ngModel)]="newAgendaStart" type="datetime-local" />
            <input [(ngModel)]="newAgendaLocation" type="text" placeholder="Lieu" />
            <button type="button" class="action-button wide primary" (click)="createAgendaEvent()">
              <ck-glyph name="crosshair" [size]="14" />
              <span>Ajouter a l'agenda</span>
            </button>
          </div>
        </aside>
      </section>
    </ng-template>

    <ng-template #messagesView>
      <section class="content-panel">
        <span class="eyebrow">Messages prioritaires</span>
        <h2>Priorites institutionnelles</h2>
        <div class="message-list">
          @for (message of timeline()?.messages || []; track message.id) {
            <article [class]="message.priority">
              <time>{{ message.time }}</time>
              <div>
                <strong>{{ message.subject }}</strong>
                <span>{{ message.from }}</span>
                <p>{{ message.summary }}</p>
              </div>
            </article>
          }
        </div>
      </section>
    </ng-template>

    <ng-template #libraryView>
      <section class="two-column">
        <article class="content-panel">
          <span class="eyebrow">Bibliotheque</span>
          <h2>Collections {{ missionBrandLabel() }}</h2>
          <div class="collection-list">
            @for (collection of library()?.collections || []; track collection) {
              <span>{{ collection }}</span>
            }
          </div>
        </article>
        <article class="content-panel">
          <span class="eyebrow">Sources de reference</span>
          <h2>Bibliotheque de mission</h2>
          <div class="library-list">
            @for (item of library()?.items || []; track item.id) {
              <article>
                <strong>{{ item.title }}</strong>
                <small>{{ item.kind }} · {{ item.collection }}</small>
                <p>{{ item.summary }}</p>
              </article>
            }
          </div>
        </article>
      </section>
    </ng-template>

    <ng-template #newsView>
      <section class="ministerial-news">
        <article class="content-panel span-2 news-brief-hero">
          <span class="eyebrow">{{ newsEyebrowLabel() }}</span>
          <h2>{{ news()?.briefing_note?.headline || 'Synthese executive' }}</h2>
          <p>{{ news()?.summary }}</p>
          @if (briefPriorityItems().length) {
            <ul class="brief-priority-list">
              @for (bullet of briefPriorityItems(); track bullet) {
                <li>
                  <button type="button" class="brief-priority-item" (click)="openBriefBullet(bullet)">
                    {{ bullet }}
                  </button>
                </li>
              }
            </ul>
          }
        </article>

        <div class="news-geo-tabs span-2">
          @for (tab of newsGeoTabs(); track tab.key) {
            <button type="button" [class.active]="activeNewsGeoTier() === tab.key" (click)="setNewsGeoTier(tab.key)">
              <strong>{{ tab.label }}</strong>
              <span>{{ tab.count }}</span>
            </button>
          }
        </div>

        @if (pressArticleListOpen()) {
          <div class="press-full-list span-2" role="region" aria-label="Liste complete des articles">
            @for (signal of displayedPressArticles(); track signal.id) {
              <button
                type="button"
                class="content-panel executive-alert-card compact press-article-card press-list-row"
                [class.highlighted]="selectedPressArticle()?.id === signal.id"
                (click)="openPressArticle(signal)"
              >
                <div class="panel-heading-row">
                  <span class="status-pill" [class]="signal.risk_level">{{ ministerialRisk(signal.risk_level) }}</span>
                  <small>{{ signal.source_name || signal.viewpoint || signal.zone || signal.source }}</small>
                </div>
                <h3>{{ signal.title }}</h3>
                <p>{{ signal.briefing_value || signal.impact_ci || signal.summary }}</p>
                @if (signal.source_name) {
                  <span class="publisher-badge">{{ signal.source_name }}</span>
                }
              </button>
            }
          </div>
        } @else {
          <div class="executive-alert-grid span-2 compact-news-list">
            @for (signal of heroNewsAlerts(); track signal.id) {
              <button
                type="button"
                class="content-panel executive-alert-card compact press-article-card"
                [class.highlighted]="highlightTarget() === signal.id || highlightTarget() === 'attention-inter-budget'"
                [attr.id]="signal.id"
                (click)="openPressArticle(signal)"
              >
                <div class="panel-heading-row">
                  <span class="status-pill" [class]="signal.risk_level">{{ ministerialRisk(signal.risk_level) }}</span>
                  <small>{{ signal.source_name || signal.viewpoint || signal.zone || signal.source }}</small>
                </div>
                <h3>{{ signal.title }}</h3>
                <p>{{ signal.briefing_value || signal.impact_ci || signal.summary }}</p>
                @if (signal.source_name) {
                  <span class="publisher-badge">{{ signal.source_name }}</span>
                }
              </button>
            }
          </div>
        }

        <div class="press-drill-footer span-2">
          <button type="button" class="press-see-all" (click)="togglePressArticleList()">
            {{ pressArticleListToggleLabel() }}
          </button>
          <button type="button" class="press-kpi-link" (click)="openPressArticleList({ sortByRisk: true })">
            {{ pressKpiLabel() }}
          </button>
        </div>

        <article class="content-panel">
          <span class="eyebrow">{{ talkingPointsEyebrowLabel() }}</span>
          <h2>{{ recommendedPositionLabel() }}</h2>
          <ul class="language-list">
            @for (line of news()?.briefing_note?.talking_points || []; track line) {
              <li>{{ line }}</li>
            }
          </ul>
        </article>
      </section>
    </ng-template>

    <ng-template #securiteView>
      <div class="securite-shell">
        <aside class="securite-council-bar" aria-live="polite">
          <span class="eyebrow">Prochain arbitrage sécuritaire</span>
          <strong>{{ securityCouncilLabel() }}</strong>
          <a routerLink="/hypervisor/mission-room/securite/monitor" class="inline-action">
            Ouvrir Security Monitor
          </a>
        </aside>

        <div class="securite-tabs" role="tablist">
          <button type="button" [class.active]="securiteTab() === 'vue'" (click)="securiteTab.set('vue')">Vue</button>
          <button type="button" [class.active]="securiteTab() === 'documents'" (click)="securiteTab.set('documents')">Documents</button>
        </div>

        @if (securiteTab() === 'vue') {
          <app-vp-cockpit
            [securityOnly]="true"
            [assistantName]="assistantName()"
            [statusBar]="[]"
            [mapPreview]="vpMapPreviewContext()"
            [directive]="directiveOfDay()"
            [ayaRecommendation]="ayaRecommendation()"
            [arbitrationCards]="[]"
            [pressPreview]="[]"
            [securityPosture]="securityPosture()"
            [focusTarget]="s3FocusTarget()"
            (securityPostureRequested)="openAssistant('AYA, montre-moi la posture sécuritaire du jour.')"
            (securityCommuniqueRequested)="openAssistant('AYA, prépare un communiqué de sécurité sur la rumeur Nord.')"
          />

          <section class="securite-stack">
            <app-vp-troops-theater-drawer
              [embedded]="true"
              [open]="true"
              [snapshot]="troopsSahel()"
            />
            <app-vp-rumor-trace-timeline
              id="s3-rumor-trace"
              [embedded]="true"
              [open]="true"
              [trace]="rumorFrontierTrace()"
              [focusStep]="selectedRumorStep()"
              (draftCommunique)="openAssistant('AYA, prépare un communiqué de sécurité sur la rumeur Nord.')"
              (showMap)="focusSecurityMapFromRumor()"
            />
          </section>
        } @else {
          <section class="content-panel span-2 securite-documents" id="security-doc-workbench">
            <div class="panel-heading-row">
              <div>
                <span class="eyebrow">{{ securityCollectionLabel() }}</span>
                <h2>Documents sécurité · workbench mission</h2>
                <p>{{ securityCollectionDescription() }}</p>
              </div>
              <span class="status-pill elevated">{{ securityDocuments().length }} sources indexées</span>
            </div>
            <div class="security-doc-workbench">
              <nav class="securite-doc-list" aria-label="Documents sécurité S3">
                @for (doc of securityDocuments(); track doc.id) {
                  <button
                    type="button"
                    class="securite-doc-card"
                    [class.active]="selectedSecurityDoc()?.id === doc.id"
                    (click)="selectSecurityDoc(doc)"
                  >
                    <span class="status-pill elevated">{{ doc.kind }}</span>
                    <strong>{{ doc.title }}</strong>
                    <small>{{ doc.collection }}</small>
                  </button>
                }
              </nav>

              @if (selectedSecurityDoc(); as doc) {
                <article class="security-doc-detail" aria-live="polite">
                  <div class="panel-heading-row">
                    <div>
                      <span class="eyebrow">Document sélectionné</span>
                      <h3>{{ doc.title }}</h3>
                      <p>{{ doc.summary }}</p>
                    </div>
                    <span class="status-pill elevated">{{ doc.kind }}</span>
                  </div>

                  <div class="doc-context-grid">
                    <article>
                      <span>Dernière mise à jour</span>
                      <strong>{{ currentAbidjanSessionLabel() }}</strong>
                    </article>
                    <article>
                      <span>Usage démo S3</span>
                      <strong>{{ securityDocUsage(doc) }}</strong>
                    </article>
                  </div>

                  <section class="doc-excerpt">
                    <span class="eyebrow">Extraits / citations</span>
                    <p>{{ securityDocExcerpt(doc) }}</p>
                  </section>

                  <div class="source-row doc-source-row">
                    @for (source of doc.sources || []; track source) {
                      <app-mission-source-pill [label]="sourceLabel(source)" (click)="showSource(source)" />
                    } @empty {
                      <span class="doc-source-empty">Source indexée · extrait non disponible</span>
                    }
                  </div>

                  <div class="doc-action-row">
                    <button type="button" class="inline-action primary" (click)="runSecurityDocAction(doc)">
                      {{ securityDocActionLabel(doc) }}
                    </button>
                    <button type="button" class="inline-action" (click)="openAssistant('AYA, résume le document sécurité ' + doc.title)">
                      Résumer avec {{ assistantName() }}
                    </button>
                  </div>
                </article>
              }
            </div>
          </section>
        }
      </div>
    </ng-template>

    <ng-template #reputationView>
      <section class="two-column">
        <app-mission-chart-panel eyebrow="E-Reputation" title="Sentiment medias" [value]="reputationValue()" [tall]="true">
          <svg class="line-chart big" viewBox="0 0 520 230" preserveAspectRatio="none">
            <text class="chart-label" x="20" y="24">{{ reputationTrendStartLabel() }}</text>
            <text class="chart-label right" x="500" y="24">{{ currentAbidjanShortDateLabel() }} · {{ cockpit()?.reputation?.score || 72 }}%</text>
            <path class="line good" [attr.d]="trendPath(cockpit()?.reputation?.trend || [], 210, 32)"></path>
            <path class="line muted" d="M20 160 L500 160"></path>
            <text class="chart-label muted-label" x="24" y="154">seuil neutre</text>
            <path class="line danger soft" d="M20 185 L130 195 L240 172 L340 202 L500 180"></path>
            <circle class="chart-current-point" cx="500" cy="32" r="5"></circle>
            <text class="chart-label current-label" x="430" y="50">+{{ cockpit()?.reputation?.delta || 4 }} pts</text>
          </svg>
        </app-mission-chart-panel>
        <article class="content-panel">
          <span class="eyebrow">Lecture cabinet</span>
          <h2>Reputation institutionnelle</h2>
          <p>{{ cockpit()?.reputation?.summary || "La dynamique positive reste fragile. Les signaux critiques viennent surtout des retards territoriaux et d'une perception de coordination insuffisante." }}</p>
          <div class="keyword-grid compact">
            @for (kw of cockpit()?.keywords || []; track kw.label) {
              <article>
                <span>{{ kw.label }}</span>
                <strong>{{ kw.count }}</strong>
                <small [class.down]="kw.delta < 0">{{ kw.delta > 0 ? '+' : '' }}{{ kw.delta }}%</small>
              </article>
            }
          </div>
        </article>
      </section>

      @if (reputationDrillItems().length) {
        <section class="content-panel span-2 reputation-drill-panel" id="reputation-drill">
          <div class="panel-heading-row">
            <div>
              <span class="eyebrow">Drill du sentiment · {{ cockpit()?.reputation?.period_label || 'Cette semaine' }}</span>
              <h2>Réputation 2 positifs · 1 critique</h2>
              @if (cockpit()?.reputation?.aya_sentence; as sentence) {
                <p>{{ sentence }}</p>
              }
            </div>
            <button
              type="button"
              class="inline-action"
              (click)="openAssistant('AYA, montre le drill de réputation 2 positifs et 1 critique.')"
            >
              Demander à {{ assistantName() }}
            </button>
          </div>
          <section class="reputation-balance-band">
            <div>
              <span>Balance narrative</span>
              <strong>{{ reputationNarrativeBalanceLabel() }}</strong>
            </div>
            <button type="button" class="inline-action" (click)="runReputationCouncilAction()">
              Préparer un encart Conseil 15h
            </button>
          </section>
          <div class="reputation-detail-layout">
            <div class="reputation-drill-grid" aria-label="Signaux réputation">
              @for (item of reputationDrillItems(); track item.id) {
                <button
                  type="button"
                  class="reputation-drill-card"
                  [class.positive]="item.kind === 'positif' || item.tone === 'positive'"
                  [class.critical]="item.kind === 'critique' || item.tone === 'negative'"
                  [class.active]="selectedReputationItem()?.id === item.id"
                  (click)="selectReputationItem(item)"
                >
                  <header class="reputation-drill-head">
                    <span class="reputation-drill-tag">
                      {{ item.kind === 'critique' ? 'Critique' : 'Positif' }}
                    </span>
                    @if (item.engagement) {
                      <small class="reputation-drill-engagement">{{ item.engagement }} eng.</small>
                    }
                  </header>
                  <h3>{{ item.title }}</h3>
                  @if (item.summary) {
                    <p>{{ item.summary }}</p>
                  }
                  <footer class="reputation-drill-foot">
                    @if (item.source_label) {
                      <span class="reputation-drill-source">{{ item.source_label }}</span>
                    }
                    @if (item.source_id) {
                      <span class="reputation-drill-source">{{ sourceLabel(item.source_id) }}</span>
                    }
                  </footer>
                </button>
              }
            </div>

            @if (selectedReputationItem(); as item) {
              <aside class="reputation-active-detail" aria-live="polite">
                <span class="eyebrow">Signal actif</span>
                <h3>{{ item.title }}</h3>
                @if (item.summary) {
                  <p>{{ item.summary }}</p>
                }
                <dl>
                  <div><dt>Source</dt><dd>{{ item.source_label || sourceLabel(item.source_id || '') }}</dd></div>
                  <div><dt>Engagement</dt><dd>{{ item.engagement || '—' }} interactions</dd></div>
                  <div><dt>Risque</dt><dd>{{ reputationItemRiskLabel(item) }}</dd></div>
                  <div><dt>Réponse</dt><dd>{{ reputationResponseLabel(item) }}</dd></div>
                </dl>
                <div class="doc-action-row">
                  <button type="button" class="inline-action primary" (click)="runReputationCouncilAction()">
                    Préparer réponse cabinet
                  </button>
                  @if (item.source_id) {
                    <button type="button" class="inline-action" (click)="showSource(item.source_id)">
                      Voir source
                    </button>
                  }
                  <button type="button" class="inline-action" (click)="openReputationArticle(item)">
                    {{ reputationArticleActionLabel(item) }}
                  </button>
                  @if (reputationExternalUrl(item); as externalUrl) {
                    <a class="inline-action" [href]="externalUrl" target="_blank" rel="noopener noreferrer">Site source</a>
                  }
                </div>
              </aside>
            }
          </div>
        </section>
      }
    </ng-template>

    <ng-template #watchView>
      <section class="two-column">
        <app-mission-chart-panel eyebrow="Veille mediatique" title="Sources et couverture" [tall]="true">
          <div class="source-bars large">
            @for (source of cockpit()?.media_sources || []; track source.label) {
              <div>
                <span>{{ source.label }}</span>
                <i><b [style.width.%]="source.coverage"></b></i>
                <strong>{{ source.coverage }}%</strong>
                <small>{{ source.count }}</small>
              </div>
            }
          </div>
        </app-mission-chart-panel>
        <article class="content-panel">
          <span class="eyebrow">Derniers signaux faibles</span>
          <div class="panel-heading-row">
            <h2>Qualification</h2>
            <a
              class="action-button compact"
              [routerLink]="systemRouteFor('veille') || '/intelligence'"
              [queryParams]="{ facet: 'intelligence' }"
            >
              <ck-glyph name="pulse" [size]="14" />
              <span>News Lab</span>
            </a>
          </div>
          <div class="library-list">
            @for (signal of news()?.signals || []; track signal.id) {
              <article>
                <strong>{{ signal.title }}</strong>
                <small>{{ signal.source }}</small>
                <p>{{ signal.summary }}</p>
              </article>
            }
          </div>
        </article>
      </section>
    </ng-template>

    <ng-template #decisionsView>
      <section class="decisions-split-layout">
        <article class="content-panel span-2 arbitration-layout-panel">
          <div class="panel-heading-row">
            <div>
              <span class="eyebrow">Sujets a arbitrer</span>
              <h2>3 decisions ce matin</h2>
            </div>
          </div>
          <div class="decision-arbitration-grid">
            @for (card of arbitrationCards(); track card.id) {
              <button
                type="button"
                class="decision-arbitration-card"
                [class.active]="selectedArbitrationCard()?.id === card.id"
                [class.highlighted]="highlightTarget() === card.id"
                [class.critical]="monitorTone(card.tone) === 'critical'"
                [class.elevated]="monitorTone(card.tone) === 'elevated'"
                (click)="selectArbitrationCard(card)"
              >
                <span>{{ card.rank }} · {{ card.domain_label }}</span>
                <strong>{{ card.title }}</strong>
                <p>{{ card.summary }}</p>
                <footer>
                  <em>{{ card.status_label }}</em>
                  <small>{{ card.deadline }}</small>
                </footer>
              </button>
            }
          </div>
        </article>

        <article class="content-panel selected-detail">
          @if (selectedArbitrationCard(); as card) {
            <span class="eyebrow">Detail arbitrage</span>
            <h2>{{ card.title }}</h2>
            <p>{{ card.summary }}</p>
            <dl class="arbitration-meta">
              <div><dt>Domaine</dt><dd>{{ card.domain_label || card.domain || '—' }}</dd></div>
              <div><dt>Statut</dt><dd>{{ card.status_label || '—' }}</dd></div>
              <div><dt>Echeance</dt><dd>{{ card.deadline || '—' }}</dd></div>
            </dl>
            <div class="card-actions">
              <button type="button" class="inline-action primary" (click)="openArbitrationDetailDrillDown(card)">
                {{ arbitrationDrillLabel(card) }}
              </button>
              <button type="button" class="inline-action" (click)="openAssistant('AYA, explique les options pour ' + card.title)">
                Demander a {{ assistantName() }}
              </button>
              <button type="button" class="inline-action" (click)="createDraft(card.id, 'decision')">
                Generer brouillon
              </button>
            </div>
          } @else {
            <span class="eyebrow">Detail arbitrage</span>
            <h2>Selectionnez un sujet</h2>
            <p>Choisissez une carte ci-dessus pour afficher le detail, l echeance et les options d arbitrage.</p>
          }
        </article>

        @if (zoneNorthOptionCompare(); as compare) {
          <article class="content-panel span-2 option-compare-panel" [attr.id]="compareAnchor()">
            <div class="panel-heading-row">
              <div>
                <span class="eyebrow">Zone Nord · arbitrage</span>
                <h3>{{ compare.title }}</h3>
                @if (compare.subtitle) {
                  <p>{{ compare.subtitle }}</p>
                }
              </div>
              <span class="status-pill elevated">Comparaison A/B</span>
            </div>
            <div class="option-compare-head">
              <span>{{ compare.option_a_label }}</span>
              <span>{{ compare.option_b_label }}</span>
            </div>
            @for (metric of compare.metrics; track metric.key) {
              <div class="option-compare-row">
                <label>{{ metric.label }}</label>
                <div class="compare-bars">
                  <i [style.width.%]="metric.option_a" [class.recommended]="compare.recommended === 'a'"></i>
                  <i [style.width.%]="metric.option_b" [class.recommended]="compare.recommended === 'b'"></i>
                </div>
                <small>{{ metric.option_a }} / {{ metric.option_b }}</small>
              </div>
            }
            <div class="card-actions">
              <button type="button" class="inline-action" (click)="openAssistant('AYA, explique pourquoi l option B est recommandee pour la Zone Nord.')">
                Expliquer l option recommandee
              </button>
              <button type="button" class="inline-action" (click)="createDraft('package-zone-nord', 'decision')">
                Valider option B (audit)
              </button>
            </div>
          </article>
        }

        <aside class="content-panel draft-sidebar">
          @if (draft(); as draftValue) {
            <span class="eyebrow">Brouillon advisory</span>
            <h2>{{ draftValue.title }}</h2>
            <p>{{ draftValue.body }}</p>
            <dl>
              <div><dt>Destinataire</dt><dd>{{ draftValue.recipient }}</dd></div>
              <div><dt>Statut</dt><dd>{{ draftValue.status }}</dd></div>
            </dl>
          } @else {
            <span class="eyebrow">Brouillon advisory</span>
            <h2>Aucun brouillon ouvert</h2>
            <p>Generez un brouillon depuis une carte ou la comparaison Zone Nord.</p>
          }
        </aside>

        <article class="content-panel span-2 meeting-decisions-panel">
          <div class="panel-heading-row">
            <div>
              <span class="eyebrow">Décisions de réunion</span>
              <h2>Arbitrages loggés en mode meeting</h2>
            </div>
            <small class="meeting-decisions-source">source : journal /meetings · advisory</small>
          </div>
          @if (meetingDecisionsLog().length) {
            <div class="meeting-decisions-list">
              @for (entry of meetingDecisionsLog(); track entry.id) {
                <article class="meeting-decision-card">
                  <header>
                    <strong>{{ entry.title }}</strong>
                    <small>{{ entry.decided_at_label }}</small>
                  </header>
                  <p class="meeting-decision-choice">
                    Option <em>{{ entry.chosen_option }}</em> retenue
                    @if (entry.event_title) {
                      · {{ entry.event_title }}
                    }
                  </p>
                  @if (entry.rationale) {
                    <p class="meeting-decision-rationale">« {{ entry.rationale }} »</p>
                  }
                </article>
              }
            </div>
          } @else {
            <p class="empty-line">Aucune décision loggée. Démarrez une réunion depuis l'agenda pour enregistrer les arbitrages.</p>
          }
        </article>
      </section>
    </ng-template>

    <ng-template #mapView>
      <section class="map-mode-shell">
        <div class="map-mode-tabs">
          <button type="button" [class.active]="mapViewMode() === 'territory'" (click)="setMapViewMode('territory')">
            Territoire
          </button>
          <button type="button" [class.active]="mapViewMode() === 'live'" (click)="setMapViewMode('live')">
            Live
          </button>
        </div>

        @if (mapViewMode() === 'live') {
          <app-mission-control-monitor
            [monitor]="monitor()"
            [missionMap]="missionMap()"
            [selectedZone]="selectedZone()"
            [mapCommandState]="mapCommandState()"
            [portWebcam]="activePortWebcam()"
            [assistantName]="assistantName()"
            [captureImages]="visualCaptureImages()"
            [vessels]="strategicVessels()"
            (zoneSelected)="selectZone($event)"
            (visualCapture)="captureVisualSource($event)"
            (assistantPrompt)="openAssistant($event)"
            (voiceRequest)="openAssistantVoice()"
          />
        } @else {
          <section class="two-column map-layout">
            <article class="content-panel map-panel span-2" style="position:relative">
              <span class="eyebrow">{{ strategicMapEyebrowLabel() }}</span>
              <h2>{{ strategicMapQuestion() }}</h2>
              <app-workspace-map
                class="strategy-map-canvas"
                style="display:block;height:clamp(760px,78vh,1040px)"
                [zones]="missionMap()?.zones || []"
                [map]="missionMap()?.map || null"
                [mapSystem]="missionMap()?.map_system || null"
                [mapState]="mapCommandState()"
                [selectedZoneId]="selectedZone()?.id || null"
                [assistantName]="assistantName()"
                [vessels]="strategicVessels()"
                [highlightedVesselMmsi]="highlightedStrategicVesselMmsi()"
                (zoneSelected)="selectStrategicZone($event)"
                (evidenceAction)="handleMapEvidenceAction($event)"
                (vesselSelected)="selectStrategicVessel($event)"
                (mapBackgroundClick)="clearStrategicVessel()"
              />
              @if (selectedStrategicVessel(); as vessel) {
                <aside class="md" aria-label="Fiche navire selectionne">
                  <header>
                    <span class="eyebrow">Navire AIS</span>
                    <button type="button" class="action-button compact" aria-label="Fermer" (click)="clearStrategicVessel()">×</button>
                  </header>
                  <strong>{{ vessel.name }}</strong>
                  <p>
                    {{ vessel.vessel_type || 'navire' }}
                    @if (vessel.sog != null) { · {{ vessel.sog | number:'1.0-0' }} kn }
                    @if (vessel.imo) { · IMO {{ vessel.imo }}
                    } · MMSI {{ vessel.mmsi }}
                  </p>
                  @if (vessel.destination) {
                    <p>→ {{ vessel.destination }}@if (vessel.eta) { · ETA {{ vessel.eta }} }</p>
                  }
                  @if (vessel.linked_cargo_id) {
                    <span class="hero-status">Cargo lie projet Centre Drones Napie</span>
                  }
                  <div class="source-row">
                    @if (strategicVesselHasPortWebcam(vessel)) {
                      <button type="button" class="action-button compact" (click)="openStrategicVesselPort(vessel)">
                        Voir au port
                      </button>
                    }
                    @if (vessel.linked_cargo_id || vessel.mmsi === '627012345') {
                      <button type="button" class="action-button compact ghost" (click)="openAssistant('AYA, ouvre le PV douanes.')">
                        PV douanes
                      </button>
                    }
                  </div>
                </aside>
              }
            </article>
          </section>
        }
      </section>
    </ng-template>

    <ng-template #searchView>
      <section class="two-column">
        <article class="content-panel">
          <span class="eyebrow">Recherche</span>
          <h2>Sources, briefing, projets et signaux</h2>
          <form class="search-form" (ngSubmit)="runSearch()">
            <input name="q" [(ngModel)]="searchQueryValue" placeholder="Ex. Nord, cooperation, projet rouge" />
            <button type="submit" class="action-button">Rechercher</button>
          </form>
        </article>
        <article class="content-panel">
          <span class="eyebrow">{{ search()?.total || 0 }} resultats</span>
          <h2>Resultats gouvernes</h2>
          <div class="library-list">
            @for (result of search()?.results || []; track result.id) {
              <article>
                <strong>{{ result.title }}</strong>
                <small>{{ result.kind }}</small>
                <p>{{ result.summary }}</p>
              </article>
            }
          </div>
        </article>
      </section>
    </ng-template>

    <ng-template #assistantView>
      <section class="two-column">
        <article class="content-panel">
          <span class="eyebrow">{{ assistantName() }}</span>
          <h2>Assistant transversal Chat / V2V</h2>
          <p>L'assistant combine conversation, recherche sourcee et oracle de contexte pour preparer l'action.</p>
          <button type="button" class="action-button wide" (click)="openAssistant()">
            <ck-glyph name="crosshair" [size]="15" />
            <span>Ouvrir {{ assistantName() }}</span>
          </button>
        </article>
        <article class="content-panel">
          <span class="eyebrow">Prompts utiles</span>
          <h2>Tandem oracle</h2>
          <div class="prompt-list">
            @for (prompt of cockpit()?.assistant_prompts || []; track prompt) {
              <button type="button" (click)="openAssistant(prompt)">
                <ck-glyph name="bolt" [size]="13" />
                <span>{{ prompt }}</span>
              </button>
            }
          </div>
        </article>
      </section>
    </ng-template>
  `,
  styles: [
    `
      :host {
        display: block;
        height: 100vh;
        overflow: hidden;
        background: var(--mission-bg);
        color: var(--mission-text-primary);
        font-family: var(--mission-font-body);
        font-feature-settings: "tnum", "zero";
      }
      .mission-shell {
        height: 100vh;
        display: grid;
        grid-template-columns: 220px minmax(0, 1fr);
        background:
          linear-gradient(90deg, rgba(255, 255, 255, 0.018) 1px, transparent 1px),
          linear-gradient(180deg, rgba(255, 255, 255, 0.016) 1px, transparent 1px),
          linear-gradient(180deg, rgba(101, 214, 110, 0.05) 0%, rgba(242, 140, 56, 0.025) 18%, rgba(5, 8, 12, 0) 36%),
          var(--mission-bg);
        background-size: 48px 48px, 48px 48px, auto, auto;
        color: var(--mission-text);
        min-width: 0;
      }
      .mission-shell.agentium-theme {
        --mission-bg: #061016;
        --mission-rail-bg: #07141b;
        --mission-panel: #0a1720;
        --mission-panel-hi: #0d1d27;
        --mission-inset: #061016;
        --mission-border: rgba(125, 211, 252, 0.16);
        --mission-border-strong: rgba(125, 211, 252, 0.34);
        --mission-accent: #7dd3fc;
        --mission-accent-wash: rgba(125, 211, 252, 0.1);
        --mission-orange: #7dd3fc;
        --mission-trust: #42d99b;
        background:
          linear-gradient(90deg, rgba(125, 211, 252, 0.035) 1px, transparent 1px),
          linear-gradient(180deg, rgba(125, 211, 252, 0.025) 1px, transparent 1px),
          linear-gradient(180deg, rgba(125, 211, 252, 0.07) 0%, rgba(66, 217, 155, 0.03) 24%, rgba(5, 8, 12, 0) 48%),
          var(--mission-bg);
        background-size: 48px 48px, 48px 48px, auto, auto;
      }
      .mission-main {
        min-width: 0;
        overflow: auto;
        padding: 26px 34px 42px;
      }
      .video-octave-chat {
        position: fixed;
        right: 28px; top: 86px;
        z-index: 24;
        width: min(520px, calc(100vw - 280px));
        display: grid;
        overflow: hidden;
        background: rgba(4, 10, 16, 0.97);
      }
      .video-octave-chat header,
      .video-octave-chat footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 14px 16px;
      }
      .video-octave-chat header span,
      .video-octave-chat footer span,
      .video-octave-message span {
        color: rgba(125, 211, 252, 0.86);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        text-transform: uppercase;
      }
      .video-octave-thread {
        display: grid;
        gap: 12px;
        padding: 16px;
      }
      .video-octave-message {
        display: grid;
        gap: 6px;
      }
      .video-octave-message p {
        margin: 0;
        color: rgba(231, 241, 250, 0.88);
        font-size: 14px;
        line-height: 1.4;
      }
      .video-octave-message.user { justify-self: end; }
      .video-octave-message.user p {
        padding: 13px 14px;
        border-radius: 12px 12px 3px 12px;
        background: #22d3ee;
        color: #031018;
      }
      .video-octave-message.assistant {
        padding: 14px;
        border-left: 3px solid rgba(66, 217, 155, 0.76);
        border-radius: 12px;
        background: rgba(10, 18, 28, 0.82);
      }
      .loading-panel {
        min-height: 360px;
        display: grid;
        place-items: center;
        gap: 14px;
        color: var(--mission-text-soft);
      }
      .dots {
        width: 96px;
        height: 10px;
        border-radius: 999px;
        background: repeating-linear-gradient(90deg, var(--mission-accent) 0 8px, transparent 8px 18px);
      }
      .mission-hero {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 24px;
        margin: 0 0 20px;
        padding: 0 0 18px;
        border-bottom: 1px solid var(--mission-border);
      }
      .hero-copy {
        min-width: 0;
      }
      .hero-meta {
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
      }
      .eyebrow {
        display: block;
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.16em;
      }
      .hero-status {
        border: 1px solid rgba(66, 217, 155, 0.24);
        border-radius: 999px;
        background: var(--mission-trust-wash);
        color: var(--mission-trust);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        line-height: 1;
        padding: 5px 8px;
        text-transform: uppercase;
        white-space: nowrap;
      }
      .mission-hero h1 {
        margin: 8px 0 6px;
        color: var(--mission-text);
        font-size: clamp(34px, 3.2vw, 44px);
        font-weight: 650;
        line-height: 1.02;
        letter-spacing: 0;
      }
      .mission-hero p {
        display: flex;
        align-items: center;
        gap: 9px;
        margin: 0;
        color: var(--mission-text-muted);
        font-size: 14px;
      }
      .hero-dot {
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: var(--mission-border-strong);
      }
      .hero-actions,
      .source-row,
      .option-list,
      .project-summary {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .action-button,
      .inline-action {
        min-height: 36px;
        border: 1px solid var(--mission-border);
        background: var(--mission-panel-hi);
        color: var(--mission-text);
        border-radius: var(--mission-radius);
        padding: 8px 11px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        text-decoration: none;
        cursor: pointer;
      }
      .inline-action.primary {
        border-color: var(--mission-border-strong);
        background: var(--mission-accent-wash);
        color: var(--mission-accent);
        font-weight: 650;
      }
      .arbitration-meta {
        margin: 14px 0;
        display: grid;
        gap: 4px;
      }
      .arbitration-meta div {
        display: grid;
        grid-template-columns: 92px minmax(0, 1fr);
        gap: 12px;
        padding: 6px 0;
        border-top: 1px solid var(--mission-border);
        font-size: 12px;
      }
      .arbitration-meta dt { color: var(--mission-text-muted); }
      .arbitration-meta dd { color: var(--mission-text); margin: 0; }
      .action-button.primary {
        border-color: var(--mission-border-strong);
        background: var(--mission-accent-wash);
        color: var(--mission-accent);
        font-weight: 650;
        box-shadow: none;
      }
      .action-button.compact {
        min-height: 31px;
        padding: 6px 9px;
        font-size: 12px;
      }
      .action-button.wide {
        width: 100%;
        margin-top: 14px;
      }
      .panel-heading-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 8px;
      }
      .panel-heading-row h2 {
        margin: 0;
      }
      .vp-status-bar {
        display: grid;
        grid-template-columns: repeat(5, minmax(120px, 1fr));
        gap: 10px;
        margin-bottom: 14px;
      }
      .vp-status-item {
        min-width: 0;
        padding: 11px 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(8, 14, 20, 0.78);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025);
      }
      .vp-status-item.critical { border-color: rgba(240, 100, 118, 0.34); background: linear-gradient(135deg, var(--mission-danger-wash), rgba(8, 14, 20, 0.82)); }
      .vp-status-item.elevated { border-color: rgba(241, 180, 90, 0.32); background: linear-gradient(135deg, var(--mission-warn-wash), rgba(8, 14, 20, 0.82)); }
      .vp-status-item.stable { border-color: rgba(63, 209, 141, 0.28); }
      .vp-status-item span,
      .vp-status-item small {
        display: block;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .vp-status-item span {
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }
      .vp-status-item strong {
        display: block;
        margin: 5px 0 3px;
        color: var(--mission-text);
        font-size: 18px;
        font-weight: 700;
        line-height: 1.1;
      }
      .vp-status-item small {
        color: var(--mission-text-faint);
        font-size: 11px;
      }
      .vp-directive-layout {
        display: grid;
        grid-template-columns: minmax(280px, 0.72fr) minmax(0, 1.28fr);
        gap: 14px;
        margin-bottom: 14px;
      }
      .vp-aya-card {
        display: grid;
        grid-template-columns: 54px minmax(0, 1fr);
        align-items: start;
        gap: 14px;
        position: relative;
        overflow: hidden;
      }
      .vp-aya-card::after,
      .vp-sentence::after {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background:
          radial-gradient(circle at 84% 18%, rgba(242, 140, 56, 0.16), transparent 34%),
          radial-gradient(circle at 18% 92%, rgba(101, 214, 110, 0.09), transparent 30%);
        opacity: 0.76;
      }
      .vp-aya-card > *,
      .vp-sentence > * {
        position: relative;
        z-index: 1;
      }
      .assistant-orb {
        width: 54px;
        height: 54px;
        border-radius: 16px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid rgba(242, 140, 56, 0.38);
        background: linear-gradient(135deg, rgba(242, 140, 56, 0.18), rgba(101, 214, 110, 0.08));
        color: var(--mission-orange);
        font-family: var(--ck-font-mono);
        font-size: 20px;
        font-weight: 850;
        box-shadow: 0 0 34px rgba(242, 140, 56, 0.12);
      }
      .vp-aya-card h2 {
        margin: 7px 0 5px;
        font-size: 22px;
        line-height: 1.12;
      }
      .vp-aya-card p,
      .vp-sentence p {
        color: var(--mission-text-muted);
        line-height: 1.45;
      }
      .vp-aya-card .hero-actions {
        grid-column: 1 / -1;
      }
      .vp-c2-strip {
        display: grid;
        grid-template-columns: minmax(320px, 1.05fr) minmax(340px, 1.1fr) minmax(260px, 0.75fr);
        gap: 14px;
        margin-bottom: 14px;
      }
      .vp-mode-row {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin-top: 10px;
      }
      .vp-mode-row button {
        min-width: 0;
        padding: 9px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text);
        text-align: left;
        cursor: pointer;
      }
      .vp-mode-row strong,
      .vp-evidence-card strong,
      .vp-source-grid strong {
        display: block;
        color: var(--mission-text);
      }
      .vp-mode-row small,
      .vp-evidence-card p {
        display: block;
        margin-top: 6px;
        color: var(--mission-text-muted);
        line-height: 1.34;
      }
      .vp-source-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        margin-top: 10px;
      }
      .vp-source-grid article {
        min-width: 0;
        padding: 9px 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
      }
      .vp-source-grid span {
        color: var(--mission-text-muted);
      }
      .vp-dashboard-grid {
        display: grid;
        grid-template-columns: minmax(360px, 1.18fr) minmax(320px, 0.82fr) minmax(280px, 0.72fr);
        gap: 14px;
        align-items: stretch;
      }
      .vp-attention-panel {
        grid-row: span 2;
      }
      .vp-attention-list {
        display: grid;
        gap: 10px;
      }
      .vp-attention-card {
        min-width: 0;
        padding: 13px;
        border: 1px solid var(--mission-border);
        border-left: 4px solid var(--mission-trust);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.62);
      }
      .vp-attention-card.critical {
        border-left-color: var(--mission-danger);
        background: linear-gradient(135deg, var(--mission-danger-wash), rgba(4, 8, 13, 0.66));
      }
      .vp-attention-card.watch {
        border-left-color: var(--mission-warn);
      }
      .vp-attention-card span {
        color: var(--mission-orange);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .vp-attention-card strong {
        display: block;
        margin: 6px 0;
        font-size: 18px;
        line-height: 1.15;
      }
      .vp-attention-card p {
        margin: 0;
        color: var(--mission-text-soft);
        line-height: 1.42;
      }
      .vp-attention-card small {
        display: block;
        margin-top: 8px;
        color: var(--mission-text-muted);
      }
      .card-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 10px;
      }
      .inline-action {
        min-height: 28px;
        padding: 5px 9px;
        color: var(--mission-accent);
        font-size: 12px;
        background: rgba(101, 214, 110, 0.08);
        border-color: rgba(101, 214, 110, 0.18);
      }
      .vp-map-card {
        min-height: 300px;
      }
      .vp-map-preview {
        display: grid;
        gap: 12px;
        min-height: 226px;
        padding: 12px;
        border: 1px solid rgba(101, 214, 110, 0.18);
        border-radius: var(--mission-radius);
        background:
          linear-gradient(90deg, rgba(255, 255, 255, 0.025) 1px, transparent 1px),
          linear-gradient(180deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px),
          radial-gradient(circle at 84% 8%, rgba(241, 180, 90, 0.12), transparent 32%),
          rgba(2, 7, 10, 0.68);
        background-size: 30px 30px, 30px 30px, auto, auto;
      }
      .vp-map-zone-list {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }
      .vp-map-zone-list button {
        min-width: 0;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 3px 8px;
        padding: 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(9, 18, 24, 0.82);
        color: var(--mission-text);
        text-align: left;
        cursor: pointer;
      }
      .vp-map-zone-list button.critical { border-color: rgba(240, 100, 118, 0.42); }
      .vp-map-zone-list button.elevated { border-color: rgba(241, 180, 90, 0.38); }
      .vp-map-zone-list button.stable { border-color: rgba(63, 209, 141, 0.28); }
      .vp-map-zone-list strong,
      .vp-map-zone-list small {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .vp-map-zone-list span {
        color: var(--mission-text-muted);
        font-size: 12px;
      }
      .vp-map-zone-list small {
        grid-column: 1 / -1;
        color: var(--mission-text-muted);
      }
      .vp-map-zone-list i {
        grid-column: 1 / -1;
        display: block;
        height: 5px;
        border-radius: 999px;
        background:
          linear-gradient(90deg, var(--mission-orange) calc(var(--bars) * 25%), rgba(255,255,255,0.08) 0);
      }
      .vp-map-layers,
      .vp-tier-list,
      .vp-indicator-list {
        display: grid;
        gap: 8px;
      }
      .vp-map-layers {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .vp-map-layers span {
        padding: 7px 9px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        color: var(--mission-text-soft);
        font-size: 12px;
        background: rgba(5, 10, 16, 0.72);
      }
      .vp-next-event,
      .vp-window,
      .vp-indicator-list article,
      .vp-tier-list button {
        padding: 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-inset);
        min-width: 0;
      }
      .vp-next-event span,
      .vp-window span,
      .vp-indicator-list span {
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
      }
      .vp-next-event strong,
      .vp-window strong,
      .vp-indicator-list strong,
      .vp-tier-list strong {
        display: block;
        margin: 5px 0;
        color: var(--mission-text);
      }
      .vp-window p,
      .vp-indicator-list small,
      .vp-tier-list small {
        margin: 0;
        color: var(--mission-text-muted);
        line-height: 1.38;
      }
      .vp-indicator-list article.critical { border-color: rgba(240, 100, 118, 0.32); }
      .vp-indicator-list article.elevated { border-color: rgba(241, 180, 90, 0.32); }
      .vp-decision-card strong {
        display: block;
        margin-top: 8px;
        font-size: 20px;
      }
      .vp-decision-card p {
        color: var(--mission-text-soft);
        line-height: 1.5;
      }
      .vp-decision-card small {
        color: var(--mission-text-muted);
      }
      .vp-tier-list button {
        color: inherit;
        text-align: left;
        cursor: pointer;
      }
      .vp-tier-list button:hover,
      .vp-map-zone-list button:hover {
        border-color: var(--mission-border-strong);
        background: var(--mission-panel-hi);
      }
      .vp-tier-list span {
        display: block;
        color: var(--mission-orange);
        font-size: 12px;
      }
      .vp-sentence h2 {
        max-width: 1100px;
        margin: 10px 0 8px;
        color: var(--mission-text);
        font-size: clamp(28px, 3.4vw, 46px);
        line-height: 1.04;
        font-weight: 700;
      }
      .vp-sentence p {
        margin: 0 0 18px;
        color: var(--mission-text-muted);
      }
      .now-panel ul,
      .language-list {
        margin: 12px 0 0;
        padding-left: 18px;
        color: var(--mission-text-soft);
        line-height: 1.55;
      }
      .now-panel li,
      .language-list li {
        margin: 7px 0;
      }
      .brief-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 14px;
      }
      .brief-meta span {
        padding: 5px 8px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        background: var(--mission-panel-hi);
        color: var(--mission-text-muted);
        font-size: 12px;
      }
      .line-chart {
        width: 100%;
        min-height: 150px;
        flex: 1 1 auto;
      }
      .line-chart.big { min-height: 230px; }
      .line {
        fill: none;
        stroke-width: 3;
      }
      .line.danger { stroke: var(--mission-danger); }
      .line.good { stroke: var(--mission-trust); }
      .line.muted { stroke: var(--mission-border-strong); stroke-width: 1; stroke-dasharray: 4 5; }
      .line.soft { opacity: 0.65; }
      .area.danger { fill: var(--mission-danger-wash); }
      .bar-chart {
        height: 150px;
        display: grid;
        grid-template-columns: repeat(8, minmax(0, 1fr));
        gap: 10px;
        align-items: end;
      }
      .bar-col {
        height: 100%;
        display: flex;
        flex-direction: column;
        gap: 8px;
        align-items: center;
        justify-content: flex-end;
      }
      .bar-pair {
        height: 120px;
        display: flex;
        align-items: flex-end;
        gap: 5px;
      }
      .bar {
        width: 14px;
        border-radius: 4px 4px 0 0;
        min-height: 8px;
      }
      .bar.primary { background: var(--mission-accent); }
      .bar.grey { background: rgba(156, 184, 212, 0.22); }
      .bar-col small {
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        font-variant-numeric: tabular-nums;
      }
      .ops-panel {
        display: flex;
        align-items: center;
        justify-content: space-around;
        gap: 16px;
        flex: 1 1 auto;
      }
      .donut {
        width: 132px;
        aspect-ratio: 1;
        border-radius: 50%;
        background: conic-gradient(var(--mission-trust) 0 calc(var(--value) * 1%), var(--mission-warn) 0 86%, var(--mission-danger) 0 100%);
        display: grid;
        place-items: center;
        position: relative;
      }
      .donut::after {
        content: '';
        position: absolute;
        inset: 16px;
        border-radius: 50%;
        background: var(--mission-panel-hi);
      }
      .donut strong,
      .donut span {
        position: relative;
        z-index: 1;
        grid-area: 1 / 1;
      }
      .donut strong {
        font-family: var(--ck-font-mono);
        font-size: 26px;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.01em;
        transform: translateY(-7px);
      }
      .donut span { color: var(--mission-text-muted); font-size: 11px; transform: translateY(16px); }
      .legend {
        display: flex;
        flex-direction: column;
        gap: 9px;
        color: var(--mission-text-soft);
        font-size: 12px;
        font-variant-numeric: tabular-nums;
      }
      .legend i {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 6px;
      }
      .good { color: var(--mission-trust); }
      .watch { color: var(--mission-warn); }
      .critical, .red { color: var(--mission-danger); }
      .orange { color: var(--mission-warn); }
      .green { color: var(--mission-trust); }
      .legend i.good { background: var(--mission-trust); }
      .legend i.watch { background: var(--mission-warn); }
      .legend i.critical { background: var(--mission-danger); }
      .zone-bars,
      .source-bars {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .zone-bars button,
      .source-bars div {
        display: grid;
        grid-template-columns: 92px minmax(0, 1fr) 42px;
        align-items: center;
        gap: 10px;
        color: var(--mission-text-soft);
        background: transparent;
        border: 0;
        text-align: left;
      }
      .source-bars div { grid-template-columns: 150px minmax(0, 1fr) 44px 32px; }
      .zone-bars i,
      .source-bars i {
        height: 7px;
        border-radius: 999px;
        background: var(--mission-inset);
        overflow: hidden;
      }
      .zone-bars b,
      .source-bars b {
        display: block;
        height: 100%;
        background: var(--mission-accent);
        border-radius: inherit;
      }
      .zone-bars b.critical { background: var(--mission-danger); }
      .zone-bars b.watch { background: var(--mission-warn); }
      .zone-bars b.stable { background: var(--mission-trust); }
      .compact-list,
      .agenda-list {
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .compact-list li {
        padding: 6px 0;
        color: var(--mission-text-soft);
        border-top: 1px solid var(--mission-border);
        overflow-wrap: anywhere;
      }
      .agenda-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .agenda-list li {
        display: grid;
        grid-template-columns: 48px minmax(0, 1fr);
        gap: 12px;
      }
      .agenda-list.large li {
        padding: 12px 0;
        border-bottom: 1px solid var(--mission-border);
      }
      .agenda-list time {
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
      }
      .agenda-list strong {
        display: block;
        color: var(--mission-text);
      }
      .agenda-list span { color: var(--mission-text-muted); font-size: 12px; }
      .agenda-workbench {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 380px;
        gap: 16px;
        align-items: start;
      }
      .agenda-command {
        display: grid;
        grid-template-columns: minmax(0, 1.1fr) minmax(420px, 1fr);
        gap: 18px;
        align-items: center;
      }
      .agenda-status-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
      }
      .linked-action-strip {
        grid-column: 1 / -1;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin-top: 10px;
      }
      .linked-action-strip button {
        min-width: 0;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-inset);
        color: var(--mission-text-soft);
        padding: 10px;
        text-align: left;
        cursor: pointer;
      }
      .linked-action-strip span,
      .linked-action-strip small {
        display: block;
        color: var(--mission-text-muted);
        font-size: 11px;
      }
      .linked-action-strip span.critical,
      .linked-action-strip span.high { color: var(--mission-danger); }
      .linked-action-strip span.medium { color: var(--mission-warn); }
      .linked-action-strip strong {
        display: block;
        margin: 4px 0;
        color: var(--mission-text);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .calendar-intelligence {
        grid-column: 1 / -1;
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        margin-top: 10px;
      }
      .calendar-intelligence article {
        min-width: 0;
        padding: 11px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.035), rgba(126, 205, 255, 0.035));
      }
      .calendar-intelligence span {
        color: var(--mission-warn);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .calendar-intelligence span.critical,
      .calendar-intelligence span.high { color: var(--mission-danger); }
      .calendar-intelligence article.move span { color: var(--mission-accent); }
      .calendar-intelligence strong,
      .calendar-intelligence small {
        display: block;
        overflow-wrap: anywhere;
      }
      .calendar-intelligence strong { margin: 5px 0 3px; }
      .calendar-intelligence small {
        color: var(--mission-text-muted);
        line-height: 1.35;
      }
      .agenda-status-grid article {
        min-width: 0;
        padding: 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-panel-hi);
      }
      .agenda-status-grid span,
      .agenda-status-grid small {
        display: block;
        color: var(--mission-text-muted);
        font-size: 11px;
        overflow-wrap: anywhere;
      }
      .agenda-status-grid strong {
        display: block;
        margin: 5px 0;
        color: var(--mission-text);
        font-weight: 650;
        overflow-wrap: anywhere;
      }
      .agenda-timeline-panel,
      .agenda-detail-panel {
        min-height: 560px;
      }
      .week-strip {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 12px 0 16px;
      }
      .week-strip span {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        min-height: 31px;
        padding: 5px 9px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        background: var(--mission-inset);
        color: var(--mission-text-muted);
        font-size: 12px;
        text-transform: capitalize;
      }
      .week-strip span.active {
        border-color: var(--mission-border-strong);
        color: var(--mission-accent);
        background: var(--mission-accent-wash);
      }
      .week-strip b {
        color: var(--mission-text-soft);
        font-family: var(--ck-font-mono);
        font-size: 11px;
      }
      .agenda-events {
        gap: 8px;
      }
      .agenda-events li {
        display: block;
      }
      .agenda-events button {
        width: 100%;
        display: grid;
        grid-template-columns: 72px minmax(0, 1fr) auto;
        gap: 13px;
        align-items: start;
        padding: 13px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-panel-hi);
        color: var(--mission-text);
        text-align: left;
        cursor: pointer;
      }
      .agenda-events li.active button {
        border-color: var(--mission-border-strong);
        background: var(--mission-accent-wash);
      }
      .agenda-events li.critical button { border-left: 3px solid var(--mission-danger); }
      .agenda-events li.watch button { border-left: 3px solid var(--mission-warn); }
      .agenda-events li.info button { border-left: 3px solid var(--mission-accent); }
      .agenda-events li.stable button { border-left: 3px solid var(--mission-trust); }
      .agenda-events time {
        display: grid;
        gap: 3px;
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 13px;
      }
      .agenda-events time small {
        color: var(--mission-text-faint);
        font-size: 10px;
      }
      .agenda-events p {
        margin: 5px 0 0;
        color: var(--mission-text-muted);
        font-size: 12px;
        line-height: 1.4;
      }
      .agenda-events i {
        align-self: start;
        padding: 4px 7px;
        border-radius: 999px;
        background: var(--mission-inset);
        color: var(--mission-text-muted);
        font-style: normal;
        font-size: 11px;
      }
      .agenda-detail-panel dl {
        display: grid;
        gap: 8px;
        margin: 14px 0;
      }
      .agenda-detail-panel dl div {
        display: grid;
        grid-template-columns: 92px minmax(0, 1fr);
        gap: 12px;
        padding: 9px 0;
        border-top: 1px solid var(--mission-border);
      }
      .agenda-pending-banner {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 12px;
        align-items: center;
        margin: 12px 0 16px;
        padding: 10px 12px;
        border: 1px solid rgba(242, 140, 56, 0.42);
        border-radius: var(--mission-radius);
        background: var(--agentium-aya-soft, rgba(242, 140, 56, 0.08));
      }
      .agenda-pending-copy strong {
        display: block;
        margin-top: 2px;
        font-size: 13px;
        font-weight: 600;
        color: var(--mission-text-primary);
      }
      .agenda-pending-copy p {
        margin: 4px 0 0;
        color: var(--mission-text-soft);
        font-size: 12px;
      }
      .agenda-pending-actions {
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-width: 160px;
      }
      .agenda-actions {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin: 14px 0;
      }
      .agenda-actions button {
        min-height: 34px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-panel-hi);
        color: var(--mission-text-soft);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        cursor: pointer;
      }
      .agenda-actions button.danger {
        border-color: rgba(240, 100, 118, 0.26);
        color: var(--mission-danger);
        background: var(--mission-danger-wash);
      }
      .agenda-odj {
        margin: 14px 0 6px;
        padding: 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.42);
      }
      .agenda-odj-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
      }
      .agenda-odj .eyebrow {
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }
      .agenda-odj-list {
        margin: 0;
        padding-left: 18px;
        display: grid;
        gap: 6px;
      }
      .agenda-odj-list li {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        gap: 8px;
        align-items: center;
        padding: 6px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-panel-hi, rgba(4, 8, 13, 0.32));
      }
      .agenda-odj-list input[type="text"] {
        min-height: 30px;
        padding: 0 8px;
        border: 1px solid transparent;
        background: transparent;
        color: inherit;
        font: inherit;
        font-size: 12px;
        min-width: 0;
      }
      .agenda-odj-list input[type="text"]:focus {
        outline: none;
        border-color: rgba(125, 211, 252, 0.35);
        background: rgba(4, 8, 13, 0.6);
        border-radius: var(--mission-radius-sm);
      }
      .agenda-odj-meta {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
      }
      .agenda-source-badge {
        padding: 2px 6px;
        border-radius: 999px;
        border: 1px solid var(--mission-border);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.06em;
        color: var(--mission-text-muted);
      }
      .agenda-source-badge.source-aya {
        border-color: rgba(101, 214, 110, 0.32);
        color: var(--mission-trust);
        background: var(--mission-trust-wash);
      }
      .agenda-source-badge.source-brief {
        border-color: rgba(241, 180, 90, 0.32);
        color: var(--mission-warn);
        background: rgba(241, 180, 90, 0.08);
      }
      .agenda-source-badge.source-vp {
        border-color: rgba(125, 211, 252, 0.28);
        color: var(--mission-accent);
        background: rgba(125, 211, 252, 0.08);
      }
      .agenda-decision-pill {
        padding: 2px 6px;
        border-radius: 999px;
        border: 1px solid rgba(241, 180, 90, 0.32);
        color: var(--mission-warn);
        font-size: 10px;
      }
      .ghost-icon {
        width: 24px;
        height: 24px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: transparent;
        color: var(--mission-text-muted);
        cursor: pointer;
        font: inherit;
        line-height: 1;
      }
      .ghost-link {
        padding: 4px 9px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: transparent;
        color: var(--mission-text);
        font: inherit;
        font-size: 11px;
        cursor: pointer;
      }
      .empty-line {
        margin: 6px 0 0;
        color: var(--mission-text-faint);
        font-size: 12px;
      }
      .meeting-cta {
        margin-top: 8px;
      }
      .meeting-decisions-panel .meeting-decisions-source {
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
      }
      .meeting-decisions-list {
        display: grid;
        gap: 8px;
        margin-top: 8px;
      }
      .meeting-decision-card {
        padding: 10px 12px;
        border: 1px solid var(--mission-border);
        border-left: 3px solid var(--mission-trust);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.42);
      }
      .meeting-decision-card header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
      }
      .meeting-decision-card strong {
        font-size: 13px;
      }
      .meeting-decision-card small {
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 10px;
      }
      .meeting-decision-choice {
        margin: 6px 0 0;
        color: var(--mission-text-soft, var(--mission-text));
        font-size: 12px;
      }
      .meeting-decision-choice em {
        font-style: normal;
        color: var(--mission-trust);
        font-family: var(--ck-font-mono);
      }
      .meeting-decision-rationale {
        margin: 4px 0 0;
        color: var(--mission-text-muted);
        font-size: 12px;
        line-height: 1.4;
      }
      .agenda-form {
        margin-top: 18px;
        padding-top: 16px;
        border-top: 1px solid var(--mission-border);
        display: grid;
        gap: 9px;
      }
      .agenda-form input {
        min-height: 38px;
        border: 1px solid var(--mission-border);
        background: var(--mission-inset);
        color: var(--mission-text);
        border-radius: var(--mission-radius);
        padding: 0 11px;
        min-width: 0;
      }
      .keyword-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 8px;
      }
      .keyword-grid.compact { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .keyword-grid article {
        padding: 12px;
        border-radius: var(--mission-radius);
        background: var(--mission-panel-hi);
        border: 1px solid var(--mission-border);
        min-width: 0;
      }
      .keyword-grid span,
      .keyword-grid small {
        display: block;
        color: var(--mission-text-muted);
        font-size: 11px;
        overflow-wrap: anywhere;
      }
      .keyword-grid strong {
        display: block;
        margin-top: 6px;
        font-family: var(--ck-font-mono);
        font-size: 20px;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.01em;
      }
      .keyword-grid small { color: var(--mission-trust); }
      .keyword-grid small.down { color: var(--mission-danger); }
      .two-column {
        display: grid;
        grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
        gap: 16px;
        align-items: start;
      }
      .ministerial-news {
        display: grid;
        grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
        gap: 16px;
        align-items: start;
      }
      .span-2 { grid-column: 1 / -1; }
      .content-panel {
        padding: 18px;
        border: 1px solid var(--mission-border);
        background: var(--mission-panel);
        border-radius: var(--mission-radius);
        box-shadow: var(--mission-shadow-card);
        min-width: 0;
      }
      .content-panel h2,
      .content-panel h3 {
        margin: 8px 0 8px;
        font-weight: 650;
        letter-spacing: -0.01em;
      }
      .content-panel p {
        color: var(--mission-text-soft);
        line-height: 1.55;
      }
      .news-brief-hero {
        background:
          linear-gradient(135deg, rgba(139, 216, 255, 0.10), rgba(66, 217, 155, 0.04)),
          var(--mission-panel);
      }
      .maritime-news-panel {
        border-color: rgba(255, 155, 74, 0.22);
        background:
          linear-gradient(135deg, rgba(255, 155, 74, 0.08), rgba(66, 217, 155, 0.035)),
          var(--mission-panel);
      }
      .maritime-news-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin-top: 14px;
      }
      .maritime-news-grid a,
      .maritime-news-grid article {
        min-width: 0;
        padding: 12px;
        border: 1px solid rgba(255, 155, 74, 0.16);
        border-radius: 7px;
        background: rgba(255, 155, 74, 0.045);
        text-decoration: none;
      }
      .maritime-news-grid strong,
      .maritime-news-grid small {
        display: block;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .maritime-news-grid strong {
        color: var(--mission-text);
        font-size: 13px;
        white-space: nowrap;
      }
      .maritime-news-grid small {
        margin-top: 5px;
        color: var(--mission-orange);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        text-transform: uppercase;
        white-space: nowrap;
      }
      .maritime-news-grid p {
        margin: 8px 0 0;
        font-size: 12px;
        line-height: 1.38;
      }
      .compact-row {
        margin-top: 14px;
      }
      .compact-row > small {
        color: var(--mission-text-muted);
        line-height: 1.4;
      }
      .health-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin: 14px 0;
      }
      .health-grid article {
        padding: 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-panel-hi);
      }
      .health-grid strong,
      .health-grid span {
        display: block;
      }
      .health-grid strong {
        font-family: var(--ck-font-mono);
        font-size: 22px;
        color: var(--mission-accent);
      }
      .health-grid span {
        margin-top: 4px;
        color: var(--mission-text-muted);
        font-size: 12px;
      }
      .news-geo-tabs,
      .badge-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .news-geo-tabs button {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-height: 34px;
        padding: 7px 10px;
        border: 1px solid var(--mission-border);
        border-radius: 7px;
        background: rgba(5, 12, 10, 0.66);
        color: var(--mission-text-soft);
        font: inherit;
        cursor: pointer;
      }
      .news-geo-tabs button.active,
      .news-geo-tabs button:hover {
        border-color: rgba(66, 217, 155, 0.45);
        background: rgba(22, 58, 42, 0.76);
        color: var(--mission-text);
      }
      .news-geo-tabs strong {
        font-size: 12px;
      }
      .news-geo-tabs span,
      .badge-row span {
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 10px;
      }
      .badge-row span {
        padding: 4px 6px;
        border: 1px solid rgba(151, 185, 164, 0.14);
        border-radius: 999px;
        color: var(--mission-text-muted);
      }
      .executive-alert-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
      }
      .executive-alert-card {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .executive-alert-card .panel-heading-row small {
        color: var(--mission-text-muted);
        text-align: right;
      }
      .executive-alert-card dl {
        display: grid;
        gap: 10px;
        margin: 0;
      }
      .executive-alert-card dl div {
        padding-top: 10px;
        border-top: 1px solid var(--mission-border);
      }
      .executive-alert-card dt {
        margin-bottom: 4px;
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
      }
      .executive-alert-card dd {
        margin: 0;
        color: var(--mission-text-soft);
        line-height: 1.45;
      }
      .executive-alert-card.highlighted,
      .decision-arbitration-card.highlighted {
        border-color: rgba(242, 140, 56, 0.55);
        box-shadow: 0 0 0 1px rgba(242, 140, 56, 0.18), 0 0 24px rgba(242, 140, 56, 0.08);
      }
      .decision-arbitration-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }
      .decision-arbitration-card {
        min-width: 0;
        padding: 13px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.62);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
      }
      .decision-arbitration-card.critical {
        border-color: rgba(240, 100, 118, 0.34);
        background: linear-gradient(135deg, var(--mission-danger-wash), rgba(4, 8, 13, 0.66));
      }
      .decision-arbitration-card span {
        display: block;
        color: var(--mission-orange);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .decision-arbitration-card strong {
        display: block;
        margin-top: 6px;
        font-size: 15px;
        line-height: 1.25;
      }
      .decision-arbitration-card p {
        margin: 7px 0 0;
        color: var(--mission-text-muted);
        font-size: 12px;
        line-height: 1.4;
      }
      .decision-arbitration-card footer {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        margin-top: 10px;
      }
      .decision-arbitration-card footer em {
        font-style: normal;
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--mission-warn);
      }
      .option-compare-panel {
        display: grid;
        gap: 10px;
      }
      .reputation-drill-panel {
        display: grid;
        gap: 12px;
      }
      .reputation-balance-band {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 12px;
        border: 1px solid rgba(101, 214, 110, 0.28);
        border-radius: var(--mission-radius);
        background: linear-gradient(135deg, rgba(101, 214, 110, 0.10), rgba(8, 14, 20, 0.78));
      }
      .reputation-balance-band span,
      .doc-context-grid span {
        display: block;
        margin-bottom: 4px;
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .reputation-balance-band strong {
        color: var(--mission-text);
        font-size: 14px;
      }
      .reputation-detail-layout {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(320px, 0.42fr);
        gap: 12px;
        align-items: start;
      }
      .reputation-drill-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
      }
      .reputation-drill-card {
        display: grid;
        gap: 8px;
        padding: 12px;
        min-width: 0;
        border-radius: var(--mission-radius);
        border: 1px solid var(--mission-border);
        background: var(--mission-inset);
        border-left: 3px solid var(--mission-border);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
      }
      .reputation-drill-card.positive { border-left-color: rgba(101, 214, 110, 0.65); }
      .reputation-drill-card.critical { border-left-color: rgba(240, 100, 118, 0.65); }
      .reputation-drill-card:hover,
      .reputation-drill-card.active {
        border-color: rgba(101, 214, 110, 0.42);
        background: rgba(15, 111, 63, 0.10);
      }
      .reputation-drill-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .reputation-drill-tag {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--mission-text-muted);
      }
      .reputation-drill-card.positive .reputation-drill-tag { color: rgba(101, 214, 110, 0.95); }
      .reputation-drill-card.critical .reputation-drill-tag { color: rgba(240, 100, 118, 0.95); }
      .reputation-drill-engagement {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        color: var(--mission-text-faint);
      }
      .reputation-drill-card h3 {
        margin: 0;
        font-size: 14px;
        color: var(--mission-text);
      }
      .reputation-drill-card p {
        margin: 0;
        color: var(--mission-text-soft);
        font-size: 12px;
        line-height: 1.4;
      }
      .reputation-drill-foot {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        font-size: 11px;
        color: var(--mission-text-faint);
      }
      .reputation-drill-source {
        font-family: var(--ck-font-mono);
      }
      .reputation-drill-link {
        color: var(--mission-accent);
        text-decoration: none;
      }
      .reputation-drill-link:hover { text-decoration: underline; }
      .reputation-active-detail {
        position: sticky;
        top: 84px;
        display: grid;
        gap: 12px;
        padding: 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(8, 14, 20, 0.78);
      }
      .reputation-active-detail h3 {
        margin: 0;
        font-size: 16px;
        color: var(--mission-text);
      }
      .reputation-active-detail p {
        margin: 0;
        color: var(--mission-text-soft);
        font-size: 13px;
        line-height: 1.5;
      }
      .reputation-active-detail dl {
        margin: 0;
        display: grid;
        gap: 8px;
      }
      .reputation-active-detail dl div {
        display: grid;
        grid-template-columns: 82px minmax(0, 1fr);
        gap: 10px;
      }
      .reputation-active-detail dt {
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .reputation-active-detail dd {
        margin: 0;
        color: var(--mission-text-soft);
        font-size: 12px;
        line-height: 1.4;
      }
      .chart-label {
        fill: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.04em;
      }
      .chart-label.right { text-anchor: end; }
      .chart-label.current-label { fill: var(--mission-trust); }
      .chart-label.muted-label { fill: rgba(151, 185, 164, 0.5); }
      .chart-current-point {
        fill: var(--mission-trust);
        stroke: rgba(4, 8, 13, 0.9);
        stroke-width: 3px;
      }

      .securite-shell { display: grid; gap: var(--mission-space-4); }
      .securite-council-bar {
        position: sticky;
        top: var(--mission-space-3);
        z-index: 8;
        display: flex;
        align-items: center;
        gap: 16px;
        flex-wrap: wrap;
        padding: 12px 16px;
        border: 1px solid rgba(240, 100, 118, 0.35);
        border-radius: var(--mission-radius-lg);
        background: linear-gradient(135deg, rgba(240, 100, 118, 0.14), rgba(8, 14, 20, 0.92));
        box-shadow: var(--mission-shadow-soft);
        backdrop-filter: blur(12px);
      }
      .securite-council-bar strong { color: #fda4af; }
      .securite-tabs { display: flex; gap: 8px; }
      .securite-tabs button {
        padding: 8px 14px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        background: transparent;
        color: var(--mission-text-secondary);
        cursor: pointer;
      }
      .securite-tabs button.active {
        background: rgba(15, 111, 63, 0.18);
        color: var(--mission-text-primary);
        border-color: rgba(15, 111, 63, 0.45);
      }
      .securite-stack {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--mission-space-4);
        align-items: start;
      }
      .security-doc-workbench {
        display: grid;
        grid-template-columns: minmax(280px, 0.42fr) minmax(0, 1fr);
        gap: 12px;
        margin-top: 12px;
        align-items: start;
      }
      .securite-doc-list {
        display: grid;
        gap: 10px;
      }
      .securite-doc-card {
        display: grid;
        gap: 8px;
        padding: 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(8, 14, 20, 0.55);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
      }
      .securite-doc-card:hover,
      .securite-doc-card.active {
        border-color: rgba(101, 214, 110, 0.42);
        background: rgba(15, 111, 63, 0.11);
      }
      .securite-doc-card strong {
        font-size: 14px;
        line-height: 1.25;
        color: var(--mission-text);
      }
      .securite-doc-card small {
        color: var(--mission-text-secondary);
        overflow-wrap: anywhere;
      }
      .security-doc-detail {
        display: grid;
        gap: 14px;
        min-width: 0;
        padding: 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.55);
      }
      .security-doc-detail h3 {
        margin: 0;
        font-size: 18px;
        color: var(--mission-text);
      }
      .security-doc-detail p {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: 13px;
        line-height: 1.5;
      }
      .doc-context-grid {
        display: grid;
        grid-template-columns: minmax(0, 0.45fr) minmax(0, 1fr);
        gap: 10px;
      }
      .doc-context-grid article {
        min-width: 0;
        padding: 10px;
        border: 1px solid rgba(151, 185, 164, 0.16);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
      }
      .doc-context-grid strong {
        display: block;
        color: var(--mission-text);
        font-size: 13px;
        line-height: 1.35;
      }
      .doc-excerpt {
        padding: 12px;
        border: 1px solid rgba(242, 140, 56, 0.24);
        border-radius: var(--mission-radius-sm);
        background: rgba(242, 140, 56, 0.07);
      }
      .doc-source-row { margin-top: 0; }
      .doc-source-empty {
        color: var(--mission-text-faint);
        font-size: 12px;
      }
      .doc-action-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .inline-action.primary {
        border-color: rgba(101, 214, 110, 0.42);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
      }
      .securite-doc-card:focus-visible,
      .reputation-drill-card:focus-visible,
      .inline-action:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }

      @media (max-width: 980px) {
        .reputation-detail-layout,
        .reputation-drill-grid {
          grid-template-columns: 1fr;
        }
        .reputation-active-detail { position: static; }
        .securite-stack,
        .security-doc-workbench,
        .doc-context-grid { grid-template-columns: 1fr; }
      }
      .option-compare-head,
      .option-compare-row {
        display: grid;
        grid-template-columns: 120px minmax(0, 1fr) 72px;
        gap: 10px;
        align-items: center;
      }
      .option-compare-head span {
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .option-compare-row label {
        color: var(--mission-text-soft);
        font-size: 12px;
      }
      .compare-bars {
        display: flex;
        gap: 6px;
        align-items: center;
      }
      .compare-bars i {
        display: block;
        height: 8px;
        min-width: 0;
        border-radius: 999px;
        background: var(--mission-accent);
      }
      .compare-bars i + i {
        background: rgba(125, 211, 252, 0.35);
      }
      .compare-bars i.recommended {
        background: var(--mission-trust);
        box-shadow: 0 0 0 1px rgba(101, 214, 110, 0.28);
      }
      .option-compare-row small {
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        text-align: right;
      }
      .action-panel {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .project-risk-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 10px;
      }
      .project-risk-grid article {
        min-width: 0;
        padding: 11px;
        border: 1px solid var(--mission-border);
        border-left: 3px solid var(--mission-warn);
        border-radius: var(--mission-radius);
        background: var(--mission-inset);
      }
      .project-risk-grid article.red { border-left-color: var(--mission-danger); }
      .project-risk-grid strong,
      .project-risk-grid span,
      .project-risk-grid small {
        display: block;
        overflow-wrap: anywhere;
      }
      .project-risk-grid span {
        margin: 5px 0;
        color: var(--mission-orange);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        text-transform: uppercase;
      }
      .project-risk-grid small {
        color: var(--mission-text-muted);
        line-height: 1.35;
      }
      .project-risk-list {
        display: grid;
        gap: 8px;
        margin-top: 16px;
      }
      .project-risk-list button {
        display: grid;
        gap: 4px;
        width: 100%;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-inset);
        color: var(--mission-text);
        padding: 10px;
        text-align: left;
        cursor: pointer;
      }
      .project-risk-list small {
        color: var(--mission-text-muted);
        line-height: 1.35;
      }
      .project-summary span,
      .option-list span,
      .collection-list span,
      .status-pill {
        padding: 6px 9px;
        border-radius: 999px;
        background: var(--mission-panel-hi);
        border: 1px solid var(--mission-border);
        font-size: 12px;
      }
      .project-list,
      .decision-list,
      .library-list,
      .message-list,
      .prompt-list,
      .collection-list {
        display: flex;
        flex-direction: column;
        gap: 10px;
        margin-top: 14px;
      }
      .collection-list { flex-direction: row; flex-wrap: wrap; }
      .project-list button,
      .decision-list button,
      .prompt-list button {
        width: 100%;
        text-align: left;
        border: 1px solid var(--mission-border);
        background: var(--mission-panel-hi);
        color: var(--mission-text);
        border-radius: var(--mission-radius);
        padding: 12px;
        display: grid;
        gap: 6px;
        cursor: pointer;
      }
      .project-list button.active {
        border-color: var(--mission-border-strong);
        background: var(--mission-accent-wash);
      }
      .decision-kpis {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin: 14px 0;
      }
      .decision-kpis article,
      .action-linked {
        padding: 11px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-inset);
      }
      .decision-kpis strong,
      .decision-kpis span,
      .action-linked strong,
      .action-linked span,
      .action-linked small {
        display: block;
      }
      .decision-kpis strong {
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 21px;
      }
      .decision-kpis span,
      .action-linked span,
      .action-linked small {
        color: var(--mission-text-muted);
        font-size: 11px;
      }
      .action-linked {
        margin: 12px 0 0;
      }
      .action-linked strong {
        margin: 4px 0;
        color: var(--mission-text);
      }
      .scenario-grid,
      .action-item-list,
      .window-list {
        display: grid;
        gap: 10px;
        margin-top: 12px;
      }
      .scenario-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .scenario-grid article,
      .action-item-list article,
      .window-list article {
        min-width: 0;
        padding: 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-panel-hi);
      }
      .scenario-grid article.recommended {
        border-color: var(--mission-border-strong);
        background: var(--mission-accent-wash);
      }
      .scenario-grid strong,
      .scenario-grid span,
      .scenario-grid small,
      .window-list time,
      .window-list strong,
      .window-list small {
        display: block;
      }
      .scenario-grid span,
      .window-list time {
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 11px;
      }
      .scenario-grid p {
        margin: 6px 0;
        font-size: 13px;
      }
      .scenario-grid.compact { grid-template-columns: 1fr; }
      .scenario-metrics {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-top: 8px;
      }
      .scenario-metrics i {
        padding: 4px 7px;
        border-radius: 999px;
        border: 1px solid var(--mission-border);
        color: var(--mission-text-muted);
        font-style: normal;
        font-size: 10px;
      }
      .scenario-grid small,
      .window-list small {
        color: var(--mission-text-muted);
        line-height: 1.4;
      }
      .action-item-list article {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 12px;
        align-items: center;
      }
      .action-item-list article.done,
      .action-item-list article.cancelled {
        opacity: 0.62;
      }
      .action-item-list p {
        margin: 5px 0 0;
        font-size: 12px;
      }
      .action-row {
        display: flex;
        gap: 7px;
        flex-wrap: wrap;
      }
      .action-row button {
        min-height: 31px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-inset);
        color: var(--mission-text-soft);
        padding: 6px 9px;
        cursor: pointer;
      }
      .action-row button.danger {
        border-color: rgba(240, 100, 118, 0.26);
        color: var(--mission-danger);
        background: var(--mission-danger-wash);
      }
      .action-row button:disabled {
        cursor: not-allowed;
        opacity: 0.45;
      }
      .window-list article {
        display: grid;
        grid-template-columns: 86px minmax(0, 1fr);
        gap: 10px;
      }
      .map-system-strip,
      .driver-list {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin: 10px 0 12px;
      }
      .map-system-strip {
        justify-content: space-between;
        color: var(--mission-text-muted);
        font-size: 12px;
      }
      .driver-list span {
        padding: 5px 8px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        background: var(--mission-panel-hi);
        color: var(--mission-text-soft);
        font-size: 11px;
      }
      .project-list small,
      .decision-list small,
      .library-list small {
        color: var(--mission-text-muted);
      }
      .selected-detail dl {
        display: grid;
        gap: 8px;
        margin: 14px 0;
      }
      .selected-detail dl div {
        display: grid;
        grid-template-columns: 120px minmax(0, 1fr);
        gap: 12px;
        padding: 8px 0;
        border-top: 1px solid var(--mission-border);
      }
      dt { color: var(--mission-text-faint); }
      dd { margin: 0; color: var(--mission-text-soft); }
      .message-list article,
      .library-list article {
        padding: 13px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: var(--mission-panel-hi);
      }
      .message-list article {
        display: grid;
        grid-template-columns: 64px minmax(0, 1fr);
        gap: 12px;
      }
      .message-list time {
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
      }
      .message-list span {
        display: block;
        color: var(--mission-text-muted);
        margin-top: 3px;
      }
      .status-pill.high,
      .status-pill.critical { color: var(--mission-danger); background: var(--mission-danger-wash); }
      .status-pill.medium { color: var(--mission-warn); background: var(--mission-warn-wash); }
      .map-layout {
        grid-template-columns: minmax(0, 2.15fr) minmax(340px, 0.65fr);
      }
      .md {
        position: absolute;
        right: 18px;
        bottom: 18px;
        width: min(320px, calc(100% - 36px));
        padding: 14px 16px;
        border: 1px solid rgba(180, 136, 255, 0.35);
        border-radius: var(--mission-radius-lg);
        background: rgba(8, 12, 20, 0.94);
      }
      .md header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 8px;
      }
      .territory-map {
        width: 100%;
        min-height: 560px;
        border-radius: var(--mission-radius);
        background:
          linear-gradient(var(--mission-bg-grid) 1px, transparent 1px),
          linear-gradient(90deg, var(--mission-bg-grid) 1px, transparent 1px),
          var(--mission-inset);
        background-size: 28px 28px;
        border: 1px solid var(--mission-border);
      }
      .territory-map polygon {
        stroke: rgba(244, 247, 251, 0.28);
        stroke-width: 2;
        cursor: pointer;
        transition: opacity 120ms;
      }
      .territory-map text {
        fill: var(--mission-text);
        font-family: var(--ck-font-sans);
        font-size: 16px;
        font-weight: 700;
        pointer-events: none;
      }
      .search-form {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 10px;
        margin-top: 16px;
      }
      .search-form input {
        min-height: 40px;
        border: 1px solid var(--mission-border);
        background: var(--mission-inset);
        color: var(--mission-text);
        border-radius: var(--mission-radius);
        padding: 0 12px;
      }
      .map-mode-shell { display: grid; gap: 12px; }
      .map-mode-tabs {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .map-mode-tabs button {
        min-height: 34px;
        padding: 8px 12px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        background: rgba(4, 8, 13, 0.58);
        color: var(--mission-text-soft);
        font: inherit;
        font-size: 12px;
        cursor: pointer;
      }
      .map-mode-tabs button.active {
        border-color: rgba(125, 211, 252, 0.42);
        color: var(--mission-accent);
        background: rgba(125, 211, 252, 0.08);
      }
      .decisions-split-layout {
        display: grid;
        grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.85fr);
        gap: 12px;
        align-items: start;
      }
      .decision-arbitration-card.active {
        border-color: rgba(125, 211, 252, 0.42);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.12);
      }
      .draft-sidebar { position: sticky; top: 12px; }
      .compact-news-list { grid-template-columns: 1fr !important; }
      .executive-alert-card.compact p { margin-bottom: 0; }
      .press-article-card {
        width: 100%;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
        color: inherit;
        transition:
          border-color var(--mission-dur-fast, 120ms) ease,
          box-shadow var(--mission-dur-fast, 120ms) ease;
      }
      .press-article-card:hover,
      .press-article-card:focus-visible {
        border-color: rgba(66, 217, 155, 0.42);
        outline: none;
      }
      .press-article-card:focus-visible {
        box-shadow: 0 0 0 2px rgba(66, 217, 155, 0.24);
      }
      .publisher-badge {
        display: inline-flex;
        margin-top: 8px;
        padding: 3px 8px;
        border: 1px solid rgba(66, 217, 155, 0.22);
        border-radius: 999px;
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .brief-priority-list {
        display: grid;
        gap: 8px;
        margin: 14px 0 0;
        padding: 0;
        list-style: none;
      }
      .brief-priority-item {
        width: 100%;
        padding: 10px 12px;
        border: 1px solid rgba(66, 217, 155, 0.18);
        border-radius: 7px;
        background: rgba(22, 58, 42, 0.28);
        color: var(--mission-text-soft);
        text-align: left;
        font: inherit;
        line-height: 1.45;
        cursor: pointer;
      }
      .brief-priority-item:hover,
      .brief-priority-item:focus-visible {
        border-color: rgba(66, 217, 155, 0.42);
        color: var(--mission-text);
        outline: none;
      }
      .press-drill-footer {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
        justify-content: space-between;
      }
      .press-see-all,
      .press-kpi-link {
        border: 0;
        background: transparent;
        color: var(--mission-accent);
        font: inherit;
        font-size: 12px;
        cursor: pointer;
        text-decoration: underline;
        text-underline-offset: 3px;
      }
      .press-kpi-link {
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        text-decoration: none;
      }
      .press-kpi-link:hover,
      .press-see-all:hover {
        color: var(--mission-text);
      }
      .press-full-list {
        display: grid;
        gap: 10px;
        max-height: min(62vh, 720px);
        overflow-y: auto;
        padding-right: 4px;
      }
      .press-list-row h3 {
        margin: 0;
        font-size: 15px;
      }
      @media (max-width: 1200px) {
        .mission-shell { grid-template-columns: 200px minmax(0, 1fr); }
        .mission-main { padding: 24px; }
        .vp-directive-layout,
        .vp-c2-strip,
        .vp-dashboard-grid,
        .executive-alert-grid, .maritime-news-grid { grid-template-columns: 1fr; }
        .vp-status-bar { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .two-column, .ministerial-news, .map-layout, .agenda-workbench, .agenda-command { grid-template-columns: 1fr; }
        .agenda-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .linked-action-strip,
        .calendar-intelligence,
        .scenario-grid { grid-template-columns: 1fr; }
      }
      @media (max-width: 840px) {
        :host { height: auto; overflow: auto; }
        .mission-shell { min-height: 100vh; grid-template-columns: 1fr; }
        app-mission-rail { position: sticky; top: 0; z-index: 5; }
        .mission-main { padding: 20px 14px; }
        .mission-hero,
        .vp-status-bar,
        .vp-directive-layout,
        .vp-c2-strip,
        .vp-mode-row,
        .vp-source-grid,
        .vp-dashboard-grid,
        .vp-map-zone-list,
        .vp-map-layers,
        .project-risk-grid,
        .search-form {
          grid-template-columns: 1fr;
          display: grid;
        }
      }
    `,
  ],
})
export class MissionRoomComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly chat = inject(ChatOverlayService);
  private readonly assistantEffects = inject(AssistantEffectsService);
  private readonly maritimeTracking = inject(MaritimeTrackingService);
  private readonly workspaceExperienceShadow = inject(WorkspaceExperienceShadowService);
  private readonly abidjanTimeZone = 'Africa/Abidjan';
  protected readonly workspace = inject(WorkspaceService);
  /**
   * AIS vessel positions fed into the strategic <app-workspace-map>.
   * Sourced from the shared `MaritimeTrackingService` so both the cockpit
   * preview and the full-screen strategic map render the same snapshot
   * (and so toggling the maritime layer reveals real vessels everywhere).
   */
  readonly strategicVessels = signal<VesselPosition[]>([]);
  readonly selectedStrategicVessel = signal<VesselPosition | null>(null);
  private maritimeVesselsSub: Subscription | null = null;

  private readonly routeView = toSignal(
    this.route.paramMap.pipe(map((params) => (params.get('view') || 'cockpit') as MissionView)),
    { initialValue: 'cockpit' as MissionView },
  );
  private readonly videoDemoMode = toSignal(
    this.route.queryParamMap.pipe(map((params) => params.get('videoDemo') || '')),
    { initialValue: '' },
  );

  readonly loading = signal(true);
  readonly abidjanNow = signal(new Date());
  readonly navigation = signal<MissionNavigation | null>(null);
  readonly cockpit = signal<MissionCockpit | null>(null);
  readonly briefing = signal<MissionBriefing | null>(null);
  readonly projects = signal<MissionProjects | null>(null);
  readonly missionMap = signal<MissionMap | null>(null);
  readonly monitor = signal<MissionMonitor | null>(null);
  readonly news = signal<MissionNews | null>(null);
  readonly timeline = signal<MissionTimeline | null>(null);
  readonly decisions = signal<MissionDecisions | null>(null);
  readonly library = signal<MissionLibrary | null>(null);
  readonly search = signal<MissionSearch | null>(null);
  readonly selectedProject = signal<Project | null>(null);
  readonly selectedZone = signal<MapZone | null>(null);
  readonly videoDemoOctaveChat = computed(() => this.videoDemoMode() === 'octaveChat');
  readonly selectedArbitrationCard = signal<VpArbitrationCard | null>(null);
  readonly selectedSource = signal<SourceRef | null>(null);
  readonly selectedAgendaEvent = signal<AgendaItem | null>(null);
  readonly agendaPendingPatch = signal<AgendaPendingPatch | null>(null);
  readonly agendaPatchSubmitting = signal(false);
  readonly draft = signal<DraftInstruction | null>(null);
  readonly meetingDecisionsLog = signal<MeetingDecisionLogEntry[]>([]);
  readonly mapCommandState = signal<Record<string, unknown> | null>(null);
  readonly activePortWebcam = signal<Record<string, unknown> | null>(null);
  readonly visualCaptureImages = signal<Record<string, string>>({});
  readonly activeNewsGeoTier = signal<'ci' | 'cedeao' | 'africa' | 'world'>('ci');
  readonly selectedPressArticle = signal<NewsSignal | null>(null);
  readonly pressArticleListOpen = signal(false);
  readonly pressArticleListRiskSort = signal(false);
  readonly morningHighlightDismissed = signal(this.readMorningDismissed());
  readonly s3FocusTarget = signal<string | null>(null);
  readonly selectedSecurityDocId = signal<string | null>(null);
  readonly selectedRumorStep = signal<number | null>(null);
  readonly selectedReputationItemId = signal<string | null>(null);
  private readonly highlightQuery = toSignal(
    this.route.queryParamMap.pipe(map((params) => params.get('highlight'))),
    { initialValue: null as string | null },
  );
  private readonly layersQuery = toSignal(
    this.route.queryParamMap.pipe(map((params) => params.get('layers'))),
    { initialValue: null as string | null },
  );
  private readonly zoneQuery = toSignal(
    this.route.queryParamMap.pipe(map((params) => params.get('zone'))),
    { initialValue: null as string | null },
  );
  private readonly modeQuery = toSignal(
    this.route.queryParamMap.pipe(map((params) => params.get('mode'))),
    { initialValue: null as string | null },
  );
  private readonly focusQuery = toSignal(
    this.route.queryParamMap.pipe(map((params) => params.get('focus'))),
    { initialValue: null as string | null },
  );
  private readonly abidjanFullDateFormatter = new Intl.DateTimeFormat('fr-FR', {
    timeZone: this.abidjanTimeZone,
    weekday: 'long',
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  });
  private readonly abidjanShortDateFormatter = new Intl.DateTimeFormat('fr-FR', {
    timeZone: this.abidjanTimeZone,
    day: '2-digit',
    month: 'short',
  });
  private readonly abidjanHourFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: this.abidjanTimeZone,
    hour: '2-digit',
    hour12: false,
  });

  searchQueryValue = '';
  newAgendaTitle = '';
  newAgendaStart = this.defaultAgendaStartValue();
  newAgendaLocation = 'Cabinet Vice Premier Ministre';
  private readonly visualObjectUrls: string[] = [];
  private abidjanClockTimer: ReturnType<typeof setInterval> | null = null;
  private workspaceContinuationGeneration = 0;
  private workspaceActionRequests = new Subscription();
  private unregisterWorkspaceReset: () => void = () => undefined;
  private destroyed = false;
  private readonly calendarUpdateListener = () => this.loadAll(false);
  private readonly workspaceActionUpdateListener = () => this.loadAll(false);
  private focusQuerySub: Subscription | null = null;
  private s3FocusTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly mapCommandListener = (event: Event) => {
    const detail = (event as CustomEvent<Record<string, unknown>>).detail || {};
    const mapState = (detail['map_state'] as Record<string, unknown>) || null;
    const target = String(detail['target'] || mapState?.['selected_zone'] || '');
    const selectedPort = String(mapState?.['selected_port'] || '');
    const intent = String(detail['intent'] || '');
    const zone = [...(this.missionMap()?.zones || []), ...(this.monitor()?.zones || [])].find((item) => item.id === target);
    if (zone) this.selectedZone.set(zone);
    this.mapCommandState.set(mapState);
    if (target || mapState) {
      const liveMaritime = !!selectedPort || intent === 'show_vessel_snapshot' || intent === 'focus_port';
      const queryParams: Record<string, string | undefined> = liveMaritime
        ? {
          mode: 'live',
          panel: 'maritime',
          port: selectedPort || target || undefined,
          vessel: intent === 'show_vessel_snapshot' ? 'mv-atlantic-trader' : undefined,
        }
        : { mode: 'territory', zone: target || undefined };
      this.router.navigate(['/hypervisor/mission-room/strategie'], { queryParams });
    }
  };
  private readonly assistantNavigateListener = (event: Event) => {
    const detail = (event as CustomEvent<AssistantNavigateEffect>).detail;
    if (!detail?.route) return;
    // Router navigation is handled globally in AssistantEffectsService so
    // assistant-navigate still works from routes outside MissionRoom (S3.4→S3.5).
    this.applyAssistantFocus(detail);
    if (detail.route.includes('/reputation') || detail.highlight === 'reputation-drill') {
      setTimeout(() => this.scrollToHighlight(), 220);
    }
  };
  private readonly assistantProposeListener = (event: Event) => {
    const detail = (event as CustomEvent<AssistantProposeEffect>).detail;
    if (!detail?.prompt) return;
    this.openAssistant(detail.prompt);
  };
  private readonly assistantShowWebcamListener = (event: Event) => {
    const detail = (event as CustomEvent<Record<string, unknown>>).detail || {};
    if (detail['source_id']) this.activePortWebcam.set(detail);
  };

  readonly fallbackNav: MissionNavigationItem[] = [
    { key: 'cockpit', label: 'Cockpit', glyph: 'ledger', route: '/hypervisor/mission-room/cockpit', api: '/api/v1/mission-room/cockpit', object: 'Workbench', workbench: 'Workbench' },
    { key: 'strategie', label: 'Carte', glyph: 'sliders', route: '/hypervisor/mission-room/strategie', api: '/api/v1/mission-room/map', object: 'Workbench', workbench: 'Workbench' },
    { key: 'securite', label: 'Sécurité', glyph: 'shield', route: '/hypervisor/mission-room/securite', api: '/api/v1/mission-room/cockpit', object: 'Workbench', workbench: 'Workbench' },
    { key: 'reputation', label: 'Reputation', glyph: 'pulse', route: '/hypervisor/mission-room/reputation', api: '/api/v1/mission-room/news', object: 'Run', workbench: 'Run' },
    { key: 'agenda', label: 'Agenda', glyph: 'ledger', route: '/hypervisor/mission-room/agenda', api: '/api/v1/mission-room/timeline', object: 'Workbench', workbench: 'Workbench' },
    { key: 'presse', label: 'Presse', glyph: 'pulse', route: '/hypervisor/mission-room/presse', api: '/api/v1/mission-room/news', object: 'Run', workbench: 'Run' },
    { key: 'decisions', label: 'Arbitrages', glyph: 'check', route: '/hypervisor/mission-room/decisions', api: '/api/v1/mission-room/decisions', object: 'Review Queue', workbench: 'Review Queue' },
  ];

  readonly currentView = computed<MissionView>(() => {
    const view = this.routeView();
    return this.validViews.has(view) ? view : 'cockpit';
  });

  readonly missionExtension = computed(() => missionRoomExtensionState(this.workspace.current()));
  readonly octocityProfile = computed(() =>
    this.missionExtension().profile === OCTOCITY_MISSION_ROOM_PROFILE,
  );
  readonly adminRoute = computed(() => {
    const slug = this.workspace.currentSlug();
    return slug ? `/workspace/${encodeURIComponent(slug)}` : '/workspace';
  });
  readonly assistantName = computed(() =>
    this.navigation()?.app?.assistant_label
    || this.missionExtension().assistantLabel
    || (this.octocityProfile() ? 'OCTAVE' : 'AYA'),
  );
  readonly assistantProfileKey = computed(() => {
    const defaultProfile = this.workspace.current()?.settings?.['assistant_profile_default'];
    if (typeof defaultProfile === 'string' && defaultProfile.trim()) return defaultProfile;
    const profile = this.navigation()?.app?.profile || this.missionExtension().profile;
    return profile === OCTOCITY_MISSION_ROOM_PROFILE ? 'octave_executive' : 'vigie_executive';
  });
  readonly missionBrand = computed<MissionBrand>(() => {
    const navBrand = this.navigation()?.app?.brand;
    if (navBrand && Object.keys(navBrand).length) return navBrand;
    const settingsBrand = this.workspace.current()?.settings?.['workspace_app_brand'];
    if (settingsBrand && typeof settingsBrand === 'object') return settingsBrand as MissionBrand;
    if (this.octocityProfile()) {
      return {
        label: 'Octocity Mission Room',
        lines: ['AGENTIUM', 'MISSION ROOM'],
        emblem: '/assets/brand/agentium-mark.svg',
        style: 'agentium',
      };
    }
    return {};
  });
  readonly missionBrandLabel = computed(() => this.missionBrand().label || this.navigation()?.app?.label || 'SENTINEL-CI');
  readonly missionBrandLines = computed(() => {
    const lines = this.missionBrand().lines;
    if (Array.isArray(lines) && lines.length) return lines;
    return this.missionBrandStyle() === 'agentium' ? ['AGENTIUM', 'MISSION ROOM'] : ['REPUBLIQUE DE', "COTE D'IVOIRE"];
  });
  readonly missionBrandEmblem = computed(() => this.missionBrand().emblem || '/assets/brand/sentinel-ci-emblem.png?v=20260518-1');
  readonly missionBrandStyle = computed(() => this.missionBrand().style || 'sentinel');
  readonly missionTimezoneLabel = computed(() => {
    const calendar = this.workspace.current()?.settings?.['calendar'];
    const timezone = calendar && typeof calendar === 'object' ? String((calendar as Record<string, unknown>)['timezone'] || '') : '';
    if (timezone === 'UTC' || this.octocityProfile()) return 'UTC';
    return 'Abidjan UTC+0';
  });
  readonly securityCollectionLabel = computed(() =>
    this.missionBrandStyle() === 'agentium' ? 'Collection octocity-security-briefs' : 'Collection sentinel-ci-security-briefs',
  );
  readonly securityCollectionDescription = computed(() =>
    this.missionBrandStyle() === 'agentium'
      ? `Briefs posture Northern Belt, syntheses conseil et dossiers rumeur utilises par ${this.assistantName()} S3.`
      : `Briefs posture Sahel, synthèses Conseil Défense et dossiers rumeur utilisés par ${this.assistantName()} S3.`,
  );
  readonly highlightTarget = computed(() => this.highlightQuery());
  readonly mapViewMode = computed<'territory' | 'live'>(() => {
    const mode = (this.modeQuery() || 'territory').toLowerCase();
    return mode === 'live' || mode === 'maritime' ? 'live' : 'territory';
  });
  readonly pressHighlightId = computed(() => {
    if (this.morningHighlightDismissed()) return null;
    return this.pressPreview()[0]?.id || 'attention-inter-budget';
  });
  readonly railAlertBadges = computed<Partial<Record<MissionView, number>>>(() => ({
    presse: this.pressPreview().length || this.kpiNumber('press_alerts') || 0,
    decisions: this.arbitrationCards().length || this.decisionQueue().length || 0,
    securite: this.securityPosture() ? 1 : 0,
    reputation: this.reputationDrillItems().length || 0,
  }));
  readonly currentAbidjanDateLabel = computed(() => this.capitalizeDateLabel(this.abidjanFullDateFormatter.format(this.abidjanNow())));
  readonly currentAbidjanShortDateLabel = computed(() => this.abidjanShortDateFormatter.format(this.abidjanNow()).replace(/\.$/, ''));
  readonly currentAbidjanSessionLabel = computed(() => {
    const hour = Number(this.abidjanHourFormatter.format(this.abidjanNow()));
    const part = hour < 12 ? 'matin' : hour < 18 ? 'apres-midi' : 'soir';
    return `${this.currentAbidjanDateLabel()} · ${part}`;
  });
  readonly reputationTrendStartLabel = computed(() => this.formatRelativeAbidjanDate(-6));
  readonly ayaRailState = computed<'listening' | 'ready'>(() => (this.cockpit()?.briefing_status || '').toLowerCase().includes('ecoute') ? 'listening' : 'ready');
  readonly ayaRailStateLabel = computed(() => {
    const status = (this.cockpit()?.briefing_status || '').toLowerCase();
    if (status.includes('ecoute')) return 'A l ecoute';
    if (status.includes('pret')) return 'Briefing pret';
    return this.cockpit()?.briefing_status || 'Briefing pret';
  });

  readonly sources = computed(() => {
    const rows = [
      ...(this.cockpit()?.sources || []),
      ...(this.briefing()?.sources || []),
      ...(this.projects()?.sources || []),
      ...(this.missionMap()?.sources || []),
      ...(this.monitor()?.sources || []),
      ...(this.news()?.sources || []),
      ...(this.timeline()?.sources || []),
      ...(this.decisions()?.sources || []),
      ...(this.library()?.sources || []),
      ...(this.search()?.sources || []),
    ];
    return new Map(rows.map((source) => [source.id, source]));
  });

  private readonly validViews = new Set<MissionView>([
    'cockpit',
    'monitor',
    'briefing',
    'agenda',
    'presse',
    'decisions',
    'strategie',
    'recherche',
    'reputation',
    'securite',
  ]);

  readonly securiteTab = signal<'vue' | 'documents'>('vue');

  constructor() {
    this.unregisterWorkspaceReset = this.workspace.registerContextReset(() => {
      this.resetWorkspaceActionContinuations();
    });
    effect(() => {
      const view = this.routeView();
      if (view === 'briefing') {
        void this.router.navigate(['/hypervisor/mission-room/decisions'], {
          queryParams: { focus: 'brief', highlight: this.highlightQuery() || 'package-zone-nord' },
          replaceUrl: true,
        });
        return;
      }
      if (view === 'monitor') {
        void this.router.navigate(['/hypervisor/mission-room/strategie'], {
          queryParams: { mode: 'live', zone: this.zoneQuery() || undefined, highlight: this.highlightQuery() || undefined },
          replaceUrl: true,
        });
        return;
      }
      // 'reputation' used to be redirected to the cockpit, which broke the
      // S3.5 `aya.show_reputation_drill` action (the reputation view template
      // was already defined but unrouted). It is now a first-class view that
      // renders the 2 positifs / 1 critique drill panel directly.
      if (['pilotage', 'projets', 'messages', 'bibliotheque', 'veille', 'assistant'].includes(view)) {
        void this.router.navigate(['/hypervisor/mission-room/cockpit'], { replaceUrl: true });
      }
    });
  }

  ngOnInit(): void {
    window.addEventListener('agentium:calendar-updated', this.calendarUpdateListener);
    window.addEventListener('agentium:action-plan-updated', this.workspaceActionUpdateListener);
    window.addEventListener('agentium:visual-intelligence-updated', this.workspaceActionUpdateListener);
    window.addEventListener('agentium:map-command', this.mapCommandListener);
    window.addEventListener('agentium:assistant-navigate', this.assistantNavigateListener);
    window.addEventListener('agentium:assistant-propose', this.assistantProposeListener);
    window.addEventListener('agentium:assistant-show-webcam', this.assistantShowWebcamListener);
    this.focusQuerySub = this.route.queryParamMap.subscribe((params) => {
      this.applyS3QueryState(params);
    });
    this.loadAll();
    this.subscribeMaritimeTracking();
    this.abidjanClockTimer = setInterval(() => this.abidjanNow.set(new Date()), 30_000);
    setTimeout(() => this.scrollToHighlight(), 120);
    this.applyMapQueryState();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.unregisterWorkspaceReset();
    this.unregisterWorkspaceReset = () => undefined;
    this.resetWorkspaceActionContinuations();
    window.removeEventListener('agentium:calendar-updated', this.calendarUpdateListener);
    window.removeEventListener('agentium:action-plan-updated', this.workspaceActionUpdateListener);
    window.removeEventListener('agentium:visual-intelligence-updated', this.workspaceActionUpdateListener);
    window.removeEventListener('agentium:map-command', this.mapCommandListener);
    window.removeEventListener('agentium:assistant-navigate', this.assistantNavigateListener);
    window.removeEventListener('agentium:assistant-propose', this.assistantProposeListener);
    window.removeEventListener('agentium:assistant-show-webcam', this.assistantShowWebcamListener);
    this.focusQuerySub?.unsubscribe();
    this.focusQuerySub = null;
    if (this.s3FocusTimer) clearTimeout(this.s3FocusTimer);
    this.s3FocusTimer = null;
    this.maritimeVesselsSub?.unsubscribe();
    this.maritimeVesselsSub = null;
    if (this.abidjanClockTimer) {
      clearInterval(this.abidjanClockTimer);
      this.abidjanClockTimer = null;
    }
    this.visualObjectUrls.forEach((url) => URL.revokeObjectURL(url));
    this.visualObjectUrls.length = 0;
  }

  private applyS3QueryState(params: { get(name: string): string | null }): void {
    const focus = params.get('focus');
    const panel = params.get('panel');
    const drill = params.get('drill');
    const docId = params.get('doc');
    const rumorStep = params.get('rumor_step');
    const reputationItem = params.get('reputation_item');

    if (docId) {
      this.securiteTab.set('documents');
      this.selectedSecurityDocId.set(docId);
      this.scrollToElementId('security-doc-workbench', 'start');
    }
    if (panel === 'rumor' || rumorStep) {
      this.securiteTab.set('vue');
      const stepNumber = Number(rumorStep || 5);
      this.selectedRumorStep.set(Number.isFinite(stepNumber) ? stepNumber : 5);
      this.scrollToElementId('s3-rumor-trace', 'start');
    }
    if (drill === 'reputation') {
      this.selectedReputationItemId.set(reputationItem || this.defaultReputationItemId());
      this.scrollToElementId('reputation-drill', 'center');
    } else if (reputationItem) {
      this.selectedReputationItemId.set(reputationItem);
      this.scrollToElementId('reputation-drill', 'center');
    }
    this.armS3Focus(focus || panel || drill);
  }

  private armS3Focus(rawFocus: string | null): void {
    const normalized = (rawFocus || '').toLowerCase().replace(/[\s-]+/g, '_');
    const securityPosture =
      normalized === 'security'
      || normalized === 'security_posture'
      || normalized === 'posture_securitaire'
      || normalized === 'posture_sécuritaire'
      || normalized === 's3_1'
      || (normalized.includes('security') && normalized.includes('posture'));
    if (!securityPosture) return;
    if (this.s3FocusTimer) clearTimeout(this.s3FocusTimer);
    this.s3FocusTarget.set(null);
    setTimeout(() => {
      this.s3FocusTarget.set('security_posture');
      const target = document.getElementById('s3-security-posture');
      if (target) {
        const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
      }
    }, 0);
    this.s3FocusTimer = setTimeout(() => {
      this.s3FocusTarget.set(null);
      this.s3FocusTimer = null;
    }, 2200);
  }

  private scrollToElementId(id: string, block: ScrollLogicalPosition = 'center'): void {
    setTimeout(() => {
      const target = document.getElementById(id);
      if (!target) return;
      const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block });
    }, 80);
  }

  private subscribeMaritimeTracking(): void {
    if (this.maritimeVesselsSub) return;
    this.maritimeVesselsSub = this.maritimeTracking.getSnapshot().subscribe({
      next: (snapshot) => {
        const vessels = (snapshot.vessels || []).filter(
          (vessel) => Number.isFinite(Number(vessel?.lat)) && Number.isFinite(Number(vessel?.lon)),
        );
        this.strategicVessels.set(vessels);
      },
      error: () => this.strategicVessels.set([]),
    });
  }

  private loadAll(
    showSpinner = true,
    continuation?: WorkspaceContinuationContext,
  ): void {
    // Even initial/page-level loads need a pinned scope. Action-triggered
    // callers already provide one; ordinary refreshes capture it here so a
    // late Mission Room payload from A cannot be rendered or shadow-reported
    // after A -> B.
    const activeContinuation = continuation ?? this.captureWorkspaceContinuation();
    if (!this.workspaceContinuationContextIsCurrent(activeContinuation)) return;
    if (showSpinner) this.loading.set(true);
    const workspaceOptions = this.workspaceApiOptions(activeContinuation);
    const request = forkJoin({
      navigation: this.api.get<MissionNavigation>('/mission-room/navigation', undefined, workspaceOptions),
      cockpit: this.api.get<MissionCockpit>('/mission-room/cockpit', undefined, workspaceOptions),
    }).subscribe({
      next: ({ navigation, cockpit }) => {
        if (!this.workspaceContinuationContextIsCurrent(activeContinuation)) return;
        this.navigation.set(navigation);
        // The backend response remains byte-for-byte authoritative for the
        // rendered rail. Shadow observation happens only after the current
        // payload is installed and cannot replace or mutate it.
        try {
          this.workspaceExperienceShadow.observeMissionNavigation(
            navigation,
            activeContinuation.scope,
          );
        } catch {
          // Shadow instrumentation must never interrupt installation of the
          // authoritative cockpit payload or the remaining legacy loads.
        }
        this.cockpit.set(cockpit);
        this.ensureS3Defaults();
        this.loading.set(false);
        this.loadMissionRoomDetails(activeContinuation);
      },
      error: () => {
        if (this.workspaceContinuationContextIsCurrent(activeContinuation)) {
          this.loading.set(false);
        }
      },
    });
    this.trackWorkspaceActionRequest(request, activeContinuation);
  }

  private ensureS3Defaults(): void {
    if (!this.selectedSecurityDocId()) {
      const firstDoc = this.securityDocuments()[0];
      if (firstDoc) this.selectedSecurityDocId.set(firstDoc.id);
    }
    if (!this.selectedReputationItemId()) {
      const defaultItemId = this.defaultReputationItemId();
      if (defaultItemId) this.selectedReputationItemId.set(defaultItemId);
    }
  }

  private loadMissionRoomDetails(continuation?: WorkspaceContinuationContext): void {
    if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
    const workspaceOptions = this.workspaceApiOptions(continuation);
    const request = forkJoin({
      briefing: this.api.get<MissionBriefing>('/mission-room/briefing', undefined, workspaceOptions).pipe(catchError(() => of(null))),
      projects: this.api.get<MissionProjects>('/mission-room/projects', undefined, workspaceOptions).pipe(catchError(() => of(null))),
      missionMap: this.api.get<MissionMap>('/mission-room/map', undefined, workspaceOptions).pipe(catchError(() => of(null))),
      monitor: this.api.get<MissionMonitor>('/mission-room/monitor', undefined, workspaceOptions).pipe(catchError(() => of(null))),
      news: this.api.get<MissionNews>('/mission-room/news', undefined, workspaceOptions).pipe(catchError(() => of(null))),
      timeline: this.api.get<MissionTimeline>('/mission-room/timeline', undefined, workspaceOptions).pipe(catchError(() => of(null))),
      decisions: this.api.get<MissionDecisions>('/mission-room/decisions', undefined, workspaceOptions).pipe(catchError(() => of(null))),
      library: this.api.get<MissionLibrary>('/mission-room/library', undefined, workspaceOptions).pipe(catchError(() => of(null))),
      search: this.api.get<MissionSearch>('/mission-room/search', { q: '' }, workspaceOptions).pipe(catchError(() => of(null))),
    }).subscribe(({ briefing, projects, missionMap, monitor, news, timeline, decisions, library, search }) => {
      if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
      if (briefing) this.briefing.set(briefing);
      if (projects) {
        this.projects.set(projects);
        const current = this.selectedProject();
        const stillVisible = current?.id ? projects.projects.find((item) => item.id === current.id) : null;
        this.selectedProject.set(stillVisible || projects.projects[0] || null);
      }
      if (missionMap) {
        this.missionMap.set(missionMap);
        const current = this.selectedZone();
        const stillVisible = current?.id ? missionMap.zones.find((item) => item.id === current.id) : null;
        this.selectedZone.set(stillVisible || missionMap.zones[0] || null);
        this.applyMapQueryState();
      }
      if (monitor) {
        this.monitor.set(monitor);
        this.hydrateVisualCaptureImages(monitor);
      }
      if (news) this.news.set(news);
      if (timeline) {
        this.timeline.set(timeline);
        const currentAgenda = this.selectedAgendaEvent();
        const agenda = timeline.agenda || [];
        const stillVisible = currentAgenda?.id ? agenda.find((item) => item.id === currentAgenda.id) : null;
        this.selectedAgendaEvent.set(stillVisible || agenda.find((item) => item.status !== 'cancelled') || agenda[0] || null);
      }
      if (decisions) this.decisions.set(decisions);
      if (library) this.library.set(library);
      if (search) this.search.set(search);
    });
    this.trackWorkspaceActionRequest(request, continuation);
    this.loadMeetingDecisionsLog(continuation);
  }

  private loadMeetingDecisionsLog(continuation?: WorkspaceContinuationContext): void {
    if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
    const workspaceSlug = continuation?.scope.workspaceSlug || this.workspace.currentSlug();
    if (!workspaceSlug) {
      this.meetingDecisionsLog.set([]);
      return;
    }
    const request = this.api
      .get<MeetingDecisionsLogResponse>(
        '/meetings/decisions-log',
        { workspace: workspaceSlug },
        this.workspaceApiOptions(continuation),
      )
      .pipe(catchError(() => of<MeetingDecisionsLogResponse | null>(null)))
      .subscribe((payload) => {
        if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
        const items = payload?.decisions || [];
        if (!items.length) {
          this.meetingDecisionsLog.set([]);
          return;
        }
        const entries: MeetingDecisionLogEntry[] = items
          .map((entry) => {
            const decidedAt = entry.decided_at;
            let decidedAtLabel = '';
            if (decidedAt) {
              try {
                decidedAtLabel = new Intl.DateTimeFormat('fr-FR', {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                }).format(new Date(decidedAt));
              } catch {
                decidedAtLabel = decidedAt;
              }
            }
            return {
              id: entry.id || `${entry.calendar_event_id || entry.event_id || 'meeting'}-${entry.agenda_item_ref || entry.title || 'item'}`,
              title: entry.agenda_item_title || entry.title || entry.agenda_item_ref || 'Point d ordre du jour',
              chosen_option: entry.chosen_option || '—',
              rationale: entry.rationale,
              decided_at: decidedAt,
              decided_at_label: decidedAtLabel,
              event_id: entry.calendar_event_id || entry.event_id,
              event_title: entry.event_title,
            };
          })
          .slice(0, 12);
        this.meetingDecisionsLog.set(entries);
      });
    this.trackWorkspaceActionRequest(request, continuation);
  }

  kpi(key: string): number | string {
    return this.cockpit()?.kpis?.[key] ?? '-';
  }

  kpiNumber(key: string): number {
    const value = this.kpi(key);
    return typeof value === 'number' ? value : Number(value) || 0;
  }

  reputationValue(): string {
    const reputation = this.cockpit()?.reputation;
    if (!reputation) return '';
    return `${reputation.score}% +${reputation.delta}pts`;
  }

  reputationDrillItems(): NonNullable<MissionCockpit['reputation']['items']> {
    return this.cockpit()?.reputation?.items || [];
  }

  selectedSecurityDoc(): NonNullable<MissionCockpit['security_documents']>[number] | null {
    const docs = this.securityDocuments();
    if (!docs.length) return null;
    const selectedId = this.selectedSecurityDocId();
    return docs.find((doc) => doc.id === selectedId) || docs[0] || null;
  }

  selectSecurityDoc(doc: NonNullable<MissionCockpit['security_documents']>[number]): void {
    this.selectedSecurityDocId.set(doc.id);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { doc: doc.id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  securityDocUsage(doc: NonNullable<MissionCockpit['security_documents']>[number]): string {
    const key = `${doc.id} ${doc.title} ${doc.kind}`.toLowerCase();
    if (this.missionBrandStyle() === 'agentium') {
      if (key.includes('conseil')) return 'Support de préparation coordination avant la revue Northern Belt de 15h.';
      if (key.includes('rumeur')) return 'Source de vérité S3.3 : chaîne OSINT, démenti Garde Civique et mise au point territoriale.';
      if (key.includes('ads') || key.includes('troupes')) return 'Contexte S3.4 : traces ADS-B advisory et théâtre Northern Belt.';
      if (key.includes('posture') || key.includes('sahel')) return 'Alimente S3.1 : posture dual-axis et conseil de coordination 15h.';
    } else {
      if (key.includes('conseil')) return 'Support de préparation cabinet avant la revue Sahel de 15h.';
      if (key.includes('rumeur')) return 'Source de vérité S3.3 : chaîne OSINT, démenti FANCI et mise au point Préfecture.';
      if (key.includes('ads') || key.includes('troupes')) return 'Contexte S3.4 : traces ADS-B advisory et théâtre Sahel.';
      if (key.includes('posture') || key.includes('sahel')) return 'Alimente S3.1 : posture dual-axis et Conseil Défense 15h.';
    }
    return `Document indexé pour les réponses ${this.assistantName()} S3.`;
  }

  securityDocActionLabel(doc: NonNullable<MissionCockpit['security_documents']>[number]): string {
    const key = `${doc.id} ${doc.title} ${doc.kind}`.toLowerCase();
    if (key.includes('conseil')) return 'Voir Conseil 15h';
    if (key.includes('rumeur')) return 'Ouvrir timeline rumeur';
    if (key.includes('ads') || key.includes('troupes')) return 'Ouvrir Security Monitor';
    if (key.includes('posture') || key.includes('sahel')) return `Demander la posture à ${this.assistantName()}`;
    return `Ouvrir avec ${this.assistantName()}`;
  }

  securityDocSourceLabels(doc: NonNullable<MissionCockpit['security_documents']>[number]): string[] {
    return (doc.sources || []).map((source) => this.sourceLabel(source));
  }

  securityDocExcerpt(doc: NonNullable<MissionCockpit['security_documents']>[number]): string {
    const sourceLabel = this.securityDocSourceLabels(doc)[0];
    if (!sourceLabel) return 'Source indexée · extrait non disponible.';
    return `${doc.summary} Source principale : ${sourceLabel}.`;
  }

  runSecurityDocAction(doc: NonNullable<MissionCockpit['security_documents']>[number]): void {
    const key = `${doc.id} ${doc.title} ${doc.kind}`.toLowerCase();
    if (key.includes('conseil')) {
      this.securiteTab.set('vue');
      this.armS3Focus('security_posture');
      this.scrollToElementId('s3-security-posture', 'center');
      return;
    }
    if (key.includes('rumeur')) {
      this.securiteTab.set('vue');
      this.selectedRumorStep.set(5);
      this.scrollToElementId('s3-rumor-trace', 'start');
      return;
    }
    if (key.includes('ads') || key.includes('troupes')) {
      this.openSecurityMonitor();
      return;
    }
    if (key.includes('posture') || key.includes('sahel')) {
      this.openAssistant('AYA, montre-moi la posture sécuritaire du jour.');
      return;
    }
    this.openAssistant(`AYA, résume le document sécurité ${doc.title}.`);
  }

  defaultReputationItemId(): string | null {
    const items = this.reputationDrillItems();
    return items.find((item) => item.kind === 'critique' || item.tone === 'negative')?.id || items[0]?.id || null;
  }

  selectedReputationItem(): NonNullable<MissionCockpit['reputation']['items']>[number] | null {
    const items = this.reputationDrillItems();
    if (!items.length) return null;
    const selectedId = this.selectedReputationItemId() || this.defaultReputationItemId();
    return items.find((item) => item.id === selectedId) || items[0] || null;
  }

  selectReputationItem(item: NonNullable<MissionCockpit['reputation']['items']>[number]): void {
    this.selectedReputationItemId.set(item.id);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { drill: 'reputation', reputation_item: item.id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  reputationItemRiskLabel(item: NonNullable<MissionCockpit['reputation']['items']>[number]): string {
    if (item.kind === 'critique' || item.tone === 'negative') return 'Risque : cadrage budget défense avant Conseil 15h.';
    if (/nawa|liora/i.test(item.title)) {
      return this.missionBrandStyle() === 'agentium'
        ? 'Opportunité : valoriser la réponse territoriale et bio-composites.'
        : 'Opportunité : valoriser la réponse territoriale et cacao.';
    }
    return 'Opportunité : consolider la lecture Nord auprès des partenaires.';
  }

  reputationResponseLabel(item: NonNullable<MissionCockpit['reputation']['items']>[number]): string {
    if (item.kind === 'critique' || item.tone === 'negative') return 'Réponse recommandée : encart sobre, chiffres prudents, validation cabinet.';
    return 'Réponse recommandée : reprendre le signal positif sans triomphalisme.';
  }

  reputationNarrativeBalanceLabel(): string {
    const positive = this.reputationDrillItems().filter((item) => item.kind !== 'critique' && item.tone !== 'negative').length;
    const critical = this.reputationDrillItems().filter((item) => item.kind === 'critique' || item.tone === 'negative').length;
    return `${positive} signaux positifs compensent ${critical} critique · budget défense relié au Conseil 15h.`;
  }

  runReputationCouncilAction(): void {
    this.openAssistant('AYA, prépare un encart Conseil 15h sur la réputation et le budget défense.');
  }

  reputationArticleActionLabel(item: NonNullable<MissionCockpit['reputation']['items']>[number]): string {
    if (item.kind === 'critique' || item.tone === 'negative') return "Ouvrir l'article interne";
    return 'Ouvrir la note presse';
  }

  reputationExternalUrl(item: NonNullable<MissionCockpit['reputation']['items']>[number]): string | null {
    const url = item.url || '';
    if (!url || /\/example\//i.test(url) || /example\./i.test(url)) return null;
    return url;
  }

  openReputationArticle(item: NonNullable<MissionCockpit['reputation']['items']>[number]): void {
    const article = this.reputationArticleFor(item);
    this.openPressArticle(article);
  }

  private reputationArticleFor(item: NonNullable<MissionCockpit['reputation']['items']>[number]): NewsSignal {
    const linkedAttentionId = item.linked_attention_id || '';
    const sourceId = item.source_id || '';
    const match = this.allNewsSignals().find((signal) =>
      signal.id === linkedAttentionId
      || signal.id === sourceId
      || signal.article_id === linkedAttentionId
      || signal.sources?.includes(sourceId)
      || signal.sources?.includes(linkedAttentionId),
    );
    if (match) return match;
    const negative = item.kind === 'critique' || item.tone === 'negative';
    return {
      id: linkedAttentionId || item.id,
      article_id: linkedAttentionId || item.id,
      title: item.title,
      risk_level: negative ? 'high' : 'medium',
      sentiment: item.sentiment || (negative ? 'negative' : 'positive'),
      summary: item.summary || 'Source presse indexée pour le drill réputation S3.',
      source: item.source_label || sourceId || 'Source presse',
      source_name: item.source_label || sourceId || 'Source presse',
      source_category: 'presse',
      sources: [sourceId || linkedAttentionId || item.id].filter(Boolean),
      tags: ['reputation', 'sentinel-ci', negative ? 'critique' : 'positif'],
      briefing_value: this.reputationResponseLabel(item),
      why_it_matters: this.reputationItemRiskLabel(item),
      recommended_action: negative
        ? 'Préparer une réponse cabinet sobre avant le Conseil 15h.'
        : 'Capitaliser sans surjouer : signal positif utile pour l’encart Conseil 15h.',
      url: this.reputationExternalUrl(item),
    };
  }

  newsAlerts(): NewsSignal[] {
    const payload = this.news();
    return payload?.executive_alerts?.length ? payload.executive_alerts : payload?.signals || [];
  }

  allNewsSignals(): NewsSignal[] {
    const payload = this.news();
    const primary = payload?.all_signals?.length
      ? payload.all_signals
      : payload?.executive_alerts?.length
        ? payload.executive_alerts
        : payload?.signals || [];
    const sectionSignals = (payload?.geo_sections || []).flatMap((section) => section.signals || []);
    const merged = new Map<string, NewsSignal>();
    for (const signal of [...primary, ...sectionSignals]) {
      if (signal?.id) merged.set(signal.id, signal);
    }
    return [...merged.values()];
  }

  briefPriorityItems(): string[] {
    return (this.news()?.briefing_note?.bullets || []).slice(0, 3);
  }

  heroNewsAlerts(): NewsSignal[] {
    return this.regionArticles().slice(0, 1);
  }

  regionArticleCount(): number {
    return this.regionArticles().length;
  }

  displayedPressArticles(): NewsSignal[] {
    const articles = this.regionArticles();
    if (!this.pressArticleListRiskSort()) return articles;
    return [...articles].sort(
      (left, right) => this.pressRiskRank(right.risk_level) - this.pressRiskRank(left.risk_level),
    );
  }

  pressKpiLabel(): string {
    const health = this.news()?.source_health;
    const analyzed = health?.analyzed || this.kpiNumber('analyzed_articles') || this.allNewsSignals().length;
    const highRisk = health?.high_risk
      || this.allNewsSignals().filter((signal) => this.pressRiskRank(signal.risk_level) >= 3).length;
    if (this.missionBrandStyle() === 'agentium') {
      return `${analyzed} articles analyzed · ${highRisk} high-risk signals`;
    }
    return `${analyzed} articles analyses · ${highRisk} signaux haut risque`;
  }

  selectedPressArticleDetail(): PressArticleDetail | null {
    const article = this.selectedPressArticle();
    if (!article) return null;
    return {
      id: article.id,
      title: article.title,
      summary: article.summary,
      briefing_value: article.briefing_value,
      impact_ci: article.impact_ci,
      why_it_matters: article.why_it_matters,
      source: article.source,
      source_name: article.source_name,
      risk_level: article.risk_level,
      url: article.url,
      tags: article.tags,
      published_at: article.published_at,
      entities: article.entities,
      viewpoint: article.viewpoint,
      zone: article.zone,
      sentiment: article.sentiment,
      confidence: article.confidence,
      source_count: article.source_count,
      velocity: article.velocity,
    };
  }

  pressConfigRoute(): string | null {
    const route = this.systemRouteFor('veille');
    return route ? `${route}?facet=intelligence&panel=config` : null;
  }

  openPressArticle(article: NewsSignal): void {
    this.selectedPressArticle.set(article);
  }

  closePressArticle(): void {
    this.selectedPressArticle.set(null);
  }

  togglePressArticleList(): void {
    this.pressArticleListOpen.update((open) => !open);
    if (!this.pressArticleListOpen()) {
      this.pressArticleListRiskSort.set(false);
    }
  }

  openPressArticleList(options?: { sortByRisk?: boolean }): void {
    this.pressArticleListRiskSort.set(!!options?.sortByRisk);
    this.pressArticleListOpen.set(true);
    this.closePressArticle();
  }

  openBriefBullet(bullet: string): void {
    const match = this.matchBriefBulletArticle(bullet);
    if (match) {
      this.openPressArticle(match);
      return;
    }
    this.openPressArticleList({ sortByRisk: true });
  }

  matchBriefBulletArticle(bullet: string): NewsSignal | null {
    const normalizedBullet = bullet.toLowerCase();
    const articles = this.allNewsSignals();
    let best: NewsSignal | null = null;
    let bestScore = 0;
    for (const article of articles) {
      const titleWords = article.title.toLowerCase().split(/\s+/).filter((word) => word.length > 4);
      const score = titleWords.filter((word) => normalizedBullet.includes(word)).length;
      if (score > bestScore) {
        bestScore = score;
        best = article;
      }
    }
    if (best && bestScore >= 2) return best;
    return articles.find((article) => this.pressRiskRank(article.risk_level) >= 3) || articles[0] || null;
  }

  private pressRiskRank(level?: string): number {
    const normalized = (level || '').toLowerCase();
    if (normalized === 'critical' || normalized === 'high') return 3;
    if (normalized === 'medium' || normalized === 'elevated' || normalized === 'watch') return 2;
    return 1;
  }

  maritimeIntelligence(): MaritimeIntelligence | null {
    return this.news()?.maritime_intelligence || this.monitor()?.maritime || null;
  }

  openMaritimeMonitor(): void {
    const agentium = this.missionBrandStyle() === 'agentium';
    const evidence = this.maritimeIntelligence()?.active_evidence;
    this.mapCommandState.set(evidence?.['map_focus'] || {
      active_layers: ['territorial-risk', 'open-intelligence', 'visual-streams', 'maritime-traffic'],
      camera: { longitude: -4.0083, latitude: 5.2512, zoom: 9.15, duration_ms: 220 },
      focus_marker: {
        longitude: -4.0083,
        latitude: 5.2512,
        label: agentium ? 'Port Meridian · maritime' : "Port d'Abidjan · maritime",
        zone_id: 'zone-sud',
        tone: 'maritime',
      },
    });
    void this.router.navigate(['/hypervisor/mission-room/strategie'], { queryParams: { mode: 'live' } });
  }

  newsGeoTabs(): { key: 'ci' | 'cedeao' | 'africa' | 'world'; label: string; count: number }[] {
    const sections = this.news()?.geo_sections || [];
    const labels: Record<string, string> = this.missionBrandStyle() === 'agentium'
      ? { ci: 'France operations', cedeao: 'European coordination', africa: 'Strategic context', world: 'International' }
      : { ci: "Cote d'Ivoire", cedeao: 'CEDEAO', africa: 'Afrique', world: 'International' };
    return (['ci', 'cedeao', 'africa', 'world'] as const).map((key) => ({
      key,
      label: sections.find((section) => section.key === key)?.label || labels[key],
      count: sections.find((section) => section.key === key)?.count
        ?? this.newsAlerts().filter((signal) => this.newsGeoTier(signal) === key).length,
    }));
  }

  newsEyebrowLabel(): string {
    return this.missionBrandStyle() === 'agentium' ? 'Open intelligence' : 'Alerte presse';
  }

  missionRoomRoleLabel(): string {
    return this.missionBrandStyle() === 'agentium'
      ? 'Mission Room · Coordination Director'
      : 'Mission Room · Vice Premier Ministre';
  }

  missionRoomGreetingFallback(): string {
    return this.missionBrandStyle() === 'agentium'
      ? 'Good morning, Coordination Director.'
      : 'Bonjour, Monsieur le Vice Premier Ministre.';
  }

  missionRoomHeroTitle(): string {
    if (this.missionBrandStyle() === 'agentium') {
      return 'Good morning, Coordination Director.';
    }
    return this.cockpit()?.title || this.missionRoomGreetingFallback();
  }

  missionRoomDateLabel(): string {
    if (this.missionBrandStyle() === 'agentium') {
      return 'Wednesday, July 1, 2026';
    }
    return this.cockpit()?.date_label || this.currentAbidjanDateLabel();
  }

  missionRoomVisionLabel(): string {
    return this.missionBrandStyle() === 'agentium'
      ? 'Consolidated executive view'
      : 'Vision executive consolidee';
  }

  strategicMapEyebrowLabel(): string {
    return this.missionBrandStyle() === 'agentium' ? 'Strategic map' : 'Carte strategique';
  }

  strategicMapQuestion(): string {
    if (this.missionBrandStyle() === 'agentium') {
      return 'Which real-world signals require a governed decision this month?';
    }
    return this.missionMap()?.question || '';
  }

  talkingPointsEyebrowLabel(): string {
    return this.missionBrandStyle() === 'agentium' ? 'Executive language' : 'Elements de langage';
  }

  recommendedPositionLabel(): string {
    return this.missionBrandStyle() === 'agentium' ? 'Recommended position' : 'Position recommandee';
  }

  pressArticleListToggleLabel(): string {
    if (this.missionBrandStyle() === 'agentium') {
      return this.pressArticleListOpen()
        ? 'Back to synthesis'
        : `View all signals (${this.regionArticleCount()})`;
    }
    return this.pressArticleListOpen()
      ? 'Revenir a la synthese'
      : `Voir tous les articles (${this.regionArticleCount()})`;
  }

  setNewsGeoTier(key: 'ci' | 'cedeao' | 'africa' | 'world'): void {
    this.activeNewsGeoTier.set(key);
    this.pressArticleListOpen.set(false);
    this.pressArticleListRiskSort.set(false);
    this.closePressArticle();
  }

  regionArticles(): NewsSignal[] {
    const tier = this.activeNewsGeoTier();
    const direct = this.allNewsSignals().filter((signal) => this.newsGeoTier(signal) === tier);
    const section = (this.news()?.geo_sections || []).find((item) => item.key === tier);
    const sectionSignals = section?.signals || [];
    const merged = new Map<string, NewsSignal>();
    for (const signal of [...direct, ...sectionSignals]) {
      if (signal?.id) merged.set(signal.id, signal);
    }
    return [...merged.values()].slice(0, 30);
  }

  filteredNewsAlerts(): NewsSignal[] {
    return this.regionArticles().slice(0, 4);
  }

  newsGeoTier(signal: NewsSignal): 'ci' | 'cedeao' | 'africa' | 'world' {
    const raw = (signal.geo_tier || signal.geography_tier || 'world').toLowerCase();
    return raw === 'ci' || raw === 'cedeao' || raw === 'africa' || raw === 'world' ? raw : 'world';
  }

  newsBadges(signal: NewsSignal): string[] {
    const badges = signal.badges?.length ? signal.badges : [
      signal.source_count && signal.source_count > 1 ? 'multi-source' : 'source unique',
      signal.velocity ? `vitesse ${signal.velocity}` : 'veille',
    ];
    return badges.slice(0, 4);
  }

  decisionSentence60(): NonNullable<MissionCockpit['decision_sentence']> {
    return this.cockpit()?.decision_sentence || {
      label: 'Sentence du jour',
      text: 'Monsieur le Vice Premier Ministre, votre priorité absolue ce matin est la Zone Nord. Tout le reste peut attendre.',
      deadline: 'avant Conseil 15h00',
      generated_by: this.assistantName(),
    };
  }

  vpStatusBar(): NonNullable<MissionCockpit['vp_status_bar']> {
    const direct = this.cockpit()?.vp_status_bar;
    const items = direct?.length
      ? direct
      : [
      { key: 'tension-nord', label: 'Zone Nord', value: 'Tendue', detail: 'projet public bloque · cargo affecte', tone: 'critical', drill_down: { view: 'strategie', zone: 'zone-nord', layers: 'threat,press,maritime-traffic', anchor: 'projet-napie' } },
      { key: 'posture', label: 'Posture nationale', value: this.postureLabel(this.cockpit()?.strategic_posture), detail: 'consolidation sources', tone: this.cockpit()?.strategic_posture?.label || 'monitoring' },
      { key: 'decisions', label: 'Decisions', value: '3', detail: 'avant 15h00', tone: 'elevated' },
      { key: 'press', label: 'Presse', value: String(this.kpiNumber('press_alerts') || 16), detail: 'alertes qualifiees', tone: 'critical' },
      { key: 'agenda', label: 'Agenda', value: this.kpi('next_meeting_in') === '-' ? '1h46' : String(this.kpi('next_meeting_in')), detail: 'prochaine sequence', tone: 'stable' },
      { key: 'flux', label: 'Flux', value: String(this.kpiNumber('analyzed_articles') || 80), detail: 'articles analyses', tone: 'monitoring' },
    ];
    return items.slice(0, 3);
  }

  securityPosture(): Record<string, any> | null {
    return this.cockpit()?.security_posture || null;
  }

  socialSnapshot(): Record<string, any> | null {
    return this.cockpit()?.social_snapshot || null;
  }

  rumorFrontierTrace(): Record<string, any> | null {
    return this.cockpit()?.rumor_frontier_trace || null;
  }

  troopsSahel(): Record<string, any> | null {
    return this.cockpit()?.troops_sahel || null;
  }

  securityDocuments(): NonNullable<MissionCockpit['security_documents']> {
    return this.cockpit()?.security_documents || [];
  }

  securityCouncilLabel(): string {
    const council = (this.securityPosture()?.['next_council'] || {}) as Record<string, unknown>;
    const label = String(council['label'] || 'Conseil Défense restreint');
    const time = String(council['time'] || '15:00');
    return `${label} · ${time}`;
  }

  directiveOfDay(): NonNullable<MissionCockpit['directive_of_day']> {
    const direct = this.cockpit()?.directive_of_day;
    if (direct?.text) {
      return {
        ...direct,
        text: direct.text || 'Tension Zone Nord requiert votre attention prioritaire.',
      };
    }
    const sentence = this.decisionSentence60();
    return {
      ...sentence,
      text: sentence.text || 'Tension Zone Nord requiert votre attention prioritaire.',
      window: sentence.deadline || 'avant Conseil 15h00',
      primary_cta: 'Ouvrir le dossier Zone Nord',
      voice_cta: `Ecouter le briefing ${this.assistantName()}`,
    };
  }

  ayaRecommendation(): NonNullable<MissionCockpit['aya_recommendation']> {
    return this.cockpit()?.aya_recommendation || {
      assistant: this.assistantName(),
      voice_first: true,
      prompt: `${this.assistantName()}, quelle est la situation au nord en ce moment ?`,
      answer: 'Zone Nord sous attention prioritaire. Deux options sont preparees : coordination locale ou arbitrage cabinet avant 15h00.',
      target_latency_s: 6,
      cta_primary: `Ecouter le briefing ${this.assistantName()}`,
      cta_secondary: `Parler a ${this.assistantName()}`,
    };
  }

  scenarioModes(): NonNullable<MissionCockpit['scenario_modes']> {
    const direct = this.cockpit()?.scenario_modes;
    if (direct?.length) return direct;
    const postureModes = this.cockpit()?.decision_posture?.modes;
    if (postureModes?.length) return postureModes;
    return [
      { key: 'explorer', label: 'Explorer', goal: 'Voir posture, couches, zones et sources fraiches.' },
      { key: 'comprendre', label: 'Comprendre', goal: 'Relier sources, rumeurs, projets, agenda et carte.' },
      { key: 'decider', label: 'Decider', goal: "Comparer options, impact, confiance et preparer l'action." },
    ];
  }

  sourceFreshnessItems(): NonNullable<NonNullable<MissionCockpit['source_freshness']>['items']> {
    const items = this.cockpit()?.source_freshness?.items;
    if (items?.length) return items;
    const layers = this.cockpit()?.monitoring_layers || [];
    if (layers.length) {
      return layers.slice(0, 4).map((layer) => ({
        key: layer.key || layer.name || layer.label || 'source',
        label: layer.label || layer.name || 'Source',
        state: layer.visible === false ? 'masque' : 'visible',
        freshness: layer.freshness || 'a jour',
        count: layer.count || 0,
        confidence: layer.confidence || 50,
      }));
    }
    return [
      { key: 'open-intelligence', label: 'Presse / rumeurs', state: 'qualified', freshness: 'veille qualifiee', count: this.kpiNumber('analyzed_articles') || 80, confidence: 72 },
      { key: 'territorial-risk', label: 'Carte / territoire', state: 'ready', freshness: 'scoring actif', count: this.fusedMapPreview().zones.length || 5, confidence: 78 },
      { key: 'visual-streams', label: 'Observations visuelles', state: 'monitoring', freshness: 'snapshot recent', count: this.cockpit()?.visual_summary?.observations || 1, confidence: 62 },
      { key: 'maritime-traffic', label: 'Maritime / douanes', state: 'snapshot', freshness: 'provider optionnel', count: 5, confidence: 66 },
    ];
  }

  evidenceGraphSummary(): MissionCockpit['evidence_graph_summary'] | null {
    return this.cockpit()?.evidence_graph_summary || null;
  }

  sixtySecondCockpit(): NonNullable<MissionCockpit['sixty_second_cockpit']> {
    return this.cockpit()?.sixty_second_cockpit || {};
  }

  attentionItems60(): AttentionRequiredItem[] {
    const direct = this.cockpit()?.attention_required;
    const sixty = this.cockpit()?.sixty_second_cockpit?.urgences;
    const priorities = (this.cockpit()?.priorities || []).map((priority) => ({
      id: priority.id,
      title: priority.title,
      sentence: priority.summary,
      deadline: priority.deadline,
      kind: priority.kind,
      tone: priority.tone,
    }));
    return (direct?.length ? direct : sixty?.length ? sixty : priorities).slice(0, 3);
  }

  attentionTone(item: AttentionRequiredItem): string {
    const raw = `${item.tone || ''} ${item.status || ''}`.toLowerCase();
    if (raw.includes('critical') || raw.includes('critique')) return 'critical';
    if (raw.includes('watch') || raw.includes('attente') || raw.includes('pret') || raw.includes('ready')) return 'watch';
    return 'stable';
  }

  attentionActionLabel(item: AttentionRequiredItem): string {
    return item.action_label || 'Ouvrir action';
  }

  agendaFocus60(): AgendaItem | null {
    return this.cockpit()?.sixty_second_cockpit?.agenda_focus?.[0] || this.cockpit()?.agenda?.[0] || null;
  }

  fusedMapPreview(): NonNullable<MissionCockpit['fused_map_preview']> {
    const direct = this.cockpit()?.fused_map_preview;
    if (direct) return direct;
    const zones = this.missionMap()?.zones || this.cockpit()?.situation_monitor?.top_zones || [];
    return {
      route: '/hypervisor/mission-room/strategie',
      label: 'Carte fusionnee',
      question: 'Quelles zones necessitent une action preventive non militaire ce mois-ci ?',
      top_zone: zones[0],
      zones,
      layers: [
        { key: 'press', label: 'Presse', count: 10, tone: 'elevated', visible: true },
        { key: 'projects', label: 'Projets', count: 5, tone: 'stable', visible: true },
        { key: 'agenda', label: 'Agenda', count: 6, tone: 'watch', visible: true },
        { key: 'visual', label: 'Visuel', count: this.cockpit()?.visual_summary?.observations || 1, tone: 'monitoring', visible: true },
      ],
      heatmap: zones.slice(0, 3).map((zone) => ({ label: zone.name, score: zone.level, tone: zone.tone })),
      source_label: 'Presse + projets + agenda + observations',
    };
  }

  territorialLiveStatus(): { zone: string; level: string; bars: number; summary: string; tone: string }[] {
    const direct = this.cockpit()?.territorial_live_status;
    if (direct?.length) return direct;
    const zones = this.fusedMapPreview().zones;
    if (zones.length) {
      return zones.slice(0, 5).map((zone) => ({
        zone: zone.name,
        level: zone.level >= 75 ? 'critique' : zone.level >= 50 ? 'surveillance' : 'stable',
        bars: Math.max(1, Math.min(4, Math.ceil(zone.level / 25))),
        summary: zone.signals?.[0] || zone.recommendations?.[0] || 'suivi territorial',
        tone: this.monitorTone(zone.tone),
      }));
    }
    return [
      { zone: 'Nord', level: 'critique', bars: 4, summary: 'Incident frontière · arbitrage attendu', tone: 'critical' },
      { zone: 'Ouest', level: 'surveillance', bars: 3, summary: 'Rumeur locale en progression', tone: 'elevated' },
      { zone: 'Centre', level: 'stable', bars: 2, summary: 'Projets sous controle', tone: 'stable' },
      { zone: 'Sud', level: 'operationnel', bars: 1, summary: this.missionBrandStyle() === 'agentium' ? 'Meridian nominal' : 'Abidjan nominal', tone: 'stable' },
    ];
  }

  agendaDay(): NonNullable<MissionCockpit['agenda_day']> {
    const direct = this.cockpit()?.agenda_day;
    if (direct) return direct;
    const events = this.cockpit()?.agenda || this.timeline()?.agenda || [];
    return {
      label: 'Agenda ministeriel',
      next_event: this.agendaFocus60(),
      events,
      available_window: {
        label: 'Avant point presse',
        time: '13:40-14:00',
        reason: 'Dernier creneau utile pour valider une reponse publique.',
      },
    };
  }

  sovereignIndicators(): NonNullable<MissionCockpit['sovereign_indicators']> {
    const direct = this.cockpit()?.sovereign_indicators;
    if (direct?.length) return direct;
    return [
      { label: 'Menace nationale', value: this.sixtySecondCockpit().menace?.score || 85, unit: '/100', source: 'Carte + veille', confidence: '72%', trend: 'hausse', tone: 'critical' },
      { label: "Reputation de l'Etat", value: this.cockpit()?.reputation?.score || 63, unit: '%', source: 'Presse locale', confidence: '68%', trend: '+5 pts', tone: 'stable' },
      { label: 'Arbitrages', value: this.decisionQueue().length || 3, unit: '', source: 'Cabinet', confidence: 'haute', trend: 'avant 15h', tone: 'elevated' },
      { label: 'Agenda critique', value: this.agendaDay().events?.length || 5, unit: '', source: 'Agenda habilite', confidence: 'haute', trend: 'journee chargee', tone: 'monitoring' },
    ];
  }

  decisionQueue(): NonNullable<MissionCockpit['decision_queue']> {
    const direct = this.cockpit()?.decision_queue;
    if (direct?.length) return direct;
    const packages = this.cockpit()?.executive_decision_packages || [];
    if (packages.length) {
      return packages.map((item) => ({
        id: String(item['id'] || item['target_id'] || item['title']),
        label: String(item['label'] || 'Arbitrage'),
        title: String(item['title'] || item['label'] || 'Decision cabinet'),
        decision: String(item['decision'] || item['summary'] || ''),
        recommended_option: String(item['recommended_option'] || item['recommendation'] || item['summary'] || ''),
        why_now: String(item['why_now'] || item['rationale'] || ''),
        deadline: String(item['deadline'] || '15:00'),
        owner: String(item['owner'] || 'Cabinet'),
        confidence: Number(item['confidence'] || 0.68),
        status: String(item['status'] || 'validation_required'),
        tone: String(item['tone'] || 'elevated'),
        sources: Array.isArray(item['sources']) ? item['sources'] : [],
        cta: String(item['cta'] || 'Preparer arbitrage'),
        email_draft_ready: Boolean(item['email_draft_ready']),
        validation_required: true,
      }));
    }
    return [
      {
        id: 'attention-inter-budget',
        label: 'Presse',
        title: "Article L'Inter - budget defense",
        decision: 'Valider une reponse publique prudente.',
        recommended_option: 'Projet de reponse au responsable communication avant 14h00.',
        why_now: 'L’article peut structurer le point presse hebdomadaire.',
        deadline: '14:00',
        owner: 'Cabinet communication',
        confidence: 0.72,
        status: 'validation_required',
        tone: 'elevated',
        sources: ['L’Inter', 'veille presse'],
        cta: 'Preparer email',
        email_draft_ready: true,
        validation_required: true,
      },
    ];
  }

  geographicSignalTiers(): NonNullable<MissionCockpit['geographic_signal_tiers']> {
    const direct = this.cockpit()?.geographic_signal_tiers;
    if (direct?.length) return direct;
    const newsSections = this.news()?.geo_sections || [];
    if (newsSections.length) {
      return newsSections.map((section) => ({
        key: section.key,
        label: section.label,
        count: section.count,
        top_signal: section.signals?.[0]?.title || null,
        signals: section.signals || [],
      }));
    }
    return [
      { key: 'ci', label: this.missionBrandStyle() === 'agentium' ? 'Asteria' : "Cote d'Ivoire", count: 3, top_signal: 'Article budget defense et rumeur sociale locale', signals: [] },
      { key: 'cedeao', label: this.missionBrandStyle() === 'agentium' ? 'Alliance Aurora' : 'CEDEAO', count: 2, top_signal: this.missionBrandStyle() === 'agentium' ? 'Coordination Northern Belt' : 'Coordination frontière Burkina', signals: [] },
      { key: 'africa', label: this.missionBrandStyle() === 'agentium' ? 'Atlantic Arc' : 'Afrique', count: 4, top_signal: 'Tensions regionales a surveiller', signals: [] },
      { key: 'world', label: 'Monde', count: 1, top_signal: this.missionBrandStyle() === 'agentium' ? 'Lecture diplomatique Aurora-AS' : 'Lecture diplomatique France-CI', signals: [] },
    ];
  }

  arbitrationCards(): VpArbitrationCard[] {
    const direct = this.cockpit()?.arbitration_cards;
    if (direct?.length) return direct.slice(0, 3);
    return this.attentionItems60().slice(0, 3).map((item, index) => this.buildArbitrationCard(item, index + 1));
  }

  intelligenceFeeds(): VpIntelligenceFeed[] {
    const direct = this.cockpit()?.intelligence_feeds;
    if (direct?.length) return direct.slice(0, 8);
    const layers = this.cockpit()?.monitoring_layers || [];
    if (layers.length) {
      return layers.slice(0, 8).map((layer) => ({
        key: String(layer.key || layer.name || layer.label || 'feed'),
        label: String(layer.label || layer.name || 'Source'),
        subtitle: String(layer.source_kind || 'source qualifiee'),
        metric: `${layer.count || 0} signaux`,
        confidence: Number(layer.confidence || 50),
        freshness_at: layer.freshness,
        tone: layer.visible === false ? 'monitoring' : 'stable',
      }));
    }
    return [
      { key: 'satellite', label: 'Imagerie satellite', subtitle: 'Couverture Nord · indicative', metric: '2 zones', confidence: 68, tone: 'monitoring' },
      { key: 'maritime', label: 'Trafic maritime AIS', subtitle: this.missionBrandStyle() === 'agentium' ? 'Port Meridian · corridor actif' : 'Port Abidjan · corridor actif', metric: '5 navires', confidence: 66, tone: 'elevated' },
      { key: 'adsb', label: 'Espace aerien ADS-B', subtitle: this.missionBrandStyle() === 'agentium' ? 'Perimetre Northern Belt · veille' : 'Perimetre Sahel · veille', metric: 'nominal', confidence: 61, tone: 'stable' },
      { key: 'osint', label: 'OSINT multilingue', subtitle: 'Presse africaine qualifiee', metric: `${this.kpiNumber('analyzed_articles') || 80} articles`, confidence: 72, tone: 'stable' },
      { key: 'mobile', label: 'Signal reseau mobile', subtitle: 'Nord · faible densite', metric: '3 clusters', confidence: 58, tone: 'monitoring' },
      { key: 'economy', label: 'Economie reelle', subtitle: this.missionBrandStyle() === 'agentium' ? 'Douanes Meridian · retard BTP' : 'Douanes Abidjan · retard BTP', metric: '2 signaux', confidence: 64, tone: 'elevated' },
      { key: 'terrain', label: 'Capteurs terrain', subtitle: '16 capteurs Nord', metric: 'actif', confidence: 62, tone: 'critical' },
      { key: 'cyber', label: 'Veille cyber', subtitle: 'Canaux habilites', metric: 'stable', confidence: 70, tone: 'stable' },
    ];
  }

  pressPreview(): VpPressPreviewItem[] {
    const direct = this.cockpit()?.press_preview;
    if (direct?.length) return direct.slice(0, 3).map((item) => this.normalizePressPreviewItem(item));
    const alerts = this.newsAlerts().slice(0, 3);
    if (alerts.length) {
      return alerts.map((signal) => ({
        id: signal.id,
        title: signal.title,
        source: signal.source_name || signal.source,
        risk: signal.risk_level,
        risk_label: this.ministerialRisk(signal.risk_level),
        summary: signal.summary,
        tone: signal.risk_level,
        drill_down: { view: 'presse', anchor: signal.id },
      }));
    }
    return this.attentionItems60()
      .filter((item) => this.openAttentionTargetLooksPress(item))
      .slice(0, 3)
      .map((item) => ({
        id: item.id || 'attention-inter-budget',
        title: item.title,
        source: "L'Inter",
        risk: this.attentionTone(item),
        risk_label: 'Reponse a valider',
        summary: item.sentence || item.summary,
        tone: this.attentionTone(item),
        drill_down: { view: 'presse', anchor: item.id || 'attention-inter-budget' },
      }));
  }

  agendaTimeline(): VpAgendaTimeline {
    const direct = this.cockpit()?.agenda_timeline;
    if (direct?.events?.length) return direct;
    const day = this.agendaDay();
    const events = (day.events || []).slice(0, 4).map((event, index) => ({
      id: event.id,
      time: event.time,
      end_time: event.end_time,
      title: event.title,
      location: event.location,
      tone: event.tone,
      is_now: index === 1,
      countdown: index === 1 ? 'dans 1h44' : undefined,
    }));
    return {
      label: day.label,
      now_marker: 'MAINTENANT',
      events,
      separate_from_actions: true,
    };
  }

  vpMapPreviewContext(): VpMapPreviewContext {
    const preview = this.fusedMapPreview();
    const geoPreview = preview.geo_preview || this.buildGeoPreviewFallback(preview);
    const topZone = preview.top_zone || preview.zones?.[0];
    return {
      route: preview.route || '/hypervisor/mission-room/strategie',
      label: preview.label || 'Carte fusionnee',
      zones: (preview.zones || []) as unknown as Record<string, unknown>[],
      map: (this.missionMap()?.map as Record<string, unknown>) || null,
      mapSystem: (this.missionMap()?.map_system as Record<string, unknown>) || null,
      geoPreview,
      topZoneId: geoPreview.top_zone_id || topZone?.id || null,
    };
  }

  decisionTeaser(): { id: string; title: string; recommended_option: string; deadline?: string; confidence?: number } | null {
    const queue = this.decisionQueue();
    const zonePackage = queue.find((item) => `${item.id} ${item.title}`.toLowerCase().includes('nord')) || queue[0];
    if (!zonePackage) return null;
    return {
      id: zonePackage.id,
      title: zonePackage.title,
      recommended_option: zonePackage.recommended_option,
      deadline: zonePackage.deadline,
      confidence: zonePackage.confidence,
    };
  }

  morningHighlightMessage(): string | null {
    if (this.morningHighlightDismissed()) return null;
    const narrative = this.cockpit()?.demo_narrative?.steps?.find((step) => step.phase === 'comprendre');
    if (narrative?.prompt) return narrative.prompt;
    const item = this.pressPreview()[0];
    if (!item) return null;
    return `Un signal presse ressort de la nuit — voulez-vous voir le projet de reponse pour « ${item.title} » ?`;
  }

  zoneNorthOptionCompare(): VpOptionCompare | null {
    const zone = (this.missionMap()?.zones || []).find((item) => `${item.id} ${item.name}`.toLowerCase().includes('nord'));
    const options = zone?.scenario_options || [];
    if (options.length >= 2) {
      const optionA = options[0];
      const optionB = options.find((item) => item.recommended) || options[1];
      return {
        title: `Arbitrage ${zone?.name || 'Zone Nord'}`,
        subtitle: `Comparaison risque, cout, deploiement, reputation et lecture ${this.missionBrandStyle() === 'agentium' ? 'Aurora' : 'CEDEAO'}.`,
        option_a_label: optionA.label,
        option_b_label: optionB.label,
        recommended: optionB.recommended ? 'b' : 'a',
        metrics: [
          { key: 'risk', label: 'Risque securitaire', option_a: optionA.risk_reduction ?? 42, option_b: optionB.risk_reduction ?? 68 },
          { key: 'cost', label: 'Cout / effort', option_a: 100 - (optionA.cost_score ?? 35), option_b: 100 - (optionB.cost_score ?? 58) },
          { key: 'deploy', label: 'Delai deploiement', option_a: optionA.time_sensitivity ?? 48, option_b: optionB.time_sensitivity ?? 72 },
          { key: 'reputation', label: 'Reputation Etat', option_a: optionA.impact_score ?? 44, option_b: optionB.impact_score ?? 71 },
          { key: 'cedeao', label: this.missionBrandStyle() === 'agentium' ? 'Lecture Aurora' : 'Lecture CEDEAO', option_a: 52, option_b: 74 },
        ],
      };
    }
    return {
      title: 'Arbitrage Zone Nord',
      subtitle: 'Coordination locale vs arbitrage cabinet avant Conseil 15h00.',
      option_a_label: 'Option A · coordination locale',
      option_b_label: 'Option B · arbitrage cabinet',
      recommended: 'b',
      metrics: [
        { key: 'risk', label: 'Risque securitaire', option_a: 42, option_b: 68 },
        { key: 'cost', label: 'Cout / effort', option_a: 65, option_b: 42 },
        { key: 'deploy', label: 'Delai deploiement', option_a: 78, option_b: 55 },
        { key: 'reputation', label: 'Reputation Etat', option_a: 48, option_b: 71 },
        { key: 'cedeao', label: this.missionBrandStyle() === 'agentium' ? 'Lecture Aurora' : 'Lecture CEDEAO', option_a: 52, option_b: 74 },
      ],
    };
  }

  compareAnchor(): string {
    return this.highlightTarget() || 'package-zone-nord';
  }

  openDrillDown(card: Pick<VpArbitrationCard, 'id' | 'drill_down'>): void {
    this.navigateDrillDown(card.drill_down, card.id);
  }

  navigateDrillDown(drill: VpDrillDown, fallbackAnchor?: string): void {
    this.openDrillDownView(
      drill.view,
      drill.anchor || fallbackAnchor,
      drill.route,
      { zone: drill.zone, layers: drill.layers },
    );
  }

  openDrillDownView(
    view: VpDrillDown['view'],
    anchor?: string,
    route?: string,
    options?: Pick<VpDrillDown, 'zone' | 'layers'>,
    focus?: string,
  ): void {
    const normalizedView = view === 'briefing' ? 'decisions' : view === 'monitor' ? 'strategie' : view;
    const target = route || `/hypervisor/mission-room/${normalizedView}`;
    const queryParams: Record<string, string> = {};
    if (anchor) queryParams['highlight'] = anchor;
    if (focus) queryParams['focus'] = focus;
    const zone =
      options?.zone
      || (normalizedView === 'strategie' ? this.vpMapPreviewContext().geoPreview.top_zone_id || undefined : undefined);
    const layers =
      options?.layers
      || (normalizedView === 'strategie'
        ? this.vpMapPreviewContext().geoPreview.active_layers?.join(',')
        : undefined);
    if (zone) queryParams['zone'] = zone;
    if (layers) queryParams['layers'] = layers;
    if (normalizedView === 'strategie' && view === 'monitor') queryParams['mode'] = 'live';
    this.router.navigate([target], { queryParams }).then(() => this.scrollToHighlight());
  }

  selectArbitrationCard(card: VpArbitrationCard): void {
    // Pure selection: surface the card in the right-hand detail panel of the
    // decisions/arbitrages view without immediately drilling into the source
    // surface. The deep drill is exposed as an explicit click via
    // ``openArbitrationDetailDrillDown``.
    this.selectedArbitrationCard.set(card);
  }

  /**
   * Cockpit entry point — never drills directly into a press article or zone
   * dossier. Always lands on ``/decisions`` (the list+detail arbitrages view)
   * so the user keeps the context of *which* item they picked among the day's
   * arbitrages before going deeper.
   */
  openArbitrationFromCockpit(card: VpArbitrationCard): void {
    this.selectedArbitrationCard.set(card);
    this.openDrillDownView('decisions', card.id);
  }

  arbitrationDrillLabel(card: VpArbitrationCard): string {
    const pressLike = card.domain === 'PRESSE' || card.drill_down?.view === 'presse';
    if (pressLike) return 'Voir l article';
    const nordLike =
      card.domain === 'DEFENSE'
      || card.domain_label === 'Defense'
      || `${card.id} ${card.title}`.toLowerCase().includes('nord');
    if (nordLike) return 'Ouvrir le dossier Zone Nord';
    return 'Arbitrer les options';
  }

  /**
   * Explicit drill-down from the arbitrage detail panel — opens the press
   * article drawer, the Zone Nord dossier, or the configured drill route.
   */
  openArbitrationDetailDrillDown(card: VpArbitrationCard): void {
    const pressLike = card.domain === 'PRESSE' || card.drill_down?.view === 'presse';
    if (pressLike) {
      const article = this.allNewsSignals().find((signal) => signal.id === card.id);
      if (article) {
        this.openPressArticle(article);
        return;
      }
    }
    const nordLike =
      card.domain === 'DEFENSE'
      || card.domain_label === 'Defense'
      || `${card.id} ${card.title}`.toLowerCase().includes('nord');
    if (nordLike) {
      this.openZoneNordDossier();
      return;
    }
    this.navigateDrillDown(card.drill_down || { view: 'decisions', anchor: card.id }, card.id);
  }

  setMapViewMode(mode: 'territory' | 'live'): void {
    const queryParams: Record<string, string | undefined> = {
      mode,
      zone: this.zoneQuery() || undefined,
      highlight: this.highlightQuery() || undefined,
      layers: this.layersQuery() || undefined,
    };
    void this.router.navigate(['/hypervisor/mission-room/strategie'], { queryParams });
  }

  openPressPreviewItem(item: VpPressPreviewItem): void {
    const article = this.allNewsSignals().find((signal) => signal.id === item.id);
    if (article) {
      this.openPressArticle(article);
      return;
    }
    const drill = this.resolvePressPreviewDrillDown(item);
    this.navigateDrillDown(drill, item.id);
  }

  openZoneNordDossier(): void {
    this.openDrillDownView('strategie', 'projet-napie', undefined, {
      zone: 'zone-nord',
      layers: 'threat,press,maritime-traffic',
    });
    setTimeout(
      () => this.openAssistant('AYA, pourquoi la situation Nord est-elle tendue ?'),
      240,
    );
  }

  openSecurityMonitor(): void {
    void this.router.navigate(['/hypervisor/mission-room/securite/monitor'], {
      queryParams: { panel: 'satellite-imagery-rail' },
    });
  }

  focusSecurityMapFromRumor(): void {
    this.openDrillDownView('strategie', undefined, undefined, {
      zone: 'zone-nord',
      layers: 'border-tension,social-geo,military-air',
    });
  }

  highlightedStrategicVesselMmsi(): string | null {
    return this.selectedStrategicVessel()?.mmsi || this.maritimeTracking.selectedVessel()?.mmsi || null;
  }

  selectStrategicVessel(vessel: VesselPosition): void {
    if (!vessel?.mmsi) return;
    this.selectedStrategicVessel.set(vessel);
    this.maritimeTracking.selectVessel(vessel);
    this.mapCommandState.set({
      ...(this.mapCommandState() || {}),
      active_layers: ['territorial-risk', 'open-intelligence', 'visual-streams', 'maritime-traffic'],
      camera: {
        longitude: Number(vessel.lon),
        latitude: Number(vessel.lat),
        zoom: 11.2,
        duration_ms: 220,
      },
      focus_marker: {
        longitude: Number(vessel.lon),
        latitude: Number(vessel.lat),
        label: vessel.name || vessel.mmsi,
        tone: 'maritime',
      },
    });
  }

  clearStrategicVessel(): void {
    this.selectedStrategicVessel.set(null);
    this.maritimeTracking.clearSelection();
  }

  selectStrategicZone(zone: MapZone): void {
    this.clearStrategicVessel();
    this.selectZone(zone);
  }

  strategicVesselHasPortWebcam(vessel: VesselPosition): boolean {
    return Boolean(
      vessel.recommended_webcam_source_id
      || vessel.linked_cargo_id === 'cargo-abidjan-supply-001'
      || vessel.mmsi === '627012345',
    );
  }

  openStrategicVesselPort(vessel: VesselPosition): void {
    const sourceId =
      vessel.recommended_webcam_source_id
      || (vessel.linked_cargo_id === 'cargo-abidjan-supply-001' || vessel.mmsi === '627012345'
        ? 'apm-apapa-gate-1'
        : '');
    if (!sourceId) return;
    window.dispatchEvent(
      new CustomEvent('agentium:assistant-show-webcam', {
        detail: {
          source_id: sourceId,
          vessel_mmsi: vessel.mmsi,
          vessel_name: vessel.name,
          cargo_id: vessel.linked_cargo_id || null,
        },
      }),
    );
    void this.router.navigate(['/hypervisor/mission-room/strategie'], {
      queryParams: {
        mode: 'live',
        panel: 'maritime',
        layers: 'maritime-traffic,visual-streams',
        zone: 'zone-sud',
        vessel: vessel.mmsi,
        ...(vessel.linked_cargo_id ? { cargo: vessel.linked_cargo_id } : {}),
      },
    });
  }

  openCockpitVesselDrillDown(vessel: VesselPosition): void {
    this.maritimeTracking.selectVessel(vessel);
    const isDemoCargo =
      vessel.mmsi === '627012345'
      || vessel.linked_cargo_id === 'cargo-abidjan-supply-001'
      || /atlantic trader/i.test(vessel.name || '');
    const cargoId =
      vessel.linked_cargo_id
      || (isDemoCargo ? 'cargo-abidjan-supply-001' : undefined);
    if (isDemoCargo) {
      window.dispatchEvent(
        new CustomEvent('agentium:assistant-show-webcam', {
          detail: {
            source_id: vessel.recommended_webcam_source_id || 'apm-apapa-gate-1',
            vessel_mmsi: vessel.mmsi || '627012345',
            vessel_name: vessel.name || 'MV ATLANTIC TRADER',
            cargo_id: cargoId,
          },
        }),
      );
    }
    const queryParams: Record<string, string> = {
      mode: 'live',
      panel: 'maritime',
      layers: 'maritime-traffic,visual-streams',
      zone: 'zone-sud',
    };
    if (vessel.mmsi) queryParams['vessel'] = vessel.mmsi;
    if (cargoId) queryParams['cargo'] = cargoId;
    void this.router.navigate(['/hypervisor/mission-room/strategie'], { queryParams });
  }

  openStatusBarDrillDown(item: VpStatusBarItem): void {
    this.navigateDrillDown(this.statusBarDrillDown(item));
  }

  openSovereignGaugeDrillDown(indicator: VpSovereignIndicator): void {
    this.navigateDrillDown(this.sovereignGaugeDrillDown(indicator));
  }

  openIntelligenceFeedDrillDown(feed: VpIntelligenceFeed): void {
    this.navigateDrillDown(this.intelligenceFeedDrillDown(feed));
  }

  openMapZoneDrillDown(zone: VpZoneScore): void {
    const zoneId = zone.id || this.resolveZoneId(zone.name);
    const layers = this.vpMapPreviewContext().geoPreview.active_layers?.join(',') || 'threat,press';
    this.openDrillDownView('strategie', undefined, undefined, { zone: zoneId, layers });
  }

  openAgendaEventDrillDown(event: VpAgendaTimelineEvent): void {
    const drill = event.drill_down || { view: 'agenda' as const, anchor: event.id };
    this.navigateDrillDown(drill, event.id);
  }

  private resolvePressPreviewDrillDown(item: VpPressPreviewItem & { route?: string; risk_level?: string }): VpDrillDown {
    if (item.drill_down) return item.drill_down;
    const route = item.route;
    if (route) {
      const highlight = route.match(/highlight=([^&]+)/)?.[1];
      const view = route.includes('/decisions')
          ? 'decisions'
          : route.includes('/agenda')
            ? 'agenda'
            : route.includes('/monitor')
              ? 'strategie'
              : route.includes('/briefing')
                ? 'decisions'
                : route.includes('/strategie')
                  ? 'strategie'
                  : 'presse';
      return { view, anchor: highlight || item.id, route };
    }
    return { view: 'presse', anchor: item.id };
  }

  private statusBarDrillDown(item: VpStatusBarItem): VpDrillDown {
    if (item.drill_down) return item.drill_down;
    const defaults: Record<string, VpDrillDown> = {
      'tension-nord': { view: 'strategie', zone: 'zone-nord', layers: 'threat,press,maritime-traffic', anchor: 'projet-napie' },
      posture: { view: 'strategie', layers: 'territorial-risk,open-intelligence' },
      deadline: { view: 'decisions', anchor: 'package-zone-nord' },
      decisions: { view: 'decisions' },
      arbitrages: { view: 'decisions' },
      presse: { view: 'presse' },
      agenda: { view: 'agenda' },
      flux: { view: 'strategie', layers: 'open-intelligence,visual-streams' },
    };
    return defaults[item.key] || { view: 'strategie' };
  }

  private sovereignGaugeDrillDown(indicator: VpSovereignIndicator): VpDrillDown {
    if (indicator.drill_down) return indicator.drill_down;
    const label = indicator.label.toLowerCase();
    if (label.includes('menace')) {
      return { view: 'strategie', zone: 'zone-nord', layers: 'threat,press' };
    }
    if (label.includes('reputation')) return { view: 'presse' };
    if (label.includes('stabilite')) return { view: 'decisions', anchor: 'package-zone-nord' };
    if (label.includes('maritime')) return { view: 'strategie', layers: 'maritime-traffic' };
    if (label.includes('arbitrage')) return { view: 'decisions' };
    if (label.includes('agenda')) return { view: 'agenda' };
    return { view: 'strategie' };
  }

  private intelligenceFeedDrillDown(feed: VpIntelligenceFeed): VpDrillDown {
    if (feed.drill_down) return feed.drill_down;
    const defaults: Record<string, VpDrillDown> = {
      satellite: { view: 'strategie', zone: 'zone-nord', layers: 'threat' },
      'maritime-ais': { view: 'strategie', layers: 'maritime-traffic' },
      maritime: { view: 'strategie', layers: 'maritime-traffic' },
      'ads-b': { view: 'strategie', layers: 'visual-streams' },
      adsb: { view: 'strategie', layers: 'visual-streams' },
      osint: { view: 'presse' },
      'mobile-signal': { view: 'strategie', zone: 'zone-nord' },
      mobile: { view: 'strategie', zone: 'zone-nord' },
      economy: { view: 'strategie', layers: 'open-intelligence' },
      'terrain-sensors': { view: 'strategie', layers: 'visual-streams' },
      terrain: { view: 'strategie', layers: 'visual-streams' },
      cyber: { view: 'strategie', layers: 'open-intelligence' },
    };
    return defaults[feed.key] || { view: 'strategie' };
  }

  private resolveZoneId(name: string): string {
    const normalized = name.toLowerCase();
    const match = (this.missionMap()?.zones || this.fusedMapPreview().zones || []).find(
      (zone) => zone.id === normalized || zone.name.toLowerCase() === normalized,
    );
    if (match?.id) return match.id;
    if (normalized.includes('nord')) return 'zone-nord';
    if (normalized.includes('ouest')) return 'zone-ouest';
    if (normalized.includes('centre')) return 'zone-centre';
    if (normalized.includes('sud')) return 'zone-sud';
    return normalized.replace(/\s+/g, '-');
  }

  openMorningPressHighlight(): void {
    const item = this.pressPreview()[0];
    if (item) this.openPressPreviewItem(item);
  }

  dismissMorningHighlight(): void {
    this.morningHighlightDismissed.set(true);
    const key = this.morningDismissedStorageKey();
    if (key) sessionStorage.setItem(key, '1');
  }

  private readMorningDismissed(slug = this.workspace.currentSlug()): boolean {
    try {
      const key = this.morningDismissedStorageKey(slug);
      if (!key) return false;
      const scoped = sessionStorage.getItem(key);
      if (scoped !== null) return scoped === '1';

      // The extension profile, not a mutable workspace slug, owns this
      // one-time compatibility key. Profiles without a declared migration
      // key (including Octocity) cannot inherit Sentinel session state.
      const legacyKey = missionRoomExtensionState(this.workspace.current())
        .legacyMorningDismissedStorageKey;
      if (!legacyKey) return false;
      const legacy = sessionStorage.getItem(legacyKey);
      if (legacy === null) return false;
      sessionStorage.setItem(key, legacy);
      sessionStorage.removeItem(legacyKey);
      return legacy === '1';
    } catch {
      return false;
    }
  }

  private morningDismissedStorageKey(slug = this.workspace.currentSlug()): string | null {
    return slug
      ? `agentium:mission-room:morning-dismissed:${encodeURIComponent(slug)}`
      : null;
  }

  private buildArbitrationCard(item: AttentionRequiredItem, rank: number): VpArbitrationCard {
    const pressLike = this.openAttentionTargetLooksPress(item);
    const nordLike = `${item.id || ''} ${item.title || ''}`.toLowerCase().includes('nord');
    const agendaLike = `${item.id || ''} ${item.title || ''}`.toLowerCase().includes('ambassadeur')
      || `${item.id || ''} ${item.title || ''}`.toLowerCase().includes('agenda');
    const view: VpDrillDown['view'] = pressLike ? 'presse' : nordLike ? 'briefing' : agendaLike ? 'agenda' : 'decisions';
    return {
      id: item.id || `attention-${rank}`,
      rank,
      domain: pressLike ? 'PRESSE' : nordLike ? 'DEFENSE' : agendaLike ? 'DIPLOMATIE' : 'CABINET',
      domain_label: pressLike ? 'Presse' : nordLike ? 'Defense' : agendaLike ? 'Diplomatie' : 'Cabinet',
      title: item.title,
      summary: item.sentence || item.summary || '',
      status: item.status || 'validation_required',
      status_label: pressLike ? 'REPONSE A VALIDER' : 'DECISION REQUISE',
      deadline: item.deadline || 'ce matin',
      tone: this.attentionTone(item),
      cta_label: pressLike ? 'Preparer reponse' : 'Arbitrer',
      drill_down: { view, anchor: item.id || `attention-${rank}` },
      draft_ready: pressLike,
      aya_prepared: true,
    };
  }

  private buildGeoPreviewFallback(preview: NonNullable<MissionCockpit['fused_map_preview']>): VpMapPreviewContext['geoPreview'] {
    const zones = preview.zones || [];
    return {
      active_layers: ['threat', 'press', 'maritime'],
      zone_scores: zones.slice(0, 4).map((zone) => ({
        id: zone.id,
        name: zone.name,
        score: zone.level,
        trend: zone.tone === 'critical' ? '+12/24h' : zone.tone === 'watch' ? '+4/24h' : 'stable',
        tone: zone.tone,
      })),
      top_zone_id: preview.top_zone?.id || zones[0]?.id || 'zone-nord',
    };
  }

  private normalizePressPreviewItem(
    item: VpPressPreviewItem & { route?: string; risk_level?: string },
  ): VpPressPreviewItem {
    const risk = item.risk || item.risk_level || 'medium';
    if (item.drill_down) return { ...item, risk };
    return {
      ...item,
      risk,
      drill_down: this.resolvePressPreviewDrillDown(item),
    };
  }

  private applyAssistantFocus(effect: AssistantNavigateEffect): void {
    const focusNode =
      effect.metadata?.last_focus
      || effect.metadata?.focus_node_id
      || effect.highlight
      || effect.queryParams?.['focus_node']
      || effect.queryParams?.['highlight'];
    if (!focusNode) return;
    const focusType = (effect.metadata?.focus_node_type || '').toLowerCase();
    const normalized = String(focusNode).toLowerCase();
    const zones = [
      ...((this.missionMap()?.zones || []) as MapZone[]),
      ...((this.monitor()?.zones || []) as MapZone[]),
    ];
    const zoneMatch = zones.find(
      (zone) =>
        zone.id === focusNode
        || zone.id?.toLowerCase() === normalized
        || zone.name?.toLowerCase() === normalized
        || (normalized.includes('nord') && zone.id === 'zone-nord')
        || (normalized.includes(zone.id?.toLowerCase() || '__never__')),
    );
    if (zoneMatch && (!focusType || focusType === 'zone' || focusType === 'territory')) {
      this.selectedZone.set(zoneMatch);
      this.mapCommandState.set({
        ...(this.mapCommandState() || {}),
        preset: 'zone',
        zone: zoneMatch.id,
        zoom: 'territory',
        highlight: true,
      });
    }
    const projects = this.projects()?.projects || [];
    const projectMatch = projects.find(
      (project) => project.id === focusNode || project.id.toLowerCase() === normalized,
    );
    if (projectMatch && (!focusType || focusType === 'project')) {
      this.selectedProject.set(projectMatch);
    }
    const arbitrationMatch = this.arbitrationCards().find(
      (card) => card.id === focusNode || card.id.toLowerCase() === normalized,
    );
    if (arbitrationMatch && (!focusType || focusType === 'arbitration' || focusType === 'decision')) {
      this.selectedArbitrationCard.set(arbitrationMatch);
    }
    setTimeout(() => this.scrollToHighlight(), 160);
  }

  private scrollToHighlight(): void {
    const target = this.highlightTarget();
    if (!target) return;
    if (this.currentView() === 'presse') {
      const article = this.allNewsSignals().find((signal) => signal.id === target);
      if (article) {
        this.openPressArticle(article);
        return;
      }
    }
    setTimeout(() => {
      const element = document.getElementById(target)
        || document.querySelector(`[id="${target}"]`)
        || document.querySelector('.highlighted');
      element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 180);
  }

  private applyMapQueryState(): void {
    const layers = this.layersQuery();
    const zone = this.zoneQuery();
    const mode = this.modeQuery();
    if (!layers && !zone && !mode) return;
    const active_layers = layers ? layers.split(',').map((item) => item.trim()).filter(Boolean) : undefined;
    this.mapCommandState.set({
      ...(this.mapCommandState() || {}),
      active_layers: mode === 'maritime'
        ? ['territorial-risk', 'open-intelligence', 'visual-streams', 'maritime-traffic']
        : active_layers,
      selected_zone: zone || undefined,
      preset: zone ? 'zone' : undefined,
      zone,
    });
    if (zone) {
      const match = (this.missionMap()?.zones || []).find((item) => item.id === zone || item.name.toLowerCase() === zone.toLowerCase());
      if (match) this.selectedZone.set(match);
    }
  }

  createAttentionDraft(item: AttentionRequiredItem): void {
    const targetId = item.id || item.title;
    const targetType = item.draft_target_type
      || (this.openAttentionTargetLooksPress(item) ? 'press_response' : 'decision');
    this.createDraft(targetId, targetType);
  }

  private openAttentionTargetLooksPress(item: AttentionRequiredItem): boolean {
    const target = `${item.id || ''} ${item.title || ''} ${item.sentence || ''}`.toLowerCase();
    return target.includes('inter') || target.includes('article') || target.includes('presse') || target.includes('reponse');
  }

  openAttentionItem(item: AttentionRequiredItem): void {
    const target = `${item.id || ''} ${item.title || ''} ${item.sentence || ''}`.toLowerCase();
    if (target.includes('article') || target.includes('inter') || target.includes('presse') || target.includes('critique')) {
      this.router.navigateByUrl('/hypervisor/mission-room/presse');
      return;
    }
    if (target.includes('nord') || target.includes('frontiere') || target.includes('burkina')) {
      this.focusZoneInMonitor('Nord');
      return;
    }
    if (target.includes('ambassadeur') || target.includes('agenda') || target.includes('dejeuner')) {
      this.router.navigateByUrl('/hypervisor/mission-room/agenda');
      return;
    }
    this.router.navigateByUrl('/hypervisor/mission-room/decisions');
  }

  ministerialRisk(level: string): string {
    const normalized = (level || '').toLowerCase();
    if (this.missionBrandStyle() === 'agentium') {
      if (normalized === 'critical' || normalized === 'high') return 'priority';
      if (normalized === 'medium') return 'watch';
      return 'monitoring';
    }
    if (normalized === 'critical' || normalized === 'high') return 'prioritaire';
    if (normalized === 'medium') return 'a suivre';
    return 'veille';
  }

  confidencePct(value?: number): string {
    const confidence = typeof value === 'number' ? value : 0.62;
    return `${Math.round(Math.max(0, Math.min(confidence, 1)) * 100)}%`;
  }

  intelligenceStatusLabel(status?: string): string {
    const normalized = (status || '').toLowerCase();
    if (normalized === 'completed') return 'veille a jour';
    if (normalized === 'running') return 'veille en cours';
    if (normalized === 'failed') return 'veille a verifier';
    if (normalized === 'fixture') return 'scenario de reference';
    return 'veille prete';
  }

  postureLabel(posture?: StrategicPosture | null): string {
    if (!posture) return 'monitoring · posture consolidee';
    const labels: Record<string, string> = {
      stable: 'stable',
      monitoring: 'monitoring',
      elevated: 'elevated',
      critical: 'critical',
    };
    return `${labels[posture.label] || posture.label} · ${posture.score}/100`;
  }

  monitorTone(level?: string | null): string {
    const normalized = (level || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'high') return 'elevated';
    if (normalized === 'stable') return 'stable';
    return 'monitoring';
  }

  barHeight(value: number): number {
    return Math.max(8, Math.min(100, (value / 50) * 100));
  }

  zonePulseRadius(zone: MapZone): number {
    return Math.max(6, Math.min(18, zone.level / 7));
  }

  trendPath(values: number[], yMax = 170, yMin = 24): string {
    if (!values.length) return '';
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const span = Math.max(max - min, 1);
    return values
      .map((value, index) => {
        const x = 20 + index * (480 / Math.max(values.length - 1, 1));
        const y = yMax - ((value - min) / span) * (yMax - yMin);
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ');
  }

  trendArea(values: number[]): string {
    const path = this.trendPath(values);
    if (!path) return '';
    return `${path} L500 170 L20 170 Z`;
  }

  zoneFill(zone: MapZone): string {
    if (zone.tone === 'critical') return 'var(--mission-danger)';
    if (zone.tone === 'watch') return 'var(--mission-warn)';
    return 'var(--mission-trust)';
  }

  captureVisualSource(source: VisualSource): void {
    if (!source?.id) return;
    this.api.post<{ capture?: { id?: string } }>(`/visual-intelligence/sources/${source.id}/capture`, {}).subscribe((result) => {
      const captureId = result?.capture?.id;
      this.router.navigate(['/hypervisor/mission-room/monitor'], {
        queryParams: captureId ? { capture: captureId, panel: 'visual' } : { panel: 'visual' },
      });
      this.loadAll();
    });
  }

  private hydrateVisualCaptureImages(monitor: MissionMonitor): void {
    const captures = (monitor.visual?.captures || [])
      .filter((capture) => capture.status === 'analyzed' || capture.status === 'captured')
      .slice(0, 4);
    const existing = this.visualCaptureImages();
    captures.forEach((capture) => {
      if (!capture.id || existing[capture.id]) return;
      this.api.getBlob(`/visual-intelligence/captures/${capture.id}/image`).subscribe({
        next: (blob) => {
          const url = URL.createObjectURL(blob);
          this.visualObjectUrls.push(url);
          this.visualCaptureImages.update((images) => ({ ...images, [capture.id]: url }));
        },
      });
    });
  }

  selectZone(zone: MapZone): void {
    this.selectedZone.set(zone);
  }

  selectZoneByName(name: string): void {
    const zone = (this.missionMap()?.zones || []).find((item) => item.name === name);
    if (zone) this.selectedZone.set(zone);
    this.router.navigateByUrl('/hypervisor/mission-room/strategie');
  }

  focusZoneInMonitor(name: string): void {
    const zone = (this.missionMap()?.zones || this.monitor()?.zones || []).find((item) => item.name === name);
    if (zone) this.selectedZone.set(zone);
    this.mapCommandState.set({
      preset: 'zone',
      zone: zone?.id || name,
      zoom: 'territory',
      highlight: true,
    });
    void this.router.navigate(['/hypervisor/mission-room/strategie'], {
      queryParams: { mode: 'territory', zone: zone?.id || undefined },
    });
  }

  selectProject(project: Project): void {
    this.selectedProject.set(project);
  }

  projectDecisionRisks(): Project[] {
    return (this.projects()?.projects || [])
      .filter((project) => project.weather === 'red' || project.weather === 'orange')
      .slice(0, 3);
  }

  focusPriority(priority: Priority): void {
    if (priority.kind === 'decision_required') {
      this.router.navigateByUrl('/hypervisor/mission-room/presse');
      return;
    }
    if (priority.id === 'prio-security-north') {
      this.focusZoneInMonitor('Nord');
      return;
    }
    if (priority.kind === 'mail') {
      this.router.navigateByUrl('/hypervisor/mission-room/decisions');
      return;
    }
    this.router.navigateByUrl('/hypervisor/mission-room/agenda');
  }

  goToDecisions(): void {
    this.router.navigateByUrl('/hypervisor/mission-room/decisions');
  }

  sourceLabel(sourceId: string): string {
    return this.sources().get(sourceId)?.label || sourceId;
  }

  systemRouteFor(view: MissionView): string | null {
    const item = (this.navigation()?.items || []).find((nav) => nav.key === view);
    return item?.system_id ? `/systems/${item.system_id}` : null;
  }

  showSource(sourceId: string): void {
    this.selectedSource.set(this.sources().get(sourceId) || null);
  }

  openAssistant(prompt?: string, options?: { voiceLoop?: boolean }): void {
    const initialPrompt = prompt ? prompt.replace(/\bAYA\b/g, this.assistantName()) : null;
    this.chat.open({
      mode: 'quick',
      assistantProfile: this.assistantProfileKey(),
      initialPrompt,
      autoStartVoiceLoop: !!options?.voiceLoop,
    });
  }

  openAssistantVoice(prompt?: string): void {
    this.openAssistant(prompt, { voiceLoop: true });
  }

  handleMapEvidenceAction(event: { action: string; zone: any }): void {
    const zone = event?.zone;
    const title = zone?.popup_brief?.title || zone?.name || 'la zone sélectionnée';
    if (event?.action === 'arbitrage') {
      this.openAssistant(`AYA, prépare un arbitrage Vice Premier Ministre pour ${title} avec options, sources et échéance.`);
      return;
    }
    if (event?.action === 'maritime') {
      this.openAssistant(`AYA, explique le risque portuaire autour de ${title} et les actions recommandées.`);
      return;
    }
    this.openAssistant(`AYA, donne-moi le brief opérationnel pour ${title} avec sources et action recommandée.`);
  }

  draftForProject(project: Project): void {
    this.createDraft(project.id, 'project');
  }

  draftForZone(zone: MapZone): void {
    this.createDraft(zone.id, 'zone');
  }

  createActionForProject(project: Project): void {
    const scenario = project.scenario_options?.find((item) => item.recommended) || project.scenario_options?.[0];
    this.createAction({
      title: `Arbitrer ${project.name}`,
      description: scenario?.summary || project.risk,
      target_kind: 'project',
      target_id: project.id,
      target_label: project.name,
      priority: project.weather === 'red' ? 'high' : 'medium',
      owner_label: project.owner || 'Cabinet',
      source_kind: 'mission_room_project',
      source_id: project.id,
      recommended_window: {
        label: 'Fenetre cabinet',
        start: '16:10',
        end: '16:45',
        why: 'Arbitrage possible avant la prochaine sequence institutionnelle.',
      },
    });
  }

  createActionForZone(zone: MapZone): void {
    const window = zone.recommended_windows?.[0];
    this.createAction({
      title: `Action preventive ${zone.name}`,
      description: zone.recommendations?.[0] || 'Qualifier le signal territorial et preparer une action non militaire.',
      target_kind: 'zone',
      target_id: zone.id,
      target_label: zone.name,
      priority: zone.level >= 80 ? 'critical' : zone.level >= 50 ? 'high' : 'medium',
      owner_label: 'Cabinet territorial',
      source_kind: 'mission_room_map',
      source_id: zone.id,
      recommended_window: window,
    });
  }

  private createAction(payload: Partial<ActionItem> & { title: string }): void {
    const continuation = this.captureWorkspaceContinuation();
    const request = this.api
      .post<ActionItem>('/action-plans/', {
        ...payload,
        due_at: payload.due_at || null,
        confidence: payload.confidence || 'medium',
      }, this.workspaceApiOptions(continuation))
      .subscribe((item) => {
        if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
        this.loadAll(true, continuation);
        this.openAssistant(`Action cabinet ajoutee : ${item.title}. Resume les prochaines etapes et les sources utiles.`);
      });
    this.workspaceActionRequests.add(request);
  }

  completeAction(item: ActionItem): void {
    const continuation = this.captureWorkspaceContinuation();
    const request = this.api
      .post<ActionItem>(
        `/action-plans/${item.id}/complete`,
        {},
        this.workspaceApiOptions(continuation),
      )
      .subscribe(() => {
        if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
        this.loadAll(true, continuation);
      });
    this.workspaceActionRequests.add(request);
  }

  cancelAction(item: ActionItem): void {
    const continuation = this.captureWorkspaceContinuation();
    const request = this.api
      .post<ActionItem>(
        `/action-plans/${item.id}/cancel`,
        { reason: 'Arbitrage depuis Mission Room' },
        this.workspaceApiOptions(continuation),
      )
      .subscribe(() => {
        if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
        this.loadAll(true, continuation);
      });
    this.workspaceActionRequests.add(request);
  }

  selectAgendaEvent(event: AgendaItem): void {
    this.selectedAgendaEvent.set(event);
    if (event?.id) this.refreshAgendaPendingPatch(event.id);
    else this.agendaPendingPatch.set(null);
  }

  private refreshAgendaPendingPatch(eventId: string): void {
    const continuation = this.captureWorkspaceContinuation();
    const request = this.api
      .get<{ pending_agenda_patch?: AgendaPendingPatch | null }>(
        `/meetings/${eventId}/agenda-patch`,
        undefined,
        this.workspaceApiOptions(continuation),
      )
      .pipe(catchError(() => of<{ pending_agenda_patch?: AgendaPendingPatch | null } | null>(null)))
      .subscribe((response) => {
        if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
        this.agendaPendingPatch.set(response?.pending_agenda_patch || null);
      });
    this.workspaceActionRequests.add(request);
  }

  confirmAgendaPendingPatch(): void {
    const event = this.selectedAgendaEvent();
    const pending = this.agendaPendingPatch();
    if (!event?.id || !pending || this.agendaPatchSubmitting()) return;
    const continuation = this.captureWorkspaceContinuation();
    this.agendaPatchSubmitting.set(true);
    const request = this.api
      .post<{ agenda_items?: AgendaSubItem[] }>(
        `/meetings/${event.id}/agenda-patch/confirm`,
        {},
        this.workspaceApiOptions(continuation),
      )
      .pipe(catchError(() => of<{ agenda_items?: AgendaSubItem[] } | null>(null)))
      .subscribe((response) => {
        if (!this.workspaceContinuationContextIsCurrent(continuation)) return;
        this.agendaPatchSubmitting.set(false);
        this.agendaPendingPatch.set(null);
        if (response?.agenda_items) {
          const updated: AgendaItem = {
            ...event,
            metadata: { ...(event.metadata || {}), agenda_items: response.agenda_items },
          };
          this.selectedAgendaEvent.set(updated);
        }
        this.loadAll(true, continuation);
      });
    this.workspaceActionRequests.add(request);
  }

  rejectAgendaPendingPatch(): void {
    this.agendaPendingPatch.set(null);
  }

  agendaPendingPatchTitle(): string {
    const items = this.agendaPendingPatch()?.agenda_items || [];
    const first = items[0];
    if (!first) return 'Modification ODJ proposee';
    const more = items.length > 1 ? ` (+${items.length - 1})` : '';
    return `${first.title || 'Point sans titre'}${more}`;
  }

  private defaultAgendaStartValue(): string {
    return `${this.abidjanDateKey()}T09:45`;
  }

  private abidjanDateKey(offsetDays = 0): string {
    const today = this.abidjanDateAtNoon();
    today.setDate(today.getDate() + offsetDays);
    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  private abidjanDateAtNoon(): Date {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: this.abidjanTimeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(this.abidjanNow());
    const get = (type: string) => parts.find((part) => part.type === type)?.value || '01';
    return new Date(Number(get('year')), Number(get('month')) - 1, Number(get('day')), 12, 0, 0);
  }

  private formatRelativeAbidjanDate(offsetDays: number): string {
    const date = this.abidjanDateAtNoon();
    date.setDate(date.getDate() + offsetDays);
    return this.abidjanShortDateFormatter.format(date).replace(/\.$/, '');
  }

  private capitalizeDateLabel(label: string): string {
    return label ? label.charAt(0).toUpperCase() + label.slice(1) : label;
  }

  agendaDayLabel(): string {
    const dateValue = this.selectedAgendaEvent()?.date || this.timeline()?.agenda?.[0]?.date;
    if (!dateValue) return 'Journee consolidee';
    const parsed = new Date(`${dateValue}T12:00:00`);
    return parsed.toLocaleDateString('fr-FR', { weekday: 'long', day: '2-digit', month: 'long' });
  }

  agendaWeekDays(): { label: string; count: number; active: boolean }[] {
    const events = this.timeline()?.agenda || [];
    const grouped = new Map<string, number>();
    events.forEach((event) => {
      if (!event.date) return;
      grouped.set(event.date, (grouped.get(event.date) || 0) + (event.status === 'cancelled' ? 0 : 1));
    });
    return Array.from(grouped.entries()).map(([date, count]) => {
      const parsed = new Date(`${date}T12:00:00`);
      return {
        label: parsed.toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit' }),
        count,
        active: date === (this.selectedAgendaEvent()?.date || events[0]?.date),
      };
    });
  }

  calendarConnectorLabel(): string {
    return this.timeline()?.calendar?.connector?.label || 'Agenda institutionnel';
  }

  createAgendaEvent(): void {
    const title = this.newAgendaTitle.trim();
    if (!title) return;
    const start = this.newAgendaStart || '2026-04-15T09:45';
    const startDate = new Date(start);
    const endDate = new Date(startDate.getTime() + 45 * 60 * 1000);
    this.api
      .post<AgendaItem>('/calendar/events', {
        title,
        start_at: start.length === 16 ? `${start}:00` : start,
        end_at: this.localIso(endDate),
        location: this.newAgendaLocation || 'Cabinet ministeriel',
        priority: 'medium',
        category: 'cabinet',
      })
      .subscribe((event) => {
        this.newAgendaTitle = '';
        this.selectedAgendaEvent.set(event);
        this.loadAll();
      });
  }

  moveSelectedAgendaEvent(minutes: number): void {
    const event = this.selectedAgendaEvent();
    if (!event?.id || !event.date) return;
    const start = new Date(`${event.date}T${event.time}:00`);
    const end = new Date(`${event.date}T${event.end_time || event.time}:00`);
    const duration = Math.max(30 * 60 * 1000, end.getTime() - start.getTime());
    const nextStart = new Date(start.getTime() + minutes * 60 * 1000);
    const nextEnd = new Date(nextStart.getTime() + duration);
    this.api
      .patch<AgendaItem>(`/calendar/events/${event.id}`, {
        start_at: this.localIso(nextStart),
        end_at: this.localIso(nextEnd),
      })
      .subscribe((updated) => {
        this.selectedAgendaEvent.set(updated);
        this.loadAll();
      });
  }

  private localIso(value: Date): string {
    const pad = (input: number) => String(input).padStart(2, '0');
    return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}:00`;
  }

  cancelSelectedAgendaEvent(): void {
    const event = this.selectedAgendaEvent();
    if (!event?.id) return;
    this.api
      .post<AgendaItem>(`/calendar/events/${event.id}/cancel`, { reason: 'Arbitrage cabinet depuis Mission Room' })
      .subscribe((cancelled) => {
        this.selectedAgendaEvent.set(cancelled);
        this.loadAll();
      });
  }

  agendaSubItems(event: AgendaItem): AgendaSubItem[] {
    const items = event.metadata?.agenda_items;
    if (Array.isArray(items)) return items;
    return [];
  }

  agendaSubItemSourceLabel(item: AgendaSubItem): string {
    const raw = (item.source_label || item.source || '').trim().toLowerCase();
    if (!raw) return 'Ajouté par Vice Premier Ministre';
    if (raw.includes('aya') || raw.includes('octave') || raw.includes('assistant')) return `Ajouté par ${this.assistantName()}`;
    if (raw.includes('brief') || raw.includes('prefet') || raw.includes('préfet')) return 'Importé du brief préfet';
    if (raw.includes('vp') || raw.includes('cabinet')) return 'Ajouté par Vice Premier Ministre';
    return item.source_label || item.source || 'Ajouté par Vice Premier Ministre';
  }

  agendaSubItemSourceClass(item: AgendaSubItem): string {
    const raw = (item.source_label || item.source || '').toLowerCase();
    if (raw.includes('aya')) return 'source-aya';
    if (raw.includes('brief') || raw.includes('prefet') || raw.includes('préfet')) return 'source-brief';
    return 'source-vp';
  }

  addAgendaSubItem(): void {
    const event = this.selectedAgendaEvent();
    if (!event) return;
    const existing = this.agendaSubItems(event);
    const next: AgendaSubItem = {
      id: `odj-${Date.now()}`,
      title: 'Nouveau point',
      order: existing.length + 1,
      source: 'vp',
      source_label: 'Ajouté par Vice Premier Ministre',
    };
    this.patchAgendaSubItems(event, [...existing, next]);
  }

  updateAgendaSubItem(index: number, title: string): void {
    const event = this.selectedAgendaEvent();
    if (!event) return;
    const existing = this.agendaSubItems(event).slice();
    if (!existing[index]) return;
    existing[index] = { ...existing[index], title };
    this.patchAgendaSubItems(event, existing);
  }

  removeAgendaSubItem(index: number): void {
    const event = this.selectedAgendaEvent();
    if (!event) return;
    const existing = this.agendaSubItems(event).slice();
    if (!existing[index]) return;
    existing.splice(index, 1);
    this.patchAgendaSubItems(event, existing);
  }

  private patchAgendaSubItems(event: AgendaItem, items: AgendaSubItem[]): void {
    const nextEvent: AgendaItem = {
      ...event,
      metadata: { ...(event.metadata || {}), agenda_items: items },
    };
    this.selectedAgendaEvent.set(nextEvent);
    if (!event.id) return;
    const nextMetadata = nextEvent.metadata || {};
    this.api
      .patch<AgendaItem>(`/calendar/events/${event.id}`, { metadata: nextMetadata })
      .pipe(catchError(() => of(null)))
      .subscribe((updated) => {
        if (updated) this.selectedAgendaEvent.set(updated);
      });
  }

  startMeeting(event: AgendaItem): void {
    if (!event.id) return;
    const eventId = event.id;
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceContinuationGeneration;
    // Mirror ``aya.start_meeting`` server-side so a follow-up voice
    // ``aya.log_decision`` finds an active meeting. The navigation runs
    // regardless so the meeting view always opens.
    const request = this.api
      .post(`/meetings/${eventId}/start`, {}, { workspaceSlug: scope.workspaceSlug })
      .pipe(catchError(() => of(null)))
      .subscribe(() => {
        if (!this.workspaceContinuationIsCurrent(scope, generation)) return;
        void this.router.navigate(['/hypervisor/mission-room/agenda/meeting', eventId]);
      });
    this.workspaceActionRequests.add(request);
  }

  private workspaceContinuationIsCurrent(
    scope: WorkspaceRequestScope,
    generation: number,
  ): boolean {
    return (
      !this.destroyed
      && generation === this.workspaceContinuationGeneration
      && this.workspace.isRequestScopeCurrent(scope)
    );
  }

  private captureWorkspaceContinuation(): WorkspaceContinuationContext {
    return {
      scope: this.workspace.captureRequestScope(),
      generation: this.workspaceContinuationGeneration,
    };
  }

  private workspaceContinuationContextIsCurrent(
    continuation?: WorkspaceContinuationContext,
  ): boolean {
    return !continuation || this.workspaceContinuationIsCurrent(
      continuation.scope,
      continuation.generation,
    );
  }

  private workspaceApiOptions(
    continuation?: WorkspaceContinuationContext,
  ): { workspaceSlug?: string | null } | undefined {
    return continuation
      ? { workspaceSlug: continuation.scope.workspaceSlug }
      : undefined;
  }

  private trackWorkspaceActionRequest(
    request: Subscription,
    continuation?: WorkspaceContinuationContext,
  ): void {
    if (continuation) {
      this.workspaceActionRequests.add(request);
    }
  }

  private resetWorkspaceActionContinuations(): void {
    this.workspaceContinuationGeneration += 1;
    this.workspaceActionRequests.unsubscribe();
    this.workspaceActionRequests = new Subscription();
    this.loading.set(false);
    this.draft.set(null);
    this.selectedAgendaEvent.set(null);
    this.agendaPendingPatch.set(null);
    this.agendaPatchSubmitting.set(false);
  }

  createDraft(targetId: string, targetType: string): void {
    const continuation = this.captureWorkspaceContinuation();
    const request = this.api
      .post<DraftInstruction>('/mission-room/actions/draft', {
        target_id: targetId,
        target_type: targetType,
        instruction_type: 'dircab_instruction',
      }, this.workspaceApiOptions(continuation))
      .subscribe((draft) => {
        if (this.workspaceContinuationContextIsCurrent(continuation)) {
          this.draft.set(draft);
        }
      });
    this.workspaceActionRequests.add(request);
  }

  runSearch(): void {
    this.api
      .get<MissionSearch>('/mission-room/search', { q: this.searchQueryValue.trim() })
      .subscribe((payload) => this.search.set(payload));
  }
}
