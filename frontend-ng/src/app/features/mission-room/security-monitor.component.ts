import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { catchError, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceMapComponent } from './workspace-map.component';
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
  satellite_imagery?: SatelliteImageryPayload | null;
}

interface SatelliteImageryPayload {
  mode?: string;
  captured_at?: string;
  provider?: string;
  source_product?: string;
  attribution?: string;
  disclaimer?: string;
  scenes?: SatelliteScene[];
}

interface SatelliteScene {
  id: string;
  axis?: string;
  label?: string;
  narrative_status?: string;
  narrative_summary?: string;
  cloud_cover_pct?: number;
  resolution_m?: number;
  provider?: string;
  attribution?: string;
  thumbnail_url?: string;
  proxy_url?: string;
  asset_url?: string;
}

type SatelliteImageVariant = 'asset' | 'thumbnail';

@Component({
  selector: 'app-security-monitor',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    WorkspaceMapComponent,
    VpRumorTraceTimelineComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="security-monitor" [attr.aria-label]="i18n.t('mission.security.title')">
      <header class="sm-topbar">
        <div class="sm-brand">
          <a routerLink="/hypervisor/mission-room/securite" class="sm-back">
            <span>{{ i18n.t('mission.security.back') }}</span>
          </a>
          <span class="live-dot" aria-hidden="true"></span>
          <strong>SENTINEL-CI</strong>
          <small>{{ i18n.t('mission.security.monitor') }}</small>
        </div>

        <div class="sm-status">
          <span class="mission-status-badge is-baseline" [title]="i18n.t('mission.security.demo_mode')">{{ sourceBadgeLabel() }}</span>
          <span class="mission-status-badge is-advisory">{{ i18n.t('mission.security.advisory_only') }}</span>
          <b>{{ monitor()?.title || i18n.t('mission.security.theater_fallback') }}</b>
        </div>

        <div class="sm-council">
          <span>{{ i18n.t('mission.security.council') }}</span>
          <strong>{{ councilTime() }}</strong>
        </div>
      </header>

      <div class="sm-grid">
        <main class="sm-map-stage">
          <div class="stage-head mission-panel-head">
            <div class="mission-panel-head-copy">
              <span class="mission-panel-kicker">{{ i18n.t('mission.security.map_kicker') }}</span>
              <p class="mission-panel-subtitle">{{ monitor()?.summary || '' }}</p>
            </div>
            <span class="mission-status-badge is-watch">{{ i18n.t('mission.security.traces', { count: alertCount() }) }}</span>
          </div>

          <app-workspace-map
            class="sm-map"
            [zones]="$any(monitor()?.zones || [])"
            [map]="monitor()?.map || null"
            [mapSystem]="monitor()?.map_system || null"
            [mapState]="monitor()?.map_state || defaultMapState()"
          />

          @if (satelliteScenes().length) {
            <section
              id="satellite-imagery-rail"
              class="sm-satellite-rail"
              [attr.aria-label]="i18n.t('mission.security.satellite_rail')"
            >
              <header class="sm-satellite-head">
                <div>
                  <span class="eyebrow">{{ i18n.t('mission.security.satellite_rail') }}</span>
                  <strong>{{ i18n.t('mission.security.satellite_coverage') }}</strong>
                </div>
                <div class="sm-satellite-badges">
                  <span class="mission-status-badge is-baseline">{{ satelliteModeLabel() }}</span>
                  <span class="mission-status-badge is-advisory">{{ i18n.t('mission.security.no_auto_reading') }}</span>
                </div>
              </header>

              <div class="sm-satellite-meta">
                <span>{{ i18n.t('mission.security.captured_at', { time: satelliteCapturedLabel() }) }}</span>
                <span>{{ satelliteProviderLabel() }}</span>
              </div>

              <div class="sm-satellite-scenes">
                @for (scene of satelliteScenes(); track scene.id) {
                  <button type="button" class="sm-satellite-card" (click)="openSatelliteScene(scene)">
                    <span class="sm-satellite-thumb" aria-hidden="true">
                      @if (satelliteThumbUrl(scene); as thumbUrl) {
                        <img [src]="thumbUrl" [alt]="scene.label || i18n.t('mission.security.scene_alt')" />
                      } @else {
                        <span class="sm-satellite-thumb-placeholder">{{ i18n.t('common.loading') }}</span>
                      }
                    </span>
                    <span class="sm-satellite-copy">
                      <span class="sm-satellite-axis">{{ sceneAxisLabel(scene) }}</span>
                      <strong>{{ scene.label }}</strong>
                      <span class="sm-satellite-status">{{ sceneStatusLabel(scene) }}</span>
                      <small>
                        {{ i18n.t('mission.security.clouds') }} {{ scene.cloud_cover_pct ?? '—' }}% ·
                        {{ scene.narrative_summary || i18n.t('mission.security.osint_correlation') }}
                      </small>
                    </span>
                  </button>
                }
              </div>

              <p class="sm-satellite-note">{{ satelliteDisclaimer() }}</p>
            </section>
          }

          @if (monitor()?.disclaimer; as disclaimer) {
            <p class="sm-disclaimer">{{ disclaimer }}</p>
          }
        </main>

        <aside class="sm-adsb-rail" [attr.aria-label]="i18n.t('mission.security.adsb_rail')">
          <section class="sm-panel sm-panel-adsb">
            <header class="sm-panel-head">
              <span class="eyebrow">{{ i18n.t('mission.security.adsb_rail') }}</span>
              <strong>{{ i18n.t('mission.security.traces', { count: alertCount() }) }}</strong>
            </header>

            <div class="sm-alert-list">
              @for (alert of monitor()?.adsb_alerts || []; track alert['id'] || alert['callsign']) {
                <article class="sm-alert mission-row-highlight" [class]="'tone-' + (alert['tone'] || 'watch')">
                  <header>
                    <strong>{{ alert['callsign'] }}</strong>
                    <span>{{ alert['kind'] || i18n.t('mission.security.trace') }}</span>
                  </header>
                  <p>{{ alert['summary'] }}</p>
                  <footer>
                    <small>{{ alertRoute(alert) }}</small>
                    <span class="sm-status-chip" [class]="'tone-' + (alert['tone'] || 'watch')">{{ toneLabel(alert['tone']) }}</span>
                  </footer>
                </article>
              } @empty {
                <p class="empty-line">{{ i18n.t('mission.troops.no_tracks') }}</p>
              }
            </div>
          </section>
        </aside>

        <aside class="sm-intel-rail" [attr.aria-label]="i18n.t('mission.security.intel_rail')">
          <section class="sm-panel sm-rumor-panel">
            <header class="sm-panel-head">
              <span class="eyebrow">{{ i18n.t('mission.security.rumor_panel') }}</span>
              <span class="mission-status-badge is-denied">{{ i18n.t('mission.rumor.phase.denial') }}</span>
            </header>
            <app-vp-rumor-trace-timeline
              [embedded]="true"
              [open]="true"
              [trace]="$any(monitor()?.rumor_thread || null)"
            />
          </section>

          <section class="sm-panel sm-feed">
            <div class="sm-feed-head">
              <span class="eyebrow">{{ i18n.t('mission.security.social_panel') }} · Abidjan</span>
              <small>{{ freshnessLabel() }}</small>
            </div>
            <div class="sm-feed-grid">
              @for (item of monitor()?.social_feed || []; track item['id']) {
                <article class="sm-tweet" [class]="'kind-' + (item['kind'] || 'citoyen')">
                  <header>
                    <strong>{{ item['handle'] }}</strong>
                    <span>{{ sentimentLabel(item['sentiment']) }}</span>
                  </header>
                  <p>{{ item['text'] }}</p>
                  <small>{{ item['engagement'] }} {{ i18n.t('mission.social.engagement_short') }}</small>
                </article>
              } @empty {
                <p class="empty-line">{{ i18n.t('mission.security.no_social') }}</p>
              }
            </div>
          </section>
        </aside>
      </div>

      @if (selectedSatelliteScene(); as scene) {
        <div
          class="sm-satellite-drawer-backdrop"
          role="presentation"
          (click)="closeSatelliteScene()"
          (keydown.escape)="closeSatelliteScene()"
          tabindex="-1"
        >
          <article class="sm-satellite-drawer" role="dialog" aria-modal="true" (click)="$event.stopPropagation()">
            <header class="sm-satellite-drawer-head">
              <div>
                <span class="eyebrow">{{ i18n.t('mission.security.scene') }} · {{ sceneAxisLabel(scene) }}</span>
                <h2>{{ scene.label }}</h2>
              </div>
              <button type="button" class="sm-icon-button" [attr.aria-label]="i18n.t('common.close')" (click)="closeSatelliteScene()">×</button>
            </header>

            <div class="sm-satellite-drawer-body">
              <figure>
                @if (satelliteAssetUrl(scene); as assetUrl) {
                  <img [src]="assetUrl" [alt]="scene.label || i18n.t('mission.security.scene_alt_detail')" />
                } @else {
                  <figcaption>{{ i18n.t('mission.security.scene_loading') }}</figcaption>
                }
              </figure>

              <aside>
                <span class="mission-status-badge is-baseline">{{ satelliteModeLabel() }}</span>
                <h3>{{ sceneStatusLabel(scene) }}</h3>
                <p>{{ scene.narrative_summary || i18n.t('mission.security.osint_public_reading') }}</p>
                <dl>
                  <div>
                    <dt>{{ i18n.t('mission.security.resolution') }}</dt>
                    <dd>{{ scene.resolution_m || 10 }} m</dd>
                  </div>
                  <div>
                    <dt>{{ i18n.t('mission.security.clouds') }}</dt>
                    <dd>{{ scene.cloud_cover_pct ?? '—' }}%</dd>
                  </div>
                  <div>
                    <dt>{{ i18n.t('mission.security.capture') }}</dt>
                    <dd>{{ satelliteCapturedLabel() }}</dd>
                  </div>
                </dl>
                <p class="sm-satellite-warning">{{ satelliteDisclaimer() }}</p>
                <small>{{ satelliteAttribution() }}</small>
              </aside>
            </div>
          </article>
        </div>
      }
    </section>
  `,
  styles: [
    `
      :host {
        display: block;
        min-height: 100vh;
        background: #070d14;
        color: var(--mission-text-primary);
      }
      .security-monitor {
        display: grid;
        gap: 0;
        min-height: 100vh;
      }
      .sm-topbar {
        position: sticky;
        top: 0;
        z-index: 20;
        display: grid;
        grid-template-columns: minmax(260px, 1.15fr) minmax(280px, 1fr) auto;
        gap: 16px;
        align-items: center;
        padding: 14px 20px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        background: rgba(6, 12, 18, 0.96);
      }
      .sm-brand {
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
      }
      .sm-brand strong {
        color: var(--mission-text-primary);
        letter-spacing: 0.05em;
      }
      .sm-brand small {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.09em;
        text-transform: uppercase;
      }
      .sm-back {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.58);
        color: var(--mission-text-secondary);
        text-decoration: none;
      }
      .sm-back::before { content: '←'; }
      .sm-back:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .live-dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--mission-warning);
        box-shadow: 0 0 8px rgba(241, 180, 90, 0.5);
      }
      .sm-status {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 6px 8px;
      }
      .sm-status b {
        flex: 1 0 100%;
        color: var(--mission-text-primary);
        font-size: var(--mission-text-sm);
      }
      .sm-council {
        text-align: right;
        padding: 8px 12px;
        border: 1px solid rgba(240, 100, 118, 0.35);
        border-radius: var(--mission-radius-md);
        background: rgba(240, 100, 118, 0.08);
      }
      .sm-council span {
        display: block;
        color: var(--mission-text-secondary);
        font-size: 11px;
      }
      .sm-council strong {
        color: #fda4af;
        font-size: 18px;
      }
      .sm-grid {
        display: grid;
        grid-template-columns: minmax(560px, 2.1fr) minmax(260px, 0.82fr) minmax(300px, 0.95fr);
        grid-template-rows: minmax(0, 1fr);
        gap: 16px;
        min-height: calc(100vh - 72px);
        padding: 16px 20px 24px;
      }
      .sm-map-stage {
        display: grid;
        grid-template-rows: auto minmax(420px, 1fr) auto auto;
        gap: 12px;
        min-height: 0;
        padding: 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-lg);
        background: rgba(8, 14, 20, 0.62);
      }
      .sm-map {
        display: block;
        min-height: 590px;
        height: 100%;
        overflow: hidden;
        border-radius: var(--mission-radius-md);
      }
      .sm-disclaimer {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: 12px;
      }
      .sm-satellite-rail {
        display: grid;
        gap: 9px;
        padding: 12px;
        border: 1px solid rgba(125, 211, 252, 0.2);
        border-radius: var(--mission-radius-md);
        background:
          linear-gradient(135deg, rgba(14, 165, 233, 0.08), rgba(15, 23, 42, 0.4)),
          rgba(4, 9, 14, 0.72);
      }
      .sm-satellite-head,
      .sm-satellite-meta,
      .sm-satellite-badges {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }
      .sm-satellite-head strong {
        color: var(--mission-text-primary);
        font-size: 14px;
      }
      .sm-satellite-badges {
        justify-content: flex-end;
        flex-wrap: wrap;
      }
      .sm-satellite-meta {
        justify-content: flex-start;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .sm-satellite-scenes {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .sm-satellite-card {
        display: grid;
        grid-template-columns: 120px minmax(0, 1fr);
        gap: 10px;
        width: 100%;
        padding: 8px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: var(--mission-radius-md);
        background: rgba(255, 255, 255, 0.035);
        color: inherit;
        text-align: left;
        cursor: pointer;
      }
      .sm-satellite-card:hover,
      .sm-satellite-card:focus-visible {
        border-color: rgba(125, 211, 252, 0.44);
        outline: none;
        background: rgba(125, 211, 252, 0.06);
      }
      .sm-satellite-thumb {
        display: grid;
        place-items: center;
        min-height: 74px;
        overflow: hidden;
        border-radius: var(--mission-radius-sm);
        background: rgba(15, 23, 42, 0.85);
      }
      .sm-satellite-thumb img,
      .sm-satellite-drawer figure img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .sm-satellite-thumb-placeholder {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        text-transform: uppercase;
      }
      .sm-satellite-copy {
        display: grid;
        align-content: center;
        gap: 3px;
        min-width: 0;
      }
      .sm-satellite-copy strong {
        color: var(--mission-text-primary);
        font-size: 13px;
      }
      .sm-satellite-axis,
      .sm-satellite-status {
        color: var(--mission-text-secondary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .sm-satellite-status {
        color: var(--mission-success);
      }
      .sm-satellite-copy small,
      .sm-satellite-note {
        color: var(--mission-text-secondary);
        font-size: 11px;
        line-height: 1.35;
      }
      .sm-satellite-note {
        margin: 0;
      }
      .sm-satellite-drawer-backdrop {
        position: fixed;
        inset: 0;
        z-index: 80;
        display: grid;
        place-items: center;
        padding: 28px;
        background: rgba(2, 6, 12, 0.72);
      }
      .sm-satellite-drawer {
        width: min(1120px, 96vw);
        max-height: min(820px, 92vh);
        overflow: hidden;
        border: 1px solid rgba(125, 211, 252, 0.2);
        border-radius: var(--mission-radius-lg);
        background: #081018;
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
      }
      .sm-satellite-drawer-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 16px 18px;
        border-bottom: 1px solid var(--mission-border);
      }
      .sm-satellite-drawer h2,
      .sm-satellite-drawer h3 {
        margin: 0;
        color: var(--mission-text-primary);
      }
      .sm-icon-button {
        width: 34px;
        height: 34px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(255, 255, 255, 0.04);
        color: var(--mission-text-primary);
        font-size: 22px;
        line-height: 1;
        cursor: pointer;
      }
      .sm-icon-button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .sm-satellite-drawer-body {
        display: grid;
        grid-template-columns: minmax(0, 1.7fr) minmax(260px, 0.75fr);
        gap: 16px;
        padding: 16px;
      }
      .sm-satellite-drawer figure {
        display: grid;
        place-items: center;
        min-height: 460px;
        margin: 0;
        overflow: hidden;
        border-radius: var(--mission-radius-md);
        background: rgba(15, 23, 42, 0.9);
      }
      .sm-satellite-drawer aside {
        display: grid;
        align-content: start;
        gap: 12px;
        color: var(--mission-text-secondary);
      }
      .sm-satellite-drawer dl {
        display: grid;
        gap: 8px;
        margin: 0;
      }
      .sm-satellite-drawer dl div {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--mission-border);
      }
      .sm-satellite-drawer dt,
      .sm-satellite-drawer small {
        color: var(--mission-text-tertiary);
      }
      .sm-satellite-drawer dd {
        margin: 0;
        color: var(--mission-text-primary);
        font-family: var(--mission-font-mono);
      }
      .sm-satellite-warning {
        margin: 0;
        padding: 10px;
        border-left: 3px solid rgba(241, 180, 90, 0.72);
        border-radius: var(--mission-radius-sm);
        background: rgba(241, 180, 90, 0.08);
      }
      .sm-adsb-rail,
      .sm-intel-rail {
        display: grid;
        align-content: start;
        gap: 12px;
        min-height: 0;
        max-height: calc(100vh - 112px);
        overflow: auto;
      }
      .sm-panel {
        padding: 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-lg);
        background: rgba(8, 14, 20, 0.72);
      }
      .sm-panel-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 10px;
      }
      .sm-panel-head strong {
        color: var(--mission-text-primary);
        font-family: var(--mission-font-mono);
        font-size: 12px;
        font-variant-numeric: tabular-nums;
      }
      .sm-alert-list { display: grid; gap: 8px; }
      .sm-alert {
        padding: 10px 12px;
        border-radius: var(--mission-radius-md);
      }
      .sm-alert.tone-stable { border-left-color: rgba(63, 209, 141, 0.65); }
      .sm-alert.tone-critical { border-left-color: rgba(240, 100, 118, 0.68); }
      .sm-alert header,
      .sm-alert footer {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
      }
      .sm-alert header span,
      .sm-alert footer small {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .sm-alert p {
        margin: 6px 0;
        color: var(--mission-text-secondary);
        font-size: 12px;
        line-height: 1.42;
      }
      .sm-rumor-panel {
        padding-bottom: 0;
        overflow: hidden;
      }
      .sm-rumor-panel app-vp-rumor-trace-timeline {
        display: block;
        margin: 0 -14px;
      }
      .sm-feed-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 10px;
      }
      .sm-feed-head small {
        color: var(--mission-text-tertiary);
        font-size: 11px;
      }
      .sm-feed-grid {
        display: grid;
        gap: 8px;
        max-height: 300px;
        overflow: auto;
      }
      .sm-tweet {
        padding: 10px;
        border-left: 3px solid rgba(148, 163, 184, 0.5);
        border-radius: var(--mission-radius-md);
        background: rgba(255, 255, 255, 0.03);
      }
      .sm-tweet.kind-rumeur { border-left-color: rgba(240, 100, 118, 0.65); }
      .sm-tweet.kind-officiel { border-left-color: rgba(101, 214, 110, 0.65); }
      .sm-tweet header {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        font-size: 12px;
      }
      .sm-tweet header span {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        text-transform: uppercase;
      }
      .sm-tweet p {
        margin: 6px 0;
        font-size: 13px;
        line-height: 1.38;
      }
      .sm-tweet small {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
      }
      .sm-status-chip {
        display: inline-flex;
        padding: 2px 7px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        color: var(--mission-text-secondary);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        text-transform: uppercase;
      }
      .sm-status-chip.tone-watch {
        border-color: rgba(241, 180, 90, 0.42);
        color: var(--mission-warning);
      }
      .sm-status-chip.tone-stable {
        border-color: rgba(63, 209, 141, 0.42);
        color: var(--mission-success);
      }
      .sm-status-chip.tone-critical {
        border-color: rgba(240, 100, 118, 0.42);
        color: var(--mission-critical);
      }
      .eyebrow {
        display: block;
        margin-bottom: 6px;
        color: var(--mission-text-secondary);
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .empty-line {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: 13px;
      }
      @media (max-width: 1240px) {
        .sm-grid {
          grid-template-columns: minmax(0, 1.5fr) minmax(300px, 0.9fr);
        }
        .sm-intel-rail {
          grid-column: 1 / -1;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
      }
      @media (max-width: 900px) {
        .sm-topbar,
        .sm-grid,
        .sm-intel-rail,
        .sm-satellite-scenes,
        .sm-satellite-drawer-body {
          grid-template-columns: 1fr;
        }
        .sm-council { text-align: left; }
        .sm-map { min-height: 430px; }
        .sm-satellite-card {
          grid-template-columns: 104px minmax(0, 1fr);
        }
        .sm-satellite-drawer figure {
          min-height: 320px;
        }
        .sm-adsb-rail,
        .sm-intel-rail {
          max-height: none;
          overflow: visible;
        }
      }
    `,
  ],
})
export class SecurityMonitorComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  readonly i18n = inject(I18nService);
  private readonly satelliteObjectUrls = new Map<string, string>();

  readonly monitor = signal<SecurityMonitorPayload | null>(null);
  readonly loading = signal(true);
  readonly satelliteThumbUrls = signal<Record<string, string>>({});
  readonly satelliteAssetUrls = signal<Record<string, string>>({});
  readonly satelliteLoading = signal<Record<string, boolean>>({});
  readonly selectedSatelliteScene = signal<SatelliteScene | null>(null);

  ngOnInit(): void {
    this.api
      .get<SecurityMonitorPayload>('/mission-room/security-monitor')
      .pipe(catchError(() => of(null)))
      .subscribe((payload) => {
        this.monitor.set(payload);
        this.loading.set(false);
        this.preloadSatelliteThumbnails(payload);
      });
  }

  ngOnDestroy(): void {
    for (const url of this.satelliteObjectUrls.values()) {
      URL.revokeObjectURL(url);
    }
    this.satelliteObjectUrls.clear();
  }

  councilTime(): string {
    const council = (this.monitor()?.security_posture as Record<string, unknown> | null)?.['next_council'] as Record<string, unknown> | undefined;
    return String(council?.['time'] || '15:00');
  }

  freshnessLabel(): string {
    const fresh = this.monitor()?.source_freshness;
    return String(fresh?.['social'] || this.i18n.t('mission.security.snapshot_demo_safe'));
  }

  sourceBadgeLabel(): string {
    const snapshot = this.monitor()?.theater_sahel as Record<string, unknown> | null;
    const raw = String(snapshot?.['source_badge'] || 'CACHE BASELINE').toLowerCase();
    return raw.includes('live') ? this.i18n.t('mission.security.live') : this.i18n.t('mission.security.baseline');
  }

  alertCount(): number {
    return this.monitor()?.adsb_alerts?.length || 0;
  }

  alertRoute(alert: Record<string, unknown>): string {
    const origin = String(alert['origin'] || '');
    const destination = String(alert['destination'] || '');
    if (origin || destination) return `${origin || '—'} → ${destination || '—'}`;
    return this.i18n.t('mission.security.route_fallback');
  }

  toneLabel(tone: unknown): string {
    const key = String(tone || '').toLowerCase();
    if (key === 'critical') return this.i18n.t('mission.troops.tone.critical');
    if (key === 'stable') return this.i18n.t('mission.troops.tone.stable');
    return this.i18n.t('mission.troops.tone.watch');
  }

  sentimentLabel(value: unknown): string {
    const key = String(value || '').toLowerCase();
    if (key === 'positive') return this.i18n.t('mission.social.sentiment.positive');
    if (key === 'negative') return this.i18n.t('mission.social.sentiment.negative');
    if (key === 'neutral') return this.i18n.t('mission.social.sentiment.neutral');
    return key || this.i18n.t('mission.social.sentiment.neutral');
  }

  defaultMapState(): Record<string, unknown> {
    return {
      preset: 'sahel',
      zoom: 'regional',
      basemap: 'satellite',
      active_layers: ['military-air', 'border-tension', 'satellite-footprint', 'regional-context'],
    };
  }

  satelliteScenes(): SatelliteScene[] {
    return this.monitor()?.satellite_imagery?.scenes || [];
  }

  satelliteModeLabel(): string {
    const mode = String(this.monitor()?.satellite_imagery?.mode || 'cache_baseline').toLowerCase();
    return mode.includes('live') ? 'LIVE' : 'CACHE BASELINE';
  }

  satelliteCapturedLabel(): string {
    const raw = this.monitor()?.satellite_imagery?.captured_at;
    if (!raw) return '06:40 UTC';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return String(raw);
    const hour = String(date.getUTCHours()).padStart(2, '0');
    const minute = String(date.getUTCMinutes()).padStart(2, '0');
    return `${hour}:${minute} UTC`;
  }

  satelliteProviderLabel(): string {
    const sat = this.monitor()?.satellite_imagery;
    return String(sat?.source_product || sat?.provider || 'Copernicus Sentinel-2 baseline');
  }

  satelliteDisclaimer(): string {
    return String(
      this.monitor()?.satellite_imagery?.disclaimer ||
        this.i18n.t('mission.security.satellite_disclaimer'),
    );
  }

  satelliteAttribution(): string {
    return String(
      this.monitor()?.satellite_imagery?.attribution ||
        'Contains modified Copernicus Sentinel data via Sentinel-2 cloudless (EOX)',
    );
  }

  satelliteThumbUrl(scene: SatelliteScene): string | null {
    return this.satelliteThumbUrls()[scene.id] || null;
  }

  satelliteAssetUrl(scene: SatelliteScene): string | null {
    return this.satelliteAssetUrls()[scene.id] || null;
  }

  sceneAxisLabel(scene: SatelliteScene): string {
    return String(scene.axis || '').toLowerCase() === 'exterieur'
      ? this.i18n.t('mission.security.axis_exterior')
      : this.i18n.t('mission.security.axis_interior');
  }

  sceneStatusLabel(scene: SatelliteScene): string {
    const status = String(scene.narrative_status || '').toLowerCase();
    if (status === 'no_anomaly_confirmed') return this.i18n.t('mission.security.status.no_anomaly');
    if (status === 'context_only') return this.i18n.t('mission.security.status.context_only');
    return this.i18n.t('mission.security.advisory_only');
  }

  openSatelliteScene(scene: SatelliteScene): void {
    this.selectedSatelliteScene.set(scene);
    this.loadSatelliteImage(scene, 'asset');
  }

  closeSatelliteScene(): void {
    this.selectedSatelliteScene.set(null);
  }

  private preloadSatelliteThumbnails(payload: SecurityMonitorPayload | null): void {
    for (const scene of payload?.satellite_imagery?.scenes || []) {
      this.loadSatelliteImage(scene, 'thumbnail');
    }
  }

  private loadSatelliteImage(scene: SatelliteScene, variant: SatelliteImageVariant): void {
    const target = variant === 'thumbnail' ? this.satelliteThumbUrls : this.satelliteAssetUrls;
    if (!scene.id || target()[scene.id]) return;

    const key = `${scene.id}:${variant}`;
    if (this.satelliteLoading()[key]) return;
    this.satelliteLoading.update((state) => ({ ...state, [key]: true }));

    this.api
      .getBlob(this.satelliteProxyPath(scene, variant))
      .pipe(catchError(() => of(null)))
      .subscribe((blob) => {
        this.satelliteLoading.update((state) => ({ ...state, [key]: false }));
        if (!blob) return;
        const previous = target()[scene.id];
        if (previous) URL.revokeObjectURL(previous);
        const objectUrl = URL.createObjectURL(blob);
        this.satelliteObjectUrls.set(key, objectUrl);
        target.update((state) => ({ ...state, [scene.id]: objectUrl }));
      });
  }

  private satelliteProxyPath(scene: SatelliteScene, variant: SatelliteImageVariant): string {
    const raw =
      variant === 'thumbnail'
        ? scene.thumbnail_url
        : scene.asset_url || scene.proxy_url;
    const fallback = `/mission-room/satellite/proxy?scene_id=${encodeURIComponent(scene.id)}&variant=${variant}`;
    const path = raw || fallback;
    return path.startsWith('/api/v1') ? path.slice('/api/v1'.length) : path;
  }
}
