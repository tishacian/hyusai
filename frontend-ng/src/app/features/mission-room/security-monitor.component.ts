import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { catchError, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { WorkspaceMapComponent } from './workspace-map.component';
import { VpTroopsTheaterDrawerComponent } from './vp-troops-theater-drawer.component';
import { VpRumorTraceTimelineComponent } from './vp-rumor-trace-timeline.component';

interface SecurityMonitorPayload {
  title?: string;
  summary?: string;
  map?: Record<string, unknown> | null;
  map_system?: Record<string, unknown> | null;
  map_state?: Record<string, unknown> | null;
  zones?: Record<string, unknown>[];
  theater_sahel?: Record<string, unknown> | null;
  social_signals?: Record<string, unknown> | null;
  rumor_thread?: Record<string, unknown> | null;
  security_posture?: Record<string, unknown> | null;
  adsb_alerts?: Record<string, unknown>[];
  social_feed?: Record<string, unknown>[];
  source_freshness?: Record<string, unknown> | null;
  disclaimer?: string;
  layers?: Record<string, unknown>[];
}

@Component({
  selector: 'app-security-monitor',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    WorkspaceMapComponent,
    VpTroopsTheaterDrawerComponent,
    VpRumorTraceTimelineComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="security-monitor" aria-label="Security Monitor Sahel">
      <header class="sm-topbar">
        <div class="sm-brand">
          <a routerLink="/hypervisor/mission-room/securite" class="sm-back">
            <span>← Securite</span>
          </a>
          <span class="live-dot"></span>
          <strong>SENTINEL-CI</strong>
          <small>Security Monitor</small>
        </div>
        <div class="sm-status">
          <span class="baseline-badge">CACHE BASELINE</span>
          <b>{{ monitor()?.title || 'Theatre Sahel' }}</b>
        </div>
        <div class="sm-council">
          <span>Conseil Defense restreint</span>
          <strong>{{ councilTime() }}</strong>
        </div>
      </header>

      <div class="sm-grid">
        <main class="sm-map-stage">
          <div class="stage-head">
            <span class="eyebrow">Carte Sahel · ADS-B advisory + tension frontiere</span>
            <p>{{ monitor()?.summary || '' }}</p>
          </div>
          <app-workspace-map
            class="sm-map"
            [zones]="$any(monitor()?.zones || [])"
            [map]="monitor()?.map || null"
            [mapSystem]="monitor()?.map_system || null"
            [mapState]="monitor()?.map_state || defaultMapState()"
          />
          @if (monitor()?.disclaimer; as disclaimer) {
            <p class="sm-disclaimer">{{ disclaimer }}</p>
          }
        </main>

        <aside class="sm-side">
          <section class="sm-panel">
            <span class="eyebrow">Alertes ADS-B</span>
            @for (alert of monitor()?.adsb_alerts || []; track alert['id']) {
              <article class="sm-alert" [class]="'tone-' + (alert['tone'] || 'watch')">
                <strong>{{ alert['callsign'] }}</strong>
                <small>{{ alert['kind'] }}</small>
                <p>{{ alert['summary'] }}</p>
              </article>
            } @empty {
              <p class="empty-line">Aucune trace ADS-B dans le snapshot.</p>
            }
          </section>

          <section class="sm-panel sm-rumor-panel">
            <span class="eyebrow">Fil rumeur frontiere Nord</span>
            <app-vp-rumor-trace-timeline
              [embedded]="true"
              [open]="true"
              [trace]="monitor()?.rumor_thread || null"
            />
          </section>
        </aside>

        <footer class="sm-feed">
          <div class="sm-feed-head">
            <span class="eyebrow">Signaux sociaux · snapshot Abidjan</span>
            <small>{{ freshnessLabel() }}</small>
          </div>
          <div class="sm-feed-grid">
            @for (item of monitor()?.social_feed || []; track item['id']) {
              <article class="sm-tweet" [class]="'kind-' + (item['kind'] || 'citoyen')">
                <header>
                  <strong>{{ item['handle'] }}</strong>
                  <span>{{ item['sentiment'] }}</span>
                </header>
                <p>{{ item['text'] }}</p>
                <small>{{ item['engagement'] }} eng.</small>
              </article>
            }
          </div>
        </footer>
      </div>

      @if (monitor()?.theater_sahel; as troops) {
        <section class="sm-troops-inline">
          <app-vp-troops-theater-drawer
            [embedded]="true"
            [open]="true"
            [snapshot]="troops"
          />
        </section>
      }
    </section>
  `,
  styles: [
    `
      :host { display: block; min-height: 100vh; background: #070d14; color: var(--mission-text-primary); }
      .security-monitor { display: grid; gap: 0; min-height: 100vh; }
      .sm-topbar {
        display: grid;
        grid-template-columns: 1.2fr 1fr auto;
        gap: 16px;
        align-items: center;
        padding: 14px 20px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        background: rgba(6, 12, 18, 0.96);
        position: sticky;
        top: 0;
        z-index: 20;
      }
      .sm-brand { display: flex; align-items: center; gap: 10px; }
      .sm-back {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: var(--mission-text-secondary);
        text-decoration: none;
        margin-right: 8px;
      }
      .live-dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: #f59e0b;
        box-shadow: 0 0 8px rgba(245, 158, 11, 0.5);
      }
      .sm-status { display: flex; flex-direction: column; gap: 4px; }
      .baseline-badge {
        display: inline-flex;
        width: fit-content;
        padding: 2px 8px;
        border-radius: 999px;
        background: rgba(245, 158, 11, 0.15);
        color: #fbbf24;
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .sm-council {
        text-align: right;
        padding: 8px 12px;
        border: 1px solid rgba(240, 100, 118, 0.35);
        border-radius: 8px;
        background: rgba(240, 100, 118, 0.08);
      }
      .sm-council span { display: block; font-size: 11px; color: var(--mission-text-secondary); }
      .sm-council strong { font-size: 18px; color: #fda4af; }
      .sm-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.8fr);
        grid-template-rows: minmax(420px, 1fr) auto;
        gap: 16px;
        padding: 16px 20px 24px;
      }
      .sm-map-stage {
        grid-row: 1 / span 2;
        display: grid;
        grid-template-rows: auto 1fr auto;
        gap: 10px;
        min-height: 0;
      }
      .sm-map { display: block; min-height: 520px; height: 100%; border-radius: 12px; overflow: hidden; }
      .sm-disclaimer {
        margin: 0;
        font-size: 12px;
        color: var(--mission-text-secondary);
      }
      .sm-side { display: grid; gap: 12px; align-content: start; max-height: calc(100vh - 120px); overflow: auto; }
      .sm-panel {
        padding: 14px;
        border: 1px solid var(--mission-border);
        border-radius: 12px;
        background: rgba(8, 14, 20, 0.72);
      }
      .sm-alert {
        padding: 10px 12px;
        border-left: 3px solid rgba(245, 158, 11, 0.65);
        border-radius: 8px;
        background: rgba(255,255,255,0.03);
        margin-top: 8px;
      }
      .sm-alert p { margin: 4px 0 0; font-size: 12px; color: var(--mission-text-secondary); }
      .sm-feed {
        grid-column: 2;
        padding: 14px;
        border: 1px solid var(--mission-border);
        border-radius: 12px;
        background: rgba(8, 14, 20, 0.72);
      }
      .sm-feed-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
      .sm-feed-grid { display: grid; gap: 8px; max-height: 220px; overflow: auto; }
      .sm-tweet {
        padding: 10px;
        border-radius: 8px;
        background: rgba(255,255,255,0.03);
        border-left: 3px solid rgba(148, 163, 184, 0.5);
      }
      .sm-tweet.kind-rumeur { border-left-color: rgba(240, 100, 118, 0.65); }
      .sm-tweet.kind-officiel { border-left-color: rgba(101, 214, 110, 0.65); }
      .sm-tweet header { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; }
      .sm-tweet p { margin: 6px 0; font-size: 13px; }
      .sm-troops-inline { padding: 0 20px 24px; }
      .eyebrow {
        display: block;
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--mission-text-secondary);
        margin-bottom: 6px;
      }
      .empty-line { color: var(--mission-text-secondary); font-size: 13px; }
      @media (max-width: 1100px) {
        .sm-grid { grid-template-columns: 1fr; grid-template-rows: auto; }
        .sm-map-stage { grid-row: auto; }
        .sm-feed { grid-column: 1; }
      }
    `,
  ],
})
export class SecurityMonitorComponent implements OnInit {
  private readonly api = inject(ApiService);

  readonly monitor = signal<SecurityMonitorPayload | null>(null);
  readonly loading = signal(true);

  ngOnInit(): void {
    this.api
      .get<SecurityMonitorPayload>('/mission-room/security-monitor')
      .pipe(catchError(() => of(null)))
      .subscribe((payload) => {
        this.monitor.set(payload);
        this.loading.set(false);
      });
  }

  councilTime(): string {
    const council = (this.monitor()?.security_posture as Record<string, unknown> | null)?.['next_council'] as Record<string, unknown> | undefined;
    return String(council?.['time'] || '15:00');
  }

  freshnessLabel(): string {
    const fresh = this.monitor()?.source_freshness;
    return String(fresh?.['social'] || 'Snapshot demo-safe');
  }

  defaultMapState(): Record<string, unknown> {
    return {
      preset: 'sahel',
      zoom: 'regional',
      active_layers: ['military-air', 'border-tension', 'regional-context'],
    };
  }
}
