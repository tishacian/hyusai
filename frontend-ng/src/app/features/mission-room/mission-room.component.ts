import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { forkJoin } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { GlyphComponent } from '@app/shared/cockpit';

interface SourceRef {
  id: string;
  label: string;
  kind: string;
  confidence: number;
  age: string;
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

interface MissionOverview {
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
  selector: 'app-mission-room',
  standalone: true,
  imports: [CommonModule, GlyphComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="mission-shell">
      <aside class="aria-rail" aria-label="ARIA ministerial cockpit">
        <div class="aria-brand">
          <span class="brand-mark">A</span>
          <span>ARIA</span>
        </div>
        <label class="rail-search">
          <ck-glyph name="zoom-in" [size]="12" />
          <input type="search" placeholder="Rechercher" />
        </label>
        <nav class="ministerial-nav" aria-label="Surfaces ministerielles">
          @for (item of navItems; track item.key) {
            <button
              type="button"
              class="ministerial-nav-item"
              [class.active]="activeSection() === item.key"
              (click)="activeSection.set(item.key)"
            >
              <ck-glyph [name]="item.glyph" [size]="14" />
              <span>{{ item.label }}</span>
            </button>
          }
        </nav>
        <div class="demo-status">
          <span>Mode demo</span>
          <strong>Credits epuises</strong>
        </div>
        <div class="rail-alerts">
          <ck-glyph name="warn" [size]="13" />
          <span>16 alertes</span>
        </div>
        <button type="button" class="rail-settings" (click)="activeSection.set('decisions')">
          <ck-glyph name="sliders" [size]="13" />
          <span>Parametres</span>
        </button>
        <div class="rail-clock">
          <strong>11:15</strong>
          <span>Mercredi 15 Avril</span>
        </div>
      </aside>

      <main class="mission-main">
        @if (loading()) {
          <div class="loading-panel">
            <span class="dots"></span>
            <strong>Chargement du cockpit SENTINEL-CI</strong>
          </div>
        } @else {
          <header class="mission-hero">
            <div>
              <span class="eyebrow">SENTINEL-CI / Government Mission Room</span>
              <h1>{{ overview()?.title || 'Bonjour, Ministre.' }}</h1>
              <p>{{ overview()?.date_label || 'Mercredi 15 Avril 2026' }}</p>
            </div>
            <div class="hero-actions">
              <button type="button" class="action-button ghost" (click)="activeSection.set('briefing')">
                <ck-glyph name="ledger" [size]="15" />
                <span>Briefing</span>
              </button>
              <button type="button" class="action-button" (click)="openAssistant()">
                <ck-glyph name="crosshair" [size]="15" />
                <span>ARIA</span>
              </button>
            </div>
          </header>

          <section class="priorities-grid" aria-label="Priorites du jour">
            @for (priority of overview()?.priorities || []; track priority.id) {
              <button
                type="button"
                class="priority-card"
                [class.critical]="priority.tone === 'critical'"
                [class.watch]="priority.tone === 'watch'"
                (click)="focusPriority(priority)"
              >
                <span class="priority-kind">{{ priority.kind }}</span>
                <strong>{{ priority.title }}</strong>
                <p>{{ priority.summary }}</p>
                <small>{{ priority.deadline }}</small>
              </button>
            }
          </section>

          <section class="metric-strip" aria-label="Indicateurs executifs">
            <article class="metric-card danger">
              <span>Alertes presse</span>
              <strong>{{ kpi('press_alerts') }}</strong>
              <small>{{ kpi('negative_articles') }} articles negatifs</small>
            </article>
            <article class="metric-card gold">
              <span>Emails</span>
              <strong>{{ kpi('emails') }}</strong>
              <small>{{ kpi('urgent_emails') }} urgents</small>
            </article>
            <article class="metric-card blue">
              <span>Reunions du jour</span>
              <strong>{{ kpi('meetings') }}</strong>
              <small>Prochaine dans {{ kpi('next_meeting_in') }}</small>
            </article>
            <article class="metric-card green">
              <span>Score reputation</span>
              <strong>{{ kpi('reputation_score') }}</strong>
              <small>{{ kpi('analyzed_articles') }} articles analyses</small>
            </article>
          </section>

          <section class="dashboard-grid">
            <article class="panel wide">
              <header>
                <span>Niveau de menace</span>
                <strong>7 derniers jours</strong>
              </header>
              <svg viewBox="0 0 520 190" class="line-chart" role="img" aria-label="Tendance du niveau de menace">
                <path class="gridline" d="M20 150 H500 M20 105 H500 M20 60 H500" />
                <path [attr.d]="trendPath(overview()?.threat_trend || [])" class="danger-line" />
                <path [attr.d]="trendArea(overview()?.threat_trend || [])" class="danger-area" />
              </svg>
            </article>

            <article class="panel wide">
              <header>
                <span>Flux communications</span>
                <strong>Aujourd'hui</strong>
              </header>
              <div class="bar-chart">
                @for (row of overview()?.communications_flow || []; track row.hour) {
                  <div class="bar-group">
                    <span class="bar institutional" [style.height.%]="barHeight(row.institutional)"></span>
                    <span class="bar press" [style.height.%]="barHeight(row.press)"></span>
                    <small>{{ row.hour }}</small>
                  </div>
                }
              </div>
            </article>

            <article class="panel ops-panel">
              <header>
                <span>Etat ops</span>
                <strong>68%</strong>
              </header>
              <div class="donut" aria-label="Etat operationnel">
                <span>68%</span>
              </div>
              <div class="legend-list">
                <span><i class="green-dot"></i>Operationnel 68%</span>
                <span><i class="gold-dot"></i>En alerte 22%</span>
                <span><i class="red-dot"></i>Critique 10%</span>
              </div>
            </article>

            <article class="panel zones-panel">
              <header>
                <span>Zones de surveillance</span>
                <strong>Niveaux d'alerte</strong>
              </header>
              @for (zone of overview()?.zones || []; track zone.name) {
                <button type="button" class="zone-row" (click)="selectZoneByName(zone.name)">
                  <span>{{ zone.name }}</span>
                  <b [style.width.%]="zone.level" [ngClass]="zone.tone"></b>
                  <strong>{{ zone.level }}%</strong>
                </button>
              }
            </article>

            <article class="panel agenda-panel">
              <header>
                <span>Agenda</span>
                <strong>Aujourd'hui - {{ overview()?.agenda?.length || 0 }}</strong>
              </header>
              @for (item of overview()?.agenda || []; track item.time) {
                <div class="agenda-item" [ngClass]="item.tone">
                  <time>{{ item.time }}</time>
                  <div>
                    <strong>{{ item.title }}</strong>
                    <small>{{ item.location }}</small>
                  </div>
                </div>
              }
            </article>

            <article class="panel wide">
              <header>
                <span>E-reputation</span>
                <strong>Sentiment medias</strong>
              </header>
              <svg viewBox="0 0 520 170" class="line-chart compact" role="img" aria-label="Tendance reputation">
                <path class="gridline" d="M20 130 H500 M20 90 H500 M20 50 H500" />
                <path [attr.d]="trendPath(overview()?.reputation?.trend || [], 145, 20)" class="good-line" />
              </svg>
              <div class="panel-badge positive">{{ overview()?.reputation?.score || 0 }}% positif</div>
            </article>

            <article class="panel wide">
              <header>
                <span>Veille mediatique</span>
                <strong>Sources et alertes</strong>
              </header>
              @for (source of overview()?.media_sources || []; track source.label) {
                <div class="media-source">
                  <span>{{ source.label }}</span>
                  <b [style.width.%]="source.coverage"></b>
                  <strong>{{ source.coverage }}%</strong>
                  <small>{{ source.count }}</small>
                </div>
              }
              <div class="latest-alerts">
                @for (signal of news()?.signals || []; track signal.id) {
                  <button type="button" (click)="activeSection.set('presse')">
                    <span [ngClass]="signal.risk_level"></span>
                    {{ signal.title }}
                  </button>
                }
              </div>
            </article>
          </section>

          <section class="lower-grid">
            <article class="panel briefing-panel">
              <header>
                <span>Briefing quotidien</span>
                <strong>{{ briefing()?.title }}</strong>
              </header>
              @for (section of briefing()?.sections || []; track section.id) {
                <div class="briefing-section">
                  <h3>{{ section.title }}</h3>
                  <p>{{ section.content }}</p>
                  <div class="source-pills">
                    @for (sourceId of section.sources; track sourceId) {
                      <button type="button" (click)="showSource(sourceId)">{{ sourceLabel(sourceId) }}</button>
                    }
                  </div>
                </div>
              }
            </article>

            <article class="panel projects-panel">
              <header>
                <span>Pilotage projets</span>
                <strong>{{ projects()?.summary?.red || 0 }} rouge</strong>
              </header>
              @for (project of projects()?.projects || []; track project.id) {
                <button
                  type="button"
                  class="project-row"
                  [ngClass]="project.weather"
                  (click)="selectProject(project)"
                >
                  <div>
                    <strong>{{ project.name }}</strong>
                    <small>{{ project.cause }}</small>
                  </div>
                  <span>{{ project.progress }}%</span>
                </button>
              }
              @if (selectedProject()) {
                <div class="selection-card">
                  <h3>{{ selectedProject()?.name }}</h3>
                  <p>{{ selectedProject()?.risk }}</p>
                  <button type="button" class="action-button compact" (click)="draftForProject(selectedProject()!)">
                    <ck-glyph name="ledger" [size]="14" />
                    <span>Creer instruction</span>
                  </button>
                </div>
              }
            </article>

            <article class="panel map-panel">
              <header>
                <span>Carte strategique</span>
                <strong>{{ missionMap()?.map?.country }}</strong>
              </header>
              <p class="map-question">{{ missionMap()?.question }}</p>
              <div class="map-grid">
                <svg
                  [attr.viewBox]="missionMap()?.map?.view_box || '200 40 470 480'"
                  class="territory-map"
                  role="img"
                  aria-label="Carte decisionnelle illustrative"
                >
                  @for (zone of missionMap()?.zones || []; track zone.id) {
                    <polygon
                      [attr.points]="zone.polygon"
                      [attr.fill]="zoneFill(zone)"
                      [attr.stroke]="selectedZone()?.id === zone.id ? '#f1c75b' : '#2d4052'"
                      [attr.stroke-width]="selectedZone()?.id === zone.id ? 4 : 2"
                      (click)="selectedZone.set(zone)"
                    />
                    <text
                      [attr.x]="zone.centroid.x"
                      [attr.y]="zone.centroid.y"
                      text-anchor="middle"
                      dominant-baseline="middle"
                    >
                      {{ zone.name }}
                    </text>
                  }
                </svg>
                @if (selectedZone()) {
                  <div class="zone-detail">
                    <span class="eyebrow">Zone prioritaire</span>
                    <h3>{{ selectedZone()?.name }} - {{ selectedZone()?.level }}%</h3>
                    <strong>Signaux</strong>
                    <ul>
                      @for (signal of selectedZone()?.signals || []; track signal) {
                        <li>{{ signal }}</li>
                      }
                    </ul>
                    <strong>Actions non militaires</strong>
                    <ul>
                      @for (action of selectedZone()?.recommendations || []; track action) {
                        <li>{{ action }}</li>
                      }
                    </ul>
                    <button type="button" class="action-button compact" (click)="draftForZone(selectedZone()!)">
                      <ck-glyph name="ledger" [size]="14" />
                      <span>Instruction zone</span>
                    </button>
                  </div>
                }
              </div>
            </article>

            <article class="panel assistant-panel">
              <header>
                <span>Assistant transverse</span>
                <strong>RAG + Oracle + Audit</strong>
              </header>
              <p>ARIA combine connaissances, signaux ouverts, projets et contexte temporel. Les recommandations restent advisory et sourcées.</p>
              @for (prompt of overview()?.assistant_prompts || []; track prompt) {
                <button type="button" class="prompt-button" (click)="openAssistant(prompt)">
                  {{ prompt }}
                </button>
              }
            </article>
          </section>

          @if (draft()) {
            <aside class="draft-panel">
              <button type="button" class="close-draft" (click)="draft.set(null)" aria-label="Fermer">
                <ck-glyph name="x" [size]="15" />
              </button>
              <span class="eyebrow">Draft / validation required</span>
              <h2>{{ draft()?.title }}</h2>
              <p class="recipient">Destinataire : {{ draft()?.recipient }}</p>
              <p>{{ draft()?.body }}</p>
              <div class="source-pills">
                @for (sourceId of draft()?.sources || []; track sourceId) {
                  <button type="button" (click)="showSource(sourceId)">{{ sourceLabel(sourceId) }}</button>
                }
              </div>
              <div class="draft-control">
                <ck-glyph name="shield" [size]="15" />
                <span>Aucun envoi externe. Validation humaine obligatoire.</span>
              </div>
            </aside>
          }
        }
      </main>
    </section>
  `,
  styles: [
    `
      :host {
        display: block;
        min-height: 100%;
        background: #050607;
        color: #f7f7f2;
      }

      * { box-sizing: border-box; letter-spacing: 0; }

      button {
        font: inherit;
      }

      .mission-shell {
        min-height: calc(100vh - 76px);
        display: grid;
        grid-template-columns: 236px minmax(0, 1fr);
        background:
          linear-gradient(180deg, rgba(12, 16, 19, 0.96), rgba(5, 6, 7, 1)),
          #050607;
      }

      .aria-rail {
        position: sticky;
        top: 0;
        height: calc(100vh - 76px);
        padding: 22px 16px;
        border-right: 1px solid rgba(255, 255, 255, 0.08);
        background: rgba(0, 0, 0, 0.78);
        display: flex;
        flex-direction: column;
        gap: 12px;
        overflow: hidden;
      }

      .aria-brand {
        display: flex;
        align-items: center;
        gap: 10px;
        color: #f4d273;
        font-family: var(--ck-font-mono);
        font-size: 13px;
        font-weight: 700;
      }

      .brand-mark {
        width: 28px;
        height: 28px;
        border: 1px solid rgba(244, 210, 115, 0.46);
        border-radius: 6px;
        display: grid;
        place-items: center;
        background: rgba(244, 210, 115, 0.1);
      }

      .rail-search {
        display: flex;
        align-items: center;
        gap: 8px;
        height: 34px;
        padding: 0 10px;
        border: 1px solid rgba(255, 255, 255, 0.09);
        border-radius: 6px;
        background: rgba(255, 255, 255, 0.04);
        color: #8b96a4;
      }

      .rail-search input {
        width: 100%;
        min-width: 0;
        border: 0;
        outline: 0;
        color: #f7f7f2;
        background: transparent;
        font-size: 12px;
      }

      .ministerial-nav {
        display: flex;
        flex-direction: column;
        gap: 3px;
      }

      .ministerial-nav-item,
      .rail-settings {
        width: 100%;
        min-height: 34px;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 10px;
        border: 0;
        border-radius: 6px;
        color: #c7ccd4;
        background: transparent;
        text-align: left;
        cursor: pointer;
      }

      .ministerial-nav-item:hover,
      .rail-settings:hover,
      .ministerial-nav-item.active {
        color: #f7f7f2;
        background: rgba(255, 255, 255, 0.1);
      }

      .demo-status,
      .rail-alerts {
        border-radius: 6px;
        padding: 9px 10px;
        font-size: 12px;
      }

      .demo-status {
        margin-top: auto;
        color: #f4d273;
        background: rgba(160, 118, 36, 0.16);
        border: 1px solid rgba(244, 210, 115, 0.22);
      }

      .demo-status strong,
      .demo-status span {
        display: block;
      }

      .rail-alerts {
        display: flex;
        align-items: center;
        gap: 8px;
        color: #ff7878;
        background: rgba(159, 32, 32, 0.18);
      }

      .rail-clock strong {
        display: block;
        font-family: var(--ck-font-mono);
        font-size: 24px;
        font-weight: 600;
      }

      .rail-clock span {
        color: #8b96a4;
        font-size: 11px;
      }

      .mission-main {
        position: relative;
        min-width: 0;
        padding: 34px 42px 80px;
      }

      .loading-panel {
        min-height: 420px;
        display: grid;
        place-items: center;
        color: #b7c0cd;
      }

      .dots {
        width: 100px;
        height: 8px;
        border-radius: 999px;
        background: repeating-linear-gradient(90deg, #57c7df 0 8px, transparent 8px 16px);
        margin-bottom: 18px;
      }

      .mission-hero {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 24px;
        margin-bottom: 26px;
      }

      .eyebrow,
      .priority-kind,
      .panel header span {
        display: block;
        color: #f4d273;
        font-family: var(--ck-font-mono);
        font-size: 11px;
        text-transform: uppercase;
      }

      .mission-hero h1 {
        margin: 6px 0 4px;
        font-size: clamp(32px, 5vw, 56px);
        line-height: 1;
      }

      .mission-hero p,
      .priority-card p,
      .panel p,
      .briefing-section p {
        color: #a6adba;
        line-height: 1.55;
      }

      .hero-actions,
      .source-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }

      .action-button {
        min-height: 40px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 9px;
        padding: 0 16px;
        border: 1px solid rgba(244, 210, 115, 0.46);
        border-radius: 6px;
        color: #1a1407;
        background: #f4d273;
        cursor: pointer;
        font-weight: 700;
      }

      .action-button.ghost {
        color: #f4d273;
        background: rgba(244, 210, 115, 0.12);
      }

      .action-button.compact {
        min-height: 34px;
        padding: 0 12px;
        font-size: 13px;
      }

      .priorities-grid,
      .metric-strip {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 12px;
      }

      .metric-strip {
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }

      .priority-card,
      .metric-card,
      .panel {
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        background: #12151b;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.18);
      }

      .priority-card {
        min-height: 132px;
        padding: 18px;
        color: inherit;
        text-align: left;
        cursor: pointer;
      }

      .priority-card:first-child {
        background: linear-gradient(135deg, rgba(27, 91, 160, 0.34), #12151b 62%);
      }

      .priority-card.critical {
        background: linear-gradient(135deg, rgba(159, 32, 32, 0.36), #12151b 64%);
      }

      .priority-card.watch {
        background: linear-gradient(135deg, rgba(144, 105, 26, 0.34), #12151b 64%);
      }

      .priority-card strong,
      .metric-card strong,
      .panel header strong {
        display: block;
        color: #f7f7f2;
        font-size: 18px;
        line-height: 1.25;
      }

      .priority-card small,
      .metric-card small,
      .agenda-item small,
      .project-row small {
        color: #7e8795;
      }

      .metric-card {
        min-height: 96px;
        padding: 17px;
      }

      .metric-card span {
        color: #8b96a4;
        text-transform: uppercase;
        font-size: 11px;
      }

      .metric-card strong {
        margin-top: 8px;
        font-size: 32px;
      }

      .metric-card.danger strong { color: #ff5d5d; }
      .metric-card.gold strong { color: #f4d273; }
      .metric-card.blue strong { color: #64c7ef; }
      .metric-card.green strong { color: #46db7a; }

      .dashboard-grid,
      .lower-grid {
        display: grid;
        grid-template-columns: repeat(12, minmax(0, 1fr));
        gap: 12px;
      }

      .lower-grid {
        margin-top: 12px;
      }

      .panel {
        position: relative;
        min-height: 220px;
        padding: 18px;
        overflow: hidden;
      }

      .panel.wide { grid-column: span 6; }
      .ops-panel { grid-column: span 3; }
      .zones-panel { grid-column: span 6; }
      .agenda-panel { grid-column: span 3; }
      .briefing-panel { grid-column: span 5; }
      .projects-panel { grid-column: span 3; }
      .map-panel { grid-column: span 8; }
      .assistant-panel { grid-column: span 4; }

      .panel header {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 14px;
      }

      .line-chart {
        width: 100%;
        height: 180px;
      }

      .line-chart.compact {
        height: 130px;
      }

      .gridline {
        stroke: rgba(255, 255, 255, 0.08);
        stroke-width: 1;
      }

      .danger-line,
      .good-line {
        fill: none;
        stroke-width: 4;
        stroke-linecap: round;
      }

      .danger-line { stroke: #f15d5d; }
      .good-line { stroke: #46db7a; }
      .danger-area {
        fill: rgba(241, 93, 93, 0.16);
        stroke: none;
      }

      .bar-chart {
        height: 168px;
        display: flex;
        align-items: end;
        gap: 14px;
        padding: 18px 4px 0;
      }

      .bar-group {
        flex: 1 1 0;
        height: 100%;
        display: flex;
        align-items: end;
        justify-content: center;
        gap: 4px;
        position: relative;
        padding-bottom: 24px;
      }

      .bar {
        width: 14px;
        min-height: 8px;
        border-radius: 4px 4px 0 0;
      }

      .bar.institutional { background: #f4d273; }
      .bar.press { background: #4c5361; }

      .bar-group small {
        position: absolute;
        bottom: 0;
        color: #798393;
        font-size: 11px;
      }

      .donut {
        width: 128px;
        height: 128px;
        margin: 8px auto 18px;
        border-radius: 50%;
        background: conic-gradient(#46db7a 0 68%, #f4d273 68% 90%, #ff5d5d 90% 100%);
        display: grid;
        place-items: center;
      }

      .donut span {
        width: 82px;
        height: 82px;
        border-radius: 50%;
        display: grid;
        place-items: center;
        background: #12151b;
        color: #f7f7f2;
        font-size: 24px;
        font-weight: 800;
      }

      .legend-list,
      .latest-alerts {
        display: grid;
        gap: 8px;
      }

      .legend-list span {
        display: flex;
        align-items: center;
        gap: 8px;
        color: #a6adba;
        font-size: 12px;
      }

      .legend-list i {
        width: 8px;
        height: 8px;
        border-radius: 50%;
      }

      .green-dot { background: #46db7a; }
      .gold-dot { background: #f4d273; }
      .red-dot { background: #ff5d5d; }

      .zone-row,
      .project-row,
      .prompt-button,
      .latest-alerts button {
        width: 100%;
        border: 0;
        background: transparent;
        color: inherit;
        cursor: pointer;
        text-align: left;
      }

      .zone-row {
        display: grid;
        grid-template-columns: 80px minmax(0, 1fr) 52px;
        align-items: center;
        gap: 12px;
        padding: 9px 0;
      }

      .zone-row b {
        height: 6px;
        border-radius: 999px;
        min-width: 10px;
        background: #f4d273;
      }

      .zone-row b.critical { background: #ff5d5d; }
      .zone-row b.stable { background: #46db7a; }
      .zone-row strong {
        color: #a6adba;
        font-size: 12px;
      }

      .agenda-item {
        display: grid;
        grid-template-columns: 48px minmax(0, 1fr);
        gap: 12px;
        padding: 10px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      }

      .agenda-item time {
        color: #8b96a4;
        font-family: var(--ck-font-mono);
        font-size: 12px;
      }

      .agenda-item.urgent strong { color: #ffb3b3; }
      .agenda-item.watch strong { color: #f4d273; }

      .media-source {
        display: grid;
        grid-template-columns: 170px minmax(0, 1fr) 50px 34px;
        gap: 10px;
        align-items: center;
        margin: 8px 0;
        color: #a6adba;
        font-size: 13px;
      }

      .media-source b {
        height: 4px;
        border-radius: 999px;
        background: #f4d273;
      }

      .media-source strong {
        color: #46db7a;
        font-size: 12px;
      }

      .media-source small {
        color: #7e8795;
      }

      .latest-alerts {
        margin-top: 16px;
      }

      .latest-alerts button {
        display: flex;
        align-items: center;
        gap: 8px;
        color: #b9c1cc;
        font-size: 13px;
      }

      .latest-alerts span {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #f4d273;
      }

      .latest-alerts span.high { background: #ff5d5d; }

      .panel-badge {
        position: absolute;
        top: 18px;
        right: 18px;
        color: #46db7a;
        font-weight: 800;
      }

      .briefing-section {
        padding: 14px 0;
        border-top: 1px solid rgba(255, 255, 255, 0.07);
      }

      .briefing-section h3,
      .selection-card h3,
      .zone-detail h3 {
        margin: 0 0 8px;
        font-size: 17px;
      }

      .source-pills button {
        min-height: 26px;
        padding: 0 9px;
        border: 1px solid rgba(100, 199, 239, 0.26);
        border-radius: 6px;
        color: #8bdcf9;
        background: rgba(100, 199, 239, 0.08);
        cursor: pointer;
        font-size: 11px;
      }

      .project-row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 54px;
        gap: 10px;
        padding: 13px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.07);
      }

      .project-row.red strong { color: #ff8a8a; }
      .project-row.orange strong { color: #f4d273; }
      .project-row.green strong { color: #7ee29b; }

      .project-row span {
        align-self: center;
        justify-self: end;
        color: #c9d1dc;
        font-weight: 700;
      }

      .selection-card,
      .zone-detail {
        margin-top: 14px;
        padding: 14px;
        border: 1px solid rgba(244, 210, 115, 0.18);
        border-radius: 8px;
        background: rgba(244, 210, 115, 0.06);
      }

      .map-panel {
        min-height: 470px;
      }

      .map-question {
        margin-top: -4px;
      }

      .map-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.1fr) minmax(240px, 0.9fr);
        gap: 16px;
        align-items: stretch;
      }

      .territory-map {
        width: 100%;
        min-height: 360px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        background: #081015;
      }

      .territory-map polygon {
        cursor: pointer;
        transition: opacity 120ms ease, stroke 120ms ease;
      }

      .territory-map polygon:hover {
        opacity: 0.84;
      }

      .territory-map text {
        fill: #f7f7f2;
        font-size: 16px;
        font-weight: 800;
        pointer-events: none;
      }

      .zone-detail ul {
        margin: 8px 0 14px 18px;
        padding: 0;
        color: #b9c1cc;
      }

      .assistant-panel {
        min-height: 470px;
      }

      .prompt-button {
        min-height: 44px;
        margin-top: 10px;
        padding: 10px 12px;
        border: 1px solid rgba(100, 199, 239, 0.18);
        border-radius: 6px;
        color: #d8edf5;
        background: rgba(100, 199, 239, 0.06);
      }

      .draft-panel {
        position: fixed;
        right: 28px;
        top: 72px;
        width: min(520px, calc(100vw - 96px));
        max-height: calc(100vh - 120px);
        overflow: auto;
        z-index: 60;
        padding: 24px;
        border: 1px solid rgba(244, 210, 115, 0.38);
        border-radius: 8px;
        background: #12151b;
        box-shadow: 0 28px 90px rgba(0, 0, 0, 0.42);
      }

      .close-draft {
        position: absolute;
        top: 12px;
        right: 12px;
        width: 34px;
        height: 34px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 6px;
        color: #c9d1dc;
        background: rgba(255, 255, 255, 0.06);
        cursor: pointer;
      }

      .draft-panel h2 {
        margin: 10px 0 8px;
      }

      .recipient {
        color: #f4d273;
      }

      .draft-control {
        margin-top: 18px;
        display: flex;
        align-items: center;
        gap: 10px;
        color: #9de2bb;
      }

      @media (max-width: 1300px) {
        .mission-shell {
          grid-template-columns: 210px minmax(0, 1fr);
        }

        .mission-main {
          padding: 26px 24px 70px;
        }

        .priorities-grid,
        .metric-strip {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .panel.wide,
        .ops-panel,
        .zones-panel,
        .agenda-panel,
        .briefing-panel,
        .projects-panel,
        .map-panel,
        .assistant-panel {
          grid-column: span 12;
        }
      }

      @media (max-width: 860px) {
        .mission-shell {
          grid-template-columns: 1fr;
        }

        .aria-rail {
          position: relative;
          height: auto;
          flex-direction: row;
          overflow-x: auto;
          padding: 12px;
        }

        .ministerial-nav {
          flex-direction: row;
          min-width: max-content;
        }

        .demo-status,
        .rail-alerts,
        .rail-settings,
        .rail-clock {
          display: none;
        }

        .mission-hero,
        .map-grid {
          grid-template-columns: 1fr;
          display: grid;
        }

        .priorities-grid,
        .metric-strip {
          grid-template-columns: 1fr;
        }
      }
    `,
  ],
})
export class MissionRoomComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly chat = inject(ChatOverlayService);
  protected readonly workspace = inject(WorkspaceService);

  readonly loading = signal(true);
  readonly activeSection = signal('cockpit');
  readonly overview = signal<MissionOverview | null>(null);
  readonly briefing = signal<MissionBriefing | null>(null);
  readonly projects = signal<MissionProjects | null>(null);
  readonly missionMap = signal<MissionMap | null>(null);
  readonly news = signal<MissionNews | null>(null);
  readonly selectedProject = signal<Project | null>(null);
  readonly selectedZone = signal<MapZone | null>(null);
  readonly draft = signal<DraftInstruction | null>(null);

  readonly sources = computed(() => {
    const rows = [
      ...(this.overview()?.sources || []),
      ...(this.briefing()?.sources || []),
      ...(this.projects()?.sources || []),
      ...(this.missionMap()?.sources || []),
      ...(this.news()?.sources || []),
    ];
    return new Map(rows.map((source) => [source.id, source]));
  });

  readonly navItems = [
    { key: 'cockpit', label: 'Cockpit', glyph: 'ledger' as const },
    { key: 'pilotage', label: 'Pilotage', glyph: 'telemetry' as const },
    { key: 'agenda', label: 'Agenda', glyph: 'ledger' as const },
    { key: 'messages', label: 'Messages', glyph: 'layers' as const },
    { key: 'bibliotheque', label: 'Bibliotheque', glyph: 'cube' as const },
    { key: 'projets', label: 'Projets', glyph: 'flow' as const },
    { key: 'presse', label: 'Presse', glyph: 'pulse' as const },
    { key: 'reputation', label: 'E-Reputation', glyph: 'focus' as const },
    { key: 'veille', label: 'Veille', glyph: 'crosshair' as const },
    { key: 'decisions', label: 'Decisions', glyph: 'check' as const },
    { key: 'strategie', label: 'Strategie', glyph: 'sliders' as const },
    { key: 'recherche', label: 'Recherche', glyph: 'zoom-in' as const },
    { key: 'aria', label: 'ARIA', glyph: 'bolt' as const },
  ];

  ngOnInit(): void {
    forkJoin({
      overview: this.api.get<MissionOverview>('/mission-room/overview'),
      briefing: this.api.get<MissionBriefing>('/mission-room/briefing'),
      projects: this.api.get<MissionProjects>('/mission-room/projects'),
      missionMap: this.api.get<MissionMap>('/mission-room/map'),
      news: this.api.get<MissionNews>('/mission-room/news'),
    }).subscribe({
      next: ({ overview, briefing, projects, missionMap, news }) => {
        this.overview.set(overview);
        this.briefing.set(briefing);
        this.projects.set(projects);
        this.missionMap.set(missionMap);
        this.news.set(news);
        this.selectedProject.set(projects.projects[0] || null);
        this.selectedZone.set(missionMap.zones[0] || null);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  kpi(key: string): number | string {
    return this.overview()?.kpis?.[key] ?? '-';
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
    if (zone.tone === 'critical') return '#793039';
    if (zone.tone === 'watch') return '#836734';
    return '#1f6b50';
  }

  selectZoneByName(name: string): void {
    const zone = (this.missionMap()?.zones || []).find((item) => item.name === name);
    if (zone) this.selectedZone.set(zone);
    this.activeSection.set('strategie');
  }

  selectProject(project: Project): void {
    this.selectedProject.set(project);
    this.activeSection.set('projets');
  }

  focusPriority(priority: Priority): void {
    if (priority.id === 'prio-security-north') {
      this.selectZoneByName('Nord');
      return;
    }
    this.activeSection.set(priority.kind === 'mail' ? 'messages' : 'agenda');
  }

  sourceLabel(sourceId: string): string {
    return this.sources().get(sourceId)?.label || sourceId;
  }

  showSource(sourceId: string): void {
    const source = this.sources().get(sourceId);
    if (!source) return;
    this.draft.set({
      status: 'source',
      requires_validation: false,
      sent: false,
      title: source.label,
      recipient: source.kind,
      body: `Source ${source.kind}, confiance ${(source.confidence * 100).toFixed(0)}%, age ${source.age}.`,
      sources: [source.id],
      control: { audit: 'visible' },
    });
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

  private createDraft(targetId: string, targetType: string): void {
    this.api
      .post<DraftInstruction>('/mission-room/actions/draft', {
        target_id: targetId,
        target_type: targetType,
        instruction_type: 'dircab_instruction',
      })
      .subscribe((draft) => this.draft.set(draft));
  }
}
