import { NgClass } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { WorkspaceService } from '@app/core/workspace.service';
import { GlyphComponent, PageFrameComponent } from '@app/shared/cockpit';

type ViewKey = 'opportunities' | 'customer' | 'data' | 'mapping' | 'mail' | 'campaigns' | 'chat';

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
  error?: string | null;
  metadata?: Record<string, unknown>;
}

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

@Component({
  selector: 'app-client360-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, NgClass, GlyphComponent, PageFrameComponent],
  template: `
    <ck-page-frame eyebrow="Andritz / Spare Parts" title="Client360 PDR" [hasActions]="true">
      <button actions type="button" class="icon-button" title="Rafraichir" (click)="refresh()">
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
        <div class="state-line"><ck-glyph name="pulse" [size]="14" color="currentColor" /> Chargement Client360 PDR</div>
      } @else if (error()) {
        <div class="state-line error"><ck-glyph name="warn" [size]="14" color="currentColor" /> {{ error() }}</div>
      }

      <section class="kpi-grid">
        <div class="ck-surface kpi">
          <span>Opportunites</span>
          <strong>{{ summary()?.summary?.opportunities ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>Clients</span>
          <strong>{{ summary()?.summary?.customers ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>Sources</span>
          <strong>{{ summary()?.summary?.data_sources ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>Ecart adressable</span>
          <strong>{{ formatQty(summary()?.summary?.potential_gap_qty) }}</strong>
        </div>
      </section>

      @if (view() === 'opportunities') {
        @if (alerts().length > 0) {
          <section class="ck-surface alerts-panel">
            <div class="alerts-head">
              <h3><ck-glyph name="warn" [size]="14" color="currentColor" /> Alertes ({{ alerts().length }})</h3>
              <div class="alerts-counts">
                @for (entry of alertCountEntries(); track entry.key) {
                  <span class="pill" [ngClass]="entry.key">{{ labelAlertType(entry.key) }} · {{ entry.value }}</span>
                }
              </div>
            </div>
            <ul class="alerts-list">
              @for (alert of alerts(); track alert.id) {
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
          </section>
        }
        <section class="ck-surface toolbar">
          <label>
            Client
            <input type="search" [(ngModel)]="filters.customer" (keyup.enter)="loadOpportunities()" placeholder="Nom client" />
          </label>
          <label>
            Pays
            <select [(ngModel)]="filters.country" (change)="loadOpportunities()">
              <option value="">Tous</option>
              @for (item of opportunitiesResponse()?.facets?.countries ?? []; track item) {
                <option [value]="item">{{ item }}</option>
              }
            </select>
          </label>
          <label>
            Famille
            <select [(ngModel)]="filters.part_family" (change)="loadOpportunities()">
              <option value="">Toutes</option>
              @for (item of opportunitiesResponse()?.facets?.part_families ?? []; track item) {
                <option [value]="item">{{ item }}</option>
              }
            </select>
          </label>
          <label>
            Confiance
            <select [(ngModel)]="filters.confidence" (change)="loadOpportunities()">
              <option value="">Toutes</option>
              <option value="high">Haute</option>
              <option value="medium">Moyenne</option>
              <option value="low">Faible</option>
            </select>
          </label>
          <label>
            Trier par
            <select [ngModel]="sortKey()" (ngModelChange)="sortKey.set($event)">
              <option value="score">Confiance</option>
              <option value="value">Valeur potentielle (EUR)</option>
            </select>
          </label>
          <button type="button" class="secondary" (click)="loadOpportunities()">
            <ck-glyph name="sliders" [size]="14" color="currentColor" /> Filtrer
          </button>
        </section>

        <section class="ck-surface table-wrap">
          @if (opportunities().length === 0) {
            <div class="empty">
              <ck-glyph name="ledger" [size]="18" color="currentColor" />
              <span>Aucune opportunite PDR calculee pour le moment.</span>
              <small>Les sources detectees et les gaps sont visibles dans l'onglet Donnees.</small>
            </div>
          } @else {
            <table>
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Piece / famille</th>
                  <th>Pays</th>
                  <th>Echeance</th>
                  <th>Potentiel</th>
                  <th>Achats connus</th>
                  <th>Ecart achats</th>
                  <th>Valeur potentielle</th>
                  <th>Confiance</th>
                  <th>Action</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                @for (opp of sortedOpportunities(); track opp.id) {
                  <tr (click)="selectOpportunity(opp)">
                    <td>
                      <strong>{{ opp.customer_name }}</strong>
                      <small>{{ opp.technology || opp.line_label || opp.machine_label || 'Perimetre a completer' }}</small>
                    </td>
                    <td>
                      <strong>{{ opp.part_family }}</strong>
                      <small>{{ opp.part_reference || opp.part_description || 'Reference a completer' }}</small>
                    </td>
                    <td>{{ opp.country || opp.hub || 'A completer' }}</td>
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
          }
        </section>
      }

      @if (view() === 'customer') {
        <section class="split">
          <aside class="ck-surface list-panel">
            @for (opp of opportunities(); track opp.id) {
              <button type="button" [ngClass]="{ active: selectedOpportunity()?.id === opp.id }" (click)="selectOpportunity(opp)">
                <strong>{{ opp.customer_name }}</strong>
                <span>{{ opp.part_family }}</span>
              </button>
            }
          </aside>
          <article class="ck-surface detail-panel">
            @if (selectedOpportunity()) {
              <div class="detail-head">
                <div>
                  <p class="ck-label c360-eyebrow">Fiche client PDR</p>
                  <h2>{{ selectedOpportunity()?.customer_name }}</h2>
                </div>
                <div class="detail-actions">
                  <div class="button-row">
                    <button type="button" class="secondary" (click)="updateOpportunityStatus(selectedOpportunity()!, 'validated')">
                      <ck-glyph name="check" [size]="14" color="currentColor" /> Valider
                    </button>
                    <button type="button" class="secondary" (click)="updateOpportunityStatus(selectedOpportunity()!, 'dismissed')">
                      <ck-glyph name="x" [size]="14" color="currentColor" /> Rejeter
                    </button>
                    <button
                      type="button"
                      class="primary"
                      [disabled]="isGeneratingDraft(selectedOpportunity())"
                      [attr.aria-busy]="isGeneratingDraft(selectedOpportunity())"
                      [ngClass]="{ 'is-loading': isGeneratingDraft(selectedOpportunity()) }"
                      (click)="generateDraft(selectedOpportunity()!)"
                    >
                      @if (isGeneratingDraft(selectedOpportunity())) {
                        <ck-glyph name="pulse" [size]="14" color="currentColor" /> Generation...
                      } @else {
                        <ck-glyph name="ledger" [size]="14" color="currentColor" /> Brouillon mail
                      }
                    </button>
                  </div>
                  @if (isGeneratingDraft(selectedOpportunity())) {
                    <div class="action-status" role="status" aria-live="polite">
                      <ck-glyph name="pulse" [size]="12" color="currentColor" />
                      Generation du brouillon IA en cours
                    </div>
                  }
                </div>
              </div>

              @if (selectedCustomer()?.ai_summary; as summaryAi) {
                <section class="c360-summary">
                  <div class="c360-summary-head">
                    <p class="ck-label c360-eyebrow">Resume IA</p>
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
              }

              <h3>Parc installe</h3>
              @if ((selectedCustomer()?.installed_base ?? []).length) {
                <div class="c360-tree">
                  @for (tech of selectedCustomer()?.installed_base ?? []; track tech.technology) {
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
                                <div class="c360-tree-part">
                                  <span class="c360-tree-part-label">{{ part.part_family }}<small>{{ part.part_reference ? ' · ' + part.part_reference : '' }}</small></span>
                                  <span class="c360-tree-part-meta">
                                    Ecart {{ formatQty(part.potential_gap_qty) }} · {{ formatCurrency(part.potential_gap_value, part.currency) }}
                                  </span>
                                </div>
                              }
                            </div>
                          }
                        </details>
                      }
                    </details>
                  }
                </div>
              } @else {
                <p class="hint">Aucun parc installe agrege pour ce client.</p>
              }

              <h3>Chronologie</h3>
              @if ((selectedCustomer()?.timeline ?? []).length) {
                <ol class="c360-timeline">
                  @for (event of selectedCustomer()?.timeline ?? []; track $index) {
                    <li [ngClass]="timelineKindClass(event.kind)">
                      <span class="c360-timeline-when">{{ formatDateTime(event.at) }}</span>
                      <span class="c360-timeline-kind">{{ timelineKindLabel(event.kind) }}</span>
                      <span class="c360-timeline-label">{{ event.label }}</span>
                    </li>
                  }
                </ol>
              } @else {
                <p class="hint">Aucun evenement chronologique enregistre.</p>
              }

              <h3>Detail opportunite selectionnee</h3>
              <dl class="facts">
                <div><dt>Pays / hub</dt><dd>{{ selectedOpportunity()?.country || selectedOpportunity()?.hub || 'A completer' }}</dd></div>
                <div><dt>Technologie</dt><dd>{{ selectedOpportunity()?.technology || 'A completer' }}</dd></div>
                <div><dt>Piece</dt><dd>{{ selectedOpportunity()?.part_family }}</dd></div>
                <div><dt>Periodicite</dt><dd>{{ formatWeeks(selectedOpportunity()?.periodicity_weeks) }}</dd></div>
                <div><dt>Quantite annuelle</dt><dd>{{ formatQty(selectedOpportunity()?.annual_theoretical_qty) }}</dd></div>
                <div><dt>Achats SAP connus</dt><dd>{{ formatQty(selectedOpportunity()?.sales_known_qty) }}</dd></div>
                <div><dt>Ecart vs achats</dt><dd>{{ formatQty(selectedOpportunity()?.potential_gap_qty) }}</dd></div>
                <div><dt>Valeur potentielle</dt><dd>{{ formatCurrency(selectedOpportunity()?.potential_gap_value, selectedOpportunity()?.currency) }}</dd></div>
                <div><dt>Adressable pondere</dt><dd>{{ formatQty(selectedOpportunity()?.potential_addressable) }}</dd></div>
                <div><dt>Delai</dt><dd>{{ formatWeeks(selectedOpportunity()?.delivery_time_weeks) }}</dd></div>
                <div><dt>Echeance</dt><dd>{{ formatDate(selectedOpportunity()?.next_due_at) }}</dd></div>
                <div><dt>Action</dt><dd>{{ labelAction(selectedOpportunity()?.recommended_action) }}</dd></div>
              </dl>
              <h3>Donnees manquantes</h3>
              <div class="chips">
                @for (gap of selectedOpportunity()?.data_gaps ?? []; track gap) {
                  <span>{{ labelGap(gap) }}</span>
                }
              </div>
              <h3>Raisons du score</h3>
              <div class="reason-list">
                @for (reason of selectedOpportunity()?.score_reasons ?? []; track reason.code) {
                  <span [ngClass]="{ met: reason.met }">{{ reason.label }}</span>
                }
              </div>
              @if (selectedOpportunity()?.metadata?.addressable_factors; as factors) {
                <h3>Valorisation et ponderation</h3>
                <dl class="facts">
                  <div>
                    <dt>Prix unitaire estime</dt>
                    <dd>
                      {{ formatCurrency(selectedOpportunity()?.metadata?.pricing?.unit_price, selectedOpportunity()?.currency) }}
                      <small>{{ pricingSourceLabel(selectedOpportunity()?.metadata?.pricing?.source) }}</small>
                    </dd>
                  </div>
                  <div><dt>Facteur adressable</dt><dd>{{ formatQty(factors.factor) }}</dd></div>
                  <div><dt>Hub connu</dt><dd>{{ factors.hub_present ? 'Oui' : 'Non' }}</dd></div>
                  <div><dt>Historique d'achat</dt><dd>{{ factors.existing_purchase_history ? 'Oui' : 'Non' }}</dd></div>
                  <div><dt>Taux de conversion observe</dt><dd>{{ formatQty(factors.observed_conversion_rate) }}</dd></div>
                </dl>
                <p class="hint">
                  Adressable pondere = ecart potentiel x facteur (base + hub + historique + taux de conversion observe).
                </p>
              }
              <h3>Signaux externes</h3>
              <div class="chips">
                @for (signal of selectedCustomer()?.market_signals ?? []; track signal.id) {
                  <span>{{ signal.label }}</span>
                }
                @if ((selectedCustomer()?.market_signals ?? []).length === 0) {
                  <span>Pas de signal externe rattache</span>
                }
              </div>
            } @else {
              <div class="empty"><span>Selectionner une opportunite.</span></div>
            }
          </article>
        </section>
      }

      @if (view() === 'data') {
        <section class="data-layout">
          <div class="ck-surface gap-panel">
            <div class="detail-head compact">
              <div>
                <p class="ck-label c360-eyebrow">Moteur donnees</p>
                <h2>Gaps metier</h2>
              </div>
              <button type="button" class="primary" (click)="runEngine(false)">
                <ck-glyph name="play" [size]="14" color="currentColor" /> Calculer
              </button>
            </div>
            <div class="chips">
              @for (gap of summary()?.data_gaps ?? []; track gap) {
                <span>{{ labelGap(gap) }}</span>
              }
              @if ((summary()?.data_gaps ?? []).length === 0) {
                <span class="ok">Sources minimales detectees</span>
              }
            </div>
            <div class="scope-panel">
              <h3>Scope MVP</h3>
              <p>{{ summary()?.positioning?.mvp_contract?.promise || 'Potentiel PDR explicable, validation humaine et boucle impact.' }}</p>
              <div class="chips">
                @for (segment of campaignSegments(); track segment.id) {
                  <span>{{ segment.label }}</span>
                }
              </div>
              <h3>Routage IA</h3>
              <dl class="engine-facts">
                <div><dt>Mode</dt><dd>{{ mailAiStatusLabel() }}</dd></div>
                <div><dt>Route</dt><dd>{{ mailAiRouteLabel() }}</dd></div>
                <div><dt>Runtime</dt><dd>{{ mailAiModelLabel() }}</dd></div>
                <div><dt>Source</dt><dd>{{ mailAiSourceLabel() }}</dd></div>
              </dl>
            </div>
            @if (engineResult()) {
              <dl class="engine-facts">
                <div><dt>Records lus</dt><dd>{{ engineResult()?.records_seen }}</dd></div>
                <div><dt>Opportunites</dt><dd>{{ engineResult()?.opportunities_detected }}</dd></div>
                <div><dt>Crees</dt><dd>{{ engineResult()?.created }}</dd></div>
                <div><dt>Maj</dt><dd>{{ engineResult()?.updated }}</dd></div>
                <div><dt>Mappings</dt><dd>{{ engineResult()?.candidate_mappings_created }}</dd></div>
              </dl>
            }
          </div>
          <div class="ck-surface table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Source</th>
                  <th>Collection</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                @for (source of summary()?.data_sources ?? []; track source.id) {
                  <tr>
                    <td>{{ labelSourceType(source.source_type) }}</td>
                    <td>
                      <strong>{{ source.label }}</strong>
                      <small>{{ source.origin }}</small>
                    </td>
                    <td>{{ source.collection_slug || '-' }}</td>
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
              <span>Aucun mapping SAP / famille PDR pour le moment.</span>
              <small>Lancer le moteur depuis Donnees cree les candidats detectables.</small>
            </div>
          } @else {
            <table>
              <thead>
                <tr>
                  <th>SAP / source</th>
                  <th>Famille PDR</th>
                  <th>Technologie</th>
                  <th>Periodicite</th>
                  <th>Statut</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (mapping of mappings(); track mapping.id) {
                  <tr>
                    <td>
                      <strong>{{ mapping.source_part_reference || mapping.source_part_family || mapping.source_part_label || '-' }}</strong>
                      <small>{{ mapping.notes || 'Mapping semi-manuel' }}</small>
                    </td>
                    <td>{{ mapping.pdr_family }}</td>
                    <td>{{ mapping.technology || '-' }}</td>
                    <td>{{ formatWeeks(mapping.periodicity_weeks) }}</td>
                    <td><span class="status">{{ labelMappingStatus(mapping.status) }}</span></td>
                    <td>
                      @if (mapping.status !== 'validated') {
                        <button type="button" class="secondary" (click)="validateMapping(mapping)">
                          <ck-glyph name="check" [size]="14" color="currentColor" /> Valider
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
                <p class="ck-label c360-eyebrow">Mail & suivi</p>
                <h2>{{ currentDraft()?.subject || 'Aucun brouillon selectionne' }}</h2>
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
                Destinataire
                <input type="email" [(ngModel)]="recipientEmail" placeholder="contact@client.com" />
              </label>
              <label>
                Sujet
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
                  <ck-glyph name="pulse" [size]="14" color="currentColor" /> Envoi SMTP...
                } @else {
                  <ck-glyph name="arrow-up" [size]="14" color="currentColor" /> Envoyer via SMTP
                }
              </button>
              @if (currentDraft()?.action_item_id) {
                <button type="button" class="secondary" (click)="markSent()" [disabled]="isSendingMail()">
                  <ck-glyph name="check" [size]="14" color="currentColor" /> Tracer envoye
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
          </div>
          <aside class="side-stack">
            <section class="ck-surface impact-panel">
              <h3>Suivi commercial</h3>
              <label>
                Attribution a cette campagne
                <select [(ngModel)]="impactAttribution">
                  <option value="direct">Directe</option>
                  <option value="probable">Probable</option>
                  <option value="unknown">A qualifier</option>
                  <option value="none">Non liee</option>
                </select>
              </label>
              <label>
                Motif
                <select [(ngModel)]="impactReason">
                  <option value="unknown">A qualifier</option>
                  <option value="price">Prix</option>
                  <option value="competitor">Concurrent</option>
                  <option value="no_need">Pas besoin</option>
                  <option value="wrong_contact">Mauvais contact</option>
                  <option value="timing">Timing</option>
                  <option value="hub">Hub</option>
                  <option value="technical_mismatch">Ecart technique</option>
                  <option value="bad_data">Donnee incorrecte</option>
                  <option value="other">Autre</option>
                </select>
              </label>
              <label>
                Commentaire retour client
                <textarea class="small-textarea" [(ngModel)]="impactSummary"></textarea>
              </label>
              <div class="impact-buttons">
                <button type="button" (click)="recordImpact('response')">Reponse recue</button>
                <button type="button" (click)="recordImpact('quote')">Devis demande</button>
                <button type="button" (click)="recordImpact('order')">Commande</button>
                <button type="button" (click)="recordImpact('lost')">Perdu</button>
              </div>
            </section>

            <section class="ck-surface smtp-panel">
              <div class="panel-head">
                <h3>SMTP workspace</h3>
                <span class="status" [ngClass]="{ ok: mailSettings()?.configured }">{{ smtpStatusLabel() }}</span>
              </div>
              <label>
                Host
                <input type="text" [(ngModel)]="smtpHost" />
              </label>
              <div class="settings-grid">
                <label>
                  Port
                  <input type="number" [(ngModel)]="smtpPort" />
                </label>
                <label>
                  User
                  <input type="text" [(ngModel)]="smtpUsername" />
                </label>
              </div>
              <label>
                Password
                <input type="password" [(ngModel)]="smtpPassword" [placeholder]="smtpPasswordPlaceholder()" />
              </label>
              <div class="settings-grid">
                <label>
                  From
                  <input type="email" [(ngModel)]="smtpFromEmail" />
                </label>
                <label>
                  Nom expediteur
                  <input type="text" [(ngModel)]="smtpFromName" />
                </label>
              </div>
              <div class="toggle-row">
                <label class="checkline"><input type="checkbox" [(ngModel)]="smtpEnabled" /> Actif</label>
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
                  <ck-glyph name="pulse" [size]="14" color="currentColor" /> Enregistrement...
                } @else {
                  <ck-glyph name="check" [size]="14" color="currentColor" /> Enregistrer SMTP
                }
              </button>
            </section>
          </aside>
        </section>
      }

      @if (view() === 'campaigns') {
        <section class="split">
          <div class="ck-surface list-panel">
            <div class="panel-head">
              <h3>Campagnes</h3>
              <span class="muted">{{ campaigns().length }}</span>
            </div>
            <div class="campaign-form">
              <label>
                Nom
                <input type="text" [(ngModel)]="campaignName" placeholder="Nom de campagne" />
              </label>
              <label>
                Type
                <select [(ngModel)]="campaignType">
                  <option value="first_replacement">Premier remplacement</option>
                  <option value="maintenance_education">Pedagogie maintenance</option>
                  <option value="renewal">Renouvellement</option>
                  <option value="cross_selling">Vente croisee</option>
                  <option value="upselling">Montee en gamme</option>
                  <option value="free">Libre</option>
                </select>
              </label>
              <div class="settings-grid">
                <label>
                  Pays
                  <input type="text" [(ngModel)]="campaignCriteria.country" placeholder="Tous" />
                </label>
                <label>
                  Technologie
                  <input type="text" [(ngModel)]="campaignCriteria.technology" placeholder="Toutes" />
                </label>
              </div>
              <div class="settings-grid">
                <label>
                  Famille
                  <input type="text" [(ngModel)]="campaignCriteria.part_family" placeholder="Toutes" />
                </label>
                <label>
                  Confiance
                  <select [(ngModel)]="campaignCriteria.confidence">
                    <option value="">Toutes</option>
                    <option value="high">Haute</option>
                    <option value="medium">Moyenne</option>
                    <option value="low">Faible</option>
                  </select>
                </label>
              </div>
              <button type="button" class="primary" [disabled]="campaignBusy()" (click)="createCampaign()">
                <ck-glyph name="ledger" [size]="14" color="currentColor" /> Creer depuis les filtres
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
                <li class="muted">Aucune campagne. Creez-en une depuis les filtres.</li>
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
              @if (campaignStats(); as stats) {
                <section class="kpi-grid campaign-kpis">
                  <div class="ck-surface kpi"><span>CA potentiel</span><strong>{{ formatCurrency(stats.potential_gap_value, stats.currency) }}</strong></div>
                  <div class="ck-surface kpi"><span>Clients cibles</span><strong>{{ stats.targeted_customers }}</strong></div>
                  <div class="ck-surface kpi"><span>Brouillons</span><strong>{{ stats.drafts }}</strong></div>
                  <div class="ck-surface kpi"><span>Envoyes</span><strong>{{ stats.sent }}</strong></div>
                  <div class="ck-surface kpi"><span>Reponses</span><strong>{{ stats.responses }}</strong></div>
                  <div class="ck-surface kpi"><span>Devis</span><strong>{{ stats.quotes }}</strong></div>
                  <div class="ck-surface kpi"><span>Commandes</span><strong>{{ stats.orders }}</strong></div>
                  <div class="ck-surface kpi"><span>CA gagne</span><strong>{{ formatCurrency(stats.won_value, stats.currency) }}</strong></div>
                </section>
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
    tbody tr:hover { background: rgba(255, 255, 255, .035); }
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
    .list-panel, .detail-panel, .gap-panel, .impact-panel, .smtp-panel { border-radius: var(--ck-radius-md); padding: 12px; }
    .list-panel { display: flex; flex-direction: column; gap: 6px; overflow: auto; }
    .list-panel button { text-align: left; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); color: var(--ck-fg-2); padding: 10px; cursor: pointer; }
    .list-panel button.active { border-color: rgba(103, 213, 246, .42); color: var(--ck-signal-cool); }
    .list-panel span { display: block; margin-top: 4px; color: var(--ck-fg-4); font-size: 11px; }
    .detail-head { display: flex; justify-content: space-between; gap: 12px; align-items: start; margin-bottom: 14px; }
    .detail-head.compact { margin-bottom: 10px; }
    .draft-meta { display: flex; align-items: center; gap: 8px; margin-top: 8px; color: var(--ck-fg-4); font-size: 11px; }
    .draft-meta .pill.ai_assisted { color: var(--ck-signal-cool); border-color: rgba(103, 213, 246, .42); }
    .c360-summary { border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); padding: 12px; margin-bottom: 14px; }
    .c360-summary-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
    .c360-summary .pill.ai_assisted { color: var(--ck-signal-cool); border-color: rgba(103, 213, 246, .42); }
    .c360-summary-text { margin: 0 0 8px; color: var(--ck-fg-2); line-height: 1.55; }
    .c360-tree { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
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
    .reason-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .reason-list span { border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); color: var(--ck-fg-4); padding: 4px 8px; font-size: 11px; }
    .reason-list span.met { color: var(--ck-signal-pos); border-color: rgba(16,185,129,.35); }
    .impact-panel, .smtp-panel { display: flex; flex-direction: column; gap: 12px; }
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
export class Client360PageComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);
  readonly view = signal<ViewKey>('opportunities');
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly summary = signal<Client360Summary | null>(null);
  readonly opportunitiesResponse = signal<Client360OpportunitiesResponse | null>(null);
  readonly selectedOpportunity = signal<Client360Opportunity | null>(null);
  readonly selectedCustomer = signal<Client360CustomerResponse | null>(null);
  readonly currentDraft = signal<Client360MailDraft | null>(null);
  readonly draftBody = signal('');
  readonly draftSubject = signal('');
  readonly alertsResponse = signal<Client360AlertsResponse | null>(null);
  readonly mappingsResponse = signal<Client360MappingsResponse | null>(null);
  readonly engineResult = signal<Client360EngineResult | null>(null);
  readonly mailAiResolved = signal(false);
  readonly generatingDraftOpportunityId = signal<string | null>(null);
  readonly sendingMailDraftId = signal<string | null>(null);
  readonly savingMailSettings = signal(false);
  readonly mailSettings = signal<Client360MailSettings | null>(null);
  readonly mailStatus = signal<string | null>(null);
  readonly campaignsResponse = signal<Client360CampaignsResponse | null>(null);
  readonly selectedCampaign = signal<Client360Campaign | null>(null);
  readonly campaignStats = signal<Client360CampaignStats | null>(null);
  readonly campaignStatus = signal<string | null>(null);
  readonly campaignBusy = signal(false);
  readonly chatMessages = signal<Array<{ role: 'user' | 'assistant'; content: string; sources?: string[] }>>([]);
  readonly chatBusy = signal(false);
  readonly chatError = signal<string | null>(null);
  chatInput = '';

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

  impactAttribution = 'unknown';
  impactReason = 'unknown';
  impactSummary = '';

  campaignName = '';
  campaignType = 'first_replacement';
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
    { id: 'opportunities', label: 'Opportunites' },
    { id: 'customer', label: 'Client' },
    { id: 'data', label: 'Donnees' },
    { id: 'mapping', label: 'Mapping' },
    { id: 'mail', label: 'Mail & suivi' },
    { id: 'campaigns', label: 'Campagnes' },
    { id: 'chat', label: 'Assistant' },
  ];

  readonly opportunities = computed(() => this.opportunitiesResponse()?.items ?? []);
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
  readonly alertCountEntries = computed(() =>
    Object.entries(this.alertsResponse()?.counts?.by_type ?? {}).map(([key, value]) => ({ key, value })),
  );
  readonly campaigns = computed(() => this.campaignsResponse()?.items ?? []);
  readonly campaignSegments = computed(() => this.summary()?.positioning?.mvp_contract?.campaign_segments ?? []);
  readonly isDemoSafe = computed(() => this.workspace.isDemoSafeMode());

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    this.mailStatus.set(null);
    this.mailAiResolved.set(false);
    this.loadSummary(false);
    this.loadMailSettings(false);
    this.loadMappings(false);
    this.loadOpportunities(false);
    this.loadAlerts();
  }

  loadAlerts(): void {
    this.http.get<Client360AlertsResponse>('/api/v1/client360/alerts').subscribe({
      next: (payload) => this.alertsResponse.set(payload),
      error: () => this.alertsResponse.set(null),
    });
  }

  openAlert(alert: Client360Alert): void {
    if (!alert.opportunity_id) return;
    const opp = this.opportunities().find((item) => item.id === alert.opportunity_id);
    if (opp) this.selectOpportunity(opp);
  }

  openTab(tab: ViewKey): void {
    this.view.set(tab);
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

  sendChatMessage(): void {
    const query = this.chatInput.trim();
    if (!query || this.chatBusy()) return;
    this.chatError.set(null);
    this.chatMessages.update((msgs) => [...msgs, { role: 'user', content: query }]);
    this.chatInput = '';
    this.chatBusy.set(true);
    this.http.post<Client360ChatResponse>('/api/v1/client360/chat', { query }).subscribe({
      next: (payload) => {
        const sources = (payload.sources ?? [])
          .map((src) => src?.source_label || src?.title)
          .filter((label): label is string => !!label);
        this.chatMessages.update((msgs) => [
          ...msgs,
          { role: 'assistant', content: payload.content || 'Aucune reponse.', sources },
        ]);
        this.chatBusy.set(false);
      },
      error: (err) => {
        const detail = err?.error?.detail;
        this.chatError.set(typeof detail === 'string' ? detail : 'Assistant Client360 indisponible.');
        this.chatBusy.set(false);
      },
    });
  }

  loadSummary(includeMailAi = false): void {
    const params = new HttpParams()
      .set('include_mail_ai', includeMailAi ? 'true' : 'false')
      .set('include_workspace_candidates', 'false');
    this.http.get<Client360Summary>('/api/v1/client360/summary', { params }).subscribe({
      next: (payload) => {
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
        if (includeMailAi) {
          this.error.set('Routage IA Client360 PDR indisponible');
        } else if (!this.opportunitiesResponse()) {
          this.error.set('Client360 PDR indisponible');
        }
      },
    });
  }

  loadMappings(showLoading = true): void {
    if (showLoading) this.loading.set(true);
    this.http.get<Client360MappingsResponse>('/api/v1/client360/mappings').subscribe({
      next: (payload) => {
        this.mappingsResponse.set(payload);
        if (showLoading) this.loading.set(false);
      },
      error: () => {
        if (showLoading) this.loading.set(false);
        this.error.set('Impossible de charger les mappings Client360 PDR');
      },
    });
  }

  loadMailSettings(showStatus = false): void {
    this.http.get<MailSettingsResponse>('/api/v1/client360/mail-settings').subscribe({
      next: (payload) => {
        this.mailSettings.set(payload.mail_settings);
        this.applyMailSettings(payload.mail_settings);
        if (showStatus) this.mailStatus.set('Parametres SMTP charges');
      },
      error: () => {
        if (showStatus) this.mailStatus.set('Parametres SMTP indisponibles');
      },
    });
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
    this.http.patch<MailSettingsResponse>('/api/v1/client360/mail-settings', payload).subscribe({
      next: (response) => {
        this.mailSettings.set(response.mail_settings);
        this.applyMailSettings(response.mail_settings);
        this.savingMailSettings.set(false);
        this.mailStatus.set(response.mail_settings.configured ? 'SMTP workspace pret' : 'SMTP workspace incomplet');
      },
      error: () => {
        this.savingMailSettings.set(false);
        this.mailStatus.set("Impossible d'enregistrer le SMTP");
      },
    });
  }

  runEngine(dryRun: boolean): void {
    this.loading.set(true);
    this.error.set(null);
    this.http.post<Client360EngineResult>('/api/v1/client360/engines/opportunities/run', { dry_run: dryRun }).subscribe({
      next: (payload) => {
        this.engineResult.set(payload);
        this.loading.set(false);
        this.refresh();
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Impossible de lancer le moteur Client360 PDR');
      },
    });
  }

  validateMapping(mapping: Client360MappingRule): void {
    this.http.patch<{ mapping: Client360MappingRule }>(`/api/v1/client360/mappings/${encodeURIComponent(mapping.id)}`, {
      status: 'validated',
      confidence: Math.max(mapping.confidence || 0, 0.75),
    }).subscribe({
      next: () => {
        this.loadMappings(false);
        this.runEngine(false);
      },
      error: () => this.error.set('Impossible de valider le mapping'),
    });
  }

  updateOpportunityStatus(opp: Client360Opportunity, status: 'validated' | 'dismissed'): void {
    this.http.patch<{ opportunity: Client360Opportunity }>(`/api/v1/client360/opportunities/${encodeURIComponent(opp.id)}`, {
      status,
      validation_reason: status === 'validated' ? 'sales_review' : undefined,
      rejection_reason: status === 'dismissed' ? 'sales_rejected' : undefined,
    }).subscribe({
      next: (payload) => {
        this.selectedOpportunity.set(payload.opportunity);
        this.loadOpportunities(false);
      },
      error: () => this.error.set('Impossible de qualifier opportunite'),
    });
  }

  loadOpportunities(showLoading = true): void {
    if (showLoading) this.loading.set(true);
    let params = new HttpParams().set('limit', '200');
    for (const [key, value] of Object.entries(this.filters)) {
      if (value) params = params.set(key, value);
    }
    this.http.get<Client360OpportunitiesResponse>('/api/v1/client360/opportunities', { params }).subscribe({
      next: (payload) => {
        this.opportunitiesResponse.set(payload);
        if (!this.selectedOpportunity() && payload.items.length) {
          this.selectedOpportunity.set(payload.items[0]);
        }
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Impossible de charger les opportunites Client360 PDR');
      },
    });
  }

  selectOpportunity(opp: Client360Opportunity): void {
    this.selectedOpportunity.set(opp);
    this.view.set('customer');
    this.http.get<Client360CustomerResponse>(`/api/v1/client360/customers/${encodeURIComponent(opp.customer_key)}`).subscribe({
      next: (payload) => this.selectedCustomer.set(payload),
      error: () => this.selectedCustomer.set(null),
    });
  }

  generateDraft(opp: Client360Opportunity): void {
    if (this.generatingDraftOpportunityId()) return;
    this.loading.set(true);
    this.error.set(null);
    this.generatingDraftOpportunityId.set(opp.id);
    this.http.post<MailDraftResponse>('/api/v1/client360/mail-drafts', {
      opportunity_id: opp.id,
      language: 'fr',
      include_prices: false,
    }).subscribe({
      next: (payload) => {
        this.currentDraft.set(payload.mail_draft);
        this.draftSubject.set(payload.mail_draft.subject);
        this.draftBody.set(payload.mail_draft.generated_body);
        this.mailStatus.set(null);
        this.view.set('mail');
        this.loading.set(false);
        this.generatingDraftOpportunityId.set(null);
        this.loadOpportunities(false);
      },
      error: () => {
        this.loading.set(false);
        this.generatingDraftOpportunityId.set(null);
        this.error.set('Impossible de generer le brouillon');
      },
    });
  }

  isGeneratingDraft(opp: Client360Opportunity | null | undefined): boolean {
    return Boolean(opp?.id && this.generatingDraftOpportunityId() === opp.id);
  }

  markSent(): void {
    const draft = this.currentDraft();
    if (!draft?.action_item_id) return;
    this.http.patch<ActionResponse>(`/api/v1/client360/actions/${encodeURIComponent(draft.action_item_id)}`, {
      mail_draft_id: draft.id,
      mail_status: 'sent',
      status: 'in_progress',
      sent_body: this.draftBody(),
      sent_at: new Date().toISOString(),
    }).subscribe({
      next: () => {
        this.currentDraft.set({ ...draft, subject: this.draftSubject(), status: 'sent', sent_body: this.draftBody(), sent_at: new Date().toISOString() });
        this.mailStatus.set('Envoi manuel trace');
        this.loadOpportunities(false);
      },
      error: () => this.error.set('Impossible de mettre a jour le suivi mail'),
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
    this.http.post<MailSendResponse>(`/api/v1/client360/mail-drafts/${encodeURIComponent(draft.id)}/send`, {
      to_email: this.recipientEmail.trim(),
      subject: this.draftSubject(),
      body: this.draftBody(),
    }).subscribe({
      next: (payload) => {
        this.currentDraft.set(payload.mail_draft);
        this.draftSubject.set(payload.mail_draft.subject);
        this.draftBody.set(payload.mail_draft.sent_body || payload.mail_draft.generated_body);
        this.sendingMailDraftId.set(null);
        this.mailStatus.set('Mail envoye via SMTP');
        this.loadOpportunities(false);
      },
      error: () => {
        this.sendingMailDraftId.set(null);
        this.mailStatus.set('Echec envoi SMTP');
      },
    });
  }

  recordImpact(type: string): void {
    const draft = this.currentDraft();
    if (!draft?.action_item_id) return;
    this.http.post<ImpactResponse>(`/api/v1/client360/actions/${encodeURIComponent(draft.action_item_id)}/impact`, {
      impact_type: type,
      attribution: this.impactAttribution,
      reason: this.impactReason,
      summary: this.impactSummary,
      opportunity_id: draft.opportunity_id,
      mail_draft_id: draft.id,
    }).subscribe({
      next: () => {
        this.refresh();
      },
      error: () => this.error.set('Impossible de qualifier impact'),
    });
  }

  loadCampaigns(showLoading = false): void {
    if (showLoading) this.loading.set(true);
    this.http.get<Client360CampaignsResponse>('/api/v1/client360/campaigns').subscribe({
      next: (payload) => {
        this.campaignsResponse.set(payload);
        if (showLoading) this.loading.set(false);
      },
      error: () => {
        if (showLoading) this.loading.set(false);
        this.error.set('Impossible de charger les campagnes Client360 PDR');
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
    const selection_criteria: Record<string, string> = {};
    for (const [key, value] of Object.entries(this.campaignCriteria)) {
      if (value) selection_criteria[key] = value;
    }
    this.campaignBusy.set(true);
    this.campaignStatus.set('Creation de la campagne...');
    this.http.post<Client360CampaignResponse>('/api/v1/client360/campaigns', {
      name,
      campaign_type: this.campaignType,
      selection_criteria,
    }).subscribe({
      next: (payload) => {
        this.campaignBusy.set(false);
        this.campaignName = '';
        this.campaignStatus.set('Campagne creee');
        this.loadCampaigns(false);
        this.selectCampaign(payload.campaign);
      },
      error: () => {
        this.campaignBusy.set(false);
        this.campaignStatus.set('Impossible de creer la campagne');
      },
    });
  }

  selectCampaign(campaign: Client360Campaign): void {
    this.selectedCampaign.set(campaign);
    this.campaignStats.set(null);
    this.loadCampaignStats(campaign);
  }

  loadCampaignStats(campaign: Client360Campaign): void {
    this.http.get<Client360CampaignStatsResponse>(`/api/v1/client360/campaigns/${encodeURIComponent(campaign.id)}/stats`).subscribe({
      next: (payload) => {
        this.campaignStats.set(payload.stats);
        this.selectedCampaign.set(payload.campaign);
      },
      error: () => this.campaignStats.set(null),
    });
  }

  generateCampaignDrafts(followUp: boolean): void {
    const campaign = this.selectedCampaign();
    if (!campaign || this.campaignBusy()) return;
    this.campaignBusy.set(true);
    this.campaignStatus.set(followUp ? 'Preparation des relances...' : 'Generation des brouillons...');
    this.http.post<Client360CampaignDraftsResult>(`/api/v1/client360/campaigns/${encodeURIComponent(campaign.id)}/drafts`, {
      language: 'fr',
      include_prices: false,
      follow_up: followUp,
    }).subscribe({
      next: (payload) => {
        this.campaignBusy.set(false);
        const count = followUp ? (payload.prepared ?? 0) : (payload.created ?? 0);
        this.campaignStatus.set(followUp ? `${count} relance(s) preparee(s)` : `${count} brouillon(s) genere(s)`);
        this.selectedCampaign.set(payload.campaign);
        this.loadCampaigns(false);
        this.loadCampaignStats(payload.campaign);
      },
      error: () => {
        this.campaignBusy.set(false);
        this.campaignStatus.set('Impossible de generer les brouillons');
      },
    });
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
      return summary?.fallback_reason ? `Fallback deterministe (${summary.fallback_reason})` : 'Resume deterministe a partir des agregats';
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

  labelSourceType(value: string): string {
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
    if (!settings) return 'Non charge';
    if (settings.configured) return 'Pret';
    if (!settings.enabled) return 'Desactive';
    return 'Incomplet';
  }

  smtpPasswordPlaceholder(): string {
    return this.mailSettings()?.password_configured ? 'Secret configure' : 'Mot de passe SMTP';
  }
}
