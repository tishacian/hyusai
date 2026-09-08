import {
  ChangeDetectionStrategy,
  Component,
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
import {
  HYPERVISOR_FACETS,
  isHypervisorFacet,
  type HypervisorFacetId,
  type NavLinkInput,
} from '@app/core/navigation.catalog';
import {
  CkChartMiniAreaComponent,
  CkChartPulseComponent,
  CkChartRadialDaysComponent,
  CkChartSankeyFlowComponent,
  CkChartStreamComponent,
  CkChartUnitDotsComponent,
  CkPanelComponent,
  CkTabComponent,
  CkTabsComponent,
  GlyphComponent,
  KbdComponent,
  NavLinkDirective,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
  type CkRadialDay,
  type CkSankeySource,
  type CkStreamSeries,
} from '@app/shared/cockpit';
import {
  availableNumber,
  projectSeries,
  sortRegisterRows,
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

@Component({
  selector: 'app-hypervisor-v2',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    PageFrameComponent,
    NavLinkDirective,
    GlyphComponent,
    KbdComponent,
    TagComponent,
    StatReadoutComponent,
    CkPanelComponent,
    CkTabsComponent,
    CkTabComponent,
    CkChartRadialDaysComponent,
    CkChartSankeyFlowComponent,
    CkChartStreamComponent,
    CkChartMiniAreaComponent,
    CkChartUnitDotsComponent,
    CkChartPulseComponent,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('hypervisor.v2.page.eyebrow')"
      [title]="i18n.t('hypervisor.v2.page.title')"
      [description]="i18n.t('hypervisor.v2.page.description')"
    >
      <div actions class="hv2-actions">
        <div class="hv2-switch" role="tablist">
          @for (view of views(); track view.id) {
            <button
              type="button"
              class="ck-mono"
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

      <nav class="hv2-facets" data-testid="hypervisor-v2-facets">
        @for (facet of facets; track facet.id) {
          <a
            [navLink]="facetLink(facet.id)"
            [attr.data-testid]="'hypervisor-v2-facet-' + facet.id"
            [class.hv2-facets-on]="activeFacet() === facet.id"
          >{{ i18n.t(facet.i18nKey) }}</a>
        }
      </nav>

      @if (loading()) {
        <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.loading') }}</p>
      } @else {
        <ck-tabs [active]="activeFacet()" (activeChange)="onFacetChange($event)" class="hv2-tabs">
        <ck-tab id="synthese" [label]="i18n.t('nav.facet.synthese')">
        @if (!series()) {
          <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.empty') }}</p>
        } @else {
          <div class="hv2-stack">
            @if (showStratum('comprendre')) {
              <section class="hv2-stack" data-testid="hypervisor-v2-stratum-comprendre">
                <h2 class="ck-mono hv2-stratum"><ck-glyph name="ledger" [size]="12" /> {{ i18n.t('hypervisor.v2.stratum.comprendre') }}</h2>
                @if (showBlock('comprendre', 'monument') || showBlock('comprendre', 'provenance')) {
                  <section class="hv2-hero" data-testid="hypervisor-v2-hero">
                    <div class="hv2-hero-grid">
                      @if (showBlock('comprendre', 'monument')) {
                        <div>
                          <div class="ck-mono hv2-kicker">{{ denominatorLabel() }}</div>
                          <div class="hv2-monument ck-tnum">{{ formatFact(series()!.monument, 'denom') }}</div>
                          @if (unitDots() > 0) {
                            <ck-chart-unit-dots [units]="unitDots()" [unitsPerDot]="1" />
                          }
                        </div>
                      }
                      @if (showBlock('comprendre', 'provenance')) {
                        <div>
                          <div class="hv2-provenance" aria-hidden="true">
                            <span class="hv2-provenance-ink" [style.flexGrow]="series()!.measuredTotal || 0.01"></span>
                            <span class="hv2-provenance-teal" [style.flexGrow]="series()!.declaredTotal || 0.01"></span>
                            <span class="hv2-provenance-out" [style.flexGrow]="series()!.outside.length || 0.01"></span>
                          </div>
                          <div class="ck-mono hv2-caption">
                            {{ i18n.t('hypervisor.v2.provenance.measured') }}
                            · {{ formatNumber(series()!.measuredTotal) }}
                            · {{ i18n.t('hypervisor.v2.provenance.declared') }}
                            · {{ formatNumber(series()!.declaredTotal) }}
                            · {{ i18n.t('hypervisor.v2.provenance.outside') }}
                            · {{ series()!.outside.length }}
                          </div>
                          @if (series()!.peak; as peak) {
                            <div class="ck-mono hv2-caption">{{ i18n.t('hypervisor.v2.peak', { date: peak.date }) }}</div>
                          }
                        </div>
                      }
                      <div class="hv2-metrics">
                        <ck-stat-readout [label]="i18n.t('hypervisor.v2.metric.cost')" [value]="formatFact(series()!.costTotal, 'currency')" />
                        <ck-stat-readout [label]="i18n.t('hypervisor.v2.metric.value')" [value]="formatFact(series()!.valueTotal, 'currency')" />
                        <ck-stat-readout [label]="i18n.t('hypervisor.v2.metric.ratio')" [value]="formatFact(series()!.ratio, 'ratio')" />
                      </div>
                    </div>
                  </section>
                }
                @if (showBlock('comprendre', 'cadran') || showBlock('comprendre', 'sankey')) {
                  <div class="hv2-split">
                    @if (showBlock('comprendre', 'cadran')) {
                      <article class="ck-surface hv2-card">
                        <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.block.cadran') }}</h3>
                        <ck-chart-radial-days
                          [days]="radialDays()"
                          [ticks]="series()!.ticks"
                          [centerValue]="formatFact(series()!.monument, 'denom')"
                          [centerCaption]="denominatorLabel()"
                          [rangeLabel]="periodLabel()"
                        />
                      </article>
                    }
                    @if (showBlock('comprendre', 'sankey')) {
                      <article class="ck-surface hv2-card">
                        <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.block.sankey') }}</h3>
                        <ck-chart-sankey-flow
                          [sources]="sankeySources()"
                          [middleLabel]="denominatorLabel()"
                          [rightLabel]="i18n.t('hypervisor.v2.sankey.right')"
                          [leftCaption]="i18n.t('hypervisor.v2.sankey.left_caption')"
                          [middleCaption]="i18n.t('hypervisor.v2.sankey.middle_caption')"
                          [rightCaption]="i18n.t('hypervisor.v2.sankey.right_caption')"
                        />
                      </article>
                    }
                  </div>
                }
                @if (showBlock('comprendre', 'rivers')) {
                  <article class="ck-surface hv2-card">
                    <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.block.rivers') }}</h3>
                    <ck-chart-stream
                      [series]="streamSeries()"
                      [weekendStarts]="series()!.weekendStarts"
                      [ticks]="series()!.ticks"
                      [peak]="streamPeak()"
                    />
                  </article>
                }
                @if (showBlock('comprendre', 'hors_denominateur')) {
                  <article class="ck-surface hv2-card" data-testid="hypervisor-v2-hors-denominateur">
                    <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.hors.title') }}</h3>
                    @if (series()!.outside.length === 0) {
                      <p class="hv2-muted">{{ i18n.t('hypervisor.v2.hors.empty') }}</p>
                    } @else {
                      <ul class="hv2-list">
                        @for (row of series()!.outside; track row.systemId) {
                          <li class="hv2-list-row">
                            <span>{{ row.name }}</span>
                            @if (row.capabilityId) {
                              <a [navLink]="basesLink(row.capabilityId)">{{ i18n.t('hypervisor.v2.hors.open_basis') }}</a>
                            }
                          </li>
                        }
                      </ul>
                    }
                  </article>
                }
              </section>
            }
            @if (showStratum('detailler') && showBlock('detailler', 'registre')) {
              <section data-testid="hypervisor-v2-stratum-detailler">
                <h2 class="ck-mono hv2-stratum"><ck-glyph name="table" [size]="12" /> {{ i18n.t('hypervisor.v2.stratum.detailler') }}</h2>
                <ng-container [ngTemplateOutlet]="registerTpl" [ngTemplateOutletContext]="{ testid: 'hypervisor-v2-register' }"></ng-container>
              </section>
            }
            @if (showStratum('decider')) {
              <section class="hv2-stack" data-testid="hypervisor-v2-stratum-decider">
                <h2 class="ck-mono hv2-stratum"><ck-glyph name="focus" [size]="12" /> {{ i18n.t('hypervisor.v2.stratum.decider') }}</h2>
                <ng-container [ngTemplateOutlet]="decideTpl"></ng-container>
              </section>
            }
          </div>
        }
        </ck-tab>

        <ck-tab id="registre" [label]="i18n.t('nav.facet.registre')">
          <section>
            @if (series()) {
              <ng-container [ngTemplateOutlet]="registerTpl" [ngTemplateOutletContext]="{ testid: 'hypervisor-v2-register-registre' }"></ng-container>
            } @else {
              <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.empty') }}</p>
            }
          </section>
        </ck-tab>

        <ck-tab id="couts" [label]="i18n.t('nav.facet.couts')">
          <section class="hv2-stack">
            @if (series(); as view) {
              <article class="ck-surface hv2-card">
                <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.metric.cost') }}</h3>
                <ck-chart-stream
                  [series]="costStreamSeries()"
                  [weekendStarts]="view.weekendStarts"
                  [ticks]="view.ticks"
                />
              </article>
              <ng-container [ngTemplateOutlet]="registerTpl" [ngTemplateOutletContext]="{ testid: 'hypervisor-v2-register-couts' }"></ng-container>
            } @else {
              <p class="ck-mono hv2-muted">{{ i18n.t('hypervisor.v2.empty') }}</p>
            }
          </section>
        </ck-tab>

        <ck-tab id="bases" [label]="i18n.t('nav.facet.bases')">
          <ng-container [ngTemplateOutlet]="basesTpl"></ng-container>
        </ck-tab>

        <ck-tab id="decisions" [label]="i18n.t('nav.facet.decisions')">
          <section class="hv2-stack">
            <ng-container [ngTemplateOutlet]="decideTpl"></ng-container>
          </section>
        </ck-tab>

        <ck-tab id="journal" [label]="i18n.t('nav.facet.journal')">
          <article class="ck-surface hv2-card">
            <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.journal.title') }}</h3>
            @if (series(); as view) {
              <ck-chart-pulse
                [values]="view.pulseValues"
                [staleFrom]="view.staleFrom"
                [startLabel]="i18n.t('hypervisor.v2.journal.start')"
                [endLabel]="i18n.t('hypervisor.v2.journal.end')"
                [zeroLabel]="i18n.t('hypervisor.v2.journal.zero')"
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
      }
    </ck-page-frame>

    <ng-template #registerTpl let-testid="testid">
      <article class="ck-surface hv2-card ck-h-scroll" [attr.data-testid]="testid">
        <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.block.registre') }}</h3>
        @if (registerRows().length === 0) {
          <p class="hv2-muted">{{ i18n.t('hypervisor.v2.register.empty') }}</p>
        } @else {
          <table class="hv2-table">
            <thead>
              <tr>
                <th>{{ i18n.t('hypervisor.v2.col.system') }}</th>
                @if (showCol('unit')) { <th>{{ i18n.t('hypervisor.v2.col.unit') }}</th> }
                @if (showCol('spark')) { <th>{{ i18n.t('hypervisor.v2.col.spark') }}</th> }
                @if (showCol('cost')) { <th>{{ i18n.t('hypervisor.v2.col.cost') }}</th> }
                @if (showCol('basis')) { <th>{{ i18n.t('hypervisor.v2.col.basis') }}</th> }
                @if (showCol('value')) { <th>{{ i18n.t('hypervisor.v2.col.value') }}</th> }
              </tr>
            </thead>
            <tbody>
              @for (row of registerRows(); track row.systemId) {
                <tr>
                  <td>
                    <span class="hv2-glyph" [attr.data-health]="row.health">{{ row.initials }}</span>
                    {{ row.name }}
                  </td>
                  @if (showCol('unit')) { <td>{{ row.outputUnit || factLabel(row.outcomes) }}</td> }
                  @if (showCol('spark')) {
                    <td>
                      <ck-chart-mini-area [values]="row.weekSpark" [tone]="row.outsideDenominator ? 'declared' : 'ink'" />
                    </td>
                  }
                  @if (showCol('cost')) { <td>{{ formatFact(row.cost, 'currency') }}</td> }
                  @if (showCol('basis')) { <td>{{ basisLabel(row) }}</td> }
                  @if (showCol('value')) { <td>{{ formatFact(row.valueDeclared, 'currency') }}</td> }
                </tr>
              }
            </tbody>
            <tfoot>
              <tr>
                <th>{{ i18n.t('hypervisor.v2.register.total') }}</th>
                @if (showCol('unit')) { <td>{{ formatFact(series()!.unitsTotal, 'units') }}</td> }
                @if (showCol('spark')) { <td></td> }
                @if (showCol('cost')) { <td>{{ formatFact(series()!.costTotal, 'currency') }}</td> }
                @if (showCol('basis')) { <td></td> }
                @if (showCol('value')) { <td>{{ formatFact(series()!.valueTotal, 'currency') }}</td> }
              </tr>
            </tfoot>
          </table>
        }
      </article>
    </ng-template>

    <ng-template #decideTpl>
      @if (showBlock('decider', 'signal') || activeFacet() === 'decisions') {
        <article class="ck-surface hv2-card">
          <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.v2.signal.title') }}</h3>
          <p>{{ signalCopy() }}</p>
        </article>
      }
      @if (showBlock('decider', 'decisions') || activeFacet() === 'decisions') {
        <article class="ck-surface hv2-card">
          <div class="hv2-row">
            <h3 class="ck-mono hv2-kicker">{{ i18n.t('hypervisor.decisions.title') }}</h3>
            <button type="button" class="hv2-text-btn" (click)="scanRecommendations()" [disabled]="scanning()">
              {{ scanning() ? i18n.t('hypervisor.reco.scanning') : i18n.t('hypervisor.reco.scan') }}
            </button>
          </div>
          @if (recommendations().length === 0 && decisions().length === 0) {
            <p class="hv2-muted">{{ i18n.t('hypervisor.decisions.empty') }}</p>
          }
          <ul class="hv2-list">
            @for (item of recommendations(); track item.id) {
              <li>{{ item.title }}</li>
            }
            @for (item of decisions(); track item.id) {
              <li class="hv2-list-row">
                <span>{{ item.title }}</span>
                <span class="ck-mono hv2-muted">{{ decisionStatus(item.status) }}</span>
                @if (item.status === 'proposed') {
                  <button type="button" class="hv2-text-btn" (click)="accept(item)">{{ i18n.t('hypervisor.decisions.accept') }}</button>
                  <button type="button" class="hv2-text-btn" (click)="reject(item)">{{ i18n.t('hypervisor.decisions.reject') }}</button>
                }
              </li>
            }
          </ul>
        </article>
      }
    </ng-template>

    <ng-template #basesTpl>
      <article class="ck-surface hv2-card ck-h-scroll" data-testid="hypervisor-v2-value-bases">
        <h3 class="ck-mono hv2-kicker">{{ i18n.t('nav.facet.bases') }}</h3>
        @if (bases().length === 0) {
          <p class="hv2-muted">{{ i18n.t('hypervisor.v2.bases.empty') }}</p>
        } @else {
          <table class="hv2-table">
            <thead>
              <tr>
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
                  <td>{{ formatMaybeNumber(row.value_basis?.hours_per_unit) }}</td>
                  <td>{{ formatMoney(row.value_basis?.value_per_unit, row.value_basis?.currency) }}</td>
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
    .hv2-actions, .hv2-row, .hv2-list-row, .hv2-block-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .hv2-stack { display: flex; flex-direction: column; gap: 20px; }
    .hv2-switch { display: flex; gap: 4px; padding: 4px; background: var(--ck-bg-panel); border: 1px solid var(--ck-stroke-2); }
    .hv2-switch button, .hv2-text-btn {
      background: transparent; border: 0; color: var(--ck-fg-3); cursor: pointer;
      font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; padding: 6px 10px;
    }
    .hv2-switch-on { color: var(--ck-fg-1); background: var(--ck-bg-inset); outline: 1px solid var(--ck-stroke-strong); }
    .hv2-facets {
      display: flex; gap: 2px; flex-wrap: wrap;
      border-bottom: 1px solid var(--ck-stroke-2); margin: 8px 0 20px;
    }
    .hv2-facets a {
      font-family: var(--ck-font-mono); font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
      color: var(--ck-fg-2); text-decoration: none; padding: 10px 14px;
      border-bottom: 2px solid transparent;
    }
    .hv2-facets-on { color: var(--ck-signal-cool); border-bottom-color: var(--ck-signal-cool); font-weight: 600; }
    :host ::ng-deep .hv2-tabs [role="tablist"] { display: none; }
    .hv2-hero {
      background: var(--ck-bg-inset);
      border-block: 1px solid var(--ck-stroke-2);
      margin-inline: -32px;
      padding: 28px 32px;
    }
    .hv2-hero-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr) minmax(0, 1fr); gap: 24px; align-items: start; }
    .hv2-monument { font-size: 48px; font-weight: 300; letter-spacing: -0.03em; color: var(--ck-fg-1); line-height: 1; }
    .hv2-metrics { display: grid; gap: 12px; }
    .hv2-provenance { display: flex; height: 8px; gap: 2px; background: var(--ck-bg-panel); }
    .hv2-provenance-ink { background: var(--ck-fg-1); }
    .hv2-provenance-teal { background: var(--ck-signal-cool); }
    .hv2-provenance-out { background: var(--ck-fg-4); }
    .hv2-card { padding: 18px 20px; }
    .hv2-split { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .hv2-stratum { font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--ck-fg-3); margin: 0; }
    .hv2-kicker { font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--ck-fg-4); margin: 0 0 10px; }
    .hv2-caption, .hv2-muted { font-size: 12px; color: var(--ck-fg-4); }
    .hv2-error { color: var(--ck-signal-neg); font-size: 12px; }
    .hv2-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
    .hv2-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .hv2-table th, .hv2-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--ck-stroke-2); vertical-align: middle; }
    .hv2-glyph {
      display: inline-flex; align-items: center; justify-content: center;
      width: 28px; height: 28px; margin-right: 8px;
      border: 1px solid var(--ck-stroke-strong); font-size: 10px; letter-spacing: 0.08em;
    }
    .hv2-glyph[data-health='pos'] { border-color: var(--ck-signal-pos); }
    .hv2-glyph[data-health='warn'] { border-color: var(--ck-signal-warn); }
    .hv2-glyph[data-health='neg'] { border-color: var(--ck-signal-neg); }
    .hv2-row-focus { background: var(--ck-bg-inset); }
    .hv2-fieldset { border: 1px solid var(--ck-stroke-2); padding: 10px 12px; margin: 0 0 12px; display: flex; flex-direction: column; gap: 6px; }
    .hv2-edit { display: flex; flex-direction: column; gap: 6px; min-width: 180px; }
    .hv2-edit input, .hv2-edit select {
      width: 100%; background: var(--ck-bg-inset); color: var(--ck-fg-1);
      border: 1px solid var(--ck-stroke-2); padding: 4px 6px;
    }
    @media (max-width: 900px) {
      .hv2-hero-grid { grid-template-columns: 1fr; }
      .hv2-hero { margin-inline: -14px; padding-inline: 14px; }
    }
  `],
})
export class HypervisorV2Component implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService);
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
  readonly facets = HYPERVISOR_FACETS;
  readonly denominators: readonly HypervisorViewDenominator[] = ['hours', 'units', 'value'];
  readonly periods = ['30d', '90d'] as const;
  readonly columns = REGISTER_COLUMNS;
  readonly sorts = VIEW_SORTS;
  readonly strata: ReadonlyArray<{ id: HypervisorStratumId; label: string; blocks: readonly string[] }> = [
    { id: 'comprendre', label: 'hypervisor.v2.customize.stratum.comprendre', blocks: COMPRENDRE_BLOCKS },
    { id: 'detailler', label: 'hypervisor.v2.customize.stratum.detailler', blocks: DETAILLER_BLOCKS },
    { id: 'decider', label: 'hypervisor.v2.customize.stratum.decider', blocks: DECIDER_BLOCKS },
  ];

  readonly loading = signal(true);
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
  readonly scanning = signal(false);
  readonly savingViews = signal(false);
  readonly savingBasis = signal(false);
  readonly basisError = signal(false);
  readonly editingId = signal<string | null>(null);
  readonly draft = signal<BasisDraft | null>(null);

  readonly activeView = computed(() =>
    this.views().find((view) => view.id === this.activeViewId()) ?? this.views()[0] ?? null,
  );
  readonly registerRows = computed(() => {
    const view = this.series();
    const active = this.activeView();
    if (!view) return [];
    return sortRegisterRows(view.register, active?.sort ?? 'name');
  });

  private routeSub: Subscription | null = null;

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

  facetLink(facet: string): NavLinkInput {
    return { facet };
  }

  basesLink(capabilityId: string): NavLinkInput {
    return { facet: 'bases', capabilityId };
  }

  viewLabel(view: HypervisorNamedView): string {
    const key = `hypervisor.v2.view.${view.id}`;
    const label = this.i18n.t(key);
    return label === key ? view.label : label;
  }

  denominatorLabel(): string {
    return this.i18n.t(`hypervisor.v2.denominator.${viewDenominator(this.activeView())}`);
  }

  periodLabel(): string {
    return this.i18n.t(`hypervisor.v2.period.${viewPeriod(this.activeView())}`);
  }

  showStratum(stratum: HypervisorStratumId): boolean {
    const view = this.activeView();
    return Boolean(view?.strata[stratum]?.length);
  }

  showBlock(stratum: HypervisorStratumId, block: string): boolean {
    return showsBlock(this.activeView(), stratum, block);
  }

  showCol(column: string): boolean {
    return showsColumn(this.activeView(), column);
  }

  radialDays(): CkRadialDay[] {
    return (this.series()?.days ?? []).map((day) => ({
      measured: day.measured,
      declared: day.declared,
      weekend: day.weekend,
      label: day.date,
    }));
  }

  streamSeries(): CkStreamSeries[] {
    return (this.series()?.streams ?? []).map((row) => ({
      label: row.label,
      values: row.values,
      tone: row.tone,
    }));
  }

  costStreamSeries(): CkStreamSeries[] {
    return (this.series()?.costStreams ?? []).map((row) => ({
      label: row.label,
      values: row.values,
      tone: row.tone,
    }));
  }

  sankeySources(): CkSankeySource[] {
    const stub = this.i18n.t('hypervisor.v2.sankey.stub');
    return (this.series()?.sankey ?? []).map((row) => ({
      label: row.label,
      detail: row.detail,
      value: row.value || 1,
      stubLabel: row.outsideDenominator ? stub : '',
    }));
  }

  streamPeak(): { index: number; label: string } | null {
    const peak = this.series()?.peak;
    return peak ? { index: peak.index, label: this.i18n.t('hypervisor.v2.peak', { date: peak.date }) } : null;
  }

  unitDots(): number {
    const hours = availableNumber(this.series()?.hoursTotal ?? { state: 'not_measured', value: null });
    if (hours == null || hours <= 0 || hours > 64) return 0;
    return Math.round(hours);
  }

  selectView(id: string): void {
    const current = this.activeView();
    this.activeViewId.set(id);
    const next = this.views().find((view) => view.id === id);
    if (current && next && viewPeriod(current) !== viewPeriod(next)) this.reload();
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

  formatFact(fact: SeriesFact, kind: 'denom' | 'currency' | 'ratio' | 'units'): string {
    if (fact.state !== 'available' || fact.value == null) return this.factLabel(fact);
    if (kind === 'currency') return this.formatMoney(fact.value, this.series()?.currency);
    if (kind === 'ratio') return this.formatNumber(fact.value);
    if (kind === 'units') return this.formatNumber(fact.value);
    return this.formatNumber(fact.value);
  }

  formatMoney(value: number | null | undefined, currency: string | null | undefined): string {
    if (value == null) return '';
    const code = currency && /^[A-Z]{3}$/.test(currency) ? currency : null;
    if (!code) return this.formatNumber(value);
    return new Intl.NumberFormat(this.localeTag(), { style: 'currency', currency: code }).format(value);
  }

  formatNumber(value: number): string {
    return new Intl.NumberFormat(this.localeTag(), { maximumFractionDigits: 2 }).format(value);
  }

  formatMaybeNumber(value: number | null | undefined): string {
    return value == null ? '' : this.formatNumber(value);
  }

  factLabel(fact: SeriesFact): string {
    return this.i18n.t(`hypervisor.state.${fact.state}`);
  }

  basisLabel(row: HypervisorRegisterRow): string {
    if (!row.basisStatus) return this.i18n.t('hypervisor.v2.bases.status.none');
    return this.i18n.t(`hypervisor.v2.bases.status.${row.basisStatus}`);
  }

  basisStatusLabel(status: HypervisorValueBasisStatus): string {
    return this.i18n.t(`hypervisor.v2.bases.status.${status}`);
  }

  provenanceCopy(row: HypervisorValueBasisItem): string {
    const who = row.value_basis?.declared_by;
    const when = row.value_basis?.declared_at;
    if (!who && !when) return '';
    return this.i18n.t('hypervisor.v2.bases.declared_by', { who: who || '', when: when || '' });
  }

  systemNames(row: HypervisorValueBasisItem): string {
    return (row.systems ?? []).map((item) => item.name).join(', ');
  }

  decisionStatus(status: string): string {
    const key = `hypervisor.decisions.status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? status : label;
  }

  signalCopy(): string {
    const stale = this.series()?.register.filter((row) => this.series()?.staleSystemIds.includes(row.systemId)) ?? [];
    if (stale.length === 0) return this.i18n.t('hypervisor.v2.signal.healthy');
    if (stale.length === 1) return this.i18n.t('hypervisor.v2.signal.stale_one', { name: stale[0]!.name });
    return this.i18n.t('hypervisor.v2.signal.stale', { count: stale.length });
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
  }

  private lastSeries: HypervisorSeriesResponse | null = null;

  private reset(): void {
    this.series.set(null);
    this.bases.set([]);
    this.decisions.set([]);
    this.recommendations.set([]);
    this.signals.set([]);
    this.editingId.set(null);
  }

  private reload(): void {
    const request = this.workspaceView.beginRequest();
    const period = viewPeriod(this.activeView() ?? DEFAULT_HYPERVISOR_VIEWS[0]);
    this.loading.set(true);
    forkJoin({
      series: this.api.hypervisorSeries(period),
      views: this.api.hypervisorViews(),
      bases: this.api.hypervisorValueBases(),
      capabilities: this.api.listCapabilities(),
      balance: this.api.hypervisorBalanceSheet(period === '90d' ? 'rolling_90d' : 'rolling_30d'),
      recos: this.api.hypervisorRecommendations(),
      decisions: this.api.listDecisions({ limit: 20 }),
    }).pipe(
      catchError(() => of({
        series: null,
        views: null,
        bases: [] as HypervisorValueBasisItem[],
        capabilities: [] as Capability[],
        balance: null,
        recos: [] as Recommendation[],
        decisions: { items: [] as DecisionRow[], total: 0, limit: 20, offset: 0 },
      })),
    ).subscribe((bundle) => {
      if (!this.workspaceView.isCurrent(request)) return;
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
    });
  }
}
