import { HypervisorAutomationComponent } from './hypervisor-automation.component';
import { OperationalObjectiveComponent } from '@app/features/systems/operational-objective.component';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription, forkJoin, of, type Observable } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import {
  CanonicalApiService,
  type Capability,
  type DecisionRow,
  type HypervisorSignal,
  type HypervisorValueBasisItem,
  type HypervisorValueBasisStatus,
  type Recommendation,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { isHypervisorFacet, type HypervisorFacetId, type NavLinkInput } from '@app/core/navigation.catalog';
import {
  CkChartMiniAreaComponent,
  CkChartPulseComponent,
  CkChartRadialDaysComponent,
  CkChartSankeyFlowComponent,
  CkChartStreamComponent,
  CkChartTipComponent,
  CkChartUnitDotsComponent,
  CkPanelComponent,
  FilterChipComponent,
  KbdComponent,
  NavLinkDirective,
  PageFrameComponent,
  TagComponent,
  type CkChartTick,
  type CkChartTipLine,
  type CkChartTone,
  type CkRadialDay,
  type CkSankeySource,
  type CkStreamPeak,
  type CkStreamSeries,
} from '@app/shared/cockpit';
import {
  arrivalProvenanceLabel,
  arrivalProvenanceState,
  readArrivalProvenance,
  type ArrivalProvenance,
} from '@app/shared/cockpit/arrival-provenance';
import { easeOutProgress, prefersReducedMotion } from '@app/shared/cockpit/charts/chart-interact';
import {
  STALE_AFTER_DAYS,
  availableNumber,
  projectSeries,
  sortRegisterRows,
  type HypervisorChartTick,
  type HypervisorDenominator,
  type HypervisorNativeUnit,
  type HypervisorRegisterRow,
  type HypervisorSeriesResponse,
  type HypervisorSeriesView,
  type SeriesFact,
} from './hypervisor-v2-series';
import {
  COMPRENDRE_BLOCKS,
  DECIDER_BLOCKS,
  DEFAULT_HYPERVISOR_VIEWS,
  DETAILLER_BLOCKS,
  IMPACT_GENERIC_VIEWS,
  REGISTER_COLUMNS,
  VIEW_SORTS,
  cloneView,
  impactGenericView,
  isImpactViewId,
  moveStratumBlock,
  parseImpactViewQuery,
  parseViewsPayload,
  removeStratumBlock,
  replaceView,
  serializeViewsForWrite,
  showsBlock,
  showsColumn,
  toggleRegisterColumn,
  toggleStratumBlock,
  viewDenominator,
  viewPeriod,
  type HypervisorBlockRef,
  type HypervisorNamedView,
  type HypervisorStratumId,
  type HypervisorViewDenominator,
  type ImpactViewId,
} from './hypervisor-v2-views';
import {
  LOADING_SOURCES,
  impactPageProblem,
  impactSourceRequests,
  settleSource,
  withSourceState,
  type ImpactSourceId,
  type ImpactSourceState,
  type ImpactSourceStates,
  type ImpactSourceValues,
  type SourceOutcome,
} from './impact-sources';
import { ImpactBlockAlertesComponent } from './blocks/impact-block-alertes.component';
import { ImpactBlockCarteComponent } from './blocks/impact-block-carte.component';
import { ImpactBlockEcheancierComponent } from './blocks/impact-block-echeancier.component';
import { ImpactBlockFluxComponent } from './blocks/impact-block-flux.component';
import { ImpactBlockIndicateursComponent } from './blocks/impact-block-indicateurs.component';
import { ImpactBlockOrdreDuJourComponent } from './blocks/impact-block-ordre-du-jour.component';
import {
  mapAgendaMetadataToOrdre,
  mapDecisionsToOrdre,
  mapMacroToIndicateurs,
  mapMapToZones,
  mapMonitorToAlertes,
  mapNewsToFlux,
  mapRegisterToIndicateurs,
  mapSignalsToAlertes,
  mapTimelineToEcheancier,
  type ImpactMacroRaw,
  type ImpactMapRaw,
  type ImpactMonitorRaw,
  type ImpactNewsRaw,
  type ImpactTimelineRaw,
} from './impact-block-data';

interface BasisDraft {
  unit: string;
  hours_per_unit: string;
  value_per_unit: string;
  currency: string;
  status: HypervisorValueBasisStatus;
  note: string;
}

interface RecommendationGroup {
  item: Recommendation;
  count: number;
}

/** Provenance marks: measured, declared/estimated, missing. */
const MARK_MEASURED = '●';
const MARK_DECLARED = '◐';
const MARK_NONE = '○';
const MAX_UNIT_DOTS = 24;
const NICE_DOT_STEPS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000];

function humanizeOutputUnit(unit: string | null | undefined, fallback: string): string {
  const raw = (unit ?? '').trim();
  return raw ? raw.replace(/_/g, ' ') : fallback;
}

@Component({
  selector: 'app-hypervisor-v2',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[class.hv2-enter]': 'entering()',
    '[class.hv2-theme-presentation]': 'presentationTheme()',
    '[attr.data-testid]': '"hypervisor-v2"',
  },
  imports: [
    NgTemplateOutlet,
    PageFrameComponent,
    HypervisorAutomationComponent,
    OperationalObjectiveComponent,
    NavLinkDirective,
    KbdComponent,
    TagComponent,
    FilterChipComponent,
    CkPanelComponent,
    CkChartRadialDaysComponent,
    CkChartSankeyFlowComponent,
    CkChartStreamComponent,
    CkChartMiniAreaComponent,
    CkChartUnitDotsComponent,
    CkChartPulseComponent,
    CkChartTipComponent,
    ImpactBlockEcheancierComponent,
    ImpactBlockFluxComponent,
    ImpactBlockCarteComponent,
    ImpactBlockAlertesComponent,
    ImpactBlockOrdreDuJourComponent,
    ImpactBlockIndicateursComponent,
  ],
  template: `
    @if (presentationTheme()) {
      <div class="hv2-presentation-liseré" aria-hidden="true" data-testid="hypervisor-presentation-lisere"></div>
    }
    <p class="sr-only" role="status" aria-live="polite" data-testid="hypervisor-v2-source-announcer">{{ sourceAnnouncement() }}</p>
    <ck-page-frame
      [eyebrow]="pageEyebrow()"
      [title]="pageTitle()"
      [description]="presentationTheme() ? '' : pageSummary()"
    >
      @if (arrivalChipLabel(); as chip) {
        <ck-filter-chip
          kind="provenance"
          [label]="chip"
          [href]="arrivalBackHref()"
          testId="impact-arrival-provenance"
          (navigate)="onArrivalBack()"
        />
      }
      <div actions class="hv2-actions">
        @if (presentationTheme()) {
          <button
            type="button"
            class="hv2-text-btn"
            data-testid="hypervisor-quit-presentation"
            (click)="exitPresentationTheme()"
          >
            {{ i18n.t('hypervisor.v2.theme.quit') }}
            <ck-kbd>{{ i18n.t('hypervisor.v2.theme.quit_kbd') }}</ck-kbd>
          </button>
        } @else {
          <div class="hv2-switch" role="tablist">
            @for (view of switcherViews(); track view.id) {
              <button
                type="button"
                role="tab"
                class="ck-mono"
                [attr.data-testid]="'hypervisor-v2-view-' + view.id"
                [attr.aria-selected]="view.id === switcherActiveId()"
                [class.hv2-switch-on]="view.id === switcherActiveId()"
                (click)="selectSwitcherView(view.id)"
              >{{ viewLabel(view) }}</button>
            }
          </div>
          <button
            type="button"
            class="hv2-text-btn"
            data-testid="hypervisor-enter-presentation"
            (click)="enterPresentationTheme()"
          >
            {{ i18n.t('hypervisor.v2.theme.present') }}
          </button>
          <button type="button" class="hv2-text-btn" (click)="customizeOpen.set(true)">
            {{ i18n.t('hypervisor.v2.customize') }}
            <ck-kbd>⌘E</ck-kbd>
          </button>
        }
      </div>

      @if (loading()) {
        <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.loading') }}</p>
      } @else if (loadProblem(); as problem) {
        <section role="alert">
          <p>{{ i18n.t(problem) }}</p>
          <div style="display:flex;align-items:center;gap:16px;margin-top:12px">
            <button type="button" style="padding:8px 16px;border:1px solid var(--ck-stroke-2);border-radius:4px" (click)="reload()">{{ i18n.t('common.retry') }}</button>
            <a style="text-decoration:underline" [navLink]="{ leaf: 'help-guide', ref: 'value' }">{{ i18n.t('experience.adoption.help') }}</a>
          </div>
        </section>
      } @else {
        <div data-testid="hypervisor-v2-facets">
        @if (activeFacet() === 'synthese') {
          @if (activeImpactView(); as impactView) {
            <section
              class="hv2-impact-blocks"
              data-testid="hypervisor-v2-impact-blocks"
              [attr.data-view]="impactView.id"
            >
              @for (block of impactComprendreBlocks(); track block.type + '-' + $index) {
                @switch (block.type) {
                  @case ('echeancier') {
                    <app-impact-block-echeancier
                      [source]="block.source || null"
                      [title]="block.title || null"
                      [width]="block.width || null"
                      [settings]="block.settings"
                      [exit]="block.exit || null"
                      [items]="impactEcheancierItems()"
                    />
                  }
                  @case ('flux') {
                    <app-impact-block-flux
                      [source]="block.source || null"
                      [title]="block.title || null"
                      [width]="block.width || null"
                      [settings]="block.settings"
                      [exit]="block.exit || null"
                      [items]="impactFluxItems()"
                    />
                  }
                  @case ('carte') {
                    <app-impact-block-carte
                      [source]="block.source || null"
                      [title]="block.title || null"
                      [width]="block.width || null"
                      [settings]="block.settings"
                      [exit]="block.exit || null"
                      [zones]="impactCarteZones()"
                      [selectedZoneId]="impactSelectedZone()"
                      [attribution]="mapAttribution()"
                      (zoneSelect)="onImpactZoneSelect($event)"
                    />
                  }
                  @case ('alertes') {
                    <app-impact-block-alertes
                      [source]="block.source || null"
                      [title]="block.title || null"
                      [width]="block.width || null"
                      [settings]="block.settings"
                      [exit]="block.exit || null"
                      [items]="impactAlerteItems()"
                    />
                  }
                  @case ('ordre_du_jour') {
                    <app-impact-block-agenda
                      [source]="block.source || null"
                      [title]="block.title || null"
                      [width]="block.width || null"
                      [settings]="block.settings"
                      [exit]="block.exit || null"
                      [points]="impactOrdrePoints()"
                      (logDecision)="onMeetingDecision($event)"
                    />
                  }
                  @case ('indicateurs') {
                    <app-impact-block-indicateurs
                      [source]="block.source || null"
                      [title]="block.title || null"
                      [width]="block.width || null"
                      [settings]="block.settings"
                      [exit]="block.exit || null"
                      [items]="impactIndicateurItems()"
                    />
                  }
                }
              }
              @if (showsBlock(impactView, 'decider', 'decisions') && !presentationTheme()) {
                <article class="hv2-card hv2-card-decision">
                  <ng-container [ngTemplateOutlet]="decisionTpl"></ng-container>
                </article>
              }
            </section>
          } @else if (presentationTheme()) {
            <ng-container [ngTemplateOutlet]="presentationTpl"></ng-container>
          } @else {
            <app-operational-objective />
            <app-hypervisor-automation />
            <ng-container [ngTemplateOutlet]="legendTpl"></ng-container>
            @if (sourceStates().series !== 'ready') {
              <div class="hv2-degraded-page" data-testid="hypervisor-v2-series-degraded">
                <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'series' }"></ng-container>
                @if (showBlock('comprendre', 'decisions') || showBlock('decider', 'decisions')) {
                  <article class="hv2-card hv2-card-decision">
                    <ng-container [ngTemplateOutlet]="decisionTpl"></ng-container>
                  </article>
                }
              </div>
            } @else if (!series()) {
              <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.empty') }}</p><a [navLink]="{leaf:'help-guide',params:{guideId:'value'}}">{{i18n.t('experience.adoption.help')}}</a>
            } @else {
              <div class="hv2-page">
            <ck-chart-tip
              [open]="pageTipOpen()"
              [title]="pageTipTitle()"
              [lines]="pageTipLines()"
              [x]="pageTipX()"
              [y]="pageTipY()"
            />
            @if (showStratum('comprendre')) {
              <section class="hv2-stratum" data-testid="hypervisor-v2-stratum-comprendre">
                <ng-container [ngTemplateOutlet]="leaderTpl" [ngTemplateOutletContext]="{ id: 'comprendre', num: '01' }"></ng-container>
                <div class="hv2-body">
                  @if (showHero()) {
                    <section class="hv2-hero" data-testid="hypervisor-v2-hero">
                      @if (showBlock('comprendre', 'monument') || showBlock('comprendre', 'provenance') || showBlock('comprendre', 'unites')) {
                        <div class="hv2-hero-text">
                          <div>
                            @if (showBlock('comprendre', 'monument') || showBlock('comprendre', 'provenance')) {
                              <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.hero.kicker', { days: dayCount() }) }}</div>
                            }
                            @if (showBlock('comprendre', 'monument')) {
                              @if (monument(); as mon) {
                                <p class="hv2-monument-group" data-testid="hypervisor-v2-monument">
                                  <span class="sr-only">{{ monumentLabel() }}</span>
                                  <span class="hv2-monument-row" aria-hidden="true">
                                    <span class="hv2-monument-figure">
                                      <span class="hv2-monument ck-tnum">{{ monumentValue() }}</span>
                                      <span class="hv2-monument-unit">{{ mon.unit }}</span>
                                    </span>
                                    @if (measuredPart(); as part) {
                                      <span class="ck-mono hv2-measured-part" data-testid="hypervisor-v2-measured-part">{{ measuredMark }} {{ part }}</span>
                                    }
                                  </span>
                                  <span class="hv2-sentence" aria-hidden="true">{{ heroSentence() }}</span>
                                </p>
                                <p class="hv2-sub">{{ heroSub() }}</p>
                              } @else {
                                <div class="hv2-monument-row">
                                  <span class="hv2-monument hv2-monument-state ck-mono">{{ factLabel(series()!.monument) }}</span>
                                </div>
                                <p class="hv2-sub">{{ i18n.t('hypervisor.v2.hero.not_configured') }}</p>
                              }
                            }
                            @if (showBlock('comprendre', 'unites')) {
                              <ng-container [ngTemplateOutlet]="unitesTpl"></ng-container>
                            }
                          </div>
                          @if (showBlock('comprendre', 'provenance')) {
                            <div class="hv2-provenance-block">
                              @if (provenance(); as prov) {
                                <div class="hv2-provenance">
                                  <span
                                    class="hv2-provenance-ink"
                                    tabindex="0"
                                    [style.flexGrow]="prov.measured"
                                    [attr.aria-label]="provenanceMeasuredTip()"
                                    (pointerenter)="onProvenanceTip('measured', $event)"
                                    (pointerleave)="clearPageTip()"
                                    (focus)="onProvenanceTip('measured', $event)"
                                    (blur)="clearPageTip()"
                                  ></span>
                                  <span
                                    class="hv2-provenance-teal"
                                    tabindex="0"
                                    [style.flexGrow]="prov.declared"
                                    [attr.aria-label]="provenanceDeclaredTip()"
                                    (pointerenter)="onProvenanceTip('declared', $event)"
                                    (pointerleave)="clearPageTip()"
                                    (focus)="onProvenanceTip('declared', $event)"
                                    (blur)="clearPageTip()"
                                  ></span>
                                </div>
                                <div class="ck-mono hv2-provenance-legend">
                                  <span>{{ measuredMark }} {{ i18n.t('hypervisor.v2.hero.measured_share', { pct: prov.measuredPct }) }}</span>
                                  <span class="hv2-teal">{{ declaredMark }} {{ i18n.t('hypervisor.v2.hero.declared_share', { pct: prov.declaredPct }) }}</span>
                                </div>
                              }
                              <div
                                class="hv2-peak-card"
                                [class.hv2-peak-lit]="hoverDay() != null && hoverDay() === series()!.peak?.index"
                                (pointerenter)="onDayHover(series()!.peak?.index ?? null)"
                                (pointerleave)="onDayHover(null)"
                              >
                                @if (peakCard(); as peak) {
                                  <div class="ck-mono hv2-peak-kicker">
                                    <span class="hv2-dot-teal" aria-hidden="true"></span>
                                    {{ i18n.t('hypervisor.v2.peak', { date: peak.date }) }}
                                  </div>
                                  <div class="hv2-peak-row">
                                    <span class="hv2-peak-value ck-tnum">{{ peak.total }}</span>
                                    <span class="hv2-peak-detail">{{ peak.detail }}</span>
                                  </div>
                                  <div class="ck-mono hv2-peak-split">
                                    @if (peak.measured) {
                                      <span>{{ measuredMark }} {{ i18n.t('hypervisor.v2.hero.peak.measured', { value: peak.measured }) }}</span>
                                    }
                                    @if (peak.declared) {
                                      <span class="hv2-teal">{{ declaredMark }} {{ i18n.t('hypervisor.v2.hero.peak.declared', { value: peak.declared }) }}</span>
                                    }
                                  </div>
                                } @else {
                                  <div class="ck-mono hv2-peak-kicker">{{ i18n.t('hypervisor.v2.hero.peak.none') }}</div>
                                }
                              </div>
                              <dl class="hv2-facts">
                                <div class="hv2-fact">
                                  <dt>{{ i18n.t('hypervisor.v2.hero.cost') }}</dt>
                                  <dd class="ck-mono ck-tnum" data-fact="cost">{{ costFact() }}</dd>
                                </div>
                                <div class="hv2-fact">
                                  <dt>{{ i18n.t('hypervisor.v2.hero.value') }}</dt>
                                  <dd class="ck-mono ck-tnum" [class.hv2-teal]="series()!.valueTotal.state === 'available'" data-fact="value">{{ valueFact() }}</dd>
                                </div>
                              </dl>
                            </div>
                          }
                        </div>
                      }
                      @if (showBlock('comprendre', 'cadran')) {
                        <div class="hv2-hero-dial">
                          <ck-chart-radial-days
                            [days]="radialDays()"
                            [ticks]="radialTicks()"
                            [centerValue]="i18n.t('hypervisor.v2.cadran.center', { days: dayCount() })"
                            [centerCaption]="i18n.t('hypervisor.v2.cadran.grammar')"
                            [rangeLabel]="rangeLabel()"
                            [peakLabel]="quantityLabel"
                            [hoverDay]="hoverDay()"
                            (dayHover)="onDayHover($event)"
                          />
                          <div class="ck-mono hv2-chart-caption">{{ cadranLegend() }}</div>
                        </div>
                      }
                      @if (showBlock('comprendre', 'couverture')) {
                        <ng-container [ngTemplateOutlet]="couvertureTpl"></ng-container>
                      }
                      @if (showBlock('comprendre', 'sankey')) {
                        <div class="hv2-hero-flow">
                          <h3 class="hv2-flow-title">{{ i18n.t('hypervisor.v2.sankey.title') }}</h3>
                          <p class="hv2-flow-explainer">{{ sankeyExplainer() }}</p>
                          @if (sankeySources().length) {
                            <ck-chart-sankey-flow
                              [sources]="sankeySources()"
                              [middleLabel]="sankeyMiddleLabel()"
                              [rightLabel]="sankeyRightLabel()"
                              [leftCaption]="i18n.t('hypervisor.v2.sankey.left_caption') + ' ' + measuredMark"
                              [middleCaption]="i18n.t('hypervisor.v2.sankey.middle_caption')"
                              [rightCaption]="i18n.t('hypervisor.v2.sankey.right_caption') + ' ' + declaredMark"
                              [hoverSystem]="hoverSystem()"
                              [middleTip]="sankeyMiddleTip()"
                              [rightTip]="sankeyRightTip()"
                              (systemHover)="onSystemHover($event)"
                              (systemClick)="onSystemClick($event)"
                            />
                          }
                        </div>
                      }
                      @if (showBlock('comprendre', 'signal')) {
                        <ng-container [ngTemplateOutlet]="signalTpl" [ngTemplateOutletContext]="{ hero: true }"></ng-container>
                      }
                      @if (showBlock('comprendre', 'decisions')) {
                        <div class="hv2-hero-decision">
                          <ng-container [ngTemplateOutlet]="decisionTpl"></ng-container>
                        </div>
                      }
                    </section>
                  }
                  @if (showBlock('comprendre', 'rivers') || showBlock('comprendre', 'hors_denominateur')) {
                    <div class="hv2-under">
                      @if (showBlock('comprendre', 'rivers')) {
                        <article class="hv2-card hv2-rivers">
                          <header class="hv2-card-head">
                            <div>
                              <h3 class="hv2-card-title">{{ riversTitle() }}</h3>
                              <p class="hv2-card-sub">{{ i18n.t('hypervisor.v2.rivers.sub') }}</p>
                            </div>
                            <span class="ck-mono hv2-card-legend">{{ riversLegend() }}</span>
                          </header>
                          @if (streamSeries().length) {
                            <ck-chart-stream
                              fluid
                              [series]="streamSeries()"
                              [dayLabels]="dayLabels()"
                              [weekendStarts]="series()!.weekendStarts"
                              [ticks]="streamTicks()"
                              [peak]="streamPeak()"
                              [gridLabel]="quantityLabel"
                              [hoverDay]="hoverDay()"
                              [hoverSystem]="hoverSystem()"
                              (dayHover)="onDayHover($event)"
                              (systemHover)="onSystemHover($event)"
                            />
                          } @else {
                            <p class="hv2-muted">{{ i18n.t('hypervisor.v2.rivers.empty') }}</p>
                          }
                        </article>
                      }
                      @if (showBlock('comprendre', 'hors_denominateur')) {
                        <article class="hv2-card hv2-hors" data-testid="hypervisor-v2-hors-denominateur">
                          <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.hors.kicker') }}</div>
                          @if (series()!.outside.length === 0) {
                            <h3 class="hv2-hors-title">{{ i18n.t('hypervisor.v2.hors.title') }}</h3>
                            <p class="hv2-muted">{{ i18n.t('hypervisor.v2.hors.empty') }}</p>
                          } @else {
                            <h3 class="hv2-hors-title">{{ horsTitle() }}</h3>
                            <div class="hv2-hors-list">
                              @for (row of series()!.outside; track row.systemId) {
                                <div
                                  class="hv2-hors-row"
                                  [class.hv2-row-lit]="hoverSystem() === row.systemId"
                                  (pointerenter)="onSystemHover(row.systemId)"
                                  (pointerleave)="onSystemHover(null)"
                                >
                                  <div class="hv2-hors-line">
                                    <span class="hv2-hors-name">{{ row.name }}</span>
                                    <span class="ck-mono ck-tnum hv2-hors-value" [attr.title]="dotsTitle(row)">{{ outcomeLabel(row) }} {{ outcomeMark(row) }}</span>
                                  </div>
                                  @if (outcomeCount(row) > 0) {
                                    <ck-chart-unit-dots
                                      [units]="outcomeCount(row)"
                                      [unitsPerDot]="unitsPerDot()"
                                      [dotSize]="5"
                                      [gap]="3"
                                      [tipTitle]="dotsTip(row)"
                                    />
                                  }
                                </div>
                              }
                            </div>
                            @if (horsDeclareLink(); as link) {
                              <a class="hv2-link" [navLink]="link">{{ i18n.t('hypervisor.v2.hors.declare') }}</a>
                            }
                          }
                        </article>
                      }
                    </div>
                  }
                </div>
              </section>
            }
            @if (showStratum('detailler') && showBlock('detailler', 'registre')) {
              <section class="hv2-stratum" data-testid="hypervisor-v2-stratum-detailler">
                <ng-container [ngTemplateOutlet]="leaderTpl" [ngTemplateOutletContext]="{ id: 'detailler', num: '02' }"></ng-container>
                <div class="hv2-body">
                  <ng-container [ngTemplateOutlet]="registerTpl" [ngTemplateOutletContext]="{ testid: 'hypervisor-v2-register' }"></ng-container>
                </div>
              </section>
            }
            @if (showStratum('decider')) {
              <section class="hv2-stratum" data-testid="hypervisor-v2-stratum-decider">
                <ng-container [ngTemplateOutlet]="leaderTpl" [ngTemplateOutletContext]="{ id: 'decider', num: '03' }"></ng-container>
                <div class="hv2-body hv2-cards3">
                  @if (showBlock('decider', 'signal')) {
                    <ng-container [ngTemplateOutlet]="signalTpl" [ngTemplateOutletContext]="{ hero: false }"></ng-container>
                  }
                  @if (showBlock('decider', 'decisions')) {
                    <article class="hv2-card hv2-card-decision" [style.--stagger]="1">
                      <ng-container [ngTemplateOutlet]="decisionTpl"></ng-container>
                    </article>
                  }
                  <article class="hv2-card hv2-card-bases" [style.--stagger]="2">
                    <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.bases.kicker', { declared: declaredCount(), total: series()!.register.length }) }}</div>
                    <h3 class="hv2-card-title">{{ basesTitle() }}</h3>
                    @if (series()!.outside.length) {
                      <ul class="hv2-bases-list">
                        @for (row of series()!.outside; track row.systemId) {
                          <li class="hv2-bases-row">
                            <span>{{ row.name }}</span>
                            <span class="ck-mono ck-tnum hv2-muted">{{ outcomeLabel(row) }}</span>
                            @if (row.capabilityId) {
                              <a class="hv2-link" [navLink]="basesLink(row.capabilityId)">→ {{ i18n.t('hypervisor.v2.bases.declare_short') }}</a>
                            }
                          </li>
                        }
                      </ul>
                    }
                    <p class="hv2-footnote">{{ i18n.t('hypervisor.v2.bases.footnote') }}</p>
                  </article>
                </div>
              </section>
            }
          </div>
        }
        }
        }

        @if (activeFacet() === 'registre') {
          <ng-container [ngTemplateOutlet]="legendTpl"></ng-container>
          @if (sourceStates().series !== 'ready') {
            <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'series' }"></ng-container>
          } @else if (series()) {
            <ng-container [ngTemplateOutlet]="registerTpl" [ngTemplateOutletContext]="{ testid: 'hypervisor-v2-register-registre' }"></ng-container>
          } @else {
            <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.empty') }}</p><a [navLink]="{leaf:'help-guide',params:{guideId:'value'}}">{{i18n.t('experience.adoption.help')}}</a>
          }
        }

        @if (activeFacet() === 'couts') {
          <ng-container [ngTemplateOutlet]="legendTpl"></ng-container>
          <div class="hv2-stack">
            @if (sourceStates().series !== 'ready') {
              <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'series' }"></ng-container>
            } @else if (series(); as view) {
              <article class="hv2-card">
                <header class="hv2-card-head hv2-card-head-wrap">
                  <div>
                    <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.hero.cost') }}</h3>
                    <p class="hv2-card-sub">{{ costFact() }}</p>
                  </div>
                  <dl class="hv2-facts hv2-facts-aside" data-testid="hypervisor-v2-couts-ratio">
                    <div class="hv2-fact">
                      <dt>{{ i18n.t('hypervisor.v2.metric.ratio') }}</dt>
                      <dd class="ck-mono ck-tnum" data-fact="ratio">
                        <span [class.hv2-teal]="view.ratio.state === 'available'">{{ ratioFact() }}</span>
                        @if (valueDeclaredShare(); as share) {
                          <span class="hv2-fact-share" data-testid="hypervisor-v2-couts-declared-share">· {{ share }}</span>
                        }
                      </dd>
                    </div>
                  </dl>
                </header>
                @if (costStreamSeries().length) {
                  <ck-chart-stream
                    fluid
                    [series]="costStreamSeries()"
                    [dayLabels]="dayLabels()"
                    [weekendStarts]="view.weekendStarts"
                    [ticks]="streamTicks()"
                    [gridLabel]="moneyLabel"
                    [hoverDay]="hoverDay()"
                    [hoverSystem]="hoverSystem()"
                    (dayHover)="onDayHover($event)"
                    (systemHover)="onSystemHover($event)"
                  />
                } @else {
                  <p class="hv2-muted">{{ factLabel(view.costTotal) }}</p>
                }
              </article>
              <ng-container [ngTemplateOutlet]="registerTpl" [ngTemplateOutletContext]="{ testid: 'hypervisor-v2-register-couts' }"></ng-container>
            } @else {
              <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.empty') }}</p><a [navLink]="{leaf:'help-guide',params:{guideId:'value'}}">{{i18n.t('experience.adoption.help')}}</a>
            }
          </div>
        }

        @if (activeFacet() === 'bases') {
          <ng-container [ngTemplateOutlet]="basesTpl"></ng-container>
        }

        @if (activeFacet() === 'decisions') {
          <div class="hv2-stack">
            <article class="hv2-card">
              <header class="hv2-card-head">
                <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.decisions.proposed') }}@if (sourceStates().decisions === 'ready') { <span class="ck-mono hv2-count">{{ proposedDecisions().length }}</span>}</h3>
                <button type="button" class="hv2-text-btn" (click)="scanRecommendations()" [disabled]="scanning()">
                  {{ scanning() ? i18n.t('hypervisor.reco.scanning') : i18n.t('hypervisor.reco.scan') }}
                </button>
              </header>
              @if (sourceStates().decisions !== 'ready') {
                <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'decisions' }"></ng-container>
              } @else if (proposedDecisions().length === 0) {
                <p class="hv2-muted">{{ i18n.t('hypervisor.v2.decisions.none_proposed') }}</p>
              } @else {
                <ul class="hv2-list">
                  @for (item of proposedDecisions(); track item.id) {
                    <li class="hv2-list-row">
                      @if (isAgentSuggested(item)) {
                        <span class="hv2-agent-orb" data-testid="hypervisor-decision-agent-orb" [attr.aria-label]="i18n.t('hypervisor.v2.decisions.agent_orb')"></span>
                      }
                      <span class="hv2-grow">{{ item.title }}</span>
                      <span class="ck-mono hv2-muted">{{ formatDate(item.created_at) }}</span>
                      <button type="button" class="hv2-btn" (click)="accept(item)">{{ i18n.t('hypervisor.v2.decision.accept') }}</button>
                      <button type="button" class="hv2-btn" (click)="reject(item)">{{ i18n.t('hypervisor.v2.decision.reject') }}</button>
                    </li>
                  }
                </ul>
              }
            </article>
            <a class="hv2-link" data-testid="hypervisor-decisions-review-queue" [navLink]="{ leaf: 'review-queue' }">
              {{ i18n.t('hypervisor.v2.decisions.review_queue') }}
            </a>
            <article class="hv2-card">
              <header class="hv2-card-head">
                <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.decisions.recommendations') }}@if (sourceStates().recos === 'ready') { <span class="ck-mono hv2-count">{{ recommendationGroups().length }}</span>}</h3>
              </header>
              @if (sourceStates().recos !== 'ready') {
                <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'recos' }"></ng-container>
              } @else if (recommendationGroups().length === 0) {
                <p class="hv2-muted">{{ i18n.t('hypervisor.v2.decisions.none_reco') }}</p>
              } @else {
                <ul class="hv2-list">
                  @for (group of recommendationGroups(); track group.item.id) {
                    <li class="hv2-list-row">
                      <span class="hv2-grow">{{ group.item.title }}</span>
                      @if (group.count > 1) {
                        <span class="ck-mono hv2-count">×{{ group.count }}</span>
                      }
                      <span class="ck-mono hv2-muted">{{ scopeLabel(group.item.scope) }}</span>
                    </li>
                  }
                </ul>
              }
            </article>
            <article class="hv2-card">
              <header class="hv2-card-head">
                <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.decisions.history') }}@if (sourceStates().decisions === 'ready') { <span class="ck-mono hv2-count">{{ historyDecisions().length }}</span>}</h3>
                @if (historyDecisions().length) {
                  <button type="button" class="hv2-text-btn" (click)="historyOpen.set(!historyOpen())" [attr.aria-expanded]="historyOpen()">
                    {{ historyOpen() ? i18n.t('hypervisor.v2.decisions.history_hide') : i18n.t('hypervisor.v2.decisions.history_show', { count: historyDecisions().length }) }}
                  </button>
                }
              </header>
              @if (sourceStates().decisions !== 'ready') {
                <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'decisions' }"></ng-container>
              } @else if (historyDecisions().length === 0) {
                <p class="hv2-muted">{{ i18n.t('hypervisor.v2.decisions.none_history') }}</p>
              } @else if (historyOpen()) {
                <ul class="hv2-list">
                  @for (item of historyDecisions(); track item.id) {
                    <li class="hv2-list-row">
                      <span class="hv2-grow">{{ item.title }}</span>
                      <span class="ck-mono hv2-muted">{{ decisionStatus(item.status) }}</span>
                      <span class="ck-mono hv2-muted">{{ formatDate(item.applied_at || item.created_at) }}</span>
                    </li>
                  }
                </ul>
              }
            </article>
          </div>
        }

        @if (activeFacet() === 'journal') {
          <article class="hv2-card">
            <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.journal.title') }}</h3>
            @if (sourceStates().series !== 'ready') {
              <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'series' }"></ng-container>
            } @else if (series(); as view) {
              <ck-chart-pulse
                [values]="view.pulseValues"
                [staleFrom]="view.staleFrom"
                [startLabel]="i18n.t('hypervisor.v2.journal.start')"
                [endLabel]="i18n.t('hypervisor.v2.journal.end')"
                [zeroLabel]="i18n.t('hypervisor.v2.journal.zero')"
                [valueLabel]="pulseTip"
              />
            }
            @if (sourceStates().decisions !== 'ready') {
              <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'decisions' }"></ng-container>
            } @else if (journalEntries().length === 0) {
              <p class="hv2-muted">{{ i18n.t('hypervisor.v2.journal.empty') }}</p>
            } @else {
              <ul class="hv2-list" data-testid="hypervisor-v2-journal-entries">
                @for (entry of journalEntries(); track entry.id) {
                  <li class="hv2-journal-entry">
                    <div class="hv2-list-row">
                      <span class="hv2-grow">{{ i18n.t('hypervisor.v2.journal.decision', { title: entry.title }) }}</span>
                      <span class="ck-mono hv2-muted">{{ formatDate(entry.at) }}</span>
                    </div>
                    <div class="hv2-list-row hv2-journal-effect">
                      <span class="hv2-grow">{{ entry.effect
                        ? i18n.t('hypervisor.v2.journal.effect', { effect: entry.effect })
                        : i18n.t('hypervisor.v2.journal.effect_pending') }}</span>
                    </div>
                  </li>
                }
              </ul>
            }
            <ul class="hv2-list">
              @for (item of signals(); track item.id) {
                <li class="hv2-list-row">
                  <ck-tag [tone]="item.tone">{{ item.label }}</ck-tag>
                </li>
              }
            </ul>
          </article>
        }
        </div>
      }
    </ck-page-frame>

    <ng-template #legendTpl>
      <div class="ck-mono hv2-legend">{{ i18n.t('hypervisor.v2.legend') }}</div>
    </ng-template>

    <ng-template #unitesTpl>
      <div class="hv2-unites" data-testid="hypervisor-v2-unites">
        <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.unites.kicker') }}</div>
        <ul class="hv2-unites-list">
          @for (group of nativeUnits(); track group.unit) {
            <li class="hv2-unites-row">
              <span class="hv2-unites-value ck-tnum">{{ formatNumber(group.total, 0) }}</span>
              <div class="hv2-unites-meta">
                <span class="hv2-unites-unit">{{ nativeUnitLabel(group.unit) }}</span>
                <span class="ck-mono hv2-unites-systems">{{ unitesSystems(group) }}</span>
              </div>
              @if (group.total > 0) {
                <ck-chart-unit-dots
                  [units]="group.total"
                  [unitsPerDot]="nativeUnitsPerDot()"
                  [width]="96"
                  [dotSize]="5"
                  [gap]="3"
                  [tipTitle]="unitesDotsTip(group)"
                />
              }
            </li>
          }
        </ul>
        <p class="hv2-sub">{{ unitesNote() }}</p>
      </div>
    </ng-template>

    <ng-template #couvertureTpl>
      <div class="hv2-hero-couverture" data-testid="hypervisor-v2-couverture">
        <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.couverture.kicker', { declared: declaredCount(), total: series()!.register.length }) }}</div>
        <h3 class="hv2-card-title">{{ couvertureTitle() }}</h3>
        <p class="hv2-card-sub">{{ i18n.t('hypervisor.v2.couverture.note') }}</p>
        @if (missingBasisRows().length) {
          <ul class="hv2-bases-list">
            @for (row of missingBasisRows(); track row.systemId) {
              <li class="hv2-bases-row">
                <span>{{ row.name }}</span>
                <span class="ck-mono ck-tnum hv2-muted">{{ outcomeLabel(row) }}</span>
              </li>
            }
          </ul>
          <a class="hv2-link" [navLink]="basesFacetLink()">{{ couvertureDeclare() }}</a>
        }
      </div>
    </ng-template>

    <ng-template #signalTpl let-hero="hero">
      <article
        class="hv2-card hv2-card-signal"
        [class.hv2-hero-signal]="hero"
        [attr.data-testid]="hero ? 'hypervisor-v2-hero-signal' : null"
        [style.--stagger]="0"
      >
        <div class="ck-mono hv2-kicker">{{ signalKicker() }}</div>
        <h3 class="hv2-card-title">{{ signalCopy() }}</h3>
        <ck-chart-pulse
          [values]="series()!.pulseValues"
          [staleFrom]="series()!.staleFrom"
          [width]="250"
          [height]="56"
          [startLabel]="i18n.t('hypervisor.v2.journal.start')"
          [endLabel]="i18n.t('hypervisor.v2.journal.end')"
          [zeroLabel]="i18n.t('hypervisor.v2.journal.zero')"
          [valueLabel]="pulseTip"
        />
        <p class="hv2-card-sub">{{ signalContext() }}</p>
        @if (staleRows().length === 1) {
          <a class="hv2-btn" [navLink]="systemLink(staleRows()[0]!)">{{ i18n.t('hypervisor.v2.signal.open_system') }}</a>
        }
      </article>
    </ng-template>

    <ng-template #decisionTpl>
      @if (sourceStates().decisions !== 'ready') {
        <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'decisions' }"></ng-container>
      } @else if (firstProposed(); as decision) {
        <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.decision.kicker', { date: formatDate(decision.created_at, true) }) }}</div>
        <h3 class="hv2-card-title">
          @if (isAgentSuggested(decision)) {
            <span class="hv2-agent-orb" data-testid="hypervisor-decision-agent-orb" [attr.aria-label]="i18n.t('hypervisor.v2.decisions.agent_orb')"></span>
          }
          {{ decision.title }}
        </h3>
        <dl class="hv2-facts hv2-facts-plain">
          <div class="hv2-fact"><dt>{{ i18n.t('hypervisor.v2.decision.scope') }}</dt><dd>{{ scopeLabel(decision.scope) }}</dd></div>
          <div class="hv2-fact"><dt>{{ i18n.t('hypervisor.v2.decision.kind') }}</dt><dd>{{ kindLabel(decision.kind) }}</dd></div>
          @if (proposedDecisions().length > 1) {
            <div class="hv2-fact"><dt>{{ i18n.t('hypervisor.v2.decisions.proposed') }}</dt><dd>{{ pendingLabel(proposedDecisions().length - 1) }}</dd></div>
          }
        </dl>
        <div class="hv2-btn-row">
          <button type="button" class="hv2-btn" (click)="accept(decision)">{{ i18n.t('hypervisor.v2.decision.accept') }}</button>
          <button type="button" class="hv2-btn" (click)="reject(decision)">{{ i18n.t('hypervisor.v2.decision.reject') }}</button>
        </div>
        <a class="hv2-link" [navLink]="{ leaf: 'review-queue' }">{{ i18n.t('hypervisor.v2.decisions.review_queue') }}</a>
      } @else {
        <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.decision.kicker_none') }}</div>
        <p class="hv2-card-sub">{{ i18n.t('hypervisor.v2.decision.empty') }}</p>
      }
    </ng-template>

    <ng-template #presentationTpl>
      <div class="hv2-presentation" data-testid="hypervisor-presentation">
        @if (sourceStates().series !== 'ready') {
          <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'series' }"></ng-container>
        } @else if (!series()) {
          <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.empty') }}</p>
        } @else {
          <div class="hv2-presentation-kpis">
            <div class="hv2-presentation-kpi">
              <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.theme.kpi.systems') }}</div>
              <div class="hv2-presentation-num ck-tnum">{{ series()!.register.length }}</div>
            </div>
            <div class="hv2-presentation-kpi">
              <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.theme.kpi.runs') }}</div>
              <div class="hv2-presentation-num ck-tnum">{{ presentationRuns() }}</div>
            </div>
            <div class="hv2-presentation-kpi">
              <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.theme.kpi.cost') }}</div>
              <div class="hv2-presentation-num ck-tnum">{{ costFact() }}</div>
            </div>
            <div class="hv2-presentation-kpi">
              <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.theme.kpi.decisions') }}</div>
              @if (sourceStates().decisions === 'ready') {
                <div
                  class="hv2-presentation-num ck-tnum"
                  [class.hv2-presentation-warn]="proposedDecisions().length > 0"
                >{{ proposedDecisions().length }}</div>
              } @else {
                <div class="ck-mono hv2-presentation-state">{{ i18n.t('hypervisor.state.unavailable') }}</div>
              }
            </div>
          </div>
          <p class="hv2-presentation-summary">{{ pageSummary() }}</p>
          <div class="hv2-presentation-columns">
            <article class="hv2-card" data-testid="hypervisor-presentation-decide">
              <header class="hv2-card-head">
                <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.theme.decide.title') }}</h3>
                <a class="hv2-link" [navLink]="decisionsFacetLink()">{{ i18n.t('hypervisor.v2.theme.decide.open') }}</a>
              </header>
              @if (sourceStates().decisions !== 'ready') {
                <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'decisions' }"></ng-container>
              } @else {
                @if (presentationDecideRows().length) {
                  <ul class="hv2-presentation-list">
                    @for (row of presentationDecideRows(); track row.id) {
                      <li>
                        <span>{{ row.label }}</span>
                        <span class="ck-mono hv2-muted">{{ row.meta }}</span>
                      </li>
                    }
                  </ul>
                } @else if (sourceStates().recos === 'ready') {
                  <p class="hv2-muted">{{ i18n.t('hypervisor.v2.theme.decide.empty') }}</p>
                }
                @if (sourceStates().recos !== 'ready') {
                  <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'recos' }"></ng-container>
                }
              }
            </article>
            <article class="hv2-card" data-testid="hypervisor-presentation-watch">
              <header class="hv2-card-head">
                <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.theme.watch.title') }}</h3>
                <a class="hv2-link" [navLink]="registreFacetLink()">{{ i18n.t('hypervisor.v2.theme.watch.open') }}</a>
              </header>
              @if (presentationWatchRows().length === 0) {
                <p class="hv2-muted">{{ i18n.t('hypervisor.v2.theme.watch.empty') }}</p>
              } @else {
                <ul class="hv2-presentation-list">
                  @for (row of presentationWatchRows(); track row.id) {
                    <li>
                      <span>{{ row.label }}</span>
                      <span class="hv2-presentation-status" [attr.data-tone]="row.tone">{{ row.status }}</span>
                    </li>
                  }
                </ul>
              }
            </article>
          </div>
        }
      </div>
    </ng-template>

    <ng-template #unavailableTpl let-source="source">
      <div class="hv2-unavailable" [attr.data-testid]="'hypervisor-v2-unavailable-' + source">
        <div class="hv2-unavailable-copy">
          <span class="ck-mono hv2-unavailable-kicker">{{ sourceName(source) }}</span>
          <p class="hv2-unavailable-text" role="status" aria-live="polite">{{ sourceRetrying(source)
            ? i18n.t('hypervisor.v2.source.retrying')
            : i18n.t('hypervisor.v2.source.unavailable') }}</p>
        </div>
        <button
          type="button"
          class="hv2-retry ck-press"
          [attr.data-testid]="'hypervisor-v2-retry-' + source"
          [attr.aria-label]="i18n.t('hypervisor.v2.source.retry_label', { source: sourceName(source) })"
          [attr.aria-disabled]="sourceRetrying(source) ? 'true' : null"
          (click)="retrySource(source)"
        >{{ i18n.t('hypervisor.v2.source.retry') }}</button>
      </div>
    </ng-template>

    <ng-template #leaderTpl let-id="id" let-num="num">
      <div class="hv2-leader">
        <span class="hv2-leader-bar" aria-hidden="true"></span>
        <span class="ck-mono hv2-leader-num">{{ num }}</span>
        <h2 class="hv2-leader-title">{{ i18n.t('hypervisor.v2.leader.' + id + '.title') }}</h2>
        <p class="hv2-leader-sub">{{ i18n.t('hypervisor.v2.leader.' + id + '.sub') }}</p>
      </div>
    </ng-template>

    <ng-template #registerTpl let-testid="testid">
      <article class="hv2-card hv2-register ck-h-scroll" [attr.data-testid]="testid">
        <header class="hv2-card-head">
          <div>
            <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.register.title') }}</h3>
            <p class="hv2-card-sub">{{ registerSub() }}</p>
          </div>
        </header>
        @if (registerRows().length === 0) {
          <p class="hv2-muted">{{ i18n.t('hypervisor.v2.register.empty') }}</p>
        } @else {
          <table class="hv2-table">
            <thead>
              <tr class="ck-mono">
                <th>{{ i18n.t('hypervisor.v2.col.system') }}</th>
                @if (showCol('unit')) { <th>{{ i18n.t('hypervisor.v2.col.unit') }}</th> }
                @if (showCol('spark')) { <th>{{ periodLabel() }}</th> }
                @if (showCol('cost')) { <th class="hv2-num">{{ i18n.t('hypervisor.v2.col.cost') }}</th> }
                @if (showCol('basis')) { <th>{{ i18n.t('hypervisor.v2.col.basis') }}</th> }
                @if (showCol('value')) { <th class="hv2-num">{{ i18n.t('hypervisor.v2.col.value') }}</th> }
                <th class="hv2-arrow-col"><span aria-hidden="true">→</span></th>
              </tr>
            </thead>
            <tbody>
              @for (row of registerRows(); track row.systemId; let i = $index) {
                <tr
                  [attr.data-system-id]="row.systemId"
                  [class.hv2-row-outside]="row.outsideDenominator"
                  [class.hv2-row-lit]="hoverSystem() === row.systemId"
                  [class.hv2-row-flash]="flashSystem() === row.systemId || cameFromSystem() === row.systemId"
                  [style.--stagger]="i"
                  (pointerenter)="onSystemHover(row.systemId)"
                  (pointerleave)="onSystemHover(null)"
                >
                  <td>
                    <div class="hv2-system">
                      <span class="hv2-glyph ck-mono" [attr.data-health]="row.health">{{ row.initials }}</span>
                      <div>
                        <div class="hv2-system-name">
                          {{ row.name }}
                          @if (cameFromSystem() === row.systemId) {
                            <span class="ck-mono hv2-came-from">{{ i18n.t('nav.provenance.came_from') }}</span>
                          }
                        </div>
                        <div class="ck-mono hv2-system-meta"><span class="hv2-up">{{ runsWord(row) }}</span> · {{ runsLabel(row) }}</div>
                      </div>
                    </div>
                  </td>
                  @if (showCol('unit')) {
                    <td>
                      <span class="ck-mono ck-tnum hv2-result-value">{{ resultMain(row) }}</span>
                      <span class="hv2-result-qualifier">{{ resultQualifier(row) }}</span>
                    </td>
                  }
                  @if (showCol('spark')) {
                    <td><ck-chart-mini-area [values]="row.weekSpark" [tone]="sparkTone(row)" [width]="84" [height]="24" [valueLabel]="sparkTip" /></td>
                  }
                  @if (showCol('cost')) { <td class="ck-mono ck-tnum hv2-num">{{ formatFact(row.cost, 'currency') }}</td> }
                  @if (showCol('basis')) {
                    <td class="ck-mono hv2-basis" [class.hv2-teal]="row.basisStatus === 'declared'" [class.hv2-basis-absent]="!row.basisStatus || row.basisStatus === 'none'">
                      {{ basisLabel(row) }}
                      @if (!row.basisStatus || row.basisStatus === 'none') {
                        @if (row.capabilityId) {
                          · <a class="hv2-link" [navLink]="basesLink(row.capabilityId)">{{ i18n.t('hypervisor.v2.register.basis_state.declare') }}</a>
                        }
                      }
                    </td>
                  }
                  @if (showCol('value')) {
                    <td class="ck-mono ck-tnum hv2-num" [class.hv2-teal]="row.valueDeclared.state === 'available'">{{ rowValue(row) }}</td>
                  }
                  <td class="hv2-arrow-col">
                    <a
                      class="hv2-arrow"
                      [navLink]="systemLink(row)"
                      [navState]="registreProvenanceState()"
                      [attr.aria-label]="i18n.t('hypervisor.v2.register.open_system')"
                      [title]="i18n.t('hypervisor.v2.register.open_system')"
                    >→</a>
                  </td>
                </tr>
              }
            </tbody>
            <tfoot>
              <tr>
                <th>{{ i18n.t('hypervisor.v2.register.total_systems', { count: series()!.register.length }) }}</th>
                @if (showCol('unit')) { <td class="ck-mono ck-tnum">{{ footerResult() }}</td> }
                @if (showCol('spark')) { <td></td> }
                @if (showCol('cost')) { <td class="ck-mono ck-tnum hv2-num">{{ formatFact(series()!.costTotal, 'currency') }}</td> }
                @if (showCol('basis')) { <td class="ck-mono">{{ i18n.t('hypervisor.v2.register.total_declared', { declared: declaredCount(), total: series()!.register.length }) }}</td> }
                @if (showCol('value')) { <td class="ck-mono ck-tnum hv2-num" [class.hv2-teal]="series()!.valueTotal.state === 'available'">{{ footerValue() }}</td> }
                <td></td>
              </tr>
            </tfoot>
          </table>
        }
      </article>
    </ng-template>

    <ng-template #basesTpl>
      <article class="hv2-card ck-h-scroll" data-testid="hypervisor-v2-value-bases">
        <h3 class="ck-mono hv2-kicker">{{ i18n.t('nav.facet.bases') }}</h3>
        @if (sourceStates().bases !== 'ready') {
          <ng-container [ngTemplateOutlet]="unavailableTpl" [ngTemplateOutletContext]="{ source: 'bases' }"></ng-container>
        } @else if (bases().length === 0) {
          <p class="hv2-muted">{{ i18n.t('hypervisor.v2.bases.empty') }}</p>
        } @else {
          <table class="hv2-table">
            <thead>
              <tr class="ck-mono">
                <th>{{ i18n.t('hypervisor.v2.bases.col.capability') }}</th>
                <th>{{ i18n.t('hypervisor.v2.bases.col.unit') }}</th>
                <th>{{ i18n.t('hypervisor.v2.bases.col.hours') }}</th>
                <th>{{ i18n.t('hypervisor.v2.bases.col.value') }}</th>
                <th>{{ i18n.t('hypervisor.v2.bases.col.status') }}</th>
                <th>{{ i18n.t('hypervisor.v2.bases.col.provenance') }}</th>
                <th>{{ i18n.t('hypervisor.v2.bases.col.systems') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              @for (row of bases(); track row.capability_id) {
                <tr [class.hv2-row-focus]="focusCapabilityId() === row.capability_id">
                  <td>
                    <div>{{ row.name }}</div>
                    @if (posedByCopy(row); as posed) {
                      <div class="ck-mono hv2-muted hv2-posed" data-testid="hypervisor-bases-posed-by">{{ posed }}</div>
                    }
                    <button
                      type="button"
                      class="hv2-text-btn"
                      [attr.aria-expanded]="expandedBasisId() === row.capability_id"
                      (click)="toggleBasisContract(row.capability_id)"
                    >{{ i18n.t('hypervisor.v2.bases.contract_toggle') }}</button>
                    @if (expandedBasisId() === row.capability_id) {
                      <div class="hv2-basis-contract" data-testid="hypervisor-bases-contract">
                        <div class="ck-mono">{{ row.value_basis?.unit || row.output_unit || '—' }}</div>
                        <div class="ck-mono">{{ formatMaybeNumber(row.value_basis?.hours_per_unit) }} h</div>
                        <div class="ck-mono">{{ formatMoney(row.value_basis?.value_per_unit, row.value_basis?.currency) }}</div>
                        <div>{{ provenanceCopy(row) }}</div>
                      </div>
                    }
                  </td>
                  <td>{{ row.value_basis?.unit || row.output_unit || '' }}</td>
                  <td class="ck-mono ck-tnum">{{ formatMaybeNumber(row.value_basis?.hours_per_unit) }}</td>
                  <td class="ck-mono ck-tnum">{{ formatMoney(row.value_basis?.value_per_unit, row.value_basis?.currency) }}</td>
                  <td>{{ basisStatusLabel(row.value_basis?.status ?? 'none') }}</td>
                  <td>{{ provenanceCopy(row) }}</td>
                  <td>{{ systemNames(row) }}</td>
                  <td>
                    @if (isCatalogLocked(row)) {
                      <p class="hv2-muted">{{ i18n.t('hypervisor.v2.bases.catalog_readonly') }}</p>
                    } @else if (canEdit()) {
                      @if (editingId() === row.capability_id) {
                        <div class="hv2-edit">
                          <label>{{ i18n.t('hypervisor.v2.bases.unit') }}
                            <input [value]="draft()!.unit" (input)="patchDraft('unit', $event)" />
                          </label>
                          <label>{{ i18n.t('hypervisor.v2.bases.hours_per_unit') }}
                            <input type="number" [value]="draft()!.hours_per_unit" (input)="patchDraft('hours_per_unit', $event)" />
                          </label>
                          <label>{{ i18n.t('hypervisor.v2.bases.value_per_unit') }}
                            <input type="number" [value]="draft()!.value_per_unit" (input)="patchDraft('value_per_unit', $event)" />
                          </label>
                          <label>{{ i18n.t('hypervisor.v2.bases.currency') }}
                            <input [value]="draft()!.currency" (input)="patchDraft('currency', $event)" />
                          </label>
                          <label>{{ i18n.t('hypervisor.v2.bases.col.status') }}
                            <select [value]="draft()!.status" (change)="patchDraft('status', $event)">
                              <option value="declared">{{ i18n.t('hypervisor.v2.bases.status.declared') }}</option>
                              <option value="measured">{{ i18n.t('hypervisor.v2.bases.status.measured') }}</option>
                              <option value="none">{{ i18n.t('hypervisor.v2.bases.status.none') }}</option>
                            </select>
                          </label>
                          <label>{{ i18n.t('hypervisor.v2.bases.note') }}
                            <input [value]="draft()!.note" (input)="patchDraft('note', $event)" />
                          </label>
                          <button type="button" class="hv2-text-btn" (click)="saveBasis(row)" [disabled]="savingBasis()">{{ i18n.t('common.save') }}</button>
                          <button type="button" class="hv2-text-btn" (click)="editingId.set(null)">{{ i18n.t('common.cancel') }}</button>
                          @if (basisError()) {
                            <p class="hv2-error">{{ i18n.t('hypervisor.v2.bases.save_failed') }}</p>
                          }
                        </div>
                      } @else {
                        <button type="button" class="hv2-text-btn" (click)="startEdit(row)">{{ i18n.t('common.edit') }}</button>
                      }
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      </article>
    </ng-template>

    <ck-panel
      [open]="customizeOpen()"
      (openChange)="customizeOpen.set($event)"
      position="side"
      [title]="i18n.t('hypervisor.v2.customize.title')"
      width="720px"
    >
      @if (activeView(); as view) {
        @if (!canEdit()) {
          <p class="hv2-muted">{{ i18n.t('hypervisor.v2.customize.preview_only') }}</p>
        }
        <div class="hv2-customize-grid">
          <div class="hv2-customize-assembly" data-testid="hypervisor-customize-assembly">
            <p class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.customize.assembly') }}</p>
            <fieldset class="hv2-fieldset">
              <legend class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.customize.denominator') }}</legend>
              @for (item of denominators; track item) {
                <label>
                  <input type="radio" name="denominator" [checked]="view.denominator === item" (change)="setDenominator(item)" />
                  {{ i18n.t('hypervisor.v2.denominator.' + item) }}
                </label>
              }
            </fieldset>
            <fieldset class="hv2-fieldset">
              <legend class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.customize.period') }}</legend>
              @for (item of periods; track item) {
                <label>
                  <input type="radio" name="period" [checked]="viewPeriod(view) === item" (change)="setPeriod(item)" />
                  {{ i18n.t('hypervisor.v2.period.' + item) }}
                </label>
              }
            </fieldset>
            <fieldset class="hv2-fieldset">
              <legend class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.customize.sort') }}</legend>
              @for (item of sorts; track item) {
                <label>
                  <input type="radio" name="sort" [checked]="view.sort === item" (change)="setSort(item)" />
                  {{ i18n.t('hypervisor.v2.sort.' + item) }}
                </label>
              }
            </fieldset>
            <fieldset class="hv2-fieldset">
              <legend class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.customize.columns') }}</legend>
              @for (item of columns; track item) {
                <label>
                  <input type="checkbox" [checked]="showsColumn(view, item)" (change)="toggleColumn(item)" />
                  {{ i18n.t('hypervisor.v2.col.' + item) }}
                </label>
              }
            </fieldset>
            @for (stratum of strata; track stratum.id) {
              <fieldset class="hv2-fieldset">
                <legend class="ck-mono hv2-kicker">{{ i18n.t(stratum.label) }}</legend>
                @for (block of assembledBlocks(view, stratum.id); track block.type) {
                  <div
                    class="hv2-block-row"
                    [attr.data-testid]="'hypervisor-customize-block-' + block.type"
                    tabindex="0"
                    (keydown)="onCustomizeKeydown($event, stratum.id, block.type)"
                  >
                    <span>{{ i18n.t('hypervisor.v2.block.' + block.type) }}</span>
                    <button type="button" class="hv2-text-btn" (click)="moveBlock(stratum.id, block.type, -1)" [attr.aria-label]="i18n.t('hypervisor.v2.customize.move_up')">↑</button>
                    <button type="button" class="hv2-text-btn" (click)="moveBlock(stratum.id, block.type, 1)" [attr.aria-label]="i18n.t('hypervisor.v2.customize.move_down')">↓</button>
                    <button type="button" class="hv2-text-btn" (click)="removeBlock(stratum.id, block.type)" [attr.aria-label]="i18n.t('hypervisor.v2.customize.remove')">×</button>
                  </div>
                }
              </fieldset>
            }
          </div>
          <div class="hv2-customize-catalog" data-testid="hypervisor-customize-catalog">
            <p class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.customize.catalog') }}</p>
            @for (stratum of strata; track stratum.id) {
              <fieldset class="hv2-fieldset">
                <legend class="ck-mono hv2-kicker">{{ i18n.t(stratum.label) }}</legend>
                @for (block of stratum.blocks; track block) {
                  <label>
                    <input type="checkbox" [checked]="showsBlock(view, stratum.id, block)" (change)="toggleBlock(stratum.id, block)" />
                    {{ i18n.t('hypervisor.v2.block.' + block) }}
                  </label>
                }
              </fieldset>
            }
          </div>
        </div>
        @if (canEdit()) {
          <button type="button" class="hv2-text-btn" (click)="saveViews()" [disabled]="savingViews()">
            {{ i18n.t('hypervisor.v2.customize.save') }}
          </button>
        }
      }
    </ck-panel>
  `,
  styles: [`
    :host { display: block; color: var(--ck-fg-1); position: relative; }
    :host.hv2-theme-presentation { --hv2-presentation-mark: var(--sentinel-accent, #65d66e); }
    :host.hv2-theme-presentation ::ng-deep .ck-label {
      color: var(--hv2-presentation-mark) !important;
    }
    .hv2-presentation-liseré {
      height: 2px;
      margin: -8px -32px 16px;
      background: var(--hv2-presentation-mark, var(--sentinel-accent, #65d66e));
    }
    :host.hv2-theme-presentation .hv2-monument { font-size: 112px; }
    :host.hv2-theme-presentation .hv2-presentation-num { font-size: 48px; font-weight: 600; letter-spacing: -0.04em; line-height: 1; color: var(--ck-fg-1); }
    :host.hv2-theme-presentation .hv2-presentation-warn { color: var(--ck-signal-warn, #f1b45a); }
    .hv2-presentation { display: flex; flex-direction: column; gap: 28px; }
    .hv2-presentation-kpis {
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 24px;
      padding: 8px 0 4px;
    }
    .hv2-presentation-kpi { min-width: 0; display: flex; flex-direction: column; gap: 10px; }
    .hv2-presentation-summary { margin: 0; font-size: 14px; line-height: 1.45; color: var(--ck-fg-2); max-width: 52rem; }
    .hv2-presentation-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .hv2-presentation-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
    .hv2-presentation-list li {
      display: flex; align-items: baseline; justify-content: space-between; gap: 16px;
      font-size: 14px; color: var(--ck-fg-1);
    }
    .hv2-presentation-status { font-size: 12px; font-weight: 600; white-space: nowrap; }
    .hv2-presentation-status[data-tone='neg'] { color: var(--ck-signal-neg, #f06476); }
    .hv2-presentation-status[data-tone='warn'] { color: var(--ck-signal-warn, #f1b45a); }
    .hv2-presentation-status[data-tone='pos'] { color: var(--ck-signal-pos); }
    .hv2-actions, .hv2-list-row, .hv2-block-row, .hv2-btn-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .hv2-customize-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 24px;
      align-items: start;
    }
    .hv2-customize-assembly, .hv2-customize-catalog { min-width: 0; }
    .hv2-agent-orb {
      display: inline-block;
      width: 8px;
      height: 8px;
      margin-right: 8px;
      border: 2px solid var(--ck-fg-1);
      background: transparent;
      vertical-align: middle;
    }
    .hv2-basis-absent { border-bottom: 1px dotted var(--ck-stroke-2); }
    .hv2-posed { font-size: 11px; margin-top: 4px; }
    .hv2-basis-contract {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--ck-stroke-2);
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .hv2-journal-entry { display: flex; flex-direction: column; gap: 4px; padding: 8px 0; border-bottom: 1px solid var(--ck-stroke-2); }
    .hv2-journal-effect { color: var(--ck-fg-2); font-size: 12px; }
    :host.hv2-theme-presentation .hv2-btn,
    :host.hv2-theme-presentation .hv2-btn-primary { display: none; }
    :host.hv2-theme-presentation .hv2-agent-orb { display: none; }
    .hv2-stack { display: flex; flex-direction: column; gap: 20px; }
    .hv2-switch { display: flex; gap: 4px; padding: 4px; background: var(--ck-bg-panel); border: 1px solid var(--ck-stroke-2); border-radius: 8px; }
    .hv2-switch button, .hv2-text-btn {
      background: transparent; border: 0; color: var(--ck-fg-3); cursor: pointer; border-radius: 6px;
      font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; padding: 6px 10px;
    }
    .hv2-text-btn:disabled { cursor: default; opacity: 0.5; }
    .hv2-switch-on { color: var(--ck-fg-1); background: var(--ck-bg-inset); outline: 1px solid var(--ck-stroke-strong); }
    .hv2-legend {
      display: flex; justify-content: flex-end; font-size: 11px; color: var(--ck-fg-3);
      margin: -6px 0 14px; letter-spacing: 0.02em;
    }
    .hv2-page { display: flex; flex-direction: column; gap: 36px; position: relative; }
    .hv2-stratum { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 24px; align-items: start; }
    .hv2-body { min-width: 0; display: flex; flex-direction: column; gap: 0; }
    .hv2-leader { display: flex; flex-direction: column; gap: 4px; padding-top: 4px; }
    .hv2-leader-bar { display: block; width: 2px; height: 28px; background: var(--ck-signal-cool); margin-bottom: 6px; }
    .hv2-leader-num { font-size: 11px; color: var(--ck-fg-3); }
    .hv2-leader-title { margin: 0; font-size: 13px; font-weight: 600; color: var(--ck-fg-1); }
    .hv2-leader-sub { margin: 0; font-size: 11px; line-height: 1.4; color: var(--ck-fg-3); }

    .hv2-hero {
      display: grid; grid-template-columns: 246px 360px minmax(0, 1fr); align-items: stretch; gap: 10px;
      margin-inline: -32px;
      padding: 26px 28px 22px;
      background: var(--ck-bg-inset);
      border-block: 1px solid var(--ck-stroke-2);
    }
    .hv2-hero-text { display: flex; flex-direction: column; justify-content: space-between; gap: 18px; min-width: 0; }
    .hv2-hero-dial { display: flex; flex-direction: column; align-items: center; gap: 4px; }
    .hv2-hero-flow { min-width: 0; display: flex; flex-direction: column; }
    .hv2-hero-flow ck-chart-sankey-flow { margin-top: auto; }
    .hv2-hero:has([data-testid="hypervisor-v2-unites"]) {
      grid-template-columns: minmax(280px, 1.15fr) minmax(220px, 0.9fr) minmax(240px, 1fr);
      align-items: start;
      gap: 28px;
    }
    .hv2-unites { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
    .hv2-unites-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
    .hv2-unites-row {
      display: grid; grid-template-columns: 4.6rem minmax(0, 1fr) 96px;
      gap: 8px 12px; align-items: center;
    }
    .hv2-unites-value {
      font-size: 22px; font-weight: 600; letter-spacing: -0.03em; line-height: 1;
      text-align: right; color: var(--ck-fg-1);
    }
    .hv2-unites-meta { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
    .hv2-unites-unit {
      font-size: 13px; line-height: 1.25; color: var(--ck-fg-1);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .hv2-unites-systems { font-size: 10px; color: var(--ck-fg-3); }
    .hv2-unites-row ck-chart-unit-dots { justify-self: end; }
    .hv2-hero-couverture, .hv2-hero-decision {
      min-width: 0; display: flex; flex-direction: column; gap: 10px; padding: 4px 0;
    }
    .hv2-hero-couverture .hv2-link { margin-top: auto; }
    .hv2-card.hv2-hero-signal { align-self: stretch; }
    .hv2-kicker { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ck-fg-3); margin: 0 0 10px; }
    .hv2-monument-group { margin: 4px 0 0; }
    .hv2-monument-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
    .hv2-monument-figure { display: inline-flex; align-items: baseline; gap: 8px; white-space: nowrap; }
    .hv2-measured-part { font-size: 12px; line-height: 1.3; letter-spacing: 0.02em; color: var(--ck-fg-1); white-space: nowrap; }
    .hv2-monument { font-size: 88px; font-weight: 600; letter-spacing: -0.05em; line-height: 0.9; color: var(--ck-fg-1); }
    .hv2-monument-state { font-size: 22px; letter-spacing: 0.08em; line-height: 1.2; color: var(--ck-fg-2); }
    .hv2-monument-unit { font-size: 34px; font-weight: 500; color: var(--ck-fg-3); }
    .hv2-sentence { display: block; margin: 12px 0 0; font-size: 17px; line-height: 1.3; color: var(--ck-fg-2); }
    .hv2-sub { margin: 6px 0 0; font-size: 12px; line-height: 1.4; color: var(--ck-fg-3); }
    .hv2-provenance-block { display: flex; flex-direction: column; gap: 12px; }
    /* No overflow clip: the segments are focusable and the keyboard ring sits
       outside them. The ends round themselves instead. */
    .hv2-provenance { display: flex; height: 6px; border-radius: 3px; background: var(--ck-stroke-2); }
    .hv2-provenance > :first-child { border-radius: 3px 0 0 3px; }
    .hv2-provenance > :last-child { border-radius: 0 3px 3px 0; }
    .hv2-provenance > :only-child { border-radius: 3px; }
    .hv2-provenance-ink { background: var(--ck-fg-1); }
    /* Declared share: a light teal tint over the track (12 %, so the lines keep
       3:1 on it) under a 45° hatch of the declared ink — readable without
       colour, and unlike a link or a filled button. */
    .hv2-provenance-teal {
      background-color: color-mix(in srgb, var(--ck-data-declared) 12%, transparent);
      background-image: repeating-linear-gradient(-45deg, var(--ck-data-declared) 0 2px, transparent 2px 5px);
    }
    .hv2-provenance-legend { display: flex; justify-content: space-between; gap: 8px; font-size: 10px; color: var(--ck-fg-2); }
    .hv2-teal { color: var(--ck-signal-cool); }
    .hv2-peak-card { border: 1px solid var(--ck-stroke-2); background: var(--ck-bg-panel); padding: 10px 12px; border-radius: 8px; display: flex; flex-direction: column; gap: 6px; transition: background 120ms var(--ck-ease-out, ease-out); }
    .hv2-peak-lit { background: var(--ck-bg-inset); }
    .hv2-peak-kicker { font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ck-fg-3); display: flex; align-items: center; gap: 6px; }
    .hv2-dot-teal { width: 6px; height: 6px; border-radius: 50%; background: var(--ck-signal-cool); display: inline-block; }
    .hv2-peak-row { display: flex; align-items: baseline; gap: 8px; }
    .hv2-peak-value { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; color: var(--ck-fg-1); }
    .hv2-peak-detail { font-size: 11px; color: var(--ck-fg-3); }
    .hv2-peak-split { display: flex; gap: 12px; font-size: 10px; color: var(--ck-fg-2); }
    .hv2-facts { margin: 0; display: flex; flex-direction: column; gap: 6px; padding-top: 10px; border-top: 1px solid var(--ck-stroke-2); }
    .hv2-facts-plain { border-top: 0; padding-top: 0; margin: 10px 0 14px; }
    .hv2-fact { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin: 0; }
    .hv2-fact dt { font-size: 12px; color: var(--ck-fg-2); }
    .hv2-fact dd { margin: 0; font-size: 12px; color: var(--ck-fg-1); }
    .hv2-card-head-wrap { flex-wrap: wrap; }
    .hv2-facts-aside { border-top: 0; padding-top: 0; min-width: min(100%, 320px); }
    .hv2-facts-aside .hv2-fact dt, .hv2-facts-aside .hv2-fact dd { font-size: 13px; }
    .hv2-fact-share { color: var(--ck-fg-2); margin-left: 4px; }
    .hv2-degraded-page { display: flex; flex-direction: column; gap: 14px; }
    .hv2-unavailable {
      display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px 16px;
      padding: 12px 14px; border: 1px dashed var(--ck-stroke-strong); border-left: 2px solid var(--ck-signal-warn);
      border-radius: 8px; background: var(--ck-bg-panel);
    }
    .hv2-unavailable-copy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
    .hv2-unavailable-kicker { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ck-fg-3); }
    .hv2-unavailable-text { margin: 0; font-size: 13px; line-height: 1.4; color: var(--ck-fg-1); }
    /* Inside a card the card is the frame: no second box, same copy and action. */
    .hv2-card .hv2-unavailable { padding: 0; border: 0; border-radius: 0; background: transparent; }
    .hv2-degraded-page > .hv2-card { max-width: 640px; }
    .hv2-retry {
      min-height: 32px; padding: 6px 14px; border-radius: 6px; border: 1px solid var(--ck-stroke-strong);
      background: transparent; color: var(--ck-fg-1); font-size: 12px; cursor: pointer;
    }
    .hv2-retry:hover { background: var(--ck-bg-inset); }
    .hv2-retry[aria-disabled='true'] { cursor: progress; color: var(--ck-fg-3); }
    .hv2-presentation-state { font-size: 16px; letter-spacing: 0.08em; line-height: 48px; color: var(--ck-fg-2); }
    .hv2-chart-caption { font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ck-fg-3); text-align: center; }
    .hv2-flow-title { margin: 0 0 6px; font-size: 15px; font-weight: 600; line-height: 1.3; color: var(--ck-fg-1); }
    .hv2-flow-explainer { margin: 0 0 12px; font-size: 11px; line-height: 1.45; color: var(--ck-fg-3); max-width: 420px; }

    .hv2-under { display: flex; gap: 14px; align-items: stretch; margin-inline: -32px; padding: 18px 28px 26px; }
    .hv2-rivers { flex: 2 1 0; min-width: 0; }
    .hv2-hors { flex: 1 1 0; min-width: 0; border-style: dashed; display: flex; flex-direction: column; gap: 10px; }
    .hv2-card { border: 1px solid var(--ck-stroke-2); border-radius: 10px; background: var(--ck-bg-panel); padding: 16px 18px; }
    .hv2-card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
    .hv2-card-title { margin: 0; font-size: 14px; font-weight: 600; line-height: 1.3; color: var(--ck-fg-1); }
    .hv2-card-sub { margin: 3px 0 0; font-size: 11px; line-height: 1.4; color: var(--ck-fg-3); }
    .hv2-card-legend { font-size: 10px; color: var(--ck-fg-3); white-space: nowrap; }
    .hv2-hors-title { margin: 0; font-size: 16px; font-weight: 600; line-height: 1.3; color: var(--ck-fg-1); }
    .hv2-hors-list { display: flex; flex-direction: column; gap: 12px; }
    .hv2-hors-row { display: flex; flex-direction: column; gap: 5px; padding: 4px 6px; margin: 0 -6px; border-radius: 6px; transition: background 120ms var(--ck-ease-out, ease-out); }
    .hv2-hors-line { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
    .hv2-hors-name { font-size: 12px; color: var(--ck-fg-1); }
    .hv2-hors-value { font-size: 11px; color: var(--ck-fg-1); white-space: nowrap; }
    .hv2-link { color: var(--ck-signal-cool); text-decoration: none; font-size: 12px; }
    .hv2-link:hover { text-decoration: underline; }
    .hv2-hors .hv2-link { margin-top: auto; padding-top: 6px; font-size: 12px; }

    .hv2-register { padding: 16px 18px 10px; }
    .hv2-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .hv2-table thead th {
      text-align: left; padding: 6px 10px 8px; border-bottom: 1px solid var(--ck-stroke-2);
      font-size: 9.5px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500; color: var(--ck-fg-3);
    }
    .hv2-table td, .hv2-table tfoot th { text-align: left; padding: 10px 10px; border-bottom: 1px solid var(--ck-stroke-2); vertical-align: middle; }
    .hv2-table tfoot th { font-size: 12px; font-weight: 600; color: var(--ck-fg-1); }
    .hv2-table tfoot td, .hv2-table tfoot th { border-bottom: 0; border-top: 1px solid var(--ck-stroke-strong); padding-top: 12px; font-size: 12px; }
    .hv2-num { text-align: right !important; white-space: nowrap; }
    .hv2-arrow-col { width: 28px; text-align: right !important; }
    .hv2-arrow { color: var(--ck-fg-3); text-decoration: none; font-size: 14px; }
    .hv2-arrow:hover { color: var(--ck-fg-1); }
    .hv2-system { display: flex; align-items: center; gap: 10px; }
    .hv2-system-name { font-size: 13px; font-weight: 500; color: var(--ck-fg-1); display: inline-flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .hv2-came-from { font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ck-signal-cool); font-weight: 500; }
    .hv2-system-meta { font-size: 10px; color: var(--ck-fg-3); margin-top: 2px; }
    .hv2-up { text-transform: uppercase; letter-spacing: 0.08em; }
    .hv2-result-value { font-size: 12px; color: var(--ck-fg-1); }
    .hv2-result-qualifier { font-size: 11px; color: var(--ck-fg-3); margin-left: 6px; }
    .hv2-basis { font-size: 11px; color: var(--ck-fg-2); white-space: nowrap; }
    .hv2-row-outside .hv2-system-name { color: var(--ck-fg-2); }
    .hv2-glyph {
      display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
      width: 28px; height: 28px; border-radius: 6px;
      border: 1px solid var(--ck-stroke-strong); font-size: 10px; letter-spacing: 0.06em; color: var(--ck-fg-2);
    }
    .hv2-glyph[data-health='pos'] { border-color: var(--ck-signal-pos); }
    .hv2-glyph[data-health='warn'] { border-color: var(--ck-signal-warn); }
    .hv2-glyph[data-health='neg'] { border-color: var(--ck-signal-neg); }
    .hv2-row-focus { background: var(--ck-bg-inset); }
    .hv2-table tbody tr { transition: background 120ms var(--ck-ease-out, ease-out); }
    .hv2-row-lit { background: var(--ck-bg-inset); }
    .hv2-row-flash { outline: 1px solid var(--ck-signal-cool); outline-offset: -1px; }
    /* The entering class sits on the host: only :host() matches it under
       emulated encapsulation. Tokens v2 home entrance, first rows staggered. */
    :host(.hv2-enter) .hv2-register tbody tr,
    :host(.hv2-enter) .hv2-cards3 > .hv2-card {
      animation: hv2FadeUp var(--ck-dur-med, 200ms) var(--ck-ease-out, ease-out) both;
      animation-delay: calc(min(var(--stagger, 0), 3) * 30ms);
    }
    @keyframes hv2FadeUp {
      from { opacity: 0; transform: translateY(8px); }
    }
    @media (prefers-reduced-motion: reduce) {
      :host(.hv2-enter) .hv2-register tbody tr,
      :host(.hv2-enter) .hv2-cards3 > .hv2-card { animation: none; }
      .hv2-table tbody tr, .hv2-hors-row, .hv2-peak-card { transition: none; }
    }

    .hv2-cards3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
    .hv2-cards3 .hv2-card { display: flex; flex-direction: column; gap: 10px; }
    .hv2-cards3 .hv2-kicker { margin: 0; }
    .hv2-card-signal { border-left: 2px solid var(--ck-signal-warn); }
    .hv2-card-decision { border-left: 2px solid var(--ck-signal-cool); }
    .hv2-card-bases { border-style: dashed; }
    .hv2-btn {
      display: inline-flex; align-items: center; justify-content: center; align-self: flex-start;
      padding: 6px 12px; border-radius: 6px; border: 1px solid var(--ck-stroke-strong);
      background: transparent; color: var(--ck-fg-1); font-size: 12px; cursor: pointer; text-decoration: none;
    }
    .hv2-btn-primary { background: var(--ck-fg-1); color: var(--ck-bg-base); border-color: var(--ck-fg-1); }
    .hv2-bases-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
    .hv2-bases-row { display: flex; align-items: baseline; gap: 10px; font-size: 12px; }
    .hv2-bases-row > span:first-child { flex: 1 1 auto; color: var(--ck-fg-1); }
    .hv2-bases-row .ck-mono { font-size: 11px; }
    .hv2-footnote { margin: auto 0 0; padding-top: 10px; border-top: 1px solid var(--ck-stroke-2); font-size: 11px; line-height: 1.45; color: var(--ck-fg-3); }
    .hv2-count { font-size: 11px; color: var(--ck-fg-3); margin-left: 6px; }
    .hv2-grow { flex: 1 1 auto; }
    .hv2-muted { font-size: 12px; color: var(--ck-fg-4); }
    .hv2-error { color: var(--ck-signal-neg); font-size: 12px; }
    .hv2-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
    .hv2-list-row { padding: 6px 0; border-bottom: 1px solid var(--ck-stroke-2); }
    .hv2-fieldset { border: 1px solid var(--ck-stroke-2); padding: 10px 12px; margin: 0 0 12px; display: flex; flex-direction: column; gap: 6px; }
    .hv2-edit { display: flex; flex-direction: column; gap: 6px; min-width: 180px; }
    .hv2-edit input, .hv2-edit select {
      width: 100%; background: var(--ck-bg-inset); color: var(--ck-fg-1);
      border: 1px solid var(--ck-stroke-2); padding: 4px 6px;
    }
    @media (max-width: 1240px) {
      .hv2-hero { grid-template-columns: 246px minmax(0, 1fr); }
      .hv2-hero-flow { grid-column: 1 / -1; }
      .hv2-under { flex-direction: column; }
    }
    @media (max-width: 900px) {
      .hv2-stratum { grid-template-columns: 1fr; gap: 12px; }
      .hv2-hero { margin-inline: -14px; padding-inline: 14px; grid-template-columns: 1fr; }
      .hv2-hero-flow { grid-column: auto; }
      .hv2-under { margin-inline: -14px; padding-inline: 14px; }
      .hv2-cards3 { grid-template-columns: 1fr; }
    }
  `],
})
export class HypervisorV2Component implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService);
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly api = inject(CanonicalApiService);
  private readonly http = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.reset(),
    () => this.reload(),
  );

  readonly viewPeriod = viewPeriod;
  readonly showsColumn = showsColumn;
  readonly showsBlock = showsBlock;
  readonly measuredMark = MARK_MEASURED;
  readonly declaredMark = MARK_DECLARED;
  readonly denominators: readonly HypervisorViewDenominator[] = ['hours', 'runs', 'value'];
  readonly periods = ['30d', '90d'] as const;
  readonly columns = REGISTER_COLUMNS;
  readonly sorts = VIEW_SORTS;
  readonly strata: ReadonlyArray<{ id: HypervisorStratumId; label: string; blocks: readonly string[] }> = [
    { id: 'comprendre', label: 'hypervisor.v2.customize.stratum.comprendre', blocks: COMPRENDRE_BLOCKS },
    { id: 'detailler', label: 'hypervisor.v2.customize.stratum.detailler', blocks: DETAILLER_BLOCKS },
    { id: 'decider', label: 'hypervisor.v2.customize.stratum.decider', blocks: DECIDER_BLOCKS },
  ];

  readonly loading = signal(true);
  readonly loadProblem = signal<string | null>(null);
  /** One state per data source, so a failed request only degrades its own blocks. */
  readonly sourceStates = signal<ImpactSourceStates>(LOADING_SOURCES);
  /** Polite announcement once a retried source is back (its inline block is gone). */
  readonly sourceAnnouncement = signal('');
  readonly views = signal<HypervisorNamedView[]>([]);
  readonly canEdit = signal(false);
  readonly activeViewId = signal('direction');
  readonly activeImpactViewId = signal<ImpactViewId | null>(null);
  readonly meetingEventId = signal<string | null>(null);
  readonly impactSelectedZone = signal<string | null>(null);
  readonly expandedBasisId = signal<string | null>(null);
  readonly mapAttribution = signal('OpenStreetMap contributors / CARTO');
  readonly activeFacet = signal<HypervisorFacetId>('synthese');
  readonly presentationTheme = signal(false);
  readonly focusCapabilityId = signal<string | null>(null);
  readonly series = signal<HypervisorSeriesView | null>(null);
  readonly bases = signal<HypervisorValueBasisItem[]>([]);
  readonly capabilities = signal<Capability[]>([]);
  readonly catalogLocked = signal<ReadonlySet<string>>(new Set());
  readonly recommendations = signal<Recommendation[]>([]);
  readonly decisions = signal<DecisionRow[]>([]);
  readonly signals = signal<HypervisorSignal[]>([]);
  /** Live Mission Room payloads for generic Impact blocks (honest empty when absent). */
  readonly impactTimeline = signal<ImpactTimelineRaw | null>(null);
  readonly impactNews = signal<ImpactNewsRaw | null>(null);
  readonly impactMap = signal<ImpactMapRaw | null>(null);
  readonly impactMonitor = signal<ImpactMonitorRaw | null>(null);
  readonly impactMacro = signal<ImpactMacroRaw | null>(null);
  readonly customizeOpen = signal(false);
  readonly historyOpen = signal(false);
  readonly scanning = signal(false);
  readonly savingViews = signal(false);
  readonly savingBasis = signal(false);
  readonly basisError = signal(false);
  readonly editingId = signal<string | null>(null);
  readonly draft = signal<BasisDraft | null>(null);
  readonly hoverDay = signal<number | null>(null);
  readonly hoverSystem = signal<string | null>(null);
  readonly flashSystem = signal<string | null>(null);
  readonly cameFromSystem = signal<string | null>(null);
  readonly arrival = signal<ArrivalProvenance | null>(null);
  readonly arrivalChipLabel = computed(() => {
    const provenance = this.arrival();
    if (!provenance || provenance.kind === 'see_in_impact') return null;
    if (provenance.kind !== 'system' && provenance.kind !== 'object' && provenance.kind !== 'impact_registre') {
      return null;
    }
    return arrivalProvenanceLabel(provenance, (key, params) => this.i18n.t(key, params));
  });
  readonly arrivalBackHref = computed(() => this.arrival()?.backUrl || '');
  readonly entering = signal(false);
  readonly monumentValue = signal('');
  readonly pageTipOpen = signal(false);
  readonly pageTipTitle = signal('');
  readonly pageTipLines = signal<CkChartTipLine[]>([]);
  readonly pageTipX = signal(0);
  readonly pageTipY = signal(0);

  readonly activeView = computed(() =>
    this.views().find((view) => view.id === this.activeViewId()) ?? this.views()[0] ?? null,
  );
  readonly activeImpactView = computed(() => impactGenericView(this.activeImpactViewId()));
  readonly switcherViews = computed(() => {
    const portfolio = this.views();
    if (this.activeFacet() !== 'synthese') return portfolio;
    return [...portfolio, ...IMPACT_GENERIC_VIEWS.map(cloneView)];
  });
  readonly switcherActiveId = computed(() => this.activeImpactViewId() ?? this.activeViewId());
  readonly impactComprendreBlocks = computed(() => this.activeImpactView()?.strata.comprendre ?? []);
  readonly journalEntries = computed(() => {
    return this.decisions()
      .filter((row) => row.status === 'applied' || row.status === 'accepted')
      .map((row) => ({
        id: row.id,
        title: row.title,
        at: row.applied_at || row.created_at || null,
        effect: typeof row.effect === 'string' ? row.effect : null,
      }));
  });
  readonly registerRows = computed(() => {
    const view = this.series();
    const active = this.activeView();
    if (!view) return [];
    return sortRegisterRows(view.register, active?.sort ?? 'name');
  });
  readonly staleRows = computed(() => {
    const view = this.series();
    if (!view) return [];
    return view.register.filter((row) => view.staleSystemIds.includes(row.systemId));
  });
  readonly proposedDecisions = computed(() => this.decisions().filter((row) => row.status === 'proposed'));
  readonly firstProposed = computed(() => this.proposedDecisions()[0] ?? null);
  readonly historyDecisions = computed(() => this.decisions().filter((row) => row.status !== 'proposed'));
  /** Recommendations by title, minus those already materialised as a decision. */
  readonly recommendationGroups = computed<RecommendationGroup[]>(() => {
    const taken = new Set(this.decisions().map((row) => normaliseTitle(row.title)));
    const groups = new Map<string, RecommendationGroup>();
    for (const item of this.recommendations()) {
      const key = normaliseTitle(item.title);
      if (taken.has(key)) continue;
      const group = groups.get(key);
      if (group) group.count += 1;
      else groups.set(key, { item, count: 1 });
    }
    return [...groups.values()];
  });

  /** Bound as properties so the chart primitives can call them without `this`. */
  readonly quantityLabel = (value: number): string => this.formatQuantity(value);
  readonly moneyLabel = (value: number): string => this.formatMoney(value, this.series()?.currency, 0);
  readonly sparkTip = (value: number): string => this.i18n.t('hypervisor.v2.spark.tip', {
    value: this.formatNumber(value, Math.abs(value) < 10 ? 1 : 0),
  });
  readonly pulseTip = (value: number, index: number): string => this.i18n.t('hypervisor.v2.pulse.tip', {
    date: this.formatDate(this.series()?.dates[index]),
    value: this.formatNumber(value, 0),
  });

  readonly radialDays = computed((): CkRadialDay[] => {
    const view = this.series();
    if (!view) return [];
    this.i18n.locale();
    return view.days.map((day) => {
      const total = day.measured + day.declared;
      const lines: CkChartTipLine[] = [
        { label: this.i18n.t('hypervisor.v2.tip.label.total'), value: this.formatQuantity(total) },
      ];
      if (day.measured > 0) {
        lines.push({
          label: '',
          value: this.i18n.t('hypervisor.v2.tip.measured', {
            mark: MARK_MEASURED,
            value: this.formatQuantity(day.measured),
          }),
        });
      }
      if (day.declared > 0) {
        lines.push({
          label: '',
          value: this.i18n.t('hypervisor.v2.tip.declared', {
            mark: MARK_DECLARED,
            value: this.formatQuantity(day.declared),
          }),
        });
      }
      lines.push({ label: this.i18n.t('hypervisor.v2.tip.label.runs'), value: this.formatNumber(day.runs, 0) });
      lines.push({ label: this.i18n.t('hypervisor.v2.tip.label.systems'), value: this.formatNumber(day.systems, 0) });
      const title = this.formatDate(day.date, true);
      return {
        measured: day.measured,
        declared: day.declared,
        weekend: day.weekend,
        dateLabel: title,
        shortLabel: this.formatDate(day.date),
        runs: day.runs,
        systems: day.systems,
        tip: { title, lines },
        aria: [title, ...lines.map((line) => `${line.label} ${line.value}`.trim())].join(' · '),
      };
    });
  });

  readonly radialTicks = computed((): CkChartTick[] => {
    this.i18n.locale();
    return (this.series()?.ticks ?? [])
      .filter((tick) => tick.kind === 'week')
      .map((tick) => ({ index: tick.index, label: this.tickLabel(tick), anchor: 'middle' as const }));
  });

  readonly streamTicks = computed((): CkChartTick[] => {
    this.i18n.locale();
    return (this.series()?.ticks ?? []).map((tick) => ({
      index: tick.index,
      label: this.tickLabel(tick),
      anchor: tick.anchor,
    }));
  });

  readonly dayLabels = computed((): string[] => {
    this.i18n.locale();
    return (this.series()?.dates ?? []).map((date) => this.formatDate(date, true));
  });

  readonly streamSeries = computed((): CkStreamSeries[] => {
    this.i18n.locale();
    return (this.series()?.streams ?? []).map((row) => ({
      id: row.systemId,
      label: row.label,
      detail: `${this.formatQuantity(row.total)} ${row.tone === 'declared' || row.tone === 'declared-soft' ? MARK_DECLARED : MARK_MEASURED}`,
      values: row.values,
      tone: row.tone,
    }));
  });

  readonly costStreamSeries = computed((): CkStreamSeries[] => {
    this.i18n.locale();
    return (this.series()?.costStreams ?? []).map((row) => ({
      id: row.systemId,
      label: row.label,
      detail: this.formatMoney(row.total, this.series()?.currency, 0),
      values: row.values,
      tone: row.tone,
    }));
  });

  readonly streamPeak = computed((): CkStreamPeak | null => {
    const peak = this.series()?.peak;
    if (!peak) return null;
    this.i18n.locale();
    return { index: peak.index, label: `${this.formatQuantity(peak.total)} · ${this.formatDate(peak.date)}` };
  });

  readonly sankeySources = computed((): CkSankeySource[] => {
    const view = this.series();
    if (!view) return [];
    this.i18n.locale();
    const byId = new Map(view.register.map((row) => [row.systemId, row]));
    return view.sankey.map((row) => {
      const register = byId.get(row.systemId);
      const lines: CkChartTipLine[] = [
        { label: this.i18n.t('hypervisor.v2.tip.label.runs'), value: `${this.formatNumber(row.runs, 0)} ${this.i18n.t('hypervisor.v2.unit.runs')}` },
        { label: this.i18n.t('hypervisor.v2.tip.label.outcomes'), value: this.outcomeLabel(row) },
      ];
      const hours = availableNumber(register?.hours);
      const value = availableNumber(register?.valueDeclared);
      if (hours != null) {
        lines.push({ label: this.i18n.t('hypervisor.v2.tip.label.hours'), value: this.formatQuantity(hours) });
      }
      if (value != null) {
        lines.push({
          label: this.i18n.t('hypervisor.v2.tip.label.value'),
          value: this.formatMoney(value, register?.currency ?? view.currency, 0),
        });
      }
      const basis = row.basisStatus && row.basisStatus !== 'none' ? row.basisStatus : 'none';
      lines.push({
        label: this.i18n.t('hypervisor.v2.tip.label.basis'),
        value: this.i18n.t(`hypervisor.v2.register.basis_state.${basis}`),
      });
      return {
        id: row.systemId,
        label: row.label,
        detail: `${this.formatNumber(row.runs, 0)} ${this.i18n.t('hypervisor.v2.unit.runs')}`,
        value: row.runs,
        ...(row.outsideDenominator ? { stubLabel: `${this.outcomeLabel(row)} ${MARK_NONE}` } : {}),
        tip: { title: row.label, lines },
      };
    });
  });

  readonly sankeyMiddleTip = computed(() => {
    const view = this.series();
    if (!view) return null;
    this.i18n.locale();
    const converting = view.sankey.filter((row) => !row.outsideDenominator).length;
    return {
      title: this.sankeyMiddleLabel(),
      lines: [{ label: this.i18n.t('hypervisor.v2.sankey.tip.aggregates', { count: converting }), value: '' }],
    };
  });

  readonly sankeyRightTip = computed(() => {
    const view = this.series();
    if (!view) return null;
    this.i18n.locale();
    const converting = view.sankey.filter((row) => !row.outsideDenominator).length;
    return {
      title: this.sankeyRightLabel(),
      lines: [{ label: this.i18n.t('hypervisor.v2.sankey.tip.aggregates', { count: converting }), value: '' }],
    };
  });

  private readonly sourceGenerations: Record<ImpactSourceId, number> = { series: 0, bases: 0, decisions: 0, recos: 0 };
  private readonly applySourceOutcome: { [K in ImpactSourceId]: (outcome: SourceOutcome<ImpactSourceValues[K]>) => void } = {
    series: (outcome) => {
      const value = outcome.ok ? outcome.value : null;
      this.lastSeries = value;
      this.series.set(value ? projectSeries(value, viewDenominator(this.activeView())) : null);
      this.markSource('series', outcome.ok ? 'ready' : 'unavailable');
    },
    bases: (outcome) => {
      this.bases.set(outcome.ok ? outcome.value : []);
      this.markSource('bases', outcome.ok ? 'ready' : 'unavailable');
    },
    decisions: (outcome) => {
      this.decisions.set(outcome.ok ? outcome.value : []);
      this.markSource('decisions', outcome.ok ? 'ready' : 'unavailable');
    },
    recos: (outcome) => {
      this.recommendations.set(outcome.ok ? outcome.value : []);
      this.markSource('recos', outcome.ok ? 'ready' : 'unavailable');
    },
  };
  private routeSub: Subscription | null = null;
  private impactLiveSub: Subscription | null = null;
  private impactLiveGeneration = 0;
  private lastSeries: HypervisorSeriesResponse | null = null;
  private painted = false;
  private enterTimer: ReturnType<typeof setTimeout> | null = null;
  private flashTimer: ReturnType<typeof setTimeout> | null = null;
  private monumentRaf = 0;

  ngOnInit(): void {
    const provenance = readArrivalProvenance();
    this.arrival.set(provenance);
    if (provenance?.kind === 'system' || provenance?.kind === 'object') {
      this.cameFromSystem.set(provenance.systemId || null);
    }
    this.routeSub = this.route.queryParamMap.subscribe((params) => {
      const facet = params.get('facet');
      this.activeFacet.set(isHypervisorFacet(facet) ? facet : 'synthese');
      this.focusCapabilityId.set(params.get('capabilityId'));
      const theme = params.get('theme');
      this.presentationTheme.set(theme === 'presentation');
      const impactView = parseImpactViewQuery(params.get('view'));
      this.activeImpactViewId.set(impactView);
      this.meetingEventId.set(params.get('eventId'));
      if (impactView && this.activeFacet() !== 'synthese') {
        this.activeFacet.set('synthese');
      }
      this.reloadImpactLive();
    });
    this.reload();
  }

  ngOnDestroy(): void {
    this.routeSub?.unsubscribe();
    this.impactLiveSub?.unsubscribe();
    this.workspaceView.destroy();
    this.stopMonument();
    if (this.enterTimer) clearTimeout(this.enterTimer);
    if (this.flashTimer) clearTimeout(this.flashTimer);
  }

  onDayHover(index: number | null): void {
    if (this.hoverDay() === index) return;
    this.hoverDay.set(index);
  }

  onSystemHover(id: string | null): void {
    if (this.hoverSystem() === id) return;
    this.hoverSystem.set(id);
  }

  onSystemClick(id: string): void {
    this.onSystemHover(id);
    const row = this.host.nativeElement.querySelector(
      `[data-testid="hypervisor-v2-register"] [data-system-id="${CSS.escape(id)}"]`,
    );
    if (!(row instanceof HTMLElement)) return;
    row.scrollIntoView({ block: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
    this.flashSystem.set(id);
    if (this.flashTimer) clearTimeout(this.flashTimer);
    this.flashTimer = setTimeout(() => {
      if (this.flashSystem() === id) this.flashSystem.set(null);
    }, 600);
  }

  onProvenanceTip(kind: 'measured' | 'declared', event: Event): void {
    const title = kind === 'measured' ? this.provenanceMeasuredTip() : this.provenanceDeclaredTip();
    this.showPageTip(title, event);
  }

  clearPageTip(): void {
    this.pageTipOpen.set(false);
  }

  provenanceMeasuredTip(): string {
    const view = this.series();
    const prov = this.provenance();
    if (!view || !prov) return '';
    return this.i18n.t('hypervisor.v2.hero.provenance.measured_tip', {
      mark: MARK_MEASURED,
      pct: prov.measuredPct,
      value: this.formatQuantity(view.measuredTotal),
    });
  }

  provenanceDeclaredTip(): string {
    const view = this.series();
    const prov = this.provenance();
    if (!view || !prov) return '';
    return this.i18n.t('hypervisor.v2.hero.provenance.declared_tip', {
      mark: MARK_DECLARED,
      pct: prov.declaredPct,
      value: this.formatQuantity(view.declaredTotal),
    });
  }

  dotsTip(row: HypervisorRegisterRow): string {
    return this.i18n.t('hypervisor.v2.hors.units_tip', {
      count: this.outcomeCount(row),
      n: this.unitsPerDot(),
      unit: row.outputUnit ?? this.i18n.t('hypervisor.v2.unit.units'),
    });
  }

  private showPageTip(title: string, event: Event): void {
    const page = this.host.nativeElement.querySelector('.hv2-page');
    const origin = page instanceof HTMLElement ? page : this.host.nativeElement;
    const target = event.target instanceof HTMLElement ? event.target : origin;
    const hostRect = origin.getBoundingClientRect();
    const rect = target.getBoundingClientRect();
    this.pageTipTitle.set(title);
    this.pageTipLines.set([]);
    this.pageTipX.set(rect.left + rect.width / 2 - hostRect.left);
    this.pageTipY.set(rect.top - hostRect.top);
    this.pageTipOpen.set(true);
  }

  @HostListener('document:keydown', ['$event'])
  onKey(event: KeyboardEvent): void {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'e') {
      event.preventDefault();
      this.customizeOpen.set(true);
      return;
    }
    if (event.key === 'Escape' && this.presentationTheme() && this.canExitPresentationTheme()) {
      event.preventDefault();
      this.exitPresentationTheme();
    }
  }

  enterPresentationTheme(): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { theme: 'presentation' },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  exitPresentationTheme(): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { theme: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /** Escape exits only when no menu, panel or tooltip is open. */
  private canExitPresentationTheme(): boolean {
    if (this.customizeOpen() || this.pageTipOpen()) return false;
    if (typeof document === 'undefined') return true;
    if (document.querySelector('[role="menu"], [role="listbox"], [aria-expanded="true"]')) {
      return false;
    }
    return true;
  }

  onFacetChange(id: string): void {
    if (!isHypervisorFacet(id) || id === this.activeFacet()) return;
    this.activeFacet.set(id);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet: id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  basesLink(capabilityId: string): NavLinkInput {
    return { facet: 'bases', capabilityId };
  }

  basesFacetLink(): NavLinkInput {
    return { facet: 'bases' };
  }

  decisionsFacetLink(): NavLinkInput {
    return { facet: 'decisions' };
  }

  registreFacetLink(): NavLinkInput {
    return { facet: 'registre' };
  }

  systemLink(row: HypervisorRegisterRow): NavLinkInput {
    return { type: 'system', ref: row.systemId };
  }

  registreProvenanceState(): Record<string, ArrivalProvenance> {
    return arrivalProvenanceState({
      kind: 'impact_registre',
      backUrl: this.router.url,
    });
  }

  onArrivalBack(): void {
    const back = this.arrival()?.backUrl;
    if (back) void this.router.navigateByUrl(back);
  }

  horsDeclareLink(): NavLinkInput | null {
    const row = this.series()?.outside.find((item) => item.capabilityId);
    return row?.capabilityId ? this.basesLink(row.capabilityId) : null;
  }

  viewLabel(view: HypervisorNamedView): string {
    const key = `hypervisor.v2.view.${view.id}`;
    const label = this.i18n.t(key);
    return label === key ? view.label : label;
  }

  // --- Page frame ---------------------------------------------------------

  pageEyebrow(): string {
    if (this.presentationTheme()) {
      return this.i18n.t('hypervisor.v2.theme.eyebrow');
    }
    return this.i18n.t('hypervisor.v2.page.eyebrow');
  }

  pageTitle(): string {
    if (this.presentationTheme()) {
      return this.i18n.t('hypervisor.v2.theme.title');
    }
    return this.i18n.t('hypervisor.v2.page.title');
  }

  presentationRuns(): string {
    const view = this.series();
    if (!view) return '—';
    const total = availableNumber(view.unitsTotal);
    if (total == null) {
      const summed = view.register.reduce((sum, row) => sum + (availableNumber(row.runs) ?? 0), 0);
      return this.formatNumber(summed, 0);
    }
    return this.formatNumber(total, 0);
  }

  presentationDecideRows(): Array<{ id: string; label: string; meta: string }> {
    this.i18n.locale();
    const rows: Array<{ id: string; label: string; meta: string }> = [];
    for (const item of this.proposedDecisions().slice(0, 5)) {
      rows.push({
        id: item.id,
        label: item.title,
        meta: this.formatDate(item.created_at, true),
      });
    }
    for (const group of this.recommendationGroups().slice(0, 5 - rows.length)) {
      rows.push({
        id: group.item.id,
        label: group.item.title,
        meta: group.count > 1 ? `×${group.count}` : '',
      });
    }
    return rows;
  }

  presentationWatchRows(): Array<{ id: string; label: string; status: string; tone: 'neg' | 'warn' | 'pos' }> {
    this.i18n.locale();
    const stale = this.staleRows().slice(0, 5).map((row) => ({
      id: row.systemId,
      label: row.name,
      status: this.i18n.t('hypervisor.v2.theme.watch.stale'),
      tone: 'warn' as const,
    }));
    if (stale.length) return stale;
    return this.registerRows().slice(0, 5).map((row) => ({
      id: row.systemId,
      label: row.name,
      status: row.outsideDenominator
        ? this.i18n.t('hypervisor.v2.theme.watch.outside')
        : this.i18n.t('hypervisor.v2.theme.watch.ready'),
      tone: row.outsideDenominator ? 'neg' as const : 'pos' as const,
    }));
  }

  pageSummary(): string {
    const view = this.series();
    if (!view) return this.i18n.t('hypervisor.v2.page.description');
    const capabilities = new Set(view.register.map((row) => row.capabilityId).filter(Boolean)).size;
    return this.i18n.t('hypervisor.v2.page.summary', {
      systems: view.register.length,
      capabilities: capabilities || this.bases().length,
      days: view.dates.length,
      date: this.formatDate(view.to),
      view: this.viewLabel(this.activeView() ?? DEFAULT_HYPERVISOR_VIEWS[0]!),
    });
  }

  denominator(): HypervisorDenominator {
    return viewDenominator(this.activeView());
  }

  periodLabel(): string {
    return this.i18n.t(`hypervisor.v2.period.${viewPeriod(this.activeView())}`);
  }

  dayCount(): number {
    return this.series()?.dates.length ?? 0;
  }

  showStratum(stratum: HypervisorStratumId): boolean {
    const view = this.activeView();
    return Boolean(view?.strata[stratum]?.length);
  }

  showBlock(stratum: HypervisorStratumId, block: string): boolean {
    return showsBlock(this.activeView(), stratum, block);
  }

  showHero(): boolean {
    return (
      this.showBlock('comprendre', 'monument')
      || this.showBlock('comprendre', 'provenance')
      || this.showBlock('comprendre', 'cadran')
      || this.showBlock('comprendre', 'sankey')
      || this.showBlock('comprendre', 'unites')
      || this.showBlock('comprendre', 'couverture')
      || this.showBlock('comprendre', 'signal')
      || this.showBlock('comprendre', 'decisions')
    );
  }

  showCol(column: string): boolean {
    return showsColumn(this.activeView(), column);
  }

  // --- Hero ---------------------------------------------------------------

  monument(): { value: string; unit: string } | null {
    const view = this.series();
    const value = availableNumber(view?.monument);
    if (view == null || value == null) return null;
    const denominator = this.denominator();
    if (denominator === 'value') {
      return { value: this.formatNumber(value, 0), unit: this.currencySymbol(view.currency) };
    }
    return {
      value: this.formatNumber(value, value < 10 ? 1 : 0),
      unit: denominator === 'hours' ? this.i18n.t('hypervisor.v2.unit.hours_short') : this.i18n.t('hypervisor.v2.unit.runs'),
    };
  }

  heroSentence(): string {
    return this.i18n.t(`hypervisor.v2.hero.sentence.${this.denominator()}`, { days: this.dayCount() });
  }

  /** The measured share, shown right next to the monument number. */
  measuredPart(): string {
    const prov = this.provenance();
    if (!prov) return '';
    return this.i18n.t(`hypervisor.v2.hero.measured_part.${this.denominator()}`, { pct: prov.measuredPct });
  }

  /**
   * The monument read as one sentence by screen readers, with the final
   * value (never the count-up frames): "2 496 heures de travail attribuées
   * aux agents en 91 jours, dont 38 % mesurées".
   */
  monumentLabel(): string {
    const mon = this.monument();
    if (!mon) return '';
    const amount = this.denominator() === 'value' ? `${mon.value} ${mon.unit}`.trim() : mon.value;
    const sentence = this.heroSentence();
    const measured = this.measuredPart();
    return measured
      ? this.i18n.t('hypervisor.v2.hero.monument_label_measured', { amount, sentence, measured })
      : this.i18n.t('hypervisor.v2.hero.monument_label', { amount, sentence });
  }

  heroSub(): string {
    const view = this.series();
    if (!view) return '';
    return this.i18n.t(`hypervisor.v2.hero.sub.${this.denominator()}`, {
      inside: view.register.length - view.outside.length,
      total: view.register.length,
    });
  }

  provenance(): { measured: number; declared: number; measuredPct: string; declaredPct: string } | null {
    const view = this.series();
    if (!view) return null;
    const total = view.measuredTotal + view.declaredTotal;
    if (total <= 0) return null;
    return {
      measured: view.measuredTotal / total,
      declared: view.declaredTotal / total,
      measuredPct: this.formatPercent(view.measuredTotal / total),
      declaredPct: this.formatPercent(view.declaredTotal / total),
    };
  }

  peakCard(): { date: string; total: string; detail: string; measured: string; declared: string } | null {
    const peak = this.series()?.peak;
    if (!peak) return null;
    return {
      date: this.formatDate(peak.date, true),
      total: this.formatQuantity(peak.total),
      detail: this.i18n.t('hypervisor.v2.hero.peak.detail', {
        runs: this.formatNumber(peak.runs, 0),
        systems: peak.systems,
      }),
      measured: peak.measured > 0 ? this.formatQuantity(peak.measured) : '',
      declared: peak.declared > 0 ? this.formatQuantity(peak.declared) : '',
    };
  }

  costFact(): string {
    const fact = this.series()?.costTotal;
    if (!fact) return '';
    const value = availableNumber(fact);
    if (value == null) return this.factLabel(fact);
    return `${this.formatMoney(value, this.series()?.currency, 0)} ${MARK_MEASURED}`;
  }

  valueFact(): string {
    const fact = this.series()?.valueTotal;
    if (!fact) return '';
    const value = availableNumber(fact);
    if (value == null) return this.factLabel(fact);
    return `≈ ${this.formatMoney(value, this.series()?.currency, 0, true)} ${MARK_DECLARED}`;
  }

  ratioFact(): string {
    const fact = this.series()?.ratio;
    if (!fact) return '';
    const value = availableNumber(fact);
    if (value == null) return this.factLabel(fact);
    return `× ${this.formatNumber(value, 1)} ${MARK_DECLARED}`;
  }

  /** Share of the declared value that rests on a declared (not measured) basis. */
  valueDeclaredShare(): string {
    const view = this.series();
    if (!view) return '';
    let total = 0;
    let declared = 0;
    for (const row of view.register) {
      const value = availableNumber(row.valueDeclared);
      if (value == null || value <= 0) continue;
      total += value;
      if (row.basisStatus !== 'measured') declared += value;
    }
    if (total <= 0) return '';
    return this.i18n.t('hypervisor.v2.metric.ratio_declared_share', { pct: this.formatPercent(declared / total) });
  }

  // --- Charts -------------------------------------------------------------

  rangeLabel(): string {
    const view = this.series();
    if (!view) return '';
    return `${this.formatDate(view.from)} → ${this.formatDate(view.to)}`;
  }

  sankeyMiddleLabel(): string {
    const mon = this.monument();
    return mon ? `${mon.value} ${mon.unit} ${MARK_MEASURED}` : '';
  }

  sankeyRightLabel(): string {
    const fact = this.series()?.valueTotal;
    const value = availableNumber(fact);
    if (value == null) return '';
    return `≈ ${this.formatMoney(value, this.series()?.currency, 0, true)} ${MARK_DECLARED}`;
  }

  sankeyExplainer(): string {
    const rows = this.series()?.sankey ?? [];
    if (!rows.length) return this.i18n.t('hypervisor.v2.sankey.empty');
    const joined = rows.filter((row) => !row.outsideDenominator).length;
    const stopped = rows.length - joined;
    const unit = this.i18n.t(`hypervisor.v2.in.${this.denominator()}`);
    const parts = [this.i18n.t('hypervisor.v2.sankey.width')];
    if (joined === 1) parts.push(this.i18n.t('hypervisor.v2.sankey.join_one', { unit }));
    else if (joined > 1) parts.push(this.i18n.t('hypervisor.v2.sankey.join', { count: joined, unit }));
    if (stopped === 1) parts.push(this.i18n.t('hypervisor.v2.sankey.stop_one'));
    else if (stopped > 1) parts.push(this.i18n.t('hypervisor.v2.sankey.stop', { count: stopped }));
    return parts.join(' ');
  }

  riversTitle(): string {
    return this.i18n.t(`hypervisor.v2.rivers.title.${this.denominator()}`);
  }

  riversLegend(): string {
    return this.denominator() === 'runs'
      ? this.i18n.t('hypervisor.v2.rivers.legend_runs')
      : this.i18n.t('hypervisor.v2.rivers.legend');
  }

  cadranLegend(): string {
    return this.denominator() === 'runs'
      ? this.i18n.t('hypervisor.v2.cadran.legend_runs')
      : this.i18n.t('hypervisor.v2.cadran.legend');
  }

  nativeUnits(): HypervisorNativeUnit[] {
    return this.series()?.nativeUnits ?? [];
  }

  nativeUnitsPerDot(): number {
    const max = Math.max(0, ...this.nativeUnits().map((group) => group.total));
    const needed = max / MAX_UNIT_DOTS;
    return NICE_DOT_STEPS.find((step) => step >= needed) ?? Math.ceil(needed);
  }

  nativeUnitLabel(unit: string | null | undefined): string {
    return humanizeOutputUnit(unit, this.i18n.t('hypervisor.v2.unit.units'));
  }

  unitesNote(): string {
    const groups = this.nativeUnits();
    if (groups.length < 2) return this.i18n.t('hypervisor.v2.unites.note_one');
    return this.i18n.t('hypervisor.v2.unites.note', {
      left: this.nativeUnitLabel(groups[0]!.unit),
      right: this.nativeUnitLabel(groups[1]!.unit),
    });
  }

  unitesSystems(group: HypervisorNativeUnit): string {
    return group.systems.length === 1
      ? this.i18n.t('hypervisor.v2.unites.systems_one')
      : this.i18n.t('hypervisor.v2.unites.systems', { count: group.systems.length });
  }

  unitesDotsTip(group: HypervisorNativeUnit): string {
    return this.i18n.t('hypervisor.v2.unites.dots', {
      n: this.nativeUnitsPerDot(),
      unit: this.nativeUnitLabel(group.unit),
    });
  }

  missingBasisRows(): HypervisorRegisterRow[] {
    return (this.series()?.register ?? []).filter((row) => !row.basisStatus || row.basisStatus === 'none');
  }

  couvertureTitle(): string {
    const missing = this.missingBasisRows().length;
    if (missing === 0) return this.i18n.t('hypervisor.v2.couverture.title_none');
    return this.i18n.t('hypervisor.v2.couverture.title', {
      declared: this.declaredCount(),
      missing,
    });
  }

  couvertureDeclare(): string {
    const count = this.missingBasisRows().length;
    return count === 1
      ? this.i18n.t('hypervisor.v2.couverture.declare_one')
      : this.i18n.t('hypervisor.v2.couverture.declare', { count });
  }

  horsTitle(): string {
    const count = this.series()?.outside.length ?? 0;
    const key = this.denominator() === 'value' ? 'value' : 'hours';
    return count === 1
      ? this.i18n.t(`hypervisor.v2.hors.title.${key}_one`)
      : this.i18n.t(`hypervisor.v2.hors.title.${key}`, { count });
  }

  outcomeCount(row: Pick<HypervisorRegisterRow, 'outcomes'>): number {
    return availableNumber(row.outcomes) ?? 0;
  }

  outcomeLabel(row: Pick<HypervisorRegisterRow, 'outcomes' | 'outputUnit'>): string {
    const value = availableNumber(row.outcomes);
    if (value == null) return this.factLabel(row.outcomes);
    return `${this.formatNumber(value, 0)} ${this.nativeUnitLabel(row.outputUnit)}`.trim();
  }

  outcomeMark(row: Pick<HypervisorRegisterRow, 'outcomes'>): string {
    return availableNumber(row.outcomes) == null ? MARK_NONE : MARK_MEASURED;
  }

  /** Units per dot so the longest hors-dénominateur row stays within 24 dots. */
  unitsPerDot(): number {
    const max = Math.max(0, ...(this.series()?.outside ?? []).map((row) => this.outcomeCount(row)));
    const needed = max / MAX_UNIT_DOTS;
    return NICE_DOT_STEPS.find((step) => step >= needed) ?? Math.ceil(needed);
  }

  dotsTitle(row: HypervisorRegisterRow): string {
    return this.i18n.t('hypervisor.v2.hors.dots_title', {
      n: this.unitsPerDot(),
      unit: row.outputUnit ?? this.i18n.t('hypervisor.v2.unit.units'),
    });
  }

  // --- Register -----------------------------------------------------------

  registerSub(): string {
    const view = this.series();
    if (!view) return '';
    const sort = this.i18n.t(`hypervisor.v2.sort.${this.activeView()?.sort ?? 'name'}`).toLocaleLowerCase(this.localeTag());
    const unit = this.i18n.t(`hypervisor.v2.in.${this.denominator()}`);
    const outside = view.outside.length;
    if (!outside) return this.i18n.t('hypervisor.v2.register.sub_all', { sort, unit });
    return this.i18n.t('hypervisor.v2.register.sub', {
      sort,
      unit,
      inside: view.register.length - outside,
      outside,
    });
  }

  runsWord(row: HypervisorRegisterRow): string {
    return (availableNumber(row.runs) ?? 0) > 0
      ? this.i18n.t('hypervisor.v2.register.operated')
      : this.i18n.t('hypervisor.v2.register.silent');
  }

  runsLabel(row: HypervisorRegisterRow): string {
    return `${this.formatNumber(availableNumber(row.runs) ?? 0, 0)} ${this.i18n.t('hypervisor.v2.unit.runs')}`;
  }

  resultMain(row: HypervisorRegisterRow): string {
    const denominator = this.denominator();
    if (row.outsideDenominator || denominator === 'runs') return this.outcomeLabel(row);
    if (denominator === 'value') {
      const value = availableNumber(row.valueDeclared);
      if (value == null) return this.factLabel(row.valueDeclared);
      return this.i18n.t('hypervisor.v2.register.result.value', { value: this.formatMoney(value, row.currency ?? this.series()?.currency, 0) });
    }
    const hours = availableNumber(row.hours);
    if (hours == null) return this.factLabel(row.hours);
    return this.i18n.t('hypervisor.v2.register.result.hours', { value: this.formatQuantity(hours) });
  }

  resultQualifier(row: HypervisorRegisterRow): string {
    if (row.outsideDenominator || this.denominator() === 'runs') {
      return availableNumber(row.outcomes) == null
        ? ''
        : `· ${this.i18n.t('hypervisor.v2.register.qualifier.outcome')} ${MARK_MEASURED}`;
    }
    const fact = this.denominator() === 'value' ? row.valueDeclared : row.hours;
    if (availableNumber(fact) == null) return '';
    return row.basisStatus === 'measured'
      ? `· ${this.i18n.t('hypervisor.v2.register.qualifier.measured')} ${MARK_MEASURED}`
      : `· ${this.i18n.t('hypervisor.v2.register.qualifier.declared')} ${MARK_DECLARED}`;
  }

  sparkTone(row: HypervisorRegisterRow): CkChartTone {
    if (this.denominator() === 'runs') return 'ink';
    if (row.outsideDenominator) return 'muted';
    return row.basisStatus === 'measured' ? 'ink' : 'declared';
  }

  basisLabel(row: HypervisorRegisterRow): string {
    if (!row.basisStatus || row.basisStatus === 'none') {
      return `${MARK_NONE} ${this.i18n.t('hypervisor.v2.register.basis_state.none')}`;
    }
    const rate = this.basisRate(row);
    const state = this.i18n.t(`hypervisor.v2.register.basis_state.${row.basisStatus}`);
    return row.basisStatus === 'measured'
      ? `${rate} ${MARK_MEASURED} ${state}`.trim()
      : `≈ ${rate} ${MARK_DECLARED} ${state}`.trim();
  }

  rowValue(row: HypervisorRegisterRow): string {
    const value = availableNumber(row.valueDeclared);
    if (value == null) return `— ${this.factLabel(row.valueDeclared)}`;
    return `≈ ${this.formatMoney(value, row.currency ?? this.series()?.currency, 0)}`;
  }

  footerResult(): string {
    const view = this.series();
    if (!view) return '';
    const mon = this.monument();
    if (!mon) return this.factLabel(view.monument);
    const inside = view.register.length - view.outside.length;
    const unit = this.i18n.t(`hypervisor.v2.in.${this.denominator()}`);
    return `${mon.value} ${mon.unit} · ${this.i18n.t('hypervisor.v2.register.total_inside', { count: inside, unit })}`;
  }

  footerValue(): string {
    const view = this.series();
    if (!view) return '';
    const value = availableNumber(view.valueTotal);
    if (value == null) return this.factLabel(view.valueTotal);
    return `≈ ${this.formatMoney(value, view.currency, 0)}`;
  }

  declaredCount(): number {
    return (this.series()?.register ?? []).filter((row) => row.basisStatus === 'declared' || row.basisStatus === 'measured').length;
  }

  // --- Stratum 03 ---------------------------------------------------------

  signalKicker(): string {
    const stale = this.staleRows();
    if (!stale.length) return this.i18n.t('hypervisor.v2.signal.kicker_quiet');
    const days = Math.max(...stale.map((row) => availableNumber(row.daysSinceLastRun) ?? STALE_AFTER_DAYS));
    return this.i18n.t('hypervisor.v2.signal.kicker', { days });
  }

  signalCopy(): string {
    const stale = this.staleRows();
    if (stale.length === 0) return this.i18n.t('hypervisor.v2.signal.healthy');
    if (stale.length === 1) return this.i18n.t('hypervisor.v2.signal.stale_one', { name: stale[0]!.name });
    return this.i18n.t('hypervisor.v2.signal.stale', { count: stale.length });
  }

  signalContext(): string {
    const stale = this.staleRows();
    if (stale.length === 0) return this.i18n.t('hypervisor.v2.signal.context_healthy', { n: STALE_AFTER_DAYS });
    if (stale.length === 1) {
      const row = stale[0]!;
      return this.i18n.t('hypervisor.v2.signal.context_one', {
        days: availableNumber(row.daysSinceLastRun) ?? STALE_AFTER_DAYS,
        runs: this.formatNumber(availableNumber(row.runs) ?? 0, 0),
      });
    }
    return this.i18n.t('hypervisor.v2.signal.context_many', { count: stale.length, n: STALE_AFTER_DAYS });
  }

  basesTitle(): string {
    const count = this.series()?.outside.length ?? 0;
    if (count === 0) return this.i18n.t('hypervisor.v2.bases.title_none');
    if (count === 1) return this.i18n.t('hypervisor.v2.bases.title_one');
    return this.i18n.t('hypervisor.v2.bases.title', { count });
  }

  pendingLabel(count: number): string {
    return count === 1
      ? this.i18n.t('hypervisor.v2.decision.pending_one')
      : this.i18n.t('hypervisor.v2.decision.pending', { count });
  }

  scopeLabel(scope: string): string {
    return this.fallback(`hypervisor.scope.${scope}`, scope);
  }

  kindLabel(kind: string): string {
    return this.fallback(`hypervisor.decisions.kind.${kind}`, kind);
  }

  decisionStatus(status: string): string {
    return this.fallback(`hypervisor.decisions.status.${status}`, status);
  }

  // --- Views & editing ----------------------------------------------------

  selectView(id: string): void {
    const current = this.activeView();
    this.activeImpactViewId.set(null);
    this.activeViewId.set(id);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: null, eventId: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
    const next = this.views().find((view) => view.id === id);
    if (!current || !next) return;
    if (viewPeriod(current) !== viewPeriod(next)) this.reload();
    else if (viewDenominator(current) !== viewDenominator(next)) this.reproject();
  }

  selectImpactView(id: ImpactViewId): void {
    this.activeImpactViewId.set(id);
    this.activeFacet.set('synthese');
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: id, facet: 'synthese' },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  selectSwitcherView(id: string): void {
    if (isImpactViewId(id)) this.selectImpactView(id);
    else this.selectView(id);
  }

  assembledBlocks(view: HypervisorNamedView, stratum: HypervisorStratumId): HypervisorBlockRef[] {
    return view.strata[stratum] ?? [];
  }

  removeBlock(stratum: HypervisorStratumId, block: string): void {
    this.patchActive((view) => removeStratumBlock(view, stratum, block));
  }

  onCustomizeKeydown(event: KeyboardEvent, stratum: HypervisorStratumId, block: string): void {
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.moveBlock(stratum, block, -1);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.moveBlock(stratum, block, 1);
    } else if (event.key === 'x' || event.key === 'X' || event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      this.removeBlock(stratum, block);
    }
  }

  workspaceCurrency(): string | null {
    const settings = this.workspace.current()?.settings;
    const raw = settings?.['currency'] ?? settings?.['default_currency'];
    return typeof raw === 'string' && /^[A-Z]{3}$/.test(raw) ? raw : null;
  }

  posedByCopy(row: HypervisorValueBasisItem): string {
    const who = row.value_basis?.declared_by;
    const when = row.value_basis?.declared_at;
    if (!who || !when) return '';
    return this.i18n.t('hypervisor.v2.bases.posed_by', { who, when: this.formatDate(when) });
  }

  toggleBasisContract(id: string): void {
    this.expandedBasisId.set(this.expandedBasisId() === id ? null : id);
  }

  isAgentSuggested(row: DecisionRow): boolean {
    return row.agent_suggested === true
      || row.rationale?.['suggested_by'] === 'agent'
      || row.rationale?.['agent'] != null;
  }

  onImpactZoneSelect(zoneId: string): void {
    this.impactSelectedZone.set(this.impactSelectedZone() === zoneId ? null : zoneId);
  }

  impactEcheancierItems() {
    return mapTimelineToEcheancier(this.impactTimeline());
  }

  impactFluxItems() {
    return mapNewsToFlux(this.impactNews());
  }

  impactCarteZones() {
    return mapMapToZones(this.impactMap());
  }

  impactAlerteItems() {
    const zone = this.impactSelectedZone();
    const fromMission = mapMonitorToAlertes(this.impactMonitor(), this.impactNews());
    const items = fromMission.length ? fromMission : mapSignalsToAlertes(this.signals());
    if (!zone) return items;
    const selected = this.impactCarteZones().find((row) => row.id === zone);
    const zoneName = selected?.name;
    return items.filter((item) => item.zone === zone || item.zone === zoneName);
  }

  impactOrdrePoints() {
    const fromMeeting = mapAgendaMetadataToOrdre(this.impactTimeline(), this.meetingEventId());
    if (fromMeeting.length) return fromMeeting;
    return mapDecisionsToOrdre(this.decisions());
  }

  impactIndicateurItems() {
    const fromMacro = mapMacroToIndicateurs(this.impactMacro());
    if (fromMacro.length) return fromMacro;
    return mapRegisterToIndicateurs(this.series()?.register ?? []);
  }

  onMeetingDecision(payload: { pointId: string; optionId: string }): void {
    const eventId = this.meetingEventId();
    if (!eventId) return;
    const note = `Meeting decision · ${payload.pointId} · ${payload.optionId}`;
    this.api.createDecision({
      scope: 'portfolio',
      target_id: null,
      kind: 'meeting',
      title: note,
      notes: note,
      origin: 'meeting',
      meeting_event_id: eventId,
      agenda_item_ref: payload.pointId,
      rationale: { origin: 'meeting', option_id: payload.optionId },
    }).subscribe(() => this.reload());
  }

  setDenominator(value: HypervisorViewDenominator): void {
    this.patchActive((view) => ({ ...view, denominator: value }));
    this.reproject();
  }

  setPeriod(value: '30d' | '90d'): void {
    this.patchActive((view) => ({ ...view, period: value }));
    this.reload();
  }

  setSort(value: string): void {
    this.patchActive((view) => ({ ...view, sort: value }));
  }

  toggleColumn(column: string): void {
    this.patchActive((view) => toggleRegisterColumn(view, column));
  }

  toggleBlock(stratum: HypervisorStratumId, block: string): void {
    this.patchActive((view) => toggleStratumBlock(view, stratum, block));
  }

  moveBlock(stratum: HypervisorStratumId, block: string, direction: -1 | 1): void {
    this.patchActive((view) => moveStratumBlock(view, stratum, block, direction));
  }

  saveViews(): void {
    if (!this.canEdit()) return;
    this.savingViews.set(true);
    this.api.putHypervisorViews(serializeViewsForWrite(this.views())).subscribe({
      next: (payload) => {
        const parsed = parseViewsPayload(payload);
        this.views.set(parsed.views);
        this.canEdit.set(parsed.can_edit);
        this.savingViews.set(false);
      },
      error: (error: unknown) => {
        this.savingViews.set(false);
        if (error instanceof HttpErrorResponse && error.status === 403) this.canEdit.set(false);
      },
    });
  }

  isCatalogLocked(row: HypervisorValueBasisItem): boolean {
    if (this.catalogLocked().has(row.capability_id)) return true;
    const capability = this.capabilities().find((item) => item.id === row.capability_id);
    return capability?.workspace_scope === 'global';
  }

  startEdit(row: HypervisorValueBasisItem): void {
    this.basisError.set(false);
    this.editingId.set(row.capability_id);
    this.draft.set({
      unit: row.value_basis?.unit || row.output_unit || '',
      hours_per_unit: row.value_basis?.hours_per_unit != null ? String(row.value_basis.hours_per_unit) : '',
      value_per_unit: row.value_basis?.value_per_unit != null ? String(row.value_basis.value_per_unit) : '',
      currency: row.value_basis?.currency || this.workspaceCurrency() || '',
      status: row.value_basis?.status ?? 'declared',
      note: row.value_basis?.note || '',
    });
  }

  patchDraft(key: keyof BasisDraft, event: Event): void {
    const current = this.draft();
    if (!current) return;
    const target = event.target as HTMLInputElement | HTMLSelectElement;
    this.draft.set({ ...current, [key]: target.value });
  }

  saveBasis(row: HypervisorValueBasisItem): void {
    const draft = this.draft();
    if (!draft) return;
    this.savingBasis.set(true);
    this.basisError.set(false);
    this.api.putCapabilityValueBasis(row.capability_id, {
      unit: draft.unit,
      hours_per_unit: draft.hours_per_unit === '' ? null : Number(draft.hours_per_unit),
      value_per_unit: draft.value_per_unit === '' ? null : Number(draft.value_per_unit),
      currency: draft.currency,
      status: draft.status,
      note: draft.note || null,
    }).subscribe({
      next: (item) => {
        this.bases.update((list) => list.map((entry) => entry.capability_id === item.capability_id ? { ...entry, ...item } : entry));
        this.editingId.set(null);
        this.savingBasis.set(false);
        this.reload();
      },
      error: (error: unknown) => {
        this.savingBasis.set(false);
        if (error instanceof HttpErrorResponse && error.status === 404) {
          this.catalogLocked.update((set) => new Set([...set, row.capability_id]));
          this.editingId.set(null);
          return;
        }
        this.basisError.set(true);
      },
    });
  }

  scanRecommendations(): void {
    this.scanning.set(true);
    this.api.generateProactiveRecommendations({ since_days: 7 }).subscribe({
      next: () => {
        this.scanning.set(false);
        this.reload();
      },
      error: () => this.scanning.set(false),
    });
  }

  accept(row: DecisionRow): void {
    this.api.acceptDecision(row.id).subscribe(() => this.reload());
  }

  reject(row: DecisionRow): void {
    this.api.rejectDecision(row.id).subscribe(() => this.reload());
  }

  // --- Formatting ---------------------------------------------------------

  formatFact(fact: SeriesFact, kind: 'currency' | 'quantity'): string {
    const value = availableNumber(fact);
    if (value == null) return this.factLabel(fact);
    if (kind === 'currency') return this.formatMoney(value, this.series()?.currency, 0);
    return this.formatQuantity(value);
  }

  /** Money in the active locale; `compact` renders `55,9 k€` past 10 000. */
  formatMoney(
    value: number | null | undefined,
    currency: string | null | undefined,
    digits = 2,
    compact = false,
  ): string {
    if (value == null) return '';
    const code = currency && /^[A-Z]{3}$/.test(currency) ? currency : null;
    const options: Intl.NumberFormatOptions = compact && Math.abs(value) >= 10_000
      ? { notation: 'compact', maximumFractionDigits: 1 }
      : { maximumFractionDigits: digits };
    if (code) {
      options.style = 'currency';
      options.currency = code;
    }
    return new Intl.NumberFormat(this.localeTag(), options).format(value);
  }

  formatNumber(value: number, digits = 2): string {
    return new Intl.NumberFormat(this.localeTag(), { maximumFractionDigits: digits }).format(value);
  }

  /** A denominator quantity with its unit: `71 h`, `0,8 h`, `212 unités`, `1 284 €`. */
  formatQuantity(value: number): string {
    const denominator = this.denominator();
    if (denominator === 'value') return this.formatMoney(value, this.series()?.currency, 0);
    const number = this.formatNumber(value, Math.abs(value) < 10 ? 1 : 0);
    const unit = denominator === 'hours' ? this.i18n.t('hypervisor.v2.unit.hours_short') : this.i18n.t('hypervisor.v2.unit.runs');
    return `${number} ${unit}`;
  }

  formatPercent(share: number): string {
    return new Intl.NumberFormat(this.localeTag(), { style: 'percent', maximumFractionDigits: 0 }).format(share);
  }

  formatMaybeNumber(value: number | null | undefined): string {
    return value == null ? '' : this.formatNumber(value);
  }

  /** `9 août` / `Aug 9`; with `weekday`, `mar. 25 août` / `Tue, Aug 25`. */
  formatDate(iso: string | null | undefined, weekday = false): string {
    if (!iso) return '';
    const key = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso : iso.slice(0, 10);
    const date = new Date(`${key}T12:00:00Z`);
    if (Number.isNaN(date.getTime())) return iso;
    return new Intl.DateTimeFormat(this.localeTag(), {
      day: 'numeric',
      month: 'short',
      timeZone: 'UTC',
      ...(weekday ? { weekday: 'short' } : {}),
    }).format(date);
  }

  factLabel(fact: SeriesFact): string {
    return this.i18n.t(`hypervisor.state.${fact.state}`);
  }

  basisStatusLabel(status: HypervisorValueBasisStatus): string {
    return this.i18n.t(`hypervisor.v2.bases.status.${status}`);
  }

  provenanceCopy(row: HypervisorValueBasisItem): string {
    const who = row.value_basis?.declared_by;
    const when = row.value_basis?.declared_at;
    if (!who && !when) return '';
    return this.i18n.t('hypervisor.v2.bases.declared_by', { who: who || '', when: when ? this.formatDate(when) : '' });
  }

  systemNames(row: HypervisorValueBasisItem): string {
    return (row.systems ?? []).map((item) => item.name).join(', ');
  }

  private tickLabel(tick: HypervisorChartTick): string {
    return tick.kind === 'week'
      ? this.i18n.t('hypervisor.v2.tick.week', { week: tick.isoWeek })
      : this.formatDate(tick.date);
  }

  private basisRate(row: HypervisorRegisterRow): string {
    const basis = this.bases().find((item) => item.capability_id === row.capabilityId)?.value_basis;
    if (!basis) return '';
    const currency = basis.currency ?? row.currency ?? this.series()?.currency;
    const unit = basis.unit || row.outputUnit || this.i18n.t('hypervisor.v2.unit.units');
    if (basis.hours_per_unit && basis.value_per_unit != null && this.denominator() === 'hours') {
      return `${this.formatMoney(basis.value_per_unit / basis.hours_per_unit, currency, 0)} / ${this.i18n.t('hypervisor.v2.unit.hours_short')}`;
    }
    if (basis.value_per_unit != null) return `${this.formatMoney(basis.value_per_unit, currency, 0)} / ${unit}`;
    if (basis.hours_per_unit != null) return `${this.formatNumber(basis.hours_per_unit, 2)} ${this.i18n.t('hypervisor.v2.unit.hours_short')} / ${unit}`;
    return '';
  }

  private currencySymbol(currency: string | null | undefined): string {
    const code = currency && /^[A-Z]{3}$/.test(currency) ? currency : null;
    if (!code) return '';
    const part = new Intl.NumberFormat(this.localeTag(), { style: 'currency', currency: code })
      .formatToParts(0)
      .find((item) => item.type === 'currency');
    return part?.value ?? code;
  }

  private fallback(key: string, raw: string): string {
    const label = this.i18n.t(key);
    return label === key ? raw : label;
  }

  private localeTag(): string {
    return this.i18n.locale() === 'en' ? 'en-US' : 'fr-FR';
  }

  private patchActive(mutate: (view: HypervisorNamedView) => HypervisorNamedView): void {
    const current = this.activeView();
    if (!current) return;
    this.views.set(replaceView(this.views(), mutate(cloneView(current))));
  }

  private reproject(): void {
    const raw = this.lastSeries;
    if (!raw) return;
    this.series.set(projectSeries(raw, viewDenominator(this.activeView())));
    this.syncMonument(false);
  }

  private reset(): void {
    this.series.set(null);
    this.bases.set([]);
    this.decisions.set([]);
    this.recommendations.set([]);
    this.signals.set([]);
    this.impactTimeline.set(null);
    this.impactNews.set(null);
    this.impactMap.set(null);
    this.impactMonitor.set(null);
    this.impactMacro.set(null);
    this.sourceStates.set(LOADING_SOURCES);
    this.sourceAnnouncement.set('');
    this.editingId.set(null);
    this.painted = false;
    this.entering.set(false);
    this.monumentValue.set('');
    this.hoverDay.set(null);
    this.hoverSystem.set(null);
    this.stopMonument();
  }

  reload(): void {
    const request = this.workspaceView.beginRequest();
    const period = viewPeriod(this.activeView() ?? DEFAULT_HYPERVISOR_VIEWS[0]);
    const sources = impactSourceRequests(this.http, period);
    this.loading.set(true);
    this.loadProblem.set(null);
    // Each block source settles on its own: one failure never blanks the page.
    forkJoin({
      series: settleSource(sources.series()),
      bases: settleSource(sources.bases()),
      decisions: settleSource(sources.decisions()),
      recos: settleSource(sources.recos()),
      views: this.api.hypervisorViews().pipe(catchError(() => of(null))),
      capabilities: this.api.listCapabilities().pipe(catchError(() => of([] as Capability[]))),
      balance: this.api.hypervisorBalanceSheet(period === '90d' ? 'rolling_90d' : 'rolling_30d').pipe(
        catchError(() => of(null)),
      ),
      mapSettings: this.api.hypervisorMapSettings().pipe(catchError(() => of(null))),
    }).subscribe((bundle) => {
      if (!this.workspaceView.isCurrent(request)) return;
      const problem = impactPageProblem(bundle);
      if (problem) {
        this.loadProblem.set(problem);
        this.loading.set(false);
        return;
      }
      const parsed = parseViewsPayload(bundle.views);
      this.views.set(parsed.views);
      this.canEdit.set(parsed.can_edit);
      if (bundle.mapSettings?.attribution) {
        this.mapAttribution.set(bundle.mapSettings.attribution);
      }
      if (!parsed.views.some((view) => view.id === this.activeViewId())) {
        this.activeViewId.set(parsed.views[0]?.id ?? 'direction');
      }
      if (viewPeriod(this.activeView()) !== period) {
        this.reload();
        return;
      }
      this.applySourceOutcome.series(bundle.series);
      this.applySourceOutcome.bases(bundle.bases);
      this.applySourceOutcome.decisions(bundle.decisions);
      this.applySourceOutcome.recos(bundle.recos);
      this.capabilities.set(bundle.capabilities);
      this.signals.set(bundle.balance?.signals ?? []);
      this.sourceAnnouncement.set('');
      this.loading.set(false);
      this.afterSeriesPaint();
      this.reloadImpactLive();
    });
  }

  sourceName(id: ImpactSourceId): string {
    return this.i18n.t(`hypervisor.v2.source.name.${id}`);
  }

  sourceRetrying(id: ImpactSourceId): boolean {
    return this.sourceStates()[id] === 'loading';
  }

  /** Re-requests only the failed source; the other blocks stay as they are. */
  retrySource(id: ImpactSourceId): void {
    if (this.sourceRetrying(id)) return;
    const scope = this.workspaceView.captureRequest();
    const generation = ++this.sourceGenerations[id];
    const period = viewPeriod(this.activeView() ?? DEFAULT_HYPERVISOR_VIEWS[0]);
    this.sourceAnnouncement.set('');
    this.markSource(id, 'loading');
    this.settleOne(id, impactSourceRequests(this.http, period)[id](), scope, generation);
  }

  private settleOne<K extends ImpactSourceId>(
    id: K,
    request: Observable<ImpactSourceValues[K]>,
    scope: ReturnType<WorkspaceViewContext['captureRequest']>,
    generation: number,
  ): void {
    settleSource(request).subscribe((outcome) => {
      if (!this.workspaceView.isCurrent(scope) || generation !== this.sourceGenerations[id]) return;
      this.applySourceOutcome[id](outcome);
      if (id === 'series') this.afterSeriesPaint();
      if (outcome.ok) {
        this.sourceAnnouncement.set(this.i18n.t('hypervisor.v2.source.loaded', { source: this.sourceName(id) }));
      }
    });
  }

  private markSource(id: ImpactSourceId, state: ImpactSourceState): void {
    this.sourceStates.update((states) => withSourceState(states, id, state));
  }

  private afterSeriesPaint(): void {
    const firstPaint = !this.painted && this.series() != null;
    if (this.series()) this.painted = true;
    this.syncMonument(firstPaint);
    if (firstPaint) this.beginEntrance();
    const cameFrom = this.cameFromSystem();
    if (cameFrom && firstPaint) {
      queueMicrotask(() => this.onSystemClick(cameFrom));
    }
  }

  /** Fetch Mission Room payloads only when a generic Impact view is open. */
  private reloadImpactLive(): void {
    this.impactLiveSub?.unsubscribe();
    this.impactLiveSub = null;
    const generation = ++this.impactLiveGeneration;
    if (!this.activeImpactViewId()) {
      this.impactTimeline.set(null);
      this.impactNews.set(null);
      this.impactMap.set(null);
      this.impactMonitor.set(null);
      this.impactMacro.set(null);
      return;
    }
    const scope = this.workspaceView.captureRequest();
    this.impactLiveSub = forkJoin({
      timeline: this.http.get<ImpactTimelineRaw>('/mission-room/timeline').pipe(
        catchError((): Observable<ImpactTimelineRaw | null> => of(null)),
      ),
      news: this.http.get<ImpactNewsRaw>('/mission-room/news').pipe(
        catchError((): Observable<ImpactNewsRaw | null> => of(null)),
      ),
      map: this.http.get<ImpactMapRaw>('/mission-room/map').pipe(
        catchError((): Observable<ImpactMapRaw | null> => of(null)),
      ),
      monitor: this.http.get<ImpactMonitorRaw>('/mission-room/monitor').pipe(
        catchError((): Observable<ImpactMonitorRaw | null> => of(null)),
      ),
      macro: this.http.get<ImpactMacroRaw>('/mission-room/macro-indicators').pipe(
        catchError((): Observable<ImpactMacroRaw | null> => of(null)),
      ),
    }).subscribe((bundle) => {
      if (generation !== this.impactLiveGeneration) return;
      if (!this.workspaceView.isCurrent(scope)) return;
      this.impactTimeline.set(bundle.timeline);
      this.impactNews.set(bundle.news);
      this.impactMap.set(bundle.map);
      this.impactMonitor.set(bundle.monitor);
      this.impactMacro.set(bundle.macro);
    });
  }

  private beginEntrance(): void {
    if (prefersReducedMotion()) {
      this.entering.set(false);
      return;
    }
    this.entering.set(true);
    if (this.enterTimer) clearTimeout(this.enterTimer);
    this.enterTimer = setTimeout(() => this.entering.set(false), 1600);
  }

  private syncMonument(animate: boolean): void {
    const mon = this.monument();
    const raw = availableNumber(this.series()?.monument);
    if (!mon || raw == null) {
      this.stopMonument();
      this.monumentValue.set(mon?.value ?? '');
      return;
    }
    if (!animate || prefersReducedMotion()) {
      this.stopMonument();
      this.monumentValue.set(mon.value);
      return;
    }
    this.beginCountUp(raw, mon.value, raw < 10 ? 1 : 0);
  }

  private beginCountUp(target: number, final: string, digits: number): void {
    this.stopMonument();
    this.monumentValue.set(this.formatNumber(0, digits));
    const start = performance.now();
    const step = (now: number): void => {
      const t = (now - start) / 900;
      if (t >= 1) {
        this.monumentValue.set(final);
        this.monumentRaf = 0;
        return;
      }
      this.monumentValue.set(this.formatNumber(target * easeOutProgress(t), digits));
      this.monumentRaf = requestAnimationFrame(step);
    };
    this.monumentRaf = requestAnimationFrame(step);
  }

  private stopMonument(): void {
    if (this.monumentRaf) cancelAnimationFrame(this.monumentRaf);
    this.monumentRaf = 0;
  }
}

function normaliseTitle(title: string): string {
  return title.trim().toLocaleLowerCase();
}
