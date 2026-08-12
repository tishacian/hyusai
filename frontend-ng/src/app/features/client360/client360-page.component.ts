import { NgClass } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import {
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { GlyphComponent, PageFrameComponent } from '@app/shared/cockpit';

type ViewKey = 'opportunities' | 'customer' | 'data' | 'mapping' | 'mail' | 'campaigns' | 'chat';

interface WorkspaceActionContext {
  scope: WorkspaceRequestScope;
  generation: number;
}

interface Client360ChatSource {
  title?: string;
  source_label?: string;
}

interface Client360ChatResponse {
  content?: string;
  sources?: Client360ChatSource[];
  intent?: string;
}

interface Client360DataSource {
  id: string;
  origin: string;
  source_type: string;
  label: string;
  filename?: string | null;
  collection_slug?: string | null;
  status: string;
  row_count?: number | null;
  error?: string | null;
  metadata?: Record<string, unknown>;
}

interface Client360SyncFromCollectionResult {
  collection_slug?: string;
  dry_run?: boolean;
  files_seen?: number;
  sources_seen?: number;
  sources_upserted?: number;
  mvp_sources_linked?: number;
  records_seen?: number;
  created?: number;
  updated?: number;
  skipped?: Record<string, number>;
  by_source_type?: Record<string, number>;
  message?: string;
}

const CLIENT360_UNIFIED_COLLECTION_SLUG = 'andritz-client360-installed-base';

// Long fiche lists are paged client-side to keep the page height manageable.
const FICHE_PURCHASES_PAGE = 15;
const FICHE_OPPORTUNITIES_PAGE = 24;
const FICHE_TIMELINE_PAGE = 12;
// Landing page: alerts collapse to a short digest and the table pages itself.
const ALERTS_PREVIEW_COUNT = 6;
const OPPORTUNITIES_TABLE_PAGE = 25;

interface Client360Opportunity {
  id: string;
  customer_key: string;
  customer_name: string;
  site_name?: string | null;
  country?: string | null;
  hub?: string | null;
  technology?: string | null;
  line_label?: string | null;
  machine_label?: string | null;
  part_family: string;
  part_reference?: string | null;
  part_description?: string | null;
  installed_quantity?: number | null;
  recommended_quantity?: number | null;
  periodicity_weeks?: number | null;
  delivery_time_weeks?: number | null;
  annual_theoretical_qty?: number | null;
  potential_theoretical?: number | null;
  potential_addressable?: number | null;
  potential_gap_qty?: number | null;
  potential_gap_value?: number | null;
  potential_unit: string;
  currency?: string | null;
  sales_known_qty?: number | null;
  sales_known_value?: number | null;
  next_due_at?: string | null;
  confidence_score?: number | null;
  confidence_label: string;
  score_reasons: Array<{ code: string; label: string; weight: number; met: boolean }>;
  recommended_action?: string | null;
  status: string;
  data_gaps: string[];
  evidence_refs: Array<Record<string, unknown>>;
  metadata?: {
    pricing?: {
      source?: string | null;
      unit_price?: number | null;
      currency?: string | null;
    } | null;
    addressable_factors?: {
      weights?: Record<string, number>;
      hub_present?: boolean;
      existing_purchase_history?: boolean;
      observed_conversion_rate?: number;
      factor?: number;
      gap_qty?: number | null;
    } | null;
  } | null;
}

interface Client360Summary {
  workspace: { id: string; slug: string; name: string };
  positioning: {
    name?: string;
    mode?: string;
    no_supervised_prediction?: boolean;
    no_automatic_email_send?: boolean;
    mvp_contract?: {
      promise?: string;
      mvp_in_scope?: string[];
      deferred_scope?: string[];
      campaign_segments?: Array<{ id: string; label: string; confidence_policy?: string }>;
    };
    mail_ai?: {
      enabled?: boolean;
      configured?: boolean;
      disabled_reason?: string | null;
      provider?: string | null;
      model?: string | null;
      model_source?: string | null;
      routing_source?: string | null;
      route_id?: string | null;
    };
  };
  summary: {
    opportunities: number;
    customers: number;
    data_sources: number;
    mapping_rules: number;
    potential_theoretical: number;
    potential_gap_qty: number;
    potential_unit: string;
    mail_drafts: number;
    impact_events: number;
  };
  by_status: Record<string, number>;
  by_confidence: Record<string, number>;
  source_counts: Record<string, number>;
  data_gaps: string[];
  data_sources: Client360DataSource[];
}

interface Client360Alert {
  id: string;
  type: string;
  severity: string;
  title: string;
  message: string;
  opportunity_id?: string | null;
  opportunity_label?: string | null;
  customer_key?: string | null;
  mail_draft_id?: string | null;
  mail_draft_label?: string | null;
  due_at?: string | null;
  metrics?: Record<string, unknown>;
}

interface Client360AlertsResponse {
  alerts: Client360Alert[];
  counts: { total: number; by_type: Record<string, number>; by_severity: Record<string, number> };
  thresholds: Record<string, unknown>;
  generated_at?: string;
}

interface Client360OpportunitiesResponse {
  items: Client360Opportunity[];
  facets: {
    countries: string[];
    hubs: string[];
    technologies: string[];
    part_families: string[];
    statuses: string[];
    confidence_labels: string[];
  };
}

interface Client360AiSummary {
  text: string;
  highlights?: string[];
  generation_mode?: string;
  provider?: string | null;
  model?: string | null;
  model_source?: string | null;
  routing_source?: string | null;
  route_id?: string | null;
  prompt_version?: string | null;
  fallback_reason?: string | null;
}

interface Client360InstalledBasePart {
  opportunity_id?: string | null;
  part_family?: string | null;
  part_reference?: string | null;
  part_description?: string | null;
  installed_quantity?: number | null;
  potential_gap_qty?: number | null;
  potential_gap_value?: number | null;
  currency?: string | null;
  next_due_at?: string | null;
  confidence_label?: string | null;
  status?: string | null;
}

interface Client360InstalledBaseMachine {
  machine_label: string;
  parts: Client360InstalledBasePart[];
  opportunity_count: number;
  potential_gap_value?: number | null;
}

interface Client360InstalledBaseLine {
  line_label: string;
  machines: Client360InstalledBaseMachine[];
  opportunity_count: number;
  potential_gap_value?: number | null;
}

interface Client360InstalledBaseTechnology {
  technology: string;
  lines: Client360InstalledBaseLine[];
  opportunity_count: number;
  potential_gap_value?: number | null;
}

interface Client360TimelineEvent {
  at: string;
  kind: string;
  label: string;
  status?: string | null;
  impact_type?: string | null;
  opportunity_id?: string | null;
  mail_draft_id?: string | null;
}

interface Client360CustomerProject {
  project_code?: string | null;
  sap_reference?: string | null;
  wbs_element?: string | null;
  country?: string | null;
}

interface Client360CustomerMachine {
  machine_label?: string | null;
  technology?: string | null;
  line_label?: string | null;
  project_code?: string | null;
  sap_reference?: string | null;
  wbs_element?: string | null;
  construction_year?: string | null;
  country?: string | null;
  customer_key?: string | null;
}

interface Client360CustomerPurchase {
  part_reference: string;
  part_description?: string | null;
  sales_known_qty?: number | null;
  sales_known_value?: number | null;
  currency?: string | null;
  last_document_date?: string | null;
  order_line_count?: number | null;
  unit_cost?: number | null;
  delivery_time_weeks?: number | null;
  po_count?: number | null;
  cost_sum?: number | null;
}

interface Client360NextDueItem {
  part_reference?: string | null;
  part_family?: string | null;
  part_description?: string | null;
  next_due_at?: string | null;
  recommended_quantity?: number | null;
  confidence?: string | null;
  customer_key?: string | null;
  opportunity_id?: string | null;
  [key: string]: unknown;
}

interface Client360DirectoryCustomer {
  customer_key: string;
  customer_name: string;
  countries: string[];
  hubs: string[];
  technologies: string[];
  projects: Client360CustomerProject[];
  project_count: number;
  opportunity_count: number;
  statuses: Record<string, number>;
  potential_gap_value: number;
  potential_gap_qty: number;
  currency?: string | null;
}

interface Client360CustomersResponse {
  items: Client360DirectoryCustomer[];
  total: number;
  facets: {
    countries: string[];
    technologies: string[];
  };
}

interface Client360CustomerResponse {
  customer: {
    id: string;
    name: string;
    countries: string[];
    hubs: string[];
    technologies: string[];
  };
  ai_summary?: Client360AiSummary | null;
  installed_base?: Client360InstalledBaseTechnology[];
  timeline?: Client360TimelineEvent[];
  projects?: Client360CustomerProject[];
  machines?: Client360CustomerMachine[];
  purchases?: Client360CustomerPurchase[];
  next_due?: Client360NextDueItem[];
  opportunities: Client360Opportunity[];
  mail_drafts: Client360MailDraft[];
  impact_events: Client360ImpactEvent[];
  market_signals: Client360DataSource[];
  data_gaps: string[];
}

interface Client360MailDraft {
  id: string;
  opportunity_id: string;
  action_item_id?: string | null;
  subject: string;
  generated_body: string;
  sent_body?: string | null;
  language: string;
  status: string;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  sent_at?: string | null;
}

interface Client360MappingRule {
  id: string;
  source_part_reference?: string | null;
  source_part_label?: string | null;
  source_part_family?: string | null;
  technology?: string | null;
  pdr_family: string;
  recommended_quantity?: number | null;
  periodicity_weeks?: number | null;
  delivery_time_weeks?: number | null;
  status: string;
  confidence: number;
  notes?: string | null;
}

interface Client360MappingsResponse {
  items: Client360MappingRule[];
}

interface Client360EngineResult {
  engine: string;
  dry_run: boolean;
  records_seen: number;
  candidate_mappings_created: number;
  opportunities_detected: number;
  created: number;
  updated: number;
  skipped: Record<string, number>;
  preview: Client360Opportunity[];
}

interface Client360ImpactEvent {
  id: string;
  opportunity_id?: string | null;
  action_item_id?: string | null;
  mail_draft_id?: string | null;
  impact_type: string;
  attribution: string;
  reason: string;
  summary: string;
  quote_value?: number | null;
  order_value?: number | null;
  currency?: string | null;
  occurred_at?: string | null;
}

interface ActionResponse {
  action: { id: string; status: string; metadata?: Record<string, unknown> };
}

interface MailDraftResponse {
  mail_draft: Client360MailDraft;
  action: { id: string; status: string };
}

interface ImpactResponse {
  impact_event: Client360ImpactEvent;
}

interface MailSettingsResponse {
  mail_settings: Client360MailSettings;
}

interface Client360MailSettings {
  enabled: boolean;
  configured: boolean;
  disabled_reason?: string | null;
  source: string;
  host: string;
  port: number;
  username: string;
  from_email: string;
  from_name: string;
  ssl: boolean;
  starttls: boolean;
  password_configured: boolean;
  password_env_var?: string | null;
  system_prompt?: string;
  system_prompt_source?: 'default' | 'workspace';
  prompt_version?: string;
}

interface MailSendResponse {
  mail_draft: Client360MailDraft;
  action?: { id: string; status: string } | null;
  delivery: { status: string };
}

interface Client360Campaign {
  id: string;
  name: string;
  campaign_type: string;
  status: string;
  description?: string;
  selection_criteria: Record<string, unknown>;
  targeted_count: number;
  drafts_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

interface Client360CampaignsResponse {
  items: Client360Campaign[];
}

interface Client360CampaignResponse {
  campaign: Client360Campaign;
}

interface Client360CampaignStats {
  targeted_opportunities: number;
  targeted_customers: number;
  potential_gap_value: number;
  expected_value?: number | null;
  expected_value_disclaimer?: string | null;
  conversion_proxy?: number | null;
  conversion_proxy_source?: string | null;
  drafts: number;
  sent: number;
  responses: number;
  quotes: number;
  orders: number;
  won_value: number;
  currency: string;
}

interface Client360CampaignStatsResponse {
  campaign: Client360Campaign;
  stats: Client360CampaignStats;
}

interface Client360CampaignDraftsResult {
  campaign: Client360Campaign;
  created?: number;
  prepared?: number;
  skipped: Record<string, number>;
  drafts: Client360MailDraft[];
}

interface CampaignDraftsOutcome {
  campaignId: string;
  followUp: boolean;
  created: number;
  prepared: number;
  skippedTotal: number;
  skipped: Array<{ reason: string; count: number; label: string }>;
}

@Component({
  selector: 'app-client360-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, NgClass, GlyphComponent, PageFrameComponent],
  template: `
    <ck-page-frame eyebrow="Andritz / Spare Parts" title="Client360 PDR" [hasActions]="true">
      <button actions type="button" class="icon-button" [title]="i18n.t('client360.refresh')" (click)="refresh()">
        <ck-glyph name="orbit" [size]="14" color="currentColor" />
      </button>

      <nav sub class="ck-surface c360-tabs" aria-label="Client360 PDR">
        @for (tab of tabs; track tab.id) {
          <button type="button" (click)="openTab(tab.id)" [ngClass]="{ active: view() === tab.id }">
            {{ tab.label }}
          </button>
        }
      </nav>

      <section class="c360-workspace">
      @if (loading()) {
        <div class="state-line"><ck-glyph name="pulse" [size]="14" color="currentColor" /> {{ i18n.t('client360.loading') }}</div>
      } @else if (error()) {
        <div class="state-line error"><ck-glyph name="warn" [size]="14" color="currentColor" /> {{ error() }}</div>
      }

      <section class="kpi-grid">
        <div class="ck-surface kpi">
          <span>{{ i18n.t('client360.kpi.opportunities') }}</span>
          <strong>{{ summary()?.summary?.opportunities ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>{{ i18n.t('client360.kpi.customers') }}</span>
          <strong>{{ summary()?.summary?.customers ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>{{ i18n.t('client360.kpi.sources') }}</span>
          <strong>{{ summary()?.summary?.data_sources ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>{{ i18n.t('client360.kpi.addressable_gap') }}</span>
          <strong>{{ formatQty(summary()?.summary?.potential_gap_qty) }}</strong>
        </div>
      </section>

      @if (view() === 'opportunities') {
        @if (alerts().length > 0) {
          <section class="ck-surface alerts-panel">
            <div class="alerts-head">
              <h3><ck-glyph name="warn" [size]="14" color="currentColor" /> {{ i18n.t('client360.alerts.title', { count: alerts().length }) }}</h3>
              <div class="alerts-counts">
                @for (entry of alertCountEntries(); track entry.key) {
                  <button
                    type="button"
                    class="pill pill-filter"
                    [ngClass]="{ active: alertTypeFilter() === entry.key }"
                    [title]="i18n.t('client360.alerts.filter_hint')"
                    (click)="toggleAlertTypeFilter(entry.key)"
                  >
                    {{ labelAlertType(entry.key) }} · {{ entry.value }}
                  </button>
                }
              </div>
            </div>
            <ul class="alerts-list" [class.expanded]="alertsExpanded()">
              @for (alert of visibleAlerts(); track alert.id) {
                <li [ngClass]="alert.severity" (click)="openAlert(alert)">
                  <span class="alert-sev" [ngClass]="alert.severity">{{ labelAlertSeverity(alert.severity) }}</span>
                  <div class="alert-body">
                    <strong>{{ alert.title }}</strong>
                    <small>{{ alert.message }}</small>
                  </div>
                  @if (alert.opportunity_label) {
                    <span class="alert-target">{{ alert.opportunity_label }}</span>
                  }
                </li>
              }
            </ul>
            @if (filteredAlerts().length > visibleAlerts().length || alertsExpanded()) {
              <div class="button-row">
                <button type="button" class="secondary" (click)="toggleAlertsExpanded()">
                  @if (alertsExpanded()) {
                    {{ i18n.t('client360.alerts.collapse') }}
                  } @else {
                    {{ i18n.t('client360.alerts.show_all', { count: filteredAlerts().length }) }}
                  }
                </button>
              </div>
            }
          </section>
        }
        <section class="ck-surface toolbar">
          <label>
            {{ i18n.t('client360.filter.customer') }}
            <input
              type="search"
              [(ngModel)]="filters.customer"
              (keyup.enter)="loadOpportunities()"
              [placeholder]="i18n.t('client360.filter.customer_placeholder')"
            />
          </label>
          <label>
            {{ i18n.t('client360.filter.country') }}
            <select [(ngModel)]="filters.country" (change)="loadOpportunities()">
              <option value="">{{ i18n.t('client360.filter.all_countries') }}</option>
              @for (item of opportunitiesResponse()?.facets?.countries ?? []; track item) {
                <option [value]="item">{{ item }}</option>
              }
            </select>
          </label>
          <label>
            {{ i18n.t('client360.filter.part_family') }}
            <select [(ngModel)]="filters.part_family" (change)="loadOpportunities()">
              <option value="">{{ i18n.t('client360.filter.all_families') }}</option>
              @for (item of opportunitiesResponse()?.facets?.part_families ?? []; track item) {
                <option [value]="item">{{ item }}</option>
              }
            </select>
          </label>
          <label>
            {{ i18n.t('client360.filter.confidence') }}
            <select [(ngModel)]="filters.confidence" (change)="loadOpportunities()">
              <option value="">{{ i18n.t('client360.filter.any_confidence') }}</option>
              <option value="high">{{ i18n.t('client360.confidence.high') }}</option>
              <option value="medium">{{ i18n.t('client360.confidence.medium') }}</option>
              <option value="low">{{ i18n.t('client360.confidence.low') }}</option>
            </select>
          </label>
          <label>
            {{ i18n.t('client360.filter.sort') }}
            <select [ngModel]="sortKey()" (ngModelChange)="sortKey.set($event)">
              <option value="score">{{ i18n.t('client360.sort.score') }}</option>
              <option value="value">{{ i18n.t('client360.sort.value') }}</option>
            </select>
          </label>
          <button type="button" class="secondary" (click)="loadOpportunities()">
            <ck-glyph name="sliders" [size]="14" color="currentColor" />
            {{ i18n.t('client360.filter.apply') }}
          </button>
        </section>

        <section class="ck-surface table-wrap">
          @if (opportunities().length === 0) {
            <div class="empty">
              <ck-glyph name="ledger" [size]="18" color="currentColor" />
              <span>{{ i18n.t('client360.opportunities.empty') }}</span>
              <small>{{ i18n.t('client360.opportunities.empty_hint') }}</small>
            </div>
          } @else {
            <table>
              <thead>
                <tr>
                  <th>{{ i18n.t('client360.table.customer') }}</th>
                  <th>{{ i18n.t('client360.table.part') }}</th>
                  <th>{{ i18n.t('client360.table.country') }}</th>
                  <th>{{ i18n.t('client360.table.due') }}</th>
                  <th>{{ i18n.t('client360.table.potential') }}</th>
                  <th>{{ i18n.t('client360.table.known_purchases') }}</th>
                  <th>{{ i18n.t('client360.table.purchase_gap') }}</th>
                  <th>{{ i18n.t('client360.table.potential_value') }}</th>
                  <th>{{ i18n.t('client360.table.confidence') }}</th>
                  <th>{{ i18n.t('client360.table.action') }}</th>
                  <th>{{ i18n.t('client360.table.status') }}</th>
                </tr>
              </thead>
              <tbody>
                @for (opp of visibleOpportunities(); track opp.id) {
                  <tr (click)="selectOpportunity(opp)">
                    <td>
                      <strong>{{ opp.customer_name }}</strong>
                      <small>{{ opp.technology || opp.line_label || opp.machine_label || i18n.t('client360.placeholder.scope') }}</small>
                    </td>
                    <td>
                      <strong>{{ opp.part_family }}</strong>
                      <small>{{ opp.part_reference || opp.part_description || i18n.t('client360.placeholder.reference') }}</small>
                    </td>
                    <td>{{ opp.country || opp.hub || i18n.t('client360.placeholder.todo') }}</td>
                    <td>{{ formatDate(opp.next_due_at) }}</td>
                    <td>{{ formatQty(opp.potential_theoretical) }}</td>
                    <td>{{ formatQty(opp.sales_known_qty) }}</td>
                    <td>{{ formatQty(opp.potential_gap_qty) }}</td>
                    <td>{{ formatCurrency(opp.potential_gap_value, opp.currency) }}</td>
                    <td><span class="pill" [ngClass]="opp.confidence_label">{{ labelConfidence(opp.confidence_label) }}</span></td>
                    <td>{{ labelAction(opp.recommended_action) }}</td>
                    <td><span class="status">{{ labelStatus(opp.status) }}</span></td>
                  </tr>
                }
              </tbody>
            </table>
            @if (sortedOpportunities().length > opportunitiesTableLimit()) {
              <div class="button-row show-more-row">
                <button type="button" class="secondary" (click)="showMoreOpportunitiesTable()">
                  {{ i18n.t('client360.show_more', { count: sortedOpportunities().length - opportunitiesTableLimit() }) }}
                </button>
              </div>
            }
          }
        </section>
      }

      @if (view() === 'customer') {
        <section class="split">
          <aside class="ck-surface list-panel">
            <label class="directory-search">
              {{ i18n.t('client360.directory.label') }}
              <input
                type="search"
                [(ngModel)]="customerDirectoryQuery"
                (keyup.enter)="loadCustomers()"
                (ngModelChange)="onCustomerDirectoryQueryChange()"
                [placeholder]="i18n.t('client360.directory.search_placeholder')"
              />
            </label>
            @if (customerDirectoryFacets().countries.length || customerDirectoryFacets().technologies.length) {
              <div class="directory-facets">
                <label>
                  {{ i18n.t('client360.filter.country') }}
                  <select [(ngModel)]="customerDirectoryCountry" (ngModelChange)="loadCustomers()">
                    <option value="">{{ i18n.t('client360.filter.all_countries') }}</option>
                    @for (country of customerDirectoryFacets().countries; track country) {
                      <option [value]="country">{{ country }}</option>
                    }
                  </select>
                </label>
                <label>
                  {{ i18n.t('client360.filter.technology') }}
                  <select [(ngModel)]="customerDirectoryTechnology" (ngModelChange)="loadCustomers()">
                    <option value="">{{ i18n.t('client360.filter.all_technologies') }}</option>
                    @for (tech of customerDirectoryFacets().technologies; track tech) {
                      <option [value]="tech">{{ tech }}</option>
                    }
                  </select>
                </label>
              </div>
            }
            @if (directorySelection().length) {
              <div class="directory-selection-bar">
                <button type="button" class="primary" (click)="startCampaignFromSelection()">
                  <ck-glyph name="ledger" [size]="14" color="currentColor" />
                  {{ i18n.t('client360.directory.create_campaign', { count: directorySelection().length }) }}
                </button>
                <button type="button" class="secondary" [title]="i18n.t('client360.directory.clear_hint')" (click)="clearDirectorySelection()">{{ i18n.t('client360.directory.clear') }}</button>
              </div>
            }
            <div class="directory-list">
              @for (customer of directoryCustomers(); track customer.customer_key) {
                <div class="directory-row">
                  <input
                    type="checkbox"
                    [checked]="isDirectoryCustomerSelected(customer.customer_key)"
                    (change)="toggleDirectoryCustomer(customer.customer_key)"
                    [attr.aria-label]="i18n.t('client360.directory.select_customer', { name: customer.customer_name })"
                    [title]="i18n.t('client360.directory.select_hint')"
                  />
                  <button
                    type="button"
                    [ngClass]="{ active: selectedDirectoryCustomerKey() === customer.customer_key }"
                    (click)="selectDirectoryCustomer(customer)"
                  >
                    <strong>{{ customer.customer_name }}</strong>
                    <span>
                      {{ customer.countries.join(', ') || i18n.t('client360.placeholder.country') }}
                      · {{ customer.opportunity_count }} opp.
                      · {{ formatCurrency(customer.potential_gap_value, customer.currency) }}
                    </span>
                  </button>
                </div>
              }
              @if (!directoryCustomers().length) {
                <div class="empty compact"><span>{{ i18n.t('client360.directory.empty') }}</span></div>
              }
            </div>
          </aside>
          <article class="ck-surface detail-panel">
            @if (customerDetailLoading()) {
              <div class="detail-loader" role="status">
                <ck-glyph name="pulse" [size]="16" color="currentColor" />
                <span>{{ i18n.t('client360.customer.loading') }}</span>
              </div>
            } @else if (selectedCustomer(); as fiche) {
              <div class="detail-head">
                <div>
                  <p class="ck-label c360-eyebrow">{{ i18n.t('client360.customer.eyebrow') }}</p>
                  <h2>{{ fiche.customer.name }}</h2>
                  <div class="chips">
                    @for (country of fiche.customer.countries; track country) {
                      <span>{{ country }}</span>
                    }
                    @for (hub of fiche.customer.hubs; track hub) {
                      <span>{{ hub }}</span>
                    }
                    @for (tech of fiche.customer.technologies; track tech) {
                      <span>{{ tech }}</span>
                    }
                  </div>
                </div>
                @if (selectedOpportunity(); as selectedOpp) {
                  <div class="detail-actions">
                    <div class="button-row">
                      <button type="button" class="secondary" (click)="updateOpportunityStatus(selectedOpp, 'validated')">
                        <ck-glyph name="check" [size]="14" color="currentColor" />
                        {{ i18n.t('client360.validate') }}
                      </button>
                      <button type="button" class="secondary" (click)="updateOpportunityStatus(selectedOpp, 'dismissed')">
                        <ck-glyph name="x" [size]="14" color="currentColor" />
                        {{ i18n.t('client360.customer.dismiss') }}
                      </button>
                      <button
                        type="button"
                        class="primary"
                        [disabled]="isGeneratingDraft(selectedOpp)"
                        [attr.aria-busy]="isGeneratingDraft(selectedOpp)"
                        [ngClass]="{ 'is-loading': isGeneratingDraft(selectedOpp) }"
                        (click)="generateDraft(selectedOpp)"
                      >
                        @if (isGeneratingDraft(selectedOpp)) {
                          <ck-glyph name="pulse" [size]="14" color="currentColor" />
                          {{ i18n.t('client360.customer.generating') }}
                        } @else {
                          <ck-glyph name="ledger" [size]="14" color="currentColor" />
                          {{ i18n.t('client360.customer.mail_draft') }}
                        }
                      </button>
                    </div>
                  </div>
                }
              </div>

              @if (fiche.ai_summary; as summaryAi) {
                <section class="c360-summary">
                  <div class="c360-summary-head">
                    <p class="ck-label c360-eyebrow">{{ i18n.t('client360.summary.title') }}</p>
                    <span class="pill" [ngClass]="summaryAi.generation_mode">{{ summaryModeLabel(summaryAi) }}</span>
                  </div>
                  <p class="c360-summary-text">{{ summaryAi.text }}</p>
                  @if ((summaryAi.highlights ?? []).length) {
                    <div class="chips">
                      @for (item of summaryAi.highlights ?? []; track item) {
                        <span>{{ item }}</span>
                      }
                    </div>
                  }
                  <p class="hint">{{ summaryModelLabel(summaryAi) }}</p>
                </section>
              } @else if (customerSummaryLoading()) {
                <section class="c360-summary">
                  <div class="c360-summary-head">
                    <p class="ck-label c360-eyebrow">{{ i18n.t('client360.summary.title') }}</p>
                    <span class="pill">{{ i18n.t('client360.customer.generating') }}</span>
                  </div>
                  <p class="hint" role="status">
                    <ck-glyph name="pulse" [size]="14" color="currentColor" />
                    {{ i18n.t('client360.summary.writing') }}
                  </p>
                </section>
              }

              <h3>{{ i18n.t('client360.section.identity') }}</h3>
              <dl class="facts">
                <div><dt>{{ i18n.t('client360.fact.customer') }}</dt><dd>{{ fiche.customer.name }}</dd></div>
                <div><dt>{{ i18n.t('client360.fact.country') }}</dt><dd>{{ fiche.customer.countries.join(', ') || i18n.t('client360.placeholder.todo') }}</dd></div>
                <div><dt>{{ i18n.t('client360.fact.hubs') }}</dt><dd>{{ fiche.customer.hubs.join(', ') || i18n.t('client360.placeholder.todo') }}</dd></div>
                <div><dt>{{ i18n.t('client360.fact.technologies') }}</dt><dd>{{ fiche.customer.technologies.join(', ') || i18n.t('client360.placeholder.todo') }}</dd></div>
                <div><dt>{{ i18n.t('client360.fact.projects') }}</dt><dd>{{ (fiche.projects ?? []).length }}</dd></div>
                <div><dt>{{ i18n.t('client360.fact.opportunities') }}</dt><dd>{{ fiche.opportunities.length }}</dd></div>
              </dl>

              <h3>{{ i18n.t('client360.section.projects') }}</h3>
              @if ((fiche.projects ?? []).length) {
                <div class="chips">
                  @for (project of fiche.projects ?? []; track project.project_code || project.sap_reference || $index) {
                    <button type="button" class="chip-button" (click)="focusProject(project)">
                      {{ project.project_code || project.sap_reference || i18n.t('client360.placeholder.project') }}
                      <small>{{ project.sap_reference && project.project_code ? project.sap_reference : (project.country || '') }}</small>
                    </button>
                  }
                </div>
              } @else {
                <p class="hint">{{ i18n.t('client360.customer.no_projects') }}</p>
              }

              <h3>{{ i18n.t('client360.section.installed_base') }}</h3>
              @if ((fiche.machines ?? []).length) {
                <div class="c360-tree">
                  @for (machine of machinesForFocusedProject(); track machine.machine_label + (machine.project_code || '')) {
                    <div class="c360-tree-machine">
                      <p class="c360-tree-machine-head">
                        <span>{{ machine.machine_label || i18n.t('client360.placeholder.machine') }}</span>
                        <span>{{ machine.technology || i18n.t('client360.placeholder.technology') }}</span>
                      </p>
                      <p class="hint">
                        {{ machine.line_label || i18n.t('client360.placeholder.line') }}
                        @if (machine.project_code) { · {{ machine.project_code }} }
                        @if (machine.construction_year) { · {{ machine.construction_year }} }
                      </p>
                    </div>
                  }
                </div>
              }
              @if ((fiche.installed_base ?? []).length) {
                <div class="c360-tree">
                  @for (tech of fiche.installed_base ?? []; track tech.technology) {
                    <details class="c360-tree-node" open>
                      <summary>
                        <strong>{{ tech.technology }}</strong>
                        <span>{{ tech.opportunity_count }} opp. · {{ formatCurrency(tech.potential_gap_value, null) }}</span>
                      </summary>
                      @for (line of tech.lines; track line.line_label) {
                        <details class="c360-tree-line" open>
                          <summary>
                            <span>{{ line.line_label }}</span>
                            <span>{{ formatCurrency(line.potential_gap_value, null) }}</span>
                          </summary>
                          @for (machine of line.machines; track machine.machine_label) {
                            <div class="c360-tree-machine">
                              <p class="c360-tree-machine-head">
                                <span>{{ machine.machine_label }}</span>
                                <span>{{ formatCurrency(machine.potential_gap_value, null) }}</span>
                              </p>
                              @for (part of machine.parts; track part.opportunity_id) {
                                <button type="button" class="c360-tree-part linkish" (click)="selectOpportunityFromFiche(part.opportunity_id)">
                                  <span class="c360-tree-part-label">{{ part.part_family }}<small>{{ part.part_reference ? ' · ' + part.part_reference : '' }}</small></span>
                                  <span class="c360-tree-part-meta">
                                    {{ i18n.t('client360.tree.gap') }} {{ formatQty(part.potential_gap_qty) }} · {{ formatCurrency(part.potential_gap_value, part.currency) }}
                                  </span>
                                </button>
                              }
                            </div>
                          }
                        </details>
                      }
                    </details>
                  }
                </div>
              }
              @if (!(fiche.machines ?? []).length && !(fiche.installed_base ?? []).length) {
                <p class="hint">{{ i18n.t('client360.customer.no_installed_base') }}</p>
              }

              <h3>{{ i18n.t('client360.section.purchases') }}</h3>
              @if ((fiche.purchases ?? []).length) {
                <div class="table-wrap compact-table">
                  <table>
                    <thead>
                      <tr>
                        <th>{{ i18n.t('client360.purchases.part') }}</th>
                        <th>{{ i18n.t('client360.purchases.qty') }}</th>
                        <th>{{ i18n.t('client360.purchases.value') }}</th>
                        <th>{{ i18n.t('client360.purchases.po_cost') }}</th>
                        <th>{{ i18n.t('client360.purchases.lead_time') }}</th>
                        <th>{{ i18n.t('client360.purchases.last_order') }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (purchase of fichePurchases(); track purchase.part_reference) {
                        <tr (click)="selectPurchasePart(purchase.part_reference)">
                          <td>
                            <strong>{{ purchase.part_reference }}</strong>
                            <small>{{ purchase.part_description || '' }}</small>
                          </td>
                          <td>{{ formatQty(purchase.sales_known_qty) }}</td>
                          <td>{{ formatCurrency(purchase.sales_known_value, purchase.currency) }}</td>
                          <td>{{ formatCurrency(purchase.unit_cost, purchase.currency) }}</td>
                          <td>{{ formatWeeks(purchase.delivery_time_weeks) }}</td>
                          <td>{{ formatDate(purchase.last_document_date) }}</td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
                @if ((fiche.purchases ?? []).length > fichePurchasesLimit()) {
                  <div class="button-row show-more-row">
                    <button type="button" class="secondary" (click)="showMoreFichePurchases()">
                      {{ i18n.t('client360.show_more', { count: (fiche.purchases ?? []).length - fichePurchasesLimit() }) }}
                    </button>
                  </div>
                }
              } @else {
                <p class="hint">{{ i18n.t('client360.customer.no_orders') }}</p>
              }

              <h3>{{ i18n.t('client360.section.upcoming') }}</h3>
              @if ((fiche.next_due ?? []).length) {
                <div class="chips">
                  @for (item of fiche.next_due ?? []; track item.part_reference || item.next_due_at || $index) {
                    <span>
                      {{ item.part_reference || item.part_family || i18n.t('client360.placeholder.part') }}
                      · {{ formatDate(item.next_due_at) }}
                    </span>
                  }
                </div>
                <div class="button-row" style="margin-top: 10px;">
                  <button
                    type="button"
                    class="secondary"
                    [title]="i18n.t('client360.upcoming.campaign_hint')"
                    (click)="startCampaignFromNextDue(fiche)"
                  >
                    <ck-glyph name="ledger" [size]="14" color="currentColor" />
                    {{ i18n.t('client360.upcoming.campaign_cta') }}
                  </button>
                </div>
                <p class="hint">{{ i18n.t('client360.upcoming.note') }}</p>
              } @else {
                <p class="hint">{{ i18n.t('client360.customer.no_due_dates') }}</p>
              }

              <h3>{{ i18n.t('client360.section.opportunities') }}</h3>
              @if (fiche.opportunities.length) {
                <div class="chips">
                  @for (opp of ficheOpportunities(); track opp.id) {
                    <button
                      type="button"
                      class="chip-button"
                      [ngClass]="{ active: selectedOpportunity()?.id === opp.id }"
                      (click)="selectOpportunityFromFiche(opp.id)"
                    >
                      {{ opp.part_family || opp.part_reference || i18n.t('client360.placeholder.opportunity') }}
                      <small>{{ formatCurrency(opp.potential_gap_value, opp.currency) }}</small>
                    </button>
                  }
                  @if (fiche.opportunities.length > ficheOpportunitiesLimit()) {
                    <button type="button" class="chip-button" (click)="showMoreFicheOpportunities()">
                      {{ i18n.t('client360.opportunities.more', { count: fiche.opportunities.length - ficheOpportunitiesLimit() }) }}
                    </button>
                  }
                </div>
                <div class="button-row" style="margin-top: 10px;">
                  @if (selectedOpportunity(); as selectedOpp) {
                    <button
                      type="button"
                      class="primary"
                      [disabled]="isGeneratingDraft(selectedOpp)"
                      [title]="i18n.t('client360.draft.open_hint')"
                      (click)="generateDraft(selectedOpp)"
                    >
                      <ck-glyph name="ledger" [size]="14" color="currentColor" />
                      {{ i18n.t('client360.draft.cta', { label: selectedOpp.part_family || selectedOpp.part_reference || i18n.t('client360.placeholder.opportunity') }) }}
                    </button>
                  } @else {
                    <button type="button" class="primary" disabled [title]="i18n.t('client360.draft.select_first')">
                      <ck-glyph name="ledger" [size]="14" color="currentColor" />
                      {{ i18n.t('client360.customer.mail_draft') }}
                    </button>
                  }
                </div>
                <p class="hint">{{ i18n.t('client360.draft.note') }}</p>
              } @else {
                <p class="hint">{{ i18n.t('client360.customer.no_opportunities') }}</p>
              }

              @if (selectedOpportunity(); as selectedOpp) {
                <h3>{{ i18n.t('client360.section.selected_opportunity') }}</h3>
                <dl class="facts">
                  <div><dt>{{ i18n.t('client360.fact.country_hub') }}</dt><dd>{{ selectedOpp.country || selectedOpp.hub || i18n.t('client360.placeholder.todo') }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.technology') }}</dt><dd>{{ selectedOpp.technology || i18n.t('client360.placeholder.todo') }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.part') }}</dt><dd>{{ selectedOpp.part_family }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.periodicity') }}</dt><dd>{{ formatWeeks(selectedOpp.periodicity_weeks) }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.annual_qty') }}</dt><dd>{{ formatQty(selectedOpp.annual_theoretical_qty) }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.sap_known') }}</dt><dd>{{ formatQty(selectedOpp.sales_known_qty) }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.gap_vs_purchases') }}</dt><dd>{{ formatQty(selectedOpp.potential_gap_qty) }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.potential_value') }}</dt><dd>{{ formatCurrency(selectedOpp.potential_gap_value, selectedOpp.currency) }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.weighted_addressable') }}</dt><dd>{{ formatQty(selectedOpp.potential_addressable) }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.lead_time') }}</dt><dd>{{ formatWeeks(selectedOpp.delivery_time_weeks) }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.due') }}</dt><dd>{{ formatDate(selectedOpp.next_due_at) }}</dd></div>
                  <div><dt>{{ i18n.t('client360.fact.action') }}</dt><dd>{{ labelAction(selectedOpp.recommended_action) }}</dd></div>
                </dl>
                <h3>{{ i18n.t('client360.section.missing_data') }}</h3>
                <div class="chips">
                  @for (gap of selectedOpp.data_gaps; track gap) {
                    <span>{{ labelGap(gap) }}</span>
                  }
                </div>
                <h3>{{ i18n.t('client360.section.score_reasons') }}</h3>
                <div class="reason-list">
                  @for (reason of selectedOpp.score_reasons; track reason.code) {
                    <span [ngClass]="{ met: reason.met }">{{ reason.label }}</span>
                  }
                </div>
              }

              <h3>{{ i18n.t('client360.section.timeline') }}</h3>
              @if ((fiche.timeline ?? []).length) {
                <ol class="c360-timeline">
                  @for (event of ficheTimeline(); track $index) {
                    <li [ngClass]="timelineKindClass(event.kind)">
                      <span class="c360-timeline-when">{{ formatDateTime(event.at) }}</span>
                      <span class="c360-timeline-kind">{{ timelineKindLabel(event.kind) }}</span>
                      <span class="c360-timeline-label">{{ event.label }}</span>
                    </li>
                  }
                </ol>
                @if ((fiche.timeline ?? []).length > ficheTimelineLimit()) {
                  <div class="button-row show-more-row">
                    <button type="button" class="secondary" (click)="showMoreFicheTimeline()">
                      {{ i18n.t('client360.show_more', { count: (fiche.timeline ?? []).length - ficheTimelineLimit() }) }}
                    </button>
                  </div>
                }
              } @else {
                <p class="hint">{{ i18n.t('client360.customer.no_timeline') }}</p>
              }

              <h3>{{ i18n.t('client360.section.external_signals') }}</h3>
              <div class="chips">
                @for (signal of fiche.market_signals; track signal.id) {
                  <span>{{ signal.label }}</span>
                }
                @if (fiche.market_signals.length === 0) {
                  <span>{{ i18n.t('client360.customer.no_signal') }}</span>
                }
              </div>
            } @else {
              <div class="empty"><span>{{ i18n.t('client360.customer.select_prompt') }}</span></div>
            }
          </article>
        </section>
      }

      @if (view() === 'data') {
        <section class="data-layout">
          <div class="ck-surface gap-panel">
            <div class="detail-head compact">
              <div>
                <p class="ck-label c360-eyebrow">{{ i18n.t('client360.data.collection_eyebrow') }}</p>
                <h2>Installed base SPL</h2>
              </div>
            </div>
            <dl class="engine-facts">
              <div><dt>Slug</dt><dd class="mono-slug">{{ unifiedCollectionSlug }}</dd></div>
              <div><dt>{{ i18n.t('client360.data.linked_sources') }}</dt><dd>{{ unifiedCollectionStats().linkedSources }} / {{ unifiedCollectionStats().totalSources }}</dd></div>
              <div><dt>{{ i18n.t('client360.data.ready') }}</dt><dd>{{ unifiedCollectionStats().readySources }}</dd></div>
              <div><dt>{{ i18n.t('client360.data.files_origins') }}</dt><dd>{{ unifiedCollectionStats().originSummary }}</dd></div>
            </dl>
            <h3>{{ i18n.t('client360.data.counts_by_type') }}</h3>
            <div class="chips">
              @for (entry of unifiedCollectionStats().typeEntries; track entry.key) {
                <span>{{ labelSourceType(entry.key) }} · {{ entry.count }}{{ entry.rows != null ? ' · ' + formatQty(entry.rows) + ' ' + i18n.t('client360.data.rows_suffix') : '' }}</span>
              }
              @if (unifiedCollectionStats().typeEntries.length === 0) {
                <span>{{ i18n.t('client360.data.no_sources') }}</span>
              }
            </div>
            @if (!unifiedCollectionStats().hasLinkedSources && unifiedCollectionStats().totalSources > 0) {
              <p class="hint">
                {{ i18n.t('client360.data.no_link_hint', { slug: unifiedCollectionSlug }) }}
              </p>
            }
            <div class="data-actions">
              <button
                type="button"
                class="primary"
                [disabled]="syncBusy()"
                [attr.aria-busy]="syncBusy()"
                [ngClass]="{ 'is-loading': syncBusy() }"
                (click)="syncFromCollection(false)"
              >
                @if (syncBusy()) {
                  <ck-glyph name="pulse" [size]="14" color="currentColor" />
                  {{ i18n.t('client360.data.syncing') }}
                } @else {
                  <ck-glyph name="orbit" [size]="14" color="currentColor" />
                  {{ i18n.t('client360.data.sync') }}
                }
              </button>
              <button type="button" class="secondary" [disabled]="loading()" (click)="runEngine(true)">
                <ck-glyph name="sliders" [size]="14" color="currentColor" />
                {{ i18n.t('client360.data.dry_run') }}
              </button>
              <button type="button" class="primary" [disabled]="loading()" (click)="runEngine(false)">
                <ck-glyph name="play" [size]="14" color="currentColor" />
                {{ i18n.t('client360.data.compute') }}
              </button>
            </div>
            @if (syncStatus()) {
              <div class="action-status" role="status" aria-live="polite">{{ syncStatus() }}</div>
            }
            @if (syncResult()) {
              <dl class="engine-facts">
                <div><dt>{{ i18n.t('client360.data.sync_label') }}</dt><dd>{{ syncResult()?.dry_run ? i18n.t('client360.data.dry_run_value') : i18n.t('client360.data.applied') }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.sources_seen') }}</dt><dd>{{ syncResult()?.sources_seen ?? '-' }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.upsert') }}</dt><dd>{{ syncResult()?.sources_upserted ?? '-' }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.records') }}</dt><dd>{{ syncResult()?.records_seen ?? '-' }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.created') }}</dt><dd>{{ syncResult()?.created ?? '-' }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.updated') }}</dt><dd>{{ syncResult()?.updated ?? '-' }}</dd></div>
              </dl>
            }
            <div class="scope-panel">
              <h3>{{ i18n.t('client360.data.business_gaps') }}</h3>
              <div class="chips">
                @for (gap of summary()?.data_gaps ?? []; track gap) {
                  <span>{{ labelGap(gap) }}</span>
                }
                @if ((summary()?.data_gaps ?? []).length === 0) {
                  <span class="ok">{{ i18n.t('client360.data.min_sources_ok') }}</span>
                }
              </div>
              <h3>{{ i18n.t('client360.data.mvp_scope') }}</h3>
              <p>{{ summary()?.positioning?.mvp_contract?.promise || i18n.t('client360.data.mvp_promise') }}</p>
              <div class="chips">
                @for (segment of campaignSegments(); track segment.id) {
                  <span>{{ segment.label }}</span>
                }
              </div>
              <h3>{{ i18n.t('client360.data.ai_routing') }}</h3>
              <dl class="engine-facts">
                <div><dt>{{ i18n.t('client360.data.mode') }}</dt><dd>{{ mailAiStatusLabel() }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.route') }}</dt><dd>{{ mailAiRouteLabel() }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.runtime') }}</dt><dd>{{ mailAiModelLabel() }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.source') }}</dt><dd>{{ mailAiSourceLabel() }}</dd></div>
              </dl>
            </div>
            @if (engineResult()) {
              <dl class="engine-facts">
                <div><dt>{{ i18n.t('client360.data.records_read') }}</dt><dd>{{ engineResult()?.records_seen }}</dd></div>
                <div><dt>{{ i18n.t('client360.kpi.opportunities') }}</dt><dd>{{ engineResult()?.opportunities_detected }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.created') }}</dt><dd>{{ engineResult()?.created }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.updated') }}</dt><dd>{{ engineResult()?.updated }}</dd></div>
                <div><dt>{{ i18n.t('client360.data.mappings') }}</dt><dd>{{ engineResult()?.candidate_mappings_created }}</dd></div>
              </dl>
            }
          </div>
          <div class="ck-surface table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{{ i18n.t('client360.sources.type') }}</th>
                  <th>{{ i18n.t('client360.sources.source') }}</th>
                  <th>{{ i18n.t('client360.sources.collection') }}</th>
                  <th>{{ i18n.t('client360.sources.rows') }}</th>
                  <th>{{ i18n.t('client360.sources.status') }}</th>
                </tr>
              </thead>
              <tbody>
                @for (source of summary()?.data_sources ?? []; track source.id) {
                  <tr [ngClass]="{ 'is-unified': source.collection_slug === unifiedCollectionSlug }">
                    <td>{{ labelSourceType(source.source_type, source.metadata) }}</td>
                    <td>
                      <strong>{{ source.label }}</strong>
                      <small>{{ source.origin }}{{ source.filename ? ' · ' + source.filename : '' }}</small>
                    </td>
                    <td>{{ source.collection_slug || '-' }}</td>
                    <td>{{ source.row_count != null ? formatQty(source.row_count) : '-' }}</td>
                    <td><span class="status">{{ source.status }}</span></td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }

      @if (view() === 'mapping') {
        <section class="ck-surface table-wrap">
          @if (mappings().length === 0) {
            <div class="empty">
              <ck-glyph name="flow" [size]="18" color="currentColor" />
              <span>{{ i18n.t('client360.mapping.empty') }}</span>
              <small>{{ i18n.t('client360.mapping.hint') }}</small>
            </div>
          } @else {
            <table>
              <thead>
                <tr>
                  <th>{{ i18n.t('client360.mapping.source') }}</th>
                  <th>{{ i18n.t('client360.mapping.family') }}</th>
                  <th>{{ i18n.t('client360.mapping.technology') }}</th>
                  <th>{{ i18n.t('client360.mapping.periodicity') }}</th>
                  <th>{{ i18n.t('client360.mapping.status') }}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (mapping of mappings(); track mapping.id) {
                  <tr>
                    <td>
                      <strong>{{ mapping.source_part_reference || mapping.source_part_family || mapping.source_part_label || '-' }}</strong>
                      <small>{{ mapping.notes || i18n.t('client360.mapping.semi_manual') }}</small>
                    </td>
                    <td>{{ mapping.pdr_family }}</td>
                    <td>{{ mapping.technology || '-' }}</td>
                    <td>{{ formatWeeks(mapping.periodicity_weeks) }}</td>
                    <td><span class="status">{{ labelMappingStatus(mapping.status) }}</span></td>
                    <td>
                      @if (mapping.status !== 'validated') {
                        <button type="button" class="secondary" (click)="validateMapping(mapping)">
                          <ck-glyph name="check" [size]="14" color="currentColor" />
                          {{ i18n.t('client360.validate') }}
                        </button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          }
        </section>
      }

      @if (view() === 'mail') {
        <section class="mail-layout">
          <div class="ck-surface detail-panel mail-editor-panel">
            <div class="detail-head">
              <div>
                <p class="ck-label c360-eyebrow">{{ i18n.t('client360.tab.mail') }}</p>
                <h2>{{ currentDraft()?.subject || i18n.t('client360.mail.no_draft') }}</h2>
                @if (currentDraft()) {
                  <div class="draft-meta">
                    <span class="pill" [ngClass]="draftGenerationMode(currentDraft())">
                      {{ draftGenerationLabel(currentDraft()) }}
                    </span>
                    @if (draftGenerationModel(currentDraft())) {
                      <span>{{ draftGenerationModel(currentDraft()) }}</span>
                    }
                  </div>
                }
              </div>
            </div>
            <div class="draft-fields">
              <label>
                {{ i18n.t('client360.mail.recipient') }}
                <input type="email" [(ngModel)]="recipientEmail" placeholder="contact@client.com" />
              </label>
              <label>
                {{ i18n.t('client360.mail.subject') }}
                <input type="text" [ngModel]="draftSubject()" (ngModelChange)="draftSubject.set($event)" />
              </label>
            </div>
            <textarea class="mail-textarea" [ngModel]="draftBody()" (ngModelChange)="draftBody.set($event)"></textarea>
            <div class="mail-actions">
              <button
                type="button"
                class="primary"
                [disabled]="!canSendMail()"
                [attr.aria-busy]="isSendingMail()"
                [ngClass]="{ 'is-loading': isSendingMail() }"
                (click)="sendCurrentDraft()"
              >
                @if (isSendingMail()) {
                  <ck-glyph name="pulse" [size]="14" color="currentColor" />
                  {{ i18n.t('client360.mail.sending') }}
                } @else {
                  <ck-glyph name="arrow-up" [size]="14" color="currentColor" />
                  {{ i18n.t('client360.mail.send') }}
                }
              </button>
              @if (currentDraft()?.action_item_id) {
                <button type="button" class="secondary" (click)="markSent()" [disabled]="isSendingMail()">
                  <ck-glyph name="check" [size]="14" color="currentColor" />
                  {{ i18n.t('client360.mail.mark_sent') }}
                </button>
              }
              @if (mailStatus()) {
                <div class="action-status" role="status" aria-live="polite">
                  @if (isSendingMail()) {
                    <ck-glyph name="pulse" [size]="12" color="currentColor" />
                  }
                  {{ mailStatus() }}
                </div>
              }
            </div>
            @if (currentDraft() && !mailSettings()?.configured) {
              <p class="hint">
                {{ i18n.t('client360.mail.smtp_unavailable', { detail: smtpStatusDetail() || i18n.t('client360.mail.incomplete_config') }) }}
              </p>
            }
            <p class="hint">{{ i18n.t('client360.mail.human_review') }}</p>
          </div>
          <aside class="side-stack">
            <section class="ck-surface impact-panel">
              <h3>{{ i18n.t('client360.impact.title') }}</h3>
              <label>
                {{ i18n.t('client360.impact.attribution') }}
                <select [(ngModel)]="impactAttribution">
                  <option value="direct">{{ i18n.t('client360.impact.attribution.direct') }}</option>
                  <option value="probable">{{ i18n.t('client360.impact.attribution.probable') }}</option>
                  <option value="unknown">{{ i18n.t('client360.impact.attribution.unknown') }}</option>
                  <option value="none">{{ i18n.t('client360.impact.attribution.none') }}</option>
                </select>
              </label>
              <label>
                {{ i18n.t('client360.impact.reason') }}
                <select [(ngModel)]="impactReason">
                  @for (reason of impactReasons; track reason) {
                    <option [value]="reason">{{ i18n.t('client360.impact.reason.' + reason) }}</option>
                  }
                </select>
              </label>
              <label>
                {{ i18n.t('client360.impact.comment') }}
                <textarea class="small-textarea" [(ngModel)]="impactSummary"></textarea>
              </label>
              <div class="impact-buttons">
                <button type="button" (click)="recordImpact('response')">{{ i18n.t('client360.impact.response') }}</button>
                <button type="button" (click)="recordImpact('quote')">{{ i18n.t('client360.impact.quote') }}</button>
                <button type="button" (click)="recordImpact('order')">{{ i18n.t('client360.impact.order') }}</button>
                <button type="button" (click)="recordImpact('lost')">{{ i18n.t('client360.impact.lost') }}</button>
              </div>
            </section>

            @if (followUpAlerts().length) {
              <section class="ck-surface impact-panel">
                <div class="panel-head">
                  <h3>{{ i18n.t('client360.followup.title', { count: followUpAlerts().length }) }}</h3>
                  <span class="pill" [title]="i18n.t('client360.followup.manual_hint')">{{ i18n.t('client360.followup.manual_pill') }}</span>
                </div>
                <ul class="followup-list">
                  @for (alert of followUpAlerts(); track alert.id) {
                    <li>
                      <strong>{{ alert.opportunity_label || alert.customer_key || i18n.t('client360.placeholder.opportunity') }}</strong>
                      <small>{{ alert.message }}</small>
                    </li>
                  }
                </ul>
                <p class="hint">{{ i18n.t('client360.followup.note') }}</p>
              </section>
            }

            <section class="ck-surface smtp-panel">
              <div class="panel-head">
                <h3>{{ i18n.t('client360.smtp.title') }}</h3>
                <span class="status" [ngClass]="{ ok: mailSettings()?.configured }">{{ smtpStatusLabel() }}</span>
              </div>
              <p class="hint">{{ smtpSourceLabel() }}{{ smtpStatusDetail() ? ' — ' + smtpStatusDetail() : '' }}</p>
              <label>
                {{ i18n.t('client360.smtp.host') }}
                <input type="text" [(ngModel)]="smtpHost" />
              </label>
              <div class="settings-grid">
                <label>
                  {{ i18n.t('client360.smtp.port') }}
                  <input type="number" [(ngModel)]="smtpPort" />
                </label>
                <label>
                  {{ i18n.t('client360.smtp.user') }}
                  <input type="text" [(ngModel)]="smtpUsername" />
                </label>
              </div>
              <label>
                {{ i18n.t('client360.smtp.password') }}
                <input type="password" [(ngModel)]="smtpPassword" [placeholder]="smtpPasswordPlaceholder()" />
              </label>
              <div class="settings-grid">
                <label>
                  {{ i18n.t('client360.smtp.from') }}
                  <input type="email" [(ngModel)]="smtpFromEmail" />
                </label>
                <label>
                  {{ i18n.t('client360.smtp.from_name') }}
                  <input type="text" [(ngModel)]="smtpFromName" />
                </label>
              </div>
              <div class="toggle-row">
                <label class="checkline"><input type="checkbox" [(ngModel)]="smtpEnabled" /> {{ i18n.t('client360.smtp.active') }}</label>
                <label class="checkline"><input type="checkbox" [(ngModel)]="smtpSsl" /> SSL</label>
                <label class="checkline"><input type="checkbox" [(ngModel)]="smtpStarttls" /> STARTTLS</label>
              </div>
              <button
                type="button"
                class="secondary"
                [disabled]="savingMailSettings()"
                [ngClass]="{ 'is-loading': savingMailSettings() }"
                (click)="saveMailSettings()"
              >
                @if (savingMailSettings()) {
                  <ck-glyph name="pulse" [size]="14" color="currentColor" />
                  {{ i18n.t('client360.smtp.saving') }}
                } @else {
                  <ck-glyph name="check" [size]="14" color="currentColor" />
                  {{ i18n.t('client360.smtp.save') }}
                }
              </button>
            </section>

            <section class="ck-surface smtp-panel mail-prompt-panel">
              <div class="panel-head">
                <h3>{{ i18n.t('client360.prompt.title') }}</h3>
                <span
                  class="status"
                  [ngClass]="{ ok: mailSettings()?.system_prompt_source === 'workspace' }"
                  [title]="i18n.t('client360.prompt.source_hint')"
                >
                  {{ mailPromptSourceLabel() }}
                </span>
              </div>
              <p class="hint mail-prompt-invariants">
                {{ i18n.t('client360.prompt.invariants') }}
                @if (mailSettings()?.prompt_version) {
                  <span class="mono-slug"> {{ mailSettings()?.prompt_version }}</span>
                }
              </p>
              <label>
                {{ i18n.t('client360.prompt.effective') }}
                <textarea
                  class="small-textarea prompt-textarea"
                  [(ngModel)]="mailSystemPrompt"
                  rows="10"
                ></textarea>
              </label>
              <div class="button-row mail-prompt-actions">
                <button
                  type="button"
                  class="secondary"
                  [disabled]="savingMailPrompt() || resettingMailPrompt()"
                  [ngClass]="{ 'is-loading': savingMailPrompt() }"
                  (click)="saveMailPrompt()"
                >
                  @if (savingMailPrompt()) {
                    <ck-glyph name="pulse" [size]="14" color="currentColor" />
                    {{ i18n.t('client360.smtp.saving') }}
                  } @else {
                    <ck-glyph name="check" [size]="14" color="currentColor" />
                    {{ i18n.t('client360.prompt.save') }}
                  }
                </button>
                <button
                  type="button"
                  class="secondary"
                  [disabled]="
                    resettingMailPrompt() ||
                    savingMailPrompt() ||
                    mailSettings()?.system_prompt_source !== 'workspace'
                  "
                  [attr.title]="
                    mailSettings()?.system_prompt_source === 'workspace'
                      ? i18n.t('client360.prompt.reset_hint')
                      : i18n.t('client360.prompt.already_default')
                  "
                  [ngClass]="{ 'is-loading': resettingMailPrompt() }"
                  (click)="resetMailPrompt()"
                >
                  @if (resettingMailPrompt()) {
                    <ck-glyph name="pulse" [size]="14" color="currentColor" />
                    {{ i18n.t('client360.prompt.resetting') }}
                  } @else {
                    {{ i18n.t('client360.prompt.reset') }}
                  }
                </button>
              </div>
            </section>
          </aside>
        </section>
      }

      @if (view() === 'campaigns') {
        <section class="split">
          <div class="ck-surface list-panel">
            <div class="panel-head">
              <h3>{{ i18n.t('client360.campaigns.title') }}</h3>
              <span class="muted">{{ campaigns().length }}</span>
            </div>
            <div class="campaign-form">
              <label>
                {{ i18n.t('client360.campaign.name') }}
                <input type="text" [(ngModel)]="campaignName" [placeholder]="i18n.t('client360.campaign.name_placeholder')" />
              </label>
              <label>
                {{ i18n.t('client360.campaign.type') }}
                <select [(ngModel)]="campaignType">
                  @for (type of campaignTypes; track type) {
                    <option [value]="type">{{ i18n.t('client360.campaign_type.' + type) }}</option>
                  }
                </select>
              </label>
              <div class="settings-grid">
                <label>
                  {{ i18n.t('client360.filter.country') }}
                  <input type="text" [(ngModel)]="campaignCriteria.country" [placeholder]="i18n.t('client360.filter.all_countries')" />
                </label>
                <label>
                  {{ i18n.t('client360.filter.technology') }}
                  <input type="text" [(ngModel)]="campaignCriteria.technology" [placeholder]="i18n.t('client360.filter.all_technologies')" />
                </label>
              </div>
              <div class="settings-grid">
                <label>
                  {{ i18n.t('client360.filter.part_family') }}
                  <input type="text" [(ngModel)]="campaignCriteria.part_family" [placeholder]="i18n.t('client360.filter.all_families')" />
                </label>
                <label>
                  {{ i18n.t('client360.filter.confidence') }}
                  <select [(ngModel)]="campaignCriteria.confidence">
                    <option value="">{{ i18n.t('client360.filter.any_confidence') }}</option>
                    <option value="high">{{ i18n.t('client360.confidence.high') }}</option>
                    <option value="medium">{{ i18n.t('client360.confidence.medium') }}</option>
                    <option value="low">{{ i18n.t('client360.confidence.low') }}</option>
                  </select>
                </label>
              </div>
              @if (campaignTargetCustomerKeys().length) {
                <div class="campaign-targeting">
                  <div class="panel-head">
                    <h3>{{ i18n.t('client360.campaign.target_title', { count: campaignTargetCustomerKeys().length }) }}</h3>
                    <button type="button" class="secondary" [title]="i18n.t('client360.campaign.remove_target_hint')" (click)="clearCampaignTargeting()">{{ i18n.t('client360.campaign.remove_target') }}</button>
                  </div>
                  <div class="chips">
                    @for (key of campaignTargetCustomerKeys(); track key) {
                      <span>{{ key }}</span>
                    }
                  </div>
                  <label>
                    Echeance sous (semaines)
                    <input type="number" min="1" max="520" [(ngModel)]="campaignDueWithinWeeks" placeholder="Toutes" />
                  </label>
                  <p class="hint">La campagne ciblera les opportunites de ces clients ; les filtres pays / techno / famille ci-dessus restent appliques.</p>
                </div>
              }
              <button type="button" class="primary" [disabled]="campaignBusy()" (click)="createCampaign()">
                <ck-glyph name="ledger" [size]="14" color="currentColor" />
                {{ campaignTargetCustomerKeys().length
                  ? 'Creer pour la selection (' + campaignTargetCustomerKeys().length + ')'
                  : 'Creer depuis les filtres' }}
              </button>
              @if (campaignStatus()) {
                <div class="action-status" role="status" aria-live="polite">{{ campaignStatus() }}</div>
              }
            </div>
            <ul class="campaign-list">
              @for (campaign of campaigns(); track campaign.id) {
                <li [ngClass]="{ active: selectedCampaign()?.id === campaign.id }" (click)="selectCampaign(campaign)">
                  <div class="campaign-line">
                    <strong>{{ campaign.name }}</strong>
                    <span class="pill" [ngClass]="campaign.status">{{ labelCampaignStatus(campaign.status) }}</span>
                  </div>
                  <small>{{ labelCampaignType(campaign.campaign_type) }} · {{ campaign.drafts_count }} brouillon(s) / {{ campaign.targeted_count }} cible(s)</small>
                </li>
              } @empty {
                <li class="muted">{{ i18n.t('client360.campaigns.empty') }}</li>
              }
            </ul>
          </div>

          <div class="ck-surface detail-panel">
            @if (selectedCampaign(); as campaign) {
              <div class="detail-head">
                <div>
                  <p class="ck-label c360-eyebrow">{{ labelCampaignType(campaign.campaign_type) }}</p>
                  <h2>{{ campaign.name }}</h2>
                  <span class="pill" [ngClass]="campaign.status">{{ labelCampaignStatus(campaign.status) }}</span>
                  @if (campaignCriteriaChips(campaign).length) {
                    <div class="chips">
                      @for (chip of campaignCriteriaChips(campaign); track chip) {
                        <span>{{ chip }}</span>
                      }
                    </div>
                  }
                </div>
                <div class="detail-actions">
                  <button type="button" class="primary" [disabled]="campaignBusy()" (click)="generateCampaignDrafts(false)">
                    <ck-glyph name="ledger" [size]="14" color="currentColor" /> Generer les brouillons
                  </button>
                  <button type="button" class="secondary" [disabled]="campaignBusy()" (click)="generateCampaignDrafts(true)">
                    <ck-glyph name="orbit" [size]="14" color="currentColor" /> Preparer relances
                  </button>
                </div>
              </div>
              <p class="c360-note">
                Validation humaine obligatoire, aucun envoi automatique. Les clients sans email de contact ou deja engages dans une campagne active sont exclus.
              </p>
              @if (campaignDraftsOutcome(); as outcome) {
                @if (outcome.campaignId === campaign.id) {
                  <section class="drafts-outcome" role="status" aria-live="polite">
                    <strong>
                      {{ outcome.followUp
                        ? outcome.prepared + ' relance(s) preparee(s)'
                        : outcome.created + ' brouillon(s) cree(s)' }}
                      · {{ outcome.skippedTotal }} ignore(s)
                    </strong>
                    @if (outcome.skipped.length) {
                      <ul>
                        @for (entry of outcome.skipped; track entry.reason) {
                          <li>{{ entry.count }} — {{ entry.label }}</li>
                        }
                      </ul>
                    } @else {
                      <small>Aucun client exclu par les regles de dedoublonnage.</small>
                    }
                  </section>
                }
              }
              @if (campaignStats(); as stats) {
                <section class="kpi-grid campaign-kpis">
                  <div class="ck-surface kpi"><span>CA potentiel</span><strong>{{ formatCurrency(stats.potential_gap_value, stats.currency) }}</strong></div>
                  <div class="ck-surface kpi"><span>CA attendu</span><strong>{{ formatCurrency(stats.expected_value, stats.currency) }}</strong></div>
                  <div class="ck-surface kpi"><span>Clients cibles</span><strong>{{ stats.targeted_customers }}</strong></div>
                  <div class="ck-surface kpi"><span>Brouillons</span><strong>{{ stats.drafts }}</strong></div>
                  <div class="ck-surface kpi"><span>Envoyes</span><strong>{{ stats.sent }}</strong></div>
                  <div class="ck-surface kpi"><span>Reponses</span><strong>{{ stats.responses }}</strong></div>
                  <div class="ck-surface kpi"><span>Devis</span><strong>{{ stats.quotes }}</strong></div>
                  <div class="ck-surface kpi"><span>Commandes</span><strong>{{ stats.orders }}</strong></div>
                  <div class="ck-surface kpi"><span>CA gagne</span><strong>{{ formatCurrency(stats.won_value, stats.currency) }}</strong></div>
                </section>
                <p class="hint">
                  CA attendu = potentiel adressable x proxy de conversion {{ conversionProxyLabel(stats) }}
                  — {{ stats.expected_value_disclaimer || 'estimation deterministe, a recaler des les premiers retours' }}.
                </p>
              }
            } @else {
              <div class="state-line">Selectionnez une campagne pour suivre sa transformation.</div>
            }
          </div>
        </section>
      }

      @if (view() === 'chat') {
        <section class="ck-surface chat-assistant">
          <div class="panel-head">
            <h3><ck-glyph name="orbit" [size]="14" color="currentColor" /> Assistant Client360</h3>
            <span class="muted">Opportunites, campagnes et fiches clients — reponses sourcees, jamais de SQL libre.</span>
          </div>
          <div class="chat-thread">
            @for (msg of chatMessages(); track $index) {
              <div class="chat-msg" [ngClass]="msg.role">
                <div class="chat-bubble">
                  <p class="chat-text">{{ msg.content }}</p>
                  @if (msg.sources?.length) {
                    <ul class="chat-sources">
                      @for (src of msg.sources; track $index) {
                        <li>{{ src }}</li>
                      }
                    </ul>
                  }
                </div>
              </div>
            } @empty {
              <div class="state-line">Posez une question : « opportunites haute confiance », « campagnes en cours », « fiche client Septona »…</div>
            }
            @if (chatBusy()) {
              <div class="chat-msg assistant"><div class="chat-bubble muted"><ck-glyph name="pulse" [size]="12" color="currentColor" /> Recherche…</div></div>
            }
          </div>
          @if (chatError()) {
            <div class="action-status error" role="status" aria-live="polite">{{ chatError() }}</div>
          }
          <form class="chat-input" (ngSubmit)="sendChatMessage()">
            <input
              type="text"
              name="chatInput"
              [(ngModel)]="chatInput"
              [disabled]="chatBusy()"
              placeholder="Poser une question a l'assistant Client360…"
            />
            <button type="submit" class="primary" [disabled]="chatBusy() || !chatInput.trim()">
              <ck-glyph name="arrow-up" [size]="14" color="currentColor" /> Envoyer
            </button>
          </form>
        </section>
      }
      </section>
    </ck-page-frame>
  `,
  styles: [`
    :host { display: block; min-height: 100%; background: var(--ck-bg-base); color: var(--ck-fg-1); }
    .c360-workspace { display: flex; flex-direction: column; gap: 16px; }
    .c360-eyebrow { margin: 0 0 6px; color: var(--ck-signal-cool); letter-spacing: 0; }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h2 { font-size: 18px; font-weight: 650; }
    h3 { font-size: 13px; font-weight: 680; color: var(--ck-fg-2); }
    .icon-button, .primary, .secondary, .c360-tabs button, .impact-buttons button {
      display: inline-flex; align-items: center; justify-content: center; gap: 7px; border-radius: var(--ck-radius-md); border: 1px solid var(--ck-stroke-2);
      min-height: 34px; padding: 0 12px; background: var(--ck-bg-inset); color: var(--ck-fg-2); cursor: pointer; font-weight: 650;
    }
    .primary { background: color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color: var(--ck-on-signal); border-color: transparent; }
    .primary:disabled, .secondary:disabled {
      cursor: wait;
      opacity: .72;
      filter: saturate(.82);
    }
    .is-loading ck-glyph, .action-status ck-glyph {
      animation: c360-spin 1s linear infinite;
    }
    .secondary:hover, .icon-button:hover, .c360-tabs button:hover { border-color: var(--ck-stroke-3); color: var(--ck-fg-1); }
    .c360-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; margin-top: 18px; width: 100%; border-radius: var(--ck-radius-lg); }
    .c360-tabs button {
      min-height: 36px;
      padding: 0 18px;
      background: transparent;
      border-color: transparent;
      color: var(--ck-fg-4);
      font-family: var(--ck-font-mono);
      font-size: 10px;
      font-weight: 650;
      letter-spacing: 0;
      text-transform: uppercase;
    }
    .c360-tabs button.active {
      background: var(--ck-bg-inset);
      color: var(--ck-fg-1);
      border-color: var(--ck-stroke-3);
      box-shadow: inset 0 0 0 1px var(--ck-stroke-2);
    }
    .state-line { display: inline-flex; align-items: center; gap: 8px; color: var(--ck-fg-3); font-size: 12px; }
    .state-line.error { color: var(--ck-signal-neg); }
    .kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 10px; }
    .kpi { padding: 14px 16px; border-radius: var(--ck-radius-md); }
    .kpi span { display: block; color: var(--ck-fg-4); font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; }
    .kpi strong { display: block; margin-top: 9px; font-size: 22px; font-weight: 680; }
    .alerts-panel { display: flex; flex-direction: column; gap: 10px; padding: 12px 16px; border-radius: var(--ck-radius-md); border-left: 3px solid var(--ck-signal-warn); }
    .alerts-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
    .alerts-head h3 { display: inline-flex; align-items: center; gap: 6px; }
    .alerts-counts { display: flex; flex-wrap: wrap; gap: 6px; }
    .alerts-list { display: flex; flex-direction: column; gap: 6px; margin: 0; padding: 0; list-style: none; }
    .alerts-list.expanded { max-height: 46vh; overflow-y: auto; padding-right: 2px; }
    .alerts-counts .pill-filter { font: inherit; font-size: 11px; cursor: pointer; }
    .alerts-counts .pill-filter:hover { border-color: var(--ck-stroke-3); }
    .alerts-counts .pill-filter.active { border-color: var(--ck-stroke-hot); color: var(--ck-signal-cool); }
    .alerts-list li { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); cursor: pointer; }
    .alerts-list li:hover { border-color: var(--ck-stroke-3); }
    .alerts-list li.high { border-left: 3px solid var(--ck-signal-neg); }
    .alerts-list li.medium { border-left: 3px solid var(--ck-signal-warn); }
    .alerts-list li.low { border-left: 3px solid var(--ck-stroke-3); }
    .alert-sev { min-width: 64px; font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; color: var(--ck-fg-4); }
    .alert-sev.high { color: var(--ck-signal-neg); }
    .alert-sev.medium { color: var(--ck-signal-warn); }
    .alert-body { flex: 1; min-width: 0; }
    .alert-body strong { display: block; font-size: 12px; color: var(--ck-fg-1); }
    .alert-body small { display: block; margin-top: 3px; color: var(--ck-fg-4); line-height: 1.35; }
    .alert-target { color: var(--ck-fg-3); font-size: 11px; white-space: nowrap; }
    .toolbar { display: flex; align-items: end; flex-wrap: wrap; gap: 10px; padding: 12px 16px; border-radius: var(--ck-radius-md); }
    label { display: grid; min-width: 0; gap: 5px; color: var(--ck-fg-4); font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; }
    input, select, textarea {
      width: 100%; min-width: 0; box-sizing: border-box; min-height: 34px; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset);
      color: var(--ck-fg-1); padding: 0 10px; outline: 0; font: 500 13px/1.4 var(--ck-font-sans);
    }
    textarea { width: 100%; min-height: 360px; padding: 12px; resize: vertical; white-space: pre-wrap; }
    .small-textarea { min-height: 90px; }
    .table-wrap { overflow: auto; border-radius: var(--ck-radius-md); }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--ck-stroke-2); text-align: left; vertical-align: top; font-size: 12px; }
    th { color: var(--ck-fg-4); font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; }
    td strong { display: block; color: var(--ck-fg-1); font-size: 12px; }
    td small { display: block; margin-top: 4px; color: var(--ck-fg-4); line-height: 1.35; }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: var(--ck-tint-faint); }
    .pill, .status, .chips span { display: inline-flex; align-items: center; border-radius: var(--ck-radius-md); padding: 3px 8px; background: var(--ck-tint-faint); border: 1px solid var(--ck-stroke-2); color: var(--ck-fg-3); font-size: 11px; white-space: nowrap; }
    .pill.high { color: var(--ck-signal-pos); border-color: rgba(16,185,129,.35); }
    .pill.medium { color: var(--ck-signal-warn); border-color: rgba(245,158,11,.35); }
    .pill.low { color: var(--ck-fg-4); }
    .status.ok { color: var(--ck-signal-pos); border-color: rgba(16,185,129,.35); }
    .empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 180px; color: var(--ck-fg-3); text-align: center; }
    .empty small { color: var(--ck-fg-4); }
    .split { display: grid; grid-template-columns: minmax(240px, 320px) 1fr; gap: 12px; min-height: 420px; }
    .data-layout { display: grid; grid-template-columns: minmax(280px, 420px) minmax(0, 1fr); gap: 12px; min-height: 420px; }
    .mail-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, 380px); gap: 12px; min-height: 620px; align-items: stretch; }
    .list-panel, .detail-panel, .gap-panel, .impact-panel, .smtp-panel, .mail-prompt-panel { border-radius: var(--ck-radius-md); padding: 12px; }
    .list-panel { display: flex; flex-direction: column; gap: 6px; overflow: auto; }
    .list-panel button { text-align: left; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); color: var(--ck-fg-2); padding: 10px; cursor: pointer; }
    .list-panel button.active { border-color: var(--ck-stroke-hot); color: var(--ck-signal-cool); }
    .list-panel span { display: block; margin-top: 4px; color: var(--ck-fg-4); font-size: 11px; }
    .directory-search { margin-bottom: 4px; }
    .directory-facets { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 4px; }
    .directory-selection-bar { display: flex; gap: 6px; margin-bottom: 4px; }
    .directory-selection-bar button { flex: 1; text-align: center; justify-content: center; font-size: 11px; }
    .directory-selection-bar .secondary { flex: 0 0 auto; }
    .directory-row { display: flex; align-items: stretch; gap: 8px; }
    .directory-row > input[type='checkbox'] { flex: none; width: 14px; height: 14px; min-height: auto; padding: 0; margin-top: 14px; accent-color: var(--ck-signal-cool); cursor: pointer; }
    .directory-row > button { flex: 1; min-width: 0; }
    .campaign-targeting { display: grid; gap: 8px; border: 1px solid var(--ck-stroke-hot); border-radius: var(--ck-radius-md); background: var(--ck-tint-faint); padding: 10px; }
    .campaign-targeting .chips { margin-top: 0; }
    .campaign-targeting .hint { margin: 0; }
    .drafts-outcome { margin: 0 0 14px; padding: 10px 12px; border: 1px solid var(--ck-stroke-2); border-left: 3px solid var(--ck-signal-cool); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); font-size: 12px; }
    .drafts-outcome strong { color: var(--ck-fg-1); }
    .drafts-outcome small { display: block; margin-top: 4px; color: var(--ck-fg-4); }
    .drafts-outcome ul { margin: 6px 0 0; padding-left: 18px; color: var(--ck-fg-3); }
    .drafts-outcome li { margin-top: 2px; }
    .campaign-kpis { grid-template-columns: repeat(3, minmax(140px, 1fr)); }
    .followup-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .followup-list li { padding: 8px 10px; border: 1px solid var(--ck-stroke-2); border-left: 3px solid var(--ck-signal-warn); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); }
    .followup-list strong { display: block; font-size: 12px; color: var(--ck-fg-1); }
    .followup-list small { display: block; margin-top: 3px; color: var(--ck-fg-4); line-height: 1.35; }
    .empty.compact { min-height: 80px; }
    .chip-button {
      display: inline-flex; flex-direction: column; align-items: flex-start; gap: 2px;
      border-radius: var(--ck-radius-md); padding: 6px 10px; background: var(--ck-tint-faint);
      border: 1px solid var(--ck-stroke-2); color: var(--ck-fg-2); font-size: 11px; cursor: pointer; text-align: left;
    }
    .chip-button small { color: var(--ck-fg-4); }
    .chip-button.active { border-color: var(--ck-stroke-hot); color: var(--ck-signal-cool); }
    .c360-tree-part.linkish {
      width: 100%; border: 0; cursor: pointer; text-align: left;
    }
    .c360-tree-part.linkish:hover { border: 0; background: color-mix(in oklab, var(--ck-signal-cool) 12%, transparent); }
    .compact-table table { min-width: 560px; }
    .compact-table tbody tr { cursor: pointer; }
    .detail-head { display: flex; justify-content: space-between; gap: 12px; align-items: start; margin-bottom: 14px; }
    .detail-head.compact { margin-bottom: 10px; }
    .draft-meta { display: flex; align-items: center; gap: 8px; margin-top: 8px; color: var(--ck-fg-4); font-size: 11px; }
    .draft-meta .pill.ai_assisted { color: var(--ck-signal-cool); border-color: var(--ck-stroke-hot); }
    .c360-summary { border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); padding: 12px; margin-bottom: 14px; }
    .c360-summary-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
    .c360-summary .pill.ai_assisted { color: var(--ck-signal-cool); border-color: var(--ck-stroke-hot); }
    .c360-summary-text { margin: 0 0 8px; color: var(--ck-fg-2); line-height: 1.55; }
    .c360-tree { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; max-height: 440px; overflow-y: auto; }
    .directory-list { display: flex; flex-direction: column; gap: 6px; max-height: 64vh; overflow-y: auto; padding-right: 2px; }
    .detail-loader { display: flex; align-items: center; gap: 8px; justify-content: center; min-height: 180px; color: var(--ck-fg-4); font-size: 12px; }
    .show-more-row { margin-top: 8px; }
    .c360-tree-node, .c360-tree-line { border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); padding: 6px 10px; }
    .c360-tree-line { margin: 6px 0 0; background: transparent; }
    .c360-tree summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; cursor: pointer; color: var(--ck-fg-2); font-size: 12px; }
    .c360-tree summary span:last-child { color: var(--ck-fg-4); font-size: 11px; }
    .c360-tree-machine { margin: 6px 0 0 8px; }
    .c360-tree-machine-head { display: flex; justify-content: space-between; gap: 8px; margin: 4px 0; color: var(--ck-fg-3); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
    .c360-tree-part { display: flex; justify-content: space-between; gap: 8px; padding: 4px 8px; border-radius: var(--ck-radius-sm); background: var(--ck-tint-faint); margin: 3px 0; font-size: 12px; color: var(--ck-fg-2); }
    .c360-tree-part-meta { color: var(--ck-fg-4); font-size: 11px; white-space: nowrap; }
    .c360-timeline { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-direction: column; gap: 4px; }
    .c360-timeline li { display: grid; grid-template-columns: 130px 96px 1fr; gap: 8px; align-items: baseline; padding: 5px 8px; border-left: 2px solid var(--ck-stroke-2); background: var(--ck-bg-inset); border-radius: 0 var(--ck-radius-sm) var(--ck-radius-sm) 0; font-size: 12px; }
    .c360-timeline li.is-sent, .c360-timeline li.is-won { border-left-color: var(--ck-signal-pos); }
    .c360-timeline li.is-lost { border-left-color: var(--ck-signal-warn); }
    .c360-timeline li.is-mail { border-left-color: var(--ck-signal-cool); }
    .c360-timeline-when { color: var(--ck-fg-4); font-size: 11px; white-space: nowrap; }
    .c360-timeline-kind { color: var(--ck-fg-3); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
    .c360-timeline-label { color: var(--ck-fg-2); }
    .mail-editor-panel { display: flex; flex-direction: column; min-width: 0; }
    .draft-fields { display: grid; grid-template-columns: minmax(220px, 320px) minmax(0, 1fr); gap: 10px; margin-bottom: 10px; }
    .mail-textarea { flex: 1; min-height: 500px; line-height: 1.5; }
    .mail-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .side-stack { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
    .detail-actions { display: grid; justify-items: end; gap: 8px; }
    .button-row { display: inline-flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 7px; }
    .action-status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--ck-signal-cool);
      font: 700 10px/1 var(--ck-font-mono);
      text-transform: uppercase;
    }
    .facts { display: grid; grid-template-columns: repeat(3, minmax(130px, 1fr)); gap: 10px; margin: 0 0 16px; }
    .facts div { padding: 10px; background: var(--ck-bg-inset); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); }
    .engine-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 12px 0 0; }
    .engine-facts div { min-width: 0; overflow: hidden; padding: 8px; background: var(--ck-bg-inset); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); }
    dt { color: var(--ck-fg-4); font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; }
    dd { margin: 7px 0 0; color: var(--ck-fg-2); font-size: 13px; overflow-wrap: anywhere; word-break: break-word; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .chips .ok { color: var(--ck-signal-pos); }
    .scope-panel { display: grid; gap: 10px; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--ck-stroke-2); }
    .scope-panel p { margin: 0; color: var(--ck-fg-3); font-size: 12px; line-height: 1.45; }
    .data-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    .mono-slug { font: 650 11px/1.35 var(--ck-font-mono); word-break: break-all; }
    .hint { margin: 10px 0 0; color: var(--ck-fg-4); font-size: 11px; line-height: 1.4; }
    tbody tr.is-unified { background: color-mix(in oklab, var(--ck-signal-cool) 8%, transparent); }
    .reason-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .reason-list span { border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); color: var(--ck-fg-4); padding: 4px 8px; font-size: 11px; }
    .reason-list span.met { color: var(--ck-signal-pos); border-color: rgba(16,185,129,.35); }
    .impact-panel, .smtp-panel, .mail-prompt-panel { display: flex; flex-direction: column; gap: 12px; }
    .prompt-textarea { min-height: 220px; font: 500 12px/1.45 var(--ck-font-mono); }
    .mail-prompt-invariants { margin: 0; }
    .mail-prompt-actions { justify-content: flex-start; flex-wrap: wrap; }
    .impact-buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .impact-buttons button { min-height: 40px; font-size: 12px; }
    .panel-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
    .settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; min-width: 0; }
    .toggle-row { display: flex; flex-wrap: wrap; gap: 8px; }
    .checkline {
      display: inline-flex;
      grid-auto-flow: column;
      align-items: center;
      gap: 6px;
      color: var(--ck-fg-3);
      font: 650 11px/1 var(--ck-font-sans);
      text-transform: none;
    }
    .checkline input { min-height: auto; width: 14px; height: 14px; padding: 0; }
    @media (max-width: 900px) {
      .kpi-grid, .split, .mail-layout, .data-layout, .facts, .draft-fields, .settings-grid { grid-template-columns: 1fr; }
      .detail-actions { justify-items: start; }
    }
    @keyframes c360-spin {
      to { transform: rotate(360deg); }
    }
    .chat-assistant { display: flex; flex-direction: column; gap: 12px; padding: 16px; min-height: 420px; }
    .chat-thread { display: flex; flex-direction: column; gap: 10px; flex: 1; overflow-y: auto; max-height: 60vh; padding-right: 4px; }
    .chat-msg { display: flex; }
    .chat-msg.user { justify-content: flex-end; }
    .chat-msg.assistant { justify-content: flex-start; }
    .chat-bubble {
      max-width: 82%; border-radius: var(--ck-radius-lg); padding: 10px 12px; font-size: 13px; line-height: 1.5;
      border: 1px solid var(--ck-stroke-2); background: var(--ck-bg-inset); color: var(--ck-fg-1);
    }
    .chat-msg.user .chat-bubble { background: color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color: var(--ck-on-signal); border-color: transparent; }
    .chat-bubble.muted { color: var(--ck-fg-3); font-style: italic; }
    .chat-text { margin: 0; white-space: pre-wrap; }
    .chat-sources { margin: 8px 0 0; padding-left: 16px; font-size: 11px; color: var(--ck-fg-3); }
    .chat-input { display: flex; gap: 8px; align-items: center; }
    .chat-input input { flex: 1; min-height: 38px; border-radius: var(--ck-radius-md); border: 1px solid var(--ck-stroke-2); background: var(--ck-bg-inset); color: var(--ck-fg-1); padding: 0 12px; }
  `],
})
export class Client360PageComponent implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService);

  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);
  private workspaceActionGeneration = 0;
  private mappingValidationRequest: Subscription | null = null;
  private mappingReloadRequest: Subscription | null = null;
  private engineRunRequest: Subscription | null = null;
  private syncRequest: Subscription | null = null;
  private actionRefreshRequests = new Subscription();
  private readonly unregisterWorkspaceReset: () => void;
  private destroyed = false;
  readonly unifiedCollectionSlug = CLIENT360_UNIFIED_COLLECTION_SLUG;
  readonly view = signal<ViewKey>('opportunities');
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly summary = signal<Client360Summary | null>(null);
  readonly opportunitiesResponse = signal<Client360OpportunitiesResponse | null>(null);
  readonly selectedOpportunity = signal<Client360Opportunity | null>(null);
  readonly selectedCustomer = signal<Client360CustomerResponse | null>(null);
  readonly customersResponse = signal<Client360CustomersResponse | null>(null);
  readonly selectedDirectoryCustomerKey = signal<string | null>(null);
  readonly focusedProjectCode = signal<string | null>(null);
  readonly currentDraft = signal<Client360MailDraft | null>(null);
  readonly draftBody = signal('');
  readonly draftSubject = signal('');
  readonly alertsResponse = signal<Client360AlertsResponse | null>(null);
  readonly mappingsResponse = signal<Client360MappingsResponse | null>(null);
  readonly engineResult = signal<Client360EngineResult | null>(null);
  readonly syncResult = signal<Client360SyncFromCollectionResult | null>(null);
  readonly syncBusy = signal(false);
  readonly syncStatus = signal<string | null>(null);
  readonly mailAiResolved = signal(false);
  readonly generatingDraftOpportunityId = signal<string | null>(null);
  readonly sendingMailDraftId = signal<string | null>(null);
  readonly savingMailSettings = signal(false);
  readonly savingMailPrompt = signal(false);
  readonly resettingMailPrompt = signal(false);
  readonly mailSettings = signal<Client360MailSettings | null>(null);
  readonly mailStatus = signal<string | null>(null);
  readonly campaignsResponse = signal<Client360CampaignsResponse | null>(null);
  readonly selectedCampaign = signal<Client360Campaign | null>(null);
  readonly campaignStats = signal<Client360CampaignStats | null>(null);
  readonly campaignStatus = signal<string | null>(null);
  readonly campaignBusy = signal(false);
  readonly campaignDraftsOutcome = signal<CampaignDraftsOutcome | null>(null);
  readonly directorySelection = signal<string[]>([]);
  readonly customerDetailLoading = signal(false);
  readonly customerSummaryLoading = signal(false);
  readonly fichePurchasesLimit = signal(FICHE_PURCHASES_PAGE);
  readonly ficheOpportunitiesLimit = signal(FICHE_OPPORTUNITIES_PAGE);
  readonly ficheTimelineLimit = signal(FICHE_TIMELINE_PAGE);
  readonly fichePurchases = computed(() =>
    (this.selectedCustomer()?.purchases ?? []).slice(0, this.fichePurchasesLimit()),
  );
  readonly ficheOpportunities = computed(() =>
    (this.selectedCustomer()?.opportunities ?? []).slice(0, this.ficheOpportunitiesLimit()),
  );
  readonly ficheTimeline = computed(() =>
    (this.selectedCustomer()?.timeline ?? []).slice(0, this.ficheTimelineLimit()),
  );
  private customerDetailRequest: Subscription | null = null;
  private customerSummaryRequest: Subscription | null = null;
  readonly campaignTargetCustomerKeys = signal<string[]>([]);
  readonly chatMessages = signal<Array<{ role: 'user' | 'assistant'; content: string; sources?: string[] }>>([]);
  readonly chatBusy = signal(false);
  readonly chatError = signal<string | null>(null);
  chatInput = '';
  customerDirectoryQuery = '';
  customerDirectoryCountry = '';
  customerDirectoryTechnology = '';
  private customerDirectorySearchTimer: ReturnType<typeof setTimeout> | null = null;

  recipientEmail = '';
  smtpEnabled = true;
  smtpHost = '';
  smtpPort = 465;
  smtpUsername = '';
  smtpPassword = '';
  smtpFromEmail = '';
  smtpFromName = 'ANDRITZ Service';
  smtpSsl = true;
  smtpStarttls = false;
  mailSystemPrompt = '';

  impactAttribution = 'unknown';
  impactReason = 'unknown';
  impactSummary = '';
  /** Option values of the impact-reason picker; the label is `client360.impact.reason.<value>`. */
  readonly impactReasons = [
    'unknown',
    'price',
    'competitor',
    'no_need',
    'wrong_contact',
    'timing',
    'hub',
    'technical_mismatch',
    'bad_data',
    'other',
  ] as const;

  campaignName = '';
  campaignType = 'first_replacement';
  /** Option values of the campaign-type picker; the label is `client360.campaign_type.<value>`. */
  readonly campaignTypes = [
    'first_replacement',
    'maintenance_education',
    'renewal',
    'cross_selling',
    'upselling',
    'free',
  ] as const;
  campaignDueWithinWeeks: number | null = null;
  readonly campaignCriteria = {
    country: '',
    technology: '',
    part_family: '',
    confidence: '',
  };

  readonly filters = {
    customer: '',
    country: '',
    hub: '',
    technology: '',
    part_family: '',
    confidence: '',
    status: '',
  };

  readonly tabs: Array<{ id: ViewKey; label: string }> = [
    { id: 'opportunities', label: this.i18n.t('client360.tab.opportunities') },
    { id: 'customer', label: this.i18n.t('client360.tab.customer') },
    { id: 'data', label: this.i18n.t('client360.tab.data') },
    { id: 'mapping', label: this.i18n.t('client360.tab.mapping') },
    { id: 'mail', label: this.i18n.t('client360.tab.mail') },
    { id: 'campaigns', label: this.i18n.t('client360.tab.campaigns') },
    { id: 'chat', label: this.i18n.t('client360.tab.chat') },
  ];

  readonly opportunities = computed(() => this.opportunitiesResponse()?.items ?? []);
  readonly directoryCustomers = computed(() => this.customersResponse()?.items ?? []);
  readonly customerDirectoryFacets = computed(
    () => this.customersResponse()?.facets ?? { countries: [], technologies: [] },
  );
  readonly machinesForFocusedProject = computed(() => {
    const machines = this.selectedCustomer()?.machines ?? [];
    const projectCode = this.focusedProjectCode();
    if (!projectCode) return machines;
    const filtered = machines.filter((machine) => machine.project_code === projectCode);
    return filtered.length ? filtered : machines;
  });
  readonly sortKey = signal<'score' | 'value'>('score');
  readonly sortedOpportunities = computed(() => {
    const items = [...this.opportunities()];
    if (this.sortKey() === 'value') {
      return items.sort((a, b) => (b.potential_gap_value ?? 0) - (a.potential_gap_value ?? 0));
    }
    return items;
  });
  readonly mappings = computed(() => this.mappingsResponse()?.items ?? []);
  readonly alerts = computed(() => this.alertsResponse()?.alerts ?? []);
  readonly followUpAlerts = computed(() =>
    this.alerts().filter((alert) => alert.type === 'draft_no_response'),
  );
  readonly alertCountEntries = computed(() =>
    Object.entries(this.alertsResponse()?.counts?.by_type ?? {}).map(([key, value]) => ({ key, value })),
  );
  readonly alertsExpanded = signal(false);
  readonly alertTypeFilter = signal<string | null>(null);
  readonly opportunitiesTableLimit = signal(OPPORTUNITIES_TABLE_PAGE);
  readonly filteredAlerts = computed(() => {
    const type = this.alertTypeFilter();
    const rank: Record<string, number> = { high: 0, medium: 1, low: 2 };
    return this.alerts()
      .filter((alert) => !type || alert.type === type)
      .sort((a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3));
  });
  readonly visibleAlerts = computed(() =>
    this.alertsExpanded() ? this.filteredAlerts() : this.filteredAlerts().slice(0, ALERTS_PREVIEW_COUNT),
  );
  readonly visibleOpportunities = computed(() =>
    this.sortedOpportunities().slice(0, this.opportunitiesTableLimit()),
  );
  readonly campaigns = computed(() => this.campaignsResponse()?.items ?? []);
  readonly campaignSegments = computed(() => this.summary()?.positioning?.mvp_contract?.campaign_segments ?? []);
  readonly isDemoSafe = computed(() => this.workspace.isDemoSafeMode());
  readonly unifiedCollectionStats = computed(() => {
    const allSources = this.summary()?.data_sources ?? [];
    const linked = allSources.filter(
      (source) => source.collection_slug === CLIENT360_UNIFIED_COLLECTION_SLUG,
    );
    const scoped = linked.length > 0 ? linked : allSources;
    const byType = new Map<string, { count: number; rows: number | null }>();
    for (const source of scoped) {
      const key = source.source_type || 'other';
      const current = byType.get(key) ?? { count: 0, rows: null };
      current.count += 1;
      if (source.row_count != null && !Number.isNaN(Number(source.row_count))) {
        current.rows = (current.rows ?? 0) + Number(source.row_count);
      }
      byType.set(key, current);
    }
    if (linked.length === 0 && allSources.length > 0) {
      for (const [key, count] of Object.entries(this.summary()?.source_counts ?? {})) {
        if (!byType.has(key)) byType.set(key, { count, rows: null });
      }
    }
    const originCounts = new Map<string, number>();
    for (const source of scoped) {
      const origin = source.origin || 'unknown';
      originCounts.set(origin, (originCounts.get(origin) ?? 0) + 1);
    }
    const originSummary = originCounts.size
      ? [...originCounts.entries()].map(([origin, count]) => `${origin}: ${count}`).join(' · ')
      : '-';
    return {
      linkedSources: linked.length,
      totalSources: allSources.length,
      readySources: linked.filter((source) => source.status === 'ready').length,
      hasLinkedSources: linked.length > 0,
      originSummary,
      typeEntries: [...byType.entries()]
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([key, value]) => ({ key, count: value.count, rows: value.rows })),
    };
  });

  constructor() {
    this.unregisterWorkspaceReset = this.workspace.registerContextReset(() => {
      this.resetWorkspaceActions();
    });
  }

  ngOnInit(): void {
    this.refresh();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.customerDetailRequest?.unsubscribe();
    this.customerSummaryRequest?.unsubscribe();
    this.unregisterWorkspaceReset();
    this.resetWorkspaceActions();
  }

  refresh(actionContext?: WorkspaceActionContext): void {
    if (!this.workspaceActionContextIsCurrent(actionContext)) return;
    this.loading.set(true);
    this.error.set(null);
    this.mailStatus.set(null);
    this.mailAiResolved.set(false);
    this.loadSummary(false, actionContext);
    this.loadMailSettings(false, actionContext);
    this.loadMappings(false, actionContext);
    this.loadOpportunities(false, actionContext);
    this.loadCustomers(actionContext);
    this.loadAlerts(actionContext);
  }

  loadAlerts(actionContext?: WorkspaceActionContext): void {
    const request = this.http.get<Client360AlertsResponse>(
      '/api/v1/client360/alerts',
      actionContext ? this.workspaceHttpOptions(actionContext.scope) : {},
    ).subscribe({
      next: (payload) => {
        if (this.workspaceActionContextIsCurrent(actionContext)) {
          this.alertsResponse.set(payload);
        }
      },
      error: () => {
        if (this.workspaceActionContextIsCurrent(actionContext)) {
          this.alertsResponse.set(null);
        }
      },
    });
    this.trackActionRefreshRequest(request, actionContext);
  }

  openAlert(alert: Client360Alert): void {
    if (!alert.opportunity_id) return;
    const opp = this.opportunities().find((item) => item.id === alert.opportunity_id);
    if (opp) this.selectOpportunity(opp);
  }

  toggleAlertTypeFilter(type: string): void {
    this.alertTypeFilter.update((current) => (current === type ? null : type));
  }

  toggleAlertsExpanded(): void {
    this.alertsExpanded.update((expanded) => !expanded);
  }

  showMoreOpportunitiesTable(): void {
    this.opportunitiesTableLimit.update((limit) => limit + 50);
  }

  openTab(tab: ViewKey): void {
    this.view.set(tab);
    if (tab === 'customer' && !this.customersResponse()) {
      this.loadCustomers();
    }
    if (tab === 'data' && !this.mailAiResolved()) {
      this.loadSummary(true);
    }
    if (tab === 'mapping' && !this.mappingsResponse()) {
      this.loadMappings(false);
    }
    if (tab === 'mail' && !this.mailSettings()) {
      this.loadMailSettings(false);
    }
    if (tab === 'campaigns' && !this.campaignsResponse()) {
      this.loadCampaigns(false);
    }
  }

  onCustomerDirectoryQueryChange(): void {
    if (this.customerDirectorySearchTimer) {
      clearTimeout(this.customerDirectorySearchTimer);
    }
    this.customerDirectorySearchTimer = setTimeout(() => this.loadCustomers(), 250);
  }

  loadCustomers(actionContext?: WorkspaceActionContext): void {
    let params = new HttpParams().set('limit', '200');
    if (this.customerDirectoryQuery.trim()) {
      params = params.set('q', this.customerDirectoryQuery.trim());
    }
    if (this.customerDirectoryCountry) {
      params = params.set('country', this.customerDirectoryCountry);
    }
    if (this.customerDirectoryTechnology) {
      params = params.set('technology', this.customerDirectoryTechnology);
    }
    const request = this.http.get<Client360CustomersResponse>('/api/v1/client360/customers', {
      params,
      ...(actionContext ? this.workspaceHttpOptions(actionContext.scope) : {}),
    }).subscribe({
      next: (payload) => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        this.customersResponse.set(payload);
        const selectedKey = this.selectedDirectoryCustomerKey();
        if (selectedKey && !payload.items.some((item) => item.customer_key === selectedKey)) {
          return;
        }
        if (!selectedKey && payload.items.length && this.view() === 'customer' && !this.selectedCustomer()) {
          this.selectDirectoryCustomer(payload.items[0], actionContext);
        }
      },
      error: () => {
        if (this.workspaceActionContextIsCurrent(actionContext)) {
          this.customersResponse.set(null);
          this.error.set('Impossible de charger l\'annuaire clients Client360');
        }
      },
    });
    this.trackActionRefreshRequest(request, actionContext);
  }

  isDirectoryCustomerSelected(customerKey: string): boolean {
    return this.directorySelection().includes(customerKey);
  }

  toggleDirectoryCustomer(customerKey: string): void {
    this.directorySelection.update((keys) =>
      keys.includes(customerKey) ? keys.filter((key) => key !== customerKey) : [...keys, customerKey],
    );
  }

  clearDirectorySelection(): void {
    this.directorySelection.set([]);
  }

  startCampaignFromSelection(): void {
    const keys = this.directorySelection();
    if (!keys.length) return;
    this.campaignTargetCustomerKeys.set([...keys]);
    this.campaignDueWithinWeeks = null;
    if (!this.campaignName.trim()) {
      this.campaignName = `Campagne annuaire (${keys.length} client${keys.length > 1 ? 's' : ''})`;
    }
    this.campaignStatus.set('Selection annuaire prete — verifiez le nom puis creez la campagne');
    this.openTab('campaigns');
  }

  startCampaignFromNextDue(fiche: Client360CustomerResponse): void {
    const customerKey = fiche.customer.id;
    if (!customerKey) return;
    this.campaignTargetCustomerKeys.set([customerKey]);
    this.campaignDueWithinWeeks = 26;
    if (!this.campaignName.trim()) {
      this.campaignName = `Echeances ${fiche.customer.name}`;
    }
    this.campaignType = 'renewal';
    this.campaignStatus.set('Cible echeances prete — verifiez le nom puis creez la campagne');
    this.openTab('campaigns');
  }

  clearCampaignTargeting(): void {
    this.campaignTargetCustomerKeys.set([]);
    this.campaignDueWithinWeeks = null;
  }

  selectDirectoryCustomer(
    customer: Client360DirectoryCustomer,
    actionContext?: WorkspaceActionContext,
  ): void {
    this.selectedDirectoryCustomerKey.set(customer.customer_key);
    this.focusedProjectCode.set(null);
    this.view.set('customer');
    this.fetchCustomerFiche(customer.customer_key, {}, actionContext);
  }

  private fetchCustomerFiche(
    customerKey: string,
    options: { keepSelectedOpportunity?: boolean } = {},
    actionContext: WorkspaceActionContext = {
      scope: this.workspace.captureRequestScope(),
      generation: this.workspaceActionGeneration,
    },
  ): void {
    if (!this.workspaceActionContextIsCurrent(actionContext)) return;
    this.customerDetailRequest?.unsubscribe();
    this.customerSummaryRequest?.unsubscribe();
    this.customerDetailLoading.set(true);
    this.customerSummaryLoading.set(false);
    this.fichePurchasesLimit.set(FICHE_PURCHASES_PAGE);
    this.ficheOpportunitiesLimit.set(FICHE_OPPORTUNITIES_PAGE);
    this.ficheTimelineLimit.set(FICHE_TIMELINE_PAGE);
    // Two-phase load: the fiche renders immediately without the AI summary,
    // which is fetched asynchronously (it is the slow, LLM-backed part).
    this.customerDetailRequest = this.http
      .get<Client360CustomerResponse>(
        `/api/v1/client360/customers/${encodeURIComponent(customerKey)}`,
        {
          params: new HttpParams().set('include_ai_summary', 'false'),
          ...this.workspaceHttpOptions(actionContext.scope),
        },
      )
      .subscribe({
        next: (payload) => {
          if (!this.workspaceActionContextIsCurrent(actionContext)) return;
          this.selectedCustomer.set(payload);
          if (!options.keepSelectedOpportunity) {
            this.selectedOpportunity.set(payload.opportunities[0] ?? null);
          }
          this.customerDetailLoading.set(false);
          this.loadCustomerSummary(customerKey, actionContext);
        },
        error: () => {
          if (!this.workspaceActionContextIsCurrent(actionContext)) return;
          this.selectedCustomer.set(null);
          if (!options.keepSelectedOpportunity) {
            this.selectedOpportunity.set(null);
          }
          this.customerDetailLoading.set(false);
          this.error.set('Impossible de charger la fiche client');
        },
      });
  }

  private loadCustomerSummary(
    customerKey: string,
    actionContext: WorkspaceActionContext,
  ): void {
    if (!this.workspaceActionContextIsCurrent(actionContext)) return;
    this.customerSummaryLoading.set(true);
    this.customerSummaryRequest = this.http
      .get<{ ai_summary: Client360AiSummary | null }>(
        `/api/v1/client360/customers/${encodeURIComponent(customerKey)}/summary`,
        this.workspaceHttpOptions(actionContext.scope),
      )
      .subscribe({
        next: (payload) => {
          if (!this.workspaceActionContextIsCurrent(actionContext)) return;
          this.customerSummaryLoading.set(false);
          if (this.selectedDirectoryCustomerKey() !== customerKey) return;
          const current = this.selectedCustomer();
          if (current) {
            this.selectedCustomer.set({ ...current, ai_summary: payload.ai_summary ?? null });
          }
        },
        error: () => {
          if (this.workspaceActionContextIsCurrent(actionContext)) {
            this.customerSummaryLoading.set(false);
          }
        },
      });
  }

  showMoreFichePurchases(): void {
    this.fichePurchasesLimit.update((limit) => limit + 50);
  }

  showMoreFicheOpportunities(): void {
    this.ficheOpportunitiesLimit.update((limit) => limit + 100);
  }

  showMoreFicheTimeline(): void {
    this.ficheTimelineLimit.update((limit) => limit + 50);
  }

  focusProject(project: Client360CustomerProject): void {
    this.focusedProjectCode.set(project.project_code || null);
  }

  selectOpportunityFromFiche(opportunityId: string | null | undefined): void {
    if (!opportunityId) return;
    const opp =
      this.selectedCustomer()?.opportunities.find((item) => item.id === opportunityId) ||
      this.opportunities().find((item) => item.id === opportunityId) ||
      null;
    if (!opp) return;
    this.selectedOpportunity.set(opp);
  }

  selectPurchasePart(partReference: string | null | undefined): void {
    if (!partReference) return;
    const opp =
      this.selectedCustomer()?.opportunities.find((item) => item.part_reference === partReference) ||
      null;
    if (opp) this.selectedOpportunity.set(opp);
  }

  sendChatMessage(): void {
    const query = this.chatInput.trim();
    if (!query || this.chatBusy()) return;
    this.chatError.set(null);
    this.chatMessages.update((msgs) => [...msgs, { role: 'user', content: query }]);
    this.chatInput = '';
    this.chatBusy.set(true);
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.post<Client360ChatResponse>(
      '/api/v1/client360/chat',
      { query },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        const sources = (payload.sources ?? [])
          .map((src) => src?.source_label || src?.title)
          .filter((label): label is string => !!label);
        this.chatMessages.update((msgs) => [
          ...msgs,
          { role: 'assistant', content: payload.content || this.i18n.t('client360.chat.no_answer'), sources },
        ]);
        this.chatBusy.set(false);
      },
      error: (err) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        const detail = err?.error?.detail;
        this.chatError.set(typeof detail === 'string' ? detail : 'Assistant Client360 indisponible.');
        this.chatBusy.set(false);
      },
    });
  }

  loadSummary(includeMailAi = false, actionContext?: WorkspaceActionContext): void {
    const params = new HttpParams()
      .set('include_mail_ai', includeMailAi ? 'true' : 'false')
      .set('include_workspace_candidates', 'false');
    const request = this.http.get<Client360Summary>('/api/v1/client360/summary', {
      params,
      ...(actionContext ? this.workspaceHttpOptions(actionContext.scope) : {}),
    }).subscribe({
      next: (payload) => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        const current = this.summary();
        if (!includeMailAi && this.mailAiResolved() && current?.positioning?.mail_ai) {
          payload = {
            ...payload,
            positioning: {
              ...payload.positioning,
              mail_ai: current.positioning.mail_ai,
            },
          };
        }
        if (includeMailAi) this.mailAiResolved.set(true);
        this.summary.set(payload);
      },
      error: () => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        if (includeMailAi) {
          this.error.set('Routage IA Client360 PDR indisponible');
        } else if (!this.opportunitiesResponse()) {
          this.error.set('Client360 PDR indisponible');
        }
      },
    });
    this.trackActionRefreshRequest(request, actionContext);
  }

  loadMappings(showLoading = true, actionContext?: WorkspaceActionContext): void {
    if (!this.workspaceActionContextIsCurrent(actionContext)) return;
    if (showLoading) this.loading.set(true);
    const request = this.http.get<Client360MappingsResponse>(
      '/api/v1/client360/mappings',
      actionContext ? this.workspaceHttpOptions(actionContext.scope) : {},
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        this.mappingsResponse.set(payload);
        if (showLoading) this.loading.set(false);
      },
      error: () => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        if (showLoading) this.loading.set(false);
        this.error.set(this.i18n.t('client360.error.mappings'));
      },
    });
    this.trackActionRefreshRequest(request, actionContext);
  }

  loadMailSettings(showStatus = false, actionContext?: WorkspaceActionContext): void {
    const request = this.http.get<MailSettingsResponse>(
      '/api/v1/client360/mail-settings',
      actionContext ? this.workspaceHttpOptions(actionContext.scope) : {},
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        this.mailSettings.set(payload.mail_settings);
        this.applyMailSettings(payload.mail_settings);
        if (showStatus) this.mailStatus.set('Parametres SMTP charges');
      },
      error: () => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        if (showStatus) this.mailStatus.set('Parametres SMTP indisponibles');
      },
    });
    this.trackActionRefreshRequest(request, actionContext);
  }

  applyMailSettings(settings: Client360MailSettings): void {
    this.smtpEnabled = settings.enabled;
    this.smtpHost = settings.host || '';
    this.smtpPort = settings.port || 465;
    this.smtpUsername = settings.username || '';
    this.smtpFromEmail = settings.from_email || settings.username || '';
    this.smtpFromName = settings.from_name || 'ANDRITZ Service';
    this.smtpSsl = settings.ssl !== false;
    this.smtpStarttls = Boolean(settings.starttls);
    this.smtpPassword = '';
    this.mailSystemPrompt = settings.system_prompt || '';
  }

  saveMailSettings(): void {
    this.savingMailSettings.set(true);
    this.mailStatus.set(null);
    const payload: Record<string, unknown> = {
      enabled: this.smtpEnabled,
      host: this.smtpHost,
      port: Number(this.smtpPort) || 465,
      username: this.smtpUsername,
      from_email: this.smtpFromEmail,
      from_name: this.smtpFromName,
      ssl: this.smtpSsl,
      starttls: this.smtpStarttls,
    };
    if (this.smtpPassword.trim()) payload['password'] = this.smtpPassword;
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.patch<MailSettingsResponse>(
      '/api/v1/client360/mail-settings',
      payload,
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (response) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.mailSettings.set(response.mail_settings);
        this.applyMailSettings(response.mail_settings);
        this.savingMailSettings.set(false);
        this.mailStatus.set(response.mail_settings.configured ? 'SMTP workspace pret' : 'SMTP workspace incomplet');
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.savingMailSettings.set(false);
        this.mailStatus.set(this.i18n.t('client360.error.smtp_save'));
      },
    });
  }

  saveMailPrompt(): void {
    const prompt = this.mailSystemPrompt.trim();
    if (!prompt) {
      this.mailStatus.set('Le prompt ne peut pas etre vide');
      return;
    }
    this.savingMailPrompt.set(true);
    this.mailStatus.set(null);
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http
      .patch<MailSettingsResponse>(
        '/api/v1/client360/mail-settings',
        { system_prompt: prompt },
        this.workspaceHttpOptions(scope),
      )
      .subscribe({
        next: (response) => {
          if (!this.workspaceActionIsCurrent(scope, generation)) return;
          this.mailSettings.set(response.mail_settings);
          this.applyMailSettings(response.mail_settings);
          this.savingMailPrompt.set(false);
          this.mailStatus.set(
            response.mail_settings.system_prompt_source === 'workspace'
              ? 'Prompt personnalise enregistre'
              : 'Prompt mis a jour',
          );
        },
        error: () => {
          if (!this.workspaceActionIsCurrent(scope, generation)) return;
          this.savingMailPrompt.set(false);
          this.mailStatus.set(this.i18n.t('client360.error.prompt_save'));
        },
      });
  }

  resetMailPrompt(): void {
    this.resettingMailPrompt.set(true);
    this.mailStatus.set(null);
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http
      .patch<MailSettingsResponse>(
        '/api/v1/client360/mail-settings',
        { reset_system_prompt: true },
        this.workspaceHttpOptions(scope),
      )
      .subscribe({
        next: (response) => {
          if (!this.workspaceActionIsCurrent(scope, generation)) return;
          this.mailSettings.set(response.mail_settings);
          this.applyMailSettings(response.mail_settings);
          this.resettingMailPrompt.set(false);
          this.mailStatus.set('Prompt reinitialise au defaut');
        },
        error: () => {
          if (!this.workspaceActionIsCurrent(scope, generation)) return;
          this.resettingMailPrompt.set(false);
          this.mailStatus.set('Impossible de reinitialiser le prompt');
        },
      });
  }

  syncFromCollection(dryRun = false): void {
    const scope = this.workspace.captureRequestScope();
    const generation = ++this.workspaceActionGeneration;
    this.cancelActionRefreshRequests();
    this.mappingValidationRequest?.unsubscribe();
    this.mappingValidationRequest = null;
    this.mappingReloadRequest?.unsubscribe();
    this.mappingReloadRequest = null;
    this.engineRunRequest?.unsubscribe();
    this.engineRunRequest = null;
    this.syncRequest?.unsubscribe();
    this.syncRequest = null;
    this.syncBusy.set(true);
    this.syncStatus.set(
      this.i18n.t(dryRun ? 'client360.toast.sync_preview' : 'client360.toast.syncing'),
    );
    this.error.set(null);
    const request = this.http.post<Client360SyncFromCollectionResult>(
      '/api/v1/client360/sources/sync-from-collection',
      {
        collection_slug: CLIENT360_UNIFIED_COLLECTION_SLUG,
        dry_run: dryRun,
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.syncResult.set(payload);
        this.syncBusy.set(false);
        const upserted = payload.sources_upserted ?? payload.created ?? payload.updated;
        const linked = payload.mvp_sources_linked;
        const parts: string[] = [];
        if (linked != null && linked > 0) {
          parts.push(this.i18n.t('client360.toast.sync_pilots_linked', { count: linked }));
        }
        if (upserted != null) {
          parts.push(this.i18n.t('client360.toast.sync_spl_sources', { count: upserted }));
        }
        if (!parts.length && (payload.files_seen ?? 0) === 0) {
          parts.push(this.i18n.t('client360.toast.sync_no_spl'));
        }
        const detail = parts.length ? ` · ${parts.join(' · ')}` : '';
        this.syncStatus.set(
          this.i18n.t(
            dryRun ? 'client360.toast.sync_dry_run_ok' : 'client360.toast.synced',
            { detail },
          ),
        );
        if (!dryRun) this.refresh({ scope, generation });
        else this.loadSummary(this.mailAiResolved(), { scope, generation });
      },
      error: (err) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.syncBusy.set(false);
        const detail = err?.error?.detail;
        this.syncStatus.set(null);
        this.error.set(
          typeof detail === 'string' ? detail : this.i18n.t('client360.error.sync'),
        );
      },
    });
    this.syncRequest = request.closed ? null : request;
  }

  runEngine(dryRun: boolean): void {
    const scope = this.workspace.captureRequestScope();
    const generation = ++this.workspaceActionGeneration;
    this.cancelActionRefreshRequests();
    this.mappingValidationRequest?.unsubscribe();
    this.mappingValidationRequest = null;
    this.mappingReloadRequest?.unsubscribe();
    this.mappingReloadRequest = null;
    this.engineRunRequest?.unsubscribe();
    this.engineRunRequest = null;
    this.syncRequest?.unsubscribe();
    this.syncRequest = null;
    this.runEngineForScope(dryRun, scope, generation);
  }

  private runEngineForScope(
    dryRun: boolean,
    scope: WorkspaceRequestScope,
    generation: number,
  ): void {
    if (!this.workspaceActionIsCurrent(scope, generation)) return;
    this.loading.set(true);
    this.error.set(null);
    const request = this.http.post<Client360EngineResult>(
      '/api/v1/client360/engines/opportunities/run',
      { dry_run: dryRun },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.engineResult.set(payload);
        this.loading.set(false);
        this.refresh({ scope, generation });
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.loading.set(false);
        this.error.set('Impossible de lancer le moteur Client360 PDR');
      },
    });
    this.engineRunRequest = request.closed ? null : request;
  }

  validateMapping(mapping: Client360MappingRule): void {
    const scope = this.workspace.captureRequestScope();
    const generation = ++this.workspaceActionGeneration;
    this.cancelActionRefreshRequests();
    this.mappingValidationRequest?.unsubscribe();
    this.mappingReloadRequest?.unsubscribe();
    this.engineRunRequest?.unsubscribe();
    this.mappingReloadRequest = null;
    this.engineRunRequest = null;
    const request = this.http.patch<{ mapping: Client360MappingRule }>(
      `/api/v1/client360/mappings/${encodeURIComponent(mapping.id)}`,
      {
        status: 'validated',
        confidence: Math.max(mapping.confidence || 0, 0.75),
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.reloadMappingsForScope(scope, generation);
        this.runEngineForScope(false, scope, generation);
      },
      error: () => {
        if (this.workspaceActionIsCurrent(scope, generation)) {
          this.error.set('Impossible de valider le mapping');
        }
      },
    });
    this.mappingValidationRequest = request.closed ? null : request;
  }

  private reloadMappingsForScope(
    scope: WorkspaceRequestScope,
    generation: number,
  ): void {
    if (!this.workspaceActionIsCurrent(scope, generation)) return;
    this.mappingReloadRequest?.unsubscribe();
    const request = this.http.get<Client360MappingsResponse>(
      '/api/v1/client360/mappings',
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (this.workspaceActionIsCurrent(scope, generation)) {
          this.mappingsResponse.set(payload);
        }
      },
      error: () => {
        if (this.workspaceActionIsCurrent(scope, generation)) {
          this.error.set(this.i18n.t('client360.error.mappings'));
        }
      },
    });
    this.mappingReloadRequest = request.closed ? null : request;
  }

  private workspaceActionIsCurrent(
    scope: WorkspaceRequestScope,
    generation: number,
  ): boolean {
    return (
      !this.destroyed
      && generation === this.workspaceActionGeneration
      && this.workspace.isRequestScopeCurrent(scope)
    );
  }

  private workspaceActionContextIsCurrent(
    actionContext?: WorkspaceActionContext,
  ): boolean {
    return !actionContext || this.workspaceActionIsCurrent(
      actionContext.scope,
      actionContext.generation,
    );
  }

  private trackActionRefreshRequest(
    request: Subscription,
    actionContext?: WorkspaceActionContext,
  ): void {
    if (actionContext) {
      this.actionRefreshRequests.add(request);
    }
  }

  private cancelActionRefreshRequests(): void {
    this.actionRefreshRequests.unsubscribe();
    this.actionRefreshRequests = new Subscription();
  }

  private workspaceHttpOptions(scope: WorkspaceRequestScope): {
    headers?: Record<string, string>;
  } {
    return scope.workspaceSlug
      ? { headers: { 'X-Workspace-Slug': scope.workspaceSlug } }
      : {};
  }

  private resetWorkspaceActions(): void {
    this.workspaceActionGeneration += 1;
    this.cancelActionRefreshRequests();
    this.customerDetailRequest?.unsubscribe();
    this.customerDetailRequest = null;
    this.customerSummaryRequest?.unsubscribe();
    this.customerSummaryRequest = null;
    this.mappingValidationRequest?.unsubscribe();
    this.mappingValidationRequest = null;
    this.mappingReloadRequest?.unsubscribe();
    this.mappingReloadRequest = null;
    this.engineRunRequest?.unsubscribe();
    this.engineRunRequest = null;
    this.syncRequest?.unsubscribe();
    this.syncRequest = null;
    this.loading.set(false);
    this.syncBusy.set(false);
    this.error.set(null);
    this.engineResult.set(null);
    this.syncResult.set(null);
    this.syncStatus.set(null);
    // Everything below is tenant data. Leaving it rendered while the next
    // workspace loads is the same cross-tenant leak as a late response.
    this.summary.set(null);
    this.opportunitiesResponse.set(null);
    this.selectedOpportunity.set(null);
    this.selectedCustomer.set(null);
    this.customersResponse.set(null);
    this.selectedDirectoryCustomerKey.set(null);
    this.focusedProjectCode.set(null);
    this.currentDraft.set(null);
    this.alertsResponse.set(null);
    this.mappingsResponse.set(null);
    this.mailSettings.set(null);
    this.campaignsResponse.set(null);
    this.selectedCampaign.set(null);
    this.campaignStats.set(null);
    this.directorySelection.set([]);
    this.campaignTargetCustomerKeys.set([]);
    this.customerDetailLoading.set(false);
    this.customerSummaryLoading.set(false);
    this.chatMessages.set([]);
    this.chatBusy.set(false);
    this.chatError.set(null);
  }

  updateOpportunityStatus(opp: Client360Opportunity, status: 'validated' | 'dismissed'): void {
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.patch<{ opportunity: Client360Opportunity }>(
      `/api/v1/client360/opportunities/${encodeURIComponent(opp.id)}`,
      {
        status,
        validation_reason: status === 'validated' ? 'sales_review' : undefined,
        rejection_reason: status === 'dismissed' ? 'sales_rejected' : undefined,
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.selectedOpportunity.set(payload.opportunity);
        this.loadOpportunities(false, { scope, generation });
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.error.set('Impossible de qualifier opportunite');
      },
    });
  }

  loadOpportunities(showLoading = true, actionContext?: WorkspaceActionContext): void {
    if (!this.workspaceActionContextIsCurrent(actionContext)) return;
    if (showLoading) this.loading.set(true);
    let params = new HttpParams().set('limit', '200');
    for (const [key, value] of Object.entries(this.filters)) {
      if (value) params = params.set(key, value);
    }
    const request = this.http.get<Client360OpportunitiesResponse>('/api/v1/client360/opportunities', {
      params,
      ...(actionContext ? this.workspaceHttpOptions(actionContext.scope) : {}),
    }).subscribe({
      next: (payload) => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        this.opportunitiesResponse.set(payload);
        this.opportunitiesTableLimit.set(OPPORTUNITIES_TABLE_PAGE);
        if (!this.selectedOpportunity() && payload.items.length) {
          this.selectedOpportunity.set(payload.items[0]);
        }
        this.loading.set(false);
      },
      error: () => {
        if (!this.workspaceActionContextIsCurrent(actionContext)) return;
        this.loading.set(false);
        this.error.set(this.i18n.t('client360.error.opportunities'));
      },
    });
    this.trackActionRefreshRequest(request, actionContext);
  }

  selectOpportunity(opp: Client360Opportunity): void {
    const actionContext: WorkspaceActionContext = {
      scope: this.workspace.captureRequestScope(),
      generation: this.workspaceActionGeneration,
    };
    this.selectedOpportunity.set(opp);
    this.selectedDirectoryCustomerKey.set(opp.customer_key);
    this.focusedProjectCode.set(null);
    this.view.set('customer');
    if (!this.customersResponse()) {
      this.loadCustomers(actionContext);
    }
    this.fetchCustomerFiche(
      opp.customer_key,
      { keepSelectedOpportunity: true },
      actionContext,
    );
  }

  generateDraft(opp: Client360Opportunity): void {
    if (this.generatingDraftOpportunityId()) return;
    this.loading.set(true);
    this.error.set(null);
    this.generatingDraftOpportunityId.set(opp.id);
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.post<MailDraftResponse>(
      '/api/v1/client360/mail-drafts',
      {
        opportunity_id: opp.id,
        language: 'fr',
        include_prices: false,
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.currentDraft.set(payload.mail_draft);
        this.draftSubject.set(payload.mail_draft.subject);
        this.draftBody.set(payload.mail_draft.generated_body);
        this.mailStatus.set(null);
        this.view.set('mail');
        this.loading.set(false);
        this.generatingDraftOpportunityId.set(null);
        this.loadOpportunities(false, { scope, generation });
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.loading.set(false);
        this.generatingDraftOpportunityId.set(null);
        this.error.set(this.i18n.t('client360.error.generate_draft'));
      },
    });
  }

  isGeneratingDraft(opp: Client360Opportunity | null | undefined): boolean {
    return Boolean(opp?.id && this.generatingDraftOpportunityId() === opp.id);
  }

  markSent(): void {
    const draft = this.currentDraft();
    if (!draft?.action_item_id) return;
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.patch<ActionResponse>(
      `/api/v1/client360/actions/${encodeURIComponent(draft.action_item_id)}`,
      {
        mail_draft_id: draft.id,
        mail_status: 'sent',
        status: 'in_progress',
        sent_body: this.draftBody(),
        sent_at: new Date().toISOString(),
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.currentDraft.set({ ...draft, subject: this.draftSubject(), status: 'sent', sent_body: this.draftBody(), sent_at: new Date().toISOString() });
        this.mailStatus.set('Envoi manuel trace');
        this.loadOpportunities(false, { scope, generation });
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.error.set('Impossible de mettre a jour le suivi mail');
      },
    });
  }

  canSendMail(): boolean {
    const draft = this.currentDraft();
    return Boolean(draft?.id && this.mailSettings()?.configured && this.recipientEmail.trim() && this.draftBody().trim() && !this.sendingMailDraftId());
  }

  isSendingMail(): boolean {
    const draft = this.currentDraft();
    return Boolean(draft?.id && this.sendingMailDraftId() === draft.id);
  }

  sendCurrentDraft(): void {
    const draft = this.currentDraft();
    if (!draft || !this.canSendMail()) return;
    this.sendingMailDraftId.set(draft.id);
    this.mailStatus.set('Envoi SMTP en cours');
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.post<MailSendResponse>(
      `/api/v1/client360/mail-drafts/${encodeURIComponent(draft.id)}/send`,
      {
        to_email: this.recipientEmail.trim(),
        subject: this.draftSubject(),
        body: this.draftBody(),
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.currentDraft.set(payload.mail_draft);
        this.draftSubject.set(payload.mail_draft.subject);
        this.draftBody.set(payload.mail_draft.sent_body || payload.mail_draft.generated_body);
        this.sendingMailDraftId.set(null);
        this.mailStatus.set('Mail envoye via SMTP');
        this.loadOpportunities(false, { scope, generation });
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.sendingMailDraftId.set(null);
        this.mailStatus.set('Echec envoi SMTP');
      },
    });
  }

  recordImpact(type: string): void {
    const draft = this.currentDraft();
    if (!draft?.action_item_id) return;
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.post<ImpactResponse>(
      `/api/v1/client360/actions/${encodeURIComponent(draft.action_item_id)}/impact`,
      {
        impact_type: type,
        attribution: this.impactAttribution,
        reason: this.impactReason,
        summary: this.impactSummary,
        opportunity_id: draft.opportunity_id,
        mail_draft_id: draft.id,
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.refresh({ scope, generation });
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.error.set('Impossible de qualifier impact');
      },
    });
  }

  loadCampaigns(showLoading = false): void {
    if (showLoading) this.loading.set(true);
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.get<Client360CampaignsResponse>(
      '/api/v1/client360/campaigns',
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.campaignsResponse.set(payload);
        if (showLoading) this.loading.set(false);
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        if (showLoading) this.loading.set(false);
        this.error.set(this.i18n.t('client360.error.campaigns'));
      },
    });
  }

  createCampaign(): void {
    const name = this.campaignName.trim();
    if (!name) {
      this.campaignStatus.set('Nom de campagne requis');
      return;
    }
    if (this.campaignBusy()) return;
    const selection_criteria: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(this.campaignCriteria)) {
      if (value) selection_criteria[key] = value;
    }
    const targetKeys = this.campaignTargetCustomerKeys();
    if (targetKeys.length) {
      selection_criteria['customer_keys'] = targetKeys;
      const dueWeeks = Number(this.campaignDueWithinWeeks);
      if (Number.isFinite(dueWeeks) && dueWeeks > 0) {
        selection_criteria['due_within_weeks'] = Math.round(dueWeeks);
      }
    }
    this.campaignBusy.set(true);
    this.campaignStatus.set('Creation de la campagne...');
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.post<Client360CampaignResponse>(
      '/api/v1/client360/campaigns',
      {
        name,
        campaign_type: this.campaignType,
        selection_criteria,
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.campaignBusy.set(false);
        this.campaignName = '';
        this.campaignStatus.set(
          targetKeys.length
            ? this.i18n.t('client360.toast.campaign_created', { count: targetKeys.length })
            : this.i18n.t('client360.toast.campaign_created_plain'),
        );
        this.clearCampaignTargeting();
        this.clearDirectorySelection();
        this.loadCampaigns(false);
        this.selectCampaign(payload.campaign);
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.campaignBusy.set(false);
        this.campaignStatus.set(this.i18n.t('client360.error.campaign_create'));
      },
    });
  }

  selectCampaign(campaign: Client360Campaign): void {
    this.selectedCampaign.set(campaign);
    this.campaignStats.set(null);
    this.loadCampaignStats(campaign);
  }

  loadCampaignStats(campaign: Client360Campaign): void {
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.get<Client360CampaignStatsResponse>(
      `/api/v1/client360/campaigns/${encodeURIComponent(campaign.id)}/stats`,
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.campaignStats.set(payload.stats);
        this.selectedCampaign.set(payload.campaign);
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.campaignStats.set(null);
      },
    });
  }

  generateCampaignDrafts(followUp: boolean): void {
    const campaign = this.selectedCampaign();
    if (!campaign || this.campaignBusy()) return;
    this.campaignBusy.set(true);
    this.campaignStatus.set(
      this.i18n.t(
        followUp ? 'client360.toast.preparing_followups' : 'client360.toast.generating_drafts',
      ),
    );
    const scope = this.workspace.captureRequestScope();
    const generation = this.workspaceActionGeneration;
    this.http.post<Client360CampaignDraftsResult>(
      `/api/v1/client360/campaigns/${encodeURIComponent(campaign.id)}/drafts`,
      {
        language: 'fr',
        include_prices: false,
        follow_up: followUp,
      },
      this.workspaceHttpOptions(scope),
    ).subscribe({
      next: (payload) => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.campaignBusy.set(false);
        const created = payload.created ?? 0;
        const prepared = payload.prepared ?? 0;
        const skipped = Object.entries(payload.skipped ?? {})
          .filter(([, count]) => (count ?? 0) > 0)
          .map(([reason, count]) => ({ reason, count: count ?? 0, label: this.labelSkipReason(reason) }))
          .sort((a, b) => b.count - a.count);
        const skippedTotal = skipped.reduce((sum, entry) => sum + entry.count, 0);
        this.campaignDraftsOutcome.set({
          campaignId: campaign.id,
          followUp,
          created,
          prepared,
          skippedTotal,
          skipped,
        });
        const head = followUp ? `${prepared} relance(s) preparee(s)` : `${created} brouillon(s) genere(s)`;
        this.campaignStatus.set(skippedTotal ? `${head} · ${skippedTotal} ignore(s)` : head);
        this.selectedCampaign.set(payload.campaign);
        this.loadCampaigns(false);
        this.loadCampaignStats(payload.campaign);
      },
      error: () => {
        if (!this.workspaceActionIsCurrent(scope, generation)) return;
        this.campaignBusy.set(false);
        this.campaignStatus.set(this.i18n.t('client360.error.generate_drafts'));
      },
    });
  }

  labelSkipReason(reason: string): string {
    // Keys mirror the API's skip-reason values; an unknown one shows raw.
    const key = `client360.skip.${reason}`;
    const label = this.i18n.t(key);
    return label === key ? reason : label;
  }

  campaignCriteriaChips(campaign: Client360Campaign): string[] {
    const criteria = campaign.selection_criteria ?? {};
    const chips: string[] = [];
    const customerKeys = Array.isArray(criteria['customer_keys'])
      ? (criteria['customer_keys'] as string[])
      : [];
    if (customerKeys.length) {
      chips.push(
        this.i18n.t('client360.campaign.criteria.selection', { count: customerKeys.length }),
      );
    }
    const dueWeeks = Number(criteria['due_within_weeks']);
    if (Number.isFinite(dueWeeks) && dueWeeks > 0) {
      chips.push(this.i18n.t('client360.chip.due_in_weeks', { count: dueWeeks }));
    }
    const criteriaKeys = [
      'status',
      'customer',
      'country',
      'hub',
      'technology',
      'part_family',
      'confidence',
      'limit',
    ];
    for (const key of criteriaKeys) {
      const value = criteria[key];
      if (value == null || value === '') continue;
      chips.push(`${this.i18n.t(`client360.campaign.criteria.${key}`)} : ${value}`);
    }
    return chips;
  }

  conversionProxyLabel(stats: Client360CampaignStats): string {
    const proxy = stats.conversion_proxy;
    if (proxy == null || Number.isNaN(proxy)) return '';
    const pct = Math.round(proxy * 1000) / 10;
    const sources: Record<string, string> = {
      observed_impacts: this.i18n.t('client360.impact.observed_rate'),
      contract_observed_conversion_weight: this.i18n.t('client360.impact.contract_weight'),
      explicit: this.i18n.t('client360.impact.explicit'),
    };
    const source = stats.conversion_proxy_source
      ? sources[stats.conversion_proxy_source] || stats.conversion_proxy_source
      : '';
    return source ? `${pct} % (${source})` : `${pct} %`;
  }

  labelCampaignType(value: string): string {
    const labels: Record<string, string> = {
      first_replacement: 'Premier remplacement',
      maintenance_education: 'Pedagogie maintenance',
      renewal: 'Renouvellement',
      cross_selling: 'Vente croisee',
      upselling: 'Montee en gamme',
      free: 'Libre',
    };
    return labels[value] || value;
  }

  labelCampaignStatus(value: string): string {
    const labels: Record<string, string> = {
      draft: 'Brouillon',
      in_review: 'En revue',
      active: 'Active',
      completed: 'Terminee',
      archived: 'Archivee',
    };
    return labels[value] || value;
  }

  formatQty(value: number | null | undefined): string {
    if (value == null || Number.isNaN(value)) return '-';
    return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(value);
  }

  formatCurrency(value: number | null | undefined, currency?: string | null): string {
    if (value == null || Number.isNaN(value)) return '-';
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: currency || 'EUR',
      maximumFractionDigits: 0,
    }).format(value);
  }

  pricingSourceLabel(value: string | null | undefined): string {
    const labels: Record<string, string> = {
      direct: 'Prix direct (historique client)',
      family_average: 'Moyenne famille',
      family_technology_average: 'Moyenne famille + technologie',
    };
    return value ? labels[value] || value : 'Prix non estimable';
  }

  formatWeeks(value: number | null | undefined): string {
    if (value == null) return 'A completer';
    return `${this.formatQty(value)} semaines`;
  }

  formatDate(value: string | null | undefined): string {
    if (!value) return 'A completer';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'A completer';
    return new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date);
  }

  formatDateTime(value: string | null | undefined): string {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    return new Intl.DateTimeFormat('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  }

  summaryModeLabel(summary: Client360AiSummary | null | undefined): string {
    return summary?.generation_mode === 'ai_assisted' ? 'IA assistee' : 'Template';
  }

  summaryModelLabel(summary: Client360AiSummary | null | undefined): string {
    if (summary?.generation_mode !== 'ai_assisted') {
      return summary?.fallback_reason
        ? this.i18n.t('client360.summary.fallback', { reason: summary.fallback_reason })
        : this.i18n.t('client360.summary.deterministic');
    }
    if (this.isDemoSafe()) return 'Redaction assistee — modele gere par le runtime';
    const model = summary?.model;
    return model ? `Genere via ${summary?.provider ? summary.provider + ':' : ''}${model}` : 'Genere par IA';
  }

  timelineKindLabel(kind: string): string {
    const labels: Record<string, string> = {
      opportunity_update: 'Opportunite',
      mail_draft: 'Brouillon',
      mail_sent: 'Mail envoye',
      impact_response: 'Reponse',
      impact_quote: 'Devis',
      impact_order: 'Commande',
      impact_lost: 'Perdu',
    };
    return labels[kind] || (kind.startsWith('impact_') ? 'Impact' : kind);
  }

  timelineKindClass(kind: string): string {
    if (kind === 'mail_sent') return 'is-sent';
    if (kind === 'impact_order') return 'is-won';
    if (kind === 'impact_lost') return 'is-lost';
    if (kind.startsWith('impact_')) return 'is-impact';
    if (kind.startsWith('mail')) return 'is-mail';
    return 'is-opportunity';
  }

  labelConfidence(value: string): string {
    return value === 'high' ? 'Haute' : value === 'medium' ? 'Moyenne' : 'Faible';
  }

  labelAlertSeverity(value: string): string {
    const labels: Record<string, string> = { high: 'Urgent', medium: 'A suivre', low: 'Info' };
    return labels[value] || value;
  }

  labelAlertType(value: string): string {
    const labels: Record<string, string> = {
      due_soon: 'Echeance',
      long_delivery: 'Delai long',
      draft_no_response: 'Relance',
      incomplete_data: 'Donnees',
    };
    return labels[value] || value;
  }

  labelStatus(value: string): string {
    const labels: Record<string, string> = {
      detected: 'Detectee',
      validated: 'Validee',
      draft_generated: 'Brouillon',
      sent: 'Envoye',
      responded: 'Reponse',
      quote_requested: 'Devis',
      won: 'Gagne',
      lost: 'Perdu',
      dismissed: 'Ecartee',
    };
    return labels[value] || value;
  }

  labelAction(value: string | null | undefined): string {
    const labels: Record<string, string> = {
      validate_pdr_mapping: 'Valider mapping',
      request_installed_base: 'Demander base installee',
      prepare_inspection_or_spa: 'Inspection / SPA',
      draft_expertise_email: 'Brouillon expertise',
      complete_sap_history: 'Completer SAP',
      review_with_sales: 'Revue commerciale',
    };
    return value ? labels[value] || value : '-';
  }

  labelMappingStatus(value: string): string {
    const labels: Record<string, string> = {
      candidate: 'Candidat',
      validated: 'Valide',
      rejected: 'Rejete',
      needs_review: 'A revoir',
    };
    return labels[value] || value;
  }

  labelGap(value: string): string {
    const labels: Record<string, string> = {
      installed_base_missing: 'Base installee manquante',
      periodicity_missing: 'Periodicite manquante',
      sap_sales_history_missing: 'Historique SAP manquant',
      recommended_quantity_missing: 'Quantite recommandee manquante',
      installed_quantity_missing: 'Quantite installee manquante',
      customer_location_missing: 'Pays / hub manquant',
      delivery_time_missing: 'Delai manquant',
    };
    return labels[value] || value;
  }

  labelSourceType(value: string, metadata?: Record<string, unknown> | null): string {
    if (value === 'other' && metadata?.['role'] === 'purchase_history') {
      return 'Achats Montbonnot';
    }
    const labels: Record<string, string> = {
      installed_base: 'Base installee',
      periodicity: 'Periodicite',
      sap_sales_history: 'Historique SAP',
      contact_hub: 'Contacts / hubs',
      market_signal: 'Signal marche',
      other: 'Autre',
    };
    return labels[value] || value;
  }

  draftGenerationMode(draft: Client360MailDraft | null): string {
    return String(draft?.metadata?.['generation_mode'] || 'deterministic_template');
  }

  draftGenerationLabel(draft: Client360MailDraft | null): string {
    return this.draftGenerationMode(draft) === 'ai_assisted' ? 'IA assistee' : 'Template';
  }

  draftGenerationModel(draft: Client360MailDraft | null): string {
    if (this.isDemoSafe()) return '';
    return String(draft?.metadata?.['llm_model'] || draft?.metadata?.['fallback_reason'] || '');
  }

  mailAiStatusLabel(): string {
    const ai = this.summary()?.positioning?.mail_ai;
    if (ai?.disabled_reason === 'resolution_deferred') return 'Resolution a la demande';
    if (!ai?.enabled) return 'Template';
    if (ai.configured) return 'IA active';
    return `Fallback ${ai.disabled_reason || 'non configure'}`;
  }

  mailAiModelLabel(): string {
    if (this.isDemoSafe()) return 'Runtime gere';
    const ai = this.summary()?.positioning?.mail_ai;
    if (!ai?.model) return '-';
    return ai.provider ? `${ai.provider}:${ai.model}` : ai.model;
  }

  mailAiRouteLabel(): string {
    if (this.isDemoSafe()) return 'Redaction assistee';
    return this.summary()?.positioning?.mail_ai?.route_id || 'client360_pdr_mail_writer';
  }

  mailAiSourceLabel(): string {
    if (this.isDemoSafe()) return 'Masquee demo-safe';
    const ai = this.summary()?.positioning?.mail_ai;
    return ai?.model_source || ai?.routing_source || '-';
  }

  smtpStatusLabel(): string {
    const settings = this.mailSettings();
    if (!settings) return this.i18n.t('client360.smtp.status.not_loaded');
    if (settings.configured) return this.i18n.t('client360.smtp.status.ready');
    if (!settings.enabled) return this.i18n.t('client360.smtp.status.disabled');
    return this.i18n.t('client360.smtp.status.incomplete');
  }

  smtpSourceLabel(): string {
    const source = this.mailSettings()?.source;
    if (!source) return this.i18n.t('client360.smtp.source.unloaded');
    return this.i18n.t(
      source.startsWith('workspace')
        ? 'client360.smtp.source.workspace'
        : 'client360.smtp.source.global',
    );
  }

  smtpStatusDetail(): string {
    const settings = this.mailSettings();
    if (!settings || settings.configured) return '';
    const reason = settings.disabled_reason || '';
    // The keys mirror the API's `disabled_reason` values, so the lookup is
    // direct; an unknown reason falls back to the generic wording.
    if (!reason) return this.i18n.t('client360.mail.incomplete_config');
    const key = `client360.smtp.reason.${reason}`;
    const label = this.i18n.t(key);
    return label === key ? this.i18n.t('client360.smtp.reason.generic', { reason }) : label;
  }

  smtpPasswordPlaceholder(): string {
    return this.mailSettings()?.password_configured ? 'Secret configure' : 'Mot de passe SMTP';
  }

  mailPromptSourceLabel(): string {
    const source = this.mailSettings()?.system_prompt_source;
    if (source === 'workspace') return 'Personnalise';
    if (source === 'default') return 'Defaut';
    return 'Non charge';
  }
}
