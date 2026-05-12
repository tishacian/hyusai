import { ChangeDetectionStrategy, Component, Input, OnInit, computed, inject, signal } from '@angular/core';
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

type MissionView =
  | 'cockpit'
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

interface AgendaItem {
  time: string;
  title: string;
  location: string;
  tone: string;
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
  sources: string[];
}

interface MapZone {
  id: string;
  name: string;
  level: number;
  tone: string;
  centroid: { x: number; y: number };
  polygon: string;
  signals: string[];
  recommendations: string[];
  sources: string[];
}

interface NewsSignal {
  id: string;
  title: string;
  risk_level: string;
  sentiment: string;
  summary: string;
  source: string;
  sources: string[];
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
  map: { country: string; view_box: string; projection: string; accuracy: string };
  zones: MapZone[];
  sources: SourceRef[];
}

interface MissionNews {
  summary: string;
  signals: NewsSignal[];
  sources: SourceRef[];
}

interface MissionTimeline {
  agenda: AgendaItem[];
  messages: MessageItem[];
  summary: string;
  sources: SourceRef[];
}

interface MissionDecisions {
  decisions: DecisionItem[];
  policy: Record<string, unknown>;
  sources: SourceRef[];
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
        <span class="brand-mark">S</span>
        <div>
          <strong>SENTINEL-CI</strong>
          <small>{{ assistantName }}</small>
        </div>
      </div>

      <a class="rail-search" routerLink="/hypervisor/mission-room/recherche">
        <ck-glyph name="zoom-in" [size]="12" />
        <span>Rechercher</span>
      </a>

      <nav class="mission-nav">
        @for (item of items; track item.key) {
          <a
            [routerLink]="item.route"
            routerLinkActive="active"
            class="mission-nav-item"
            [attr.aria-current]="activeView === item.key ? 'page' : null"
          >
            <ck-glyph [name]="item.glyph" [size]="14" />
            <span>{{ item.label }}</span>
          </a>
        }
      </nav>

      <div class="rail-spacer"></div>

      <div class="demo-card">
        <span>Sources qualifiees</span>
        <strong>Institutionnel · presse · signaux faibles</strong>
      </div>
      <div class="rail-alerts">
        <ck-glyph name="warn" [size]="13" />
        <span>16 alertes</span>
      </div>
      <a class="rail-admin" [routerLink]="adminRoute">
        <ck-glyph name="sliders" [size]="13" />
        <span>Workspace Admin</span>
      </a>
      <a class="rail-admin" routerLink="/systems">
        <ck-glyph name="cube" [size]="13" />
        <span>Agentium OS</span>
      </a>
      <div class="rail-clock">
        <strong>11:15</strong>
        <span>Mercredi 15 Avril</span>
      </div>
    </aside>
  `,
  styles: [
    `
      :host { display: block; min-height: 0; }
      .mission-rail {
        font-family: var(--ck-font-sans);
        width: 220px;
        height: 100%;
        padding: 18px 16px;
        background: var(--mission-rail-bg, var(--ck-bg-base));
        border-right: 1px solid var(--mission-border, var(--ck-stroke-2));
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-height: 0;
      }
      .rail-brand {
        display: flex;
        align-items: center;
        gap: 10px;
        color: var(--mission-text, var(--ck-fg-1));
        min-width: 0;
      }
      .brand-mark {
        width: 34px;
        height: 34px;
        border-radius: 9px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--mission-accent, var(--ck-signal-cool));
        font-weight: 800;
        background: var(--mission-accent-wash, rgba(125, 211, 252, 0.08));
        border: 1px solid var(--mission-border-strong, var(--ck-stroke-hot));
        box-shadow: var(--mission-shadow-card, none);
      }
      .rail-brand strong {
        display: block;
        font-family: var(--ck-font-mono);
        font-size: 12px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }
      .rail-brand small {
        color: var(--mission-text-muted, var(--ck-fg-3));
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.18em;
      }
      .rail-search,
      .mission-nav-item,
      .rail-admin {
        display: flex;
        align-items: center;
        gap: 9px;
        min-height: 34px;
        padding: 8px 10px;
        border-radius: var(--mission-radius-sm, 7px);
        color: var(--mission-text-soft, var(--ck-fg-2));
        text-decoration: none;
        font-size: 13px;
        min-width: 0;
      }
      .rail-search {
        border: 1px solid var(--mission-border, var(--ck-stroke-2));
        background: var(--mission-inset, var(--ck-bg-inset));
        color: var(--mission-text-faint, var(--ck-fg-4));
      }
      .mission-nav {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-height: 0;
      }
      .mission-nav-item.active,
      .mission-nav-item:hover,
      .rail-admin:hover {
        background: var(--mission-panel-hi, var(--ck-bg-panel-hi));
        color: var(--mission-text, var(--ck-fg-1));
      }
      .mission-nav-item.active {
        color: var(--mission-accent, var(--ck-signal-cool));
        box-shadow: inset 3px 0 0 var(--mission-accent, var(--ck-signal-cool));
      }
      .rail-spacer { flex: 1 1 auto; min-height: 8px; }
      .demo-card {
        padding: 10px;
        border: 1px solid var(--mission-border, var(--ck-stroke-2));
        border-radius: var(--mission-radius, 8px);
        color: var(--mission-accent, var(--ck-signal-cool));
        background: var(--mission-panel-hi, var(--ck-bg-panel-hi));
      }
      .demo-card span,
      .rail-clock span {
        display: block;
        color: var(--mission-text-faint, var(--ck-fg-4));
        font-size: 11px;
      }
      .demo-card strong {
        display: block;
        margin-top: 3px;
        font-size: 12px;
      }
      .rail-alerts {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 9px 10px;
        color: var(--mission-danger, var(--ck-signal-neg));
        border-radius: var(--mission-radius, 8px);
        background: var(--mission-danger-wash, rgba(239, 90, 111, 0.11));
        border: 1px solid rgba(239, 90, 111, 0.20);
      }
      .rail-admin {
        padding: 6px 8px;
        min-height: 30px;
        font-size: 12px;
      }
      .rail-clock strong {
        display: block;
        font-family: var(--ck-font-mono);
        font-variant-numeric: tabular-nums;
        color: var(--mission-text, var(--ck-fg-1));
        font-size: 24px;
        font-weight: 500;
        letter-spacing: -0.01em;
      }
    `,
  ],
})
export class MissionRailComponent {
  @Input() items: MissionNavigationItem[] = [];
  @Input() activeView: MissionView = 'cockpit';
  @Input() adminRoute = '/workspace';
  @Input() assistantName = 'VIGIE';
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
    MissionMetricCardComponent,
    MissionChartPanelComponent,
    MissionSourcePillComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="mission-shell">
      <app-mission-rail
        [items]="navigation()?.items || fallbackNav"
        [activeView]="currentView()"
        [adminRoute]="adminRoute()"
        [assistantName]="assistantName()"
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
                <span class="eyebrow">AI Government Mission Room</span>
                <span class="hero-status">{{ cockpit()?.briefing_status || 'Briefing pret' }}</span>
              </div>
              <h1>{{ cockpit()?.title || 'Bonjour, Ministre.' }}</h1>
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
      <section class="priorities-grid" aria-label="Priorites du jour">
        @for (priority of cockpit()?.priorities || []; track priority.id) {
          <button
            type="button"
            class="priority-card"
            [class.critical]="priority.tone === 'critical'"
            [class.watch]="priority.tone === 'watch'"
            (click)="focusPriority(priority)"
          >
            <span>{{ priority.kind }}</span>
            <strong>{{ priority.title }}</strong>
            <p>{{ priority.summary }}</p>
            <small>{{ priority.deadline }}</small>
          </button>
        }
      </section>

      <section class="metrics-grid">
        <app-mission-metric-card label="Alertes presse" [value]="kpi('press_alerts')" caption="articles negatifs" tone="critical" />
        <app-mission-metric-card label="Emails" [value]="kpi('emails')" caption="2 urgents" tone="watch" />
        <app-mission-metric-card label="Reunions" [value]="kpi('meetings')" caption="prochaine dans 1h46" tone="info" />
        <app-mission-metric-card label="Reputation" [value]="kpi('reputation_score')" caption="80 articles analyses" tone="good" />
        <app-mission-metric-card label="Decisions" [value]="decisions()?.decisions?.length || 0" caption="validation requise" tone="watch" />
      </section>

      <section class="cockpit-grid">
        <app-mission-chart-panel eyebrow="Niveau de menace" title="7 derniers jours">
          <svg class="line-chart" viewBox="0 0 520 190" preserveAspectRatio="none">
            <path class="area danger" [attr.d]="trendArea(cockpit()?.threat_trend || [])"></path>
            <path class="line danger" [attr.d]="trendPath(cockpit()?.threat_trend || [])"></path>
            <path class="line muted" d="M20 145 L500 145"></path>
          </svg>
        </app-mission-chart-panel>

        <app-mission-chart-panel eyebrow="Flux communications" title="Aujourd'hui">
          <div class="bar-chart">
            @for (bar of cockpit()?.communications_flow || []; track bar.hour) {
              <div class="bar-col">
                <div class="bar-pair">
                  <span class="bar primary" [style.height.%]="barHeight(bar.institutional)"></span>
                  <span class="bar grey" [style.height.%]="barHeight(bar.press)"></span>
                </div>
                <small>{{ bar.hour }}</small>
              </div>
            }
          </div>
        </app-mission-chart-panel>

        <app-mission-chart-panel eyebrow="Etat ops" title="Disponibilite">
          <div class="ops-panel">
            <div class="donut" [style.--value]="kpiNumber('ops_operational_pct')">
              <strong>{{ kpi('ops_operational_pct') }}%</strong>
              <span>operationnel</span>
            </div>
            <div class="legend">
              <span><i class="good"></i> Operationnel {{ kpi('ops_operational_pct') }}%</span>
              <span><i class="watch"></i> En alerte {{ kpi('ops_watch_pct') }}%</span>
              <span><i class="critical"></i> Critique {{ kpi('ops_critical_pct') }}%</span>
            </div>
          </div>
        </app-mission-chart-panel>

        <app-mission-chart-panel eyebrow="Zones de surveillance" title="Niveaux d'alerte">
          <div class="zone-bars">
            @for (zone of cockpit()?.zones || []; track zone.name) {
              <button type="button" (click)="selectZoneByName(zone.name)">
                <span>{{ zone.name }}</span>
                <i><b [style.width.%]="zone.level" [class]="zone.tone"></b></i>
                <strong>{{ zone.level }}%</strong>
              </button>
            }
          </div>
        </app-mission-chart-panel>

        <app-mission-chart-panel eyebrow="E-Reputation" title="Sentiment medias" [value]="reputationValue()">
          <svg class="line-chart" viewBox="0 0 520 190" preserveAspectRatio="none">
            <path class="line good" [attr.d]="trendPath(cockpit()?.reputation?.trend || [])"></path>
            <path class="line muted" d="M20 120 L500 120"></path>
            <path class="line danger soft" d="M20 150 L130 155 L240 142 L340 158 L500 146"></path>
          </svg>
        </app-mission-chart-panel>

        <app-mission-chart-panel eyebrow="Veille mediatique" title="Sources & alertes">
          <div class="source-bars">
            @for (source of cockpit()?.media_sources || []; track source.label) {
              <div>
                <span>{{ source.label }}</span>
                <i><b [style.width.%]="source.coverage"></b></i>
                <strong>{{ source.coverage }}%</strong>
                <small>{{ source.count }}</small>
              </div>
            }
          </div>
          <ul class="compact-list">
            @for (alert of cockpit()?.latest_alerts || []; track alert.id) {
              <li>{{ alert.title }}</li>
            }
          </ul>
        </app-mission-chart-panel>

        <app-mission-chart-panel eyebrow="Agenda" title="Aujourd'hui - 5">
          <ol class="agenda-list">
            @for (item of cockpit()?.agenda || []; track item.time) {
              <li [class]="item.tone">
                <time>{{ item.time }}</time>
                <div>
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.location }}</span>
                </div>
              </li>
            }
          </ol>
        </app-mission-chart-panel>

        <app-mission-chart-panel eyebrow="Mots-cles" title="Tendances de recherche">
          <div class="keyword-grid">
            @for (kw of cockpit()?.keywords || []; track kw.label) {
              <article>
                <span>{{ kw.label }}</span>
                <strong>{{ kw.count }}</strong>
                <small [class.down]="kw.delta < 0">{{ kw.delta > 0 ? '+' : '' }}{{ kw.delta }}%</small>
              </article>
            }
          </div>
        </app-mission-chart-panel>
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
            <button type="button" class="action-button wide" (click)="draftForProject(project)">
              <ck-glyph name="ledger" [size]="15" />
              <span>Creer instruction Directeur de cabinet</span>
            </button>
          }
        </article>
      </section>
    </ng-template>

    <ng-template #timelineView>
      <section class="two-column">
        <article class="content-panel">
          <span class="eyebrow">Agenda ministeriel</span>
          <h2>Deroule de la journee</h2>
          <ol class="agenda-list large">
            @for (item of timeline()?.agenda || []; track item.time) {
              <li [class]="item.tone">
                <time>{{ item.time }}</time>
                <div>
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.location }}</span>
                </div>
              </li>
            }
          </ol>
        </article>
        <article class="content-panel">
          <span class="eyebrow">Synthese</span>
          <h2>Canaux institutionnels</h2>
          <p>{{ timeline()?.summary }}</p>
          <button type="button" class="action-button wide" (click)="openAssistant('Prepare une synthese agenda.')">
            <ck-glyph name="bolt" [size]="14" />
            <span>Demander une synthese {{ assistantName() }}</span>
          </button>
        </article>
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
      <section class="two-column">
        <article class="content-panel span-2">
          <span class="eyebrow">Presse et intelligence ouverte</span>
          <h2>Synthese des signaux</h2>
          <p>{{ news()?.summary }}</p>
        </article>
        @for (signal of news()?.signals || []; track signal.id) {
          <article class="content-panel">
            <span class="status-pill" [class]="signal.risk_level">{{ signal.risk_level }}</span>
            <h3>{{ signal.title }}</h3>
            <p>{{ signal.summary }}</p>
            <small>{{ signal.source }} · sentiment {{ signal.sentiment }}</small>
          </article>
        }
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
          <h2>Qualification</h2>
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
          <svg class="territory-map" [attr.viewBox]="missionMap()?.map?.view_box || '200 40 470 480'" role="img">
            @for (zone of missionMap()?.zones || []; track zone.id) {
              <polygon
                [attr.points]="zone.polygon"
                [attr.fill]="zoneFill(zone)"
                [attr.opacity]="selectedZone()?.id === zone.id ? 0.94 : 0.62"
                (click)="selectedZone.set(zone)"
              ></polygon>
              <text [attr.x]="zone.centroid.x" [attr.y]="zone.centroid.y" text-anchor="middle">{{ zone.name }}</text>
            }
          </svg>
        </article>
        <article class="content-panel selected-detail">
          @if (selectedZone(); as zone) {
            <span class="eyebrow">Zone selectionnee</span>
            <h2>{{ zone.name }} · {{ zone.level }}%</h2>
            <div class="library-list">
              @for (signal of zone.signals; track signal) {
                <article><strong>{{ signal }}</strong></article>
              }
            </div>
            <h3>Actions preventives non militaires</h3>
            <div class="option-list">
              @for (recommendation of zone.recommendations; track recommendation) {
                <span>{{ recommendation }}</span>
              }
            </div>
            <button type="button" class="action-button wide" (click)="draftForZone(zone)">
              <ck-glyph name="ledger" [size]="15" />
              <span>Creer instruction preventive</span>
            </button>
          }
        </article>
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
        --mission-bg: #05080c;
        --mission-bg-grid: rgba(125, 211, 252, 0.035);
        --mission-rail-bg: linear-gradient(180deg, #05080c 0%, #060a10 100%);
        --mission-panel: linear-gradient(180deg, rgba(15, 22, 32, 0.96) 0%, rgba(10, 15, 23, 0.98) 100%);
        --mission-panel-hi: rgba(18, 27, 39, 0.92);
        --mission-inset: rgba(4, 8, 13, 0.84);
        --mission-border: rgba(156, 184, 212, 0.14);
        --mission-border-strong: rgba(125, 211, 252, 0.28);
        --mission-text: #f4f7fb;
        --mission-text-soft: #c4ceda;
        --mission-text-muted: #8996a8;
        --mission-text-faint: #596678;
        --mission-accent: #8bd8ff;
        --mission-accent-strong: #54c7f3;
        --mission-accent-muted: rgba(139, 216, 255, 0.38);
        --mission-accent-wash: rgba(139, 216, 255, 0.09);
        --mission-trust: #42d99b;
        --mission-trust-wash: rgba(66, 217, 155, 0.10);
        --mission-warn: #eab85c;
        --mission-warn-wash: rgba(234, 184, 92, 0.12);
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
          linear-gradient(180deg, rgba(125, 211, 252, 0.045) 0%, rgba(5, 8, 12, 0) 32%),
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
      .action-button.wide {
        width: 100%;
        margin-top: 14px;
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
      .metrics-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 14px;
        margin-bottom: 14px;
      }
      .cockpit-grid {
        display: grid;
        grid-template-columns: repeat(12, minmax(0, 1fr));
        gap: 14px;
      }
      .cockpit-grid > *:nth-child(1),
      .cockpit-grid > *:nth-child(2),
      .cockpit-grid > *:nth-child(5),
      .cockpit-grid > *:nth-child(6) { grid-column: span 6; }
      .cockpit-grid > *:nth-child(3),
      .cockpit-grid > *:nth-child(7) { grid-column: span 4; }
      .cockpit-grid > *:nth-child(4),
      .cockpit-grid > *:nth-child(8) { grid-column: span 8; }
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
      .action-panel {
        display: flex;
        flex-direction: column;
        gap: 10px;
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
      .map-layout { grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr); }
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
        .metrics-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .cockpit-grid > * { grid-column: span 12 !important; }
        .two-column, .map-layout { grid-template-columns: 1fr; }
      }
      @media (max-width: 840px) {
        :host { height: auto; overflow: auto; }
        .mission-shell { min-height: 100vh; grid-template-columns: 1fr; }
        app-mission-rail { position: sticky; top: 0; z-index: 5; }
        .mission-main { padding: 20px 14px; }
        .mission-hero,
        .priorities-grid,
        .metrics-grid,
        .search-form {
          grid-template-columns: 1fr;
          display: grid;
        }
      }
    `,
  ],
})
export class MissionRoomComponent implements OnInit {
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
  readonly news = signal<MissionNews | null>(null);
  readonly timeline = signal<MissionTimeline | null>(null);
  readonly decisions = signal<MissionDecisions | null>(null);
  readonly library = signal<MissionLibrary | null>(null);
  readonly search = signal<MissionSearch | null>(null);
  readonly selectedProject = signal<Project | null>(null);
  readonly selectedZone = signal<MapZone | null>(null);
  readonly selectedSource = signal<SourceRef | null>(null);
  readonly draft = signal<DraftInstruction | null>(null);

  searchQueryValue = '';

  readonly fallbackNav: MissionNavigationItem[] = [
    { key: 'cockpit', label: 'Cockpit', glyph: 'ledger', route: '/hypervisor/mission-room/cockpit', api: '/api/v1/mission-room/cockpit', object: 'Workbench', workbench: 'Workbench' },
    { key: 'briefing', label: 'Briefing', glyph: 'ledger', route: '/hypervisor/mission-room/briefing', api: '/api/v1/mission-room/briefing', object: 'Workbench', workbench: 'Workbench' },
    { key: 'pilotage', label: 'Pilotage', glyph: 'telemetry', route: '/hypervisor/mission-room/pilotage', api: '/api/v1/mission-room/projects', object: 'System', workbench: 'System' },
    { key: 'strategie', label: 'Strategie', glyph: 'sliders', route: '/hypervisor/mission-room/strategie', api: '/api/v1/mission-room/map', object: 'Workbench', workbench: 'Workbench' },
    { key: 'assistant', label: 'Assistant', glyph: 'bolt', route: '/hypervisor/mission-room/assistant', api: '/api/v1/chat/stream', object: 'Workbench', workbench: 'Workbench' },
  ];

  readonly currentView = computed<MissionView>(() => {
    const view = this.routeView();
    return this.validViews.has(view) ? view : 'cockpit';
  });

  readonly adminRoute = computed(() => `/workspace/${this.workspace.currentSlug() || 'sentinel-ci'}`);
  readonly assistantName = computed(() => this.navigation()?.app?.assistant_label || 'VIGIE');

  readonly sources = computed(() => {
    const rows = [
      ...(this.cockpit()?.sources || []),
      ...(this.briefing()?.sources || []),
      ...(this.projects()?.sources || []),
      ...(this.missionMap()?.sources || []),
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
    forkJoin({
      navigation: this.api.get<MissionNavigation>('/mission-room/navigation'),
      cockpit: this.api.get<MissionCockpit>('/mission-room/cockpit'),
      briefing: this.api.get<MissionBriefing>('/mission-room/briefing'),
      projects: this.api.get<MissionProjects>('/mission-room/projects'),
      missionMap: this.api.get<MissionMap>('/mission-room/map'),
      news: this.api.get<MissionNews>('/mission-room/news'),
      timeline: this.api.get<MissionTimeline>('/mission-room/timeline'),
      decisions: this.api.get<MissionDecisions>('/mission-room/decisions'),
      library: this.api.get<MissionLibrary>('/mission-room/library'),
      search: this.api.get<MissionSearch>('/mission-room/search', { q: '' }),
    }).subscribe({
      next: ({ navigation, cockpit, briefing, projects, missionMap, news, timeline, decisions, library, search }) => {
        this.navigation.set(navigation);
        this.cockpit.set(cockpit);
        this.briefing.set(briefing);
        this.projects.set(projects);
        this.missionMap.set(missionMap);
        this.news.set(news);
        this.timeline.set(timeline);
        this.decisions.set(decisions);
        this.library.set(library);
        this.search.set(search);
        this.selectedProject.set(projects.projects[0] || null);
        this.selectedZone.set(missionMap.zones[0] || null);
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

  barHeight(value: number): number {
    return Math.max(8, Math.min(100, (value / 50) * 100));
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

  selectZoneByName(name: string): void {
    const zone = (this.missionMap()?.zones || []).find((item) => item.name === name);
    if (zone) this.selectedZone.set(zone);
    this.router.navigateByUrl('/hypervisor/mission-room/strategie');
  }

  selectProject(project: Project): void {
    this.selectedProject.set(project);
  }

  focusPriority(priority: Priority): void {
    if (priority.id === 'prio-security-north') {
      this.selectZoneByName('Nord');
      return;
    }
    if (priority.kind === 'mail') {
      this.router.navigateByUrl('/hypervisor/mission-room/messages');
      return;
    }
    this.router.navigateByUrl('/hypervisor/mission-room/agenda');
  }

  sourceLabel(sourceId: string): string {
    return this.sources().get(sourceId)?.label || sourceId;
  }

  showSource(sourceId: string): void {
    this.selectedSource.set(this.sources().get(sourceId) || null);
  }

  openAssistant(_prompt?: string): void {
    this.chat.open({ mode: 'quick' });
  }

  draftForProject(project: Project): void {
    this.createDraft(project.id, 'project');
  }

  draftForZone(zone: MapZone): void {
    this.createDraft(zone.id, 'zone');
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
