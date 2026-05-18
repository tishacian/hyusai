import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import { MissionControlMonitorComponent } from './mission-control-monitor.component';
import { WorkspaceMapComponent } from './workspace-map.component';

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
  | 'veille'
  | 'decisions'
  | 'strategie'
  | 'recherche'
  | 'assistant';

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

interface MissionNavigation {
  workspace: WorkspaceMeta;
  app: {
    label: string;
    assistant_label: string;
    shell: string;
    default_route: string;
    default_view: MissionView;
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
  geography_tier?: string;
  viewpoint?: string;
  origin?: string;
  impact_ci?: string;
  why_it_matters?: string;
  recommended_action?: string;
  confidence?: number;
  source_count?: number;
  url?: string | null;
  run_id?: string | null;
  entities?: string[];
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
  reputation: { score: number; delta: number; trend: number[] };
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
  visual_summary?: VisualSourceHealth;
  strategic_posture?: StrategicPosture;
  what_changed?: string[];
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
  visual_observations: VisualObservation[];
  forecasts: { id: string; title: string; summary: string; level: string; horizon: string; confidence: number }[];
  news_signals: NewsSignal[];
  source_freshness: Record<string, string>;
  sources: SourceRef[];
}

interface MissionNews {
  summary: string;
  signals: NewsSignal[];
  executive_alerts?: NewsSignal[];
  briefing_note?: NewsBriefingNote;
  source_health?: NewsSourceHealth;
  media_sources?: { label: string; coverage: number; count: number }[];
  geographic_priority?: NewsGeographicPriority[];
  viewpoints?: NewsViewpoint[];
  social_listening?: SocialListeningPayload;
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
  body: string;
  sources: string[];
  control: Record<string, unknown>;
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
    <aside class="mission-rail" aria-label="Navigation SENTINEL-CI">
      <div class="rail-brand">
        <img
          class="brand-lockup"
          src="/assets/brand/sentinel-ci-logo.svg?v=20260514-2"
          alt="SENTINEL-CI - Republique de Cote d'Ivoire"
          width="184"
          height="49"
        />
      </div>

      <button
        type="button"
        class="assistant-badge"
        (click)="assistantRequest.emit()"
        aria-label="Ouvrir AYA"
      >
        <span class="assistant-avatar">{{ assistantName }}</span>
        <div>
          <strong>{{ assistantName }}</strong>
          <small>Assistante vocale</small>
        </div>
      </button>

      <a class="rail-search" routerLink="/hypervisor/mission-room/recherche" aria-label="Rechercher un dossier Sentinel-CI">
        <ck-glyph name="zoom-in" [size]="12" />
        <span>Recherche dossier</span>
      </a>

      <nav class="mission-nav">
        <span class="rail-section-label">Parcours VP</span>
        @for (item of visibleItems(); track item.key) {
          <a
            [routerLink]="item.route"
            routerLinkActive="active"
            class="mission-nav-item"
            [attr.aria-current]="activeView === item.key ? 'page' : null"
          >
            <ck-glyph [name]="item.glyph" [size]="14" />
            <span>{{ railLabel(item) }}</span>
          </a>
        }
      </nav>

      <div class="rail-spacer"></div>

      <div class="rail-summary">
        <span>Ce matin</span>
        <strong>3 arbitrages</strong>
        <small>16 alertes presse qualifiees</small>
      </div>
      <div class="rail-clock">
        <strong>{{ abidjanClockTime() }}</strong>
        <span>{{ abidjanClockDate() }} · Abidjan UTC+0</span>
      </div>
      <nav class="rail-tools" aria-label="Outils operateur">
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
        display: flex;
        align-items: center;
        min-height: 46px;
        min-width: 0;
      }
      .brand-lockup {
        display: block;
        width: min(184px, 100%);
        height: auto;
        filter: drop-shadow(0 16px 22px rgba(0, 0, 0, 0.42));
      }
      .assistant-badge {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 9px;
        border: 1px solid rgba(242, 140, 56, 0.20);
        border-radius: var(--mission-radius, 8px);
        background:
          linear-gradient(135deg, rgba(242, 140, 56, 0.095), rgba(101, 214, 110, 0.045)),
          var(--mission-panel-hi, var(--ck-bg-panel-hi));
        appearance: none;
        font: inherit;
        color: inherit;
        text-align: left;
        cursor: pointer;
      }
      .assistant-badge:hover {
        border-color: rgba(242, 140, 56, 0.38);
        box-shadow: inset 3px 0 0 var(--mission-orange, #f28c38);
      }
      .assistant-avatar {
        width: 36px;
        height: 36px;
        border-radius: 12px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--mission-orange, #f28c38);
        font-family: var(--ck-font-mono);
        font-size: 12px;
        font-weight: 850;
        letter-spacing: 0.08em;
        background: rgba(8, 13, 17, 0.72);
        border: 1px solid rgba(242, 140, 56, 0.32);
        box-shadow: inset 0 0 18px rgba(242, 140, 56, 0.08);
      }
      .assistant-badge strong {
        display: block;
        color: var(--mission-text, var(--ck-fg-1));
        font-family: var(--ck-font-mono);
        font-size: 13px;
        letter-spacing: 0.12em;
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
        letter-spacing: 0.16em;
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
        .brand-lockup { width: min(166px, 100%); }
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
  @Output() assistantRequest = new EventEmitter<void>();

  private readonly clockTimeZone = 'Africa/Abidjan';
  private readonly clockNow = signal(new Date());
  private clockTimer: number | null = null;
  private readonly primaryRailKeys: MissionView[] = [
    'cockpit',
    'monitor',
    'briefing',
    'agenda',
    'presse',
    'decisions',
    'strategie',
  ];
  private readonly railLabelOverrides: Partial<Record<MissionView, string>> = {
    cockpit: 'Priorites',
    monitor: 'Situation live',
    decisions: 'Arbitrages',
    strategie: 'Carte',
  };
  private readonly timeFormatter = new Intl.DateTimeFormat('fr-FR', {
    timeZone: this.clockTimeZone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  private readonly dateFormatter = new Intl.DateTimeFormat('fr-FR', {
    timeZone: this.clockTimeZone,
    weekday: 'long',
    day: '2-digit',
    month: 'long',
  });

  readonly abidjanClockTime = computed(() => this.timeFormatter.format(this.clockNow()));
  readonly abidjanClockDate = computed(() => this.capitalizeClockLabel(this.dateFormatter.format(this.clockNow())));

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
    return this.railLabelOverrides[item.key] || item.label;
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
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="mission-shell">
      <app-mission-rail
        [items]="navigation()?.items || fallbackNav"
        [activeView]="currentView()"
        [adminRoute]="adminRoute()"
        [assistantName]="assistantName()"
        (assistantRequest)="openAssistant('AYA, prepare le cockpit 60 secondes pour le Vice-President.')"
      />

      <main class="mission-main ck-scroll">
        @if (loading()) {
          <div class="loading-panel">
            <span class="dots"></span>
            <strong>Chargement de la Mission Room SENTINEL-CI</strong>
          </div>
        } @else {
          <header class="mission-hero">
            <div class="hero-copy">
              <div class="hero-meta">
                <span class="eyebrow">Mission Room Gouvernementale</span>
                <span class="hero-status">{{ cockpit()?.briefing_status || 'Briefing pret' }}</span>
              </div>
              <h1>{{ cockpit()?.title || 'Bonjour, M. le Vice-Président.' }}</h1>
              <p>
                <span>{{ cockpit()?.date_label || 'Mercredi 15 Avril 2026' }}</span>
                <span class="hero-dot"></span>
                <span>Vision executive consolidee</span>
              </p>
            </div>
            <div class="hero-actions">
              <a routerLink="/hypervisor/mission-room/briefing" class="action-button primary">
                <ck-glyph name="ledger" [size]="15" />
                <span>Briefing</span>
              </a>
              <button type="button" class="action-button" (click)="openAssistant()">
                <ck-glyph name="crosshair" [size]="15" />
                <span>{{ assistantName() }}</span>
              </button>
            </div>
          </header>

          @switch (currentView()) {
            @case ('cockpit') { <ng-container *ngTemplateOutlet="cockpitView"></ng-container> }
            @case ('monitor') { <ng-container *ngTemplateOutlet="monitorView"></ng-container> }
            @case ('briefing') { <ng-container *ngTemplateOutlet="briefingView"></ng-container> }
            @case ('pilotage') { <ng-container *ngTemplateOutlet="projectsView"></ng-container> }
            @case ('agenda') { <ng-container *ngTemplateOutlet="timelineView"></ng-container> }
            @case ('messages') { <ng-container *ngTemplateOutlet="messagesView"></ng-container> }
            @case ('bibliotheque') { <ng-container *ngTemplateOutlet="libraryView"></ng-container> }
            @case ('projets') { <ng-container *ngTemplateOutlet="projectsView"></ng-container> }
            @case ('presse') { <ng-container *ngTemplateOutlet="newsView"></ng-container> }
            @case ('reputation') { <ng-container *ngTemplateOutlet="reputationView"></ng-container> }
            @case ('veille') { <ng-container *ngTemplateOutlet="watchView"></ng-container> }
            @case ('decisions') { <ng-container *ngTemplateOutlet="decisionsView"></ng-container> }
            @case ('strategie') { <ng-container *ngTemplateOutlet="mapView"></ng-container> }
            @case ('recherche') { <ng-container *ngTemplateOutlet="searchView"></ng-container> }
            @case ('assistant') { <ng-container *ngTemplateOutlet="assistantView"></ng-container> }
            @default { <ng-container *ngTemplateOutlet="cockpitView"></ng-container> }
          }
        }
      </main>
    </section>

    <ng-template #cockpitView>
      <section class="vp-command-grid" aria-label="Cockpit 60 secondes">
        <article class="content-panel vp-sentence span-2">
          <span class="eyebrow">{{ decisionSentence60().label || 'Sentence du jour' }}</span>
          <h2>{{ decisionSentence60().text }}</h2>
          <p>{{ decisionSentence60().deadline || 'avant Conseil 15h00' }} · {{ decisionSentence60().generated_by || assistantName() }}</p>
          <div class="hero-actions">
            <button type="button" class="action-button primary" (click)="openAssistant('AYA, donne-moi le cockpit 60 secondes pour le Vice-President.')">
              <ck-glyph name="bolt" [size]="14" />
              <span>Interroger {{ assistantName() }}</span>
            </button>
            <a routerLink="/hypervisor/mission-room/briefing" class="action-button compact">
              <ck-glyph name="ledger" [size]="14" />
              <span>Briefing pret</span>
            </a>
          </div>
        </article>

        <article class="content-panel vp-snapshot">
          <span class="eyebrow">Lecture debout</span>
          @if (sixtySecondCockpit(); as sixty) {
            <div class="vp-snapshot-grid">
              <article [class]="attentionTone({ tone: sixty.menace?.tone || 'critical', title: 'menace' })">
                <span>Menace</span>
                <strong>{{ sixty.menace?.label || 'Zone Nord' }}</strong>
                <small>{{ sixty.menace?.score || cockpit()?.strategic_posture?.score || 0 }}% · {{ sixty.menace?.deadline || '15:00' }}</small>
              </article>
              <article class="stable">
                <span>Reputation</span>
                <strong>{{ sixty.reputation?.score || cockpit()?.reputation?.score || 0 }}/100</strong>
                <small>{{ sixty.reputation?.sentence || 'Un sujet necessite attention, le reste est gerable.' }}</small>
              </article>
              @if (agendaFocus60(); as event) {
                <article class="watch">
                  <span>Agenda</span>
                  <strong>{{ event.time }} · {{ event.title }}</strong>
                  <small>{{ event.location }}</small>
                </article>
              }
            </div>
          }
        </article>
      </section>

      <section class="vp-urgencies" aria-label="Attention requise">
        <div class="panel-heading-row">
          <div>
            <span class="eyebrow">Attention requise</span>
            <h2>3 sujets ce matin</h2>
          </div>
          <a routerLink="/hypervisor/mission-room/decisions" class="action-button compact">
            <ck-glyph name="check" [size]="14" />
            <span>Arbitrages</span>
          </a>
        </div>
        <div class="priorities-grid">
          @for (item of attentionItems60(); track item.id || item.title; let idx = $index) {
            <button
              type="button"
              class="priority-card"
              [class.critical]="attentionTone(item) === 'critical'"
              [class.watch]="attentionTone(item) === 'watch'"
              (click)="openAttentionItem(item)"
            >
              <span>{{ item.rank || idx + 1 }} · {{ item.status || 'a traiter' }}</span>
              <strong>{{ item.title }}</strong>
              <p>{{ item.sentence || item.summary }}</p>
              <small>{{ item.deadline || 'ce matin' }}</small>
              <i>{{ attentionActionLabel(item) }}</i>
            </button>
          }
        </div>
      </section>

      <section class="vp-operating-strip" aria-label="Drill-down demo">
        <a routerLink="/hypervisor/mission-room/monitor" class="content-panel vp-capability-card">
          <span>Preuve terrain</span>
          <strong>Carte + webcam + signaux</strong>
          <small>Verifier la Zone Nord et localiser les vues actives.</small>
        </a>
        <a routerLink="/hypervisor/mission-room/presse" class="content-panel vp-capability-card">
          <span>Presse et rumeurs</span>
          <strong>CI / CEDEAO / international</strong>
          <small>Identifier l'origine, la propagation et la reponse recommandee.</small>
        </a>
        <a routerLink="/hypervisor/mission-room/decisions" class="content-panel vp-capability-card">
          <span>Arbitrage humain</span>
          <strong>Instruction preparee</strong>
          <small>Valider, amender ou ajourner sous controle cabinet.</small>
        </a>
        <a routerLink="/hypervisor/mission-room/strategie" class="content-panel vp-capability-card">
          <span>Carte souveraine</span>
          <strong>Lecture territoriale</strong>
          <small>Etendre la lecture Cote d'Ivoire, CEDEAO et Golfe de Guinee.</small>
        </a>
      </section>
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
            <dl>
              <div><dt>Horaire</dt><dd>{{ event.time }} - {{ event.end_time || '—' }}</dd></div>
              <div><dt>Lieu</dt><dd>{{ event.location || 'A confirmer' }}</dd></div>
              <div><dt>Priorite</dt><dd>{{ event.priority || 'medium' }}</dd></div>
              <div><dt>Participants</dt><dd>{{ (event.participants || ['Cabinet']).join(', ') }}</dd></div>
            </dl>
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
          <h2>Collections SENTINEL-CI</h2>
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
          <span class="eyebrow">Brief presse & signaux faibles</span>
          <div class="panel-heading-row">
            <h2>{{ news()?.briefing_note?.headline || 'Synthese executive' }}</h2>
            <a
              class="action-button compact"
              [routerLink]="systemRouteFor('presse') || '/intelligence'"
              [queryParams]="{ facet: 'intelligence' }"
            >
              <ck-glyph name="pulse" [size]="14" />
              <span>Inspecter l'atelier de veille</span>
            </a>
          </div>
          <p>{{ news()?.summary }}</p>
          <div class="brief-meta">
            <span>{{ news()?.source_health?.coverage_label || 'Sources qualifiees' }}</span>
            <span>{{ intelligenceStatusLabel(news()?.source_health?.last_run_status) }}</span>
            <span>{{ news()?.source_health?.high_risk || 0 }} signaux prioritaires</span>
          </div>
        </article>

        <article class="content-panel now-panel">
          <span class="eyebrow">A retenir maintenant</span>
          <ul>
            @for (bullet of news()?.briefing_note?.bullets || []; track bullet) {
              <li>{{ bullet }}</li>
            }
          </ul>
        </article>

        <article class="content-panel source-health-panel">
          <span class="eyebrow">Couverture de veille</span>
          <div class="health-grid">
            <article>
              <strong>{{ news()?.source_health?.active_feeds || 0 }}</strong>
              <span>sources actives</span>
            </article>
            <article>
              <strong>{{ news()?.source_health?.analyzed || 0 }}</strong>
              <span>articles analyses</span>
            </article>
            <article>
              <strong>{{ news()?.source_health?.high_risk || 0 }}</strong>
              <span>prioritaires</span>
            </article>
          </div>
          <p>La Mission Room restitue les signaux utiles au pilotage. L'atelier conserve le diagnostic detaille et les sources brutes.</p>
        </article>

        <article class="content-panel">
          <span class="eyebrow">Priorite geographique</span>
          <h2>CI → CEDEAO → Afrique → Monde</h2>
          <div class="library-list">
            @for (item of news()?.geographic_priority || []; track item.key) {
              <article>
                <strong>{{ item.priority }}. {{ item.label }}</strong>
                <small>{{ item.feed_count }} sources · {{ item.signal_count }} signaux</small>
                <p>{{ item.description }}</p>
              </article>
            }
          </div>
        </article>

        <article class="content-panel">
          <span class="eyebrow">Double lecture politique</span>
          <h2>Interieur ivoirien / international</h2>
          <div class="library-list">
            @for (viewpoint of news()?.viewpoints || []; track viewpoint.key) {
              <article>
                <strong>{{ viewpoint.label }}</strong>
                <small>{{ viewpoint.feed_count }} sources · {{ viewpoint.signal_count }} signaux</small>
                <p>{{ viewpoint.brief }}</p>
              </article>
            }
          </div>
        </article>

        <article class="content-panel span-2">
          <div class="panel-heading-row">
            <div>
              <span class="eyebrow">Rumeurs + origines</span>
              <h2>Canaux sociaux publics et signalements terrain</h2>
            </div>
            <button type="button" class="action-button compact" (click)="openAssistant('AYA, donne origine rumeur prioritaire et action recommandee.')">
              <ck-glyph name="bolt" [size]="14" />
              <span>Demander a {{ assistantName() }}</span>
            </button>
          </div>
          <p>{{ news()?.social_listening?.policy }}</p>
          <div class="brief-meta">
            @for (channel of news()?.social_listening?.channels || []; track channel.key) {
              <span>{{ channel.label }} · {{ channel.coverage }}%</span>
            }
          </div>
          <div class="library-list">
            @for (rumor of news()?.social_listening?.rumor_origins || []; track rumor.label) {
              <article>
                <strong>{{ rumor.label }}</strong>
                <small>{{ rumor.zone }} · confiance {{ confidencePct(rumor.confidence) }}</small>
                <p>{{ rumor.origin }}</p>
                <small>{{ rumor.recommended_action }}</small>
              </article>
            }
          </div>
        </article>

        <div class="executive-alert-grid span-2">
          @for (signal of newsAlerts(); track signal.id) {
            <article class="content-panel executive-alert-card">
              <div class="panel-heading-row">
                <span class="status-pill" [class]="signal.risk_level">{{ ministerialRisk(signal.risk_level) }}</span>
                <small>{{ signal.viewpoint || signal.zone || signal.source }} · confiance {{ confidencePct(signal.confidence) }}</small>
              </div>
              <h3>{{ signal.title }}</h3>
              <p>{{ signal.impact_ci || signal.summary }}</p>
              <dl>
                <div>
                  <dt>Origine</dt>
                  <dd>{{ signal.origin || signal.source_name || signal.source }}</dd>
                </div>
                <div>
                  <dt>Pourquoi c'est sensible</dt>
                  <dd>{{ signal.why_it_matters || signal.summary }}</dd>
                </div>
                <div>
                  <dt>Action proposee</dt>
                  <dd>{{ signal.recommended_action || 'Qualifier les sources avant diffusion cabinet.' }}</dd>
                </div>
              </dl>
              <div class="source-row">
                @for (source of signal.sources; track source) {
                  <app-mission-source-pill [label]="sourceLabel(source)" (click)="showSource(source)" />
                }
              </div>
            </article>
          }
        </div>

        <article class="content-panel">
          <span class="eyebrow">Elements de langage</span>
          <h2>Position recommandee</h2>
          <ul class="language-list">
            @for (line of news()?.briefing_note?.talking_points || []; track line) {
              <li>{{ line }}</li>
            }
          </ul>
        </article>

        <article class="content-panel">
          <span class="eyebrow">Decisions attendues</span>
          <h2>Arbitrages cabinet</h2>
          <div class="decision-list">
            @for (item of news()?.briefing_note?.decisions_expected || []; track item) {
              <button type="button" (click)="createDraft('decision-press-lines', 'decision')">
                <strong>{{ item }}</strong>
                <small>Validation humaine requise avant diffusion.</small>
              </button>
            }
          </div>
          </article>
      </section>
    </ng-template>

    <ng-template #reputationView>
      <section class="two-column">
        <app-mission-chart-panel eyebrow="E-Reputation" title="Sentiment medias" [value]="reputationValue()" [tall]="true">
          <svg class="line-chart big" viewBox="0 0 520 230" preserveAspectRatio="none">
            <path class="line good" [attr.d]="trendPath(cockpit()?.reputation?.trend || [], 210, 32)"></path>
            <path class="line muted" d="M20 160 L500 160"></path>
            <path class="line danger soft" d="M20 185 L130 195 L240 172 L340 202 L500 180"></path>
          </svg>
        </app-mission-chart-panel>
        <article class="content-panel">
          <span class="eyebrow">Lecture cabinet</span>
          <h2>Reputation institutionnelle</h2>
          <p>La dynamique positive reste fragile. Les signaux critiques viennent surtout des retards territoriaux et d'une perception de coordination insuffisante.</p>
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
      <section class="two-column">
        <article class="content-panel">
          <span class="eyebrow">Decisions</span>
          <h2>Validation humaine requise</h2>
          <p>Les recommandations preparent l'arbitrage ; chaque instruction reste soumise a validation.</p>
          <div class="decision-kpis">
            <article>
              <strong>{{ decisions()?.action_summary?.active || 0 }}</strong>
              <span>actions actives</span>
            </article>
            <article>
              <strong>{{ decisions()?.action_summary?.critical || 0 }}</strong>
              <span>prioritaires</span>
            </article>
            <article>
              <strong>{{ decisions()?.action_summary?.completed || 0 }}</strong>
              <span>terminees</span>
            </article>
          </div>
          <div class="decision-list">
            @for (decision of decisions()?.decisions || []; track decision.id) {
              <button type="button" (click)="createDraft(decision.target_id, decision.target_type)">
                <span class="status-pill" [class]="decision.risk">{{ decision.status }}</span>
                <strong>{{ decision.title }}</strong>
                <small>{{ decision.recommendation }}</small>
              </button>
            }
          </div>
        </article>
        <article class="content-panel selected-detail">
          <span class="eyebrow">Actions cabinet</span>
          <h2>Suivi operationnel</h2>
          <div class="action-item-list">
            @for (item of decisions()?.action_items || []; track item.id) {
              <article [class]="item.priority" [class.done]="item.status === 'completed'" [class.cancelled]="item.status === 'cancelled'">
                <div>
                  <span class="status-pill" [class]="item.priority">{{ item.priority }}</span>
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.owner_label }} · {{ item.due_label || 'a planifier' }} · {{ item.status }}</small>
                  @if (item.description) { <p>{{ item.description }}</p> }
                </div>
                <div class="action-row">
                  <button type="button" (click)="completeAction(item)" [disabled]="item.status === 'completed' || item.status === 'cancelled'">Terminer</button>
                  <button type="button" class="danger" (click)="cancelAction(item)" [disabled]="item.status === 'completed' || item.status === 'cancelled'">Annuler</button>
                </div>
              </article>
            }
          </div>
          <div class="project-risk-list">
            <span class="eyebrow">Projets integres</span>
            @for (project of projectDecisionRisks(); track project.id) {
              <button type="button" (click)="draftForProject(project)">
                <strong>{{ project.name }}</strong>
                <small>{{ project.risk }}</small>
              </button>
            }
          </div>
        </article>
        <article class="content-panel selected-detail span-2">
          @if (draft(); as draftValue) {
            <span class="eyebrow">Brouillon</span>
            <h2>{{ draftValue.title }}</h2>
            <p>{{ draftValue.body }}</p>
            <dl>
              <div><dt>Destinataire</dt><dd>{{ draftValue.recipient }}</dd></div>
              <div><dt>Statut</dt><dd>{{ draftValue.status }}</dd></div>
              <div><dt>Validation</dt><dd>{{ draftValue.requires_validation ? 'requise' : 'non requise' }}</dd></div>
            </dl>
          } @else {
            <span class="eyebrow">Audit trail</span>
            <h2>Aucune instruction selectionnee</h2>
            <p>Selectionnez une recommandation pour generer un draft sous controle humain.</p>
          }
        </article>
      </section>
    </ng-template>

    <ng-template #mapView>
      <section class="two-column map-layout">
        <article class="content-panel map-panel">
          <span class="eyebrow">Carte strategique</span>
          <h2>{{ missionMap()?.question }}</h2>
          <div class="map-system-strip">
            <span>{{ missionMap()?.map_system?.name || 'Systeme cartographique workspace' }}</span>
            <small>{{ missionMap()?.score_summary?.critical || 0 }} critiques · {{ missionMap()?.score_summary?.watch || 0 }} en veille</small>
          </div>
          <app-workspace-map
            [zones]="missionMap()?.zones || []"
            [map]="missionMap()?.map || null"
            [mapSystem]="missionMap()?.map_system || null"
            [mapState]="mapCommandState()"
            [selectedZoneId]="selectedZone()?.id || null"
            (zoneSelected)="selectZone($event)"
          />
        </article>
        <article class="content-panel selected-detail">
          @if (selectedZone(); as zone) {
            <span class="eyebrow">Zone selectionnee</span>
            <h2>{{ zone.name }} · {{ zone.level }}%</h2>
            @if (zone.drivers?.length) {
              <div class="driver-list">
                @for (driver of zone.drivers || []; track driver) {
                  <span>{{ driver }}</span>
                }
              </div>
            }
            <div class="library-list">
              @for (signal of zone.signals; track signal) {
                <article><strong>{{ signal }}</strong></article>
              }
            </div>
            @if (zone.scenario_options?.length) {
              <h3>Options conseillees</h3>
              <div class="scenario-grid compact">
                @for (option of zone.scenario_options || []; track option.id) {
                  <article [class.recommended]="option.recommended">
                    <strong>{{ option.label }}</strong>
                    <span>{{ option.decision_score || confidencePct(option.confidence) }}</span>
                    <p>{{ option.summary }}</p>
                  </article>
                }
              </div>
            }
            <h3>Actions preventives non militaires</h3>
            <div class="option-list">
              @for (recommendation of zone.recommendations; track recommendation) {
                <span>{{ recommendation }}</span>
              }
            </div>
            @if (zone.recommended_windows?.length) {
              <h3>Fenetres recommandees</h3>
              <div class="window-list">
                @for (window of zone.recommended_windows || []; track window.label) {
                  <article>
                    <time>{{ window.start }}-{{ window.end }}</time>
                    <div>
                      <strong>{{ window.label }}</strong>
                      <small>{{ window.why }}</small>
                    </div>
                  </article>
                }
              </div>
            }
            @if (zone.active_action) {
              <div class="action-linked">
                <span>Action active</span>
                <strong>{{ zone.active_action.title }}</strong>
                <small>{{ zone.active_action.owner_label }} · {{ zone.active_action.due_label }}</small>
              </div>
            }
            <button type="button" class="action-button wide" (click)="draftForZone(zone)">
              <ck-glyph name="ledger" [size]="15" />
              <span>Creer instruction preventive</span>
            </button>
            <button type="button" class="action-button wide" (click)="createActionForZone(zone)">
              <ck-glyph name="check" [size]="15" />
              <span>Ajouter action territoriale</span>
            </button>
          }
        </article>
      </section>
    </ng-template>

    <ng-template #monitorView>
      <app-mission-control-monitor
        [monitor]="monitor()"
        [missionMap]="missionMap()"
        [selectedZone]="selectedZone()"
        [mapCommandState]="mapCommandState()"
        [assistantName]="assistantName()"
        [captureImages]="visualCaptureImages()"
        (zoneSelected)="selectZone($event)"
        (visualCapture)="captureVisualSource($event)"
        (assistantPrompt)="openAssistant($event)"
      />
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
        --mission-bg: #05080c;
        --mission-bg-grid: rgba(101, 214, 110, 0.035);
        --mission-rail-bg: linear-gradient(180deg, #05080c 0%, #06100a 100%);
        --mission-panel: linear-gradient(180deg, rgba(15, 24, 28, 0.96) 0%, rgba(10, 16, 19, 0.98) 100%);
        --mission-panel-hi: rgba(18, 31, 28, 0.92);
        --mission-inset: rgba(4, 8, 13, 0.84);
        --mission-border: rgba(156, 184, 212, 0.14);
        --mission-border-strong: rgba(101, 214, 110, 0.30);
        --mission-text: #f4f7fb;
        --mission-text-soft: #c4ceda;
        --mission-text-muted: #8996a8;
        --mission-text-faint: #596678;
        --mission-accent: #65d66e;
        --mission-accent-strong: #93ef74;
        --mission-accent-muted: rgba(101, 214, 110, 0.38);
        --mission-accent-wash: rgba(101, 214, 110, 0.095);
        --mission-trust: #3fd18d;
        --mission-trust-wash: rgba(63, 209, 141, 0.10);
        --mission-warn: #f1b45a;
        --mission-warn-wash: rgba(241, 180, 90, 0.12);
        --mission-orange: #f28c38;
        --mission-orange-wash: rgba(242, 140, 56, 0.12);
        --mission-gold: #e3c681;
        --mission-danger: #f06476;
        --mission-danger-wash: rgba(240, 100, 118, 0.12);
        --mission-radius-sm: 6px;
        --mission-radius: 8px;
        --mission-shadow-card: 0 16px 42px rgba(0, 0, 0, 0.22);
        display: block;
        height: 100vh;
        overflow: hidden;
        background: var(--mission-bg);
        font-family: var(--ck-font-sans);
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
      .mission-main {
        min-width: 0;
        overflow: auto;
        padding: 26px 34px 42px;
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
      .priorities-grid {
        display: grid;
        grid-template-columns: 1.2fr 1fr 1fr;
        gap: 14px;
        margin-bottom: 14px;
      }
      .priority-card {
        min-height: 150px;
        padding: 18px;
        border: 1px solid var(--mission-border);
        background: linear-gradient(135deg, var(--mission-accent-wash), rgba(10, 15, 23, 0.96));
        color: var(--mission-text);
        border-radius: var(--mission-radius);
        box-shadow: var(--mission-shadow-card);
        text-align: left;
        cursor: pointer;
        min-width: 0;
      }
      .priority-card.critical {
        background: linear-gradient(135deg, var(--mission-danger-wash), rgba(10, 15, 23, 0.96));
        border-color: rgba(240, 100, 118, 0.28);
      }
      .priority-card.watch {
        background: linear-gradient(135deg, var(--mission-warn-wash), rgba(10, 15, 23, 0.96));
        border-color: rgba(234, 184, 92, 0.24);
      }
      .priority-card span {
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.13em;
      }
      .priority-card strong {
        display: block;
        margin-top: 8px;
        font-size: 19px;
        font-weight: 650;
        letter-spacing: -0.01em;
      }
      .priority-card p {
        color: var(--mission-text-soft);
        line-height: 1.45;
      }
      .priority-card small { color: var(--mission-text-muted); }
      .priority-card i {
        display: inline-flex;
        margin-top: 12px;
        color: var(--mission-orange);
        font-style: normal;
        font-weight: 650;
      }
      .vp-command-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.75fr);
        gap: 14px;
        margin-bottom: 14px;
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
      .vp-snapshot-grid {
        display: grid;
        gap: 9px;
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
      .vp-snapshot-grid article {
        min-width: 0;
        padding: 12px;
        border: 1px solid var(--mission-border);
        border-left: 3px solid var(--mission-trust);
        border-radius: var(--mission-radius);
        background: var(--mission-inset);
      }
      .vp-snapshot-grid article.critical { border-left-color: var(--mission-danger); }
      .vp-snapshot-grid article.watch { border-left-color: var(--mission-warn); }
      .vp-snapshot-grid span,
      .vp-capability-card span {
        display: block;
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .vp-snapshot-grid strong,
      .vp-snapshot-grid small {
        display: block;
        overflow-wrap: anywhere;
      }
      .vp-snapshot-grid strong {
        margin: 5px 0 3px;
        color: var(--mission-text);
      }
      .vp-snapshot-grid small {
        color: var(--mission-text-muted);
        line-height: 1.35;
      }
      .vp-urgencies {
        margin-bottom: 14px;
      }
      .vp-operating-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
      }
      .vp-capability-card {
        display: block;
        min-height: 132px;
        text-decoration: none;
      }
      .vp-capability-card strong {
        display: block;
        margin: 8px 0;
        color: var(--mission-text);
        font-size: 17px;
      }
      .vp-capability-card small {
        color: var(--mission-text-muted);
        line-height: 1.4;
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
      .map-layout { grid-template-columns: minmax(0, 1.55fr) minmax(340px, 0.55fr); }
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
      @media (max-width: 1200px) {
        .mission-shell { grid-template-columns: 200px minmax(0, 1fr); }
        .mission-main { padding: 24px; }
        .vp-command-grid,
        .vp-operating-strip,
        .executive-alert-grid { grid-template-columns: 1fr; }
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
        .priorities-grid,
        .vp-command-grid,
        .vp-operating-strip,
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
  protected readonly workspace = inject(WorkspaceService);

  private readonly routeView = toSignal(
    this.route.paramMap.pipe(map((params) => (params.get('view') || 'cockpit') as MissionView)),
    { initialValue: 'cockpit' as MissionView },
  );

  readonly loading = signal(true);
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
  readonly selectedSource = signal<SourceRef | null>(null);
  readonly selectedAgendaEvent = signal<AgendaItem | null>(null);
  readonly draft = signal<DraftInstruction | null>(null);
  readonly mapCommandState = signal<Record<string, unknown> | null>(null);
  readonly visualCaptureImages = signal<Record<string, string>>({});

  searchQueryValue = '';
  newAgendaTitle = '';
  newAgendaStart = '2026-04-15T09:45';
  newAgendaLocation = 'Cabinet vice-presidence';
  private readonly visualObjectUrls: string[] = [];
  private readonly calendarUpdateListener = () => this.loadAll();
  private readonly workspaceActionUpdateListener = () => this.loadAll();
  private readonly mapCommandListener = (event: Event) => {
    const detail = (event as CustomEvent<Record<string, unknown>>).detail || {};
    const target = String(detail['target'] || (detail['map_state'] as any)?.selected_zone || '');
    const zone = [...(this.missionMap()?.zones || []), ...(this.monitor()?.zones || [])].find((item) => item.id === target);
    if (zone) this.selectedZone.set(zone);
    this.mapCommandState.set((detail['map_state'] as Record<string, unknown>) || null);
    if (target || detail['map_state']) this.router.navigateByUrl('/hypervisor/mission-room/strategie');
  };

  readonly fallbackNav: MissionNavigationItem[] = [
    { key: 'cockpit', label: 'Priorites', glyph: 'ledger', route: '/hypervisor/mission-room/cockpit', api: '/api/v1/mission-room/cockpit', object: 'Workbench', workbench: 'Workbench' },
    { key: 'monitor', label: 'Situation live', glyph: 'crosshair', route: '/hypervisor/mission-room/monitor', api: '/api/v1/mission-room/monitor', object: 'Workbench', workbench: 'Workbench' },
    { key: 'briefing', label: 'Briefing', glyph: 'ledger', route: '/hypervisor/mission-room/briefing', api: '/api/v1/mission-room/briefing', object: 'Workbench', workbench: 'Workbench' },
    { key: 'agenda', label: 'Agenda', glyph: 'ledger', route: '/hypervisor/mission-room/agenda', api: '/api/v1/mission-room/timeline', object: 'Workbench', workbench: 'Workbench' },
    { key: 'presse', label: 'Presse', glyph: 'pulse', route: '/hypervisor/mission-room/presse', api: '/api/v1/mission-room/news', object: 'Run', workbench: 'Run' },
    { key: 'decisions', label: 'Arbitrages', glyph: 'check', route: '/hypervisor/mission-room/decisions', api: '/api/v1/mission-room/decisions', object: 'Review Queue', workbench: 'Review Queue' },
    { key: 'strategie', label: 'Carte', glyph: 'sliders', route: '/hypervisor/mission-room/strategie', api: '/api/v1/mission-room/map', object: 'Workbench', workbench: 'Workbench' },
  ];

  readonly currentView = computed<MissionView>(() => {
    const view = this.routeView();
    return this.validViews.has(view) ? view : 'cockpit';
  });

  readonly adminRoute = computed(() => `/workspace/${this.workspace.currentSlug() || 'sentinel-ci'}`);
  readonly assistantName = computed(() => this.navigation()?.app?.assistant_label || 'AYA');

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
    'pilotage',
    'agenda',
    'messages',
    'bibliotheque',
    'projets',
    'presse',
    'reputation',
    'veille',
    'decisions',
    'strategie',
    'recherche',
    'assistant',
  ]);

  ngOnInit(): void {
    window.addEventListener('agentium:calendar-updated', this.calendarUpdateListener);
    window.addEventListener('agentium:action-plan-updated', this.workspaceActionUpdateListener);
    window.addEventListener('agentium:visual-intelligence-updated', this.workspaceActionUpdateListener);
    window.addEventListener('agentium:map-command', this.mapCommandListener);
    this.loadAll();
  }

  ngOnDestroy(): void {
    window.removeEventListener('agentium:calendar-updated', this.calendarUpdateListener);
    window.removeEventListener('agentium:action-plan-updated', this.workspaceActionUpdateListener);
    window.removeEventListener('agentium:visual-intelligence-updated', this.workspaceActionUpdateListener);
    window.removeEventListener('agentium:map-command', this.mapCommandListener);
    this.visualObjectUrls.forEach((url) => URL.revokeObjectURL(url));
    this.visualObjectUrls.length = 0;
  }

  private loadAll(): void {
    forkJoin({
      navigation: this.api.get<MissionNavigation>('/mission-room/navigation'),
      cockpit: this.api.get<MissionCockpit>('/mission-room/cockpit'),
      briefing: this.api.get<MissionBriefing>('/mission-room/briefing'),
      projects: this.api.get<MissionProjects>('/mission-room/projects'),
      missionMap: this.api.get<MissionMap>('/mission-room/map'),
      monitor: this.api.get<MissionMonitor>('/mission-room/monitor'),
      news: this.api.get<MissionNews>('/mission-room/news'),
      timeline: this.api.get<MissionTimeline>('/mission-room/timeline'),
      decisions: this.api.get<MissionDecisions>('/mission-room/decisions'),
      library: this.api.get<MissionLibrary>('/mission-room/library'),
      search: this.api.get<MissionSearch>('/mission-room/search', { q: '' }),
    }).subscribe({
      next: ({ navigation, cockpit, briefing, projects, missionMap, monitor, news, timeline, decisions, library, search }) => {
        this.navigation.set(navigation);
        this.cockpit.set(cockpit);
        this.briefing.set(briefing);
        this.projects.set(projects);
        this.missionMap.set(missionMap);
        this.monitor.set(monitor);
        this.news.set(news);
        this.timeline.set(timeline);
        this.decisions.set(decisions);
        this.library.set(library);
        this.search.set(search);
        this.selectedProject.set(projects.projects[0] || null);
        this.selectedZone.set(missionMap.zones[0] || null);
        const currentAgenda = this.selectedAgendaEvent();
        const agenda = timeline.agenda || [];
        const stillVisible = currentAgenda?.id ? agenda.find((item) => item.id === currentAgenda.id) : null;
        this.selectedAgendaEvent.set(stillVisible || agenda.find((item) => item.status !== 'cancelled') || agenda[0] || null);
        this.hydrateVisualCaptureImages(monitor);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
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

  newsAlerts(): NewsSignal[] {
    const payload = this.news();
    return payload?.executive_alerts?.length ? payload.executive_alerts : payload?.signals || [];
  }

  decisionSentence60(): NonNullable<MissionCockpit['decision_sentence']> {
    return this.cockpit()?.decision_sentence || {
      label: 'Sentence du jour',
      text: 'M. le Vice-President, votre priorite absolue ce matin est la Zone Nord. Tout le reste peut attendre.',
      deadline: 'avant Conseil 15h00',
      generated_by: this.assistantName(),
    };
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
      zone: name,
      zoom: 'territory',
      highlight: true,
    });
    this.router.navigateByUrl('/hypervisor/mission-room/monitor');
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

  openAssistant(prompt?: string): void {
    this.chat.open({
      mode: 'quick',
      assistantProfile: 'vigie_executive',
      initialPrompt: prompt || null,
    });
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
    this.api
      .post<ActionItem>('/action-plans/', {
        ...payload,
        due_at: payload.due_at || null,
        confidence: payload.confidence || 'medium',
      })
      .subscribe((item) => {
        this.loadAll();
        this.openAssistant(`Action cabinet ajoutee : ${item.title}. Resume les prochaines etapes et les sources utiles.`);
      });
  }

  completeAction(item: ActionItem): void {
    this.api.post<ActionItem>(`/action-plans/${item.id}/complete`, {}).subscribe(() => this.loadAll());
  }

  cancelAction(item: ActionItem): void {
    this.api.post<ActionItem>(`/action-plans/${item.id}/cancel`, { reason: 'Arbitrage depuis Mission Room' }).subscribe(() => this.loadAll());
  }

  selectAgendaEvent(event: AgendaItem): void {
    this.selectedAgendaEvent.set(event);
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

  createDraft(targetId: string, targetType: string): void {
    this.api
      .post<DraftInstruction>('/mission-room/actions/draft', {
        target_id: targetId,
        target_type: targetType,
        instruction_type: 'dircab_instruction',
      })
      .subscribe((draft) => this.draft.set(draft));
  }

  runSearch(): void {
    this.api
      .get<MissionSearch>('/mission-room/search', { q: this.searchQueryValue.trim() })
      .subscribe((payload) => this.search.set(payload));
  }
}
