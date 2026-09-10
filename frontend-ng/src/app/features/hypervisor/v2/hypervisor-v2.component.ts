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
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
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
  CkTabComponent,
  CkTabsComponent,
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
  REGISTER_COLUMNS,
  VIEW_SORTS,
  cloneView,
  moveStratumBlock,
  parseViewsPayload,
  replaceView,
  showsBlock,
  showsColumn,
  toggleRegisterColumn,
  toggleStratumBlock,
  viewDenominator,
  viewPeriod,
  type HypervisorNamedView,
  type HypervisorStratumId,
  type HypervisorViewDenominator,
} from './hypervisor-v2-views';

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
  host: { '[class.hv2-enter]': 'entering()' },
  imports: [
    NgTemplateOutlet,
    PageFrameComponent,
    OperationalObjectiveComponent,
    NavLinkDirective,
    KbdComponent,
    TagComponent,
    CkPanelComponent,
    CkTabsComponent,
    CkTabComponent,
    CkChartRadialDaysComponent,
    CkChartSankeyFlowComponent,
    CkChartStreamComponent,
    CkChartMiniAreaComponent,
    CkChartUnitDotsComponent,
    CkChartPulseComponent,
    CkChartTipComponent,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('hypervisor.v2.page.eyebrow')"
      [title]="pageTitle()"
      [description]="pageSummary()"
    >
      <div actions class="hv2-actions">
        <div class="hv2-switch" role="tablist">
          @for (view of views(); track view.id) {
            <button
              type="button"
              class="ck-mono"
              [attr.data-testid]="'hypervisor-v2-view-' + view.id"
              [class.hv2-switch-on]="view.id === activeViewId()"
              (click)="selectView(view.id)"
            >{{ viewLabel(view) }}</button>
          }
        </div>
        <button type="button" class="hv2-text-btn" (click)="customizeOpen.set(true)">
          {{ i18n.t('hypervisor.v2.customize') }}
          <ck-kbd>⌘E</ck-kbd>
        </button>
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
        <div class="hv2-facets" data-testid="hypervisor-v2-facets">
        <ck-tabs [active]="activeFacet()" (activeChange)="onFacetChange($event)">
        <ck-tab id="synthese" [label]="i18n.t('nav.facet.synthese')">
<app-operational-objective />
        <ng-container [ngTemplateOutlet]="legendTpl"></ng-container>
        @if (!series()) {
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
                                <div class="hv2-monument-row">
                                  <span class="hv2-monument ck-tnum">{{ monumentValue() }}</span>
                                  <span class="hv2-monument-unit">{{ mon.unit }}</span>
                                </div>
                                <p class="hv2-sentence">{{ heroSentence() }}</p>
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
                                <div class="hv2-fact">
                                  <dt>{{ i18n.t('hypervisor.v2.metric.ratio') }}</dt>
                                  <dd class="ck-mono ck-tnum" [class.hv2-teal]="series()!.ratio.state === 'available'" data-fact="ratio">{{ ratioFact() }}</dd>
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
        </ck-tab>

        <ck-tab id="registre" [label]="i18n.t('nav.facet.registre')">
          <ng-container [ngTemplateOutlet]="legendTpl"></ng-container>
          @if (series()) {
            <ng-container [ngTemplateOutlet]="registerTpl" [ngTemplateOutletContext]="{ testid: 'hypervisor-v2-register-registre' }"></ng-container>
          } @else {
            <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.empty') }}</p><a [navLink]="{leaf:'help-guide',params:{guideId:'value'}}">{{i18n.t('experience.adoption.help')}}</a>
          }
        </ck-tab>

        <ck-tab id="couts" [label]="i18n.t('nav.facet.couts')">
          <ng-container [ngTemplateOutlet]="legendTpl"></ng-container>
          <div class="hv2-stack">
            @if (series(); as view) {
              <article class="hv2-card">
                <header class="hv2-card-head">
                  <div>
                    <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.hero.cost') }}</h3>
                    <p class="hv2-card-sub">{{ costFact() }}</p>
                  </div>
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
        </ck-tab>

        <ck-tab id="bases" [label]="i18n.t('nav.facet.bases')">
          <ng-container [ngTemplateOutlet]="basesTpl"></ng-container>
        </ck-tab>

        <ck-tab id="decisions" [label]="i18n.t('nav.facet.decisions')">
          <div class="hv2-stack">
            <article class="hv2-card">
              <header class="hv2-card-head">
                <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.decisions.proposed') }} <span class="ck-mono hv2-count">{{ proposedDecisions().length }}</span></h3>
                <button type="button" class="hv2-text-btn" (click)="scanRecommendations()" [disabled]="scanning()">
                  {{ scanning() ? i18n.t('hypervisor.reco.scanning') : i18n.t('hypervisor.reco.scan') }}
                </button>
              </header>
              @if (proposedDecisions().length === 0) {
                <p class="hv2-muted">{{ i18n.t('hypervisor.v2.decisions.none_proposed') }}</p>
              } @else {
                <ul class="hv2-list">
                  @for (item of proposedDecisions(); track item.id) {
                    <li class="hv2-list-row">
                      <span class="hv2-grow">{{ item.title }}</span>
                      <span class="ck-mono hv2-muted">{{ formatDate(item.created_at) }}</span>
                      <button type="button" class="hv2-btn hv2-btn-primary" (click)="accept(item)">{{ i18n.t('hypervisor.v2.decision.accept') }}</button>
                      <button type="button" class="hv2-btn" (click)="reject(item)">{{ i18n.t('hypervisor.v2.decision.reject') }}</button>
                    </li>
                  }
                </ul>
              }
            </article>
            <article class="hv2-card">
              <header class="hv2-card-head">
                <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.decisions.recommendations') }} <span class="ck-mono hv2-count">{{ recommendationGroups().length }}</span></h3>
              </header>
              @if (recommendationGroups().length === 0) {
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
                <h3 class="hv2-card-title">{{ i18n.t('hypervisor.v2.decisions.history') }} <span class="ck-mono hv2-count">{{ historyDecisions().length }}</span></h3>
                @if (historyDecisions().length) {
                  <button type="button" class="hv2-text-btn" (click)="historyOpen.set(!historyOpen())" [attr.aria-expanded]="historyOpen()">
                    {{ historyOpen() ? i18n.t('hypervisor.v2.decisions.history_hide') : i18n.t('hypervisor.v2.decisions.history_show', { count: historyDecisions().length }) }}
                  </button>
                }
              </header>
              @if (historyDecisions().length === 0) {
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
        </ck-tab>

        <ck-tab id="journal" [label]="i18n.t('nav.facet.journal')">
          <article class="hv2-card">
            <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.journal.title') }}</h3>
            @if (series(); as view) {
              <ck-chart-pulse
                [values]="view.pulseValues"
                [staleFrom]="view.staleFrom"
                [startLabel]="i18n.t('hypervisor.v2.journal.start')"
                [endLabel]="i18n.t('hypervisor.v2.journal.end')"
                [zeroLabel]="i18n.t('hypervisor.v2.journal.zero')"
                [valueLabel]="pulseTip"
              />
            }
            <ul class="hv2-list">
              @for (item of signals(); track item.id) {
                <li class="hv2-list-row">
                  <ck-tag [tone]="item.tone">{{ item.label }}</ck-tag>
                </li>
              }
            </ul>
          </article>
        </ck-tab>
        </ck-tabs>
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
      @if (firstProposed(); as decision) {
        <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.decision.kicker', { date: formatDate(decision.created_at, true) }) }}</div>
        <h3 class="hv2-card-title">{{ decision.title }}</h3>
        <dl class="hv2-facts hv2-facts-plain">
          <div class="hv2-fact"><dt>{{ i18n.t('hypervisor.v2.decision.scope') }}</dt><dd>{{ scopeLabel(decision.scope) }}</dd></div>
          <div class="hv2-fact"><dt>{{ i18n.t('hypervisor.v2.decision.kind') }}</dt><dd>{{ kindLabel(decision.kind) }}</dd></div>
          @if (proposedDecisions().length > 1) {
            <div class="hv2-fact"><dt>{{ i18n.t('hypervisor.v2.decisions.proposed') }}</dt><dd>{{ pendingLabel(proposedDecisions().length - 1) }}</dd></div>
          }
        </dl>
        <div class="hv2-btn-row">
          <button type="button" class="hv2-btn hv2-btn-primary" (click)="accept(decision)">{{ i18n.t('hypervisor.v2.decision.accept') }}</button>
          <button type="button" class="hv2-btn" (click)="reject(decision)">{{ i18n.t('hypervisor.v2.decision.reject') }}</button>
        </div>
      } @else {
        <div class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.decision.kicker_none') }}</div>
        <p class="hv2-card-sub">{{ i18n.t('hypervisor.v2.decision.empty') }}</p>
      }
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
                  [class.hv2-row-flash]="flashSystem() === row.systemId"
                  [style.--stagger]="i"
                  (pointerenter)="onSystemHover(row.systemId)"
                  (pointerleave)="onSystemHover(null)"
                >
                  <td>
                    <div class="hv2-system">
                      <span class="hv2-glyph ck-mono" [attr.data-health]="row.health">{{ row.initials }}</span>
                      <div>
                        <div class="hv2-system-name">{{ row.name }}</div>
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
                    <td class="ck-mono hv2-basis" [class.hv2-teal]="row.basisStatus === 'declared'">
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
                    <a class="hv2-arrow" [navLink]="systemLink(row)" [attr.aria-label]="i18n.t('hypervisor.v2.register.open_system')" [title]="i18n.t('hypervisor.v2.register.open_system')">→</a>
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
        @if (bases().length === 0) {
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
                  <td>{{ row.name }}</td>
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
      width="420px"
    >
      @if (activeView(); as view) {
        @if (!canEdit()) {
          <p class="hv2-muted">{{ i18n.t('hypervisor.v2.customize.preview_only') }}</p>
        }
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
            @for (block of stratum.blocks; track block) {
              <div class="hv2-block-row">
                <label>
                  <input type="checkbox" [checked]="showsBlock(view, stratum.id, block)" (change)="toggleBlock(stratum.id, block)" />
                  {{ i18n.t('hypervisor.v2.block.' + block) }}
                </label>
                <button type="button" class="hv2-text-btn" (click)="moveBlock(stratum.id, block, -1)">{{ i18n.t('hypervisor.v2.customize.move_up') }}</button>
                <button type="button" class="hv2-text-btn" (click)="moveBlock(stratum.id, block, 1)">{{ i18n.t('hypervisor.v2.customize.move_down') }}</button>
              </div>
            }
          </fieldset>
        }
        @if (canEdit()) {
          <button type="button" class="hv2-text-btn" (click)="saveViews()" [disabled]="savingViews()">
            {{ i18n.t('hypervisor.v2.customize.save') }}
          </button>
        }
      }
    </ck-panel>
  `,
  styles: [`
    :host { display: block; color: var(--ck-fg-1); }
    .hv2-actions, .hv2-list-row, .hv2-block-row, .hv2-btn-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
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
    .hv2-monument-row { display: flex; align-items: baseline; gap: 8px; margin-top: 4px; }
    .hv2-monument { font-size: 88px; font-weight: 600; letter-spacing: -0.05em; line-height: 0.9; color: var(--ck-fg-1); }
    .hv2-monument-state { font-size: 22px; letter-spacing: 0.08em; line-height: 1.2; color: var(--ck-fg-2); }
    .hv2-monument-unit { font-size: 34px; font-weight: 500; color: var(--ck-fg-3); }
    .hv2-sentence { margin: 14px 0 0; font-size: 17px; line-height: 1.3; color: var(--ck-fg-2); }
    .hv2-sub { margin: 6px 0 0; font-size: 12px; line-height: 1.4; color: var(--ck-fg-3); }
    .hv2-provenance-block { display: flex; flex-direction: column; gap: 12px; }
    .hv2-provenance { display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: var(--ck-stroke-2); }
    .hv2-provenance-ink { background: var(--ck-fg-1); }
    .hv2-provenance-teal { background: var(--ck-signal-cool); }
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
    .hv2-system-name { font-size: 13px; font-weight: 500; color: var(--ck-fg-1); }
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
    .hv2-enter .hv2-register tbody tr,
    .hv2-enter .hv2-cards3 > .hv2-card {
      animation: hv2FadeUp 400ms var(--ck-ease-out, ease-out) both;
      animation-delay: calc(var(--stagger, 0) * 30ms);
    }
    @keyframes hv2FadeUp {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: none; }
    }
    @media (prefers-reduced-motion: reduce) {
      .hv2-enter .hv2-register tbody tr,
      .hv2-enter .hv2-cards3 > .hv2-card { animation: none; }
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
  readonly views = signal<HypervisorNamedView[]>([]);
  readonly canEdit = signal(false);
  readonly activeViewId = signal('direction');
  readonly activeFacet = signal<HypervisorFacetId>('synthese');
  readonly focusCapabilityId = signal<string | null>(null);
  readonly series = signal<HypervisorSeriesView | null>(null);
  readonly bases = signal<HypervisorValueBasisItem[]>([]);
  readonly capabilities = signal<Capability[]>([]);
  readonly catalogLocked = signal<ReadonlySet<string>>(new Set());
  readonly recommendations = signal<Recommendation[]>([]);
  readonly decisions = signal<DecisionRow[]>([]);
  readonly signals = signal<HypervisorSignal[]>([]);
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

  private routeSub: Subscription | null = null;
  private lastSeries: HypervisorSeriesResponse | null = null;
  private painted = false;
  private enterTimer: ReturnType<typeof setTimeout> | null = null;
  private flashTimer: ReturnType<typeof setTimeout> | null = null;
  private monumentRaf = 0;

  ngOnInit(): void {
    this.routeSub = this.route.queryParamMap.subscribe((params) => {
      const facet = params.get('facet');
      this.activeFacet.set(isHypervisorFacet(facet) ? facet : 'synthese');
      this.focusCapabilityId.set(params.get('capabilityId'));
    });
    this.reload();
  }

  ngOnDestroy(): void {
    this.routeSub?.unsubscribe();
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
    }
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

  systemLink(row: HypervisorRegisterRow): NavLinkInput {
    return { type: 'system', ref: row.systemId };
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

  pageTitle(): string {
    return this.i18n.t(`hypervisor.v2.page.title.${viewPeriod(this.activeView())}`);
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
    const count = this.series()?.streams.length ?? 0;
    const denominator = this.denominator();
    return count === 1
      ? this.i18n.t(`hypervisor.v2.rivers.title.${denominator}_one`)
      : this.i18n.t(`hypervisor.v2.rivers.title.${denominator}`, { count });
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
      return `— ${this.i18n.t('hypervisor.v2.register.basis_state.none')}`;
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
    this.activeViewId.set(id);
    const next = this.views().find((view) => view.id === id);
    if (!current || !next) return;
    if (viewPeriod(current) !== viewPeriod(next)) this.reload();
    else if (viewDenominator(current) !== viewDenominator(next)) this.reproject();
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
    this.api.putHypervisorViews(this.views()).subscribe({
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
      currency: row.value_basis?.currency || 'EUR',
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
    const code = currency && /^[A-Z]{3}$/.test(currency) ? currency : 'EUR';
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
    this.loading.set(true);
    this.loadProblem.set(null);
    forkJoin({
      series: this.api.hypervisorSeries(period),
      views: this.api.hypervisorViews(),
      bases: this.api.hypervisorValueBases(),
      capabilities: this.api.listCapabilities(),
      balance: this.api.hypervisorBalanceSheet(period === '90d' ? 'rolling_90d' : 'rolling_30d'),
      recos: this.api.hypervisorRecommendations(),
      decisions: this.api.listDecisions({ limit: 20 }),
    }).pipe(
      catchError((error: unknown) => {
        if (this.workspaceView.isCurrent(request)) this.loadProblem.set(
          error instanceof HttpErrorResponse && error.status === 403
            ? 'experience.adoption.access_denied' : 'experience.adoption.load_failed');
        return of({
        series: null,
        views: null,
        bases: [] as HypervisorValueBasisItem[],
        capabilities: [] as Capability[],
        balance: null,
        recos: [] as Recommendation[],
        decisions: { items: [] as DecisionRow[], total: 0, limit: 20, offset: 0 },
      }); }),
    ).subscribe((bundle) => {
      if (!this.workspaceView.isCurrent(request)) return;
      if (this.loadProblem()) { this.loading.set(false); return; }
      const parsed = parseViewsPayload(bundle.views);
      this.views.set(parsed.views);
      this.canEdit.set(parsed.can_edit);
      if (!parsed.views.some((view) => view.id === this.activeViewId())) {
        this.activeViewId.set(parsed.views[0]?.id ?? 'direction');
      }
      if (viewPeriod(this.activeView()) !== period) {
        this.reload();
        return;
      }
      this.lastSeries = bundle.series;
      this.series.set(bundle.series ? projectSeries(bundle.series, viewDenominator(this.activeView())) : null);
      this.bases.set(bundle.bases);
      this.capabilities.set(bundle.capabilities);
      this.recommendations.set(bundle.recos);
      this.decisions.set(bundle.decisions.items);
      this.signals.set(bundle.balance?.signals ?? []);
      this.loading.set(false);
      const firstPaint = !this.painted && this.series() != null;
      if (this.series()) this.painted = true;
      this.syncMonument(firstPaint);
      if (firstPaint) this.beginEntrance();
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
